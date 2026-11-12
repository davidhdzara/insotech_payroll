# -*- coding: utf-8 -*-
"""TiempoLaborado 360/30 (Anexo Tecnico DIAN §8.3.1, p.249; doc 53 §21.1). Funcion pura, valores a mano.
NO esta conectada al XML (D19 pendiente)."""

from datetime import date

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.l10n_co_nomina_electronica.services.dian_utils import (
    compute_worked_time, compute_worked_time_360 as f)


@tagged('post_install', '-at_install')
class TestTiempoLaborado360(TransactionCase):

    def test_ejemplo_oficial_anexo(self):
        # 5 anios + 3 meses + 18 dias = 5*360 + 3*30 + 18 = 1908
        self.assertEqual(f(date(2018, 1, 1), date(2023, 4, 19), inclusive=False), 1908)

    def test_caso_marzo_2024_a_marzo_2026(self):
        # 2 anios + 0 meses + 30 dias = 720 + 0 + 30 = 750 (el calendario daria 760)
        self.assertEqual(f(date(2024, 3, 1), date(2026, 3, 31), inclusive=False), 750)
        self.assertEqual(compute_worked_time(date(2024, 3, 1), date(2026, 3, 31)), 760)

    def test_inclusivo_suma_un_dia(self):
        # 2024-03-01 -> 2026-03-31 inclusivo: hasta 2026-04-01 = 2 anios + 1 mes + 0 dias = 750
        self.assertEqual(f(date(2024, 3, 1), date(2026, 3, 31), inclusive=True), 750)
        # 01-ene a 31-ene: inclusivo = 1 mes = 30; no inclusivo = 0 meses + 30 dias = 30
        self.assertEqual(f(date(2026, 1, 1), date(2026, 1, 31), inclusive=True), 30)
        self.assertEqual(f(date(2026, 1, 1), date(2026, 1, 31), inclusive=False), 30)

    def test_minimo_uno(self):
        self.assertEqual(f(date(2026, 3, 1), date(2026, 3, 1), inclusive=False), 1)

    def test_cadenas_y_vacios(self):
        self.assertEqual(f('2026-01-01', '2026-01-16', inclusive=False), 15)
        self.assertEqual(f(None, date(2026, 1, 1), inclusive=False), 0)
