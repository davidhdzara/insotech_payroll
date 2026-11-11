# -*- coding: utf-8 -*-
"""Avisos del panel de Nomina (.180): parametros (SMMLV, UVT, auxilio) y configuracion de retencion
del anio en curso y, desde noviembre, del siguiente. Se evalua el codigo del aviso con una fecha de
hoy fija. Valor de cada caso a mano (3 parametros por anio; 1 aviso por compania sin configuracion)."""

import datetime

from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval

CODES = ('l10n_co_smmlv', 'l10n_co_uvt', 'l10n_co_aux_transporte')


class TestAvisoAnioSiguiente(TransactionCase):
    def _cuenta(self, xmlid, hoy, companias=None):
        class FechaFija:
            """Como `date` en el codigo del aviso: today() fijo y date(a, m, d) real."""
            @staticmethod
            def today():
                return hoy

            def __call__(self, *args):
                return datetime.date(*args)

        codigo = self.env.ref('l10n_co_nomina_electronica.%s' % xmlid).evaluation_code
        entorno = self.env
        if companias:
            entorno = self.env(context=dict(self.env.context, allowed_company_ids=companias.ids))
        locales = {}
        safe_eval(codigo, {'self': entorno['hr.payslip'], 'date': FechaFija()}, locales,
                  mode='exec', nocopy=True)
        return locales.get('warning_count', 0)

    def _valores(self, fecha):
        for code in CODES:
            parametro = self.env['hr.rule.parameter'].search([('code', '=', code)], limit=1)
            self.env['hr.rule.parameter.value'].create({
                'rule_parameter_id': parametro.id, 'parameter_value': '1', 'date_from': fecha})

    def test_parametro_del_mes_de_aviso_es_11(self):
        valor = self.env['hr.rule.parameter']._get_parameter_from_code(
            'l10n_co_aviso_anio_siguiente_desde_mes', '2026-11-01')
        self.assertEqual(valor, 11)

    def test_antes_de_noviembre_solo_se_evalua_el_anio_en_curso(self):
        # 2026 ya trae SMMLV, UVT y auxilio (1-ene-2026): sin avisos
        self.assertEqual(self._cuenta(
            'hr_payroll_dashboard_warning_co_params_ano_actual', datetime.date(2026, 10, 15)), 0)

    def test_desde_noviembre_avisa_los_tres_parametros_del_anio_siguiente(self):
        self.assertEqual(self._cuenta(
            'hr_payroll_dashboard_warning_co_params_ano_actual', datetime.date(2026, 11, 2)), 3)

    def test_con_los_tres_cargados_para_2027_no_hay_aviso(self):
        self._valores(datetime.date(2027, 1, 1))
        self.assertEqual(self._cuenta(
            'hr_payroll_dashboard_warning_co_params_ano_actual', datetime.date(2026, 11, 2)), 0)

    def test_un_valor_de_finales_de_diciembre_cuenta_para_el_anio_siguiente(self):
        """El auxilio de 2025 quedo fijado el 25-dic: el valor 'del anio Y' empieza desde el
        1-dic de Y-1. Un valor del 26-dic-2026 cubre 2027."""
        self._valores(datetime.date(2026, 12, 26))
        self.assertEqual(self._cuenta(
            'hr_payroll_dashboard_warning_co_params_ano_actual', datetime.date(2026, 11, 2)), 0)

    def test_retencion_avisa_por_compania_sin_configuracion_del_anio_siguiente(self):
        Config = self.env['l10n.co.retefuente.uvt']
        datos = {'country_id': self.env.ref('base.co').id, 'l10n_co_pila_clase_riesgo': '1',
                 'l10n_co_ne_febrero_modo': 'real', 'l10n_co_ne_redondeo_dias': 'DOWN'}
        a = self.env['res.company'].create({'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U', 'name': 'Empresa A Aviso', **datos})
        b = self.env['res.company'].create({'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U', 'name': 'Empresa B Aviso', **datos})
        for anio, compania in (('2026', a), ('2027', a), ('2026', b)):
            Config.create({'year': anio, 'company_id': compania.id, 'procedure': '1'})
        # A completa para 2026 y 2027; B solo 2026 -> falta B-2027 = 1 aviso
        self.assertEqual(self._cuenta(
            'hr_payroll_dashboard_warning_co_retefuente_config', datetime.date(2026, 11, 2),
            a | b), 1)
        # antes de noviembre solo cuenta 2026: sin avisos
        self.assertEqual(self._cuenta(
            'hr_payroll_dashboard_warning_co_retefuente_config', datetime.date(2026, 10, 2),
            a | b), 0)
