# -*- coding: utf-8 -*-
"""Q-19 (doc 116, .332): la nómina electrónica informa los días de la prima y de las vacaciones compensadas pagadas como novedad en pesos (antes salía ``Cantidad="1"``).

Los días van en una novedad aparte, sin regla: se registran con «Días de prima y vacaciones» en un recibo en borrador o confirmado sin reportar, sin cambiar valores.
Porte v19 (versión, estado validated). NO ejecutado en Odoo."""

import base64
from datetime import date
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from .common_version import confirmar_a_mano, crear_empleado_con_contrato

NATIVO = 'odoo.addons.hr_payroll.models.hr_payslip.HrPayslip.action_payslip_done'


@tagged('post_install', '-at_install')
class TestDiasDePrimaYVacacionesCompensadas(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U', 'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_clase_riesgo': '1',
            'l10n_co_ne_febrero_modo': 'real', 'l10n_co_ne_redondeo_dias': 'DOWN', 'name': 'Compañía Días de Prima'})
        cls.env = cls.company.with_company(cls.company).env
        cls.tipo = cls.env['hr.payroll.structure.type'].create({'name': 'Tipo Días de Prima', 'country_id': cls.env.ref('base.co').id})
        cls.general = cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
        cls.n = 0

    # ── fixtures ─────────────────────────────────────────────────────
    def _recibo(self, novedades=(('input_co_prima', 500000.0), ('input_co_vac_comp', 300000.0))):
        type(self).n += 1
        empleado, version = crear_empleado_con_contrato(self.env, self.company, 3000000.0, date(2026, 1, 1), self.tipo, nombre='Empleado Dias %s' % self.n)
        version.generate_work_entries(date(2026, 9, 1), date(2026, 9, 30))
        recibo = self.env['hr.payslip'].create({
            'name': 'Recibo Dias %s' % self.n, 'employee_id': empleado.id, 'version_id': version.id, 'company_id': self.company.id,
            'struct_id': self.general.id, 'date_from': date(2026, 9, 1), 'date_to': date(2026, 9, 15),
            'input_line_ids': [(0, 0, {'input_type_id': self.env.ref('l10n_co_nomina_electronica.%s' % xmlid).id, 'amount': monto}) for xmlid, monto in novedades]})
        recibo.compute_sheet()
        return recibo

    def _registrar(self, recibo, prima=180.0, vacaciones=5.0):
        return self.env['hr.payslip.dias.prestaciones'].create({'payslip_id': recibo.id, 'dias_prima': prima, 'dias_vacaciones': vacaciones}).action_registrar_dias()

    def _confirmar(self, recibo):
        """Confirma con las demás comprobaciones, el nativo y el asiento parchados; devuelve el parche del nativo (llamado = pasó)."""
        nombres = ['_ne_validar_duracion_periodo', '_ne_validar_sin_solape', '_ne_validar_cuenta_neto', '_ne_validar_pacto_no_salarial', '_ne_validar_afiliaciones',
                   '_ne_aplicar_libranzas', '_ne_refrescar_ibc_mensual', '_ne_validar_tramos_cubiertos']
        if hasattr(type(recibo), '_action_create_account_move'):        # el asiento de hr_payroll_account: fuera de lo que se prueba
            nombres.append('_action_create_account_move')
        parches = [patch.object(type(recibo), nombre) for nombre in nombres]
        for parche in parches:
            parche.start()
        try:
            with patch(NATIVO, return_value=True) as nativo:
                recibo.action_payslip_done()
        finally:
            for parche in parches:
                parche.stop()
        return nativo

    def _cantidades_del_xml(self, recibo):
        devengados = {}
        recibo._dev_prestaciones(recibo._group_lines_by_concept(), devengados)
        return devengados['Primas']['Cantidad'], devengados['Vacaciones']['VacacionesCompensadas'][0]['Cantidad']

    def _asiento(self, recibo):
        cuentas = self.env['account.account']
        for codigo, tipo in (('510599', 'expense'), ('250599', 'liability_current')):
            cuentas |= self.env['account.account'].create({'code': codigo, 'name': 'Cuenta %s' % codigo, 'account_type': tipo, 'company_ids': [(6, 0, self.company.ids)]})
        diario = self.env['account.journal'].create({'name': 'Salarios dias', 'code': 'SLDI', 'type': 'general', 'company_id': self.company.id})
        asiento = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': diario.id, 'date': date(2026, 9, 15), 'line_ids': [
                (0, 0, {'account_id': cuentas[0].id, 'debit': 800000.0, 'credit': 0.0, 'name': 'Gasto'}),
                (0, 0, {'account_id': cuentas[1].id, 'debit': 0.0, 'credit': 800000.0, 'name': 'Por pagar'})]})
        asiento.action_post()
        recibo.move_id = asiento
        return asiento

    def _foto(self, recibo):
        """Líneas (con su id), neto, estado y asiento: lo que registrar días en un confirmado no puede tocar."""
        return (sorted((l.id, l.code, l.quantity, l.amount, l.total) for l in recibo.line_ids), recibo.net_wage, recibo.state,
                recibo.move_id.id, recibo.move_id.state, sorted((a.id, a.account_id.id, a.debit, a.credit) for a in recibo.move_id.line_ids))

    # ── borrador: no se confirma sin días ────────────────────────────
    def test_en_borrador_no_se_confirma_sin_dias_y_con_ellos_si_sin_cambiar_valores(self):
        recibo = self._recibo()
        self.assertTrue(recibo.l10n_co_ne_puede_registrar_dias)
        with self.assertRaises(UserError) as error:
            self._confirmar(recibo)
        for texto in (recibo.name, recibo.employee_id.name, 'Prima de Servicios'):
            self.assertIn(texto, error.exception.args[0])
        valores = sorted((l.code, l.total) for l in recibo.line_ids)
        self._registrar(recibo)
        self.assertEqual(sorted((l.code, l.total) for l in recibo.line_ids), valores)
        self.assertEqual(self._cantidades_del_xml(recibo), ('180', '5'))
        self.assertTrue(self._confirmar(recibo).called)

    def test_un_reembolso_no_exige_dias(self):
        recibo = self._recibo()
        recibo.credit_note = True
        recibo._ne_validar_dias_de_prestaciones()
        self.assertFalse(recibo.l10n_co_ne_puede_registrar_dias)

    # ── confirmado sin reportar: solo la novedad de días ─────────────
    def test_confirmado_sin_dias_el_xml_falla_y_registrarlos_no_toca_lineas_neto_ni_asiento(self):
        recibo = self._recibo()
        confirmar_a_mano(recibo)                                # como quedó antes de la .332
        self._asiento(recibo)
        with self.assertRaises(UserError) as error:
            self._cantidades_del_xml(recibo)
        for texto in (recibo.name, recibo.employee_id.name, 'Días de prima y vacaciones'):
            self.assertIn(texto, error.exception.args[0])
        documento = self.env['l10n.co.ne.documento'].create({
            'company_id': self.company.id, 'employee_id': recibo.employee_id.id, 'version_id': recibo.version_id.id, 'period': date(2026, 9, 1)})
        recibo.l10n_co_ne_documento_id = documento
        adjunto = self.env['ir.attachment'].create({'name': 'ne.xml', 'datas': base64.b64encode(b'<x/>'), 'res_model': documento._name, 'res_id': documento.id})
        documento.write({'xml_attachment_id': adjunto.id, 'cune': 'a' * 96, 'etapa': 'ready'})
        foto = self._foto(recibo)
        self._registrar(recibo)
        self.assertEqual(self._foto(recibo), foto)
        self.assertEqual(self._cantidades_del_xml(recibo), ('180', '5'))
        self.assertFalse(documento.xml_attachment_id)           # el XML generado con la cantidad vieja no se puede enviar
        self.assertEqual(documento.etapa, 'draft')
        nota = [m.body for m in recibo.message_ids if '180' in (m.body or '')]
        self.assertEqual(len(nota), 1)
        for texto in ('no se recalculó la hoja ni cambió el asiento', 'genérelo de nuevo'):
            self.assertIn(texto, nota[0])
        mensajes = len(recibo.message_ids)
        self._registrar(recibo)                                 # los mismos días: nada que anotar
        self.assertEqual(len(recibo.message_ids), mensajes)

    def test_reportado_o_sin_prima_no_se_registra(self):
        recibo = self._recibo()
        confirmar_a_mano(recibo)
        recibo.l10n_co_ne_state = 'accepted'
        self.assertFalse(recibo.l10n_co_ne_puede_registrar_dias)
        with self.assertRaisesRegex(UserError, 'aún no se haya reportado'):
            self._registrar(recibo)
        self.assertFalse(self._recibo(novedades=(('input_co_bonif_nosal', 100000.0),)).l10n_co_ne_puede_registrar_dias)

    def test_los_dias_deben_ser_mayores_que_cero(self):
        recibo = self._recibo()
        with self.assertRaisesRegex(UserError, 'mayores que cero, de "Vacaciones Compensadas: días"'):
            self._registrar(recibo, vacaciones=0.0)

    def test_las_lineas_que_ya_traen_dias_conservan_su_cantidad(self):
        """Liquidación y estructura Prima: la cantidad de la línea ya son días y no se pide nada."""
        recibo = self._recibo(novedades=())
        regla = self.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_prima').rule_ids.filtered(lambda r: r.code == 'CO_PRIMA_VALOR')
        linea = self.env['hr.payslip.line'].create({
            'slip_id': recibo.id, 'salary_rule_id': regla.id, 'code': regla.code, 'name': regla.name, 'version_id': recibo.version_id.id,
            'employee_id': recibo.employee_id.id, 'quantity': 180.0, 'rate': 100.0, 'amount': 1000.0, 'total': 180000.0})
        self.assertEqual(recibo._ne_cantidad_en_dias([linea]), 180.0)
