#!/bin/bash
# ================================================================
# Test exhaustivo: config de Nomina Electronica movida de la ficha de
# compania (Ajustes Generales) a Ajustes > Nomina (doc 19).
#
# El dato real sigue en res.company -- res.config.settings solo lo
# expone en otro lugar via related + readonly=False (mismo patron que
# l10n_co_dian). Este script no puede probar el renderizado visual del
# formulario (eso se confirma en pantalla real), pero si puede probar
# que el mecanismo de related+readonly=False funciona de verdad: leer
# el valor actual de la compania a traves del settings wizard, y
# escribir un valor nuevo a traves del settings wizard y confirmar que
# persiste en res.company.
#
# Mismas lecciones aprendidas de los scripts anteriores:
# - odoo-bin se invoca directo, el wrapper() de pruebas hace
#   cr.rollback() defensivo en el except.
#
# NOTA: /tmp/ne_params.tar.gz debe estar actualizado con el diff de
# doc 19 antes de correr este script.
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
Settings = env['res.config.settings']

_RELATED_FIELDS = (
    'l10n_co_ne_software_id',
    'l10n_co_ne_software_pin',
    'l10n_co_ne_test_set_id',
    'l10n_co_ne_environment',
    'l10n_co_ne_payroll_prefix',
    'l10n_co_ne_adjust_prefix',
    'l10n_co_ne_sequence_id',
    'l10n_co_ne_pre_sequence_id',
    'l10n_co_ne_certificate_id',
    'l10n_co_ugpp_legal_nature',
    'l10n_co_ugpp_contributor_type',
    'l10n_co_ugpp_special_autoretention',
    'l10n_co_ne_exoneration_1607',
    'l10n_co_pila_tipo_aportante',
    'l10n_co_pila_arl_code',
    'l10n_co_pila_forma_presentacion',
    'l10n_co_pila_codigo_sucursal',
    'l10n_co_pila_nombre_sucursal',
    'l10n_co_pila_operador_code',
)

# ================================================================
# TEST 1: los 19 campos related existen en res.config.settings y son
# escribibles (readonly=False) -- no solo existen como definicion.
# ================================================================
def t1():
    for fname in _RELATED_FIELDS:
        assert fname in Settings._fields, f"{fname} no existe en res.config.settings"
        field = Settings._fields[fname]
        assert field.related, f"{fname} deberia ser un campo related"
        assert not field.readonly, f"{fname} deberia tener readonly=False"
test("Los 19 campos related existen en res.config.settings y son escribibles", t1)

# ================================================================
# TEST 2: abrir el settings wizard refleja el valor real ya guardado
# en res.company (lectura a traves del related).
# ================================================================
def t2():
    original_prefix = company.l10n_co_ne_payroll_prefix
    company.write({'l10n_co_ne_payroll_prefix': 'NETEST'})
    cr.commit()
    try:
        settings = Settings.create({'company_id': company.id})
        assert settings.l10n_co_ne_payroll_prefix == 'NETEST', \
            f"El settings wizard no reflejo el valor real de la compania: {settings.l10n_co_ne_payroll_prefix}"
    finally:
        company.write({'l10n_co_ne_payroll_prefix': original_prefix})
        cr.commit()
test("res.config.settings refleja el valor real ya guardado en res.company", t2)

# ================================================================
# TEST 3: escribir un valor a traves del settings wizard persiste en
# res.company -- confirma que readonly=False realmente habilita la
# escritura de ida y vuelta, no solo la lectura.
# ================================================================
def t3():
    original_prefix = company.l10n_co_ne_payroll_prefix
    try:
        settings = Settings.create({
            'company_id': company.id,
            'l10n_co_ne_payroll_prefix': 'NETEST2',
        })
        cr.commit()
        company.invalidate_recordset(['l10n_co_ne_payroll_prefix'])
        assert company.l10n_co_ne_payroll_prefix == 'NETEST2', \
            f"El valor escrito via settings no persistio en res.company: {company.l10n_co_ne_payroll_prefix}"
    finally:
        company.write({'l10n_co_ne_payroll_prefix': original_prefix})
        cr.commit()
test("Escribir en res.config.settings persiste el valor real en res.company", t3)

# ================================================================
# TEST 4: la vista vieja (pestana en la ficha de compania) realmente
# eliminada -- mismo patron que T9 de test_embargo.sh.
# ================================================================
def t4():
    cr.execute("""
        SELECT count(*) FROM ir_model_data
        WHERE module = 'l10n_co_nomina_electronica'
          AND name = 'view_company_form_ne'
          AND model = 'ir.ui.view'
    """)
    assert cr.fetchone()[0] == 0, \
        "view_company_form_ne deberia haberse eliminado (pre-migrate 18.0.3.0.7)"
test("Vista vieja de la ficha de compania (view_company_form_ne) realmente eliminada", t4)

# ================================================================
# TEST 5: la nueva vista de Ajustes > Nomina existe y hereda del punto
# correcto (hr_payroll.res_config_settings_view_form).
# ================================================================
def t5():
    view = env.ref('l10n_co_nomina_electronica.res_config_settings_view_form')
    parent = env.ref('hr_payroll.res_config_settings_view_form')
    assert view.inherit_id.id == parent.id, \
        f"La vista deberia heredar de hr_payroll.res_config_settings_view_form, hereda de {view.inherit_id.name}"
    assert view.model == 'res.config.settings'
test("Nueva vista de Ajustes > Nomina hereda del punto correcto (hr_payroll)", t5)

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
