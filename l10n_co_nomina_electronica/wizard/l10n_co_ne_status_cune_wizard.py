# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.

"""H-006: consulta del estado DIAN a partir de un CUNE.

Resuelve el CUNE a la nómina que lo generó usando el historial de envíos
(``l10n.co.ne.exchange.document``, que guarda ``cune`` y ``payslip_id`` por cada documento de
cualquier envío) y reutiliza ``hr.payslip.action_check_dian_status()`` -- toda la lógica de
emparejamiento y estado ya verificada. No transmite nada nuevo a la DIAN: la consulta sigue
siendo por ZipKey (GetStatusZip). Un CUNE que no pasó por un envío de este sistema no se puede
consultar aquí (la operación GetStatus por CUNE del Anexo, numeral 14.10, no está implementada).
"""

from odoo import fields, models, _
from odoo.exceptions import UserError


class L10nCoNeStatusCuneWizard(models.TransientModel):
    _name = 'l10n.co.ne.status.cune.wizard'
    _description = 'Consultar estado DIAN por CUNE'

    cune = fields.Char(string='CUNE', required=True)

    def _resolve_payslip(self):
        self.ensure_one()
        cune = (self.cune or '').strip()
        documento = self.env['l10n.co.ne.exchange.document'].search([
            ('cune', '=', cune),
            ('company_id', '=', self.env.company.id),
        ], order='id desc', limit=1)
        if not documento:
            raise UserError(_(
                'CUNE no encontrado en el historial de envíos de esta compañía. Solo se pueden '
                'consultar documentos que este sistema ya envió a la DIAN.'))
        payslip = documento.payslip_id
        if not payslip.l10n_co_ne_zip_key:
            # El envío guardó el ZipKey en el intercambio, no necesariamente en la nómina.
            payslip.l10n_co_ne_zip_key = documento.exchange_id.zip_key
        if not payslip.l10n_co_ne_zip_key:
            raise UserError(_(
                'El envío de ese CUNE no tiene ZipKey registrado; no hay con qué consultar a la DIAN.'))
        return payslip

    def action_check_status(self):
        self.ensure_one()
        payslip = self._resolve_payslip()
        return payslip.action_check_dian_status()
