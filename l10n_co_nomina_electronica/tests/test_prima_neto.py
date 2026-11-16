# -*- coding: utf-8 -*-
"""Prima de servicios: CO_PRIMA_BASE es un acumulador interno, no un devengado.

Hallazgo de QA en pantalla (recibo de prima 8571): CO_PRIMA_NETO = BASE + VALOR - deducciones
= 2.991.678,70, porque la base (salario + auxilio) estaba en PREST y sumaba al neto; ademas el
nodo Primas del XML sumaba la Cantidad de las dos lineas (1 + 180 = 181). Valores a mano:
$3.000.000 con auxilio 2026 (249.095) -> base 3.249.095; semestre completo de 180 dias ->
valor 3.249.095 x 180 / 360 = 1.624.547,50. Desde .164 sin salud ni pension (CST Art. 307).
"""

from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPrimaNeto(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U', 'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_clase_riesgo': '1', 'l10n_co_ne_febrero_modo': 'real', 'l10n_co_ne_redondeo_dias': 'DOWN', 'name': 'Compañía de Prueba Prima Neto'})
        cls.structure_type = cls.env['hr.payroll.structure.type'].create({
            'name': 'Prueba Estructura Prima', 'country_id': cls.env.ref('base.co').id})
        cls.est_prima = cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_prima')

    def _prima(self):
        employee = self.env['hr.employee'].create({'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00', 
            'name': 'Prima Neto', 'company_id': self.company.id,
            'l10n_co_ne_payment_method': '10'})
        contract = self.env['hr.contract'].create({'l10n_co_ne_contract_type': '2', 'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00', 
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

    def test_neto_es_valor_menos_retencion_sin_salud_ni_pension_ni_la_base(self):
        """.164 (CST Art. 307): la prima no es salario ni factor salarial -> sin descuento de
        salud ni pension del empleado. Neto = valor - retencion en la fuente (que se conserva)."""
        slip = self._prima()
        valor = self._total(slip, 'CO_PRIMA_VALOR')
        self.assertAlmostEqual(valor, 1624547.50, delta=0.01)
        self.assertFalse(slip.line_ids.filtered(
            lambda l: l.code in ('CO_PRIMA_SALUD', 'CO_PRIMA_PENSION')))
        retencion = self._total(slip, 'CO_PRIMA_RETE')  # 0 si no hay configuracion de UVT
        self.assertLessEqual(retencion, 0.0)
        self.assertAlmostEqual(self._total(slip, 'CO_PRIMA_NETO'), valor + retencion, delta=0.01)

    def test_reglas_de_salud_y_pension_de_la_prima_estan_inactivas(self):
        for code in ('CO_PRIMA_SALUD', 'CO_PRIMA_PENSION'):
            regla = self.env['hr.salary.rule'].with_context(active_test=False).search(
                [('code', '=', code), ('struct_id', '=', self.est_prima.id)])
            self.assertTrue(regla, 'Debe conservarse el registro de %s (historial).' % code)
            self.assertFalse(regla.active)

    def test_xml_de_la_prima_no_trae_descuento_de_salud_ni_pension(self):
        slip = self._prima()
        deducciones = slip._build_deducciones(slip._group_lines_by_concept())
        self.assertNotIn('Salud', deducciones)
        self.assertNotIn('FondoPension', deducciones)

    def test_la_base_no_es_un_concepto_visible_ni_va_a_dian(self):
        slip = self._prima()
        base = slip.line_ids.filtered(lambda l: l.code == 'CO_PRIMA_BASE')
        self.assertAlmostEqual(base.total, 3249095.0, delta=0.01)   # el acumulador sigue calculandose
        self.assertFalse(base.salary_rule_id.appears_on_payslip)
        self.assertFalse(base.salary_rule_id.l10n_co_ne_dian_concept)
        self.assertNotIn('CO_PRIMA_BASE', slip._ne_pdf_lineas().mapped('code'))

    def test_xml_primas_cantidad_180_y_pago_del_valor(self):
        slip = self._prima()
        devengados = {}
        slip._dev_prestaciones(slip._group_lines_by_concept(), devengados)
        self.assertEqual(devengados['Primas']['Cantidad'], '180')
        self.assertEqual(devengados['Primas']['Pago'], '1624547.50')

    # ── Retención en la fuente de la prima (.164): base SIN descontar salud/pensión ──────────
    # UVT 2026 = 52.374; tabla Art. 383 ET; renta exenta 25 % (tope 790 UVT anuales / 12 = 3.447.955).
    # Sin aportes: subtotal = valor de la prima; base = valor − 25 % del valor.
    def _prima_con_retencion(self, wage, contrato_extra=None, antes_de_calcular=None):
        self.env['l10n.co.retefuente.uvt'].create({
            'year': '2026', 'company_id': self.company.id, 'procedure': '1'})
        employee = self.env['hr.employee'].create({'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00', 
            'name': 'Prima Rete %s' % wage, 'company_id': self.company.id,
            'l10n_co_ne_payment_method': '10'})
        contract = self.env['hr.contract'].create({'l10n_co_ne_contract_type': '2', 'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00', 
            'name': 'Contrato Prima Rete', 'employee_id': employee.id,
            'company_id': self.company.id, 'structure_type_id': self.structure_type.id,
            'wage': wage, 'date_start': date(2024, 3, 1), 'state': 'open', **(contrato_extra or {})})
        if antes_de_calcular:
            antes_de_calcular(contract)
        slip = self.env['hr.payslip'].create({
            'name': 'Prima Rete', 'employee_id': employee.id, 'contract_id': contract.id,
            'company_id': self.company.id, 'struct_id': self.est_prima.id,
            'date_from': date(2026, 7, 1), 'date_to': date(2026, 12, 31)})
        slip.compute_sheet()
        return slip

    def test_prima_bajo_el_umbral_no_tiene_retencion(self):
        """Prima 1.624.547,50: base = 1.218.410,63 = 23,26 UVT (< 95 UVT) -> retención 0."""
        slip = self._prima_con_retencion(3000000.0)
        self.assertAlmostEqual(self._total(slip, 'CO_PRIMA_VALOR'), 1624547.50, delta=0.01)
        self.assertEqual(self._total(slip, 'CO_PRIMA_RETE'), 0.0)

    def test_prima_de_6_millones_sigue_bajo_el_umbral(self):
        """Prima 6.000.000: renta exenta 1.500.000, base 4.500.000 = 85,92 UVT < 95 -> 0
        (con el cálculo anterior, que restaba 4 %+4 %, la base era 79,05 UVT: también 0)."""
        slip = self._prima_con_retencion(12000000.0)
        self.assertAlmostEqual(self._total(slip, 'CO_PRIMA_VALOR'), 6000000.0, delta=0.01)
        self.assertEqual(self._total(slip, 'CO_PRIMA_RETE'), 0.0)

    def test_prima_de_10_millones_retencion_en_el_tramo_del_19_por_ciento(self):
        """Prima 10.000.000: renta exenta 25 % = 2.500.000; base 7.500.000 / 52.374 = 143,2008
        UVT -> tramo >95 hasta 150 (19 %): (143,2008 − 95) × 0,19 = 9,1582 UVT x 52.374 =
        479.649 (el cálculo anterior, con aportes de 800.000, daba 365.649)."""
        slip = self._prima_con_retencion(20000000.0)
        valor = self._total(slip, 'CO_PRIMA_VALOR')
        self.assertAlmostEqual(valor, 10000000.0, delta=0.01)
        self.assertAlmostEqual(self._total(slip, 'CO_PRIMA_RETE'), -479649.0, delta=0.01)
        self.assertAlmostEqual(self._total(slip, 'CO_PRIMA_NETO'), valor - 479649.0, delta=0.01)

    def test_prima_de_20_millones_retencion_en_el_tramo_del_28_por_ciento(self):
        """Prima 20.000.000: el 25 % (5.000.000) supera el tope 790/12 UVT = 3.447.955 -> exenta
        3.447.955; base 16.552.045 / 52.374 = 316,0355 UVT -> tramo >150 hasta 360 (28 %):
        (316,0355 − 150) × 0,28 + 10 = 56,4899 UVT x 52.374 = 2.958.605."""
        slip = self._prima_con_retencion(40000000.0)
        valor = self._total(slip, 'CO_PRIMA_VALOR')
        self.assertAlmostEqual(valor, 20000000.0, delta=0.01)
        self.assertAlmostEqual(self._total(slip, 'CO_PRIMA_RETE'), -2958605.0, delta=0.01)
        self.assertAlmostEqual(self._total(slip, 'CO_PRIMA_NETO'), valor - 2958605.0, delta=0.01)

    # ── R-2c (doc 59 §20.10 punto 1): el procedimiento de la prima sale del contrato ──
    def test_prima_de_un_contrato_en_procedimiento_2_usa_el_porcentaje_fijo_del_contrato(self):
        """Prima 10.000.000 (salario 20.000.000), contrato en Procedimiento 2 con 10 % fijo para el semestre que inicia el
        1-jul-2026: renta exenta 25 % = 2.500.000; base 7.500.000; retención = 7.500.000 x 10 % = 750.000. Antes la regla no
        pasaba el contrato y aplicaba la tabla del Art. 383 (479.649) sin importar el procedimiento del contrato."""
        def proc2(contrato):
            self.env['l10n.co.retefuente.procedure2'].create({
                'contract_id': contrato.id, 'semester_start': date(2026, 7, 1), 'fixed_percentage': 10.0})
        slip = self._prima_con_retencion(
            20000000.0, contrato_extra={'l10n_co_ne_retention_procedure': '2'}, antes_de_calcular=proc2)
        self.assertAlmostEqual(self._total(slip, 'CO_PRIMA_VALOR'), 10000000.0, delta=0.01)
        self.assertAlmostEqual(self._total(slip, 'CO_PRIMA_RETE'), -750000.0, delta=1.0)

    def test_la_prima_no_descuenta_la_pension_voluntaria_ni_el_afc_del_mes(self):
        """Mismo caso de 10.000.000 con voluntaria 1.000.000 + AFC 1.000.000 mensuales en el contrato: la retención de la prima
        no cambia (479.649); esos aportes son del salario del mes y no se descuentan además de la prima."""
        slip = self._prima_con_retencion(
            20000000.0, contrato_extra={'l10n_co_ne_pension_voluntaria': 1000000.0, 'l10n_co_ne_afc': 1000000.0})
        self.assertAlmostEqual(self._total(slip, 'CO_PRIMA_RETE'), -479649.0, delta=0.01)
