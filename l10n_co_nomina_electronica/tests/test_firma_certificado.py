# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""``xml_signer.load_from_certificate``: un certificado o una llave que se leen vacíos (adjunto sin archivo, base neutralizada) fallaban con un error técnico sin decir cuál certificado ni qué hacer; y una llave cargada
aparte con clave (queda cifrada) no se podía abrir porque la clave no se usaba. Dobles mínimos de ``certificate.certificate`` / ``certificate.key``: solo lo que la función lee."""

import base64
from datetime import datetime, timedelta
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from odoo.addons.l10n_co_nomina_electronica.services import xml_signer
from odoo.exceptions import UserError
from odoo.tests.common import BaseCase, tagged

NOMBRE = 'Certificado de Prueba Firma'
PIDE_RECARGAR = 'Vuelva a cargar'


def _traducir(texto, *args, **kwargs):
    return texto % (kwargs or args) if (kwargs or args) else texto


class _Registro(SimpleNamespace):
    env = SimpleNamespace(_=_traducir)

    def ensure_one(self):
        pass

    def with_context(self, **_contexto):
        return self

    def _get_certificate_chain(self):
        return self.cadena or [self]


@tagged('post_install', '-at_install')
class TestCargaDeCertificado(BaseCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.llave = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'prueba')])
        certificado = (x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre).public_key(cls.llave.public_key()).serial_number(1)
                       .not_valid_before(datetime(2026, 1, 1)).not_valid_after(datetime(2026, 1, 1) + timedelta(days=3650))
                       .sign(cls.llave, hashes.SHA256(), default_backend()))
        cls.pem_certificado = base64.b64encode(certificado.public_bytes(serialization.Encoding.PEM))

    def _pem_llave(self, clave=None):
        cifrado = serialization.BestAvailableEncryption(clave) if clave else serialization.NoEncryption()
        return base64.b64encode(self.llave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, cifrado))

    def _certificado(self, pem_llave=None, clave=False, pem_certificado=None, sin_llave=False, cadena=None):
        llave = False if sin_llave else _Registro(pem_key=self._pem_llave() if pem_llave is None else pem_llave, password=clave)
        return _Registro(display_name=NOMBRE, private_key_id=llave, cadena=cadena,
                         pem_certificate=self.pem_certificado if pem_certificado is None else pem_certificado)

    def _carga(self, certificado):
        llave, cert_pem, cert_der, _objeto, cadena = xml_signer.load_from_certificate(certificado)
        self.assertEqual(llave.private_numbers(), self.llave.private_numbers())
        self.assertTrue(cert_pem and cert_der and cadena)

    def _pide_recargar(self, certificado):
        with self.assertRaisesRegex(UserError, PIDE_RECARGAR) as caso:
            xml_signer.load_from_certificate(certificado)
        self.assertIn(NOMBRE, str(caso.exception))

    def test_una_llave_sin_cifrar_se_carga(self):
        self._carga(self._certificado())

    def test_una_llave_sin_cifrar_con_clave_guardada_no_la_usa(self):
        self._carga(self._certificado(clave='sobra'))

    def test_una_llave_cifrada_se_abre_con_la_clave_del_registro(self):
        self._carga(self._certificado(pem_llave=self._pem_llave(b'secreta'), clave='secreta'))

    def test_una_llave_cifrada_sin_clave_o_con_clave_mala_pide_recargar(self):
        for clave in (False, 'otra'):
            self._pide_recargar(self._certificado(pem_llave=self._pem_llave(b'secreta'), clave=clave))

    def test_el_certificado_vacio_pide_recargar(self):
        for vacio in (False, b''):
            self._pide_recargar(self._certificado(pem_certificado=vacio))

    def test_la_llave_vacia_o_ausente_pide_recargar(self):
        for certificado in (self._certificado(pem_llave=b''), self._certificado(pem_llave=False), self._certificado(sin_llave=True)):
            self._pide_recargar(certificado)

    def test_un_certificado_de_la_cadena_vacio_pide_recargar(self):
        hoja = self._certificado()
        hoja.cadena = [hoja, _Registro(display_name='Intermedio', pem_certificate=False)]
        self._pide_recargar(hoja)
