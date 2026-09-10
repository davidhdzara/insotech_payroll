#!/bin/bash
# ================================================================
# Test exhaustivo: migracion de l10n.co.hr.liquidacion (modelo standalone)
# a hr.payslip con struct_id=hr_payroll_structure_co_liquidacion, doc 20
# (correcciones_normativas_2026/20_diseno_migracion_liquidacion.md).
#
# Cubre:
# - El wizard crea un hr.payslip real (no el modelo viejo, que ya no
#   existe) con los campos correctos, en borrador.
# - l10n_co_ne_liquidacion_cause (hr.payslip, doc 20 SS6) se guarda.
# - CO_LIQ_INDEMNIZ como hr.payslip.input.type (doc 20 SS4.4): el wizard
#   lo inyecta para contrato fijo/obra + causa "sin_justa_causa", con el
#   numero de dias restantes ingresado, y compute_sheet() calcula
#   CO_LIQ_INDEMNIZACION = valor_dia x dias_restantes (Art. 64 CST).
# - El modelo/vistas/menus viejos (l10n.co.hr.liquidacion) realmente
#   desaparecieron -- mismo patron T4 de test_config_settings.sh.
#
# Incluye tambien el fix del hallazgo encontrado escribiendo la primera
# version de este script: CO_LIQ_INDEMNIZACION.condition_python exigia
# inputs.get('CO_LIQ_INDEMNIZ').amount > 0 para TODO tipo de contrato,
# incluido indefinido -- pero la formula de la rama indefinido nunca lee
# ese valor (usa anos trabajados y salario). El disenio original
# dependia de que RRHH ingresara un valor dummy (1) en el input solo
# para activar la regla en indefinido (ver el note viejo de la regla,
# ya corregido). Aprobado por Tech Lead: condition_python ahora lee
# payslip.l10n_co_ne_liquidacion_cause == 'sin_justa_causa' directamente,
# sin depender de ningun input para indefinido -- T6 mas abajo prueba
# este caso.
#
# Mismas lecciones aprendidas de los scripts anteriores:
# - odoo-bin se invoca directo, el wrapper() de pruebas hace
#   cr.rollback() defensivo en el except.
# - Aislar la variable bajo prueba (l10n_co_ne_contract_type) restaurando
#   en finally, mismo patron que test_estructuras_especiales.sh con
#   wage/integral_salary.
#
# NOTA: /tmp/ne_params.tar.gz debe estar actualizado con el diff de
# doc 20 antes de correr este script.
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
Wizard = env['l10n.co.hr.liquidacion.wizard']
struct_liq = env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_liquidacion')
RuleParameter = env['hr.rule.parameter']

def get_param(code, date_value):
    return RuleParameter._get_parameter_from_code(code, date_value)

_REF_DATE_FOR_SMMLV = __import__('datetime').date.today()
_SMMLV = get_param('l10n_co_smmlv', _REF_DATE_FOR_SMMLV)

contract = env['hr.contract'].search([
    ('state', '=', 'open'),
    ('company_id.country_id.code', '=', 'CO'),
], limit=1)
if not contract:
    raise Exception("No hay contrato abierto CO -- no se puede probar")
emp = contract.employee_id

# ================================================================
# TEST 1: el wizard crea un hr.payslip real (no l10n.co.hr.liquidacion,
# que ya no existe) con los campos correctos, en borrador, causa != sin
# justa causa -- sin input CO_LIQ_INDEMNIZ.
# ================================================================
def t1():
    original_cause_field_exists = 'l10n_co_ne_liquidacion_cause' in env['hr.payslip']._fields
    assert original_cause_field_exists, "hr.payslip deberia tener l10n_co_ne_liquidacion_cause"

    wizard = Wizard.create({
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_end': contract.date_start,
        'cause': 'renuncia',
    })
    action = wizard.action_create_liquidacion()
    try:
        assert action['res_model'] == 'hr.payslip', \
            f"El wizard deberia abrir hr.payslip, abre {action['res_model']}"
        payslip = env['hr.payslip'].browse(action['res_id'])
        assert payslip.exists(), "El payslip creado por el wizard no existe"
        assert payslip.struct_id.id == struct_liq.id, \
            "El payslip deberia usar hr_payroll_structure_co_liquidacion"
        assert payslip.employee_id.id == emp.id
        assert payslip.contract_id.id == contract.id
        assert payslip.date_from == contract.date_start
        assert payslip.state == 'draft', \
            f"El payslip deberia quedar en borrador, esta en {payslip.state}"
        assert payslip.l10n_co_ne_liquidacion_cause == 'renuncia', \
            "La causa de retiro no se guardo en el payslip"
        assert not payslip.input_line_ids.filtered(lambda l: l.code == 'CO_LIQ_INDEMNIZ'), \
            "No deberia inyectarse CO_LIQ_INDEMNIZ para causa != sin_justa_causa"
    finally:
        env['hr.payslip'].browse(action['res_id']).unlink()
        cr.commit()
test("Wizard crea hr.payslip real (borrador, causa != sin_justa_causa, sin input indemnizacion)", t1)

# ================================================================
# TEST 2: contrato a termino FIJO + causa "sin_justa_causa" + dias
# restantes -- el wizard inyecta CO_LIQ_INDEMNIZ, y compute_sheet()
# calcula CO_LIQ_INDEMNIZACION = valor_dia x dias_restantes (Art. 64
# CST), la formula legalmente correcta que David confirmo adoptar
# (doc 20 SS4.2), no la aproximacion del legacy.
# ================================================================
def t2():
    original_type = contract.l10n_co_ne_contract_type
    contract.write({'l10n_co_ne_contract_type': '1'})  # fijo
    cr.commit()

    dias_restantes = 45
    wizard = Wizard.create({
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_end': contract.date_start,
        'cause': 'sin_justa_causa',
        'dias_restantes_contrato': dias_restantes,
    })
    assert wizard.requires_dias_restantes, \
        "requires_dias_restantes deberia ser True para contrato fijo"

    action = wizard.action_create_liquidacion()
    payslip = env['hr.payslip'].browse(action['res_id'])
    try:
        input_line = payslip.input_line_ids.filtered(lambda l: l.code == 'CO_LIQ_INDEMNIZ')
        assert input_line and input_line.amount == dias_restantes, \
            f"CO_LIQ_INDEMNIZ deberia inyectarse con amount={dias_restantes}"

        payslip.compute_sheet()
        indem_line = payslip.line_ids.filtered(lambda l: l.code == 'CO_LIQ_INDEMNIZACION')
        assert indem_line, "No se genero CO_LIQ_INDEMNIZACION (deberia, hay input > 0)"

        valor_dia = contract.wage / get_param('l10n_co_dias_mes_comercial', payslip.date_from)
        expected = valor_dia * dias_restantes
        assert abs(indem_line.total - expected) < 0.01, \
            f"CO_LIQ_INDEMNIZACION ({indem_line.total}) no coincide con valor_dia x dias_restantes ({expected})"
    finally:
        payslip.write({'state': 'draft'})
        payslip.unlink()
        contract.write({'l10n_co_ne_contract_type': original_type})
        cr.commit()
test("Contrato fijo + sin justa causa: CO_LIQ_INDEMNIZ inyectado, indemnizacion = valor_dia x dias_restantes", t2)

# ================================================================
# TEST 3: contrato por OBRA + causa "sin_justa_causa" -- misma formula
# que fijo (Art. 64 CST no distingue entre los dos para este calculo),
# confirma que el wizard trata '3' igual que '1'.
# ================================================================
def t3():
    original_type = contract.l10n_co_ne_contract_type
    contract.write({'l10n_co_ne_contract_type': '3'})  # obra
    cr.commit()

    wizard = Wizard.create({
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_end': contract.date_start,
        'cause': 'sin_justa_causa',
        'dias_restantes_contrato': 20,
    })
    assert wizard.requires_dias_restantes, \
        "requires_dias_restantes deberia ser True para contrato por obra"

    action = wizard.action_create_liquidacion()
    payslip = env['hr.payslip'].browse(action['res_id'])
    try:
        input_line = payslip.input_line_ids.filtered(lambda l: l.code == 'CO_LIQ_INDEMNIZ')
        assert input_line and input_line.amount == 20, \
            "CO_LIQ_INDEMNIZ deberia inyectarse con amount=20 para contrato por obra"
    finally:
        payslip.write({'state': 'draft'})
        payslip.unlink()
        contract.write({'l10n_co_ne_contract_type': original_type})
        cr.commit()
test("Contrato por obra + sin justa causa: CO_LIQ_INDEMNIZ inyectado igual que fijo", t3)

# ================================================================
# TEST 6: contrato INDEFINIDO + causa "sin_justa_causa" -- el fix de
# esta ronda (T4/T5 mas abajo mantienen su numeracion original). El
# wizard NO inyecta CO_LIQ_INDEMNIZ (requires_dias_restantes es False
# para indefinido), y aun asi CO_LIQ_INDEMNIZACION debe generar linea
# con la formula tiered del Art. 64 CST (condition_python ahora lee
# payslip.l10n_co_ne_liquidacion_cause directamente). Wage forzado a
# 5 SMMLV (< 10 SMMLV) para caer en la rama "30 dias primer ano + 20
# dias por ano adicional", la mas comun.
# ================================================================
def t6():
    original_type = contract.l10n_co_ne_contract_type
    original_wage = contract.wage
    contract.write({
        'l10n_co_ne_contract_type': '2',  # indefinido
        'wage': _SMMLV * 5,
    })
    cr.commit()

    wizard = Wizard.create({
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_end': contract.date_start,
        'cause': 'sin_justa_causa',
    })
    assert not wizard.requires_dias_restantes, \
        "requires_dias_restantes deberia ser False para contrato indefinido"

    action = wizard.action_create_liquidacion()
    payslip = env['hr.payslip'].browse(action['res_id'])
    try:
        assert not payslip.input_line_ids.filtered(lambda l: l.code == 'CO_LIQ_INDEMNIZ'), \
            "No deberia inyectarse CO_LIQ_INDEMNIZ para contrato indefinido"

        payslip.compute_sheet()
        indem_line = payslip.line_ids.filtered(lambda l: l.code == 'CO_LIQ_INDEMNIZACION')
        assert indem_line, \
            "No se genero CO_LIQ_INDEMNIZACION para indefinido + sin_justa_causa (deberia, fix de doc 20 SS9)"

        dias_mes = get_param('l10n_co_dias_mes_comercial', payslip.date_from)
        dias_anio = get_param('l10n_co_dias_anio_comercial', payslip.date_from)
        valor_dia = contract.wage / dias_mes
        dias_totales = (payslip.date_to - contract.date_start).days + 1
        anos = dias_totales / dias_anio
        # < 10 SMMLV: 30 dias primer ano + 20 dias por ano adicional
        expected = valor_dia * dias_mes
        if anos > 1:
            expected += valor_dia * 20 * (anos - 1)
        assert abs(indem_line.total - expected) < 0.01, \
            f"CO_LIQ_INDEMNIZACION ({indem_line.total}) no coincide con la formula tiered esperada ({expected})"
    finally:
        payslip.write({'state': 'draft'})
        payslip.unlink()
        contract.write({'l10n_co_ne_contract_type': original_type, 'wage': original_wage})
        cr.commit()
test("Contrato indefinido + sin justa causa: CO_LIQ_INDEMNIZACION calcula sin input (fix doc 20 SS9)", t6)

# ================================================================
# TEST 4: modelo/vistas/menus del l10n.co.hr.liquidacion viejo
# realmente desaparecieron -- mismo patron T4 de test_config_settings.sh.
# ================================================================
def t4():
    assert 'l10n.co.hr.liquidacion' not in env, \
        "l10n.co.hr.liquidacion deberia haber desaparecido del registro"

    for xmlid in (
        'l10n_co_nomina_electronica.view_l10n_co_hr_liquidacion_form',
        'l10n_co_nomina_electronica.view_l10n_co_hr_liquidacion_tree',
        'l10n_co_nomina_electronica.view_l10n_co_hr_liquidacion_search',
        'l10n_co_nomina_electronica.action_l10n_co_hr_liquidacion',
        'l10n_co_nomina_electronica.menu_l10n_co_liquidaciones_root',
        'l10n_co_nomina_electronica.menu_l10n_co_liquidaciones_list',
    ):
        cr.execute("""
            SELECT count(*) FROM ir_model_data
            WHERE module = %s AND name = %s
        """, tuple(xmlid.split('.', 1)))
        assert cr.fetchone()[0] == 0, f"{xmlid} deberia haberse eliminado (orphan cleanup)"

    cr.execute("""
        SELECT count(*) FROM ir_model_access
        WHERE name IN ('l10n_co_liquidacion manager', 'l10n_co_liquidacion user')
    """)
    assert cr.fetchone()[0] == 0, "Las 2 ACL de l10n.co.hr.liquidacion deberian haberse eliminado"
test("Modelo/vistas/menus/ACL viejos de l10n.co.hr.liquidacion realmente eliminados", t4)

# ================================================================
# TEST 5: el wizard (l10n.co.hr.liquidacion.wizard) y su input type
# CO_LIQ_INDEMNIZ siguen/quedan correctamente registrados.
# ================================================================
def t5():
    assert 'l10n.co.hr.liquidacion.wizard' in env, \
        "l10n.co.hr.liquidacion.wizard deberia seguir existiendo"

    input_type = env.ref('l10n_co_nomina_electronica.input_co_liq_indemniz')
    assert input_type.code == 'CO_LIQ_INDEMNIZ'
    assert input_type.country_id.code == 'CO'
    assert input_type.id in struct_liq.input_line_type_ids.ids, \
        "CO_LIQ_INDEMNIZ deberia estar en input_line_type_ids de la estructura de liquidacion"
test("Wizard e input type CO_LIQ_INDEMNIZ correctamente registrados", t5)

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
