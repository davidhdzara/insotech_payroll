# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.

"""Etapa 4, commit 8b (doc 53 §23.17): colilla por correo desacoplada de la DIAN y los 5 defectos del asistente
``hr.payslip.send`` (cada prueba ``test_defecto_*`` falla contra el código anterior). Sin SMTP: la cola nativa de
correo (``mail.mail`` en ``outgoing``); el PDF se parchea."""

import re
from datetime import date
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

from .common_documento import DocumentoFixture

EMOJIS = re.compile('[\U0001F000-\U0001FAFF☀-➿⬀-⯿]')


@tagged('post_install', '-at_install')
class TestPayslipSendCorreo(DocumentoFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture_documento('Compañía Colilla')
        modelo = cls.env['ir.model']._get('hr.payslip')
        # Una plantilla que se ordena PRIMERO por nombre ("la primera" del código viejo) y la nativa de la prueba.
        cls.primera = cls.env['mail.template'].create({
            'name': 'AAA primera plantilla', 'model_id': modelo.id, 'subject': 'Otra', 'body_html': '<p>Otra</p>'})
        cls.nativa = cls.env['mail.template'].create({
            'name': 'ZZZ colilla', 'model_id': modelo.id, 'subject': 'Colilla', 'body_html': '<p>Colilla</p>'})
        cls.env['ir.model.data'].create({
            'module': 'l10n_co_nomina_electronica', 'name': 'tpl_colilla_prueba', 'model': 'mail.template',
            'res_id': cls.nativa.id})

    def setUp(self):
        super().setUp()
        self._patch(type(self.env['hr.payslip']), 'NE_MAIL_TEMPLATE_XMLID',
                    'l10n_co_nomina_electronica.tpl_colilla_prueba')
        self._patch(type(self.env['ir.actions.report']), '_render_qweb_pdf', lambda s, *a, **k: (b'%PDF-1.4', 'pdf'))
        self.doc = self._documento(date(2024, 3, 1))
        self.recibos = self.doc.payslip_ids
        self.recibos.write({'l10n_co_ne_documento_id': False})
        self.slip = self.recibos[0]
        contacto = self.env['res.partner'].create({'name': 'Contacto trabajo', 'email': 'contacto@ejemplo.co'})
        # En Odoo 18 work_email ES el email del contacto de trabajo (related con inverse): no son dos datos distintos.
        # Escribir un work_email distinto junto con el contacto pisaba el correo del contacto (causa de reg_ak).
        self.slip.employee_id.write({'work_contact_id': contacto.id})
        self.assertEqual(self.slip.employee_id.work_contact_id.email, 'contacto@ejemplo.co')

    def _asistente(self, recibos=None, **vals):
        datos = {'payslip_ids': [(6, 0, (recibos or self.slip).ids)], 'checkbox_send_dian': False,
                 'checkbox_send_mail': True}
        datos.update(vals)
        return self.env['hr.payslip.send'].create(datos)

    def _ejecutar(self, asistente):
        """Los fallos simulados se registran con ``_logger.error`` a propósito: se silencian aquí para no dejar ERROR
        inesperado en el log de la regresión."""
        with mute_logger('odoo.addons.l10n_co_nomina_electronica.wizard.hr_payslip_send'):
            return asistente.action_send_and_print()

    def _mensaje(self, accion):
        return accion['params']['message']

    def _correos(self, destino='contacto@ejemplo.co'):
        """Correos en cola de los recibos de la prueba cuyo destinatario es ``destino``. Se busca por modelo y recibo (no
        por el literal de ``email_to``, que Odoo puede normalizar) y se compara el destinatario por ``email_to`` o por
        ``recipient_ids``."""
        correos = self.env['mail.mail'].search([('model', '=', 'hr.payslip'), ('res_id', 'in', self.recibos.ids)])
        return correos.filtered(lambda m: destino in (m.email_to or '') or destino in m.recipient_ids.mapped('email'))

    # ── destinatario, cola y estado ──────────────────────────────────
    def test_el_correo_creado_tiene_el_destinatario_y_queda_en_cola(self):
        """Lectura directa del mail.mail que crea la plantilla (sin pasar por el asistente)."""
        self.slip.action_send_payslip_email(self.nativa)
        correos = self.env['mail.mail'].search([('model', '=', 'hr.payslip'), ('res_id', '=', self.slip.id)])
        self.assertEqual(len(correos), 1, 'La plantilla no dejó ningún mail.mail para el recibo')
        self.assertIn('contacto@ejemplo.co', (correos.email_to or '') + ' '.join(correos.recipient_ids.mapped('email')))
        self.assertEqual(correos.state, 'outgoing')

    def test_destinatario_es_el_contacto_de_trabajo_y_sale_por_la_cola(self):
        self._ejecutar(self._asistente())
        correo = self._correos()
        self.assertEqual(len(correo), 1)
        self.assertEqual(correo.state, 'outgoing')                  # cola nativa, sin force_send

    def test_defecto_correo_condicionado_al_estado_dian(self):
        """El recibo NO está aceptado por la DIAN (ciclo por recibo en borrador): la colilla sale igual."""
        self.assertEqual(self.slip.l10n_co_ne_state, 'draft')
        self._ejecutar(self._asistente())
        self.assertEqual(len(self._correos()), 1)

    def test_recibo_en_borrador_da_error_por_recibo_y_no_aborta_a_los_demas(self):
        otro = self.recibos[1]
        otro.employee_id.write({'work_contact_id': self.slip.employee_id.work_contact_id.id})
        self.slip.state = 'draft'
        accion = self._ejecutar(self._asistente(self.slip | otro))
        self.assertIn('no está confirmado', self._mensaje(accion))
        self.assertEqual(len(self._correos()), 1)                    # el otro sí salió

    def test_empleado_sin_correo_se_lista(self):
        self.slip.employee_id.work_contact_id.email = False
        accion = self._ejecutar(self._asistente())
        self.assertIn('no tiene correo', self._mensaje(accion))
        self.assertFalse(self._correos())

    def test_aviso_sin_bloqueo_si_ya_se_envio(self):
        self._ejecutar(self._asistente())
        accion = self._ejecutar(self._asistente())
        self.assertIn('ya se había enviado', self._mensaje(accion))
        self.assertEqual(len(self._correos()), 2)

    # ── plantilla ────────────────────────────────────────────────────
    def test_defecto_plantilla_la_primera(self):
        """El valor por defecto es la plantilla por xmlid, no la primera de la base (que aquí es otra)."""
        valores = self.env['hr.payslip.send'].with_context(
            active_model='hr.payslip', active_ids=self.slip.ids).default_get(['mail_template_id'])
        self.assertEqual(valores['mail_template_id'], self.nativa.id)
        self.assertNotEqual(self.nativa, self.primera)

    def test_sin_plantilla_elegida_se_usa_la_del_xmlid(self):
        self._ejecutar(self._asistente())
        self.assertEqual(self._correos().subject, 'Colilla')

    def test_plantilla_faltante_error_con_el_xmlid(self):
        self._patch(type(self.env['hr.payslip']), 'NE_MAIL_TEMPLATE_XMLID', 'hr_payroll.no_existe_colilla')
        with self.assertRaisesRegex(UserError, 'hr_payroll.no_existe_colilla'):
            self._ejecutar(self._asistente())
        self.assertFalse(self._correos())

    def test_otra_plantilla_elegida_funciona(self):
        self._ejecutar(self._asistente(mail_template_id=self.primera.id))
        self.assertEqual(self._correos().subject, 'Otra')

    # ── adjunto ──────────────────────────────────────────────────────
    def test_el_adjunto_se_reutiliza_entre_envios(self):
        self._ejecutar(self._asistente())
        self._ejecutar(self._asistente())
        adjuntos = self.env['ir.attachment'].search([
            ('res_model', '=', 'hr.payslip'), ('res_id', '=', self.slip.id), ('mimetype', '=', 'application/pdf')])
        self.assertEqual(len(adjuntos), 1)

    def test_sin_reporte_error_claro_que_nombra_estructura_y_reporte(self):
        self._patch(type(self.env['hr.payslip']), 'NE_REPORT_XMLID', 'l10n_co_nomina_electronica.no_existe_reporte')
        accion = self._ejecutar(self._asistente())
        self.assertIn('no_existe_reporte', self._mensaje(accion))
        self.assertIn(self.slip.struct_id.display_name, self._mensaje(accion))

    # ── errores: no se tragan ni abortan, sin emojis ─────────────────
    def test_defecto_error_tragado_sin_aviso(self):
        """Un error de render en un recibo queda en el resultado y en el chatter; los demás siguen."""
        otro = self.recibos[1]
        otro.employee_id.write({'work_contact_id': self.slip.employee_id.work_contact_id.id})

        def render(modelo, reporte_id, ids, *a, **k):
            if self.slip.id in ids:
                raise ValueError('fallo de render')
            return b'%PDF-1.4', 'pdf'
        self._patch(type(self.env['ir.actions.report']), '_render_qweb_pdf', render)
        accion = self._ejecutar(self._asistente(self.slip | otro))
        self.assertIn('fallo de render', self._mensaje(accion))
        self.assertEqual(accion['params']['type'], 'warning')
        self.assertEqual(len(self._correos()), 1)
        self.assertTrue(self.slip.message_ids.filtered(lambda m: 'fallo de render' in str(m.body)))

    def test_defecto_emojis_en_el_chatter(self):
        self._patch(type(self.env['ir.actions.report']), '_render_qweb_pdf',
                    lambda s, *a, **k: (_ for _ in ()).throw(ValueError('boom')))
        self._ejecutar(self._asistente())
        cuerpos = ' '.join(str(m.body) for m in self.slip.message_ids)
        self.assertIn('boom', cuerpos)
        self.assertFalse(EMOJIS.search(cuerpos))

    def test_defecto_transmision_dian_fallida_se_avisa_y_sin_emojis(self):
        def falla(slip):
            raise UserError('rechazo local')
        self._patch(type(self.env['hr.payslip']), 'action_generate_ne_xml', falla)
        accion = self._ejecutar(self._asistente(checkbox_send_dian=True, checkbox_send_mail=False))
        self.assertIn('rechazo local', self._mensaje(accion))
        cuerpos = ' '.join(str(m.body) for m in self.slip.message_ids)
        self.assertIn('rechazo local', cuerpos)
        self.assertFalse(EMOJIS.search(cuerpos))

    def test_recibo_con_documento_no_se_transmite_por_recibo(self):
        self.slip.l10n_co_ne_documento_id = self.doc      # el documento del mes ya existe (setUp)
        llamado = []
        self._patch(type(self.env['hr.payslip']), 'action_generate_ne_xml', lambda s: llamado.append(1))
        accion = self._ejecutar(self._asistente(checkbox_send_dian=True, checkbox_send_mail=False))
        self.assertFalse(llamado)
        self.assertIn('se transmite desde el documento mensual', self._mensaje(accion))

    def test_el_asistente_tiene_pruebas_y_ya_no_tiene_los_campos_retirados(self):
        campos = self.env['hr.payslip.send']._fields
        self.assertNotIn('enable_send_mail', campos)
        self.assertIn('checkbox_send_mail', campos)
