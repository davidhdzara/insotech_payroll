# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""Documento mensual de nómina electrónica por empleado (doc 53 §3, §16.2, §18.6, §20).

Etapa 1b: SOLO el modelo, la relación con el recibo, las reglas multiempresa y la migración de lo ya
transmitido (``legacy``, 1:1). Todavía no genera XML ni envía (etapas 3 y 4): no hereda el mixin del ciclo
DIAN; sus campos de estado son ``etapa`` + ``state`` calculado del último intento (patrón de ``account.move`` +
``l10n_co_dian.document``)."""

import logging
from datetime import datetime as _dt

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services import dian_message
from ..services.soap_client import _parse_response

_logger = logging.getLogger(__name__)

# Mapa del estado del recibo (ciclo DIAN de hoy) al documento legacy: (etapa, estado del intento o None).
# 'generated' (XML con número, sin enviar) queda como etapa 'ready' con su CUNE/número/XML; 'uncertain'
# conserva un intento pendiente y la marca ``incierto``; 'eliminated' conserva un intento aceptado y ``eliminado``.
_MAPA_ESTADO_LEGACY = {
    'draft': ('draft', None),
    'generated': ('ready', None),
    'sent': ('draft', 'invoice_pending'),
    'uncertain': ('draft', 'invoice_pending'),
    'accepted': ('draft', 'invoice_accepted'),
    'rejected': ('draft', 'invoice_rejected'),
    'eliminated': ('draft', 'invoice_accepted'),
}
_OPERACIONES_ENVIO = ('send_sync', 'send_test_set')


class L10nCoNeDocumento(models.Model):
    _name = 'l10n.co.ne.documento'
    _description = 'Documento mensual de nómina electrónica'
    _inherit = ['mail.thread']
    _order = 'period desc, employee_id, id desc'
    _check_company_auto = True

    name = fields.Char(string='Documento', compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', string='Compañía', required=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    employee_id = fields.Many2one('hr.employee', string='Empleado', required=True, index=True,
                                  check_company=True, ondelete='restrict')
    contract_id = fields.Many2one('hr.contract', string='Contrato', check_company=True, ondelete='restrict',
                                  help='Contrato vigente en el mes (ingreso/retiro, tipo de contrato).')
    period = fields.Date(string='Mes', required=True, index=True,
                         help='Primer día del mes del documento (mes de la primera fecha de pago de sus recibos).')
    payslip_ids = fields.One2many('hr.payslip', 'l10n_co_ne_documento_id', string='Recibos incluidos')

    etapa = fields.Selection([('draft', 'Borrador'), ('ready', 'Listo')], string='Etapa', default='draft',
                             required=True, copy=False,
                             help='Preparación previa al envío: Borrador (composición editable) y Listo (validado).')
    incierto = fields.Boolean(string='Envío incierto', copy=False,
                              help='No hubo acuse ni veredicto pasado el tiempo configurado; requiere conciliación y '
                                   'sale del cron de reconsulta.')
    eliminado = fields.Boolean(string='Eliminado por nota de ajuste', copy=False)
    eliminado_por_id = fields.Many2one('l10n.co.ne.documento', string='Eliminado por', copy=False,
                                       ondelete='set null', check_company=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('ready', 'Listo'),
        ('invoice_sending_failed', 'Envío fallido'),
        ('invoice_pending', 'Pendiente'),
        ('invoice_rejected', 'Rechazado'),
        ('invoice_accepted', 'Aceptado'),
        ('uncertain', 'Envío incierto - requiere conciliación'),
        ('eliminated', 'Eliminado por nota de ajuste'),
    ], string='Estado DIAN', compute='_compute_state', store=True, copy=False, index=True)
    intento_ids = fields.One2many('l10n.co.ne.documento.intento', 'documento_id', string='Intentos')
    message = fields.Html(string='Motivo', compute='_compute_message', sanitize=False)

    cune = fields.Char(string='CUNE', copy=False, index=True, readonly=True)
    consecutive = fields.Char(string='Consecutivo NE', copy=False, readonly=True)
    xml_attachment_id = fields.Many2one('ir.attachment', string='XML firmado', copy=False, readonly=True,
                                        ondelete='set null')
    zip_key = fields.Char(string='ZipKey DIAN', copy=False, readonly=True)
    hab_set_id = fields.Char(string='Set de habilitación DIAN', copy=False, index=True)
    exchange_ids = fields.Many2many('l10n.co.ne.exchange', 'l10n_co_ne_exchange_documento_rel',
                                    'documento_id', 'exchange_id', string='Historial de intercambios DIAN',
                                    readonly=True, copy=False)

    is_adjustment = fields.Boolean(string='Es nota de ajuste', copy=False)
    adjustment_type = fields.Selection([('1', 'Reemplazar'), ('2', 'Eliminar')], string='Tipo de nota de ajuste',
                                       copy=False)
    adjustment_ref_cune = fields.Char(string='CUNE del documento original', copy=False)
    parent_id = fields.Many2one('l10n.co.ne.documento', string='Documento original', copy=False,
                                ondelete='restrict', check_company=True)
    error_conocido_el = fields.Date(string='Error conocido el', copy=False,
                                    help='Fecha en que se conoció el error (nota de ajuste): fija el plazo de 10 días hábiles.')
    legacy = fields.Boolean(string='Migrado (legacy)', copy=False, readonly=True,
                            help='Documento migrado 1:1 desde un recibo ya transmitido: conserva su CUNE y número; '
                                 'queda fuera de la unicidad por mes y del plazo.')
    fecha_limite = fields.Date(string='Fecha límite', copy=False,
                               help='10.º día hábil del mes siguiente; lo calcula la etapa 2 (festivos y días hábiles configurables).')

    # Cola de envío y alertas (patrón de account.move.send; los llena el asistente y el cron, etapas 2 y 4).
    sending_data = fields.Json(string='Datos de envío en cola', copy=False, readonly=True)
    is_being_sent = fields.Boolean(string='En cola', compute='_compute_is_being_sent')
    alertas = fields.Json(string='Alertas', copy=False,
                          help='Lista de {"key", "level" (danger/warning), "message"} calculada al validar el documento.')
    alertas_texto = fields.Html(string='Alertas', compute='_compute_alertas_texto', sanitize=False)

    _sql_constraints = [
        ('cune_unique', 'UNIQUE(cune)', 'El CUNE debe ser único: ya existe un documento con este CUNE.'),
        ('consecutive_company_unique', 'UNIQUE(consecutive, company_id)',
         'El consecutivo de nómina electrónica debe ser único por empresa.'),
    ]

    def init(self):
        """Un original activo por (compañía, empleado, mes): índice parcial (el ORM no lo expresa)."""
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS l10n_co_ne_documento_mes_unico
            ON l10n_co_ne_documento (company_id, employee_id, period)
            WHERE is_adjustment IS NOT TRUE AND legacy IS NOT TRUE AND eliminado IS NOT TRUE
        """)

    # ──────────────────────────────────────────────────────────────────
    # Calculados
    # ──────────────────────────────────────────────────────────────────
    @api.depends('employee_id.name', 'period', 'is_adjustment')
    def _compute_name(self):
        for doc in self:
            mes = doc.period.strftime('%Y-%m') if doc.period else ''
            base = '%s %s' % (doc.employee_id.name or '', mes)
            doc.name = ('%s %s' % (_('Ajuste'), base) if doc.is_adjustment else base).strip()

    def _ultimo_intento(self):
        """Último intento (como el nativo: ``.sorted()[:1]``); el orden es por fecha y luego id."""
        self.ensure_one()
        return self.intento_ids.sorted(lambda i: (i.datetime or _dt.min, i.id), reverse=True)[:1]

    @api.depends('intento_ids.state', 'intento_ids.datetime', 'etapa', 'eliminado', 'incierto')
    def _compute_state(self):
        for doc in self:
            if doc.eliminado:
                doc.state = 'eliminated'
            elif doc.incierto:
                doc.state = 'uncertain'
            else:
                ultimo = doc._ultimo_intento()
                doc.state = ultimo.state if ultimo else doc.etapa

    @api.depends('intento_ids.message', 'intento_ids.datetime')
    def _compute_message(self):
        for doc in self:
            doc.message = doc._ultimo_intento().message or False

    @api.depends('sending_data')
    def _compute_is_being_sent(self):
        for doc in self:
            doc.is_being_sent = bool(doc.sending_data)

    @api.depends('alertas')
    def _compute_alertas_texto(self):
        etiquetas = {'danger': _('Bloqueo'), 'warning': _('Advertencia')}
        for doc in self:
            items = doc.alertas or []
            doc.alertas_texto = Markup('<ul>%s</ul>') % Markup('').join(
                Markup('<li>%s: %s</li>') % (etiquetas.get(a.get('level'), a.get('level') or ''),
                                              a.get('message') or '') for a in items) if items else False

    # ──────────────────────────────────────────────────────────────────
    # Restricciones
    # ──────────────────────────────────────────────────────────────────
    @api.constrains('company_id')
    def _check_company_colombia(self):
        """Inerte en compañías no colombianas (doc 51): no se crean documentos para ellas."""
        for doc in self:
            if not doc.company_id._ne_es_colombia():
                raise ValidationError(_(
                    'La compañía "%(compania)s" no es colombiana: el documento mensual de nómina electrónica '
                    'solo existe para compañías de Colombia.', compania=doc.company_id.name))

    @api.constrains('period')
    def _check_period(self):
        for doc in self:
            if doc.period and doc.period.day != 1:
                raise ValidationError(_(
                    'El mes del documento debe ser el primer día del mes; se recibió %(fecha)s.', fecha=doc.period))

    @api.constrains('company_id', 'employee_id', 'period', 'is_adjustment', 'legacy', 'eliminado')
    def _check_original_unico(self):
        for doc in self.filtered(lambda d: not d.is_adjustment and not d.legacy and not d.eliminado):
            otro = self.search([
                ('id', '!=', doc.id), ('company_id', '=', doc.company_id.id), ('employee_id', '=', doc.employee_id.id),
                ('period', '=', doc.period), ('is_adjustment', '=', False), ('legacy', '=', False),
                ('eliminado', '=', False)], limit=1)
            if otro:
                raise ValidationError(_(
                    'Ya existe un documento mensual activo de %(empleado)s para %(mes)s (%(otro)s). Solo puede haber '
                    'uno por empleado y mes; para corregirlo cree una nota de ajuste.',
                    empleado=doc.employee_id.display_name, mes=doc.period.strftime('%Y-%m'), otro=otro.display_name))

    @api.constrains('is_adjustment', 'adjustment_ref_cune')
    def _check_adjustment_ref_cune(self):
        for doc in self:
            if doc.is_adjustment and not doc.adjustment_ref_cune:
                raise ValidationError(_(
                    'Para una nota de ajuste debe indicar el CUNE del documento original (%(doc)s).', doc=doc.display_name))

    @api.constrains('payslip_ids', 'company_id', 'employee_id')
    def _check_recibos(self):
        """Coherencia de sus recibos (la misma regla se valida del lado del recibo al enlazarlo)."""
        self.payslip_ids._check_documento_coherente()

    def unlink(self):
        for doc in self:
            if doc.legacy or doc.cune or doc.consecutive or doc.intento_ids:
                raise UserError(_(
                    'El documento "%(doc)s" ya tiene historia ante la DIAN (CUNE, consecutivo o intentos) y no se '
                    'puede borrar. Si hay un error, cree una nota de ajuste.', doc=doc.display_name))
        return super().unlink()

    # ──────────────────────────────────────────────────────────────────
    # Migración: lo ya transmitido por recibo pasa a documentos legacy 1:1
    # ──────────────────────────────────────────────────────────────────
    @api.model
    def _ne_migrar_legacy(self):
        """Crea un documento ``legacy`` por cada recibo colombiano con historia DIAN (estado distinto de borrador, o
        CUNE, consecutivo o intercambios). NO quita nada del recibo. Idempotente: el recibo que ya apunta a un documento
        no se vuelve a migrar. Funciona con 0 filas. Devuelve los documentos creados."""
        Payslip = self.env['hr.payslip'].sudo().with_context(active_test=False)
        recibos = Payslip.search([
            ('l10n_co_ne_documento_id', '=', False),
            '|', '|', '|', ('l10n_co_ne_state', '!=', 'draft'), ('l10n_co_ne_cune', '!=', False),
            ('l10n_co_ne_consecutive', '!=', False), ('l10n_co_ne_exchange_ids', '!=', False),
        ], order='id')
        recibos = recibos.filtered(lambda s: s.company_id._ne_es_colombia())
        Documento = self.sudo().with_context(mail_notrack=True, mail_create_nolog=True)
        creados = Documento
        por_cune = {}
        for slip in recibos:
            doc = Documento.create(self._ne_valores_legacy(slip))
            creados |= doc
            if doc.cune:
                por_cune[doc.cune] = doc
            self._ne_crear_intento_legacy(doc, slip)
            slip._write({'l10n_co_ne_documento_id': doc.id})
        recibos.modified(['l10n_co_ne_documento_id'])
        # Las notas de ajuste migradas apuntan a su original por CUNE (el original puede ser de un lote anterior).
        for doc in creados.filtered(lambda d: d.is_adjustment and d.adjustment_ref_cune):
            original = por_cune.get(doc.adjustment_ref_cune) or Documento.search(
                [('cune', '=', doc.adjustment_ref_cune), ('id', '!=', doc.id)], limit=1)
            if original:
                doc.parent_id = original
                if doc.adjustment_type == '2' and doc.state == 'invoice_accepted':
                    original.eliminado_por_id = doc
        _logger.info('Documentos legacy creados desde recibos ya transmitidos: %s', len(creados))
        return creados

    @api.model
    def _ne_valores_legacy(self, slip):
        etapa, _estado_intento = _MAPA_ESTADO_LEGACY[slip.l10n_co_ne_state or 'draft']
        return {
            'company_id': slip.company_id.id,
            'employee_id': slip.employee_id.id,
            'contract_id': slip.contract_id.id or False,
            'period': slip.date_to.replace(day=1),
            'legacy': True,
            'etapa': etapa,
            'incierto': slip.l10n_co_ne_state == 'uncertain',
            'eliminado': slip.l10n_co_ne_state == 'eliminated',
            'cune': slip.l10n_co_ne_cune or False,
            'consecutive': slip.l10n_co_ne_consecutive or False,
            'xml_attachment_id': slip.l10n_co_ne_xml_attachment_id.id or False,
            'zip_key': slip.l10n_co_ne_zip_key or False,
            'hab_set_id': slip.l10n_co_ne_hab_set_id or False,
            'is_adjustment': slip.l10n_co_ne_is_adjustment,
            'adjustment_type': slip.l10n_co_ne_adjustment_type if slip.l10n_co_ne_is_adjustment else False,
            'adjustment_ref_cune': slip.l10n_co_ne_adjustment_ref_cune or False,
            'exchange_ids': [(6, 0, slip.l10n_co_ne_exchange_ids.ids)],
        }

    @api.model
    def _ne_crear_intento_legacy(self, doc, slip):
        """Un intento por documento legacy transmitido, con el motivo reparseado de la respuesta guardada."""
        _etapa, estado = _MAPA_ESTADO_LEGACY[slip.l10n_co_ne_state or 'draft']
        if not estado:
            return self.env['l10n.co.ne.documento.intento']
        envios = slip.l10n_co_ne_exchange_ids.filtered(lambda e: e.operation in _OPERACIONES_ENVIO).sorted('id')
        intercambio = envios[-1:]
        manifiesto = self.env['l10n.co.ne.exchange.document'].sudo().search(
            [('payslip_id', '=', slip.id)], order='id desc', limit=1)
        message_json = False
        if slip.l10n_co_ne_dian_response:
            try:
                message_json = dian_message.build_message_json(_parse_response(slip.l10n_co_ne_dian_response))
            except Exception:  # la respuesta guardada es texto libre: nunca bloquea la migración
                message_json = {'transport': 'PARSE_ERROR', 'errors': [], 'fault': [], 'is_valid': False,
                                'status_code': 'PARSE_ERROR', 'status': '', 'detail': ''}
        habilitacion = bool(slip.l10n_co_ne_hab_set_id)
        return self.env['l10n.co.ne.documento.intento'].sudo().create({
            'documento_id': doc.id,
            'datetime': intercambio.create_date or slip.write_date,
            'state': estado,
            'identifier': slip.l10n_co_ne_cune or False,
            'zip_key': slip.l10n_co_ne_zip_key or False,
            'numero': slip.l10n_co_ne_consecutive or False,
            'file_name': manifiesto.file_name or False,
            'sha256': manifiesto.sha256 or False,
            'attachment_id': slip.l10n_co_ne_xml_attachment_id.id or False,
            'message_json': message_json,
            'exchange_id': intercambio.id or False,
            'test_environment': habilitacion or slip.company_id.l10n_co_ne_environment == '2',
            'certification_process': habilitacion,
        })
