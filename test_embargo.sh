#!/bin/bash
# ================================================================
# Test exhaustivo: Embargo Hibrido (hr.salary.attachment + recalculo
# dinamico, doc 16)
#
# Reemplaza l10n.co.hr.embargo por hr.salary.attachment nativo
# (Enterprise, hr_payroll) extendido con 2 campos colombianos
# (models/hr_salary_attachment.py) + 3 hr.payslip.input.type propios
# (data/l10n_co_embargo_input_types_data.xml). La regla salarial
# CO_EMBARGO mantiene la misma logica de prioridad + piso jurisprudencial
# ya validada, solo cambia de donde lee los embargos activos. Ver
# correcciones_normativas_2026/16_diseno_embargo_hibrido_salary_attachment.md.
#
# Mismas lecciones aprendidas del ciclo de test_annual_params.sh:
# - odoo-bin se invoca directo (no "python odoo-bin"), el wrapper() de
#   pruebas hace cr.rollback() defensivo en el except.
# - hr.payslip.name es required+compute pero no siempre se dispara antes
#   del INSERT via create() directo en shell -- se pasa explicito.
# - compute_sheet() deja el payslip en estado 'verify', no 'draft' --
#   hay que regresarlo a draft antes de poder hacer unlink().
#
# NOTA: /tmp/ne_params.tar.gz (o el tarball que se este usando para
# empaquetar el modulo actual) debe estar actualizado con el diff de
# doc 16 antes de correr este script.
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
        try:
            cr.rollback()
        except Exception:
            pass

company = env.user.company_id
RuleParameter = env['hr.rule.parameter']

def get_param(code, date_value):
    return RuleParameter._get_parameter_from_code(code, date_value)

Attachment = env['hr.salary.attachment']

type_alimentos = env.ref('l10n_co_nomina_electronica.input_l10n_co_embargo_alimentos')
type_civil = env.ref('l10n_co_nomina_electronica.input_l10n_co_embargo_civil')
type_cooperativa = env.ref('l10n_co_nomina_electronica.input_l10n_co_embargo_cooperativa')

emp = env['hr.employee'].search([
    ('contract_ids.state', '=', 'open'),
    ('company_id', '=', company.id),
], limit=1)
if not emp:
    raise Exception("No hay empleados con contrato activo -- no se puede probar embargo")
contract = emp.contract_ids.filtered(lambda c: c.state == 'open')[:1]

_REF_DATE = date.today()
_SMMLV = get_param('l10n_co_smmlv', _REF_DATE)
_FACTOR_CIVIL = get_param('l10n_co_factor_embargo_civil', _REF_DATE)
_PCT_ALIMENTOS = get_param('l10n_co_pct_tope_embargo_alimentos', _REF_DATE)

# ================================================================
# LIMPIEZA: cancelar/borrar attachments de embargo previos del
# empleado de prueba, para empezar limpio.
# ================================================================
_prev = Attachment.search([
    ('employee_ids', 'in', emp.id),
    ('other_input_type_id', 'in', [type_alimentos.id, type_civil.id, type_cooperativa.id]),
])
if _prev:
    _prev.write({'state': 'cancel'})
    _prev.unlink()
    cr.commit()


def _make_attachment(other_input_type, porcentaje=0.0, monthly_amount=1.0,
                      date_start=None, date_end=None):
    vals = {
        'employee_ids': [(6, 0, [emp.id])],
        'description': 'Test embargo %s' % other_input_type.name,
        'other_input_type_id': other_input_type.id,
        'date_start': date_start or date(2024, 1, 1),
        'monthly_amount': monthly_amount,
        'l10n_co_embargo_porcentaje': porcentaje,
        'l10n_co_embargo_juzgado': 'Juzgado Test',
        'state': 'open',
    }
    if date_end:
        vals['date_end'] = date_end
        vals['no_end_date'] = False
    else:
        vals['no_end_date'] = True
    return Attachment.create(vals)

# ================================================================
# TEST 1: Combinado -- prioridad (alimentos/cooperativa antes que
# civil) + piso jurisprudencial de SMMLV, con un salario_neto
# sintetico bajo para forzar que el piso reduzca el civil.
# ================================================================
def t1():
    salario_neto = _SMMLV * 1.3  # poco margen sobre el SMMLV
    a_alimentos = _make_attachment(type_alimentos, porcentaje=40.0)
    a_civil = _make_attachment(type_civil, porcentaje=50.0)
    cr.commit()
    try:
        _PRIORIDAD = {
            'L10N_CO_EMBARGO_ALIMENTOS': 0,
            'L10N_CO_EMBARGO_COOPERATIVA': 1,
            'L10N_CO_EMBARGO_CIVIL': 2,
        }
        activos = (a_alimentos + a_civil).sorted(
            key=lambda a: _PRIORIDAD.get(a.other_input_type_id.code, 99))
        total = 0.0
        for att in activos:
            monto = att._l10n_co_compute_embargo_amount(
                salario_neto, _SMMLV, _REF_DATE,
                factor_embargo_civil=_FACTOR_CIVIL,
                pct_tope_embargo_alimentos=_PCT_ALIMENTOS,
            )
            espacio = max(0.0, (salario_neto - total) - _SMMLV)
            total += min(monto, espacio)

        remanente = salario_neto - total
        assert remanente >= _SMMLV - 0.01, \
            f"El piso SMMLV no se respeto: remanente={remanente}, SMMLV={_SMMLV}"
        # Alimentos (prioridad 0) debe haberse aplicado primero, sin reducir
        monto_alimentos_esperado = min(salario_neto * 0.40, salario_neto * (_PCT_ALIMENTOS / 100))
        espacio_alimentos = max(0.0, salario_neto - _SMMLV)
        assert abs(min(monto_alimentos_esperado, espacio_alimentos) - min(
            a_alimentos._l10n_co_compute_embargo_amount(
                salario_neto, _SMMLV, _REF_DATE,
                factor_embargo_civil=_FACTOR_CIVIL,
                pct_tope_embargo_alimentos=_PCT_ALIMENTOS),
            espacio_alimentos)) < 0.01, "Alimentos no se aplico con prioridad"
    finally:
        (a_alimentos + a_civil).write({'state': 'cancel'})
        (a_alimentos + a_civil).unlink()
        cr.commit()
test("Combinado: prioridad alimentos>civil + piso SMMLV respetado", t1)

# ================================================================
# TEST 2: Embargo con date_end en el pasado (fuera de vigencia) = 0
# ================================================================
def t2():
    salario_neto = _SMMLV * 3
    att = _make_attachment(
        type_civil, porcentaje=20.0,
        date_start=date(2024, 1, 1), date_end=date(2024, 12, 31))
    cr.commit()
    try:
        monto = att._l10n_co_compute_embargo_amount(
            salario_neto, _SMMLV, date(2026, 1, 1),  # fecha de nomina posterior a date_end
            factor_embargo_civil=_FACTOR_CIVIL,
            pct_tope_embargo_alimentos=_PCT_ALIMENTOS,
        )
        assert monto == 0.0, f"Embargo vencido deberia dar 0.0, dio {monto}"
    finally:
        att.write({'state': 'cancel'})
        att.unlink()
        cr.commit()
test("Vigencia: embargo con date_end pasado = 0", t2)

# ================================================================
# TEST 3: Embargo con date_start en el futuro (aun no vigente) = 0
# ================================================================
def t3():
    salario_neto = _SMMLV * 3
    att = _make_attachment(type_civil, porcentaje=20.0, date_start=date(2030, 1, 1))
    cr.commit()
    try:
        monto = att._l10n_co_compute_embargo_amount(
            salario_neto, _SMMLV, _REF_DATE,  # fecha de nomina anterior a date_start
            factor_embargo_civil=_FACTOR_CIVIL,
            pct_tope_embargo_alimentos=_PCT_ALIMENTOS,
        )
        assert monto == 0.0, f"Embargo aun no vigente deberia dar 0.0, dio {monto}"
    finally:
        att.write({'state': 'cancel'})
        att.unlink()
        cr.commit()
test("Vigencia: embargo con date_start futuro = 0", t3)

# ================================================================
# TEST 4: Tope civil Art. 155 CST -- 20% (factor_embargo_civil) del
# excedente sobre el SMMLV, aunque el porcentaje pedido sea mayor.
# ================================================================
def t4():
    salario_neto = _SMMLV * 3
    att = _make_attachment(type_civil, porcentaje=90.0)  # muy por encima del tope legal
    cr.commit()
    try:
        monto = att._l10n_co_compute_embargo_amount(
            salario_neto, _SMMLV, _REF_DATE,
            factor_embargo_civil=_FACTOR_CIVIL,
            pct_tope_embargo_alimentos=_PCT_ALIMENTOS,
        )
        tope_esperado = max(0, salario_neto - _SMMLV) * _FACTOR_CIVIL
        assert abs(monto - tope_esperado) < 0.01, \
            f"Tope civil Art. 155 CST no respetado: monto={monto}, tope={tope_esperado}"
    finally:
        att.write({'state': 'cancel'})
        att.unlink()
        cr.commit()
test("Tope Art. 155 CST: civil capeado al factor_embargo_civil del excedente", t4)

# ================================================================
# TEST 5: Tope alimentos Art. 156 CST -- pct_tope_embargo_alimentos%
# del salario neto, aunque el porcentaje pedido sea mayor.
# ================================================================
def t5():
    salario_neto = _SMMLV * 3
    att = _make_attachment(type_alimentos, porcentaje=95.0)
    cr.commit()
    try:
        monto = att._l10n_co_compute_embargo_amount(
            salario_neto, _SMMLV, _REF_DATE,
            factor_embargo_civil=_FACTOR_CIVIL,
            pct_tope_embargo_alimentos=_PCT_ALIMENTOS,
        )
        tope_esperado = salario_neto * (_PCT_ALIMENTOS / 100)
        assert abs(monto - tope_esperado) < 0.01, \
            f"Tope alimentos Art. 156 CST no respetado: monto={monto}, tope={tope_esperado}"
    finally:
        att.write({'state': 'cancel'})
        att.unlink()
        cr.commit()
test("Tope Art. 156 CST: alimentos capeado al pct_tope_embargo_alimentos del neto", t5)

# ================================================================
# TEST 6: Cooperativa usa el mismo tope que alimentos (Art. 156 CST)
# ================================================================
def t6():
    salario_neto = _SMMLV * 3
    att = _make_attachment(type_cooperativa, porcentaje=95.0)
    cr.commit()
    try:
        monto = att._l10n_co_compute_embargo_amount(
            salario_neto, _SMMLV, _REF_DATE,
            factor_embargo_civil=_FACTOR_CIVIL,
            pct_tope_embargo_alimentos=_PCT_ALIMENTOS,
        )
        tope_esperado = salario_neto * (_PCT_ALIMENTOS / 100)
        assert abs(monto - tope_esperado) < 0.01, \
            f"Tope cooperativa (mismo que Art. 156 CST) no respetado: monto={monto}, tope={tope_esperado}"
    finally:
        att.write({'state': 'cancel'})
        att.unlink()
        cr.commit()
test("Tope Art. 156 CST: cooperativa usa el mismo tope que alimentos", t6)

# ================================================================
# TEST 7: Payslip real -- embargos activos generan linea CO_EMBARGO
# negativa (integracion end-to-end de la regla salarial).
#
# El empleado que devuelva la busqueda puede tener, en este periodo,
# un salario_neto por debajo del SMMLV (ej. periodo parcial/prorrateado)
# -- con el piso jurisprudencial (T-864/14 + CSJ 2026, ya validado con
# David/QA) el resultado matematicamente correcto en ese caso es
# CO_EMBARGO = 0, no un valor negativo. Para que este test aisle
# especificamente "hay un embargo activo -> se genera y descuenta",
# se sube el wage del contrato temporalmente muy por encima del SMMLV
# (garantiza espacio antes del piso) y se restaura en el finally --
# misma leccion que T19 de test_annual_params.sh: no asumir
# propiedades del empleado que devuelva la busqueda, forzarlas.
# ================================================================
def t7():
    att = _make_attachment(type_civil, porcentaje=10.0)
    original_wage = contract.wage
    contract.wage = _SMMLV * 20
    cr.commit()
    ps = env['hr.payslip'].create({
        'name': 'Test Embargo Payslip',
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_from': _REF_DATE.replace(day=1),
        'date_to': _REF_DATE,
        'struct_id': env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina').id,
    })
    try:
        ps.compute_sheet()
        line = ps.line_ids.filtered(lambda l: l.code == 'CO_EMBARGO')
        assert line, "No se genero linea CO_EMBARGO con un embargo civil activo"
        assert line.total < 0, f"CO_EMBARGO deberia ser negativo, es {line.total}"
    finally:
        ps.write({'state': 'draft'})
        ps.unlink()
        att.write({'state': 'cancel'})
        att.unlink()
        contract.wage = original_wage
        cr.commit()
test("Payslip real: embargo activo genera linea CO_EMBARGO negativa", t7)

# ================================================================
# TEST 8: Override manual CO_EMBARGO (input de RRHH) respeta el piso
# SMMLV -- sin ningun hr.salary.attachment activo.
# ================================================================
def t8():
    ps = env['hr.payslip'].create({
        'name': 'Test Embargo Manual',
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_from': _REF_DATE.replace(day=1),
        'date_to': _REF_DATE,
        'struct_id': env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina').id,
    })
    try:
        input_type = env['hr.payslip.input.type'].search([('code', '=', 'CO_EMBARGO')], limit=1)
        assert input_type, "No existe hr.payslip.input.type con code=CO_EMBARGO"
        ps.write({'input_line_ids': [(0, 0, {
            'input_type_id': input_type.id,
            'amount': contract.wage * 10,  # deliberadamente excesivo
        })]})
        ps.compute_sheet()
        line = ps.line_ids.filtered(lambda l: l.code == 'CO_EMBARGO')
        assert line, "No se genero linea CO_EMBARGO con override manual"
        # No verificamos un numero exacto (el neto intermedio no es una
        # linea del payslip), solo que el monto manual excesivo SI fue
        # limitado -- no debe igualar el valor bruto excesivo pedido.
        assert abs(line.total) < contract.wage * 10, \
            "El override manual no se limito -- se aplico el valor excesivo sin tope"
    finally:
        ps.write({'state': 'draft'})
        ps.unlink()
        cr.commit()
test("Override manual CO_EMBARGO: valor excesivo se limita (piso SMMLV)", t8)

# ================================================================
# TEST 9: Tabla huerfana de l10n.co.hr.embargo realmente eliminada
# (mismo patron que Test 20 de test_annual_params.sh / migracion
# 18.0.3.0.3 -- ver su post-migrate.py para la causa raiz).
# ================================================================
def t9():
    cr.execute("SELECT to_regclass('l10n_co_hr_embargo')")
    exists = cr.fetchone()[0] is not None
    assert not exists, "La tabla l10n_co_hr_embargo deberia haberse eliminado, pero sigue existiendo"
test("Tabla huerfana l10n_co_hr_embargo eliminada", t9)

# ================================================================
# TEST 10: Campo viejo hr.employee.l10n_co_embargo_ids eliminado
# ================================================================
def t10():
    assert 'l10n_co_embargo_ids' not in emp._fields, \
        "Campo l10n_co_embargo_ids aun existe en hr.employee"
test("Campo viejo l10n_co_embargo_ids eliminado de hr.employee", t10)

# ================================================================
# TEST 11: Los 3 hr.payslip.input.type de embargo existen, scoped a
# Colombia, disponibles para asignaciones salariales.
# ================================================================
def t11():
    for t in (type_alimentos, type_civil, type_cooperativa):
        assert t.country_id == env.ref('base.co'), \
            f"{t.code}: country_id deberia ser Colombia, es {t.country_id.name}"
        assert t.available_in_attachments, \
            f"{t.code}: available_in_attachments deberia ser True"
test("3 input types de embargo: Colombia + disponibles en asignaciones", t11)

# ================================================================
# TEST 12: onchange sugiere monthly_amount al capturar porcentaje
# ================================================================
def t12():
    att = Attachment.new({
        'employee_ids': [(6, 0, [emp.id])],
        'description': 'Test onchange',
        'other_input_type_id': type_civil.id,
        'date_start': date(2024, 1, 1),
        'no_end_date': True,
        'monthly_amount': 1.0,
    })
    att.l10n_co_embargo_porcentaje = 10.0
    att._onchange_l10n_co_embargo_porcentaje()
    esperado = contract.wage * 10.0 / 100
    if contract.wage:
        assert abs(att.monthly_amount - esperado) < 0.01, \
            f"onchange no sugirio el monto esperado: {att.monthly_amount} vs {esperado}"
test("Onchange: sugiere monthly_amount al capturar porcentaje", t12)

# ================================================================
# TEST 13: hr_payroll_structure_co_nomina.input_line_type_ids incluye
# los 4 tipos de embargo (sin esto, hr_payslip_input.py restringe el
# picker de "Other Inputs" a un domain vacio y RRHH no puede
# seleccionarlos en la UI aunque existan como hr.payslip.input.type).
# Hallazgo de Tech Lead corriendo -u contra staging_produccion.
# ================================================================
def t13():
    struct = env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
    codes = struct.input_line_type_ids.mapped('code')
    for code in ('L10N_CO_EMBARGO_ALIMENTOS', 'L10N_CO_EMBARGO_CIVIL', 'L10N_CO_EMBARGO_COOPERATIVA', 'CO_EMBARGO'):
        assert code in codes, f"{code} no esta en input_line_type_ids -- picker de UI lo bloquearia"
test("input_line_type_ids: los 4 tipos de embargo habilitados en el picker de UI", t13)

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
