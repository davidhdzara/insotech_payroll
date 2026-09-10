#!/bin/bash
# ================================================================
# Test exhaustivo: Provisiones de Prestaciones Sociales como reglas
# invisibles (doc 18)
#
# Reemplaza el modelo standalone l10n.co.hr.provision (+ .line + .wizard,
# wizard mensual manual sin integracion contable) por 4 reglas salariales
# invisibles (appears_on_payslip=False) en hr_payroll_structure_co_nomina:
# CO_PROV_PRIMA, CO_PROV_CESANTIAS, CO_PROV_INT_CES, CO_PROV_VACACIONES.
# Categoria nueva PROV, sin parent_id (mismo patron que SS_CIA) para
# quedar fuera de categories['DEV']/['DEDU'] que usa CO_NETO. Ver
# correcciones_normativas_2026/18_diseno_provisiones_reglas_invisibles.md.
#
# Mismas lecciones aprendidas de test_annual_params.sh / test_embargo.sh /
# test_certificado.sh:
# - odoo-bin se invoca directo, el wrapper() de pruebas hace cr.rollback()
#   defensivo en el except.
# - compute_sheet() deja el payslip en estado 'verify', no 'draft' -- hay
#   que regresarlo a draft antes de poder hacer unlink().
# - Aislar la variable bajo prueba forzando wage/integral_salary segun el
#   caso, restaurando en finally (leccion de T7 de test_embargo.sh).
#
# NOTA: /tmp/ne_params.tar.gz debe estar actualizado con el diff de doc 18
# antes de correr este script.
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
struct = env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
RuleParameter = env['hr.rule.parameter']

def get_param(code, date_value):
    return RuleParameter._get_parameter_from_code(code, date_value)

_REF_DATE = date.today()
_SMMLV = get_param('l10n_co_smmlv', _REF_DATE)
_AUX_TRANS = get_param('l10n_co_aux_transporte', _REF_DATE)
_FACTOR_INTEGRAL = get_param('l10n_co_factor_integral_salary', _REF_DATE)
_PCT_INT_CES = get_param('l10n_co_pct_intereses_cesantias', _REF_DATE)

prov_prima = env.ref('l10n_co_nomina_electronica.hr_salary_rule_co_prov_prima')
prov_cesantias = env.ref('l10n_co_nomina_electronica.hr_salary_rule_co_prov_cesantias')
prov_int_ces = env.ref('l10n_co_nomina_electronica.hr_salary_rule_co_prov_int_cesantias')
prov_vacaciones = env.ref('l10n_co_nomina_electronica.hr_salary_rule_co_prov_vacaciones')
cat_prov = env.ref('l10n_co_nomina_electronica.hr_salary_rule_category_provisiones')

emp = env['hr.employee'].search([
    ('contract_ids.state', '=', 'open'),
    ('company_id', '=', company.id),
], limit=1)
if not emp:
    raise Exception("No hay empleados con contrato activo -- no se puede probar provisiones")
contract = emp.contract_ids.filtered(lambda c: c.state == 'open')[:1]

# ================================================================
# TEST 1: categoria PROV es top-level (sin parent_id) -- garantia
# estructural de que no afecta categories['DEV']/['DEDU'] ni CO_NETO,
# mismo patron que SS_CIA (aportes patronales).
# ================================================================
def t1():
    assert not cat_prov.parent_id, \
        f"PROV no deberia tener parent_id, tiene {cat_prov.parent_id.code}"
test("Categoria PROV es top-level, sin parent_id (mismo patron que SS_CIA)", t1)

# ================================================================
# TEST 2: las 4 reglas existen, son invisibles, categoria PROV,
# estructura correcta.
# ================================================================
def t2():
    for rule in (prov_prima, prov_cesantias, prov_int_ces, prov_vacaciones):
        assert not rule.appears_on_payslip, \
            f"{rule.code}: deberia ser invisible (appears_on_payslip=False)"
        assert rule.category_id.id == cat_prov.id, \
            f"{rule.code}: categoria deberia ser PROV, es {rule.category_id.code}"
        assert rule.struct_id.id == struct.id, \
            f"{rule.code}: deberia estar en hr_payroll_structure_co_nomina"
test("Las 4 reglas CO_PROV_* son invisibles, categoria PROV, estructura correcta", t2)

# ================================================================
# TEST 3: modelo viejo l10n.co.hr.provision realmente eliminado --
# mismo patron que Test 9 de test_embargo.sh / Test 20 de
# test_annual_params.sh.
# ================================================================
def t3():
    assert 'l10n.co.hr.provision' not in env, \
        "El modelo l10n.co.hr.provision deberia haberse eliminado"
    assert 'l10n.co.hr.provision.wizard' not in env, \
        "El modelo l10n.co.hr.provision.wizard deberia haberse eliminado"
    cr.execute("SELECT to_regclass('l10n_co_hr_provision')")
    assert cr.fetchone()[0] is None, "La tabla l10n_co_hr_provision deberia haberse eliminado"
    cr.execute("SELECT to_regclass('l10n_co_hr_provision_line')")
    assert cr.fetchone()[0] is None, "La tabla l10n_co_hr_provision_line deberia haberse eliminado"
test("Modelo y tablas viejas de l10n.co.hr.provision realmente eliminados", t3)

# ================================================================
# TEST 4: payslip real, empleado NO integral, salario < 2xSMMLV (aplica
# auxilio de transporte) -- valida las 4 formulas end-to-end.
# ================================================================
def t4():
    original_wage = contract.wage
    original_integral = contract.l10n_co_ne_integral_salary
    contract.write({'wage': _SMMLV * 1.5, 'l10n_co_ne_integral_salary': False})
    cr.commit()
    ps = env['hr.payslip'].create({
        'name': 'Test Provisiones No Integral',
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_from': _REF_DATE.replace(day=1),
        'date_to': _REF_DATE,
        'struct_id': struct.id,
    })
    try:
        ps.compute_sheet()
        base = contract.wage + _AUX_TRANS
        expected_prima = base / 12.0
        expected_cesantias = base / 12.0
        expected_intereses = expected_cesantias * _PCT_INT_CES / 100
        expected_vacaciones = contract.wage / 24.0

        line_prima = ps.line_ids.filtered(lambda l: l.code == 'CO_PROV_PRIMA')
        line_cesantias = ps.line_ids.filtered(lambda l: l.code == 'CO_PROV_CESANTIAS')
        line_intereses = ps.line_ids.filtered(lambda l: l.code == 'CO_PROV_INT_CES')
        line_vacaciones = ps.line_ids.filtered(lambda l: l.code == 'CO_PROV_VACACIONES')

        assert line_prima and abs(line_prima.total - expected_prima) < 0.01, \
            f"CO_PROV_PRIMA: esperado {expected_prima}, obtenido {line_prima.total if line_prima else None}"
        assert line_cesantias and abs(line_cesantias.total - expected_cesantias) < 0.01, \
            f"CO_PROV_CESANTIAS: esperado {expected_cesantias}, obtenido {line_cesantias.total if line_cesantias else None}"
        assert line_intereses and abs(line_intereses.total - expected_intereses) < 0.01, \
            f"CO_PROV_INT_CES: esperado {expected_intereses}, obtenido {line_intereses.total if line_intereses else None}"
        assert line_vacaciones and abs(line_vacaciones.total - expected_vacaciones) < 0.01, \
            f"CO_PROV_VACACIONES: esperado {expected_vacaciones}, obtenido {line_vacaciones.total if line_vacaciones else None}"
    finally:
        ps.write({'state': 'draft'})
        ps.unlink()
        contract.write({'wage': original_wage, 'l10n_co_ne_integral_salary': original_integral})
        cr.commit()
test("Payslip no integral, salario < 2xSMMLV: las 4 formulas de provision correctas", t4)

# ================================================================
# TEST 5: payslip real, salario integral (Art. 132 CST) -- base =
# wage x factor_integral_salary, SIN auxilio de transporte.
# ================================================================
def t5():
    original_wage = contract.wage
    original_integral = contract.l10n_co_ne_integral_salary
    contract.write({'wage': _SMMLV * 15, 'l10n_co_ne_integral_salary': True})
    cr.commit()
    ps = env['hr.payslip'].create({
        'name': 'Test Provisiones Integral',
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_from': _REF_DATE.replace(day=1),
        'date_to': _REF_DATE,
        'struct_id': struct.id,
    })
    try:
        ps.compute_sheet()
        base = contract.wage * _FACTOR_INTEGRAL
        expected_prima = base / 12.0
        expected_vacaciones = contract.wage / 24.0

        line_prima = ps.line_ids.filtered(lambda l: l.code == 'CO_PROV_PRIMA')
        line_vacaciones = ps.line_ids.filtered(lambda l: l.code == 'CO_PROV_VACACIONES')

        assert line_prima and abs(line_prima.total - expected_prima) < 0.01, \
            f"CO_PROV_PRIMA (integral): esperado {expected_prima}, obtenido {line_prima.total if line_prima else None}"
        assert line_vacaciones and abs(line_vacaciones.total - expected_vacaciones) < 0.01, \
            f"CO_PROV_VACACIONES (integral): esperado {expected_vacaciones}, obtenido {line_vacaciones.total if line_vacaciones else None}"
    finally:
        ps.write({'state': 'draft'})
        ps.unlink()
        contract.write({'wage': original_wage, 'l10n_co_ne_integral_salary': original_integral})
        cr.commit()
test("Payslip salario integral: base = wage x factor_integral_salary, sin aux. transporte", t5)

# ================================================================
# TEST 6: CO_NETO no se ve afectado por las lineas PROV -- verificacion
# en runtime, no solo estructural (T1). Reconstruye independientemente
# la suma DEV+DEDU caminando el arbol de categorias y confirma que
# coincide con CO_NETO, y que las lineas PROV (con monto > 0, para que
# la prueba sea significativa) quedan fuera de esa suma.
# ================================================================
def t6():
    original_wage = contract.wage
    original_integral = contract.l10n_co_ne_integral_salary
    contract.write({'wage': _SMMLV * 1.5, 'l10n_co_ne_integral_salary': False})
    cr.commit()
    ps = env['hr.payslip'].create({
        'name': 'Test Provisiones CO_NETO',
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_from': _REF_DATE.replace(day=1),
        'date_to': _REF_DATE,
        'struct_id': struct.id,
    })
    try:
        ps.compute_sheet()

        dev_cat = env.ref('l10n_co_nomina_electronica.hr_salary_rule_category_devengados')
        dedu_cat = env.ref('l10n_co_nomina_electronica.hr_salary_rule_category_deducciones')

        def is_descendant(cat, root_id):
            cur = cat
            while cur:
                if cur.id == root_id:
                    return True
                cur = cur.parent_id
            return False

        # CO_NETO_line.category_id es DEV (para agruparse visualmente con los
        # devengados en el recibo) -- si no se excluye por code, queda
        # incluida en su propia reconstruccion (componentes + el total que
        # ya es su suma), duplicando el valor. No es una fuga de PROV; PROV
        # nunca entro en la cuenta -- hallazgo de Tech Lead corriendo esto
        # contra staging_produccion.
        dev_dedu_lines = ps.line_ids.filtered(
            lambda l: l.code != 'CO_NETO' and (
                is_descendant(l.category_id, dev_cat.id) or is_descendant(l.category_id, dedu_cat.id)
            )
        )
        expected_neto = sum(dev_dedu_lines.mapped('total'))

        neto_line = ps.line_ids.filtered(lambda l: l.code == 'CO_NETO')
        assert neto_line, "No se genero linea CO_NETO"
        assert abs(neto_line.total - expected_neto) < 0.01, \
            f"CO_NETO ({neto_line.total}) no coincide con la suma DEV+DEDU " \
            f"reconstruida independientemente ({expected_neto}) -- posible fuga de PROV"

        prov_lines = ps.line_ids.filtered(lambda l: l.category_id.id == cat_prov.id)
        prov_total = sum(prov_lines.mapped('total'))
        assert prov_total > 0, \
            "Las lineas PROV deberian tener montos > 0 para que esta prueba sea significativa"
        assert not (prov_lines & dev_dedu_lines), \
            "Las lineas PROV no deberian aparecer en la suma DEV/DEDU reconstruida"
    finally:
        ps.write({'state': 'draft'})
        ps.unlink()
        contract.write({'wage': original_wage, 'l10n_co_ne_integral_salary': original_integral})
        cr.commit()
test("CO_NETO no incluye las lineas PROV (verificado en runtime, no solo estructural)", t6)

# ================================================================
# TEST 7: integracion contable -- confirma que _prepare_account_move_lines
# (hr_payslip_account.py) SI recoge las lineas invisibles CO_PROV_* una
# vez configuradas en l10n.co.payroll.account.config, sin codigo nuevo
# (doc 18 SS2.4). Usa 2 cuentas contables reales existentes, crea la
# config solo para CO_PROV_PRIMA (alcance minimo para probar el
# mecanismo), confirma el payslip y verifica el asiento generado.
#
# Sin commits intermedios, y cr.rollback() incondicional al final (no solo
# en el except de test()): la compania de prueba tiene
# check_account_audit_trail=True, y una vez un account.move se marca
# posted_before=True, Odoo protege su chatter permanentemente (cumplimiento
# legal, ver account/models/mail_message.py:_except_audit_log()) -- ni
# button_draft() ni unlink() lo deshacen. Intentar limpiar con
# escritura+commit (como el resto de la suite) revienta ahi. Como nada se
# comitea, el rollback deshace payslip+move+config+cambio de wage de una
# sola vez -- no hace falta restaurar nada a mano. Hallazgo de Tech Lead
# corriendo esto contra staging_produccion.
# ================================================================
def t7():
    accounts = env['account.account'].search([
        ('company_ids', 'in', company.id),
        ('account_type', 'not in', ('off_balance',)),
    ], limit=2)
    if len(accounts) < 2:
        raise Exception("No hay al menos 2 account.account disponibles para probar la integracion contable")
    debit_account, credit_account = accounts[0], accounts[1]

    contract.write({'wage': _SMMLV * 1.5, 'l10n_co_ne_integral_salary': False})

    AccountConfig = env['l10n.co.payroll.account.config']
    config = AccountConfig.create({
        'salary_rule_id': prov_prima.id,
        'debit_account_id': debit_account.id,
        'credit_account_id': credit_account.id,
        'company_id': company.id,
    })

    ps = env['hr.payslip'].create({
        'name': 'Test Provisiones Contabilidad',
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_from': _REF_DATE.replace(day=1),
        'date_to': _REF_DATE,
        'struct_id': struct.id,
    })
    try:
        ps.compute_sheet()
        ps.action_payslip_done()

        line_prima = ps.line_ids.filtered(lambda l: l.code == 'CO_PROV_PRIMA')
        assert line_prima and line_prima.total, "CO_PROV_PRIMA no tiene monto -- no se puede probar el asiento"

        assert ps.move_id, "No se genero asiento contable (move_id vacio) con la configuracion de CO_PROV_PRIMA"
        move_debit_lines = ps.move_id.line_ids.filtered(lambda l: l.account_id.id == debit_account.id)
        move_credit_lines = ps.move_id.line_ids.filtered(lambda l: l.account_id.id == credit_account.id)
        assert move_debit_lines and abs(sum(move_debit_lines.mapped('debit')) - abs(line_prima.total)) < 0.01, \
            "La linea de debito del asiento no refleja el monto de CO_PROV_PRIMA"
        assert move_credit_lines and abs(sum(move_credit_lines.mapped('credit')) - abs(line_prima.total)) < 0.01, \
            "La linea de credito del asiento no refleja el monto de CO_PROV_PRIMA"
    finally:
        cr.rollback()
test("Integracion contable existente recoge CO_PROV_PRIMA sin codigo nuevo (doc 18 SS2.4)", t7)

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
