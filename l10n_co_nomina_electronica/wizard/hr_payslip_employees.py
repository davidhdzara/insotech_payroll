# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""Asistente nativo «Generar recibos».

Recibos reembolsados (.341): escribe «en espera» en todos los recibos del lote; los que un reembolso protege se quedan como están y los demás siguen igual.
Q-48: en una compañía colombiana solo se ofrecen estructuras de Colombia (las nativas sin país, como «Regular Pay», dejan la lista de empleados vacía)."""

from odoo import fields, models


class HrPayslipEmployees(models.TransientModel):
    _inherit = 'hr.payslip.employees'

    structure_id = fields.Many2one(domain=lambda self: [('country_id.code', '=', 'CO')] if self.env.company._ne_es_colombia() else [])

    def compute_sheet(self):
        return super(HrPayslipEmployees, self.with_context(ne_lote_conserva_reembolsados=True)).compute_sheet()
