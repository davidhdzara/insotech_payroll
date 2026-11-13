# -*- coding: utf-8 -*-
"""Etapa 3b (doc 53 §5.4, §18.6): conciliacion de totales contra los nodos y generacion del XML mensual firmado
(consecutivo, CUNE reproducible, adjunto). Valores a mano: mes de dos quincenas con prima."""

import base64
import copy
import hashlib
from datetime import date
from lxml import etree

from odoo.exceptions import UserError
from odoo.tests.common import BaseCase, TransactionCase, tagged

from odoo.addons.l10n_co_nomina_electronica.services import (
    dian_utils, documento_merge as dm, nomina_xml_builder, xml_signer)

from .common_documento import DocumentoFixture
from .test_documento_merge import _recibo, PERIODO

NS = 'dian:gov:co:facturaelectronica:NominaIndividual'
XML_STUB = ('<NominaIndividual xmlns="%s"><InformacionGeneral/></NominaIndividual>' % NS).encode()
PIN = 'PIN-TEST'
FECHA, HORA = '2026-04-01', '10:00:00-05:00'


def _quincena_con_prima():
    """Segunda quincena con prima de 1.000.000: devengados 1.500.000 + 124.547,50 + 1.000.000 = 2.624.547,50."""
    datos = _recibo()
    datos['devengados']['Primas'] = {'Cantidad': '180', 'Pago': '1000000.00', 'PagoNS': '0.00'}
    datos['devengados_total'] = 2624547.50
    return datos


@tagged('post_install', '-at_install')
class TestConciliacion(BaseCase):

    def _fusion(self, recibos):
        return dm.fusionar_documento(recibos, ['2026-03-15', '2026-03-31'], PERIODO)

    def test_cuadra_con_prima(self):
        recibos = [_recibo(), _quincena_con_prima()]
        doc = self._fusion(recibos)
        self.assertEqual(doc['totales'], {
            'DevengadosTotal': '4249095.00', 'DeduccionesTotal': '240000.00', 'ComprobanteTotal': '4009095.00'})
        self.assertEqual(dm.conciliar_fusion(recibos, doc), [])
        self.assertEqual(dm.diferencias_nodos(doc), (0, 0))   # 3.000.000 + 249.095 + 1.000.000 = 4.249.095

    def test_nodo_perdido_en_la_fusion_se_detecta(self):
        recibos = [_recibo(), _quincena_con_prima()]
        doc = self._fusion(recibos)
        del doc['devengados']['Primas']
        errores = dm.conciliar_fusion(recibos, doc)
        self.assertEqual(len(errores), 1)
        self.assertIn('devengados del documento (3249095.00) no es la de los recibos (4249095.00)', errores[0])

    def test_total_que_no_es_la_suma_se_detecta(self):
        recibos = [_recibo(), _recibo()]
        doc = self._fusion(recibos)
        doc['totales']['DeduccionesTotal'] = '239999.99'
        errores = dm.conciliar_fusion(recibos, doc)
        self.assertTrue(any('DeduccionesTotal' in e for e in errores))
        self.assertTrue(any('ComprobanteTotal' in e for e in errores))

    def test_total_declarado_distinto_de_los_nodos_da_diferencia(self):
        recibo = _recibo()
        recibo['devengados']['Dotacion'] = '50000.00'   # nodo en dinero que el total del recibo no incluye
        doc = self._fusion([recibo])
        dif_dev, dif_ded = dm.diferencias_nodos(doc)
        self.assertEqual((str(dif_dev), str(dif_ded)), ('50000.00', '0.00'))


@tagged('post_install', '-at_install')
class TestDocumentoGenerar(DocumentoFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture_documento('Compañía Generar Documento')
        cls.env['l10n.co.ne.operation_mode'].create({
            'company_id': cls.company.id, 'software_id': 'SOFT-ID', 'software_pin': PIN, 'test_set_id': 'TS'})
        cls.company.l10n_co_ne_environment = '2'
        cls.secuencia = cls.env['ir.sequence'].create({
            'name': 'Secuencia NE prueba', 'prefix': 'NE', 'padding': 8, 'number_next': 15,
            'implementation': 'no_gap', 'company_id': cls.company.id})
        cls.company.l10n_co_ne_sequence_id = cls.secuencia

    def setUp(self):
        super().setUp()
        def fabrica(slip):
            # la segunda quincena (fin de mes) lleva la prima
            datos = copy.deepcopy(_quincena_con_prima() if slip.date_to.day > 15 else _recibo())
            datos['informacion_general'] = dict(datos['informacion_general'], FechaGen=FECHA, HoraGen=HORA)
            return datos
        self._patch(type(self.env['hr.payslip']), '_collect_payslip_data', lambda s: fabrica(s))
        self._patch(dian_utils, 'compute_software_security_code', lambda *a: 'SC')
        self._patch(type(self.company), '_l10n_co_ne_validar_config', lambda s, *a, **k: None)
        self._patch(type(self.env['l10n.co.ne.documento']), '_ne_validar_datos_recibo', lambda s, slip: None)
        self._patch(type(self.company), '_get_ne_certificate', lambda s: True)
        self._patch(dian_utils, 'clean_nit', lambda *a, **k: '900123456')
        self._patch(xml_signer, 'load_from_certificate', lambda cert: (None, b'', b'', None, None))
        self._patch(xml_signer, 'sign_xml', lambda xml_bytes, **k: xml_bytes)
        self._patch(nomina_xml_builder, 'build_nomina_individual_v2', lambda datos: XML_STUB)
        self.doc = self._documento(date(2024, 3, 1))
        self.doc._ne_validar()

    def _cune_esperado(self, consecutivo='NE00000015'):
        raw = (consecutivo + FECHA + HORA + '4249095.00' + '240000.00' + '4009095.00'
               + '900123456' + '1020304050' + '102' + PIN + '2')
        return hashlib.sha384(raw.encode()).hexdigest()

    def test_genera_con_consecutivo_cune_reproducible_y_adjunto(self):
        self.assertEqual(self.doc.state, 'ready')
        self.doc.action_generar_xml()
        self.assertEqual(self.doc.consecutive, 'NE00000015')
        self.assertEqual(self.doc.cune, self._cune_esperado())       # SHA-384 de la cadena armada a mano
        self.assertEqual(self.doc.state, 'ready')                    # sin estado "generado" (§18.6)
        xml = etree.fromstring(base64.b64decode(self.doc.xml_attachment_id.datas))
        info = xml.find('{%s}InformacionGeneral' % NS)
        self.assertEqual(info.get('CUNE'), self.doc.cune)
        self.assertEqual(info.get('EncripCUNE'), 'CUNE-SHA384')
        self.assertTrue(xml.find('{%s}CodigoQR' % NS).text.endswith('documentkey=%s' % self.doc.cune))
        self.assertEqual(self.doc.xml_attachment_id.name, 'ne_SIN_NIT_NE00000015.xml')

    def test_cune_cambia_si_cambia_un_total(self):
        self.doc.consecutive = 'NE00000015'
        datos = self.doc._collect_documento_data()
        base = self.doc._ne_calcular_cune(datos)
        self.assertEqual(base, self._cune_esperado())
        self.assertEqual(base, self.doc._ne_calcular_cune(datos))     # reproducible
        datos['totales'] = dict(datos['totales'], DevengadosTotal='4249095.01')
        self.assertNotEqual(base, self.doc._ne_calcular_cune(datos))

    def test_regenerar_reutiliza_el_consecutivo_y_no_gasta_otro(self):
        self.doc.action_generar_xml()
        self.doc.action_generar_xml()
        self.assertEqual(self.doc.consecutive, 'NE00000015')
        self.assertEqual(self.secuencia.number_next_actual, 16)       # solo se gastó el 15

    def test_error_de_datos_sale_antes_de_gastar_el_numero(self):
        def revienta(datos):
            raise ValueError('constructor roto')
        self._patch(nomina_xml_builder, 'build_nomina_individual_v2', revienta)
        with self.assertRaises(ValueError):
            self.doc.action_generar_xml()
        self.assertFalse(self.doc.consecutive)
        self.assertEqual(self.secuencia.number_next_actual, 15)

    def test_sin_secuencia_error_claro(self):
        self.company.l10n_co_ne_sequence_id = False
        with self.assertRaisesRegex(UserError, 'secuencia de nómina electrónica'):
            self.doc.action_generar_xml()
        self.assertFalse(self.doc.consecutive)

    def test_con_bloqueos_no_genera(self):
        self.doc.payslip_ids.write({'l10n_co_ne_documento_id': False})
        with self.assertRaisesRegex(UserError, 'bloqueos'):
            self.doc.action_generar_xml()
        self.assertFalse(self.doc.consecutive)

    def test_ya_enviado_no_se_regenera(self):
        self.env['l10n.co.ne.documento.intento'].create({
            'documento_id': self.doc.id, 'state': 'invoice_pending'})
        with self.assertRaisesRegex(UserError, 'no se haya enviado'):
            self.doc.action_generar_xml()
