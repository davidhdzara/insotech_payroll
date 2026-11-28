# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""Q-96 (.340): lo anulado por un reembolso CONFIRMADO no viaja a la DIAN, en ningún camino. El reembolso se hace como lo hace Odoo (``refund_sheet``: copia el recibo y niega sus líneas) y se confirma. Todo con *mock*:
ninguna prueba llama a la DIAN."""

from datetime import date, datetime

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.l10n_co_nomina_electronica.services import nomina_xml_builder

from . import test_documento_enviar as enviar
from . import test_nota_ajuste_enviar as notas
from .common_documento import DocumentoFixture
from .test_nota_ajuste import XML_NOTA

LIQUIDACION = 'l10n_co_nomina_electronica.hr_payroll_structure_co_liquidacion'


def _linea(env, recibo, valor):
    regla = env.ref('l10n_co_nomina_electronica.hr_salary_rule_co_basico')
    env['hr.payslip.line'].create({
        'slip_id': recibo.id, 'salary_rule_id': regla.id, 'code': regla.code, 'name': regla.name, 'contract_id': recibo.contract_id.id, 'employee_id': recibo.employee_id.id,
        'sequence': 1, 'quantity': 1.0, 'rate': 100.0, 'amount': valor, 'total': valor})


def _reembolsar(recibo, confirmar=True):
    accion = recibo.refund_sheet()
    reembolso = recibo.env['hr.payslip'].browse(accion['domain'][0][2])
    if confirmar:
        reembolso.write({'state': 'done'})
    return reembolso


@tagged('post_install', '-at_install')
class TestDocumentoReembolsos(DocumentoFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        enviar.TestDocumentoEnviar._preparar_compania(cls, 'Compañía Reembolsos')

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

    def _otro(self, base, valor, documento=False, estructura=None, **vals):
        """Un recibo nuevo (creado ahora) del mismo pago que ``base``, confirmado y pagado."""
        datos = {'name': 'Recibo nuevo', 'employee_id': base.employee_id.id, 'contract_id': base.contract_id.id, 'company_id': base.company_id.id,
                 'struct_id': (self.env.ref(estructura) if estructura else base.struct_id).id, 'date_from': base.date_from, 'date_to': base.date_to}
        datos.update(vals)
        recibo = self.env['hr.payslip'].create(datos)
        _linea(self.env, recibo, valor)
        recibo.write({'state': 'paid', 'paid_date': base.paid_date, 'l10n_co_ne_documento_id': documento and documento.id})
        return recibo

    def _claves(self, doc):
        return [a['key'].rsplit('_', 1)[0] if a['key'].startswith('recibo_reembolsado') else a['key'] for a in (doc.alertas or []) if a['level'] == 'danger']

    # ── la regla ─────────────────────────────────────────────────────
    def test_la_liquidacion_reembolsada_no_viaja_ni_da_fecha_de_retiro(self):
        doc = self._doc()
        quincenas = doc.payslip_ids
        base = quincenas.sorted('date_to')[-1]
        liquidacion = self._otro(base, 2328518.08, documento=doc, estructura=LIQUIDACION, date_from=doc.contract_id.date_start)
        self.assertEqual(doc.payslip_ids._ne_fecha_retiro(), str(base.date_to))
        reembolso = _reembolsar(liquidacion)
        self.assertEqual(reembolso._ne_huella_de_lineas(-1), liquidacion._ne_huella_de_lineas(), 'Premisa: el reembolso nativo niega las líneas del original')
        resultado = self.Documento._ne_preparar(doc.payslip_ids | reembolso)
        self.assertEqual((resultado['documentos'], doc.payslip_ids), (doc, quincenas))
        motivos = {recibo: motivo for recibo, motivo in resultado['sin_fecha']}
        self.assertIn('anulado por un reembolso', motivos[liquidacion])
        self.assertIn('es un reembolso', motivos[reembolso])
        self.assertEqual(doc._ne_periodo(doc.contract_id)['FechaRetiro'], '')
        doc.action_generar_xml()

    def test_si_el_reembolsado_se_cancela_y_se_rehace_el_nuevo_si_viaja_con_su_retiro(self):
        doc = self._doc()
        quincenas = doc.payslip_ids
        base = quincenas.sorted('date_to')[-1]
        anulada = self._otro(base, 2000000.0, documento=doc, estructura=LIQUIDACION, date_from=doc.contract_id.date_start)
        _reembolsar(anulada)
        anulada.write({'state': 'cancel'})
        nueva = self._otro(anulada, 1900000.0)
        self.assertEqual((anulada | nueva)._ne_reembolsos(), (anulada, []))
        self.assertEqual(nueva._ne_fecha_retiro(), str(nueva.date_to))
        self.Documento._ne_preparar(nueva)
        self.assertEqual(doc.payslip_ids, quincenas | nueva)
        self.assertEqual(doc._ne_periodo(doc.contract_id)['FechaRetiro'], str(nueva.date_to))
        doc.action_generar_xml()

    def test_reembolsado_y_corregido_de_las_mismas_fechas_viaja_solo_el_corregido(self):
        for corregido_antes_del_reembolso in (False, True):
            with self.subTest(corregido_antes_del_reembolso=corregido_antes_del_reembolso):
                doc = self._doc(pagos=((15, 15),))
                original = doc.payslip_ids
                if corregido_antes_del_reembolso:
                    corregido = self._otro(original, 1400000.0)
                    _reembolsar(original)
                else:
                    _reembolsar(original)
                    corregido = self._otro(original, 1400000.0)
                self.assertEqual((original | corregido)._ne_reembolsos(), (original, []))
                self.Documento._ne_preparar(original | corregido)
                self.assertEqual(doc.payslip_ids, corregido)
                doc.action_generar_xml()

    def test_un_reembolso_sin_confirmar_no_excluye_y_al_confirmarlo_sale_solo_el_suyo(self):
        doc = self._doc()
        primera, segunda = doc.payslip_ids.sorted('date_to')
        reembolso = _reembolsar(primera, confirmar=False)
        self.Documento._ne_preparar(doc.payslip_ids)
        self.assertEqual(doc.payslip_ids, primera | segunda)
        reembolso.write({'state': 'done'})
        self.Documento._ne_preparar(doc.payslip_ids)
        self.assertEqual(doc.payslip_ids, segunda)

    def test_un_mes_completo_reembolsado_no_arma_documento_ni_xml(self):
        doc = self._doc()
        recibos = doc.payslip_ids
        for recibo in recibos:
            _reembolsar(recibo)
        resultado = self.Documento._ne_preparar(recibos)
        self.assertFalse(doc.exists())                            # nunca viajó: no queda un documento vacío
        self.assertFalse(resultado['documentos'])
        self.assertEqual({recibo for recibo, _motivo in resultado['sin_fecha']}, set(recibos))

    def test_un_documento_con_historia_que_queda_sin_recibos_no_genera_xml(self):
        doc = self._doc()
        recibos = doc.payslip_ids
        doc._ne_validar()
        doc.action_generar_xml()
        doc._ne_encolar()
        self.soap.return_value = enviar.RECHAZO
        doc._ne_enviar_uno()
        for recibo in recibos:
            _reembolsar(recibo)
        self.Documento._ne_preparar(recibos)
        self.assertTrue(doc.exists())
        self.assertFalse(doc.payslip_ids)
        self.assertIn('sin_recibos', self._claves(doc))
        with self.assertRaises(UserError):
            doc.action_generar_xml()

    def test_confirmado_despues_de_generar_y_encolar_no_se_transmite(self):
        doc = self._doc()
        primera, segunda = doc.payslip_ids.sorted('date_to')
        doc._ne_validar()
        doc.action_generar_xml()
        doc._ne_encolar()
        self.assertTrue(doc.is_being_sent)
        _reembolsar(segunda)
        self.assertFalse(doc.is_being_sent)
        self.assertFalse(doc.xml_attachment_id)
        with self.assertRaises(UserError):
            doc._ne_enviar_uno()
        self.soap.assert_not_called()
        with self.assertRaisesRegex(UserError, 'reembolso'):      # sin volver a preparar tampoco se genera
            doc.action_generar_xml()
        self.assertIn('recibo_reembolsado', self._claves(doc))
        self.Documento._ne_preparar(doc.payslip_ids)
        self.assertEqual(doc.payslip_ids, primera)
        doc.action_generar_xml()

    def test_un_envio_fallido_con_un_recibo_reembolsado_despues_no_se_reenvia(self):
        doc = self._doc()
        doc._ne_validar()
        doc.action_generar_xml()
        doc._ne_encolar()
        self.soap.return_value = enviar.CONEXION
        doc._ne_enviar_uno()
        self.assertEqual(doc.state, 'invoice_sending_failed')
        _reembolsar(doc.payslip_ids.sorted('date_to')[-1])
        doc._ne_enviar_uno()                                      # consulta por CUNE (no lo conoce) y no reenvía
        self.assertEqual(self.soap.call_count, 1)
        with self.assertRaisesRegex(UserError, 'reembolso'):
            doc._ne_exigir_pagos_vigentes(contra_el_xml=True)

    def test_si_no_se_puede_saber_cual_se_anulo_se_detiene_nombrandolos(self):
        doc = self._doc(pagos=((15, 15),))
        primero = doc.payslip_ids
        segundo = self._otro(primero, primero.line_ids.total, documento=doc)
        segundo.paid_date = date(2026, 3, 20)                     # mismas líneas y fechas del periodo, otro pago
        _reembolsar(primero)
        anulados, dudas = (primero | segundo)._ne_reembolsos()
        self.assertFalse(anulados)
        self.assertEqual(len(dudas), 1)
        for recibo in (primero, segundo):
            self.assertIn('id %s' % recibo.id, dudas[0])
        doc._ne_validar()
        self.assertIn('reembolso_dudoso', self._claves(doc))
        with self.assertRaisesRegex(UserError, 'No se puede saber'):
            doc.action_generar_xml()

    def test_con_tantos_reembolsos_como_recibos_iguales_quedan_anulados_sin_duda(self):
        for dias_de_pago in ((15, 15), (15, 20)):
            with self.subTest(dias_de_pago=dias_de_pago):
                doc = self._doc(pagos=((15, dias_de_pago[0]),))
                primero = doc.payslip_ids
                segundo = self._otro(primero, primero.line_ids.total, documento=doc)
                segundo.paid_date = date(2026, 3, dias_de_pago[1])
                _reembolsar(primero)
                _reembolsar(segundo)
                self.assertEqual((primero | segundo)._ne_reembolsos(), (primero | segundo, []))

    def test_un_reembolso_solo_anula_recibos_anteriores_aunque_los_numeros_cuadren(self):
        doc = self._doc(pagos=((15, 15),))
        primero = doc.payslip_ids
        _reembolsar(primero)
        _reembolsar(primero)                                      # dos reembolsos y dos recibos iguales, pero el segundo recibo es posterior a ambos
        despues = self._otro(primero, primero.line_ids.total, documento=doc)
        self.assertEqual((primero | despues)._ne_reembolsos(), (primero, []))

    def test_con_menos_reembolsos_que_recibos_iguales_y_distinta_fecha_de_pago_sigue_la_duda(self):
        doc = self._doc(pagos=((15, 15),))
        primero = doc.payslip_ids
        segundo = self._otro(primero, primero.line_ids.total, documento=doc)
        segundo.paid_date = date(2026, 3, 20)
        _reembolsar(primero)
        despues = self._otro(primero, primero.line_ids.total, documento=doc)          # creado después: no entra en la duda
        anulados, dudas = (primero | segundo | despues)._ne_reembolsos()
        self.assertEqual((anulados, len(dudas)), (primero.browse(), 1))
        self.assertNotIn('id %s' % despues.id, dudas[0])

    def test_un_anulado_sin_fecha_de_pago_no_falta_en_el_mes(self):
        doc = self._doc(pagos=((15, 15),))
        otro = self._otro(doc.payslip_ids, 900000.0, date_from=date(2026, 3, 16), date_to=date(2026, 3, 31))
        otro.paid_date = False
        periodo = date(2026, 3, 1)
        self.assertIn(otro, self.Documento._ne_recibos_que_faltan(self.company, otro.employee_id, periodo, doc.payslip_ids))
        _reembolsar(otro)
        self.assertNotIn(otro, self.Documento._ne_recibos_que_faltan(self.company, otro.employee_id, periodo, doc.payslip_ids))

    def test_por_recibo_ni_el_anulado_ni_el_reembolso_se_generan_o_envian(self):
        self.company.l10n_co_ne_environment = '2'                 # el ciclo por recibo es el de habilitación
        recibo = self._doc(pagos=((15, 15),)).payslip_ids
        recibo.write({'l10n_co_ne_documento_id': False, 'state': 'done'})
        reembolso = _reembolsar(recibo)
        (recibo | reembolso).write({'l10n_co_ne_state': 'generated'})
        for registro, texto in ((recibo, 'anulado por un reembolso'), (reembolso, 'es un reembolso')):
            for accion in ('_validate_ne_prerequisites', 'action_send_ne_dian', 'action_send_test_set'):
                with self.subTest(registro=texto, accion=accion), self.assertRaisesRegex(UserError, texto):
                    getattr(registro, accion)()
        self.soap.assert_not_called()


@tagged('post_install', '-at_install')
class TestNotaConReembolso(notas.TestNotaAjusteEnviar):
    """Nota «Reemplazar» sobre un documento aceptado (fixture de ``TestNotaAjusteEnviar``: dos quincenas aceptadas)."""

    def setUp(self):
        super().setUp()

        def con_totales(datos):
            raiz = etree.fromstring(XML_NOTA)
            destino = raiz.find('{*}Reemplazar')
            destino = raiz if destino is None else destino
            for nombre, clave in (('DevengadosTotal', 'devengados_total'), ('DeduccionesTotal', 'deducciones_total')):
                etree.SubElement(destino, nombre).text = '%.2f' % datos[clave]
            return etree.tostring(raiz)
        self._patch(nomina_xml_builder, 'build_nota_ajuste_v2', con_totales)
        self.primera, self.segunda = self.padre.payslip_ids.sorted('date_to')

    def test_la_nota_deja_fuera_lo_anulado_y_el_documento_aceptado_solo_avisa(self):
        _reembolsar(self.segunda)
        self.padre._ne_validar()
        self.assertEqual(self.padre.payslip_ids, self.primera | self.segunda)     # lo aceptado no se toca
        aviso = [a for a in self.padre.alertas if a['key'] == 'recibo_reembolsado_%s' % self.segunda.id]
        self.assertEqual([a['level'] for a in aviso], ['warning'])
        nota = self._nota_lista('1')
        self.assertEqual(nota._ne_recibos_para_xml(), self.primera)
        nota._ne_exigir_pagos_vigentes(contra_el_xml=True)       # armada sin lo anulado: se puede enviar

    def test_un_reembolso_descarta_el_xml_de_la_nota_sin_enviar(self):
        nota = self._nota_lista('1')
        self.assertTrue(nota.xml_attachment_id)
        _reembolsar(self.segunda)
        self.assertFalse(nota.xml_attachment_id)

    def test_un_xml_de_nota_con_envio_fallido_armado_antes_del_reembolso_no_se_reenvia(self):
        nota = self._nota_lista('1')
        nota._ne_exigir_pagos_vigentes(contra_el_xml=True)
        self.soap.return_value = enviar.CONEXION
        nota._ne_enviar_uno()
        self.assertEqual(nota.state, 'invoice_sending_failed')
        _reembolsar(self.segunda)
        with self.assertRaisesRegex(UserError, 'reembolso'):      # es la comprobación que corre antes de cualquier reintento
            nota._ne_exigir_pagos_vigentes(contra_el_xml=True)
