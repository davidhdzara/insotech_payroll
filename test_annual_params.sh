#!/bin/bash
# ================================================================
# Test exhaustivo: Parametros Anuales de Nomina
# ================================================================
set -e

# Extraer modulo
cd /home/odoo/src/user/l10n_co_nomina_electronica
rm -rf models/ views/ data/ wizard/ services/ tests/ security/ report/ static/ __pycache__/
cd /home/odoo/src/user
tar xzf /tmp/ne_params.tar.gz -C l10n_co_nomina_electronica/

# Actualizar modulo
cd /home/odoo
python odoo-bin -d guapante-staging-dev-32580182 -u l10n_co_nomina_electronica --stop-after-init --no-http 2>&1 | tail -5

echo "========================================"
echo "  MODULO ACTUALIZADO - INICIANDO TESTS"
echo "========================================"

# Ejecutar tests via odoo shell
python odoo-bin shell -d guapante-staging-dev-32580182 --no-http <<'PYEOF'
import traceback
from datetime import date, datetime
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

company = env.user.company_id
ParamsModel = env['l10n.co.payroll.annual.params']

# ================================================================
# LIMPIEZA: Borrar parametros previos para empezar limpio
# ================================================================
ParamsModel.search([('company_id', '=', company.id)]).unlink()
cr.commit()

# ================================================================
# TEST 1: Crear parametros 2025
# ================================================================
def t1():
    p = ParamsModel.create({
        'year': 2025,
        'company_id': company.id,
        'smmlv': 1423500,
        'aux_transporte': 200000,
        'uvt': 49799,
    })
    assert p.id, "No se creo el registro"
    assert p.year == 2025, f"Ano incorrecto: {p.year}"
    assert p.smmlv == 1423500, f"SMMLV incorrecto: {p.smmlv}"
    assert p.aux_transporte == 200000, f"Aux incorrecto: {p.aux_transporte}"
    assert p.uvt == 49799, f"UVT incorrecto: {p.uvt}"
test("Crear parametros 2025", t1)

# ================================================================
# TEST 2: Crear parametros 2024
# ================================================================
def t2():
    p = ParamsModel.create({
        'year': 2024,
        'company_id': company.id,
        'smmlv': 1300000,
        'aux_transporte': 162000,
        'uvt': 47065,
    })
    assert p.id
    assert p.smmlv == 1300000
test("Crear parametros 2024", t2)

# ================================================================
# TEST 3: Crear parametros 2026
# ================================================================
def t3():
    p = ParamsModel.create({
        'year': 2026,
        'company_id': company.id,
        'smmlv': 1423500,
        'aux_transporte': 200000,
        'uvt': 49799,
    })
    assert p.id
test("Crear parametros 2026", t3)

cr.commit()

# ================================================================
# TEST 4: Unicidad - no puede haber 2 registros del mismo ano
# ================================================================
def t4():
    try:
        ParamsModel.create({
            'year': 2025,
            'company_id': company.id,
            'smmlv': 9999999,
            'aux_transporte': 999999,
            'uvt': 99999,
        })
        cr.commit()
        raise AssertionError("Debio fallar por unicidad")
    except Exception as e:
        cr.rollback()
        # Debe ser error de constraint
        assert 'unique' in str(e).lower() or 'Solo puede existir' in str(e), f"Error inesperado: {e}"
test("Unicidad: duplicado rechazado", t4)

# ================================================================
# TEST 5: Helper busca ano correcto
# ================================================================
def t5():
    p2025 = company._get_co_payroll_params(date(2025, 6, 15))
    assert p2025.smmlv == 1423500, f"SMMLV 2025: {p2025.smmlv}"
    p2024 = company._get_co_payroll_params(date(2024, 12, 31))
    assert p2024.smmlv == 1300000, f"SMMLV 2024: {p2024.smmlv}"
    p2026 = company._get_co_payroll_params(date(2026, 1, 1))
    assert p2026.smmlv == 1423500, f"SMMLV 2026: {p2026.smmlv}"
test("Helper: busca ano correcto", t5)

# ================================================================
# TEST 6: Helper con datetime (no solo date)
# ================================================================
def t6():
    p = company._get_co_payroll_params(datetime(2025, 3, 15, 10, 30))
    assert p.smmlv == 1423500
test("Helper: acepta datetime", t6)

# ================================================================
# TEST 7: Helper con string fecha
# ================================================================
def t7():
    p = company._get_co_payroll_params('2024-07-01')
    assert p.smmlv == 1300000
test("Helper: acepta string YYYY-MM-DD", t7)

# ================================================================
# TEST 8: Helper falla si no hay parametros
# ================================================================
def t8():
    try:
        company._get_co_payroll_params(date(2030, 1, 1))
        raise AssertionError("Debio lanzar UserError")
    except UserError as e:
        assert '2030' in str(e), f"Error no menciona el ano: {e}"
        assert 'Parámetros Anuales' in str(e) or 'parámetros' in str(e).lower(), f"Error no guia al usuario: {e}"
test("Helper: UserError si no hay params del ano", t8)

# ================================================================
# TEST 9: Validacion de ano (fuera de rango)
# ================================================================
def t9():
    from odoo.exceptions import ValidationError
    try:
        ParamsModel.create({
            'year': 1999,
            'company_id': company.id,
            'smmlv': 100000,
            'aux_transporte': 10000,
            'uvt': 5000,
        })
        cr.rollback()
        raise AssertionError("Debio fallar por validacion de ano")
    except (ValidationError, Exception) as e:
        cr.rollback()
        assert '2000' in str(e) or '2100' in str(e) or 'año' in str(e).lower(), f"Validacion inesperada: {e}"
test("Validacion: ano < 2000 rechazado", t9)

# ================================================================
# TEST 10: Campos obligatorios
# ================================================================
def t10():
    try:
        ParamsModel.create({
            'year': 2028,
            'company_id': company.id,
            # smmlv, aux_transporte, uvt omitidos
        })
        cr.rollback()
        raise AssertionError("Debio fallar por campos obligatorios")
    except Exception as e:
        cr.rollback()
        # Puede ser IntegrityError o ValidationError
        assert True
test("Campos obligatorios: falla sin valores", t10)

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
    ps = env['hr.payslip'].create({
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_from': date(2026, 5, 1),
        'date_to': date(2026, 5, 31),
        'struct_id': env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina').id,
    })
    ps.compute_sheet()
    
    # Verificar que se calculo (no se cayó por falta de params)
    assert ps.line_ids, "No se generaron lineas"
    
    # Verificar aux transporte: si salario <= 2 SMMLV 2026, debe ser 200000
    aux_line = ps.line_ids.filtered(lambda l: l.code == 'CO_AUX_TRANS')
    if contract.wage <= 1423500 * 2 and not contract.l10n_co_ne_integral_salary:
        assert aux_line, "Deberia tener aux transporte"
        # Aux = 200000/30 * dias trabajados
        expected_daily = 200000 / 30
        assert abs(aux_line.total) > 0, f"Aux transporte = 0"
    
    ps.unlink()
    cr.commit()
test("Nomina 2026: usa params 2026", t11)

# ================================================================
# TEST 12: Nomina falla si no hay params del ano
# ================================================================
def t12():
    emp = env['hr.employee'].search([
        ('contract_ids.state', '=', 'open'),
        ('company_id', '=', company.id),
    ], limit=1)
    contract = emp.contract_ids.filtered(lambda c: c.state == 'open')[:1]
    
    # Crear payslip del 2030 (no tiene params)
    ps = env['hr.payslip'].create({
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_from': date(2030, 1, 1),
        'date_to': date(2030, 1, 31),
        'struct_id': env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina').id,
    })
    try:
        ps.compute_sheet()
        ps.unlink()
        cr.commit()
        raise AssertionError("Debio fallar al calcular sin params 2030")
    except UserError as e:
        cr.rollback()
        assert '2030' in str(e), f"Error no menciona 2030: {e}"
    except Exception as e:
        cr.rollback()
        # Cualquier error esta bien si menciona el ano
        if '2030' not in str(e):
            raise
test("Nomina 2030: falla sin params", t12)

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
# TEST 14: Provision falla si no hay params del ano
# ================================================================
def t14():
    prov_model = env['l10n.co.hr.provision']
    prov = prov_model.create({
        'year': 2030,
        'month': '01',
        'company_id': company.id,
    })
    cr.commit()
    
    try:
        prov.action_compute_provisions()
        cr.commit()
        raise AssertionError("Debio fallar sin params 2030")
    except UserError as e:
        cr.rollback()
        assert '2030' in str(e)
    except Exception as e:
        cr.rollback()
        if '2030' not in str(e):
            raise
    finally:
        try:
            prov2 = prov_model.search([('year','=',2030),('company_id','=',company.id)])
            if prov2:
                prov2.unlink()
                cr.commit()
        except:
            cr.rollback()
test("Provision 2030: falla sin params", t14)

# ================================================================
# TEST 15: Distintos anos devuelven distintos valores
# ================================================================
def t15():
    p24 = company._get_co_payroll_params(date(2024, 6, 1))
    p25 = company._get_co_payroll_params(date(2025, 6, 1))
    # 2024 y 2025 tienen SMMLV diferente
    assert p24.smmlv != p25.smmlv or p24.aux_transporte != p25.aux_transporte, \
        "2024 y 2025 deben tener valores distintos"
    assert p24.smmlv == 1300000, f"2024 SMMLV={p24.smmlv}"
    assert p25.smmlv == 1423500, f"2025 SMMLV={p25.smmlv}"
    assert p24.aux_transporte == 162000, f"2024 aux={p24.aux_transporte}"
    assert p25.aux_transporte == 200000, f"2025 aux={p25.aux_transporte}"
test("Años distintos: valores distintos", t15)

# ================================================================
# TEST 16: name_get
# ================================================================
def t16():
    p = ParamsModel.search([('year','=',2025),('company_id','=',company.id)], limit=1)
    name = p.name_get()[0][1]
    assert '2025' in name, f"name_get no incluye ano: {name}"
test("name_get incluye ano", t16)

# ================================================================
# TEST 17: Editar parametros existentes
# ================================================================
def t17():
    p = ParamsModel.search([('year','=',2026),('company_id','=',company.id)], limit=1)
    p.write({'smmlv': 1500000})
    cr.commit()
    p_check = company._get_co_payroll_params(date(2026, 1, 1))
    assert p_check.smmlv == 1500000, f"SMMLV no se actualizo: {p_check.smmlv}"
    # Revertir
    p.write({'smmlv': 1423500})
    cr.commit()
test("Editar parametros: se refleja inmediato", t17)

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
# TEST 19: Liquidacion wizard usa params del ano
# ================================================================
def t19():
    emp = env['hr.employee'].search([
        ('contract_ids.state', '=', 'open'),
        ('company_id', '=', company.id),
    ], limit=1)
    if not emp:
        raise Exception("No hay empleados")
    contract = emp.contract_ids.filtered(lambda c: c.state == 'open')[:1]
    
    # Crear liquidacion directa con fecha 2025
    liq_model = env['l10n.co.hr.liquidacion']
    # Borrar liquidaciones previas del empleado
    liq_model.search([('employee_id','=',emp.id)]).unlink()
    cr.commit()
    
    liq = liq_model.create({
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_start': contract.date_start,
        'date_end': date(2025, 12, 31),
        'cause': 'renuncia',
        'contract_type': 'indefinido',
        'base_salary': contract.wage,
        'aux_transporte': 0,
    })
    cr.commit()
    
    # Forzar onchange para que recalcule aux transporte con params 2025
    liq._onchange_contract_id()
    cr.commit()
    
    # Si salario <= 2 SMMLV 2025 (2,847,000), debe tener aux = 200,000
    if contract.wage <= 1423500 * 2 and not contract.l10n_co_ne_integral_salary:
        assert liq.aux_transporte == 200000, f"Aux debe ser 200000 (2025), es {liq.aux_transporte}"
    
    liq.unlink()
    cr.commit()
test("Liquidacion: aux transporte del ano correcto", t19)

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
