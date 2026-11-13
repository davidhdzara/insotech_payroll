# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""Documento mensual de nómina electrónica por empleado (doc 53 §3, §16.2, §18.6, §20).

Etapa 1b: SOLO el modelo, la relación con el recibo, las reglas multiempresa y la migración de lo ya
transmitido (``legacy``, 1:1). Todavía no genera XML ni envía (etapas 3 y 4): no hereda el mixin del ciclo
DIAN; sus campos de estado son ``etapa`` + ``state`` calculado del último intento (patrón de ``account.move`` +
``l10n_co_dian.document``)."""

import base64
import hashlib
import logging
from datetime import datetime as _dt, time, timedelta

import pytz

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services import (
    cune as cune_service, dian_message, dian_respuesta, dian_utils, documento_merge, ne_xml_utils, nomina_xml_builder,
    soap_client, xml_signer)
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

# Veredicto neutral del servicio (dian_respuesta) -> estado del intento del documento (doc 53 §23.13). Un fallo de
# transporte NUNCA es rechazo.
_ESTADO_INTENTO_POR_VEREDICTO = {
    dian_respuesta.ACEPTADO: 'invoice_accepted',
    dian_respuesta.RECHAZADO: 'invoice_rejected',
    dian_respuesta.PENDIENTE: 'invoice_pending',
    dian_respuesta.ERROR_TRANSPORTE: 'invoice_sending_failed',
}


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
    fecha_limite = fields.Date(
        string='Fecha límite', compute='_compute_fecha_limite', store=True, readonly=True,
        help='10.º día hábil del mes siguiente al del documento (Res. DIAN 000013/2021 art. 8). Día hábil = día con '
             'jornada en el calendario del contrato (o de la compañía) y no festivo (D10). Solo alerta, no bloquea. '
             'No aplica a documentos migrados ni a notas de ajuste.')

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

    @api.depends('intento_ids.state', 'intento_ids.datetime', 'intento_ids.identifier', 'cune', 'etapa',
                 'eliminado', 'incierto')
    def _compute_state(self):
        for doc in self:
            if doc.eliminado:
                doc.state = 'eliminated'
            elif doc.incierto:
                doc.state = 'uncertain'
            else:
                ultimo = doc._ultimo_intento()
                if ultimo.state == 'invoice_rejected' and ultimo.identifier != doc.cune:
                    # El rechazo fue de un XML ANTERIOR: el documento se regeneró con consecutivo y CUNE nuevos
                    # (doc 53 §23.15, D-a) y el XML vigente todavía no se envió: vuelve a 'Listo'. El intento
                    # rechazado queda en el historial como evidencia.
                    doc.state = doc.etapa
                else:
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
    # Plazo de transmisión (doc 53 §4.4, D10)
    # ──────────────────────────────────────────────────────────────────
    DIAS_HABILES_PLAZO = 10   # Res. DIAN 000013/2021 art. 8: 10 primeros días hábiles del mes siguiente

    def _ne_calendario(self):
        """Calendario laboral del documento: el del contrato; si no, el de la compañía."""
        self.ensure_one()
        return self.contract_id.resource_calendar_id or self.company_id.resource_calendar_id

    def _ne_dias_habiles(self, desde, hasta):
        """Fechas hábiles de [desde, hasta]: con jornada en el calendario y sin festivo (festivos globales de la
        compañía del documento). El sábado cuenta si la jornada lo incluye (D10)."""
        self.ensure_one()
        calendario = self._ne_calendario()
        if not calendario:
            return set()
        zona = pytz.timezone(calendario.tz or self.env.user.tz or 'UTC')
        inicio = zona.localize(_dt.combine(desde, time.min))
        fin = zona.localize(_dt.combine(hasta, time.max))
        # Sin ``resources``, el nativo NO filtra los festivos por compañía (su filtro solo corre cuando
        # hay un recurso): los festivos globales de otra compañía restarían días hábiles de ESTE plazo.
        # Se limita explícitamente a los de la compañía del documento (o sin compañía).
        dominio_festivos = [('time_type', '=', 'leave'), ('company_id', 'in', [self.company_id.id, False])]
        intervalos = calendario.with_company(self.company_id)._work_intervals_batch(
            inicio, fin, domain=dominio_festivos, compute_leaves=True)[False]
        return {a.astimezone(zona).date() for a, _b, _rec in intervalos}

    def _ne_calcular_fecha_limite(self):
        """10.º día hábil del mes siguiente, o False si no se puede calcular (sin calendario o sin 10 días hábiles
        en ~45 días: falta cargar jornada o hay festivos de más)."""
        self.ensure_one()
        primero = (self.period.replace(day=28) + timedelta(days=4)).replace(day=1)
        dias = int(self.env['hr.rule.parameter']._get_parameter_from_code(
            'l10n_co_ne_dias_plazo_transmision', primero))   # Res. DIAN 000013/2021 art. 8 (versionado)
        habiles = sorted(self._ne_dias_habiles(primero, primero + timedelta(days=44)))
        return habiles[dias - 1] if len(habiles) >= dias else False

    @api.depends('period', 'contract_id.resource_calendar_id', 'company_id.resource_calendar_id',
                 'legacy', 'is_adjustment')
    def _compute_fecha_limite(self):
        for doc in self:
            doc.fecha_limite = (doc._ne_calcular_fecha_limite()
                                if doc.period and not doc.legacy and not doc.is_adjustment else False)

    # ──────────────────────────────────────────────────────────────────
    # Preparar: agrupar recibos, crear/reutilizar el documento y validarlo (doc 53 §17.2, §20.2, §22.2)
    # ──────────────────────────────────────────────────────────────────
    @api.model
    def _ne_recibos_del_mes(self, company, employee, period):
        """Recibos pagados (hechos o pagados, no notas de crédito) del empleado cuya PRIMERA fecha de pago cae en el
        mes ``period``. Con fuente 'recibo' filtra en SQL por fecha; con 'contabilidad' calcula por recibo."""
        fin = (period.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        dominio = [('company_id', '=', company.id), ('employee_id', '=', employee.id),
                   ('state', 'in', ('done', 'paid')), ('credit_note', '=', False)]
        if company.l10n_co_ne_fuente_fecha_pago == 'recibo':
            return self.env['hr.payslip'].search(dominio + [('paid_date', '>=', period), ('paid_date', '<=', fin)])
        candidatos = self.env['hr.payslip'].search(dominio)
        return candidatos.filtered(lambda s: s._ne_fechas_pagos_contables()
                                   and period <= s._ne_fechas_pagos_contables()[0] <= fin)

    @api.model
    def _ne_preparar(self, recibos):
        """Agrupa ``recibos`` por (compañía, empleado, mes de la primera fecha de pago), crea o reutiliza el documento
        de cada grupo, enlaza TODOS los recibos pagados del mes (no solo los seleccionados) y lo valida.

        No gasta consecutivo ni envía. Devuelve ``{'documentos': recordset, 'sin_fecha': [(recibo, motivo)]}``: los
        recibos sin fecha de pago (o no hechos) no pertenecen a ningún mes y se informan aparte."""
        resultado = {'documentos': self.browse(), 'sin_fecha': []}
        previos = recibos.l10n_co_ne_documento_id   # antes de relinkear: de dónde vienen los recibos
        grupos = {}
        for slip in recibos:
            if not slip.company_id._ne_es_colombia():
                resultado['sin_fecha'].append((slip, _('La compañía no es colombiana.')))
                continue
            if slip.state not in ('done', 'paid'):
                resultado['sin_fecha'].append((slip, _('El recibo no está en estado "Hecho" ni "Pagado".')))
                continue
            try:
                primera = slip._ne_fecha_pago()
            except UserError as error:
                resultado['sin_fecha'].append((slip, str(error)))
                continue
            clave = (slip.company_id, slip.employee_id, primera.replace(day=1))
            grupos.setdefault(clave, self.env['hr.payslip'])
            grupos[clave] |= slip
        for (company, employee, period) in grupos:
            doc = self._ne_documento_del_grupo(company, employee, period)
            if doc.state in ('draft', 'ready', 'invoice_sending_failed') and not doc.is_being_sent:
                doc._ne_componer(self._ne_recibos_del_mes(company, employee, period))
            doc._ne_validar()
            resultado['documentos'] |= doc
        # Un recibo que cambió de mes (nueva fecha de pago) sale del documento donde estaba: ese documento se
        # recompone y revalida; si queda vacío y sin historia, se elimina.
        for previo in previos - resultado['documentos']:
            if previo.legacy or previo.is_adjustment or previo.state not in ('draft', 'ready'):
                continue
            previo._ne_componer(self._ne_recibos_del_mes(previo.company_id, previo.employee_id, previo.period))
            if previo.payslip_ids:
                previo._ne_validar()
            else:
                previo.unlink()
        return resultado

    @api.model
    def _ne_documento_del_grupo(self, company, employee, period):
        doc = self.search([
            ('company_id', '=', company.id), ('employee_id', '=', employee.id), ('period', '=', period),
            ('is_adjustment', '=', False), ('legacy', '=', False), ('eliminado', '=', False)], limit=1)
        return doc or self.create({'company_id': company.id, 'employee_id': employee.id, 'period': period})

    def _ne_componer(self, recibos):
        """Deja exactamente ``recibos`` en el documento (los que ya no corresponden se sueltan) y fija el contrato.
        Solo se compone un documento sin transmitir (draft/ready/envío fallido): lo llama ``_ne_preparar``."""
        self.ensure_one()
        sueltos = self.payslip_ids - recibos
        if sueltos:
            sueltos.write({'l10n_co_ne_documento_id': False})
        nuevos = recibos - self.payslip_ids
        if nuevos:
            nuevos.write({'l10n_co_ne_documento_id': self.id})
        contratos = recibos.sorted('date_to').contract_id
        self.contract_id = contratos[-1:] or False
        if self.etapa == 'ready':
            self.etapa = 'draft'   # cambió la composición: se revalida

    def _ne_validar(self):
        """Calcula las alertas (persistidas en ``alertas``) y pasa a 'ready' si no hay bloqueos. Alertas de esta
        etapa; las del XML (conciliación de totales, Salud/FondoPension) llegan con la etapa 3."""
        self.ensure_one()
        alertas = []

        def alerta(key, level, message, **extra):
            alertas.append(dict({'key': key, 'level': level, 'message': message}, **extra))

        if self.state in ('invoice_pending', 'uncertain'):
            alerta('en_proceso', 'danger', _('El documento espera el veredicto de la DIAN: consulte su estado primero.'))
        elif self.state == 'invoice_accepted':
            alerta('aceptado', 'danger', _(
                'El documento ya fue aceptado por la DIAN: un cambio se corrige con una nota de ajuste.'))
        if not self.payslip_ids:
            alerta('sin_recibos', 'danger', _('El documento no tiene recibos pagados en el mes.'))
        # Datos incompletos: los mismos prerrequisitos del ciclo por recibo, sin sus chequeos de estado.
        try:
            self.company_id._l10n_co_ne_validar_config()
        except UserError as error:
            alerta('compania', 'danger', str(error))
        for slip in self.payslip_ids:
            try:
                self._ne_validar_datos_recibo(slip)
            except UserError as error:
                alerta('datos_%s' % slip.id, 'danger', str(error))
        # Recibos del mes que NO entraron (sin fecha de pago, en borrador...): ¿falta una quincena?
        fin = (self.period.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        faltan = self.env['hr.payslip'].search([
            ('company_id', '=', self.company_id.id), ('employee_id', '=', self.employee_id.id),
            ('credit_note', '=', False), ('state', '!=', 'cancel'),
            ('date_to', '>=', self.period), ('date_to', '<=', fin), ('id', 'not in', self.payslip_ids.ids)])
        if faltan:
            alerta('faltan_recibos', 'warning', _(
                'Hay recibos del mes que no están en el documento (sin pagar, pagados en otro mes o sin fecha de pago): %(recibos)s.',
                recibos=', '.join(faltan.mapped('display_name'))), confirmable=True)
        # Mes en curso sin liquidación final pagada (D14: confirmación explícita del usuario, no bloqueo).
        hoy = fields.Date.context_today(self)
        liquidacion = self.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_liquidacion',
                                   raise_if_not_found=False)
        if hoy <= fin and not self.payslip_ids.filtered(lambda s: s.struct_id == liquidacion):
            alerta('mes_en_curso', 'warning', _(
                'El mes del documento no ha terminado y el empleado no tiene liquidación final pagada en él.'),
                confirmable=True)
        # Plazo de transmisión (D10): solo alerta, no bloquea.
        if self.fecha_limite and hoy > self.fecha_limite and self.state in (
                'draft', 'ready', 'invoice_sending_failed'):
            alerta('plazo_vencido', 'warning', _(
                'El plazo de transmisión venció el %(fecha)s (10 días hábiles del mes siguiente).',
                fecha=self.fecha_limite))
        elif not self.fecha_limite and not self.legacy and not self.is_adjustment:
            alerta('plazo_sin_calcular', 'warning', _(
                'No se pudo calcular el plazo de transmisión: revise el calendario laboral y los festivos.'))
        alertas += self._ne_validar_xml()
        self.alertas = alertas
        bloqueos = [a for a in alertas if a['level'] == 'danger']
        if self.state in ('draft', 'ready'):
            self.etapa = 'draft' if bloqueos else 'ready'

    def _ne_validar_datos_recibo(self, slip):
        """Datos mínimos del empleado/contrato para generar el documento (sin los chequeos de estado del recibo)."""
        self.ensure_one()
        if not slip.employee_id.identification_id:
            raise UserError(_('El empleado %s no tiene número de identificación configurado.',
                              slip.employee_id.name))
        if not slip.contract_id:
            raise UserError(_('El recibo %s no tiene contrato asociado.', slip.number or slip.name))
        slip._ne_validar_cuenta_transferencia()
        slip.employee_id._l10n_co_nombre_dian()

    # ──────────────────────────────────────────────────────────────────
    # XML mensual: fusión de los recibos (doc 53 §5.3, §19; etapa 3)
    # ──────────────────────────────────────────────────────────────────
    def _ne_periodo(self, contrato):
        """Bloque ``Periodo`` del documento mensual (D3): liquidación desde max(1.º del mes, ingreso) hasta el retiro
        si el contrato terminó ese mes, o el fin de mes si sigue vigente. TiempoLaborado 360/30 con el día de
        ingreso incluido (D19, Anexo §8.3.1)."""
        self.ensure_one()
        primero = self.period
        ultimo = (primero.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        inicio = max(primero, contrato.date_start) if contrato.date_start else primero
        fin = min(ultimo, contrato.date_end) if contrato.date_end else ultimo
        ahora = _dt.now(pytz.timezone('America/Bogota'))
        return {
            'FechaIngreso': str(contrato.date_start) if contrato.date_start else '',
            'FechaRetiro': str(contrato.date_end) if contrato.date_end else '',
            'FechaLiquidacionInicio': str(inicio),
            'FechaLiquidacionFin': str(fin),
            'TiempoLaborado': str(dian_utils.compute_worked_time_360(contrato.date_start, fin, inclusive=True)),
            'FechaGen': ahora.strftime('%Y-%m-%d'),
        }

    def _collect_documento_data(self, consecutivo=None):
        """Diccionario del documento mensual para ``nomina_xml_builder``: los datos de cada recibo (código existente,
        sin reescribir constructores) fusionados por ``documento_merge``. ``consecutivo`` provisional (con prefijo)
        solo para armar la numeración cuando el documento aún no tiene el suyo; no gasta ninguno."""
        self.ensure_one()
        if self.is_adjustment:
            raise UserError(_('La nota de ajuste del documento mensual se genera en la etapa de ajustes.'))
        recibos = self.payslip_ids.sorted('date_to')
        if not recibos:
            raise UserError(_('El documento "%s" no tiene recibos.', self.display_name))
        contrato = self.contract_id or recibos[-1].contract_id
        fechas = sorted({str(f) for slip in recibos for f in slip._ne_fechas_pago()})
        datos_recibos = [slip._collect_payslip_data() for slip in recibos]
        try:
            datos = documento_merge.fusionar_documento(
                datos_recibos, fechas, self._ne_periodo(contrato), periodo_nomina='5')
        except documento_merge.ErrorFusion as error:
            raise UserError(_('No se pueden fusionar los recibos del mes: %s', str(error)))
        # §5.4: el CUNE depende de ValDev/ValDed/ValTol; un error de suma es un rechazo de la DIAN.
        descuadres = documento_merge.conciliar_fusion(datos_recibos, datos)
        if descuadres:
            raise UserError(_('La fusión de los recibos no cuadra: %s', ' '.join(descuadres)))
        company = self.company_id
        numero = self.consecutive or consecutivo or ''
        prefijo = company.l10n_co_ne_payroll_prefix or ''
        modo = company.l10n_co_ne_operation_mode_ids
        datos['numero_secuencia'] = dict(
            datos.get('numero_secuencia', {}), Prefijo=prefijo, Numero=numero,
            Consecutivo=numero[len(prefijo):] if prefijo and numero.startswith(prefijo) else numero)
        datos['proveedor_xml'] = dict(
            datos.get('proveedor_xml', {}),
            SoftwareSC=dian_utils.compute_software_security_code(modo.software_id, modo.software_pin, numero)
            if numero else '')
        return datos

    def _ne_xml_sin_firmar(self, consecutivo=None):
        """XML mensual sin CUNE ni firma (para validar o previsualizar; no gasta consecutivo)."""
        self.ensure_one()
        return nomina_xml_builder.build_nomina_individual_v2(self._collect_documento_data(consecutivo))

    def _ne_validar_xml(self):
        """Alertas que dependen del XML (se llaman desde ``_ne_validar``): la fusión debe ser posible y, D4, un
        documento sin Salud ni FondoPension solo avisa (la prima va siempre con la quincena; sin bloqueo)."""
        self.ensure_one()
        alertas = []
        if not self.payslip_ids or self.is_adjustment:
            return alertas
        try:
            datos = self._collect_documento_data(consecutivo='PRE')
        except UserError as error:
            return [{'key': 'xml', 'level': 'danger', 'message': str(error)}]
        dif_dev, dif_ded = documento_merge.diferencias_nodos(datos)
        if dif_dev or dif_ded:
            alertas.append({'key': 'totales_nodos', 'level': 'warning', 'message': _(
                'Los totales no son la suma de los nodos del XML (devengados %(dev)s, deducciones %(ded)s de '
                'diferencia): revise los conceptos antes de enviar.', dev=dif_dev, ded=dif_ded)})
        deducciones = datos.get('deducciones', {})
        if 'Salud' not in deducciones or 'FondoPension' not in deducciones:
            alertas.append({'key': 'sin_seguridad_social', 'level': 'warning', 'message': _(
                'El documento queda sin Salud o sin FondoPension (por ejemplo, un mes solo con prima): revíselo '
                'antes de enviarlo.')})
        return alertas

    # ──────────────────────────────────────────────────────────────────
    # Generar y firmar (etapa 3b): consecutivo, CUNE, firma y adjunto
    # ──────────────────────────────────────────────────────────────────
    def _ne_siguiente_consecutivo(self):
        """Siguiente consecutivo oficial de la compañía (misma secuencia no_gap del ciclo por recibo). Sin secuencia
        configurada es un error claro: no se inventa un número."""
        self.ensure_one()
        secuencia = self.company_id.l10n_co_ne_sequence_id
        if not secuencia:
            raise UserError(_(
                'La compañía "%(compania)s" no tiene secuencia de nómina electrónica. Configúrela en Ajustes > '
                'Nómina antes de generar el documento.', compania=self.company_id.name))
        return secuencia.next_by_id()

    def action_generar_xml(self):
        """Genera el XML mensual firmado: revalida, toma consecutivo (después de una corrida en seco), arma el
        XML fusionado, calcula el CUNE (depende de los totales fusionados), lo inserta, firma con XAdES-BES y
        guarda el adjunto. El documento queda 'ready' con su consecutivo, CUNE y XML (sin estado 'generado',
        doc 53 §18.6); un fallo después de tomar el número lo devuelve con el rollback (secuencia no_gap)."""
        self.ensure_one()
        # Se genera si nunca se envió, o si TODOS los envíos anteriores fueron rechazados (D-a: se corrige y se
        # regenera en el MISMO documento, con consecutivo y CUNE nuevos). Aceptado, pendiente, incierto, eliminado
        # o con un fallo de envío (se reintenta con el mismo XML) no se regeneran.
        solo_rechazos = all(i.state == 'invoice_rejected' for i in self.intento_ids)
        if not (self.state in ('draft', 'ready', 'invoice_rejected') and solo_rechazos):
            raise UserError(_(
                'El XML solo se genera para un documento en estado "Borrador", "Listo" o "Rechazado" que no se '
                'haya enviado con éxito (hoy: %s).', dict(self._fields['state'].selection).get(self.state)))
        self._ne_validar()
        bloqueos = [a['message'] for a in (self.alertas or []) if a['level'] == 'danger']
        if bloqueos:
            raise UserError(_('El documento tiene bloqueos: %s', ' '.join(bloqueos)))
        company = self.company_id
        prefijo = company.l10n_co_ne_payroll_prefix or 'NE'
        # Un consecutivo que ya viajó a la DIAN en un intento rechazado NO se reutiliza jamás: la DIAN devuelve el
        # veredicto viejo si se repite (doc 53 §23.15; memoria del equipo sobre consecutivos rechazados).
        consecutivo_usado = bool(self.consecutive) and self.consecutive in self.intento_ids.mapped('numero')
        if consecutivo_usado or not self.consecutive or not self.consecutive.startswith(prefijo):
            self._ne_xml_sin_firmar('%s1' % prefijo)   # corrida en seco: los errores de datos salen ANTES del número
            self.consecutive = self._ne_siguiente_consecutivo()
        datos = self._collect_documento_data()
        xml_bytes = nomina_xml_builder.build_nomina_individual_v2(datos)
        cune = self._ne_calcular_cune(datos)
        xml_bytes = ne_xml_utils.insertar_cune_y_qr(xml_bytes, cune, company._ne_dian_qr_host())
        llave, cert_pem, cert_der, cert_obj, cadena = xml_signer.load_from_certificate(company._get_ne_certificate())
        firmado = xml_signer.sign_xml(
            xml_bytes=xml_bytes, private_key=llave, cert_pem=cert_pem, cert_der=cert_der, cert_obj=cert_obj,
            cert_chain=cadena)
        nit = (company.vat or 'SIN_NIT').replace('-', '').strip()
        self.cune = cune
        self.xml_attachment_id = self.env['ir.attachment'].create({
            'name': 'ne_%s_%s.xml' % (nit, self.consecutive), 'type': 'binary', 'datas': base64.b64encode(firmado),
            'res_model': self._name, 'res_id': self.id, 'mimetype': 'application/xml'})
        _logger.info('XML mensual generado para %s (CUNE: %s)', self.display_name, cune)
        return True

    def _ne_calcular_cune(self, datos):
        """CUNE del documento mensual (Anexo §8.1.1.4): ValDev/ValDed/ValTol son los totales FUSIONADOS."""
        self.ensure_one()
        company = self.company_id
        info = datos['informacion_general']
        totales = datos['totales']
        cune, _raw = cune_service.compute_cune(
            num_ne=self.consecutive, fec_ne=info['FechaGen'], hor_ne=info['HoraGen'],
            val_dev=totales['DevengadosTotal'], val_ded=totales['DeduccionesTotal'],
            val_tol=totales['ComprobanteTotal'], nit_ne=dian_utils.clean_nit(company.vat),
            doc_trab=self.employee_id.identification_id or '', cl_ne='102',
            software_pin=company.l10n_co_ne_operation_mode_ids.software_pin or '',
            tipo_amb=company.l10n_co_ne_environment or '2')
        return cune

    # ──────────────────────────────────────────────────────────────────
    # Enviar a la DIAN (doc 53 §23.12 3.1, §23.15)
    # ──────────────────────────────────────────────────────────────────
    def _ne_precondiciones_envio(self):
        """UserError local, ANTES de tocar la DIAN: sin intento, sin consecutivo gastado."""
        self.ensure_one()
        nombre_estado = dict(self._fields['state'].selection).get(self.state)
        if self.legacy:
            raise UserError(_(
                'El documento "%s" es un documento migrado del ciclo por recibo: se reporta por recibo.',
                self.display_name))
        if self.is_adjustment:
            raise UserError(_('Las notas de ajuste se envían en la etapa de ajustes, no desde aquí.'))
        if self.eliminado:
            raise UserError(_('El documento "%s" ya fue eliminado por una nota de ajuste.', self.display_name))
        if self.incierto:
            raise UserError(_('El documento "%s" tiene un envío incierto: consulte su estado primero.',
                              self.display_name))
        if self.state in ('invoice_pending', 'invoice_accepted'):
            raise UserError(_('El documento "%(doc)s" ya fue enviado a la DIAN (estado: %(estado)s).',
                              doc=self.display_name, estado=nombre_estado))
        if self.state == 'invoice_rejected':
            raise UserError(_(
                'La DIAN rechazó el XML vigente del documento "%s". Corrija los datos y genere el XML otra vez '
                '(toma un consecutivo nuevo): el mismo XML no se reenvía.', self.display_name))
        if self.etapa != 'ready' or not (self.cune and self.consecutive and self.xml_attachment_id):
            raise UserError(_('Genere el XML del documento "%s" antes de enviarlo.', self.display_name))
        company = self.company_id
        if company.l10n_co_ne_environment == '2' or company.l10n_co_ne_certification_process:
            raise UserError(_(
                'La compañía "%s" está en habilitación (ambiente de pruebas o proceso de certificación): en '
                'habilitación el envío es por recibo hasta que el documento mensual pase a habilitación. El '
                'documento mensual solo se transmite en Producción.', company.name))
        company._l10n_co_ne_validar_config()

    def _ne_enviar_uno(self):
        """Envía UN documento a la DIAN y registra el resultado en un intento nuevo.

        No lanza por lo que responda o por lo que falle en la DIAN (queda en el intento: un fallo de conexión
        es "Envío fallido", reintentable con el MISMO consecutivo, CUNE y XML, nunca rechazo). Lanza UserError solo
        por precondiciones locales, antes de llamar. El ``state`` del documento se recalcula solo.

        Returns:
            ``l10n.co.ne.documento.intento`` creado.
        """
        self.ensure_one()
        self._ne_precondiciones_envio()
        company = self.company_id
        xml = base64.b64decode(self.xml_attachment_id.datas)
        nit = (company.vat or 'SIN_NIT').replace('-', '').strip()
        filename = 'ne_%s_%s.xml' % (nit, self.consecutive)
        exchange = self.env['l10n.co.ne.exchange']
        if company.l10n_co_ne_demo_mode:
            # Modo Demo: validación local, sin transmitir (mismo criterio que el ciclo por recibo).
            estado, zip_key = 'invoice_accepted', ''
            message_json = {
                'is_valid': True, 'status_code': '00', 'detail': '', 'errors': [], 'transport': False, 'fault': [],
                'status': _('Validado localmente en Modo Demo (sin transmisión real a la DIAN).')}
        else:
            llave, cert_pem, _der, _cert_obj, _cadena = xml_signer.load_from_certificate(company._get_ne_certificate())
            endpoint = company._ne_dian_endpoint()
            respuesta = soap_client.send_nomina_sync(
                xml_bytes=xml, filename=filename, private_key=llave, cert_pem=cert_pem, endpoint=endpoint,
                timeout=company._ne_config_int_param(
                    'l10n_co_nomina_electronica.soap_timeout_seconds', soap_client.SOAP_TIMEOUT))
            resultado = dian_respuesta.interpretar_respuesta(respuesta, contexto=dian_respuesta.CONTEXTO_ENVIO)
            estado = _ESTADO_INTENTO_POR_VEREDICTO[resultado.veredicto]
            zip_key = resultado.zip_key
            message_json = dian_message.build_message_json(respuesta)
            exchange = self.env['l10n.co.ne.exchange'].create_exchange(
                company, 'send_sync', endpoint, respuesta, self.payslip_ids, documento=self)
        intento = self.env['l10n.co.ne.documento.intento'].create({
            'documento_id': self.id, 'datetime': fields.Datetime.now(), 'state': estado,
            'identifier': self.cune, 'zip_key': zip_key or False, 'numero': self.consecutive,
            'file_name': filename, 'sha256': hashlib.sha256(xml).hexdigest(),
            'attachment_id': self.xml_attachment_id.id, 'message_json': message_json,
            'test_environment': company.l10n_co_ne_environment == '2',
            'certification_process': bool(company.l10n_co_ne_certification_process),
            'exchange_id': exchange.id or False})
        vals = {'sending_data': False}
        if zip_key:
            vals['zip_key'] = zip_key
        self.write(vals)
        self.message_post(
            body=_('Envío a la DIAN: %s.', dict(intento._fields['state'].selection).get(estado)),
            message_type='comment', subtype_xmlid='mail.mt_note')
        return intento

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

    @api.model_create_multi
    def create(self, vals_list):
        """Un original activo por (compañía, empleado, mes): se comprueba ANTES del INSERT para dar el mensaje claro
        (el índice parcial ``l10n_co_ne_documento_mes_unico`` queda como respaldo ante concurrencia)."""
        vistos = set()
        for vals in vals_list:
            if vals.get('is_adjustment') or vals.get('legacy') or vals.get('eliminado') or not vals.get('period'):
                continue
            company = vals.get('company_id') or self.env.company.id
            clave = (company, vals.get('employee_id'), fields.Date.to_date(vals['period']))
            otro = self.search([
                ('company_id', '=', company), ('employee_id', '=', clave[1]), ('period', '=', clave[2]),
                ('is_adjustment', '=', False), ('legacy', '=', False), ('eliminado', '=', False)], limit=1)
            if otro or clave in vistos:
                raise ValidationError(_(
                    'Ya existe un documento mensual activo para ese empleado y mes (%(otro)s). Solo puede haber uno por '
                    'empleado y mes; para corregirlo cree una nota de ajuste.', otro=otro.display_name or clave[2]))
            vistos.add(clave)
        return super().create(vals_list)

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
    def _ne_migrar_legacy(self, recibos=None):
        """Crea un documento ``legacy`` por cada recibo colombiano con historia DIAN (estado distinto de borrador, o
        CUNE, consecutivo o intercambios). NO quita nada del recibo. Idempotente: el recibo que ya apunta a un documento
        no se vuelve a migrar. Funciona con 0 filas. ``recibos`` limita la migración a esos recibos (las pruebas la
        usan para no depender de los datos de la base); sin él migra todos los pendientes. Devuelve los documentos
        creados."""
        Payslip = self.env['hr.payslip'].sudo().with_context(active_test=False)
        dominio = [
            ('l10n_co_ne_documento_id', '=', False),
            '|', '|', '|', ('l10n_co_ne_state', '!=', 'draft'), ('l10n_co_ne_cune', '!=', False),
            ('l10n_co_ne_consecutive', '!=', False), ('l10n_co_ne_exchange_ids', '!=', False)]
        if recibos is not None:
            dominio.append(('id', 'in', recibos.ids))
        recibos = Payslip.search(dominio, order='id')
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
        # _write no toca la caché: sin invalidar, el recibo seguiría mostrando el valor anterior en esta transacción.
        recibos.invalidate_recordset(['l10n_co_ne_documento_id'])
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
