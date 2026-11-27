# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""H-F1-08 (doc 84/89): el valor del dia de la incapacidad comun sale del IBC del MES ANTERIOR al inicio de la incapacidad INICIAL de la cadena (Decreto 780 de 2016, art. 2.2.3.3.1, sustituido por el art. 1 del Decreto 2126 de 2023), el mismo en
todas sus prorrogas, no del sueldo actual en cada recibo. Sin IBC de ese mes, el sueldo con aviso. Misma funcion que las vacaciones (H-F1-11): ``_ne_ibc_mes_anterior``.

Valores a mano: sueldo 6.000.000 (valor dia 200.000), tramo del empleador y EPS (dias 1-90) al 66,67 %, piso diario 2026 = 1.750.905 / 30 = 58.363,5. Incapacidad lun 3 a mie 12 de agosto
(10 dias corridos). El «IBC del mes anterior» (julio) se fija con un recibo confirmado de solo CO_SS_BASE_IBC y CO_DIAS_SP (tests/ibc_previo.py)."""

from datetime import date

from odoo.tests.common import tagged

from . import test_incapacidad_tramo_prorroga as base
from .common_version import crear_aumento
from .ibc_previo import crear_recibo_previo

PCT, SUELDO = base.PCT, 6000000.0
PISO_DIA = 1750905.0 / 30


@tagged('post_install', '-at_install')
class TestIncapacidadBaseIbc(base.TestIncapacidadTramoProrroga):

    def _julio(self, empleado, contrato, ibc):
        return crear_recibo_previo(self.env, empleado, contrato, self.nomina, date(2026, 7, 1), date(2026, 7, 31), ibc)

    def _recibo_inc(self, empleado, contrato, desde, hasta, calcular=True):
        contrato.generate_work_entries(date(2026, 1, 1), date(2026, 9, 30))
        recibo = self.env['hr.payslip'].create({
            'name': 'Recibo %s' % desde, 'employee_id': empleado.id, 'version_id': contrato.id, 'company_id': self.company.id,
            'struct_id': self.nomina.id, 'date_from': desde, 'date_to': hasta})
        if calcular:
            recibo.compute_sheet()
        return recibo

    def _pago_inc(self, recibo):
        linea = recibo.line_ids.filtered(lambda l: l.code == 'CO_INC_COMUN')
        self.assertTrue(linea, 'El recibo debe pagar incapacidad.')
        return linea.total

    def _agosto(self, nombre, ibc_julio=None):
        empleado, contrato = self._empleado(nombre)
        if ibc_julio is not None:
            self._julio(empleado, contrato, ibc_julio)
        self._incapacidad(empleado, date(2026, 8, 3), date(2026, 8, 12))
        return empleado, contrato, self._recibo_inc(empleado, contrato, date(2026, 8, 1), date(2026, 8, 15))

    # ── la base ──
    def test_sin_ibc_del_mes_anterior_paga_con_el_sueldo_y_avisa(self):
        """Sin recibos de julio: 10 x 200.000 x 0,6667 = 1.333.400 (lo de siempre) y el aviso dice que se uso el sueldo de la ficha del empleado."""
        _empleado, _contrato, recibo = self._agosto('IncSinBase')
        self.assertAlmostEqual(self._pago_inc(recibo), 10 * 200000.0 * PCT, delta=0.01)
        self.assertIn('No hay IBC del mes anterior (2026-07)', recibo.l10n_co_ne_aviso_ibc_anterior)

    def test_con_ibc_menor_al_sueldo_paga_con_ese_ibc(self):
        """IBC de julio 4.500.000 (valor dia 150.000): 10 x 150.000 x 0,6667 = 1.000.050, sin aviso. Antes: 1.333.400 (el sueldo actual)."""
        _empleado, _contrato, recibo = self._agosto('IncIbcMenor', ibc_julio=4500000.0)
        self.assertAlmostEqual(self._pago_inc(recibo), 10 * 150000.0 * PCT, delta=0.01)
        self.assertFalse(recibo.l10n_co_ne_aviso_ibc_anterior)

    def test_con_ibc_mayor_al_sueldo_por_variables_paga_con_ese_ibc(self):
        """IBC de julio 7.500.000 por horas extras (valor dia 250.000): 10 x 250.000 x 0,6667 = 1.666.750."""
        _empleado, _contrato, recibo = self._agosto('IncIbcMayor', ibc_julio=7500000.0)
        self.assertAlmostEqual(self._pago_inc(recibo), 10 * 250000.0 * PCT, delta=0.01)

    def test_el_piso_de_un_smmlv_por_dia_sigue_aplicando(self):
        """IBC de julio 1.000.000: 33.333 x 0,6667 = 22.222 por dia, por debajo del piso de 1 SMMLV por dia (58.363,5, CST art. 227): 10 x 58.363,5 = 583.635."""
        _empleado, _contrato, recibo = self._agosto('IncPiso', ibc_julio=1000000.0)
        self.assertAlmostEqual(self._pago_inc(recibo), 10 * PISO_DIA, delta=0.01)

    def test_un_aumento_de_sueldo_despues_de_la_inicial_no_cambia_el_pago(self):
        """El sueldo sube a 8.000.000 despues del inicio: la incapacidad sigue pagandose con el IBC de julio (6.000.000): 1.333.400 (con el sueldo actual serian 1.777.867)."""
        empleado, contrato = self._empleado('IncAumento')
        self._julio(empleado, contrato, SUELDO)
        self._incapacidad(empleado, date(2026, 8, 3), date(2026, 8, 12))
        contrato.write({'wage': 8000000.0})
        recibo = self._recibo_inc(empleado, contrato, date(2026, 8, 1), date(2026, 8, 15))
        self.assertAlmostEqual(self._pago_inc(recibo), 10 * 200000.0 * PCT, delta=0.01)

    # ── un aumento de sueldo a mitad de una incapacidad vinculada (v19: el aumento es una VERSION nueva y el recibo de cada version es otro) ──
    def _cadena_con_aumento(self, nombre, ibc_agosto):
        """Inicial del 1 al 12 de septiembre y su prorroga vinculada del 13 al 30; aumento de 6.000.000 (A) a 6.600.000 (B) el 16-sep: recibos 1-15 (A, 12 + 3 dias) y 16-30 (B, 15 dias).
        ``ibc_agosto`` (el mes anterior al inicio de la INICIAL) fija con un recibo confirmado; ``None`` = sin base."""
        empleado, version_a = self._empleado(nombre)
        version_b = crear_aumento(self.env, empleado, version_a, date(2026, 9, 16), 6600000.0)
        if ibc_agosto is not None:
            crear_recibo_previo(self.env, empleado, version_a, self.nomina, date(2026, 8, 1), date(2026, 8, 31), ibc_agosto)
        for version in (version_a, version_b):
            version.generate_work_entries(date(2026, 9, 1), date(2026, 9, 30))
        inicial = self._incapacidad(empleado, date(2026, 9, 1), date(2026, 9, 12))
        self._incapacidad(empleado, date(2026, 9, 13), date(2026, 9, 30), prorroga_de=inicial)
        recibo_a = self._recibo_inc(empleado, version_a, date(2026, 9, 1), date(2026, 9, 15), calcular=False)
        recibo_b = self._recibo_inc(empleado, version_b, date(2026, 9, 16), date(2026, 9, 30), calcular=False)
        (recibo_a | recibo_b).compute_sheet()        # R-2, mes partido: el que cierra el mes (B) se calcula junto con el tramo anterior (o con ese ya confirmado)
        self.assertEqual((recibo_a.version_id, recibo_b.version_id), (version_a, version_b))
        return recibo_a, recibo_b

    def test_un_aumento_a_mitad_de_una_incapacidad_vinculada_paga_el_mismo_valor_por_dia_en_a_y_en_b(self):
        """MANDATORIA (TL): el IBC de agosto (mes anterior a la INICIAL) es 6.000.000 -> 200.000 por dia en AMBOS recibos: 15 x 200.000 x 0,6667 = 2.000.100 cada uno, 4.000.200 en total. B NO paga con su
        sueldo (6.600.000 = 220.000 por dia daria 2.200.110): el valor del dia es el de la inicial, el mismo en toda la cadena, aunque el recibo y su sueldo sean de otra version. Sin aviso: agosto tiene base."""
        recibo_a, recibo_b = self._cadena_con_aumento('IncCadenaAumento', SUELDO)
        self.assertAlmostEqual(self._pago_inc(recibo_a), 15 * 200000.0 * PCT, delta=0.01)
        self.assertAlmostEqual(self._pago_inc(recibo_b), 15 * 200000.0 * PCT, delta=0.01)
        self.assertAlmostEqual(self._pago_inc(recibo_a) + self._pago_inc(recibo_b), 30 * 200000.0 * PCT, delta=0.01)
        self.assertNotAlmostEqual(self._pago_inc(recibo_b), 15 * 220000.0 * PCT, delta=1.0)
        self.assertEqual(recibo_b._ne_incapacidad_cadenas(), [(15, 15, date(2026, 9, 1))], 'B continua la cadena: 15 dias previos y 15 propios, la inicial del 1-sep')
        self.assertFalse(recibo_a.l10n_co_ne_aviso_ibc_anterior)
        self.assertFalse(recibo_b.l10n_co_ne_aviso_ibc_anterior)

    def test_un_aumento_a_mitad_de_una_incapacidad_vinculada_sin_ibc_usa_el_sueldo_de_la_version_de_ese_mes(self):
        """SOLO v19: sin recibos de agosto el respaldo es el sueldo de la version vigente el 1-ago (A, 6.000.000: 200.000 por dia), NO el de B que firma el recibo (6.600.000): el valor del dia
        sigue siendo el mismo en A y en B, y los dos recibos avisan (el sueldo de la ficha del empleado)."""
        recibo_a, recibo_b = self._cadena_con_aumento('IncCadenaAumentoSinBase', None)
        self.assertAlmostEqual(self._pago_inc(recibo_a), 15 * 200000.0 * PCT, delta=0.01)
        self.assertAlmostEqual(self._pago_inc(recibo_b), 15 * 200000.0 * PCT, delta=0.01)
        for recibo in (recibo_a, recibo_b):
            self.assertIn('No hay IBC del mes anterior (2026-08)', recibo.l10n_co_ne_aviso_ibc_anterior)

    # ── la cadena ──
    def test_la_prorroga_usa_el_mes_anterior_a_la_inicial_no_al_del_recibo(self):
        """A (1 a 31 de agosto) y su prorroga B (1 a 15 de septiembre, vinculada). IBC de julio 4.500.000 (mes anterior a A) y de agosto 6.000.000 (mes anterior al recibo de septiembre): en la quincena
        1-15 de septiembre las posiciones 32-46 se pagan con el IBC de la INICIAL: 15 x 150.000 x 0,6667 = 1.500.075 (con el de agosto serian 2.000.100). Y no hay aviso: el mes anterior a la inicial SI tiene base."""
        empleado, contrato = self._empleado('IncCadena')
        self._julio(empleado, contrato, 4500000.0)
        a = self._incapacidad(empleado, date(2026, 8, 1), date(2026, 8, 31))
        self._incapacidad(empleado, date(2026, 9, 1), date(2026, 9, 15), prorroga_de=a)
        # el recibo confirmado de agosto va DESPUES de validar las ausencias: hr_payroll_holidays marca «blocked» (a diferir) una ausencia que se valida sobre un recibo ya confirmado y bloquea el calculo
        crear_recibo_previo(self.env, empleado, contrato, self.nomina, date(2026, 8, 1), date(2026, 8, 31), SUELDO)
        recibo = self._recibo_inc(empleado, contrato, date(2026, 9, 1), date(2026, 9, 15))
        self.assertAlmostEqual(self._pago_inc(recibo), 15 * 150000.0 * PCT, delta=0.01)
        self.assertFalse(recibo.l10n_co_ne_aviso_ibc_anterior)

    def test_el_aviso_mira_el_mes_de_la_inicial_y_no_el_del_recibo(self):
        """Solo hay base en julio (mes anterior a la inicial): el recibo de septiembre, cuyo mes anterior (agosto) no tiene base, NO avisa. Si faltara julio, avisaria de julio."""
        empleado, contrato = self._empleado('IncAvisoInicial')
        self._julio(empleado, contrato, SUELDO)
        a = self._incapacidad(empleado, date(2026, 8, 1), date(2026, 8, 31))
        self._incapacidad(empleado, date(2026, 9, 1), date(2026, 9, 15), prorroga_de=a)
        self.assertFalse(self._recibo_inc(empleado, contrato, date(2026, 9, 1), date(2026, 9, 15)).l10n_co_ne_aviso_ibc_anterior)
        otro, contrato_otro = self._empleado('IncAvisoSinJulio')
        b = self._incapacidad(otro, date(2026, 8, 1), date(2026, 8, 31))
        self._incapacidad(otro, date(2026, 9, 1), date(2026, 9, 15), prorroga_de=b)
        crear_recibo_previo(self.env, otro, contrato_otro, self.nomina, date(2026, 8, 1), date(2026, 8, 31), SUELDO)       # agosto SI tiene base, julio no
        aviso = self._recibo_inc(otro, contrato_otro, date(2026, 9, 1), date(2026, 9, 15)).l10n_co_ne_aviso_ibc_anterior
        self.assertIn('2026-07', aviso)
        self.assertNotIn('2026-08', aviso)

    def test_otros_codigos_de_ausencia_no_cambian(self):
        """Licencia de maternidad (100 % del sueldo) y incapacidad laboral siguen con el sueldo del contrato: H-F1-08 es solo de la incapacidad comun."""
        empleado, contrato = self._empleado('OtrosCodigos')
        self._julio(empleado, contrato, 4500000.0)
        recibo = self._recibo_inc(empleado, contrato, date(2026, 8, 1), date(2026, 8, 15))
        self.assertAlmostEqual(recibo._ne_pago_ausencia_calendario('CO_INC_LABORAL', 5), 5 * 200000.0, delta=0.01)
        self.assertAlmostEqual(recibo._ne_pago_ausencia_calendario('CO_LIC_MAT', 10), 10 * 200000.0, delta=0.01)
