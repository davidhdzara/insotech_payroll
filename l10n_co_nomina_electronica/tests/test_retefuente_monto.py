# -*- coding: utf-8 -*-
"""R-1 (parte 1): pruebas de MONTO de la retención en la fuente de un pago MENSUAL (Procedimiento 1).

Hasta hoy el módulo solo probaba la configuración (UVT por año/compañía), la prima/liquidación y el tope de la renta
exenta; ninguna prueba fijaba el monto de la tabla ni de la depuración. Estas pruebas fijan el comportamiento que HOY es
correcto para un pago mensual; el comportamiento de un pago QUINCENAL (que hoy retiene 2,3 veces, doc 59 §20.5) NO se
fija aquí: va en R-2, con la prueba roja primero.

Fuente normativa (el TEXTO de los artículos NO está en el repositorio: NO VERIFICADO contra fuente primaria; los valores
salen de los parámetros versionados del módulo, ``data/l10n_co_rule_parameters_data.xml``):
- Art. 383 ET, Procedimiento 1: tabla marginal en UVT (parámetro ``l10n_co_tabla_retencion_art383``).
- Art. 206 num. 10 ET (Ley 2277/2022): renta exenta 25 %, tope 790 UVT anuales (``/12`` para la retención mensual).
- Art. 387 ET: dependientes, 10 % del ingreso con tope de 32 UVT (parámetro ``l10n_co_max_dependientes_uvt``).
- Art. 126-1 y 126-4 ET: pensión voluntaria + AFC, tope combinado del 30 % del ingreso.
- Aportes obligatorios de salud y pensión del trabajador: 4 % y 4 % del IBC (Ley 100/1993).
- UVT 2026 = $52.374 (Res. DIAN 000238 de 2025, citada en los docs 05/06 de correcciones normativas).

Los valores esperados se calcularon APARTE con un script que no importa el módulo (misma tabla y mismos porcentajes) y se
contrastaron con los dos casos que ya probaba ``test_renta_exenta_tope`` (10 M = 479.649 y 20 M = 2.958.605).
"""

from types import SimpleNamespace

from odoo.tests.common import TransactionCase, tagged

FECHA = '2026-01-01'


@tagged('post_install', '-at_install')
class TestRetefuenteMonto(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U',
            'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_clase_riesgo': '1',
            'l10n_co_ne_febrero_modo': 'real', 'l10n_co_ne_redondeo_dias': 'DOWN',
            'name': 'Compañía de Prueba Monto Retención'})
        cls.config = cls.env['l10n.co.retefuente.uvt'].create({
            'year': '2026', 'company_id': cls.company.id, 'procedure': '1'})
        cls.employee = cls.env['hr.employee'].create({
            'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00',
            'name': 'Monto Retención Sin Dependientes', 'company_id': cls.company.id})
        cls.employee_dep = cls.env['hr.employee'].create({
            'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00',
            'name': 'Monto Retención Con Dependientes', 'company_id': cls.company.id,
            'l10n_co_ne_dependientes': True})

    def _rete(self, ingreso, ibc=0.0, employee=None, contract=None):
        """Retención de un pago MENSUAL por Procedimiento 1 (se fuerza para no depender de la configuración anual)."""
        return self.config.compute_retefuente(
            employee or self.employee, ingreso, ibc, ibc, company=self.company, contract=contract,
            force_procedure='1')

    # ── Tabla del Art. 383 ET: un punto dentro de cada tramo (las fronteras exactas no se fijan: ver doc 59 §20.6) ──
    def test_la_uvt_2026_es_52374(self):
        self.assertAlmostEqual(self.config.uvt_value, 52374.0, delta=0.01)

    def test_tabla_art383_por_tramo(self):
        casos = (
            (94.99, 0.0),        # hasta 95 UVT: 0 %
            (95.01, 0.0019),     # justo sobre 95: (0,01) x 19 %
            (100.0, 0.95),       # 95-150: (100 - 95) x 19 %
            (200.0, 24.0),       # 150-360: (200 - 150) x 28 % + 10
            (400.0, 82.2),       # 360-640: (400 - 360) x 33 % + 69
            (700.0, 183.0),      # 640-945: (700 - 640) x 35 % + 162
            (1000.0, 288.35),    # 945-2300: (1000 - 945) x 37 % + 268
            (2500.0, 848.0),     # sobre 2300: (2500 - 2300) x 39 % + 770
        )
        for base_uvt, esperado in casos:
            with self.subTest(base_uvt=base_uvt):
                self.assertAlmostEqual(
                    self.config._apply_marginal_table(base_uvt, FECHA), esperado, places=6)

    def test_base_en_cero_o_negativa_no_retiene(self):
        self.assertEqual(self.config._apply_marginal_table(0.0, FECHA), 0.0)
        self.assertEqual(self.config._apply_marginal_table(-5.0, FECHA), 0.0)

    # ── Frontera de las 95 UVT en pesos (sin aportes: subtotal = ingreso; exenta 25 %; base = 75 %) ──
    def test_ingreso_que_deja_la_base_bajo_95_uvt_no_retiene(self):
        """6.620.000: exenta 1.655.000, base 4.965.000 = 94,7989 UVT (< 95) -> 0."""
        res = self._rete(6620000.0)
        self.assertAlmostEqual(res['base_uvt'], 94.7989, places=4)
        self.assertEqual(res['retencion_pesos'], 0.0)

    def test_ingreso_que_deja_la_base_sobre_95_uvt_retiene(self):
        """6.650.000: exenta 1.662.500, base 4.987.500 = 95,2285 UVT -> (95,2285 - 95) x 19 % = 0,0434 UVT = 2.274."""
        res = self._rete(6650000.0)
        self.assertAlmostEqual(res['base_uvt'], 95.2285, places=4)
        self.assertAlmostEqual(res['retencion_pesos'], 2274.0, delta=1.0)

    # ── Depuración completa de un pago mensual ──
    def test_salario_12_millones_mensual_retiene_642432(self):
        """12.000.000 con IBC 12.000.000: salud 480.000 y pensión 480.000 -> subtotal 11.040.000; exenta 25 % 2.760.000;
        base 8.280.000 = 158,0937 UVT -> (158,0937 - 150) x 28 % + 10 = 12,2662 UVT x 52.374 = 642.432.
        Es la referencia contra la que R-2 compara el pago quincenal (doc 59 §20.5, caso A)."""
        res = self._rete(12000000.0, ibc=12000000.0)
        self.assertAlmostEqual(res['aporte_salud'], 480000.0, delta=0.01)
        self.assertAlmostEqual(res['aporte_pension'], 480000.0, delta=0.01)
        self.assertAlmostEqual(res['subtotal_depurado'], 11040000.0, delta=0.01)
        self.assertAlmostEqual(res['renta_exenta_25'], 2760000.0, delta=0.01)
        self.assertAlmostEqual(res['base_gravable'], 8280000.0, delta=0.01)
        self.assertAlmostEqual(res['base_uvt'], 158.0937, places=4)
        self.assertAlmostEqual(res['retencion_pesos'], 642432.0, delta=1.0)

    def test_salario_6_millones_mensual_no_retiene(self):
        """6.000.000 con IBC 6.000.000: subtotal 5.520.000; exenta 1.380.000; base 4.140.000 = 79,05 UVT (< 95) -> 0."""
        res = self._rete(6000000.0, ibc=6000000.0)
        self.assertAlmostEqual(res['base_gravable'], 4140000.0, delta=0.01)
        self.assertEqual(res['retencion_pesos'], 0.0)

    # ── Dependientes (Art. 387 ET): 10 % del ingreso, tope 32 UVT ──
    def test_dependientes_bajo_el_tope_deducen_el_10_por_ciento(self):
        """12.000.000: 10 % = 1.200.000 (< 32 UVT = 1.675.968). Subtotal 9.840.000; exenta 2.460.000; base 7.380.000 =
        140,9096 UVT -> (140,9096 - 95) x 19 % = 8,7228 UVT = 456.849."""
        res = self._rete(12000000.0, ibc=12000000.0, employee=self.employee_dep)
        self.assertAlmostEqual(res['deduccion_dependientes'], 1200000.0, delta=0.01)
        self.assertAlmostEqual(res['base_gravable'], 7380000.0, delta=0.01)
        self.assertAlmostEqual(res['retencion_pesos'], 456849.0, delta=1.0)

    def test_dependientes_sobre_el_tope_deducen_32_uvt(self):
        """20.000.000: 10 % = 2.000.000 > 1.675.968 (32 UVT) -> deduce 1.675.968. Subtotal 16.724.032; exenta (25 % =
        4.181.008 > tope 3.447.955) 3.447.955; base 13.276.077 = 253,486 UVT -> (253,486 - 150) x 28 % + 10 = 38,9761 UVT
        = 2.041.334."""
        res = self._rete(20000000.0, ibc=20000000.0, employee=self.employee_dep)
        self.assertAlmostEqual(res['deduccion_dependientes'], 1675968.0, delta=0.01)
        self.assertAlmostEqual(res['renta_exenta_25'], 3447955.0, delta=0.01)
        self.assertAlmostEqual(res['base_gravable'], 13276077.0, delta=0.01)
        self.assertAlmostEqual(res['retencion_pesos'], 2041334.0, delta=1.0)

    def test_sin_dependientes_no_hay_deduccion(self):
        res = self._rete(12000000.0, ibc=12000000.0)
        self.assertEqual(res['deduccion_dependientes'], 0.0)

    # ── Pensión voluntaria + AFC (Art. 126-1 y 126-4 ET): tope combinado del 30 % del ingreso ──
    @staticmethod
    def _contrato(vol, afc):
        """Solo los 3 atributos que lee compute_retefuente (sin payslip: no aplica el techo anual de 3.800 UVT)."""
        return SimpleNamespace(
            l10n_co_ne_pension_voluntaria=vol, l10n_co_ne_afc=afc, l10n_co_ne_retention_procedure='1')

    def test_pension_voluntaria_y_afc_bajo_el_tope_se_deducen_completas(self):
        """12.000.000, voluntaria 1.000.000 + AFC 1.000.000 (< 30 % = 3.600.000): subtotal 9.040.000; exenta 2.260.000;
        base 6.780.000 = 129,4535 UVT -> (129,4535 - 95) x 19 % = 6,5462 UVT = 342.849."""
        res = self._rete(12000000.0, ibc=12000000.0, contract=self._contrato(1000000.0, 1000000.0))
        self.assertAlmostEqual(res['aporte_voluntario_pension'], 1000000.0, delta=0.01)
        self.assertAlmostEqual(res['afc'], 1000000.0, delta=0.01)
        self.assertAlmostEqual(res['retencion_pesos'], 342849.0, delta=1.0)

    def test_pension_voluntaria_y_afc_sobre_el_tope_se_reducen_en_proporcion(self):
        """12.000.000, voluntaria 2.000.000 + AFC 2.000.000 = 4.000.000 > 3.600.000: factor 0,9 -> 1.800.000 y 1.800.000.
        Subtotal 7.440.000; exenta 1.860.000; base 5.580.000 = 106,5414 UVT -> 2,1929 UVT = 114.849."""
        res = self._rete(12000000.0, ibc=12000000.0, contract=self._contrato(2000000.0, 2000000.0))
        self.assertAlmostEqual(res['aporte_voluntario_pension'], 1800000.0, delta=0.01)
        self.assertAlmostEqual(res['afc'], 1800000.0, delta=0.01)
        self.assertAlmostEqual(res['subtotal_depurado'], 7440000.0, delta=0.01)
        self.assertAlmostEqual(res['retencion_pesos'], 114849.0, delta=1.0)
