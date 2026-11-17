# -*- coding: utf-8 -*-
"""R-2d (doc 59 §25): el porcentaje fijo del Procedimiento 2 promedia MESES calendario, no recibos.

Antes ``action_calculate_retention_procedure2`` tomaba los últimos 12 RECIBOS y los llamaba «meses»: con pagos quincenales eran los
últimos 6 meses y el promedio de ingreso salía de medias quincenas. Ahora cada recibo guarda su devengado real
(``CO_RETEFUENTE_BASE_GROSS``, aditivo) y su IBC (``CO_RETEFUENTE_BASE_IBC``), se suman por mes de ``date_to`` (regla D4) y se promedian
hasta 12 meses. Texto normativo (Art. 384 y 386 ET) NO VERIFICADO: no está en el repositorio. Valor esperado calculado aparte: promedio
mensual 12.000.000 con IBC 12.000.000 -> base 158,0937 UVT, retención 12,2662 UVT, porcentaje fijo 7,7588 %.
"""

from datetime import date
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from .common_documento import DocumentoFixture

PORCENTAJE_12M = 7.7588


@tagged('post_install', '-at_install')
class TestRetefuenteProcedimiento2Meses(DocumentoFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture_documento('Compañía Procedimiento 2 Meses')
        cls.env['l10n.co.retefuente.uvt'].create({'year': '2026', 'company_id': cls.company.id, 'procedure': '1'})

    def _contrato(self):
        type(self).n += 1
        empleado = self.env['hr.employee'].create({
            'name': 'Empleado Proc2 %s' % self.n, 'company_id': self.company.id, 'identification_id': '1020304050',
            'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00', 'l10n_co_ne_payment_method': '10'})
        return self.env['hr.contract'].create({
            'name': 'Contrato Proc2 %s' % self.n, 'employee_id': empleado.id, 'company_id': self.company.id,
            'structure_type_id': self.structure_type.id, 'l10n_co_ne_contract_type': '2',
            'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00', 'wage': 12000000.0,
            'date_start': date(2024, 1, 1), 'state': 'open', 'l10n_co_ne_retention_procedure': '2'})

    def _recibo(self, contrato, desde, hasta, devengado, estado='paid'):
        type(self).n += 1
        recibo = self.env['hr.payslip'].create({
            'name': 'Recibo Proc2 %s' % self.n, 'employee_id': contrato.employee_id.id, 'contract_id': contrato.id,
            'company_id': self.company.id, 'struct_id': self.struct.id, 'date_from': desde, 'date_to': hasta})
        recibo.write({'state': estado})
        for codigo in ('CO_RETEFUENTE_BASE_GROSS', 'CO_RETEFUENTE_BASE_IBC'):
            regla = self.env['hr.salary.rule'].search([('code', '=', codigo), ('struct_id', '=', self.struct.id)], limit=1)
            self.assertTrue(regla, codigo)
            self.env['hr.payslip.line'].create({
                'slip_id': recibo.id, 'salary_rule_id': regla.id, 'code': codigo, 'name': codigo,
                'contract_id': contrato.id, 'employee_id': contrato.employee_id.id,
                'quantity': 1.0, 'rate': 100.0, 'amount': devengado, 'total': devengado})
        return recibo

    def _calcular(self, contrato, hoy):
        with patch('odoo.fields.Date.context_today', return_value=hoy):
            contrato.action_calculate_retention_procedure2()
        return contrato.l10n_co_ne_retention_procedure2_ids

    def test_tres_meses_quincenales_son_tres_meses_no_seis_recibos(self):
        contrato = self._contrato()
        for mes, ultimo in ((3, 31), (4, 30), (5, 31)):
            self._recibo(contrato, date(2026, mes, 1), date(2026, mes, 15), 6000000.0)
            self._recibo(contrato, date(2026, mes, 16), date(2026, mes, ultimo), 6000000.0)
        proc2 = self._calcular(contrato, date(2026, 6, 15))
        self.assertEqual(len(proc2), 1)
        self.assertEqual(proc2.semester_start, date(2026, 7, 1))
        self.assertEqual(proc2.months_considered, 3)                            # antes: 6 («meses» = recibos)
        self.assertAlmostEqual(proc2.average_gross, 12000000.0, delta=0.01)      # antes: 6.000.000 (media quincena)
        self.assertAlmostEqual(proc2.average_ibc, 12000000.0, delta=0.01)
        self.assertAlmostEqual(proc2.fixed_percentage, PORCENTAJE_12M, delta=0.001)

    def test_un_periodo_que_cruza_de_mes_cuenta_en_el_mes_de_date_to(self):
        """El recibo 21-mar -> 5-abr (5/20) suma al mes de abril, no al de marzo (regla D4)."""
        contrato = self._contrato()
        self._recibo(contrato, date(2026, 2, 21), date(2026, 3, 5), 6000000.0)
        self._recibo(contrato, date(2026, 3, 6), date(2026, 3, 20), 6000000.0)
        self._recibo(contrato, date(2026, 3, 21), date(2026, 4, 5), 6000000.0)
        self._recibo(contrato, date(2026, 4, 6), date(2026, 4, 20), 6000000.0)
        proc2 = self._calcular(contrato, date(2026, 6, 15))
        self.assertEqual(proc2.months_considered, 2)                             # marzo y abril
        self.assertAlmostEqual(proc2.average_gross, 12000000.0, delta=0.01)

    def test_solo_se_promedian_los_ultimos_12_meses_y_se_ignoran_borradores(self):
        contrato = self._contrato()
        self._recibo(contrato, date(2025, 4, 1), date(2025, 4, 30), 1000000.0)      # mes 14 hacia atrás: fuera
        self._recibo(contrato, date(2025, 5, 1), date(2025, 5, 31), 1000000.0)      # mes 13: fuera
        for anio, mes, ultimo in ((2025, 6, 30), (2025, 7, 31), (2025, 8, 31), (2025, 9, 30), (2025, 10, 31),
                                  (2025, 11, 30), (2025, 12, 31), (2026, 1, 31), (2026, 2, 28), (2026, 3, 31),
                                  (2026, 4, 30), (2026, 5, 31)):
            self._recibo(contrato, date(anio, mes, 1), date(anio, mes, ultimo), 12000000.0)
        self._recibo(contrato, date(2026, 5, 1), date(2026, 5, 31), 99000000.0, estado='draft')   # borrador: no cuenta
        proc2 = self._calcular(contrato, date(2026, 6, 15))
        self.assertEqual(proc2.months_considered, 12)
        self.assertAlmostEqual(proc2.average_gross, 12000000.0, delta=0.01)

    def test_los_recibos_pagados_cuentan_igual_que_los_hechos(self):
        contrato = self._contrato()
        self._recibo(contrato, date(2026, 4, 1), date(2026, 4, 30), 12000000.0, estado='done')
        self._recibo(contrato, date(2026, 5, 1), date(2026, 5, 31), 12000000.0, estado='paid')
        self.assertEqual(self._calcular(contrato, date(2026, 6, 15)).months_considered, 2)
