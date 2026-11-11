# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""HrPayslip._ne_dias_comerciales: calendario comercial de 360 días (meses de 30).

Decisión de David: "el 31 prácticamente se regala". El último día real de cada mes cuenta como
día 30 (febrero completo = 30). Valores esperados calculados a mano, extremos incluidos:
días = meses x 30 + día_comercial(fin) - día_comercial(inicio) + 1."""

from datetime import date

from odoo.tests.common import TransactionCase


class TestDiasComerciales(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'l10n_co_pila_clase_riesgo': '1', 'name': 'Compañía de Prueba Días Comerciales'})
        structure_type = cls.env['hr.payroll.structure.type'].create({
            'name': 'Prueba Estructura Días Comerciales',
            'country_id': cls.env.ref('base.co').id})
        employee = cls.env['hr.employee'].create({
            'name': 'Empleado Días Comerciales', 'company_id': cls.company.id,
            'l10n_co_ne_payment_method': '10'})
        contract = cls.env['hr.contract'].create({
            'name': 'Contrato Días Comerciales', 'employee_id': employee.id,
            'company_id': cls.company.id, 'structure_type_id': structure_type.id,
            'wage': 3000000.0, 'date_start': date(2023, 1, 1), 'state': 'open'})
        cls.slip = cls.env['hr.payslip'].create({
            'name': 'Nómina Días Comerciales', 'employee_id': employee.id,
            'contract_id': contract.id, 'company_id': cls.company.id,
            'struct_id': cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina').id,
            'date_from': date(2026, 7, 1), 'date_to': date(2026, 7, 31)})

    def _dias(self, ini, fin):
        return self.slip._ne_dias_comerciales(ini, fin)

    def test_mes_de_31_dias_cuenta_30(self):
        self.assertEqual(self._dias(date(2026, 1, 1), date(2026, 1, 31)), 30)

    def test_febrero_completo_cuenta_30(self):
        self.assertEqual(self._dias(date(2026, 2, 1), date(2026, 2, 28)), 30)

    def test_febrero_bisiesto_completo_cuenta_30(self):
        self.assertEqual(self._dias(date(2024, 2, 1), date(2024, 2, 29)), 30)

    def test_dia_31_no_suma_sobre_el_30(self):
        # 30-ene y 31-ene son ambos el día comercial 30: un solo día.
        self.assertEqual(self._dias(date(2026, 1, 30), date(2026, 1, 31)), 1)
        self.assertEqual(self._dias(date(2026, 1, 31), date(2026, 1, 31)), 1)

    def test_ingreso_a_mitad_de_mes(self):
        # 15-mar a 15-abr: 30 + 15 - 15 + 1 = 31 (inclusivo).
        self.assertEqual(self._dias(date(2026, 3, 15), date(2026, 4, 15)), 31)
        # 16-mar a 31-mar: 30 - 16 + 1 = 15.
        self.assertEqual(self._dias(date(2026, 3, 16), date(2026, 3, 31)), 15)

    def test_semestres_y_anio_completos(self):
        self.assertEqual(self._dias(date(2026, 1, 1), date(2026, 6, 30)), 180)
        self.assertEqual(self._dias(date(2026, 7, 1), date(2026, 12, 31)), 180)
        self.assertEqual(self._dias(date(2026, 1, 1), date(2026, 12, 31)), 360)

    def test_rango_largo(self):
        # 1-mar-2024 a 15-ago-2026: 29 meses x 30 + 15 = 885.
        self.assertEqual(self._dias(date(2024, 3, 1), date(2026, 8, 15)), 885)

    def test_rango_invertido_es_cero(self):
        self.assertEqual(self._dias(date(2026, 3, 2), date(2026, 3, 1)), 0)
