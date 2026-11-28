# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""Q-96 ampliada (.341): un recibo PAGADO con reembolso confirmado no se saca ni se envía (en los dos órdenes), y un XML que nunca viajó solo sale si lleva lo que hoy se compondría. Con envío fallido se reenvía el
mismo XML, avisando. Todo con *mock*: ninguna prueba llama a la DIAN."""

from datetime import date
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from . import test_documento_enviar as enviar
from .common_documento import DocumentoFixture
from .test_documento_reembolsos import LIQUIDACION, _linea, _reembolsar


@tagged('post_install', '-at_install')
class TestReembolsoPagado(DocumentoFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        enviar.TestDocumentoEnviar._preparar_compania(cls, 'Compañía Reembolso Pagado')

    def setUp(self):
        super().setUp()
        enviar.TestDocumentoEnviar._simular_dian(self)
        self.Documento = self.env['l10n.co.ne.documento']

    # ── utilidades ───────────────────────────────────────────────────
    def _doc(self, pagos=((15, 15), (31, 31))):
        doc = self._documento(date(2024, 3, 1), pagos=pagos)
        for numero, recibo in enumerate(doc.payslip_ids.sorted('date_to'), 1):
            _linea(self.env, recibo, 1500000.0 + numero)
        return doc

    def _generado(self, doc, encolar=True):
        doc._ne_validar()
        doc.action_generar_xml()
        if encolar:
            doc._ne_encolar()
        return doc

    def _nuevo_pagado(self, base, valor=900000.0):
        recibo = self.env['hr.payslip'].create({
            'name': 'Recibo pagado después', 'employee_id': base.employee_id.id, 'contract_id': base.contract_id.id, 'company_id': base.company_id.id,
            'struct_id': base.struct_id.id, 'date_from': date(2026, 3, 20), 'date_to': date(2026, 3, 25)})
        _linea(self.env, recibo, valor)
        recibo.write({'state': 'paid', 'paid_date': date(2026, 3, 25)})
        return recibo

    def _claves(self, doc, nivel='danger'):
        return [alerta['key'] for alerta in (doc.alertas or []) if alerta['level'] == nivel]

    def _no_sale(self, doc, texto):
        """Ni por el cron ni por el envío directo ni al encolar otra vez: no se llama a la DIAN y el documento queda fuera de la cola, listo para preparar de nuevo."""
        self.Documento._cron_enviar_cola()
        self.soap.assert_not_called()
        self.assertFalse(doc.is_being_sent)
        for camino in (doc._ne_enviar_uno, doc._ne_encolar):
            with self.assertRaisesRegex(UserError, texto):
                camino()
        self.soap.assert_not_called()

    # ── pagado y reembolsado ─────────────────────────────────────────
    def test_pagado_y_reembolsado_no_se_saca_y_dice_las_dos_salidas(self):
        doc = self._doc()
        primera, segunda = doc.payslip_ids.sorted('date_to')
        reembolso = _reembolsar(segunda, quitar_pago=False)
        anulados, dudas = segunda._ne_reembolsos()
        self.assertFalse(anulados)
        for texto in ('figura pagado', 'Si NO se pagó: pulse «Sin pagar»', 'Reintegro', 'En este orden: 1) cancele', 'id %s' % segunda.id, 'id %s' % reembolso.id):
            self.assertIn(texto, ' '.join(dudas))
        self.Documento._ne_preparar(doc.payslip_ids)
        self.assertEqual(doc.payslip_ids, primera | segunda)
        self.assertIn('reembolso_dudoso', self._claves(doc))
        with self.assertRaisesRegex(UserError, 'figura pagado'):
            doc.action_generar_xml()
        segunda.action_payslip_unpaid()          # la salida «no se pagó»
        self.Documento._ne_preparar(doc.payslip_ids)
        self.assertEqual(doc.payslip_ids, primera)
        doc.action_generar_xml()

    def test_una_liquidacion_pagada_y_reembolsada_conserva_su_retiro_y_detiene(self):
        doc = self._doc()
        base = doc.payslip_ids.sorted('date_to')[-1]
        liquidacion = self.env['hr.payslip'].create({
            'name': 'Liquidación pagada', 'employee_id': base.employee_id.id, 'contract_id': base.contract_id.id, 'company_id': base.company_id.id,
            'struct_id': self.env.ref(LIQUIDACION).id, 'date_from': base.contract_id.date_start, 'date_to': base.date_to})
        _linea(self.env, liquidacion, 2000000.0)
        liquidacion.write({'state': 'paid', 'paid_date': base.paid_date, 'l10n_co_ne_documento_id': doc.id})
        _reembolsar(liquidacion, quitar_pago=False)
        self.assertEqual(doc.payslip_ids._ne_fecha_retiro(), str(base.date_to))
        with self.assertRaisesRegex(UserError, 'figura pagado'):
            doc.action_generar_xml()
        self.soap.assert_not_called()

    def test_en_cola_y_reembolsado_ya_pagado_no_sale(self):
        doc = self._generado(self._doc())
        _reembolsar(doc.payslip_ids.sorted('date_to')[-1], quitar_pago=False)
        self._no_sale(doc, 'figura pagado')

    def test_excluido_sin_pago_y_pagado_despues_no_sale_el_xml_armado_sin_el(self):
        for forma in ('a mano', 'desde el lote'):
            with self.subTest(forma):
                doc = self._doc()
                primera, segunda = doc.payslip_ids.sorted('date_to')
                segunda.action_payslip_unpaid()
                _reembolsar(segunda, quitar_pago=False)
                self.Documento._ne_preparar(doc.payslip_ids)
                self.assertEqual(doc.payslip_ids, primera)
                self._generado(doc)
                contexto = {}
                if forma == 'desde el lote':
                    lote = self.env['hr.payslip.run'].create({'name': 'Lote %s' % forma, 'date_start': date(2026, 3, 1), 'date_end': date(2026, 3, 31), 'company_id': self.company.id})
                    segunda.payslip_run_id = lote
                    contexto = {'ne_payslip_run_ids': lote.ids}
                self.env['hr.payslip.registrar.pago'].with_context(**contexto).create({
                    'payslip_ids': [(6, 0, segunda.ids)], 'fecha': date(2026, 3, 28)}).action_registrar_pago()
                self.assertEqual(segunda.state, 'paid')
                self._no_sale(doc, 'figura pagado')

    # ── lo que hoy se compondría ─────────────────────────────────────
    def test_cancelado_el_reembolso_no_sale_el_xml_armado_sin_el_recibo(self):
        doc = self._doc()
        primera, segunda = doc.payslip_ids.sorted('date_to')
        with patch.object(type(segunda), '_ne_figura_pagado', lambda recibo: False):          # un XML armado antes de que lo pagado detuviera
            reembolso = _reembolsar(segunda, quitar_pago=False)
            self.Documento._ne_preparar(doc.payslip_ids)
            self.assertEqual(doc.payslip_ids, primera)
            self._generado(doc)
        reembolso.action_payslip_cancel()
        self._no_sale(doc, 'llevaría otros recibos')
        with self.assertRaisesRegex(UserError, 'llevaría otros recibos'):
            doc.action_generar_xml()
        self.Documento._ne_preparar(segunda)
        self.assertEqual(doc.payslip_ids, primera | segunda)
        self._generado(doc)
        self.Documento._cron_enviar_cola()
        self.assertEqual((self.soap.call_count, doc.state), (1, 'invoice_accepted'))

    def test_un_recibo_pagado_despues_de_generar_detiene_el_envio(self):
        doc = self._generado(self._doc())
        nuevo = self._nuevo_pagado(doc.payslip_ids[0])
        self._no_sale(doc, nuevo.display_name)

    def test_un_mes_normal_sale(self):
        doc = self._generado(self._doc())
        self.Documento._cron_enviar_cola()
        self.assertEqual((self.soap.call_count, doc.state), (1, 'invoice_accepted'))

    def test_el_envio_fallido_se_reintenta_avisando_y_el_aviso_sigue_al_aceptarse(self):
        doc = self._generado(self._doc(), encolar=False)
        self.soap.return_value = enviar.CONEXION
        doc._ne_enviar_uno()
        self.assertEqual(doc.state, 'invoice_sending_failed')
        xml = doc.xml_attachment_id
        nuevo = self._nuevo_pagado(doc.payslip_ids[0])
        self.Documento._ne_preparar(nuevo)
        aviso = [a for a in doc.alertas if a['key'] == 'fallo_envio_composicion']
        self.assertEqual([a['level'] for a in aviso], ['warning'])
        for texto in (nuevo.display_name, 'Al ser aceptado, corrija con una nota de ajuste'):
            self.assertIn(texto, aviso[0]['message'])
        self.assertTrue(doc.message_ids.filtered(lambda m: 'este documento llevaría otros recibos' in str(m.body)))
        self.soap.return_value = enviar.ACEPTADA
        doc._ne_enviar_uno()
        self.assertEqual((doc.state, doc.xml_attachment_id), ('invoice_accepted', xml))
        aviso = [a for a in doc.alertas if a['key'] == 'aceptado_composicion']
        self.assertEqual([a['level'] for a in aviso], ['warning'])
        self.assertIn(nuevo.display_name, aviso[0]['message'])
