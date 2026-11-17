# -*- coding: utf-8 -*-
"""H-TL-009: el centavo con 2+ entradas del mismo tipo cuyo código coincide con el de una regla (REPRODUCCIÓN, sin código de producto).

Mecanismo (hr_payroll/models/hr_payslip.py del servidor v18, líneas 957-990):
- ``rule.code in localdict['same_type_input_lines']`` (2+ entradas del mismo tipo): por CADA entrada se calcula
  ``tot_rule = payslip._get_payslip_line_total(amount, qty, rate, rule)`` (:961) y se ACUMULA
  ``result_rules_dict[rule.code]['total'] += tot_rule`` (:963-966), sin redondear;
- y se agrega UNA línea por entrada con su propio ``total`` (:972-986), que Odoo guarda redondeado a los decimales de la moneda.
El ayudante del neto de E-8 (``_ne_suma_lineas_redondeadas``) lee ese acumulado y lo redondea UNA vez: con 2 entradas de 10,004 el
acumulado es 20,008 -> 20,01, pero las líneas guardadas son 10,00 + 10,00 = 20,00. El neto guardado queda un centavo por encima de
la suma de las líneas y el asiento (débitos = devengados guardados; créditos = deducciones + neto) no cuadra. Aplica a las 39 reglas
cuyo código coincide con un tipo de entrada (CO_HED, CO_COMISIONES, CO_LIBRANZAS...) y solo con montos fraccionarios. Según v19 el
motor de v19 tiene el mismo patrón.

ESTADO: esta prueba afirma el comportamiento CORRECTO (neto = suma de las líneas guardadas, asiento cuadrado) y se espera que FALLE
con el código actual (.276); NO está importada en ``tests/__init__.py`` a propósito, para no poner en rojo la regresión. Se importa
junto con la corrección (.277). La primera prueba solo fija la premisa (una línea por entrada) y la aritmética a mano.
NO ejecutada en Odoo.
"""

from datetime import date

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import float_compare

NETOS = ('CO_NETO', 'CO_LIQ_NETO', 'CO_PRIMA_NETO', 'CO_BON_NETO')


@tagged('post_install', '-at_install')
class TestNetoEntradasMultiples(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U',
            'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_clase_riesgo': '1', 'l10n_co_ne_febrero_modo': 'real',
            'l10n_co_ne_redondeo_dias': 'DOWN', 'name': 'Compañía de Prueba Entradas Múltiples'})
        cls.structure_type = cls.env['hr.payroll.structure.type'].create({
            'name': 'Prueba Estructura Entradas Múltiples', 'country_id': cls.env.ref('base.co').id})
        cls.est_general = cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
        cls.Categoria = cls.env['hr.salary.rule.category']

    def _recibo(self, name):
        empleado = self.env['hr.employee'].create({
            'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00', 'name': name,
            'company_id': self.company.id, 'l10n_co_ne_payment_method': '10'})
        contrato = self.env['hr.contract'].create({
            'l10n_co_ne_contract_type': '2', 'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00',
            'name': 'Contrato %s' % name, 'employee_id': empleado.id, 'company_id': self.company.id,
            'structure_type_id': self.structure_type.id, 'wage': 3000000.0, 'date_start': date(2024, 3, 1),
            'state': 'open'})
        return self.env['hr.payslip'].create({
            'name': name, 'employee_id': empleado.id, 'contract_id': contrato.id, 'company_id': self.company.id,
            'struct_id': self.est_general.id, 'date_from': date(2026, 9, 1), 'date_to': date(2026, 9, 15)})

    def _comisiones(self, recibo, *montos):
        for monto in montos:
            self.env['hr.payslip.input'].create({
                'payslip_id': recibo.id, 'input_type_id': self.env.ref('l10n_co_nomina_electronica.input_co_comisiones').id,
                'code': 'CO_COMISIONES', 'amount': monto})

    def _categorias(self, codigo):
        return self.Categoria.search([('id', 'child_of', self.Categoria.search([('code', '=', codigo)]).ids)])

    def _asiento(self, recibo):
        """Lo que hace el asiento nativo con las líneas GUARDADAS: devengados se debitan; deducciones y neto se acreditan."""
        devengados, deducciones = self._categorias('DEV'), self._categorias('DEDU')
        lineas = recibo.line_ids.filtered(lambda l: l.code not in NETOS)
        neto = recibo.line_ids.filtered(lambda l: l.code in NETOS)
        self.assertEqual(len(neto), 1)
        debitos = sum(l.total for l in lineas if l.category_id in devengados)
        creditos = -sum(l.total for l in lineas if l.category_id in deducciones) + neto.total
        return debitos, creditos

    def test_premisa_una_linea_por_entrada_y_cada_una_redondeada(self):
        recibo = self._recibo('Multiples Premisa')
        self._comisiones(recibo, 10.004, 10.004)
        recibo.compute_sheet()
        lineas = recibo.line_ids.filtered(lambda l: l.code == 'CO_COMISIONES')
        self.assertEqual(len(lineas), 2, 'Se esperaba UNA línea por entrada (hr_payslip.py:972-986).')
        self.assertEqual(sorted(lineas.mapped('total')), [10.0, 10.0])
        self.assertEqual(sum(lineas.mapped('total')), 20.0)           # 10,00 + 10,00; el acumulado del motor es 20,008

    def test_el_neto_guardado_es_la_suma_de_las_lineas_y_el_asiento_cuadra(self):
        """DEBE FALLAR con el código actual: neto 0,01 por encima de la suma de las líneas."""
        recibo = self._recibo('Multiples Neto')
        self._comisiones(recibo, 10.004, 10.004)
        recibo.compute_sheet()
        debitos, creditos = self._asiento(recibo)
        self.assertEqual(
            float_compare(debitos, creditos, precision_digits=2), 0,
            'El asiento no cuadra: débitos %.2f, créditos %.2f (diferencia %.2f)' % (debitos, creditos, debitos - creditos))

    def test_con_una_sola_entrada_no_cambia(self):
        """Control: con UNA entrada fraccionaria la línea y el acumulado coinciden y el asiento cuadra hoy."""
        recibo = self._recibo('Multiples Control')
        self._comisiones(recibo, 10.004)
        recibo.compute_sheet()
        debitos, creditos = self._asiento(recibo)
        self.assertEqual(float_compare(debitos, creditos, precision_digits=2), 0)
