# -*- coding: utf-8 -*-
"""Liquidacion: las ausencias en dias HABILES que se descuentan del sueldo pendiente son solo las
del tramo del ultimo mes, no las de toda la vida del contrato.

En liquidacion date_from = inicio de contrato, asi que worked_days cubre todo el contrato mientras
que el sueldo pendiente (CO_LIQ_SALARIOS) es del tramo del ultimo mes. _ne_dias_pagables() resta
de los dias del tramo todos los dias de CO_VAC/CO_LIC_REM/CO_LIC_NR/unpaid de worked_days, de
cualquier mes: vacaciones de marzo descuentan dias del sueldo de agosto.

Caso: contrato desde 2026-01-01, vacaciones de 5 dias habiles (2-6 de marzo, lunes a viernes),
retiro el 2026-08-15 -> el tramo pagable es 1-15 de agosto = 15 dias comerciales, y las
vacaciones de marzo (ya pagadas en su nomina) no deben restarse. Sin la correccion esta prueba
da 10 dias (15 - 5).
"""

from datetime import date

from odoo.tests.common import TransactionCase

RETIRO = date(2026, 8, 15)


class TestLiquidacionTramoAusencias(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Compañía de Prueba Tramo Ausencias Liquidación'})
        # Mismo entorno y datos en la misma compañía (ver test_ausencias_nomina).
        cls.env = cls.company.with_company(cls.company).env
        cls.structure_type = cls.env['hr.payroll.structure.type'].create({
            'name': 'Prueba Estructura Tramo', 'country_id': cls.env.ref('base.co').id})
        cls.liquidacion = cls.env.ref(
            'l10n_co_nomina_electronica.hr_payroll_structure_co_liquidacion')
        cls.leave_type_vac = cls.env.ref('l10n_co_nomina_electronica.hr_leave_type_co_vac')

    def _liquidacion_con_vacaciones(self, name, vac_desde, vac_hasta):
        employee = self.env['hr.employee'].create({
            'name': name, 'company_id': self.company.id, 'l10n_co_ne_payment_method': '10'})
        contract = self.env['hr.contract'].create({
            'name': 'Contrato %s' % name, 'employee_id': employee.id,
            'company_id': self.company.id, 'structure_type_id': self.structure_type.id,
            'wage': 1800000.0, 'date_start': date(2026, 1, 1), 'state': 'open'})
        # Precondicion operativa real: work entries del contrato antes de validar la ausencia.
        contract.generate_work_entries(date(2026, 1, 1), RETIRO)
        leave = self.env['hr.leave'].create({
            'employee_id': employee.id, 'holiday_status_id': self.leave_type_vac.id,
            'request_date_from': vac_desde, 'request_date_to': vac_hasta})
        leave.action_validate()
        self.assertEqual(leave.state, 'validate')
        # Como lo crea el asistente: date_from = inicio de contrato.
        slip = self.env['hr.payslip'].create({
            'name': 'Liquidación %s' % name, 'employee_id': employee.id,
            'contract_id': contract.id, 'company_id': self.company.id,
            'struct_id': self.liquidacion.id,
            'date_from': contract.date_start, 'date_to': RETIRO})
        slip.compute_sheet()
        return slip

    def _salarios(self, slip):
        linea = slip.line_ids.filtered(lambda l: l.code == 'CO_LIQ_SALARIOS')
        self.assertTrue(linea, 'CO_LIQ_SALARIOS no generó línea.')
        return linea

    def test_vacaciones_de_meses_anteriores_no_descuentan_el_sueldo_del_ultimo_tramo(self):
        slip = self._liquidacion_con_vacaciones(
            'VacMarzo', date(2026, 3, 2), date(2026, 3, 6))   # 5 dias habiles, ya pagados
        salarios = self._salarios(slip)
        self.assertEqual(slip._ne_dias_pagables(), 15)        # tramo 1-15 de agosto
        self.assertEqual(salarios.quantity, 15.0)
        self.assertAlmostEqual(salarios.total, 1800000.0 / 30 * 15, places=2)

    def test_vacaciones_dentro_del_ultimo_tramo_si_se_descuentan(self):
        """Control: 3-7 de agosto (5 dias habiles, dentro del tramo 1-15) siguen restando."""
        slip = self._liquidacion_con_vacaciones(
            'VacAgosto', date(2026, 8, 3), date(2026, 8, 7))
        self.assertEqual(slip._ne_dias_pagables(), 10)
        self.assertEqual(self._salarios(slip).quantity, 10.0)
