#!/bin/bash
# ================================================================
# Test exhaustivo: config de Nomina Electronica en Ajustes > Nomina,
# ahora con paridad visual/estructural con Facturacion Electronica (CO)
# (doc 22, sobre lo ya construido en doc 19/21).
#
# Cambios de esquema reales en este ciclo (a diferencia de doc 21, que
# era solo vista + domain):
# - l10n_co_ne_software_id/_software_pin/_test_set_id (planos en
#   res.company) -> eliminados, migrados a l10n.co.ne.operation_mode
#   (1 fila fija por compania, sin Selection de tipo de documento --
#   Nomina Individual y Nota de Ajuste comparten siempre el mismo modo).
# - l10n_co_ne_certificate_ids (O2M nuevo, mismo patron sin filtro que
#   l10n_co_dian_certificate_ids) se agrega como tabla visual.
#   ACTUALIZADO 2026-09-12: el Many2one l10n_co_ne_certificate_id (doc 22
#   §2 Opcion B, seleccion explicita) se retiro -- paridad real con
#   Facturacion Electronica, que no tiene equivalente y toma siempre el
#   ultimo certificado de la lista. res.company._get_ne_certificate()
#   reemplaza su uso en el flujo de firma (ver T6 reescrito mas abajo).
# - l10n_co_ne_environment (Selection) se mantiene como unica fuente de
#   verdad; l10n_co_ne_test_environment (Boolean, computed+inverse) se
#   agrega para exponerla como checkbox sin duplicar el dato.
# - l10n_co_ne_certification_process (Boolean, nuevo, stored) gatea de
#   verdad action_send_test_set() -- no es decorativo.
#
# Requiere migrations/18.0.3.0.10/post-migrate.py corrido (migra los
# datos ya cargados de software_id/pin/test_set_id a operation_mode, y
# activa certification_process para compañías que ya tenían TestSetID).
#
# Mismas lecciones aprendidas de los scripts anteriores:
# - odoo-bin se invoca directo, el wrapper() de pruebas hace
#   cr.rollback() defensivo en el except.
# - Aislar la variable bajo prueba, restaurando en finally.
#
# NOTA: /tmp/ne_params.tar.gz debe estar actualizado con el diff de
# doc 19 + doc 21 + doc 22 antes de correr este script.
# ================================================================
set -e

# Extraer modulo
cd /home/odoo/src/user/l10n_co_nomina_electronica
rm -rf models/ views/ data/ wizard/ services/ tests/ security/ report/ static/ migrations/ __pycache__/
cd /home/odoo/src/user
tar xzf /tmp/ne_params.tar.gz -C l10n_co_nomina_electronica/

# Actualizar modulo
cd /home/odoo
odoo-bin -d guapante-staging-produccion-37396060 -u l10n_co_nomina_electronica --stop-after-init --no-http 2>&1 | tail -15

echo "========================================"
echo "  MODULO ACTUALIZADO - INICIANDO TESTS"
echo "========================================"

odoo-bin shell -d guapante-staging-produccion-37396060 --no-http <<'PYEOF'
from odoo.tools.safe_eval import safe_eval

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
OperationMode = env['l10n.co.ne.operation_mode']

# ================================================================
# TEST 1: los campos nuevos existen en res.config.settings, con el
# tipo/escritura correcta.
# ================================================================
def t1():
    checks = {
        'l10n_co_ne_operation_mode_ids': 'one2many',
        'l10n_co_ne_certificate_ids': 'one2many',
        'l10n_co_ne_test_environment': 'boolean',
        'l10n_co_ne_certification_process': 'boolean',
    }
    for fname, ftype in checks.items():
        assert fname in Settings._fields, f"{fname} no existe en res.config.settings"
        field = Settings._fields[fname]
        assert field.type == ftype, f"{fname} deberia ser {ftype}, es {field.type}"
        assert field.related, f"{fname} deberia ser un campo related"
        assert not field.readonly, f"{fname} deberia tener readonly=False"
test("Campos nuevos (operation_mode_ids/certificate_ids/test_environment/certification_process) existen y son escribibles", t1)

# ================================================================
# TEST 2: abrir el settings wizard refleja los datos reales ya
# migrados por post-migrate.py (software_id/pin de la compañía real).
# ================================================================
def t2():
    settings = Settings.create({'company_id': company.id})
    mode = settings.l10n_co_ne_operation_mode_ids
    assert mode, "El settings wizard no trae ningun Modo de Operacion -- deberia existir desde la migracion"
    assert len(mode) == 1, f"Deberia haber exactamente 1 modo de operacion, hay {len(mode)}"
    assert mode.software_id, "software_id deberia venir poblado desde la migracion"
test("res.config.settings refleja el Modo de Operacion ya migrado", t2)

# ================================================================
# TEST 3: escribir en operation_mode a traves del settings wizard
# persiste en l10n.co.ne.operation_mode -- confirma readonly=False de
# ida y vuelta, no solo lectura.
# ================================================================
def t3():
    original_mode = company.l10n_co_ne_operation_mode_ids
    original_vals = {
        'software_id': original_mode.software_id,
        'software_pin': original_mode.software_pin,
        'test_set_id': original_mode.test_set_id,
    } if original_mode else None
    try:
        settings = Settings.create({
            'company_id': company.id,
            'l10n_co_ne_operation_mode_ids': [(1, original_mode.id, {
                'software_id': 'NETEST-ID',
                'software_pin': 'NETEST-PIN',
            })] if original_mode else [(0, 0, {
                'software_id': 'NETEST-ID',
                'software_pin': 'NETEST-PIN',
            })],
        })
        cr.commit()
        company.invalidate_recordset(['l10n_co_ne_operation_mode_ids'])
        mode = company.l10n_co_ne_operation_mode_ids
        assert mode.software_id == 'NETEST-ID', \
            f"El software_id escrito via settings no persistio: {mode.software_id}"
        assert mode.software_pin == 'NETEST-PIN'
    finally:
        if original_vals:
            company.l10n_co_ne_operation_mode_ids.write(original_vals)
        else:
            company.l10n_co_ne_operation_mode_ids.unlink()
        cr.commit()
test("Escribir Modo de Operacion en res.config.settings persiste en l10n.co.ne.operation_mode", t3)

# ================================================================
# TEST 4: l10n_co_ne_test_environment (computed+inverse) traduce
# correctamente hacia/desde l10n_co_ne_environment en ambas direcciones,
# sin perder el dato real (mismo campo Selection de siempre).
# ================================================================
def t4():
    original_env = company.l10n_co_ne_environment
    mode = company.l10n_co_ne_operation_mode_ids
    original_test_set_id = mode.test_set_id if mode else None
    try:
        # El write de environment 1->2 mas abajo SI es un cambio real de
        # valor (a diferencia del primero, que deja el mismo '2' que ya
        # tenia la compania real) -- dispara _check_test_set_id de
        # verdad. La compania real (Guapante) tiene operation_mode con
        # software configurado pero test_set_id vacio (dato preexistente
        # incompleto, documentado en post-migrate.py) -- sin esto, el
        # segundo write de esta prueba chocaria con esa validacion real,
        # no con un bug de esta prueba. Hallazgo de Tech Lead corrido
        # contra el servidor: T4 fallaba por esto, no por el mecanismo
        # computed+inverse (que si funciona, la traduccion 2->1 ya pasaba).
        if mode and not mode.test_set_id:
            mode.write({'test_set_id': 'TEST-SET-ID-T4'})
            cr.commit()

        company.write({'l10n_co_ne_environment': '2'})
        cr.commit()
        settings = Settings.create({'company_id': company.id})
        assert settings.l10n_co_ne_test_environment is True, \
            "test_environment deberia ser True cuando environment='2'"

        settings.write({'l10n_co_ne_test_environment': False})
        cr.commit()
        company.invalidate_recordset(['l10n_co_ne_environment'])
        assert company.l10n_co_ne_environment == '1', \
            f"Escribir test_environment=False deberia dejar environment='1', quedo '{company.l10n_co_ne_environment}'"

        settings2 = Settings.create({'company_id': company.id})
        settings2.write({'l10n_co_ne_test_environment': True})
        cr.commit()
        company.invalidate_recordset(['l10n_co_ne_environment'])
        assert company.l10n_co_ne_environment == '2', \
            f"Escribir test_environment=True deberia dejar environment='2', quedo '{company.l10n_co_ne_environment}'"
    finally:
        company.write({'l10n_co_ne_environment': original_env})
        if mode and original_test_set_id != mode.test_set_id:
            mode.write({'test_set_id': original_test_set_id})
        cr.commit()
test("l10n_co_ne_test_environment computed+inverse traduce correctamente en ambas direcciones", t4)

# ================================================================
# TEST 5: los 3 campos planos viejos realmente desaparecieron de
# res.company, y el modelo/campos nuevos estan bien registrados.
# ================================================================
def t5():
    for fname in ('l10n_co_ne_software_id', 'l10n_co_ne_software_pin', 'l10n_co_ne_test_set_id'):
        assert fname not in env['res.company']._fields, \
            f"{fname} deberia haber desaparecido de res.company"

    assert 'l10n.co.ne.operation_mode' in env, "l10n.co.ne.operation_mode deberia existir"
    mode_fields = env['l10n.co.ne.operation_mode']._fields
    for fname in ('software_id', 'software_pin', 'test_set_id', 'company_id'):
        assert fname in mode_fields, f"l10n.co.ne.operation_mode deberia tener {fname}"
    # UNIQUE(company_id): confirma que la tabla es de 1 fila fija, sin
    # Selection de tipo de documento (doc 22 §1, confirmado por Tech Lead).
    assert 'operation_mode' not in mode_fields, \
        "l10n.co.ne.operation_mode NO deberia tener un campo Selection de tipo de documento"
test("Campos planos viejos eliminados de res.company; l10n.co.ne.operation_mode bien registrado (sin Selection)", t5)

# ================================================================
# TEST 6 (reescrito 2026-09-12): _get_ne_certificate() reemplaza al
# Many2one de seleccion explicita retirado (doc 22 §2 Opcion B, ya no
# vigente) -- mismo criterio que Facturacion Electronica (l10n_co_dian:
# certificates_sudo[-1], el ULTIMO de la lista). No se prueba con un
# segundo certificado sintetico: certificate.certificate.content es
# required=True (contenido X.509 real) y .copy() falla desencriptando
# el pkcs12_password enmascarado por el ORM (mismo hallazgo ya
# documentado en test_certificado.sh T4) -- generar uno de verdad solo
# para probar un slice de lista no vale el riesgo/complejidad. Se
# prueba con el unico certificado real (caso que SI importa: que el
# metodo funcione con la configuracion real de Guapante) y con una
# compania en memoria sin certificados (caso "sin certificado",
# complementa el T3 de test_certificado.sh que prueba lo mismo a nivel
# de _validate_company_ne_config). Se usa `.new()`, no `.create()`:
# `.create()` sobre res.company dispara hooks de hr_payroll que crean
# hr.payroll.note ligadas a la compania y el `.unlink()` posterior falla
# por FK (hallazgo real corrido en test_certificado.sh T3) -- `.new()`
# no inserta nada, alcanza porque _get_ne_certificate() solo lee.
# ================================================================
def t6():
    real_cert = env['certificate.certificate'].search([('company_id', '=', company.id)], limit=1)
    assert real_cert, "No hay ningun certificate.certificate real para probar -- ajustar la prueba"
    assert company._get_ne_certificate() == real_cert, \
        "Con un solo certificado, _get_ne_certificate() deberia devolver ese"

    empty_company = env['res.company'].new({'name': 'NE Test Sin Certificado (en memoria)'})
    assert not empty_company._get_ne_certificate(), \
        "Una compania sin certificados deberia devolver un recordset vacio, no error"
test("_get_ne_certificate() devuelve el certificado real, y vacio sin certificados (paridad con Facturacion Electronica)", t6)

# ================================================================
# TEST 7: l10n_co_ne_certification_process gatea de verdad
# action_send_test_set() -- False bloquea con el mensaje nuevo, True
# deja pasar al siguiente guard existente (falta ID de Pruebas, dato
# real: la compañía no tiene test_set_id configurado hoy).
# ================================================================
def t7():
    original_certification = company.l10n_co_ne_certification_process
    cert = env['certificate.certificate'].search([('company_id', '=', company.id)], limit=1)
    assert cert, "No hay ningun certificate.certificate real para probar -- ajustar la prueba"

    contract = env['hr.contract'].search([
        ('state', '=', 'open'), ('company_id', '=', company.id),
    ], limit=1)
    assert contract, "No hay ningun contrato abierto real para probar -- ajustar la prueba"

    import datetime
    payslip = env['hr.payslip'].create({
        'name': 'TEST Certification Guard',
        'employee_id': contract.employee_id.id,
        'contract_id': contract.id,
        'company_id': company.id,
        'date_from': datetime.date.today().replace(day=1),
        'date_to': datetime.date.today(),
        'l10n_co_ne_state': 'generated',
    })
    try:
        company.write({
            'l10n_co_ne_certification_process': False,
        })
        cr.commit()
        try:
            payslip.action_send_test_set()
            raise AssertionError("Deberia haber bloqueado por certification_process=False")
        except Exception as e:
            assert 'Proceso de Certificación' in str(e), \
                f"El error no menciona el guard nuevo: {e}"

        company.write({'l10n_co_ne_certification_process': True})
        cr.commit()
        try:
            payslip.action_send_test_set()
            raise AssertionError("Deberia haber bloqueado por falta de ID de Pruebas (siguiente guard)")
        except Exception as e:
            assert 'Proceso de Certificación' not in str(e), \
                "Con certification_process=True no deberia bloquear por el guard nuevo"
            assert 'ID de Pruebas' in str(e) or 'TestSetID' in str(e), \
                f"Se esperaba el guard de ID de Pruebas, salio: {e}"
    finally:
        payslip.unlink()
        company.write({
            'l10n_co_ne_certification_process': original_certification,
        })
        cr.commit()
test("l10n_co_ne_certification_process gatea action_send_test_set() de verdad", t7)

# ================================================================
# TEST 8 (doc 21, se mantiene sin cambios -- Consecutivos siguen con
# domain= explicito. El bloque de Certificado se retiro 2026-09-12: el
# Many2one con domain= desaparecio, l10n_co_ne_certificate_ids no
# necesita domain propio -- es la misma lista global de certificados de
# la compania, igual que l10n_co_dian_certificate_ids).
# ================================================================
def t8():
    expected_seq_domain = "[('code', 'like', 'l10n_co_nomina.')]"
    for fname in ('l10n_co_ne_sequence_id', 'l10n_co_ne_pre_sequence_id'):
        field = Settings._fields[fname]
        assert field.domain, f"{fname} deberia tener domain= explicito"
        assert str(field.domain) == expected_seq_domain, \
            f"{fname}.domain es {field.domain!r}, se esperaba {expected_seq_domain!r}"

    settings = Settings.create({'company_id': company.id})
    # get_domain_list() solo evalua un domain que YA es una lista Python
    # -- para un domain declarado como string (nuestro caso, patron
    # normal de Odoo para domains dinamicos con variables como
    # company_id), devuelve [] sin evaluar nada. Hallazgo de Tech Lead
    # corrido contra el servidor real: usar safe_eval() con el mismo
    # contexto que evalua el webclient (company_id/id del propio
    # registro), no get_domain_list().
    eval_context = {'company_id': settings.company_id.id, 'id': settings.id}

    Sequence = env['ir.sequence']
    other_module_seq = Sequence.search([('code', 'not like', 'l10n_co_nomina.')], limit=1)
    assert other_module_seq, "No hay ninguna secuencia de otro modulo para probar el negativo"
    seq_domain = safe_eval(settings._fields['l10n_co_ne_sequence_id'].domain, eval_context)
    matches = Sequence.search(seq_domain + [('id', '=', other_module_seq.id)])
    assert not matches, \
        f"El domain de l10n_co_ne_sequence_id NO deberia matchear una secuencia de otro modulo ({other_module_seq.code})"
test("Domain explicito en Consecutivos se mantiene (doc 21)", t8)

# ================================================================
# TEST 9: la vista de Ajustes > Nomina sigue heredando del punto
# correcto tras la reescritura de doc 22.
# ================================================================
def t9():
    view = env.ref('l10n_co_nomina_electronica.res_config_settings_view_form')
    parent = env.ref('hr_payroll.res_config_settings_view_form')
    assert view.inherit_id.id == parent.id, \
        f"La vista deberia heredar de hr_payroll.res_config_settings_view_form, hereda de {view.inherit_id.name}"
    assert view.model == 'res.config.settings'
test("Vista de Ajustes > Nomina sigue heredando del punto correcto (hr_payroll)", t9)

# ================================================================
# TEST 10: verificacion directa de que post-migrate.py corrio bien
# contra los datos reales conocidos de la compañía (TEST-SOFTWARE-ID/
# TEST-PIN, test_set_id vacio -> certification_process debe quedar
# False, no True).
# ================================================================
def t10():
    mode = env['l10n.co.ne.operation_mode'].search([('company_id', '=', company.id)])
    assert len(mode) == 1, f"Deberia haber exactamente 1 modo de operacion migrado, hay {len(mode)}"
    assert mode.software_id == 'TEST-SOFTWARE-ID', \
        f"software_id migrado deberia ser TEST-SOFTWARE-ID, es {mode.software_id!r}"
    assert mode.software_pin == 'TEST-PIN', \
        f"software_pin migrado deberia ser TEST-PIN, es {mode.software_pin!r}"
    assert not mode.test_set_id, \
        f"test_set_id deberia seguir vacio (no habia dato que migrar), es {mode.test_set_id!r}"
test("post-migrate.py migro correctamente los datos reales conocidos (software_id/pin)", t10)

# ================================================================
# TEST 11 (doc 36 v2, 2026-09-12): los 4 campos de diario por estructura
# salarial NO son `related=` -- se exponen via get_values()/set_values()
# (journal_id vive en hr.payroll.structure, company_dependent, sin
# cadena de relacion simple desde res.company). Se prueba el roundtrip
# completo: get_values() refleja el journal_id real actual de cada
# estructura, y set_values() escribe un journal distinto de vuelta a la
# estructura real -- restaurando el valor original en el finally.
# ================================================================
def t11():
    from odoo.addons.l10n_co_nomina_electronica.models.res_config_settings import (
        _NE_STRUCTURE_JOURNAL_FIELDS,
    )
    structures = {
        fname: env.ref(xmlid) for fname, xmlid in _NE_STRUCTURE_JOURNAL_FIELDS.items()
    }
    originals = {fname: structure.journal_id for fname, structure in structures.items()}

    # get_values(): debe reflejar el journal_id real actual de cada estructura.
    defaults = Settings.default_get(list(_NE_STRUCTURE_JOURNAL_FIELDS.keys()))
    for fname, structure in structures.items():
        assert defaults.get(fname) == structure.journal_id.id, \
            f"get_values() para {fname} deberia ser {structure.journal_id.id} (journal_id real de {structure.name}), devolvio {defaults.get(fname)}"

    # set_values(): un journal distinto (misma moneda que la compañia,
    # ya existente, no se crea ninguno nuevo) debe persistir en la
    # estructura real correspondiente.
    other_journal = env['account.journal'].search([
        ('company_id', '=', company.id),
        ('id', 'not in', [j.id for j in originals.values() if j]),
    ], limit=1)
    assert other_journal, "No hay un segundo diario real distinto para probar el roundtrip -- ajustar la prueba"

    try:
        settings = Settings.new({**defaults, 'company_id': company.id})
        fname_to_test = next(iter(_NE_STRUCTURE_JOURNAL_FIELDS))
        settings[fname_to_test] = other_journal.id
        settings.set_values()
        cr.commit()
        structures[fname_to_test].invalidate_recordset(['journal_id'])
        assert structures[fname_to_test].journal_id == other_journal, \
            f"set_values() no persistio el journal nuevo en {structures[fname_to_test].name}: quedo en {structures[fname_to_test].journal_id.name}"
    finally:
        settings_restore = Settings.new({**defaults, 'company_id': company.id})
        for fname, original_journal in originals.items():
            settings_restore[fname] = original_journal.id if original_journal else False
        settings_restore.set_values()
        cr.commit()
        for fname, structure in structures.items():
            structure.invalidate_recordset(['journal_id'])
            assert structure.journal_id == originals[fname], \
                f"No se restauro el journal_id original de {structure.name}"
test("Cuentas Predeterminadas: get_values()/set_values() de los 4 diarios por estructura, roundtrip real", t11)

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
