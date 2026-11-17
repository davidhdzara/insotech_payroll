# -*- coding: utf-8 -*-
"""H-TL-010 (candidato): CO_EMBARGO con 2+ entradas manuales descuenta el embargo más de una vez (REPRODUCCIÓN, sin código de producto).

Mecanismo (hr_payroll/models/hr_payslip.py del servidor v18, líneas 957-990 y la regla CO_EMBARGO de
``data/hr_payroll_structure_data.xml:1300-1325``):
- La regla CO_EMBARGO se activa si hay una entrada ``CO_EMBARGO`` (tipo ``input_co_embargo_manual``, «Ajuste Manual (Override RRHH)»)
  o asignaciones de embargo abiertas. Con 2+ entradas de ese tipo el motor entra a la rama de entradas múltiples
  (``rule.code in localdict['same_type_input_lines']``, :957) y EVALÚA LA REGLA UNA VEZ POR ENTRADA (:958-960).
- Cada evaluación ejecuta ``result = -payslip._ne_embargos_calcular(_salario_neto, _smmlv, _manual)``. Esa función devuelve el total que
  reparten las ASIGNACIONES abiertas (``hr_payslip.py:369-410``); la entrada manual solo se compara contra ese total (si lo excede, error)
  y NO se suma. Por eso cada entrada produce una línea con el embargo COMPLETO de las asignaciones.
- Entre una evaluación y la siguiente ``categories['DEDU']`` ya incluye la línea anterior (:969-970), así que ``_salario_neto`` baja y
  se recalcula con otra base.
- Además ``_ne_guardar_reparto`` REEMPLAZA el reparto por tercero en cada evaluación (``hr_payslip.py:353-359``): el reparto queda con el
  importe de la ÚLTIMA evaluación, no con la suma de las líneas.

Aritmética a mano (alimentos con valor fijo 200.000, salario 10.000.000, quincena 1-15 de septiembre 2026; neto de la base ~4.600.000):
  tope alimentos = 50 % del neto ~ 2.300.000 > 200.000; espacio = neto - SMMLV ~ 2.850.000 > 200.000 -> aplicado = 200.000.
  Correcto: embargo descontado UNA vez = -200.000.   Con 2 entradas manuales de 100.000: 2 líneas de -200.000 = -400.000.

ESTADO: afirma el comportamiento CORRECTO y se espera que FALLE con el código actual (.277). NO está importada en ``tests/__init__.py``
a propósito. NO ejecutada en Odoo. El diseño de la corrección (qué significa tener 2 entradas manuales de CO_EMBARGO: ¿se suman como
override?, ¿se rechaza la segunda?) es decisión de Tech Lead/David: NO se corrige en .277.
"""

from datetime import date

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import float_compare


@tagged('post_install', '-at_install')
class TestEmbargoEntradasMultiples(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U',
            'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_clase_riesgo': '1', 'l10n_co_ne_febrero_modo': 'real',
            'l10n_co_ne_redondeo_dias': 'DOWN', 'name': 'Compañía de Prueba Embargo Múltiple'})
        cls.structure_type = cls.env['hr.payroll.structure.type'].create({
            'name': 'Prueba Estructura Embargo Múltiple', 'country_id': cls.env.ref('base.co').id})
        cls.est_general = cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
        cls.juzgado = cls.env['res.partner'].create({'name': 'Juzgado Embargo Múltiple'})

    def _recibo(self, name):
        empleado = self.env['hr.employee'].create({
            'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00', 'name': name,
            'company_id': self.company.id, 'l10n_co_ne_payment_method': '10'})
        contrato = self.env['hr.contract'].create({
            'l10n_co_ne_contract_type': '2', 'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00',
            'name': 'Contrato %s' % name, 'employee_id': empleado.id, 'company_id': self.company.id,
            'structure_type_id': self.structure_type.id, 'wage': 10000000.0, 'date_start': date(2024, 3, 1),
            'state': 'open'})
        self.env['hr.salary.attachment'].create({
            'description': 'Embargo alimentos %s' % name, 'employee_ids': [(6, 0, [empleado.id])],
            'company_id': self.company.id,
            'other_input_type_id': self.env.ref('l10n_co_nomina_electronica.input_l10n_co_embargo_alimentos').id,
            'monthly_amount': 200000.0, 'l10n_co_embargo_porcentaje': 0.0, 'date_start': '2026-01-01',
            'no_end_date': True, 'l10n_co_partner_id': self.juzgado.id})
        return self.env['hr.payslip'].create({
            'name': name, 'employee_id': empleado.id, 'contract_id': contrato.id, 'company_id': self.company.id,
            'struct_id': self.est_general.id, 'date_from': date(2026, 9, 1), 'date_to': date(2026, 9, 15)})

    def _manuales(self, recibo, *montos):
        for monto in montos:
            self.env['hr.payslip.input'].create({
                'payslip_id': recibo.id,
                'input_type_id': self.env.ref('l10n_co_nomina_electronica.input_co_embargo_manual').id,
                'code': 'CO_EMBARGO', 'amount': monto})

    def _lineas_embargo(self, recibo):
        return recibo.line_ids.filtered(lambda l: l.code == 'CO_EMBARGO')

    def test_control_una_entrada_manual_descuenta_el_embargo_una_vez(self):
        """Control (rama simple, :991-998): con UNA entrada manual de 100.000 el embargo es el de la asignación: -200.000."""
        recibo = self._recibo('Embargo Control')
        self._manuales(recibo, 100000.0)
        recibo.compute_sheet()
        lineas = self._lineas_embargo(recibo)
        self.assertEqual(len(lineas), 1)
        self.assertEqual(float_compare(lineas.total, -200000.0, precision_digits=2), 0)

    def test_premisa_dos_entradas_manuales_generan_dos_lineas(self):
        """Premisa del mecanismo: una línea por entrada (:972-986)."""
        recibo = self._recibo('Embargo Premisa')
        self._manuales(recibo, 100000.0, 100000.0)
        recibo.compute_sheet()
        self.assertEqual(len(self._lineas_embargo(recibo)), 2, 'Se esperaba UNA línea por entrada (hr_payslip.py:972-986).')

    def test_dos_entradas_manuales_descuentan_el_embargo_una_sola_vez(self):
        """DEBE FALLAR con el código actual: 2 líneas de -200.000 = -400.000 (el embargo de la asignación es 200.000)."""
        recibo = self._recibo('Embargo Doble')
        self._manuales(recibo, 100000.0, 100000.0)
        recibo.compute_sheet()
        total = sum(self._lineas_embargo(recibo).mapped('total'))
        self.assertEqual(
            float_compare(total, -200000.0, precision_digits=2), 0,
            'El embargo se descontó %.2f; el de la asignación es 200000.00 (una sola vez).' % -total)

    def test_el_reparto_por_tercero_coincide_con_las_lineas_de_embargo(self):
        """DEBE FALLAR con el código actual: el reparto queda con la ÚLTIMA evaluación (200.000) y las líneas suman 400.000;
        el asiento por tercero y el recibo difieren."""
        recibo = self._recibo('Embargo Reparto')
        self._manuales(recibo, 100000.0, 100000.0)
        recibo.compute_sheet()
        lineas = -sum(self._lineas_embargo(recibo).mapped('total'))
        reparto = sum(self.env['l10n.co.payslip.tercero'].search([
            ('slip_id', '=', recibo.id), ('rule_code', '=', 'CO_EMBARGO')]).mapped('amount'))
        self.assertEqual(
            float_compare(lineas, reparto, precision_digits=2), 0,
            'Líneas de embargo %.2f frente a reparto por tercero %.2f' % (lineas, reparto))
