# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""H-170: el tramo de la incapacidad comun se cuenta desde el INICIO de la incapacidad (y sus
prorrogas contiguas), no desde el inicio de cada recibo.

Antes _ne_pago_ausencia_calendario(codigo, dias) solo recibia los dias del recibo y el tramo
(2 dias empleador, 3-90 EPS, 91+) reiniciaba en cada quincena. Caso de aceptacion de QA
(FUN-REG-012): salario 6.000.000 (valor dia 200.000), incapacidad desde el 1-mar-2026:
- 1 a 15 de marzo: dias 1-15 al 66,67 % = 15 x 200.000 x 0,6667 = 2.000.100.
- 1 a 15 de junio: dias 93-107 (mar 31 + abr 30 + may 31 = 92 previos) al 50 % = 15 x 200.000 x 0,5
  = 1.500.000 (con el reinicio por recibo daba 2.000.100).
Piso diario 2026 = 1.750.905 / 30 = 58.363,5 (no domina: 66,67 % y 50 % de 200.000 son mayores)."""

from datetime import date

from odoo.tests.common import TransactionCase

PCT = 0.6667
VALOR_DIA = 200000.0


class TestIncapacidadTramoProrroga(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'l10n_co_pila_clase_riesgo': '1', 'l10n_co_ne_febrero_modo': 'real',
            'l10n_co_ne_redondeo_dias': 'DOWN', 'name': 'Compañía de Prueba Tramo Incapacidad'})
        cls.env = cls.company.with_company(cls.company).env
        cls.structure_type = cls.env['hr.payroll.structure.type'].create({
            'name': 'Prueba Estructura Tramo Incap', 'country_id': cls.env.ref('base.co').id})
        cls.nomina = cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
        cls.tipo = cls.env.ref('l10n_co_nomina_electronica.hr_leave_type_co_inc_comun')

    def _empleado(self, name):
        employee = self.env['hr.employee'].create({
            'name': name, 'company_id': self.company.id, 'l10n_co_ne_payment_method': '10'})
        contract = self.env['hr.contract'].create({
            'name': 'Contrato %s' % name, 'employee_id': employee.id,
            'company_id': self.company.id, 'structure_type_id': self.structure_type.id,
            'wage': 6000000.0, 'date_start': date(2026, 1, 1), 'state': 'open'})
        contract.generate_work_entries(date(2026, 1, 1), date(2026, 6, 30))
        return employee, contract

    def _incapacidad(self, employee, desde, hasta):
        leave = self.env['hr.leave'].create({
            'employee_id': employee.id, 'holiday_status_id': self.tipo.id,
            'request_date_from': desde, 'request_date_to': hasta})
        leave.action_validate()
        self.assertEqual(leave.state, 'validate')

    def _pago(self, employee, contract, desde, hasta):
        slip = self.env['hr.payslip'].create({
            'name': 'Quincena %s' % desde, 'employee_id': employee.id,
            'contract_id': contract.id, 'company_id': self.company.id,
            'struct_id': self.nomina.id, 'date_from': desde, 'date_to': hasta})
        slip.compute_sheet()
        linea = slip.line_ids.filtered(lambda l: l.code == 'CO_INC_COMUN')
        self.assertTrue(linea, 'La quincena %s debe pagar incapacidad.' % desde)
        return linea.total

    def test_aceptacion_qa_fun_reg_012(self):
        employee, contract = self._empleado('FunReg012')
        self._incapacidad(employee, date(2026, 3, 1), date(2026, 6, 15))   # 107 dias
        self.assertAlmostEqual(
            self._pago(employee, contract, date(2026, 3, 1), date(2026, 3, 15)),
            15 * VALOR_DIA * PCT, places=2)                                  # 2.000.100
        self.assertAlmostEqual(
            self._pago(employee, contract, date(2026, 6, 1), date(2026, 6, 15)),
            15 * VALOR_DIA * 0.5, places=2)                                  # 1.500.000

    def test_el_dia_91_cambia_de_tramo_dentro_de_una_quincena(self):
        """16-31 de mayo: previos 1-mar a 15-may = 76 dias reales -> posiciones 77-91: 14 dias
        (77-90) al 66,67 % y el 91 al 50 %: 14 x 200.000 x 0,6667 + 200.000 x 0,5 = 1.966.760."""
        employee, contract = self._empleado('Dia91')
        self._incapacidad(employee, date(2026, 3, 1), date(2026, 6, 15))
        self.assertAlmostEqual(
            self._pago(employee, contract, date(2026, 5, 16), date(2026, 5, 31)),
            14 * VALOR_DIA * PCT + VALOR_DIA * 0.5, places=2)

    def test_la_prorroga_contigua_continua_el_conteo(self):
        """1-mar a 5-jun (97 dias) y prorroga 6 a 20 de junio: en la quincena 1-15 de junio van los
        dias 93-107 de la misma incapacidad: 5 de la primera y 10 de la prorroga, todos al 50 %."""
        employee, contract = self._empleado('Prorroga')
        self._incapacidad(employee, date(2026, 3, 1), date(2026, 6, 5))
        self._incapacidad(employee, date(2026, 6, 6), date(2026, 6, 20))
        self.assertAlmostEqual(
            self._pago(employee, contract, date(2026, 6, 1), date(2026, 6, 15)),
            15 * VALOR_DIA * 0.5, places=2)

    def test_una_incapacidad_no_contigua_empieza_su_propio_conteo(self):
        """1-mar a 31-may (92 dias) y otra distinta del 5 al 15 de junio (hay 4 dias libres entre
        las dos): la nueva cuenta desde 1: 11 dias (2 empleador + 9 EPS, todos al 66,67 %)."""
        employee, contract = self._empleado('NoContigua')
        self._incapacidad(employee, date(2026, 3, 1), date(2026, 5, 31))
        self._incapacidad(employee, date(2026, 6, 5), date(2026, 6, 15))
        self.assertAlmostEqual(
            self._pago(employee, contract, date(2026, 6, 1), date(2026, 6, 15)),
            11 * VALOR_DIA * PCT, places=2)

    def test_primeros_dos_dias_del_empleador_solo_en_el_inicio_de_la_incapacidad(self):
        """Con piso: el empleador (dias 1-2) y la EPS (3-90) pagan igual porcentaje, pero el 91+
        no: una quincena de junio dentro del dia 91+ nunca vuelve a tramo de empleador."""
        employee, contract = self._empleado('SoloInicio')
        self._incapacidad(employee, date(2026, 3, 1), date(2026, 6, 15))
        pago = self._pago(employee, contract, date(2026, 6, 1), date(2026, 6, 15))
        self.assertLess(pago, 15 * VALOR_DIA * PCT)
