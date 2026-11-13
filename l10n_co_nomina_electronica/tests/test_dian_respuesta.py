# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.

"""Servicio ``services/dian_respuesta`` (parte A, doc 53 §23.12 / §23.14 commit 1).

Dos clases:
- ``TestDianRespuestaPura`` (``BaseCase``, sin base de datos): los 4 helpers con valores a mano.
- ``TestMixinEnvoltorios`` (``TransactionCase``): los 4 nombres que conserva el mixin del recibo
  devuelven EXACTAMENTE lo mismo que el servicio (el recibo no cambió).
"""

from odoo.tests.common import BaseCase, TransactionCase, tagged

from odoo.addons.l10n_co_nomina_electronica.services import dian_respuesta

_NS = ('xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
       'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"')

# ApplicationResponse real: el CUNE viaja en DocumentReference/UUID (AUD-DIAN-34).
_APP_CON_CUNE = (
    '<ApplicationResponse %s><cac:DocumentResponse><cac:DocumentReference>'
    '<cbc:UUID schemeName="CUNE-SHA384">abc123cune</cbc:UUID>'
    '</cac:DocumentReference></cac:DocumentResponse></ApplicationResponse>' % _NS)
# Solo el NÚMERO (cbc:ID bajo DocumentReference).
_APP_CON_NUMERO = (
    '<ApplicationResponse %s><cac:DocumentResponse><cac:DocumentReference>'
    '<cbc:ID>NE0000000009</cbc:ID>'
    '</cac:DocumentReference></cac:DocumentResponse></ApplicationResponse>' % _NS)
# UUID/ID de nivel raíz: identidad de la respuesta, NO del documento referenciado.
_APP_SOLO_RAIZ = '<ApplicationResponse><UUID>RESP-UUID</UUID><ID>RESP-ID</ID></ApplicationResponse>'

# Respuesta de nivel SET (H-012): StatusCode 2, IsValid false, sin datos del documento.
_RESPUESTA_SET = {
    'StatusCode': '2',
    'IsValid': 'false',
    'StatusDescription': 'Set de prueba con identificador e07c1748-0000-0000-0000-000000000000 '
                         'se encuentra Aceptado.',
}


@tagged('post_install', '-at_install')
class TestDianRespuestaPura(BaseCase):

    # --- texto_respuesta ---------------------------------------------------------------------
    def test_texto_vacio_o_none_devuelve_cadena_vacia(self):
        self.assertEqual(dian_respuesta.texto_respuesta(None), '')
        self.assertEqual(dian_respuesta.texto_respuesta(''), '')
        self.assertEqual(dian_respuesta.texto_respuesta(b''), '')

    def test_texto_bytes_con_acentos_se_decodifica_utf8(self):
        self.assertEqual(
            dian_respuesta.texto_respuesta('Validación Nómina'.encode('utf-8')),
            'Validación Nómina')

    def test_texto_bytes_invalidos_se_reemplazan_no_fallan(self):
        self.assertEqual(dian_respuesta.texto_respuesta(b'\xff'), '�')

    def test_texto_se_recorta_exactamente_a_5000(self):
        self.assertEqual(len(dian_respuesta.texto_respuesta('a' * 6000)), 5000)
        exacto = 'b' * 5000
        self.assertEqual(dian_respuesta.texto_respuesta(exacto), exacto)
        self.assertEqual(len(dian_respuesta.texto_respuesta('c' * 4999)), 4999)

    def test_texto_limite_personalizado(self):
        self.assertEqual(dian_respuesta.texto_respuesta('abcdef', limite=3), 'abc')

    # --- candidatos_cune ---------------------------------------------------------------------
    def test_cune_sin_datos_es_conjunto_vacio(self):
        self.assertEqual(dian_respuesta.candidatos_cune({}), set())

    def test_cune_de_cada_una_de_las_tres_claves_con_espacios(self):
        for clave in ('XmlDocumentKey', 'CUNE', 'DocumentKey'):
            self.assertEqual(
                dian_respuesta.candidatos_cune({clave: '  abc  '}), {'abc'}, clave)

    def test_cune_tres_claves_distintas_y_una_repetida(self):
        result = {'XmlDocumentKey': 'a', 'CUNE': 'b', 'DocumentKey': 'a'}
        self.assertEqual(dian_respuesta.candidatos_cune(result), {'a', 'b'})

    def test_cune_desde_application_response(self):
        self.assertEqual(
            dian_respuesta.candidatos_cune({'ApplicationResponse': _APP_CON_CUNE}),
            {'abc123cune'})

    def test_cune_une_claves_y_application_response(self):
        result = {'XmlDocumentKey': 'otro', 'ApplicationResponse': _APP_CON_CUNE}
        self.assertEqual(dian_respuesta.candidatos_cune(result), {'otro', 'abc123cune'})

    def test_cune_ignora_uuid_de_nivel_raiz(self):
        self.assertEqual(
            dian_respuesta.candidatos_cune({'ApplicationResponse': _APP_SOLO_RAIZ}), set())

    # --- candidatos_numero -------------------------------------------------------------------
    def test_numero_sin_application_response_es_vacio(self):
        self.assertEqual(dian_respuesta.candidatos_numero({}), set())
        self.assertEqual(dian_respuesta.candidatos_numero({'ApplicationResponse': ''}), set())

    def test_numero_desde_document_reference_id(self):
        self.assertEqual(
            dian_respuesta.candidatos_numero({'ApplicationResponse': _APP_CON_NUMERO}),
            {'NE0000000009'})

    def test_numero_no_confunde_el_cune_ni_el_id_raiz(self):
        self.assertEqual(
            dian_respuesta.candidatos_numero({'ApplicationResponse': _APP_CON_CUNE}), set())
        self.assertEqual(
            dian_respuesta.candidatos_numero({'ApplicationResponse': _APP_SOLO_RAIZ}), set())

    # --- es_respuesta_de_set -----------------------------------------------------------------
    def test_set_es_detectado(self):
        self.assertTrue(dian_respuesta.es_respuesta_de_set(_RESPUESTA_SET))

    def test_set_con_espacios_en_el_codigo(self):
        self.assertTrue(dian_respuesta.es_respuesta_de_set(dict(_RESPUESTA_SET, StatusCode=' 2 ')))

    def test_set_sin_is_valid_cuenta_como_no_valido(self):
        self.assertTrue(dian_respuesta.es_respuesta_de_set({'StatusCode': '2'}))

    def test_documento_aceptado_no_es_de_set(self):
        normal = {'StatusCode': '00', 'IsValid': 'true', 'XmlDocumentKey': 'CUNE-X'}
        self.assertFalse(dian_respuesta.es_respuesta_de_set(normal))

    def test_rechazo_no_es_de_set(self):
        rechazo = {'StatusCode': '99', 'IsValid': 'false', 'ErrorMessages': ['x']}
        self.assertFalse(dian_respuesta.es_respuesta_de_set(rechazo))

    def test_set_is_valid_true_en_cualquier_mayuscula_no_es_de_set(self):
        for valor in ('true', 'True', 'TRUE'):
            self.assertFalse(
                dian_respuesta.es_respuesta_de_set(dict(_RESPUESTA_SET, IsValid=valor)), valor)

    def test_set_con_datos_del_documento_no_es_de_set(self):
        self.assertFalse(dian_respuesta.es_respuesta_de_set(
            dict(_RESPUESTA_SET, XmlDocumentKey='CUNE-X')))
        self.assertFalse(dian_respuesta.es_respuesta_de_set(
            dict(_RESPUESTA_SET, ApplicationResponse=_APP_CON_CUNE)))


@tagged('post_install', '-at_install')
class TestMixinEnvoltorios(TransactionCase):
    """Los 4 nombres del mixin del recibo devuelven lo mismo que el servicio."""

    def setUp(self):
        super().setUp()
        self.payslip = self.env['hr.payslip']

    def test_envoltorio_response_text(self):
        for valor in (None, '', 'texto', 'ñ'.encode('utf-8'), 'z' * 6000):
            self.assertEqual(
                self.payslip._ne_response_text(valor), dian_respuesta.texto_respuesta(valor))

    def test_envoltorio_cune_candidates(self):
        for result in ({}, {'CUNE': ' x '}, {'ApplicationResponse': _APP_CON_CUNE}):
            self.assertEqual(
                self.payslip._ne_cune_candidates(result), dian_respuesta.candidatos_cune(result))

    def test_envoltorio_number_candidates(self):
        for result in ({}, {'ApplicationResponse': _APP_CON_NUMERO}):
            self.assertEqual(
                self.payslip._ne_number_candidates(result),
                dian_respuesta.candidatos_numero(result))

    def test_envoltorio_is_set_level_status(self):
        for response in (_RESPUESTA_SET, {'StatusCode': '00', 'IsValid': 'true'},
                         {'StatusCode': '99', 'IsValid': 'false', 'ErrorMessages': ['x']}):
            self.assertEqual(
                self.payslip._ne_is_set_level_status(response),
                dian_respuesta.es_respuesta_de_set(response))
