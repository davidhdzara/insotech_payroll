# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.

"""
Asistente de Habilitación DIAN de Nómina Electrónica (doc 34).

Opción B confirmada en doc 34 §2: los 2 campos de meta
(``l10n_co_ne_num_nomina_certificar``/``l10n_co_ne_num_ajuste_certificar``,
en ``res.company``) no generan nada por sí solos -- este wizard produce
los documentos usando el pipeline real de ``hr.payslip`` (mismo motor de
reglas salariales y builders que produccion), no un generador sintético
aparte como hace ``insotech_dian_wizard`` (v19) con facturación.

Restricción real que obliga el diseño en 2 fases (doc 34 §5):
``action_create_adjustment()`` exige ``l10n_co_ne_state == 'accepted'`` en
el predecesor -- no se puede preparar una Nota de Ajuste antes de que la
DIAN acepte su Nómina Individual correspondiente. Por eso Fase 2 solo
avanza sobre lo que Fase 1 ya tenga aceptado.

Los botones "Enviar a la DIAN" consumen cupo real y limitado del
TestSetId de la compañía -- este wizard prepara y dejar listo cuanto se
pueda sin gastar cupo (crear, calcular, confirmar, generar XML firmado),
pero el disparo real es una acción explícita de quien lo presiona, no
algo que ocurra como efecto secundario de "preparar".

David pidió (2026-09-12) simplificar a 1 clic por fase, inspirado en el
botón único "Iniciar Habilitación DIAN" de ``insotech_dian_wizard`` (v19,
Facturación) -- pero NO se puede colapsar en un solo botón de punta a
punta las 2 fases: ``action_create_adjustment()`` exige que la DIAN ya
haya aceptado el predecesor, y esa aceptación es asíncrona (mismo patrón
de v19: ``SendTestSetAsync`` + sondeo de ``GetStatusZip``). Por eso hay
1 botón "Iniciar Habilitación" POR FASE (``action_iniciar_habilitacion_*``
abajo), cada uno encadenando internamente Preparar+Enviar+Consultar con
hasta 3 reintentos de sondeo (5s entre cada uno, mismo patrón de v19) --
los 6 botones de paso a paso (``action_prepare_*``/``action_send_*``/
``action_check_*_status``) se mantienen como mecanismo manual/diagnóstico,
ya verificado, sin cambios.
"""

import time

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_CONTRACT_OPEN_STATES = ('open', 'close')
_POLL_ATTEMPTS = 3
_POLL_DELAY_SECONDS = 5


class L10nCoNeCertificationWizard(models.TransientModel):
    _name = 'l10n.co.ne.certification.wizard'
    _description = 'Asistente de Habilitación DIAN - Nómina Electrónica'

    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Compañía',
        default=lambda self: self.env.company,
        required=True,
    )
    num_nomina_certificar = fields.Integer(
        related='company_id.l10n_co_ne_num_nomina_certificar',
        readonly=False,
        string='Meta Nómina Individual',
    )
    num_ajuste_certificar = fields.Integer(
        related='company_id.l10n_co_ne_num_ajuste_certificar',
        readonly=False,
        string='Meta Nota de Ajuste',
    )

    # ──────────────────────────────────────────────────────────────────
    # Fase 1 -- Nómina Individual
    # ──────────────────────────────────────────────────────────────────
    date_from = fields.Date(string='Periodo Desde')
    date_to = fields.Date(string='Periodo Hasta')
    employee_ids = fields.Many2many(
        comodel_name='hr.employee',
        relation='l10n_co_ne_cert_wizard_employee_rel',
        string='Empleados (Fase 1)',
        domain=[('active', '=', True)],
        help='Empleados reales de la compañía para los que se preparan '
             'los payslips de Nómina Individual de habilitación.',
    )
    payslip_individual_ids = fields.Many2many(
        comodel_name='hr.payslip',
        relation='l10n_co_ne_cert_wizard_individual_rel',
        string='Nóminas Individuales Preparadas',
        readonly=True,
    )
    show_advanced_steps = fields.Boolean(
        string='Mostrar pasos manuales (diagnóstico)',
        default=False,
        help='Revela los botones de Preparar/Enviar/Consultar por fase '
             'y paso separados, para reintentos puntuales o diagnóstico. '
             'El flujo normal es un solo clic en "Iniciar Proceso de '
             'Habilitación".',
    )
    count_accepted_individual = fields.Integer(
        compute='_compute_counts', string='Aceptadas (Individual)',
    )

    # ──────────────────────────────────────────────────────────────────
    # Fase 2 -- Nota de Ajuste
    # ──────────────────────────────────────────────────────────────────
    payslip_ajuste_ids = fields.Many2many(
        comodel_name='hr.payslip',
        relation='l10n_co_ne_cert_wizard_ajuste_rel',
        string='Notas de Ajuste Preparadas',
        readonly=True,
    )
    count_accepted_ajuste = fields.Integer(
        compute='_compute_counts', string='Aceptadas (Ajuste)',
    )

    @api.depends(
        'payslip_individual_ids.l10n_co_ne_state',
        'payslip_ajuste_ids.l10n_co_ne_state',
    )
    def _compute_counts(self):
        for wizard in self:
            wizard.count_accepted_individual = len(wizard.payslip_individual_ids.filtered(
                lambda p: p.l10n_co_ne_state == 'accepted'
            ))
            wizard.count_accepted_ajuste = len(wizard.payslip_ajuste_ids.filtered(
                lambda p: p.l10n_co_ne_state == 'accepted'
            ))

    # ──────────────────────────────────────────────────────────────────
    # Botón único, consciente del estado (2026-09-12, pedido de David:
    # "un solo botón en toda la pantalla", mismo nombre que usa
    # Facturación -- "Iniciar Proceso de Habilitación"). El sistema
    # decide internamente si toca Fase 1 o Fase 2 según lo que ya esté
    # Aceptado -- David no necesita entender el detalle de fases.
    # ──────────────────────────────────────────────────────────────────
    habilitacion_stage = fields.Selection(
        selection=[
            ('fase1', 'Fase 1 — Nómina Individual'),
            ('fase2', 'Fase 2 — Notas de Ajuste'),
            ('completo', 'Habilitación Completa'),
        ],
        compute='_compute_habilitacion_stage',
        string='Etapa de Habilitación',
    )

    @api.depends(
        'count_accepted_individual', 'count_accepted_ajuste',
        'num_nomina_certificar', 'num_ajuste_certificar',
    )
    def _compute_habilitacion_stage(self):
        for wizard in self:
            target_individual = wizard.num_nomina_certificar or 0
            target_ajuste = wizard.num_ajuste_certificar or 0
            fase1_completa = (
                bool(target_individual)
                and wizard.count_accepted_individual >= target_individual
            )
            fase2_completa = (
                bool(target_ajuste)
                and wizard.count_accepted_ajuste >= target_ajuste
            )
            if fase1_completa and fase2_completa:
                wizard.habilitacion_stage = 'completo'
            elif fase1_completa:
                wizard.habilitacion_stage = 'fase2'
            else:
                wizard.habilitacion_stage = 'fase1'

    def action_iniciar_habilitacion(self):
        """Botón único -- ejecuta la fase que corresponda según el estado.

        Fase 1 si aún no está completa; si no, Fase 2; si ambas ya están
        Aceptadas, solo devuelve el resumen final (el botón queda
        invisible en pantalla en ese caso, ver la vista).
        """
        self.ensure_one()
        if self.habilitacion_stage == 'fase1':
            return self.action_iniciar_habilitacion_individual()
        if self.habilitacion_stage == 'fase2':
            return self.action_iniciar_habilitacion_ajuste()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Habilitación DIAN completa'),
                'message': _(
                    'Metas cumplidas: %(ind)d Nómina Individual + '
                    '%(adj)d Notas de Ajuste Aceptadas por la DIAN.',
                    ind=self.count_accepted_individual,
                    adj=self.count_accepted_ajuste,
                ),
                'type': 'success',
                'sticky': True,
            },
        }

    # ──────────────────────────────────────────────────────────────────
    # Auto-selección (2026-09-12, pedido de David: "cero campos manuales
    # antes de presionar el botón" -- ni periodo ni empleados se piden en
    # pantalla, se resuelven con una regla determinística interna).
    # ──────────────────────────────────────────────────────────────────

    def _auto_select_period(self):
        """Resuelve el periodo de Fase 1 sin pedirlo en pantalla.

        Regla: el periodo del último ``hr.payslip`` confirmado
        (``state='done'``) de la estructura Nómina General de la
        compañía -- refleja el ciclo de nómina real más reciente. Si no
        hay ninguno todavía, cae al mes calendario actual completo.
        """
        self.ensure_one()
        struct = self.env.ref(
            'l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
        last = self.env['hr.payslip'].search([
            ('company_id', '=', self.company_id.id),
            ('struct_id', '=', struct.id),
            ('state', '=', 'done'),
        ], order='date_to desc', limit=1)
        if last:
            return last.date_from, last.date_to

        today = fields.Date.context_today(self)
        first_day = today.replace(day=1)
        last_day = first_day + relativedelta(months=1, days=-1)
        return first_day, last_day

    def _auto_select_employees(self, target_count):
        """Auto-selecciona empleados reales para Fase 1 sin selector en pantalla.

        Regla: contratos en estado 'open' (vigente hoy, no 'close'),
        ordenados por antigüedad ascendente (``date_start``) -- empleados
        con más antigüedad tienden a tener datos más completos/estables,
        menos probable que un contrato recién creado le falte algún dato
        que rompa la generación del XML. Determinístico, se re-ejecuta
        igual cada vez con los mismos datos de entrada.
        """
        self.ensure_one()
        if not target_count:
            raise UserError(_(
                'Configure la meta de "Nómina Individual a Certificar" '
                '(Ajustes > Nómina) antes de iniciar la habilitación.'
            ))
        contracts = self.env['hr.contract'].search([
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'open'),
        ], order='date_start asc', limit=target_count)
        if len(contracts) < target_count:
            raise UserError(_(
                'Se necesitan %(target)d empleados con contrato activo '
                'para la meta configurada, pero solo hay %(found)d '
                'disponibles.',
                target=target_count, found=len(contracts),
            ))
        return contracts.mapped('employee_id')

    # ──────────────────────────────────────────────────────────────────
    # Fase 1 -- acciones
    # ──────────────────────────────────────────────────────────────────

    def action_prepare_individual(self):
        """Crea, calcula, confirma y genera XML para los payslips de Fase 1.

        No envía nada a la DIAN -- deja los documentos en 'generated',
        listos para que se envíen cuando se decida gastar cupo.

        Periodo y empleados se auto-seleccionan internamente (2026-09-12,
        pedido de David: "cero campos manuales antes de presionar el
        botón") si todavía no están fijados en el wizard -- ver
        ``_auto_select_period``/``_auto_select_employees``.
        """
        self.ensure_one()
        if not self.date_from or not self.date_to:
            self.date_from, self.date_to = self._auto_select_period()
        if not self.employee_ids:
            self.employee_ids = self._auto_select_employees(
                self.num_nomina_certificar
            )

        struct = self.env.ref(
            'l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
        errors = []
        prepared = self.env['hr.payslip']
        for employee in self.employee_ids:
            contract = self.env['hr.contract'].search([
                ('employee_id', '=', employee.id),
                ('state', 'in', _CONTRACT_OPEN_STATES),
            ], limit=1, order='date_start desc')
            if not contract:
                errors.append(_(
                    '%s: no tiene contrato vigente.', employee.name
                ))
                continue
            try:
                payslip = self.env['hr.payslip'].create({
                    'name': _('Habilitación DIAN - %s', employee.name),
                    'employee_id': employee.id,
                    'contract_id': contract.id,
                    'struct_id': struct.id,
                    'date_from': self.date_from,
                    'date_to': self.date_to,
                })
                payslip.compute_sheet()
                payslip.action_payslip_done()
                payslip.action_generate_ne_xml()
                prepared |= payslip
            except Exception as e:
                errors.append(f'{employee.name}: {e}')

        self.payslip_individual_ids = [(4, p.id) for p in prepared]

        if errors:
            raise UserError(_(
                'Se prepararon %d de %d nóminas individuales. Errores:\n%s',
                len(prepared), len(self.employee_ids), '\n'.join(errors),
            ))
        return True

    def action_send_individual(self):
        """Envía a la DIAN las individuales listas -- consume cupo real."""
        self.ensure_one()
        records = self.payslip_individual_ids.filtered(
            lambda p: p.l10n_co_ne_state == 'generated'
        )
        if not records:
            raise UserError(_(
                'No hay nóminas individuales en estado "XML Generado" '
                'para enviar.'
            ))
        return records.action_send_test_set()

    def action_check_individual_status(self):
        """Consulta el estado DIAN de cada nómina individual enviada."""
        self.ensure_one()
        records = self.payslip_individual_ids.filtered(
            lambda p: p.l10n_co_ne_state in ('sent', 'generated')
        )
        for payslip in records:
            payslip.action_check_dian_status()
        return True

    # ──────────────────────────────────────────────────────────────────
    # Fase 2 -- acciones (requiere Individuales ya Aceptadas)
    # ──────────────────────────────────────────────────────────────────

    def action_prepare_ajuste(self):
        """Crea las Notas de Ajuste (Reemplazar) de las Individuales Aceptadas.

        Restricción real, no de diseño: ``action_create_adjustment()``
        exige predecesor en estado 'accepted' -- por eso esta fase solo
        avanza sobre lo que Fase 1 ya tenga aceptado por la DIAN.
        """
        self.ensure_one()
        accepted = self.payslip_individual_ids.filtered(
            lambda p: p.l10n_co_ne_state == 'accepted'
        )
        if not accepted:
            raise UserError(_(
                'No hay nóminas individuales Aceptadas por la DIAN '
                'todavía. La Nota de Ajuste solo puede prepararse sobre '
                'una nómina ya aceptada.'
            ))

        already_referenced = self.payslip_ajuste_ids.mapped(
            'l10n_co_ne_adjustment_ref_cune'
        )
        target = self.num_ajuste_certificar or len(accepted)
        pending = accepted.filtered(
            lambda p: p.l10n_co_ne_cune not in already_referenced
        )[:target]
        if not pending:
            raise UserError(_(
                'Ya se prepararon Notas de Ajuste para todas las nóminas '
                'individuales aceptadas disponibles.'
            ))

        errors = []
        prepared = self.env['hr.payslip']
        for original in pending:
            try:
                adjustment = self.env['hr.payslip'].create({
                    'name': _(
                        'Ajuste Habilitación DIAN - %s',
                        original.employee_id.name,
                    ),
                    'employee_id': original.employee_id.id,
                    'contract_id': original.contract_id.id,
                    'struct_id': original.struct_id.id,
                    'date_from': original.date_from,
                    'date_to': original.date_to,
                    'l10n_co_ne_is_adjustment': True,
                    'l10n_co_ne_adjustment_ref_cune': original.l10n_co_ne_cune,
                })
                adjustment.compute_sheet()
                adjustment.action_payslip_done()
                adjustment.action_generate_ne_xml()
                prepared |= adjustment
            except Exception as e:
                errors.append(f'{original.employee_id.name}: {e}')

        self.payslip_ajuste_ids = [(4, p.id) for p in prepared]

        if errors:
            raise UserError(_(
                'Se prepararon %d de %d notas de ajuste. Errores:\n%s',
                len(prepared), len(pending), '\n'.join(errors),
            ))
        return True

    def action_send_ajuste(self):
        """Envía a la DIAN las notas de ajuste listas -- consume cupo real."""
        self.ensure_one()
        records = self.payslip_ajuste_ids.filtered(
            lambda p: p.l10n_co_ne_state == 'generated'
        )
        if not records:
            raise UserError(_(
                'No hay notas de ajuste en estado "XML Generado" para '
                'enviar.'
            ))
        return records.action_send_test_set()

    def action_check_ajuste_status(self):
        """Consulta el estado DIAN de cada nota de ajuste enviada."""
        self.ensure_one()
        records = self.payslip_ajuste_ids.filtered(
            lambda p: p.l10n_co_ne_state in ('sent', 'generated')
        )
        for payslip in records:
            payslip.action_check_dian_status()
        return True

    # ──────────────────────────────────────────────────────────────────
    # Botón único por fase (2026-09-12, pedido de David) -- encadena
    # Preparar+Enviar+Consultar de la fase correspondiente en 1 clic,
    # reutilizando los métodos de arriba tal cual (sin duplicar lógica).
    # Idempotentes: repetir el clic no duplica preparación ni envío, solo
    # reintenta el sondeo de lo que siga pendiente.
    # ──────────────────────────────────────────────────────────────────

    def _poll_until_resolved(self, get_records):
        """Sondea GetStatusZip hasta _POLL_ATTEMPTS veces (mismo patrón v19).

        Args:
            get_records: función sin argumentos que devuelve el recordset
                de payslips (individual o ajuste) a considerar.
        """
        for attempt in range(_POLL_ATTEMPTS):
            checking = get_records().filtered(
                lambda p: p.l10n_co_ne_state in ('sent', 'generated')
            )
            if not checking:
                return
            for payslip in checking:
                payslip.action_check_dian_status()
            if not get_records().filtered(
                lambda p: p.l10n_co_ne_state in ('sent', 'generated')
            ) or attempt == _POLL_ATTEMPTS - 1:
                return
            time.sleep(_POLL_DELAY_SECONDS)

    def action_iniciar_habilitacion_individual(self):
        """Fase 1 en 1 clic: Preparar (si hace falta) + Enviar + Consultar.

        No re-prepara si ya hay individuales cargadas (idempotente) --
        repetir el clic solo reintenta enviar/consultar lo pendiente.
        """
        self.ensure_one()
        if not self.payslip_individual_ids:
            self.action_prepare_individual()

        pending_send = self.payslip_individual_ids.filtered(
            lambda p: p.l10n_co_ne_state == 'generated'
        )
        if pending_send:
            pending_send.action_send_test_set()

        self._poll_until_resolved(lambda: self.payslip_individual_ids)

        accepted = len(self.payslip_individual_ids.filtered(
            lambda p: p.l10n_co_ne_state == 'accepted'
        ))
        total = len(self.payslip_individual_ids)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Habilitación DIAN — Fase 1 (Nómina Individual)'),
                'message': _(
                    '%(accepted)d de %(total)d Nóminas Individuales '
                    'Aceptadas por la DIAN.',
                    accepted=accepted, total=total,
                ),
                'type': 'success' if total and accepted == total else 'warning',
                'sticky': True,
            },
        }

    def action_iniciar_habilitacion_ajuste(self):
        """Fase 2 en 1 clic: Preparar (si hace falta) + Enviar + Consultar.

        Exige que ya haya Individuales Aceptadas (restricción real de
        ``action_create_adjustment()``, no de este wizard). No re-prepara
        Notas de Ajuste ya referenciadas (idempotente).
        """
        self.ensure_one()
        accepted_individual = self.payslip_individual_ids.filtered(
            lambda p: p.l10n_co_ne_state == 'accepted'
        )
        if not accepted_individual:
            raise UserError(_(
                'No hay nóminas individuales Aceptadas por la DIAN '
                'todavía. Complete la Fase 1 primero.'
            ))

        already_referenced = self.payslip_ajuste_ids.mapped(
            'l10n_co_ne_adjustment_ref_cune'
        )
        pending_prepare = accepted_individual.filtered(
            lambda p: p.l10n_co_ne_cune not in already_referenced
        )
        if pending_prepare:
            self.action_prepare_ajuste()

        pending_send = self.payslip_ajuste_ids.filtered(
            lambda p: p.l10n_co_ne_state == 'generated'
        )
        if pending_send:
            pending_send.action_send_test_set()

        self._poll_until_resolved(lambda: self.payslip_ajuste_ids)

        accepted = len(self.payslip_ajuste_ids.filtered(
            lambda p: p.l10n_co_ne_state == 'accepted'
        ))
        total = len(self.payslip_ajuste_ids)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Habilitación DIAN — Fase 2 (Notas de Ajuste)'),
                'message': _(
                    '%(accepted)d de %(total)d Notas de Ajuste Aceptadas '
                    'por la DIAN.',
                    accepted=accepted, total=total,
                ),
                'type': 'success' if total and accepted == total else 'warning',
                'sticky': True,
            },
        }
