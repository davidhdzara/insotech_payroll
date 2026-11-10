# -*- coding: utf-8 -*-
"""La Cantidad de cada linea del recibo es la unidad real (dias u horas), no 1,00.

Patron nativo: result = valor unitario, result_qty = unidades; total = result x qty x rate / 100,
igual al de antes. Los valores esperados se calculan a mano con los parametros de
data/l10n_co_rule_parameters_data.xml (2026: SMMLV 1.750.905, auxilio 249.095, 360 dias/anio,
210 horas mensuales desde 2026-07-15, factor HED 1,25, salud/pension 4%, intereses 12%).
Quincena 1-15 de septiembre de 2026 = 15 dias comerciales.
"""

import importlib.util
import os
from datetime import date

from odoo.tests.common import TransactionCase

HORAS_MENSUALES = 210.0
FACTOR_HED = 1.25


class TestCantidadReal(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Compañía de Prueba Cantidad Real'})
        cls.structure_type = cls.env['hr.payroll.structure.type'].create({
            'name': 'Prueba Estructura Cantidad', 'country_id': cls.env.ref('base.co').id})
        ref = cls.env.ref
        cls.est_general = ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
        cls.est_liquidacion = ref('l10n_co_nomina_electronica.hr_payroll_structure_co_liquidacion')
        cls.est_prima = ref('l10n_co_nomina_electronica.hr_payroll_structure_co_prima')

    def _contrato(self, name, wage, date_start=date(2024, 3, 1), contract_type='2'):
        employee = self.env['hr.employee'].create({
            'name': name, 'company_id': self.company.id, 'l10n_co_ne_payment_method': '10'})
        contract = self.env['hr.contract'].create({
            'name': 'Contrato %s' % name, 'employee_id': employee.id,
            'company_id': self.company.id, 'structure_type_id': self.structure_type.id,
            'wage': wage, 'date_start': date_start, 'state': 'open',
            'l10n_co_ne_contract_type': contract_type})
        return employee, contract

    def _recibo(self, estructura, name, wage, date_from, date_to, date_start=date(2024, 3, 1),
                contract_type='2', cause=False):
        employee, contract = self._contrato(name, wage, date_start, contract_type)
        vals = {
            'name': name, 'employee_id': employee.id, 'contract_id': contract.id,
            'company_id': self.company.id, 'struct_id': estructura.id,
            'date_from': date_from, 'date_to': date_to}
        if cause:
            vals['l10n_co_ne_liquidacion_cause'] = cause
        return self.env['hr.payslip'].create(vals)

    def _quincena(self, name, wage=3000000.0):
        return self._recibo(self.est_general, name, wage, date(2026, 9, 1), date(2026, 9, 15))

    def _input(self, slip, xmlid, code, amount):
        self.env['hr.payslip.input'].create({
            'payslip_id': slip.id, 'input_type_id': self.env.ref(xmlid).id,
            'code': code, 'amount': amount})

    def _linea(self, slip, code):
        linea = slip.line_ids.filtered(lambda l: l.code == code)
        self.assertTrue(linea, 'La regla %s no generó línea.' % code)
        return linea

    def test_basico_quincenal_cantidad_15_dias(self):
        slip = self._quincena('Basico')
        slip.compute_sheet()
        linea = self._linea(slip, 'CO_BASICO')
        self.assertEqual(linea.quantity, 15.0)
        self.assertAlmostEqual(linea.amount, 3000000.0 / 30, places=2)
        self.assertAlmostEqual(linea.total, 1500000.0, places=2)
        # Misma fuente de dias que DiasTrabajados del XML.
        self.assertEqual(linea.quantity, slip._ne_dias_pagables())

    def test_auxilio_de_transporte_quincenal_cantidad_15_dias(self):
        slip = self._quincena('Auxilio', wage=1500000.0)
        slip.compute_sheet()
        linea = self._linea(slip, 'CO_AUX_TRANS')
        self.assertEqual(linea.quantity, 15.0)
        self.assertAlmostEqual(linea.total, 249095.0 / 30 * 15, places=2)

    def test_hora_extra_cantidad_son_las_horas_del_input(self):
        slip = self._quincena('HoraExtra')
        self._input(slip, 'l10n_co_nomina_electronica.input_co_hed', 'CO_HED', 5.0)
        slip.compute_sheet()
        linea = self._linea(slip, 'CO_HED')
        self.assertEqual(linea.quantity, 5.0)
        valor_hora = 3000000.0 / HORAS_MENSUALES
        self.assertAlmostEqual(linea.amount, valor_hora * FACTOR_HED, places=2)
        self.assertAlmostEqual(linea.total, valor_hora * FACTOR_HED * 5, places=2)

    def test_xml_de_horas_extra_cantidad_decimal_y_porcentaje_de_la_tabla(self):
        slip = self._quincena('XmlHoras')
        self._input(slip, 'l10n_co_nomina_electronica.input_co_hed', 'CO_HED', 5.5)
        slip.compute_sheet()
        devengados = {}
        slip._dev_horas_extra(slip._group_lines_by_concept(), devengados)
        item = devengados['HEDs'][0]
        self.assertEqual(item['Cantidad'], '5.50')      # xsd:decimal en el XSD v1.0.6
        self.assertEqual(item['Porcentaje'], '25.00')   # tabla 5.5.5: HED 25 (factor 1,25)

    def test_deduccion_de_salud_importe_ibc_y_tasa_4(self):
        slip = self._quincena('Salud')
        slip.compute_sheet()
        linea = self._linea(slip, 'CO_SALUD_EMP')
        ibc = self._linea(slip, 'CO_IBC_SP').total
        self.assertEqual(linea.quantity, 1.0)
        self.assertAlmostEqual(linea.rate, 4.0, places=4)
        self.assertAlmostEqual(linea.amount, -ibc, places=2)
        self.assertAlmostEqual(linea.total, -ibc * 0.04, places=2)

    def test_incapacidad_comun_cantidad_dias_y_total_igual(self):
        slip = self._quincena('Incapacidad')
        self._input(slip, 'l10n_co_nomina_electronica.input_co_inc_comun', 'CO_INC_COMUN', 10.0)
        slip.compute_sheet()
        linea = self._linea(slip, 'CO_INC_COMUN')
        self.assertEqual(linea.quantity, 10.0)
        # 66,67% del valor dia en todos los dias (empleador 2 dias y EPS 3-90 al mismo %).
        self.assertAlmostEqual(linea.total, 3000000.0 / 30 * 0.6667 * 10, places=2)

    def test_liquidacion_cantidad_en_dias_de_cada_concepto(self):
        """Retiro 2026-08-15, ingreso 2024-03-01, $3.000.000: cesantias 227 dias del anio,
        prima 46 dias del semestre; salarios = dias pagables; el total no cambia."""
        slip = self._recibo(self.est_liquidacion, 'LiqCantidad', 3000000.0, date(2024, 3, 1),
                            date(2026, 8, 15))
        slip.compute_sheet()
        base = 3000000.0 + 249095.0
        ces = self._linea(slip, 'CO_LIQ_CESANTIAS')
        self.assertEqual(ces.quantity, 227.0)
        self.assertAlmostEqual(ces.total, base * 227 / 360, places=2)
        self.assertEqual(self._linea(slip, 'CO_LIQ_INT_CES').quantity, 227.0)
        prima = self._linea(slip, 'CO_LIQ_PRIMA')
        self.assertEqual(prima.quantity, 46.0)
        self.assertAlmostEqual(prima.total, base * 46 / 360, places=2)
        self.assertEqual(self._linea(slip, 'CO_LIQ_SALARIOS').quantity, slip._ne_dias_pagables())

    def test_liquidacion_indemnizacion_cantidad_son_los_dias_de_indemnizacion(self):
        """$15.000.000, ingreso 2024-03-01, retiro 2026-08-15 (898 dias = 2,494 anios): 30 dias
        el primer anio + 20 por cada anio adicional."""
        slip = self._recibo(self.est_liquidacion, 'LiqIndemn', 15000000.0, date(2024, 3, 1),
                            date(2026, 8, 15), cause='sin_justa_causa')
        slip.compute_sheet()
        linea = self._linea(slip, 'CO_LIQ_INDEMNIZACION')
        anos = 898 / 360.0
        dias = 30 + 20 * (anos - 1)
        self.assertAlmostEqual(linea.quantity, dias, places=6)
        self.assertAlmostEqual(linea.total, 15000000.0 / 30 * dias, places=2)

    def test_prima_semestral_cantidad_son_los_dias_del_semestre(self):
        slip = self._recibo(self.est_prima, 'PrimaCantidad', 3000000.0, date(2026, 7, 1),
                            date(2026, 12, 31))
        slip.compute_sheet()
        linea = self._linea(slip, 'CO_PRIMA_VALOR')
        self.assertEqual(linea.quantity, 180.0)   # semestre completo = mitad del anio comercial
        base = self._linea(slip, 'CO_PRIMA_BASE').total
        self.assertAlmostEqual(linea.total, base * 180 / 360, places=2)

    def test_migracion_periodo_propio_a_schedule_pay_y_borra_la_columna(self):
        _empleado, contrato = self._contrato('Migracion', 3000000.0)
        cr = self.env.cr
        cr.execute("ALTER TABLE hr_contract ADD COLUMN l10n_co_payroll_period varchar")
        cr.execute("UPDATE hr_contract SET schedule_pay='monthly', l10n_co_payroll_period='15' "
                   "WHERE id=%s", (contrato.id,))
        ruta = os.path.join(os.path.dirname(__file__), '..', 'migrations', '18.0.3.0.152',
                            'post-periodo_a_schedule_pay.py')
        spec = importlib.util.spec_from_file_location('mig_periodo', ruta)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        modulo.migrate(cr, '18.0.3.0.151')
        contrato.invalidate_recordset(['schedule_pay'])
        self.assertEqual(contrato.schedule_pay, 'semi-monthly')
        cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name='hr_contract' "
                   "AND column_name='l10n_co_payroll_period'")
        self.assertFalse(cr.fetchone())
