#!/bin/bash
# ================================================================
# Test exhaustivo: bug critico de CO_BRUTO/CO_NETO en la estructura
# principal "Nomina Colombia - General" (encontrado armando el mapeo
# contable de doc 23, sin relacion con contabilidad -- es un bug del
# motor de calculo).
#
# CO_BRUTO ("Total Devengados") tenia category_id = hr_salary_rule_
# category_devengados (DEV), la MISMA categoria que lee en su propia
# formula (result = categories['DEV']). Como CO_NETO (que corre
# despues) TAMBIEN lee categories['DEV'], el subtotal de CO_BRUTO se
# sumaba una segunda vez dentro de esa categoria antes de que CO_NETO
# la leyera -- el empleado quedaba pagando casi el doble del neto real.
#
# Nunca se detecto porque nunca se confirmo un payslip real a 'done'
# en produccion, y porque test_estructuras_especiales.sh solo cubre las
# 3 estructuras especiales (Prima/Liquidacion/Bonificacion), no esta
# (Nomina Colombia - General) -- este script cierra ese hueco de
# cobertura para que no se repita.
#
# Fix: nueva categoria standalone TOT_DISPLAY (sin parent_id, mismo
# criterio que SS_CIA/PROV) para CO_BRUTO -- sigue leyendo
# categories['DEV'] para mostrar el total correcto, pero su propio
# resultado ya no se re-inyecta en 'DEV'.
#
# Mismas lecciones aprendidas de los scripts anteriores:
# - odoo-bin se invoca directo, el wrapper() de pruebas hace
#   cr.rollback() defensivo en el except.
# - Reconstruccion independiente del NETO via arbol de categorias
#   (mismo patron _is_descendant/_reconstruct_neto que
#   test_estructuras_especiales.sh para Prima/Liquidacion/Bonificacion).
#
# NOTA: /tmp/ne_params.tar.gz debe estar actualizado con el diff del
# fix de CO_BRUTO antes de correr este script.
# ================================================================
set -e

# Extraer modulo
cd /home/odoo/src/user/l10n_co_nomina_electronica
rm -rf models/ views/ data/ wizard/ services/ tests/ security/ report/ static/ migrations/ __pycache__/
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
struct_regular = env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
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

cat_dev = env.ref('l10n_co_nomina_electronica.hr_salary_rule_category_devengados')
cat_dedu = env.ref('l10n_co_nomina_electronica.hr_salary_rule_category_deducciones')

def _is_descendant(cat, root_id):
    cur = cat
    while cur:
        if cur.id == root_id:
            return True
        cur = cur.parent_id
    return False

def _reconstruct_total(ps, *root_cats, exclude_codes=()):
    """Reconstruye un total sumando independientemente las lineas cuyas
    categorias descienden de root_cats, excluyendo por codigo las
    lineas 'subtotal' que no deben contarse dos veces (CO_BRUTO/CO_NETO)."""
    root_ids = [c.id for c in root_cats]
    lines = ps.line_ids.filtered(
        lambda l: l.code not in exclude_codes and any(_is_descendant(l.category_id, rid) for rid in root_ids)
    )
    return sum(lines.mapped('total'))

def _make_payslip(name):
    return env['hr.payslip'].create({
        'name': name,
        'employee_id': emp.id,
        'contract_id': contract.id,
        'date_from': _REF_DATE.replace(day=1),
        'date_to': _REF_DATE,
        'struct_id': struct_regular.id,
    })

# ================================================================
# TEST 1: CO_BRUTO ya NO pertenece a la categoria DEV (categoria
# standalone TOT_DISPLAY, sin parent_id) -- regresion directa contra
# el fix especifico, no solo contra el sintoma.
# ================================================================
def t1():
    rule_bruto = env.ref('l10n_co_nomina_electronica.hr_salary_rule_co_bruto')
    assert rule_bruto.category_id.code == 'TOT_DISPLAY', \
        f"CO_BRUTO deberia estar en TOT_DISPLAY, esta en {rule_bruto.category_id.code}"
    assert not rule_bruto.category_id.parent_id, \
        "TOT_DISPLAY deberia ser standalone (sin parent_id), igual que SS_CIA/PROV"
test("CO_BRUTO usa la categoria standalone TOT_DISPLAY (sin parent_id)", t1)

# ================================================================
# TEST 2: CO_BRUTO muestra el total correcto (reconstruido de forma
# independiente via arbol de categorias) -- el fix no debe cambiar lo
# que se muestra, solo lo que se acumula para CO_NETO.
# ================================================================
def t2():
    original_wage = contract.wage
    original_integral = contract.l10n_co_ne_integral_salary
    contract.write({'wage': _SMMLV * 1.5, 'l10n_co_ne_integral_salary': False})
    cr.commit()
    ps = _make_payslip('Test Nomina General - CO_BRUTO')
    try:
        ps.compute_sheet()
        bruto_line = ps.line_ids.filtered(lambda l: l.code == 'CO_BRUTO')
        assert bruto_line, "No se genero CO_BRUTO"
        expected_bruto = _reconstruct_total(ps, cat_dev, exclude_codes=('CO_BRUTO', 'CO_NETO'))
        assert abs(bruto_line.total - expected_bruto) < 0.01, \
            f"CO_BRUTO ({bruto_line.total}) no coincide con el total reconstruido de DEV ({expected_bruto})"
    finally:
        ps.write({'state': 'draft'})
        ps.unlink()
        contract.write({'wage': original_wage, 'l10n_co_ne_integral_salary': original_integral})
        cr.commit()
test("CO_BRUTO coincide con el total reconstruido de DEV (sin auto-inclusion)", t2)

# ================================================================
# TEST 3: CO_NETO ya NO duplica CO_BRUTO -- debe coincidir con
# DEV_reconstruido + DEDU_reconstruido (ambos excluyendo las lineas
# subtotal por codigo), NO con el doble.
# ================================================================
def t3():
    original_wage = contract.wage
    original_integral = contract.l10n_co_ne_integral_salary
    contract.write({'wage': _SMMLV * 1.5, 'l10n_co_ne_integral_salary': False})
    cr.commit()
    ps = _make_payslip('Test Nomina General - CO_NETO')
    try:
        ps.compute_sheet()
        neto_line = ps.line_ids.filtered(lambda l: l.code == 'CO_NETO')
        assert neto_line, "No se genero CO_NETO"

        expected_dev = _reconstruct_total(ps, cat_dev, exclude_codes=('CO_BRUTO', 'CO_NETO'))
        expected_dedu = _reconstruct_total(ps, cat_dedu, exclude_codes=('CO_BRUTO', 'CO_NETO'))
        expected_neto = expected_dev + expected_dedu

        # Verificacion explicita del bug historico: el neto NO debe ser
        # aproximadamente el doble de lo esperado (si el fix se revierte
        # por error, este assert lo detecta de inmediato).
        assert abs(neto_line.total - expected_neto * 2) > 1.0, \
            "CO_NETO parece estar duplicando el total otra vez -- revisar category_id de CO_BRUTO"
        assert abs(neto_line.total - expected_neto) < 0.01, \
            f"CO_NETO ({neto_line.total}) no coincide con DEV+DEDU reconstruido ({expected_neto})"
    finally:
        ps.write({'state': 'draft'})
        ps.unlink()
        contract.write({'wage': original_wage, 'l10n_co_ne_integral_salary': original_integral})
        cr.commit()
test("CO_NETO coincide con DEV+DEDU reconstruido, sin duplicar CO_BRUTO", t3)

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
