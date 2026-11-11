# -*- coding: utf-8 -*-
"""Prima de servicios: CO_PRIMA_BASE es un acumulador interno, no un devengado.

Hallazgo de QA en pantalla (recibo de prima 8571): CO_PRIMA_NETO = BASE + VALOR - deducciones
= 2.991.678,70, porque la base (salario + auxilio) estaba en PREST y sumaba al neto; ademas el
nodo Primas del XML sumaba la Cantidad de las dos lineas (1 + 180 = 181). Valores a mano:
$3.000.000 con auxilio 2026 (249.095) -> base 3.249.095; semestre completo de 180 dias ->
valor 3.249.095 x 180 / 360 = 1.624.547,50; salud y pension 4% de ese valor = 64.981,90 c/u.
"""

from datetime import date

from odoo.tests.common import TransactionCase


class TestPrimaNeto(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'l10n_co_pila_clase_riesgo': '1', 'name': 'Compañía de Prueba Prima Neto'})
        cls.structure_type = cls.env['hr.payroll.structure.type'].create({
            'name': 'Prueba Estructura Prima', 'country_id': cls.env.ref('base.co').id})
        cls.est_prima = cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_prima')

    def _prima(self):
        employee = self.env['hr.employee'].create({
            'name': 'Prima Neto', 'company_id': self.company.id,
            'l10n_co_ne_payment_method': '10'})
        contract = self.env['hr.contract'].create({
            'name': 'Contrato Prima', 'employee_id': employee.id, 'company_id': self.company.id,
            'structure_type_id': self.structure_type.id, 'wage': 3000000.0,
            'date_start': date(2024, 3, 1), 'state': 'open'})
        slip = self.env['hr.payslip'].create({
            'name': 'Prima', 'employee_id': employee.id, 'contract_id': contract.id,
            'company_id': self.company.id, 'struct_id': self.est_prima.id,
            'date_from': date(2026, 7, 1), 'date_to': date(2026, 12, 31)})
        slip.compute_sheet()
        return slip

    def _total(self, slip, code):
        return sum(slip.line_ids.filtered(lambda l: l.code == code).mapped('total'))

    def test_neto_es_valor_menos_deducciones_sin_sumar_la_base(self):
        slip = self._prima()
        valor = self._total(slip, 'CO_PRIMA_VALOR')
        self.assertAlmostEqual(valor, 1624547.50, places=2)
        deducciones = sum(self._total(slip, c) for c in (
            'CO_PRIMA_SALUD', 'CO_PRIMA_PENSION', 'CO_PRIMA_RETE'))
        self.assertAlmostEqual(self._total(slip, 'CO_PRIMA_SALUD'), -64981.90, places=2)
        self.assertAlmostEqual(self._total(slip, 'CO_PRIMA_PENSION'), -64981.90, places=2)
        self.assertAlmostEqual(self._total(slip, 'CO_PRIMA_NETO'), valor + deducciones, places=2)

    def test_la_base_no_es_un_concepto_visible_ni_va_a_dian(self):
        slip = self._prima()
        base = slip.line_ids.filtered(lambda l: l.code == 'CO_PRIMA_BASE')
        self.assertAlmostEqual(base.total, 3249095.0, places=2)   # el acumulador sigue calculandose
        self.assertFalse(base.salary_rule_id.appears_on_payslip)
        self.assertFalse(base.salary_rule_id.l10n_co_ne_dian_concept)
        self.assertNotIn('CO_PRIMA_BASE', slip._ne_pdf_lineas().mapped('code'))

    def test_xml_primas_cantidad_180_y_pago_del_valor(self):
        slip = self._prima()
        devengados = {}
        slip._dev_prestaciones(slip._group_lines_by_concept(), devengados)
        self.assertEqual(devengados['Primas']['Cantidad'], '180')
        self.assertEqual(devengados['Primas']['Pago'], '1624547.50')
