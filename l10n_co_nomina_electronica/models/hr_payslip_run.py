# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""E-5 (doc 59 §22): el boton nativo «Mark as paid» del lote no fija la fecha de pago de forma silenciosa.

``hr.payslip.run.action_paid`` llama a ``action_payslip_paid``, que escribe ``paid_date = hoy`` sin preguntar. Con la fuente de la fecha de
pago «Fecha de pago del recibo» esa fecha decide el mes del documento de nomina electronica y ``FechasPagos``: un lote pagado el 28-oct y
marcado el 2-nov pasaria al documento de noviembre. Para companias colombianas con esa fuente el boton abre el asistente
«Registrar fecha de pago» (fecha editable, no futura) con los recibos del lote; el resto (fuente «contabilidad», otros paises) conserva
el comportamiento nativo."""

from odoo import _, fields, models


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    # H-F1-10 (opción A): un recibo por tramo cuando la ficha del empleado cambia dentro del periodo. Solo compañías de Colombia y la estructura general.
    def _get_valid_version_ids(self, date_start=None, date_end=None, structure_id=None, company_id=None, employee_ids=None, schedule_pay=None):
        """El nativo toma la versión vigente al inicio y la primera de cada contrato nuevo (``hr_payroll/models/hr_payslip_run.py:120-178``): aquí se suman las versiones del mismo contrato que empiezan dentro del periodo."""
        ids = super()._get_valid_version_ids(date_start=date_start, date_end=date_end, structure_id=structure_id, company_id=company_id, employee_ids=employee_ids, schedule_pay=schedule_pay)
        return self._ne_versiones_por_tramo(ids, date_start or self.date_start, date_end or self.date_end, structure_id, company_id)

    def _ne_versiones_por_tramo(self, ids, inicio, fin, structure_id=None, company_id=None):
        """``ids`` más las versiones intra-contrato del periodo; de los empleados con más de una, se quita la que ya tiene un recibo (no cancelado, ni ajuste ni nota crédito) cruzado con su tramo, para no duplicar."""
        compania = self.env['res.company'].browse(company_id or self.company_id.id)
        general = self.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina', raise_if_not_found=False)
        estructura = self.env['hr.payroll.structure'].browse(structure_id) if structure_id else self.structure_id
        if not (ids and inicio and fin and general and compania and compania._ne_es_colombia()) or (estructura and estructura != general):
            return ids
        inicio, fin = fields.Date.to_date(inicio), fields.Date.to_date(fin)

        def es_general(version):        # lote sin estructura: la estructura por defecto del tipo de la versión
            tipo = version.structure_type_id
            return tipo == general.type_id if estructura else tipo.default_struct_id == general

        def tramo(version):
            return (max(inicio, version.date_start) if version.date_start else inicio), (min(fin, version.date_end) if version.date_end else fin)

        resultado = list(ids)
        elegidas = self.env['hr.version'].sudo().browse(ids).filtered(es_general)
        Recibo = self.env['hr.payslip'].sudo()
        for empleado in elegidas.employee_id:
            propias = elegidas.filtered(lambda v: v.employee_id == empleado)
            contratos = set(propias.mapped('contract_date_start'))
            extra = empleado.version_ids.filtered(
                lambda v: v.id not in ids and v.contract_date_start in contratos and inicio < v.date_version <= fin and es_general(v))
            # un tramo que empieza el día 31 no tiene días en el mes comercial de 30
            extra = extra.filtered(lambda v: tramo(v)[0] <= tramo(v)[1] and tramo(v)[0].day != 31)
            partidas = propias | extra
            if len(partidas) < 2:
                continue
            resultado += extra.ids
            for version in partidas:
                desde, hasta = tramo(version)
                if Recibo.search_count([
                        ('employee_id', '=', empleado.id), ('struct_id', '=', general.id), ('state', '!=', 'cancel'), ('credit_note', '=', False),
                        ('l10n_co_ne_is_adjustment', '=', False), ('date_from', '<=', hasta), ('date_to', '>=', desde)], limit=1):
                    resultado.remove(version.id)
        return resultado

    def generate_payslips(self, version_ids=None, employee_ids=None):
        """El contexto hace que ``hr.payslip.create`` feche cada recibo por su tramo ANTES de calcular (el nativo pone las fechas del lote, ``:401-402``)."""
        return super(HrPayslipRun, self.with_context(ne_lote_por_tramo=True)).generate_payslips(version_ids=version_ids, employee_ids=employee_ids)

    def action_paid(self):
        if not self.env.context.get('ne_fecha_pago_definida'):
            recibos = self.slip_ids.filtered(
                lambda s: s.state == 'validated' and s.company_id._ne_es_colombia()
                and s.company_id.l10n_co_ne_fuente_fecha_pago == 'recibo')
            if recibos:
                return {
                    'type': 'ir.actions.act_window', 'name': _('Registrar fecha de pago'),
                    'res_model': 'hr.payslip.registrar.pago', 'view_mode': 'form', 'target': 'new',
                    'context': {'active_model': 'hr.payslip', 'active_ids': recibos.ids, 'ne_payslip_run_ids': self.ids}}
        return super().action_paid()
