# -*- coding: utf-8 -*-
"""Frente 4, U3 (doc 57): hoja de conceptos de pago UGPP (formulario 7003): tipo de pago y clasificación con el texto
exacto de las listas de la plantilla, cuenta contable tomada de las cuentas de la regla (una sola fuente) y errores que
nombran las reglas. Nivel de verificación: plantilla y Guía leídas; la aceptación en Storm User solo con Storm real."""
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.l10n_co_nomina_electronica.models import l10n_co_nomina_ugpp as ugpp


@tagged('post_install', '-at_install')
class TestUgppConceptos(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Empresa Conceptos UGPP', 'country_id': cls.env.ref('base.co').id,
            'l10n_co_pila_clase_riesgo': '1', 'l10n_co_ne_febrero_modo': 'real', 'l10n_co_ne_redondeo_dias': 'DOWN'})
        cls.reporte = cls.env['l10n_co_nomina.ugpp'].create({
            'year': 2026, 'month': '9', 'date_from': date(2026, 9, 1), 'date_to': date(2026, 9, 30),
            'company_id': cls.company.id})
        Cuenta = cls.env['account.account'].with_company(cls.company)
        cls.gasto = Cuenta.create({'code': '510506', 'name': 'Sueldos UGPP', 'account_type': 'expense'})
        cls.por_pagar = Cuenta.create({'code': '250505', 'name': 'Salarios por pagar UGPP',
                                       'account_type': 'liability_current'})

    def _regla(self, codigo, tipo, clase=False, nombre=None, debito=None, credito=None):
        regla = self.env['hr.salary.rule'].create({
            'name': nombre or 'Regla %s' % codigo, 'code': codigo,
            'category_id': self.env['hr.salary.rule.category'].search([], limit=1).id,
            'struct_id': self.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina').id,
            'amount_select': 'fix', 'amount_fix': 0.0,
            'l10n_co_ugpp_payment_type': tipo, 'l10n_co_ugpp_non_salary_class': clase})
        regla = regla.with_company(self.company)
        if debito:
            regla.account_debit = debito
        if credito:
            regla.account_credit = credito
        return regla

    def test_cuenta_de_la_regla_debito_y_credito_separadas_por_punto_y_coma(self):
        regla = self._regla('U3_CTA_1', 'tp_salarial', debito=self.gasto, credito=self.por_pagar)
        self.assertEqual(self.reporte._ugpp_cuentas_regla(regla), '510506;250505')

    def test_si_debito_y_credito_son_la_misma_cuenta_no_se_repite(self):
        regla = self._regla('U3_CTA_2', 'tp_salarial', debito=self.gasto, credito=self.gasto)
        self.assertEqual(self.reporte._ugpp_cuentas_regla(regla), '510506')

    def test_la_fila_lleva_tipo_de_pago_y_clasificacion_con_el_texto_de_la_plantilla(self):
        salarial = self._regla('U3_FILA_1', 'tp_salarial', debito=self.gasto)
        no_salarial = self._regla('U3_FILA_2', 'tp_no_salarial', clase='contrato', debito=self.gasto)
        filas = self.reporte._ugpp_filas_conceptos(salarial | no_salarial)
        self.assertEqual(filas[0], [1, 'Regla U3_FILA_1', '510506', '1 TP SALARIAL', ''])
        self.assertEqual(filas[1], [2, 'Regla U3_FILA_2', '510506', '2 TP NO SALARIAL', '3 Contrato'])

    def test_clasificacion_solo_se_escribe_si_el_tipo_es_no_salarial(self):
        regla = self._regla('U3_FILA_3', 'tp_salarial', clase='contrato', debito=self.gasto)
        self.assertEqual(self.reporte._ugpp_filas_conceptos(regla)[0][4], '')

    def test_listas_cubren_todas_las_opciones_y_no_cargan_los_tipos_de_independientes(self):
        regla = self.env['hr.salary.rule']
        self.assertEqual(set(ugpp._UGPP_TIPO_PAGO), {k for k, _v in regla._fields['l10n_co_ugpp_payment_type'].selection})
        self.assertEqual(set(ugpp._UGPP_CLASE_NO_SALARIAL),
                         {k for k, _v in regla._fields['l10n_co_ugpp_non_salary_class'].selection})
        numeros = sorted(int(t.split()[0]) for t in ugpp._UGPP_TIPO_PAGO.values())
        self.assertEqual(numeros, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 16, 17])   # 12 a 15: independientes

    def test_el_nombre_no_lleva_los_caracteres_que_la_guia_prohibe(self):
        regla = self._regla('U3_NOM', 'tp_salarial', nombre='¡Bono! "A" & B #1 $ 5%', debito=self.gasto)
        self.assertEqual(self.reporte._ugpp_filas_conceptos(regla)[0][1], 'Bono A  B 1  5')

    def test_reglas_sin_cuenta_se_listan_juntas_en_un_solo_error(self):
        a = self._regla('U3_SIN_1', 'tp_salarial')
        b = self._regla('U3_SIN_2', 'tp_prestaciones')
        c = self._regla('U3_CON', 'tp_salarial', debito=self.gasto)
        with self.assertRaises(UserError) as exc:
            self.reporte._ugpp_filas_conceptos(a | b | c)
        mensaje = str(exc.exception)
        self.assertIn('Regla U3_SIN_1', mensaje)
        self.assertIn('Regla U3_SIN_2', mensaje)
        self.assertNotIn('Regla U3_CON', mensaje)
        self.assertIn('Empresa Conceptos UGPP', mensaje)

    def test_una_regla_no_salarial_exige_clasificacion(self):
        with self.assertRaisesRegex(ValidationError, 'clasificación'):
            self._regla('U3_NS', 'tp_no_salarial')

    def test_ya_no_existe_el_campo_de_cuentas_ugpp_aparte(self):
        self.assertNotIn('l10n_co_ugpp_accounts', self.env['hr.salary.rule']._fields)
