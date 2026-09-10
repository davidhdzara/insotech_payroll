#!/bin/bash
# ================================================================
# Test exhaustivo: Certificado Digital consolidado con
# certificate.certificate nativo (doc 17)
#
# Reemplaza l10n_co_ne_cert_file/_filename/_password (.p12 propio de
# nomina, nunca usado en produccion segun doc 17 SS2.3) por
# l10n_co_ne_certificate_id = Many2one('certificate.certificate'),
# reutilizando el certificado de facturacion electronica que la
# compania ya tiene cargado. services/xml_signer.py ya no desempaqueta
# PKCS12 (load_p12 eliminada) -- ahora sign_xml recibe el material ya
# cargado via xml_signer.load_from_certificate().
#
# Mismas lecciones aprendidas de test_annual_params.sh / test_embargo.sh:
# - odoo-bin se invoca directo (no "python odoo-bin"), el wrapper() de
#   pruebas hace cr.rollback() defensivo en el except.
# - compute_sheet() deja el payslip en estado 'verify', no aplica aqui
#   (este script no crea payslips, solo prueba el firmador y la
#   validacion de configuracion).
# - pem_key/pem_certificate son Binary base64-encoded -- con_context
#   bin_size=False es obligatorio para leer el contenido real (ver
#   xml_signer.load_from_certificate).
#
# Requiere: al menos un certificate.certificate real cargado para la
# compania de prueba (en staging_produccion ya existe: id=1,
# "Certificado.pfx", vigente hasta 2027-03-30 -- ver doc 17 SS2.3).
#
# NOTA: /tmp/ne_params.tar.gz debe estar actualizado con el diff de
# doc 17 antes de correr este script.
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
from datetime import timedelta
from odoo import fields
from odoo.exceptions import UserError
from lxml import etree as _etree
from odoo.addons.l10n_co_nomina_electronica.services import xml_signer

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

_NS_EXT = 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2'
_NS_DS = 'http://www.w3.org/2000/09/xmldsig#'

company = env.user.company_id
CertModel = env['certificate.certificate']

real_cert = CertModel.search([('company_id', '=', company.id)], limit=1)
if not real_cert:
    raise Exception(
        "No hay certificate.certificate para la compania de prueba -- "
        "no se puede probar el diseno del certificado (doc 17 asume que "
        "ya existe uno de facturacion electronica, confirmado por SSH "
        "antes de escribir este script)."
    )

# ================================================================
# SETUP: apuntar l10n_co_ne_certificate_id al certificado real, y
# garantizar software_id/software_pin, para el resto de las pruebas.
# Sin esto, T3/T4 podrian fallar por el motivo equivocado --
# _validate_company_ne_config junta TODOS los campos faltantes en un
# solo UserError antes de llegar al chequeo de vigencia, asi que si
# software_id/pin tambien faltaran, el mensaje de T4 no mencionaria
# "vencido" y la asercion fallaria por una razon distinta a la que se
# quiere probar (misma leccion que T7 de test_embargo.sh: aislar la
# variable bajo prueba). Se restaura solo l10n_co_ne_certificate_id al
# valor original al final -- software_id/pin no se tocan si ya
# existian.
# ================================================================
_original_certificate_id = company.l10n_co_ne_certificate_id.id
company.write({
    'l10n_co_ne_certificate_id': real_cert.id,
    'l10n_co_ne_software_id': company.l10n_co_ne_software_id or 'TEST-SOFTWARE-ID',
    'l10n_co_ne_software_pin': company.l10n_co_ne_software_pin or 'TEST-PIN',
})
cr.commit()

# ================================================================
# TEST 1: load_from_certificate extrae correctamente private_key,
# cert_pem, cert_der y cert_obj del certificado real -- sin contrasena
# PKCS12, solo base64.b64decode() sobre pem_key/pem_certificate (doc
# 17 SS2.1).
# ================================================================
def t1():
    private_key, cert_pem, cert_der, cert_obj = xml_signer.load_from_certificate(real_cert)
    assert private_key is not None, "No se extrajo la private key"
    assert cert_pem and cert_pem.startswith(b'-----BEGIN CERTIFICATE-----'), \
        "cert_pem no es un PEM valido"
    assert cert_der, "cert_der vacio"
    assert str(cert_obj.serial_number) == real_cert.serial_number, \
        f"Serial del cert_obj cargado ({cert_obj.serial_number}) no " \
        f"coincide con serial_number guardado ({real_cert.serial_number})"
test("load_from_certificate: extrae private_key/cert_pem/cert_der/cert_obj del certificado real", t1)

# ================================================================
# TEST 2: sign_xml firma correctamente con el material cargado via
# load_from_certificate -- mismo flujo end-to-end que el PoC que corrio
# Tech Lead manualmente, ahora cubierto en la suite.
# ================================================================
def t2():
    private_key, cert_pem, cert_der, cert_obj = xml_signer.load_from_certificate(real_cert)
    test_xml = ('<Root xmlns:ext="%s"><ext:UBLExtensions/></Root>' % _NS_EXT).encode('utf-8')
    signed = xml_signer.sign_xml(
        xml_bytes=test_xml,
        private_key=private_key,
        cert_pem=cert_pem,
        cert_der=cert_der,
        cert_obj=cert_obj,
    )
    root = _etree.fromstring(signed)
    sig = root.find('.//{%s}Signature' % _NS_DS)
    assert sig is not None, "sign_xml no genero un elemento ds:Signature"
    sig_value = sig.find('{%s}SignatureValue' % _NS_DS)
    assert sig_value is not None and sig_value.text, "SignatureValue vacio"
test("sign_xml: firma XAdES-BES con material cargado via load_from_certificate", t2)

# ================================================================
# TEST 3: _validate_company_ne_config bloquea sin certificado
# configurado (campo eliminado l10n_co_ne_cert_file ya no existe --
# ahora es simplemente que l10n_co_ne_certificate_id este vacio).
# ================================================================
def t3():
    company.write({'l10n_co_ne_certificate_id': False})
    cr.commit()
    try:
        raised = False
        try:
            env['hr.payslip']._validate_company_ne_config(company)
        except UserError as e:
            raised = True
            assert 'Certificado Digital' in str(e), \
                f"Mensaje de error no menciona el certificado: {e}"
        assert raised, "_validate_company_ne_config no lanzo UserError sin certificado configurado"
    finally:
        company.write({'l10n_co_ne_certificate_id': real_cert.id})
        cr.commit()
test("_validate_company_ne_config: bloquea sin certificado configurado", t3)

# ================================================================
# TEST 4: _validate_company_ne_config bloquea con certificado vencido
# (date_end en el pasado) -- respuesta de Tech Lead a la pregunta
# abierta 1 de doc 17: NO se filtra en el domain, se valida aqui con
# mensaje explicito.
#
# NO se puede probar esto con una copia del certificado real
# (real_cert.copy(...)): pkcs12_password es un campo de seguridad
# enmascarado por el ORM (el valor real nunca se expone), y .copy()
# dispara el create() nativo que recomputa pem_certificate a partir de
# content (real) + pkcs12_password (placeholder enmascarado) --
# la desencriptacion PKCS12 falla y salta un ValidationError nativo
# ANTES de llegar siquiera a forzar date_end. Confirmado por Tech Lead
# corriendo esto aislado en staging_produccion.
#
# Fix: escribir date_end DIRECTO sobre el certificado real via
# .write() (no copia, no SQL crudo) y restaurar el valor original en
# el finally. date_end no esta en el @api.depends de
# _compute_pem_certificate (solo depende de content/pkcs12_password),
# asi que escribirlo no dispara ningun recompute ni toca la parte
# criptografica -- verificado por Tech Lead que pem_certificate se
# sigue leyendo bien despues del write y tras restaurar.
# ================================================================
def t4():
    original_date_end = real_cert.date_end
    real_cert.write({'date_end': fields.Datetime.now() - timedelta(days=1)})
    cr.commit()
    try:
        raised = False
        try:
            env['hr.payslip']._validate_company_ne_config(company)
        except UserError as e:
            raised = True
            assert 'vencido' in str(e).lower(), \
                f"Mensaje de error no menciona vencimiento: {e}"
        assert raised, "_validate_company_ne_config no lanzo UserError con certificado vencido"
    finally:
        real_cert.write({'date_end': original_date_end})
        cr.commit()
test("_validate_company_ne_config: bloquea con certificado vencido", t4)

# ================================================================
# TEST 5: _validate_company_ne_config pasa limpio con certificado
# vigente y software_id/software_pin configurados (caso feliz -- sin
# esto, T3/T4 podrian pasar "por accidente" si la validacion estuviera
# rota de otra forma, ej. lanzando UserError siempre).
# ================================================================
def t5():
    company.write({'l10n_co_ne_certificate_id': real_cert.id})
    cr.commit()
    env['hr.payslip']._validate_company_ne_config(company)  # no debe lanzar
test("_validate_company_ne_config: no lanza con certificado vigente y configuracion completa", t5)

# ================================================================
# LIMPIEZA FINAL: restaurar el valor original del campo en la
# compania de prueba (antes del setup era None en todos los ambientes
# verificados, doc 17 SS2.3).
# ================================================================
company.write({'l10n_co_ne_certificate_id': _original_certificate_id})
cr.commit()

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
