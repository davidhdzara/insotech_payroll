# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""Intento de envío de un documento mensual a la DIAN (doc 53 §16.2, §18.2): calco de ``l10n_co_dian.document``.

Es el resumen MUTABLE de un envío (cambia de estado al consultar); la evidencia cruda inmutable sigue en
``l10n.co.ne.exchange``."""

from markupsafe import Markup

from odoo import _, api, fields, models

from ..services import dian_message


class L10nCoNeDocumentoIntento(models.Model):
    _name = 'l10n.co.ne.documento.intento'
    _description = 'Intento de envío del documento mensual a la DIAN'
    _order = 'datetime desc, id desc'
    _check_company_auto = True

    documento_id = fields.Many2one('l10n.co.ne.documento', string='Documento', required=True,
                                   ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one('res.company', related='documento_id.company_id', store=True,
                                 index=True, readonly=True)
    datetime = fields.Datetime(string='Fecha y hora', help='Momento del envío (UTC en base de datos; se muestra en la zona del usuario).')
    state = fields.Selection([
        ('invoice_sending_failed', 'Envío fallido'),
        ('invoice_pending', 'Pendiente'),
        ('invoice_rejected', 'Rechazado'),
        ('invoice_accepted', 'Aceptado'),
    ], string='Estado DIAN', required=True, copy=False,
        help='Estado de ESTE envío; se actualiza al consultar. Mismas claves que el estado nativo de la factura electrónica.')
    identifier = fields.Char(string='CUNE', copy=False, index=True)
    zip_key = fields.Char(string='ZipKey', copy=False)
    numero = fields.Char(string='Número', copy=False, help='Consecutivo usado en este envío (cada intento conserva el suyo).')
    file_name = fields.Char(string='Archivo', copy=False)
    sha256 = fields.Char(string='SHA-256', copy=False)
    attachment_id = fields.Many2one('ir.attachment', string='Adjunto', copy=False, ondelete='set null')
    message_json = fields.Json(string='Respuesta DIAN (datos)', copy=False)
    message = fields.Html(string='Motivo', compute='_compute_message', sanitize=False)
    test_environment = fields.Boolean(string='Ambiente de pruebas')
    certification_process = fields.Boolean(string='Proceso de habilitación')
    exchange_id = fields.Many2one('l10n.co.ne.exchange', string='Evidencia DIAN', copy=False,
                                  ondelete='set null', check_company=True)
    show_button_get_status = fields.Boolean(compute='_compute_show_button_get_status')

    @api.depends('message_json')
    def _compute_message(self):
        for intento in self:
            texto = dian_message.render_message_html(intento.message_json, translate=_)
            intento.message = Markup(texto) if texto else False

    @api.depends('state', 'zip_key')
    def _compute_show_button_get_status(self):
        for intento in self:
            intento.show_button_get_status = bool(intento.zip_key) and intento.state in (
                'invoice_pending', 'invoice_sending_failed')
