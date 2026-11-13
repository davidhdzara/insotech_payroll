# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.

"""
Asistente transaccional para procesar y enviar Nóminas Electrónicas a la DIAN
y recibos de pago en PDF por correo electrónico a los empleados.

Inspirado en la arquitectura nativa de facturación de Odoo 18 (account.move.send).
Permite procesamiento masivo e individual desde el formulario de nómina y la vista de lista.
"""

import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrPayslipSend(models.TransientModel):
    """Asistente para firmar, transmitir a la DIAN y enviar nóminas por correo."""

    _name = 'hr.payslip.send'
    _description = 'Enviar y Procesar Nómina Electrónica'

    # ──────────────────────────────────────────────────────────────────
    # Relaciones y Configuración Base
    # ──────────────────────────────────────────────────────────────────
    payslip_ids = fields.Many2many(
        comodel_name='hr.payslip',
        string='Nóminas a Procesar',
        required=True,
    )
    mode = fields.Selection(
        selection=[
            ('single', 'Nómina Individual'),
            ('multi', 'Procesamiento Masivo'),
        ],
        string='Modo de Envío',
        compute='_compute_mode',
        store=True,
    )

    # ──────────────────────────────────────────────────────────────────
    # Opciones de Envío (DIAN & Email)
    # ──────────────────────────────────────────────────────────────────
    checkbox_send_dian = fields.Boolean(
        string='Enviar a la DIAN',
        default=True,
        help='Si está marcado, se generará el XML, se firmará digitalmente y se transmitirá '
             'al webservice de la DIAN para su aprobación oficial.',
    )
    checkbox_send_mail = fields.Boolean(
        string='Enviar colilla por correo',
        help='Si está marcado, se envía la colilla (PDF) de cada recibo confirmado al correo del contacto de trabajo '
             'del empleado, por la cola de correo. Es independiente del estado ante la DIAN.',
    )
    mail_template_id = fields.Many2one(
        comodel_name='mail.template',
        string='Plantilla de Correo',
        domain="[('model', '=', 'hr.payslip')]",
        help='Plantilla de correo electrónico que se utilizará para estructurar el mensaje '
             'que se envía al empleado junto con su recibo de nómina en PDF.',
    )

    # ──────────────────────────────────────────────────────────────────
    # Computes y Defaults
    # ──────────────────────────────────────────────────────────────────
    @api.depends('payslip_ids')
    def _compute_mode(self):
        for rec in self:
            rec.mode = 'multi' if len(rec.payslip_ids) > 1 else 'single'

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self._context.get('active_ids')
        active_model = self._context.get('active_model')

        if active_model == 'hr.payslip' and active_ids:
            res['payslip_ids'] = [(6, 0, active_ids)]
            # Plantilla nativa por xmlid (nunca "la primera"); si falta, queda vacía y el envío da un error claro.
            template = self.env.ref(self.env['hr.payslip'].NE_MAIL_TEMPLATE_XMLID, raise_if_not_found=False)
            if template:
                res['mail_template_id'] = template.id
        return res

    # ──────────────────────────────────────────────────────────────────
    # Botón Principal: Ejecutar Procesamiento
    # ──────────────────────────────────────────────────────────────────
    def _ne_aviso_resultado(self, resumen, problemas, avisos):
        """Notificación nativa con el resultado: nada se traga en silencio (los problemas se listan)."""
        lineas = [resumen] + [_('Problema: %s', p) for p in problemas] + [_('Aviso: %s', a) for a in avisos]
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _('Enviar y Procesar'), 'message': '\n'.join(lineas),
                       'type': 'warning' if problemas else 'success', 'sticky': bool(problemas),
                       'next': {'type': 'ir.actions.act_window_close'}}}

    def action_send_and_print(self):
        """Transmite por recibo (ciclo de habilitación) y envía la colilla por correo; ambos independientes."""
        self.ensure_one()
        if not self.payslip_ids:
            raise UserError(_('No hay nóminas cargadas para procesar en el asistente.'))
        template = False
        if self.checkbox_send_mail:
            template = self.mail_template_id or self.env['hr.payslip']._ne_plantilla_colilla()
        problemas, avisos = [], []
        transmitidos = enviados = 0

        for payslip in self.payslip_ids:
            nombre = payslip.number or payslip.name
            # 1. Ciclo DIAN por recibo (habilitación). Un recibo que va en un documento mensual se transmite desde él.
            if self.checkbox_send_dian and payslip.l10n_co_ne_state in ('draft', 'generated', 'rejected'):
                doc = payslip.l10n_co_ne_documento_id
                if doc and not doc.legacy:
                    avisos.append(_('%(recibo)s: se transmite desde el documento mensual "%(doc)s".',
                                    recibo=nombre, doc=doc.display_name))
                else:
                    try:
                        if payslip.l10n_co_ne_state == 'draft':
                            payslip.action_generate_ne_xml()
                        payslip.action_send_ne_dian()
                        transmitidos += 1
                    except Exception as error:   # el lote sigue: el error se lista y queda en el chatter
                        _logger.error('Fallo en transmision DIAN para nomina %s: %s', nombre, error)
                        problemas.append(_('%(recibo)s: no se transmitió (%(error)s).', recibo=nombre, error=error))
                        payslip.message_post(
                            body=_('Error de transmisión automatizada: %s', error), message_type='comment')
            # 2. Colilla por correo: por recibo confirmado, sin depender del estado DIAN.
            if self.checkbox_send_mail:
                if payslip.message_ids.filtered(lambda m: m.body and 'Colilla enviada por correo' in str(m.body)):
                    avisos.append(_('%s: ya se había enviado la colilla por correo antes.', nombre))
                try:
                    with self.env.cr.savepoint():
                        payslip.action_send_payslip_email(template)
                    enviados += 1
                except Exception as error:
                    _logger.error('Fallo en envio de correo para nomina %s: %s', nombre, error)
                    problemas.append(_('%(recibo)s: no se envió la colilla (%(error)s).', recibo=nombre, error=error))
                    payslip.message_post(
                        body=_('Fallo al enviar la colilla por correo: %s', error), message_type='comment')

        resumen = _('Recibos: %(total)s. Transmitidos por recibo: %(t)s. Colillas encoladas para envío: %(e)s.',
                    total=len(self.payslip_ids), t=transmitidos, e=enviados)
        return self._ne_aviso_resultado(resumen, problemas, avisos)
