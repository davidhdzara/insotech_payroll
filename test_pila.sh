#!/bin/bash
# ================================================================
# Test exhaustivo: retiro de l10n.co.hr.pila.wizard (v1), doc 25 --
# v2 ya cubre todo lo que le corresponde al aportante segun el Anexo
# Tecnico 2 (Resolucion 2388/2016), v1 generaba registros Tipo 8-12
# que en realidad le corresponden al operador de informacion, no al
# aportante -- ver doc 25 SS1 para la cita completa.
#
# Mismas lecciones aprendidas de los scripts anteriores:
# - odoo-bin se invoca directo, el wrapper() de pruebas hace
#   cr.rollback() defensivo en el except.
# - Verificacion de limpieza de xmlids huerfanos, mismo patron T4 de
#   test_config_settings.sh/test_liquidacion.sh.
#
# NOTA: /tmp/ne_params.tar.gz debe estar actualizado con el diff de
# doc 25 antes de correr este script.
# ================================================================
set -e

# Extraer modulo
cd /home/odoo/src/user/l10n_co_nomina_electronica
rm -rf models/ views/ data/ wizard/ services/ tests/ security/ report/ static/ migrations/ __pycache__/
cd /home/odoo/src/user
tar xzf /tmp/ne_params.tar.gz -C l10n_co_nomina_electronica/

# Actualizar modulo
cd /home/odoo
odoo-bin -d guapante-staging-produccion-37396060 -u l10n_co_nomina_electronica --stop-after-init --no-http 2>&1 | tail -10

echo "========================================"
echo "  MODULO ACTUALIZADO - INICIANDO TESTS"
echo "========================================"

odoo-bin shell -d guapante-staging-produccion-37396060 --no-http <<'PYEOF'
import datetime

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

# ================================================================
# TEST 1: l10n.co.hr.pila.wizard (v1) realmente desaparecio del
# registro de modelos.
# ================================================================
def t1():
    assert 'l10n.co.hr.pila.wizard' not in env, \
        "l10n.co.hr.pila.wizard (v1) deberia haber desaparecido del registro"
test("l10n.co.hr.pila.wizard (v1) eliminado del registro de modelos", t1)

# ================================================================
# TEST 2: vista/accion/menu de v1 realmente eliminados (sin vista
# huerfana -- confirmado en doc 25 que v1 no heredaba de nada
# compartido, pero se verifica igual el cleanup completo).
# ================================================================
def t2():
    for xmlid in (
        'l10n_co_nomina_electronica.view_l10n_co_hr_pila_wizard_form',
        'l10n_co_nomina_electronica.action_l10n_co_hr_pila_wizard',
        'l10n_co_nomina_electronica.menu_l10n_co_hr_pila_wizard',
    ):
        cr.execute("""
            SELECT count(*) FROM ir_model_data
            WHERE module = %s AND name = %s
        """, tuple(xmlid.split('.', 1)))
        assert cr.fetchone()[0] == 0, f"{xmlid} deberia haberse eliminado"

    cr.execute("""
        SELECT count(*) FROM ir_model_access
        WHERE name = 'l10n_co_pila.wizard manager'
    """)
    assert cr.fetchone()[0] == 0, "La ACL de l10n.co.hr.pila.wizard (v1) deberia haberse eliminado"
test("Vista/accion/menu/ACL de v1 realmente eliminados", t2)

# ================================================================
# TEST 3: v2 sigue intacto -- modelo, accion y menu resuelven
# correctamente (confirma que remover v1 no rompio nada compartido:
# imports de services/__init__.py, wizard/__init__.py, manifest).
# ================================================================
def t3():
    assert 'l10n.co.hr.pila.wizard.v2' in env, \
        "l10n.co.hr.pila.wizard.v2 deberia seguir existiendo"
    action = env.ref('l10n_co_nomina_electronica.action_l10n_co_hr_pila_wizard_v2')
    assert action.res_model == 'l10n.co.hr.pila.wizard.v2'
    menu = env.ref('l10n_co_nomina_electronica.menu_l10n_co_hr_pila_wizard_v2')
    assert menu.action.id == action.id, \
        f"El menu deberia apuntar a la accion de v2, apunta a {menu.action}"
test("l10n.co.hr.pila.wizard.v2 (modelo/accion/menu) sigue intacto", t3)

# ================================================================
# TEST 4: flujo real de v2 de punta a punta (borrador -> validado ->
# [generado, si los datos del empleado real ya estan completos]) --
# confirma que el generador (pila_generator_v2, sin cambios) y el
# wizard siguen funcionando con una nomina real recien confirmada.
# ================================================================
def t4():
    struct_regular = env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
    contract = env['hr.contract'].search([
        ('state', '=', 'open'), ('company_id', '=', company.id),
    ], limit=1)
    assert contract, "No hay contrato abierto real -- no se puede probar"
    emp = contract.employee_id
    today = datetime.date.today()

    ps = env['hr.payslip'].create({
        'name': 'TEST PILA v2',
        'employee_id': emp.id,
        'contract_id': contract.id,
        'struct_id': struct_regular.id,
        'date_from': today.replace(day=1),
        'date_to': today,
    })
    ps.compute_sheet()
    ps.action_payslip_done()
    assert ps.state == 'done', f"El payslip deberia quedar done, esta {ps.state}"

    wizard = env['l10n.co.hr.pila.wizard.v2'].create({
        'year': str(today.year),
        'month': '%02d' % today.month,
        'company_id': company.id,
    })
    assert wizard.state == 'draft'

    wizard.action_validate()
    assert wizard.state == 'validated', \
        f"El wizard deberia avanzar a 'validated', esta {wizard.state}"
    assert wizard.summary_total_employees >= 1, \
        "El resumen deberia contar al menos 1 empleado (el payslip recien confirmado)"

    if wizard.validation_ok:
        wizard.action_generate_pila()
        assert wizard.state == 'generated', \
            f"El wizard deberia avanzar a 'generated', esta {wizard.state}"
        assert wizard.file_data, "Deberia haberse generado el archivo PILA"
    else:
        # Dato real preexistente (no relacionado a este cambio): el
        # empleado real usado para la prueba no tiene todos los
        # codigos PILA (EPS/AFP/CCF) configurados. No es un fallo del
        # retiro de v1 -- se documenta, no se fuerza con datos falsos.
        results.append(
            f"       (info) validation_ok=False para el empleado real de prueba -- "
            f"errores: {wizard.validation_errors!r} -- dato preexistente, no relacionado a doc 25"
        )
test("Flujo real v2: borrador -> validado -> (generado si los datos del empleado ya estan completos)", t4)

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

cr.rollback()

PYEOF
