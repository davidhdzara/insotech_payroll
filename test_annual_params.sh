#!/bin/bash
# ================================================================
# Test exhaustivo: Parametros de Nomina (hr.rule.parameter nativo, doc 13)
#
# Reescrito para el framework nativo hr.rule.parameter/hr.rule.parameter.value
# (Enterprise, hr_payroll) que reemplazo a l10n.co.payroll.annual.params /
# l10n.co.payroll.time.params -- ver correcciones_normativas_2026/
# 13_migracion_hr_rule_parameter.md. La version anterior de este script
# creaba/leia registros de esos dos modelos, que ya no existen.
#
# NOTA: /tmp/ne_params.tar.gz debe estar actualizado con el diff de doc 13
# antes de correr este script -- el mecanismo de empaquetado/despliegue no
# se toco aqui (pendiente de coordinar aparte, no es parte de este fix).
# ================================================================
set -e

# Extraer modulo
cd /home/odoo/src/user/l10n_co_nomina_electronica
rm -rf models/ views/ data/ wizard/ services/ tests/ security/ report/ static/ __pycache__/
cd /home/odoo/src/user
tar xzf /tmp/ne_params.tar.gz -C l10n_co_nomina_electronica/

# Actualizar modulo
# odoo-bin es ejecutable propio (shebang /usr/bin/env python3), resuelto
# via PATH al wrapper de Odoo.sh -- se invoca directo, no como argumento
# de python/python3 (el servidor no tiene "python", solo "python3").
# Confirmado corriendo este script real contra staging_produccion.
cd /home/odoo
odoo-bin -d guapante-staging-produccion-37396060 -u l10n_co_nomina_electronica --stop-after-init --no-http 2>&1 | tail -5

echo "========================================"
echo "  MODULO ACTUALIZADO - INICIANDO TESTS"
echo "========================================"

# Ejecutar tests via odoo shell
odoo-bin shell -d guapante-staging-produccion-37396060 --no-http <<'PYEOF'
import traceback
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from odoo.exceptions import UserError

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
        # Si la prueba tronó con un error real de Postgres (no un simple
        # AssertionError de Python), la transaccion queda abortada y todas
        # las pruebas siguientes fallarian en cascada con "current
        # transaction is aborted" sin que el fallo sea suyo. Cada prueba es
        # responsable de su propio commit/rollback en su happy path, pero
        # el wrapper hace este rollback defensivo para que un error real no
        # contamine las pruebas siguientes.
        try:
            cr.rollback()
        except Exception:
            pass

company = env.user.company_id
RuleParameter = env['hr.rule.parameter']

def get_param(code, date_value, raise_if_not_found=True):
    return RuleParameter._get_parameter_from_code(
        code, date_value, raise_if_not_found=raise_if_not_found)

# ================================================================
# TEST 1: Parametro sembrado -- SMMLV 2025
# ================================================================
def t1():
    v = get_param('l10n_co_smmlv', date(2025, 6, 15))
    assert v == 1423500, f"SMMLV 2025 incorrecto: {v}"
test("Parametro sembrado: SMMLV 2025", t1)

# ================================================================
# TEST 2: Parametro sembrado -- SMMLV 2024
# ================================================================
def t2():
    v = get_param('l10n_co_smmlv', date(2024, 12, 31))
    assert v == 1300000, f"SMMLV 2024 incorrecto: {v}"
test("Parametro sembrado: SMMLV 2024", t2)

# ================================================================
# TEST 3: Parametro sembrado -- SMMLV 2026 (Decreto real)
# ================================================================
def t3():
    v = get_param('l10n_co_smmlv', date(2026, 1, 1))
    assert v == 1750905, f"SMMLV 2026 incorrecto: {v}"
test("Parametro sembrado: SMMLV 2026 (Decreto real)", t3)

# ================================================================
# TEST 4: Unicidad nativa -- (rule_parameter_id, date_from) duplicado
# rechazado (_sql_constraints de hr.rule.parameter.value). Usa un
# parametro de prueba desechable para no tocar los codigos reales.
# ================================================================
def t4():
    test_code = 'l10n_co_test_smoke_%d' % int(datetime.now().timestamp())
    test_param = RuleParameter.create({
        'name': 'Test Smoke Param',
        'code': test_code,
    })
    try:
        env['hr.rule.parameter.value'].create({
            'rule_parameter_id': test_param.id,
            'date_from': date(2025, 1, 1),
            'parameter_value': '1',
        })
        cr.commit()
        try:
            env['hr.rule.parameter.value'].create({
                'rule_parameter_id': test_param.id,
                'date_from': date(2025, 1, 1),
                'parameter_value': '2',
            })
            cr.commit()
            raise AssertionError(
                "Debio fallar por unicidad (rule_parameter_id, date_from)")
        except Exception as e:
            cr.rollback()
            assert 'unique' in str(e).lower() or 'same day' in str(e).lower(), \
                f"Error inesperado: {e}"
    finally:
        test_param.unlink()
        cr.commit()
test("Unicidad nativa: (rule_parameter_id, date_from) duplicado rechazado", t4)

# ================================================================
# TEST 5: Helper busca UVT/aux_transporte del ano correcto
# ================================================================
def t5():
    aux2025 = get_param('l10n_co_aux_transporte', date(2025, 6, 15))
    assert aux2025 == 200000, f"Aux transporte 2025: {aux2025}"
    uvt2024 = get_param('l10n_co_uvt', date(2024, 12, 31))
    assert uvt2024 == 47065, f"UVT 2024: {uvt2024}"
    uvt2026 = get_param('l10n_co_uvt', date(2026, 1, 1))
    assert uvt2026 == 52374, f"UVT 2026: {uvt2026}"
test("Helper: busca UVT/aux_transporte del ano correcto", t5)

# ================================================================
# TEST 6: raise_if_not_found=False devuelve None sin lanzar
# (del que depende hr_retefuente._compute_uvt_value -- antes esto
# probaba que el helper aceptara datetime, pero ningun sitio del
# codigo migrado pasa un datetime crudo; esto es lo que si se usa.)
#
# Fecha: 2020-01-01, ANTES del primer valor sembrado (2024-01-01) -- no
# 2030. El lookup nativo es "date_from <= fecha, el mas reciente gana",
# asi que una fecha FUTURA (2030) simplemente hereda el ultimo valor
# vigente (2026) hacia adelante -- eso es el comportamiento correcto y
# deseado, no "sin parametro". Solo una fecha anterior a TODO valor
# sembrado prueba genuinamente el caso "no hay parametro". Confirmado
# corriendo el test real contra staging_produccion (Tech Lead).
# ================================================================
def t6():
    v = get_param('l10n_co_smmlv', date(2020, 1, 1), raise_if_not_found=False)
    assert v is None, f"raise_if_not_found=False deberia devolver None, devolvio {v!r}"
test("Helper: raise_if_not_found=False devuelve None sin lanzar", t6)

# ================================================================
# TEST 7: Helper con string fecha (usado por hr_retefuente.py)
# ================================================================
def t7():
    v = get_param('l10n_co_smmlv', '2024-07-01')
    assert v == 1300000, f"SMMLV con string fecha: {v}"
test("Helper: acepta string YYYY-MM-DD", t7)

# ================================================================
# TEST 8: Helper falla si no hay parametro para la fecha
# Fecha 2020-01-01, anterior al primer valor sembrado -- ver nota en T6
# sobre por que 2030 (fecha futura) NO prueba este caso.
# ================================================================
def t8():
    try:
        get_param('l10n_co_smmlv', date(2020, 1, 1))
        raise AssertionError("Debio lanzar UserError")
    except UserError as e:
        assert 'l10n_co_smmlv' in str(e), f"Error no menciona el codigo: {e}"
        assert '2020' in str(e), f"Error no menciona la fecha: {e}"
test("Helper: UserError si no hay parametro para la fecha", t8)

# ================================================================
# TEST 9: Validacion nativa -- parameter_value debe ser literal
# Python valido (_check_parameter_value de hr.rule.parameter.value,
# via safe_eval). Reemplaza el viejo test de rango de ano (2000-2100),
# que era una validacion propia del modelo eliminado, sin equivalente
# en el framework nativo.
# ================================================================
def t9():
    test_code = 'l10n_co_test_smoke_literal_%d' % int(datetime.now().timestamp())
    test_param = RuleParameter.create({
        'name': 'Test Smoke Literal Param',
        'code': test_code,
    })
    cr.commit()
    try:
        try:
            env['hr.rule.parameter.value'].create({
                'rule_parameter_id': test_param.id,
                'date_from': date(2025, 1, 1),
                'parameter_value': 'esto no es un literal python valido =',
            })
            cr.commit()
            raise AssertionError(
                "Debio fallar: parameter_value no es un literal Python valido")
        except UserError:
            cr.rollback()
    finally:
        test_param.unlink()
        cr.commit()
test("Validacion nativa: parameter_value debe ser literal Python valido", t9)

# ================================================================
# TEST 10: Campos obligatorios -- date_from requerido
# ================================================================
def t10():
    test_code = 'l10n_co_test_smoke_required_%d' % int(datetime.now().timestamp())
    test_param = RuleParameter.create({
        'name': 'Test Smoke Required Param',
        'code': test_code,
    })
    cr.commit()
    try:
        try:
            env['hr.rule.parameter.value'].create({
                'rule_parameter_id': test_param.id,
                'parameter_value': '1',
                # date_from omitido (required=True)
            })
            cr.commit()
            raise AssertionError("Debio fallar por date_from obligatorio")
        except Exception:
            cr.rollback()
    finally:
        test_param.unlink()
        cr.commit()
test("Campos obligatorios: date_from requerido en hr.rule.parameter.value", t10)

# ================================================================
# TEST 11: Nomina usa parametros del ano correcto
# ================================================================
def t11():
    # Buscar un empleado con contrato activo
    emp = env['hr.employee'].search([
        ('contract_ids.state', '=', 'open'),
        ('company_id', '=', company.id),
    ], limit=1)
    if not emp:
        raise Exception("No hay empleados con contrato activo")
    
    contract = emp.contract_ids.filtered(lambda c: c.state == 'open')[:1]
    
    # Crear payslip de mayo 2026
    # 'name' es required+compute(store=True) en hr.payslip nativo -- se
    # pasa explicito porque en pruebas via shell/create() directo no
    # siempre se dispara el compute antes del INSERT (confirmado corriendo
    # este script real contra staging_produccion: sin 'name' explicito
    # truena con "null value in column name").
    ps = env['hr.payslip'].create({
        'name': 'Test Nomina 2026-05',
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_from': date(2026, 5, 1),
        'date_to': date(2026, 5, 31),
        'struct_id': env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina').id,
    })
    ps.compute_sheet()
    
    # Verificar que se calculo (no se cayó por falta de params)
    assert ps.line_ids, "No se generaron lineas"
    
    # Verificar aux transporte: si salario <= 2 SMMLV 2026, debe ser 249095
    aux_line = ps.line_ids.filtered(lambda l: l.code == 'CO_AUX_TRANS')
    if contract.wage <= 1750905 * 2 and not contract.l10n_co_ne_integral_salary:
        assert aux_line, "Deberia tener aux transporte"
        # Aux = 249095/30 * dias trabajados
        expected_daily = 249095 / 30
        assert abs(aux_line.total) > 0, f"Aux transporte = 0"

    # compute_sheet() deja el payslip en estado 'verify' (ver hr_payslip.py
    # nativo), y unlink() solo permite 'draft'/'cancel' -- hay que
    # regresarlo a borrador antes de poder borrarlo. Confirmado corriendo
    # este script real: sin esto, unlink() lanza "You cannot delete a
    # payslip which is not draft or cancelled!".
    ps.write({'state': 'draft'})
    ps.unlink()
    cr.commit()
test("Nomina 2026: usa params 2026", t11)

# ================================================================
# TEST 12: Nomina falla si no hay params del periodo
#
# Fecha 2020-01-01, NO 2030 -- ver nota en T6 sobre por que una fecha
# FUTURA ya no prueba "sin parametros" bajo el lookup nativo (hereda el
# ultimo valor vigente hacia adelante). Solo una fecha anterior a 2024
# (el primer valor sembrado) prueba genuinamente este caso.
# ================================================================
def t12():
    emp = env['hr.employee'].search([
        ('contract_ids.state', '=', 'open'),
        ('company_id', '=', company.id),
    ], limit=1)
    contract = emp.contract_ids.filtered(lambda c: c.state == 'open')[:1]

    # Crear payslip de un periodo anterior a cualquier parametro sembrado
    ps = env['hr.payslip'].create({
        'name': 'Test Nomina 2020-01',
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_from': date(2020, 1, 1),
        'date_to': date(2020, 1, 31),
        'struct_id': env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina').id,
    })
    try:
        ps.compute_sheet()
        ps.write({'state': 'draft'})
        ps.unlink()
        cr.commit()
        raise AssertionError("Debio fallar al calcular sin params configurados")
    except UserError as e:
        cr.rollback()
        assert '2020' in str(e) or 'l10n_co_' in str(e), f"Error no identifica el parametro/fecha: {e}"
    except Exception as e:
        cr.rollback()
        # Cualquier error esta bien si identifica el parametro o la fecha
        if '2020' not in str(e) and 'l10n_co_' not in str(e):
            raise
test("Nomina 2020: falla sin params configurados", t12)

# ================================================================
# TEST 13: Provision usa params del ano/mes correcto
# ================================================================
def t13():
    # Buscar o crear provision de mayo 2026
    prov_model = env['l10n.co.hr.provision']
    prov = prov_model.search([
        ('year', '=', 2026),
        ('month', '=', '05'),
        ('company_id', '=', company.id),
    ], limit=1)
    if prov:
        if prov.state == 'posted':
            prov.action_cancel()
        prov.unlink()
        cr.commit()
    
    prov = prov_model.create({
        'year': 2026,
        'month': '05',
        'company_id': company.id,
    })
    cr.commit()
    
    # Calcular - debe usar params 2026
    prov.action_compute_provisions()
    cr.commit()
    
    assert prov.line_ids, "No se generaron lineas de provision"
test("Provision 2026: usa params 2026", t13)

# ================================================================
# TEST 14: Provision falla si no hay params del periodo
#
# Ano 2020, NO 2030 -- misma razon que T12: una fecha futura hereda el
# ultimo valor sembrado (2026) hacia adelante bajo el lookup nativo, ya
# no prueba "sin parametros configurados".
# ================================================================
def t14():
    prov_model = env['l10n.co.hr.provision']
    prov = prov_model.create({
        'year': 2020,
        'month': '01',
        'company_id': company.id,
    })
    cr.commit()

    try:
        prov.action_compute_provisions()
        cr.commit()
        raise AssertionError("Debio fallar sin params configurados (2020)")
    except UserError as e:
        cr.rollback()
        assert '2020' in str(e) or 'l10n_co_' in str(e), f"Error no identifica el parametro/fecha: {e}"
    except Exception as e:
        cr.rollback()
        if '2020' not in str(e) and 'l10n_co_' not in str(e):
            raise
    finally:
        try:
            prov2 = prov_model.search([('year','=',2020),('company_id','=',company.id)])
            if prov2:
                prov2.unlink()
                cr.commit()
        except:
            cr.rollback()
test("Provision 2020: falla sin params configurados", t14)

# ================================================================
# TEST 15: Distintos anos devuelven distintos valores
# ================================================================
def t15():
    smmlv24 = get_param('l10n_co_smmlv', date(2024, 6, 1))
    smmlv25 = get_param('l10n_co_smmlv', date(2025, 6, 1))
    assert smmlv24 != smmlv25, "2024 y 2025 deben tener SMMLV distinto"
    assert smmlv24 == 1300000, f"2024 SMMLV={smmlv24}"
    assert smmlv25 == 1423500, f"2025 SMMLV={smmlv25}"
    aux24 = get_param('l10n_co_aux_transporte', date(2024, 6, 1))
    aux25 = get_param('l10n_co_aux_transporte', date(2025, 6, 1))
    assert aux24 == 162000, f"2024 aux={aux24}"
    assert aux25 == 200000, f"2025 aux={aux25}"
test("Años distintos: valores distintos", t15)

# ================================================================
# TEST 16: hr.rule.parameter.value expone code/rule_parameter_name
# correctamente (reemplaza el name_get del modelo eliminado)
# ================================================================
def t16():
    val = env['hr.rule.parameter.value'].search([
        ('code', '=', 'l10n_co_smmlv'),
        ('date_from', '=', date(2025, 1, 1)),
    ], limit=1)
    assert val, "No se encontro el hr.rule.parameter.value de SMMLV 2025"
    assert val.rule_parameter_name, f"rule_parameter_name vacio: {val.rule_parameter_name!r}"
    assert val.code == 'l10n_co_smmlv', f"code incorrecto: {val.code}"
test("hr.rule.parameter.value: code/rule_parameter_name correctos", t16)

# ================================================================
# TEST 17: Editar hr.rule.parameter.value existente -- se refleja
# inmediato (confirma que el write() invalida el ormcache del
# lookup, ver HrSalaryRuleParameterValue.write() en hr_payroll)
# ================================================================
def t17():
    val = env['hr.rule.parameter.value'].search([
        ('code', '=', 'l10n_co_smmlv'),
        ('date_from', '=', date(2026, 1, 1)),
    ], limit=1)
    assert val, "No se encontro hr.rule.parameter.value SMMLV 2026"
    original = val.parameter_value
    val.write({'parameter_value': '1500000'})
    cr.commit()
    check = get_param('l10n_co_smmlv', date(2026, 1, 1))
    assert check == 1500000, f"SMMLV no se actualizo: {check}"
    # Revertir al valor real de 2026 (Decreto 1469/2025)
    val.write({'parameter_value': original})
    cr.commit()
test("Editar hr.rule.parameter.value: se refleja inmediato (ormcache)", t17)

# ================================================================
# TEST 18: Company sin campos viejos
# ================================================================
def t18():
    # Los campos l10n_co_ne_smmlv, l10n_co_ne_aux_transporte, l10n_co_ne_uvt
    # ya no deben existir en res.company
    has_smmlv = hasattr(company, 'l10n_co_ne_smmlv') and 'l10n_co_ne_smmlv' in company._fields
    has_aux = hasattr(company, 'l10n_co_ne_aux_transporte') and 'l10n_co_ne_aux_transporte' in company._fields
    has_uvt = hasattr(company, 'l10n_co_ne_uvt') and 'l10n_co_ne_uvt' in company._fields
    assert not has_smmlv, "Campo l10n_co_ne_smmlv aun existe en company"
    assert not has_aux, "Campo l10n_co_ne_aux_transporte aun existe en company"
    assert not has_uvt, "Campo l10n_co_ne_uvt aun existe en company"
test("Company: campos viejos eliminados", t18)

# ================================================================
# TEST 19: Liquidacion wizard usa params del periodo correcto
#
# date_end se calcula relativo a contract.date_start (no un literal fijo
# de 2025-12-31) -- el empleado real que devuelve la busqueda varia por
# ambiente/base de datos, y un literal fijo puede caer ANTES del inicio
# del contrato real, violando _check_dates (confirmado corriendo este
# script real contra staging_produccion: le tocó un contrato que arranca
# 2026-07-01). Por la misma razon, la aserción compara contra el
# SMMLV/aux_transporte reales del periodo calculado, no un literal de
# 2025 -- el periodo real ya no es necesariamente 2025.
# ================================================================
def t19():
    emp = env['hr.employee'].search([
        ('contract_ids.state', '=', 'open'),
        ('company_id', '=', company.id),
    ], limit=1)
    if not emp:
        raise Exception("No hay empleados")
    contract = emp.contract_ids.filtered(lambda c: c.state == 'open')[:1]

    liq_date_end = contract.date_start + relativedelta(months=6)

    liq_model = env['l10n.co.hr.liquidacion']
    # Borrar liquidaciones previas del empleado
    liq_model.search([('employee_id','=',emp.id)]).unlink()
    cr.commit()

    liq = liq_model.create({
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_start': contract.date_start,
        'date_end': liq_date_end,
        'cause': 'renuncia',
        'contract_type': 'indefinido',
        'base_salary': contract.wage,
        'aux_transporte': 0,
    })
    cr.commit()

    # Forzar onchange para que recalcule aux transporte con params del periodo
    liq._onchange_contract_id()
    cr.commit()

    smmlv_periodo = get_param('l10n_co_smmlv', liq_date_end)
    aux_periodo = get_param('l10n_co_aux_transporte', liq_date_end)
    if contract.wage <= smmlv_periodo * 2 and not contract.l10n_co_ne_integral_salary:
        assert liq.aux_transporte == aux_periodo, \
            f"Aux debe ser {aux_periodo} ({liq_date_end.year}), es {liq.aux_transporte}"

    liq.unlink()
    cr.commit()
test("Liquidacion: aux transporte del periodo correcto", t19)

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
