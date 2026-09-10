#!/bin/bash
# ================================================================
# Test exhaustivo: fix de rules['CODE'].total -> result_rules['CODE']['total']
# en las 3 estructuras especiales de hr_payroll_structure_special_data.xml
# (Prima de Servicios, Liquidacion de Contrato, Bonificaciones), doc 14 SS6.
#
# rules['CODE'] es el REGISTRO hr.salary.rule (metadata, sin .total) -- el
# resultado ya calculado de una regla anterior en la misma corrida vive en
# result_rules['CODE']['total'] (dict). Bug preexistente en 16 lineas de
# hr_payroll_structure_special_data.xml (CO_PRIMA_BASE, CO_PRIMA_VALOR,
# CO_LIQ_CESANTIAS, CO_BON_VALOR), nunca ejercitado antes de este ciclo
# porque las 3 estructuras tenian 0 payslips reales en staging_produccion.
# Prerequisito para el diseno de migracion de liquidacion (doc 14).
#
# Mismas lecciones aprendidas de test_embargo.sh/test_certificado.sh/
# test_provisiones.sh:
# - odoo-bin se invoca directo, el wrapper() de pruebas hace cr.rollback()
#   defensivo en el except.
# - Aislar la variable bajo prueba forzando wage/integral_salary segun el
#   caso, restaurando en finally.
# - No se llama action_payslip_done() en ningun test de este archivo (no
#   hace falta contabilizar para verificar el fix) -- no aplica la leccion
#   del audit trail de test_provisiones.sh T7.
#
# NOTA: /tmp/ne_params.tar.gz debe estar actualizado con el diff de doc 14
# SS6 antes de correr este script.
# ================================================================
set -e

# Extraer modulo
cd /home/odoo/src/user/l10n_co_nomina_electronica
rm -rf models/ views/ data/ wizard/ services/ tests/ security/ report/ static/ __pycache__/
cd /home/odoo/src/user
tar xzf /tmp/ne_params.tar.gz -C l10n_co_nomina_electronica/

# Actualizar modulo
cd /home/odoo
odoo-bin -d guapante-staging-produccion-37396060 -u l10n_co_nomina_electronica --stop-after-init --no-http 2>&1 | tail -5

echo "========================================"
echo "  MODULO ACTUALIZADO - INICIANDO TESTS"
echo "========================================"

odoo-bin shell -d guapante-staging-produccion-37396060 --no-http <<'PYEOF'
from datetime import date

env = self.env
cr = env.cr
PASS = 0
FAIL = 0
results = []

def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        results.append(f"  [OK] {name}")
    except Exception as e:
        FAIL += 1
        results.append(f"  [FAIL] {name}: {e}")
        try:
            cr.rollback()
        except Exception:
            pass

company = env.user.company_id
struct_prima = env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_prima')
struct_liq = env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_liquidacion')
struct_bon = env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_bonificacion')
RuleParameter = env['hr.rule.parameter']

def get_param(code, date_value):
    return RuleParameter._get_parameter_from_code(code, date_value)

_REF_DATE = date.today()
_SMMLV = get_param('l10n_co_smmlv', _REF_DATE)

emp = env['hr.employee'].search([
    ('contract_ids.state', '=', 'open'),
    ('company_id', '=', company.id),
], limit=1)
if not emp:
    raise Exception("No hay empleados con contrato activo -- no se puede probar")
contract = emp.contract_ids.filtered(lambda c: c.state == 'open')[:1]

cat_prest = env.ref('l10n_co_nomina_electronica.hr_salary_rule_category_prestaciones')
cat_dev = env.ref('l10n_co_nomina_electronica.hr_salary_rule_category_devengados')
cat_dedu = env.ref('l10n_co_nomina_electronica.hr_salary_rule_category_deducciones')

def _is_descendant(cat, root_id):
    cur = cat
    while cur:
        if cur.id == root_id:
            return True
        cur = cur.parent_id
    return False

def _reconstruct_neto(ps, neto_code, *root_cats):
    """Reconstruye el NETO sumando independientemente las lineas cuyas
    categorias descienden de root_cats (excluyendo la propia linea de
    NETO por codigo, que si no queda incluida en su propia suma -- mismo
    patron que T6 de test_provisiones.sh). SS_EMP es hija de DEDU: no se
    lista aparte, ya queda cubierta caminando el arbol desde DEDU."""
    root_ids = [c.id for c in root_cats]
    lines = ps.line_ids.filtered(
        lambda l: l.code != neto_code and any(_is_descendant(l.category_id, rid) for rid in root_ids)
    )
    return sum(lines.mapped('total'))

def _make_payslip(struct, name):
    return env['hr.payslip'].create({
        'name': name,
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_from': _REF_DATE.replace(day=1),
        'date_to': _REF_DATE,
        'struct_id': struct.id,
    })

# ================================================================
# TEST 1: Prima de Servicios, empleado NO integral -- verifica que
# compute_sheet() ya NO revienta con AttributeError, y que
# BASE/VALOR/SALUD/PENSION/NETO calculan valores sanos.
# ================================================================
def t1():
    original_wage = contract.wage
    original_integral = contract.l10n_co_ne_integral_salary
    contract.write({'wage': _SMMLV * 1.5, 'l10n_co_ne_integral_salary': False})
    cr.commit()
    ps = _make_payslip(struct_prima, 'Test Prima No Integral')
    try:
        ps.compute_sheet()  # antes del fix: AttributeError en CO_PRIMA_VALOR
        base_line = ps.line_ids.filtered(lambda l: l.code == 'CO_PRIMA_BASE')
        valor_line = ps.line_ids.filtered(lambda l: l.code == 'CO_PRIMA_VALOR')
        salud_line = ps.line_ids.filtered(lambda l: l.code == 'CO_PRIMA_SALUD')
        pension_line = ps.line_ids.filtered(lambda l: l.code == 'CO_PRIMA_PENSION')
        neto_line = ps.line_ids.filtered(lambda l: l.code == 'CO_PRIMA_NETO')

        assert base_line and base_line.total > 0, "CO_PRIMA_BASE deberia ser > 0 para no integral"
        assert valor_line and valor_line.total > 0, "CO_PRIMA_VALOR deberia ser > 0"
        assert salud_line and salud_line.total < 0, "CO_PRIMA_SALUD deberia ser un descuento negativo"
        assert pension_line and pension_line.total < 0, "CO_PRIMA_PENSION deberia ser un descuento negativo"
        assert neto_line, "No se genero CO_PRIMA_NETO"
        # Reconstruccion independiente via categorias (PREST + DEDU), NO
        # una suma manual de VALOR+SALUD+PENSION -- SS_EMP es hija de DEDU,
        # sumarla aparte de la formula real duplicaba el descuento (bug
        # real encontrado por Tech Lead depurando un payslip real,
        # corregido en CO_PRIMA_NETO -- este assert verifica la formula
        # correcta, no la que tenia el bug).
        expected_neto = _reconstruct_neto(ps, 'CO_PRIMA_NETO', cat_prest, cat_dedu)
        assert abs(neto_line.total - expected_neto) < 0.01, \
            f"CO_PRIMA_NETO ({neto_line.total}) no coincide con PREST+DEDU reconstruido ({expected_neto})"
    finally:
        ps.write({'state': 'draft'})
        ps.unlink()
        contract.write({'wage': original_wage, 'l10n_co_ne_integral_salary': original_integral})
        cr.commit()
test("Prima de Servicios (no integral): compute_sheet() sin AttributeError, formulas sanas", t1)

# ================================================================
# TEST 2: Prima de Servicios, salario integral -- CO_PRIMA_BASE debe
# ser 0 (Art. 132 CST, "salario integral no genera prima") y las
# reglas dependientes (VALOR/SALUD/PENSION/RETE) NO deben generar
# linea -- confirma que la condicion corregida sigue suprimiendo
# correctamente, no solo que no revienta.
# ================================================================
def t2():
    original_wage = contract.wage
    original_integral = contract.l10n_co_ne_integral_salary
    contract.write({'wage': _SMMLV * 15, 'l10n_co_ne_integral_salary': True})
    cr.commit()
    ps = _make_payslip(struct_prima, 'Test Prima Integral')
    try:
        ps.compute_sheet()
        base_line = ps.line_ids.filtered(lambda l: l.code == 'CO_PRIMA_BASE')
        valor_line = ps.line_ids.filtered(lambda l: l.code == 'CO_PRIMA_VALOR')

        assert base_line and base_line.total == 0, \
            f"CO_PRIMA_BASE deberia ser 0 para salario integral, es {base_line.total if base_line else None}"
        assert not valor_line, "CO_PRIMA_VALOR no deberia generar linea para salario integral"
    finally:
        ps.write({'state': 'draft'})
        ps.unlink()
        contract.write({'wage': original_wage, 'l10n_co_ne_integral_salary': original_integral})
        cr.commit()
test("Prima de Servicios (integral): BASE=0 y VALOR suprimido correctamente", t2)

# ================================================================
# TEST 3: Liquidacion de Contrato, empleado NO integral -- verifica
# SALARIOS/PRIMA/CESANTIAS/INT_CES sin AttributeError (antes del fix,
# reventaba en CO_LIQ_INT_CES leyendo rules['CO_LIQ_CESANTIAS'].total).
# ================================================================
def t3():
    original_wage = contract.wage
    original_integral = contract.l10n_co_ne_integral_salary
    contract.write({'wage': _SMMLV * 1.5, 'l10n_co_ne_integral_salary': False})
    cr.commit()
    ps = _make_payslip(struct_liq, 'Test Liquidacion No Integral')
    try:
        ps.compute_sheet()  # antes del fix: AttributeError en CO_LIQ_INT_CES
        salarios_line = ps.line_ids.filtered(lambda l: l.code == 'CO_LIQ_SALARIOS')
        prima_line = ps.line_ids.filtered(lambda l: l.code == 'CO_LIQ_PRIMA')
        cesantias_line = ps.line_ids.filtered(lambda l: l.code == 'CO_LIQ_CESANTIAS')
        int_ces_line = ps.line_ids.filtered(lambda l: l.code == 'CO_LIQ_INT_CES')

        assert salarios_line and salarios_line.total > 0, "CO_LIQ_SALARIOS deberia ser > 0"
        assert prima_line and prima_line.total > 0, "CO_LIQ_PRIMA deberia ser > 0"
        assert cesantias_line and cesantias_line.total > 0, "CO_LIQ_CESANTIAS deberia ser > 0"
        assert int_ces_line and int_ces_line.total > 0, "CO_LIQ_INT_CES deberia ser > 0"
        # Intereses = ~12%/ano proporcional de las cesantias -- no es
        # exactamente proporcional (cada regla recalcula sus propios dias),
        # pero debe ser sustancialmente menor que la base de cesantias.
        assert int_ces_line.total < cesantias_line.total, \
            f"CO_LIQ_INT_CES ({int_ces_line.total}) deberia ser menor que CO_LIQ_CESANTIAS ({cesantias_line.total})"

        neto_line = ps.line_ids.filtered(lambda l: l.code == 'CO_LIQ_NETO')
        assert neto_line, "No se genero CO_LIQ_NETO"
        expected_neto = _reconstruct_neto(ps, 'CO_LIQ_NETO', cat_dev, cat_dedu)
        assert abs(neto_line.total - expected_neto) < 0.01, \
            f"CO_LIQ_NETO ({neto_line.total}) no coincide con DEV+DEDU reconstruido ({expected_neto})"
    finally:
        ps.write({'state': 'draft'})
        ps.unlink()
        contract.write({'wage': original_wage, 'l10n_co_ne_integral_salary': original_integral})
        cr.commit()
test("Liquidacion de Contrato (no integral): compute_sheet() sin AttributeError, formulas sanas", t3)

# ================================================================
# TEST 4: Liquidacion de Contrato, salario integral -- PRIMA/CESANTIAS
# /INT_CES no deben generar linea (condicion explicita
# "not contract.l10n_co_ne_integral_salary").
# ================================================================
def t4():
    original_wage = contract.wage
    original_integral = contract.l10n_co_ne_integral_salary
    contract.write({'wage': _SMMLV * 15, 'l10n_co_ne_integral_salary': True})
    cr.commit()
    ps = _make_payslip(struct_liq, 'Test Liquidacion Integral')
    try:
        ps.compute_sheet()
        prima_line = ps.line_ids.filtered(lambda l: l.code == 'CO_LIQ_PRIMA')
        cesantias_line = ps.line_ids.filtered(lambda l: l.code == 'CO_LIQ_CESANTIAS')
        int_ces_line = ps.line_ids.filtered(lambda l: l.code == 'CO_LIQ_INT_CES')

        assert not prima_line, "CO_LIQ_PRIMA no deberia generar linea para salario integral"
        assert not cesantias_line, "CO_LIQ_CESANTIAS no deberia generar linea para salario integral"
        assert not int_ces_line, "CO_LIQ_INT_CES no deberia generar linea para salario integral"
    finally:
        ps.write({'state': 'draft'})
        ps.unlink()
        contract.write({'wage': original_wage, 'l10n_co_ne_integral_salary': original_integral})
        cr.commit()
test("Liquidacion de Contrato (integral): PRIMA/CESANTIAS/INT_CES suprimidas correctamente", t4)

# ================================================================
# TEST 5: Bonificaciones Extraordinarias -- verifica VALOR/SALUD/
# PENSION/RETE sin AttributeError (antes del fix, reventaba en las
# 3 reglas que leen rules['CO_BON_VALOR'].total).
#
# hr.payslip.input.type con code='CO_BON_VALOR' NO existe en ningun
# data file del modulo -- CO_BON_VALOR es 100% input-driven
# (inputs.get('CO_BON_VALOR')), asi que sin ese input type nadie
# podria capturarlo desde la UI tampoco. Es el mismo patron de
# hallazgo que CO_EMBARGO en doc 16 (T8) -- una funcionalidad muerta
# preexistente, DISTINTA del bug rules[].total que corrige este
# archivo. No se corrige aqui (fuera de alcance de doc 14 SS6): se crea
# un input type temporal solo para esta prueba, para poder verificar
# el fix real (rules[].total) de forma aislada, y se borra en el
# finally. Reportar a Tech Lead como hallazgo aparte.
# ================================================================
def t5():
    original_wage = contract.wage
    original_integral = contract.l10n_co_ne_integral_salary
    contract.write({'wage': _SMMLV * 1.5, 'l10n_co_ne_integral_salary': False})
    cr.commit()

    InputType = env['hr.payslip.input.type']
    temp_input_type = InputType.create({
        'name': '[TEST] Valor Bonificacion (temporal, no existe en produccion)',
        'code': 'CO_BON_VALOR',
    })
    cr.commit()

    ps = _make_payslip(struct_bon, 'Test Bonificacion')
    try:
        ps.write({'input_line_ids': [(0, 0, {
            'input_type_id': temp_input_type.id,
            'amount': _SMMLV * 0.5,
        })]})
        ps.compute_sheet()  # antes del fix: AttributeError en CO_BON_SALUD/PENSION/RETE

        valor_line = ps.line_ids.filtered(lambda l: l.code == 'CO_BON_VALOR')
        salud_line = ps.line_ids.filtered(lambda l: l.code == 'CO_BON_SALUD')
        pension_line = ps.line_ids.filtered(lambda l: l.code == 'CO_BON_PENSION')

        assert valor_line and abs(valor_line.total - _SMMLV * 0.5) < 0.01, \
            "CO_BON_VALOR deberia reflejar el input capturado"
        assert salud_line and salud_line.total < 0, "CO_BON_SALUD deberia ser un descuento negativo"
        assert pension_line and pension_line.total < 0, "CO_BON_PENSION deberia ser un descuento negativo"

        neto_line = ps.line_ids.filtered(lambda l: l.code == 'CO_BON_NETO')
        assert neto_line, "No se genero CO_BON_NETO"
        expected_neto = _reconstruct_neto(ps, 'CO_BON_NETO', cat_dev, cat_dedu)
        assert abs(neto_line.total - expected_neto) < 0.01, \
            f"CO_BON_NETO ({neto_line.total}) no coincide con DEV+DEDU reconstruido ({expected_neto})"
    finally:
        ps.write({'state': 'draft'})
        ps.unlink()
        temp_input_type.unlink()
        contract.write({'wage': original_wage, 'l10n_co_ne_integral_salary': original_integral})
        cr.commit()
test("Bonificaciones (con input type temporal de prueba): compute_sheet() sin AttributeError", t5)

# ================================================================
# RESULTADOS
# ================================================================
print()
print("=" * 60)
for r in results:
    print(r)
print()
print(f"  TOTAL: {PASS} PASS, {FAIL} FAIL de {PASS+FAIL}")
print("=" * 60)

PYEOF
