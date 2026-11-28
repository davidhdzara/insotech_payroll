# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""Recibos reembolsados (.341): el asistente nativo de generar escribe «en espera» en todos los recibos del lote; los que un reembolso protege se quedan como están y los demás siguen igual."""

from odoo import models


class HrPayslipEmployees(models.TransientModel):
    _inherit = 'hr.payslip.employees'

    def compute_sheet(self):
        return super(HrPayslipEmployees, self.with_context(ne_lote_conserva_reembolsados=True)).compute_sheet()
