# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""Q-58: el botón «Validar» de la ficha de la entrada de trabajo solo aparece en compañías colombianas."""

from odoo import api, fields, models


class HrWorkEntry(models.Model):
    _inherit = 'hr.work.entry'

    l10n_co_ne_es_colombia = fields.Boolean(string='Compañía colombiana', compute='_compute_l10n_co_ne_es_colombia')

    @api.depends('company_id')
    def _compute_l10n_co_ne_es_colombia(self):
        for entrada in self:
            entrada.l10n_co_ne_es_colombia = bool(entrada.company_id) and entrada.company_id._ne_es_colombia()
