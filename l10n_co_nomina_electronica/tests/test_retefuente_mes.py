# -*- coding: utf-8 -*-
"""R-2a (doc 59 §25): la retención en la fuente se calcula sobre la base del MES y se reparte entre los pagos del mes.

Decisión de David (2026-11-14, texto normativo NO VERIFICADO en el repositorio: Art. 383 y 385 ET, num. 10 art. 206, DUR 1625
de 2016): retención SIEMPRE sobre el mes completo (depuración + tabla del Art. 383), 1.ª quincena = 50 % de la retención de
una proyección, cierre = saldo (retención del mes real menos lo ya retenido); un pago quincenal retiene lo mismo que el mismo
salario pagado mensual (antes 2,3 veces: 743.232 por quincena frente a 642.432 al mes).

Estas pruebas llaman al helper ``hr.payslip._ne_retencion_mes(categories)`` con las categorías a mano y recibos PREVIOS reales
con sus líneas creadas a mano (patrón de ``test_pdf_recibo_neto``): no usan ``compute_sheet()`` para no depender de work
entries ni de calendarios. Valores esperados calculados aparte con un script que no importa el módulo (misma tabla del
Art. 383, UVT 2026 = 52.374; el caso base 12.000.000 mensual = 642.432 ya lo fija ``test_retefuente_monto``).
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from .common_documento import DocumentoFixture

SALARIO = 12000000.0
MEDIO = 6000000.0           # media quincena de 12.000.000


@tagged('post_install', '-at_install')
class TestRetefuenteMes(DocumentoFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture_documento('Compañía Retención Mes')
        cls.env['l10n.co.retefuente.uvt'].create({'year': '2026', 'company_id': cls.company.id, 'procedure': '1'})
        cls.tipo = {
            periodicidad: cls.env['hr.payroll.structure.type'].create({
                'name': 'Retención Mes %s' % periodicidad, 'country_id': cls.env.ref('base.co').id,
                'default_schedule_pay': periodicidad})
            for periodicidad in ('monthly', 'semi-monthly', 'weekly')}

    # ── fixtures ─────────────────────────────────────────────────────
    def _contrato(self, periodicidad='semi-monthly', salario=SALARIO, ingreso=date(2024, 1, 1), **extra):
        type(self).n += 1
        empleado = self.env['hr.employee'].create({
            'name': 'Empleado Retención Mes %s' % self.n, 'company_id': self.company.id, 'identification_id': '1020304050',
            'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00', 'l10n_co_ne_payment_method': '10'})
        return self.env['hr.contract'].create(dict({
            'name': 'Contrato Retención Mes %s' % self.n, 'employee_id': empleado.id, 'company_id': self.company.id,
            'structure_type_id': self.tipo[periodicidad].id, 'l10n_co_ne_contract_type': '2',
            'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00',
            'wage': salario, 'date_start': ingreso, 'state': 'open'}, **extra))

    def _recibo(self, contrato, desde, hasta, estado=None):
        type(self).n += 1
        recibo = self.env['hr.payslip'].create({
            'name': 'Recibo Retención Mes %s' % self.n, 'employee_id': contrato.employee_id.id,
            'contract_id': contrato.id, 'company_id': self.company.id, 'struct_id': self.struct.id,
            'date_from': desde, 'date_to': hasta})
        if estado:
            recibo.write({'state': estado})
        return recibo

    def _linea(self, recibo, codigo, total):
        regla = self.env['hr.salary.rule'].search([('code', '=', codigo), ('struct_id', '=', recibo.struct_id.id)], limit=1)
        self.assertTrue(regla, 'Falta la regla %s en %s' % (codigo, recibo.struct_id.name))
        return self.env['hr.payslip.line'].create({
            'slip_id': recibo.id, 'salary_rule_id': regla.id, 'code': codigo, 'name': codigo,
            'contract_id': recibo.contract_id.id, 'employee_id': recibo.employee_id.id,
            'quantity': 1.0, 'rate': 100.0, 'amount': total, 'total': total})

    def _confirmar(self, recibo, devengado, retenido=0.0, exento=0.0, estado='paid'):
        """Deja ``recibo`` como un recibo ya confirmado del mes, con las líneas que el cálculo lee de los anteriores."""
        recibo.write({'state': estado})
        self._linea(recibo, 'CO_BASICO', devengado)
        self._linea(recibo, 'CO_RETEFUENTE_BASE_IBC', devengado)
        self._linea(recibo, 'CO_RETEFUENTE', -retenido)
        self._linea(recibo, 'CO_EXENTO_PENSION_AFC', exento)
        return recibo

    def _previo(self, contrato, desde, hasta, devengado, retenido=0.0, exento=0.0, estado='paid'):
        return self._confirmar(self._recibo(contrato, desde, hasta), devengado, retenido, exento, estado)

    # ── ¿cierra el mes? (periodicidad) ───────────────────────────────
    def test_quincenal_el_1_al_15_y_el_21_al_5_no_cierran_y_el_16_al_fin_y_el_6_al_20_si(self):
        contrato = self._contrato('semi-monthly')
        for desde, hasta, cierra in (
                (date(2026, 4, 1), date(2026, 4, 15), False), (date(2026, 4, 16), date(2026, 4, 30), True),
                (date(2026, 3, 21), date(2026, 4, 5), False), (date(2026, 4, 6), date(2026, 4, 20), True),
                (date(2026, 2, 16), date(2026, 2, 28), True)):
            with self.subTest(hasta=hasta):
                self.assertEqual(self._recibo(contrato, desde, hasta)._ne_retencion_es_cierre(), cierra)

    def test_semanal_cierra_el_que_deja_al_siguiente_pago_en_otro_mes(self):
        contrato = self._contrato('weekly')
        for desde, hasta, cierra in (
                (date(2026, 4, 1), date(2026, 4, 7), False), (date(2026, 4, 15), date(2026, 4, 21), False),
                (date(2026, 4, 22), date(2026, 4, 28), True), (date(2026, 3, 25), date(2026, 3, 31), True),
                (date(2026, 4, 29), date(2026, 5, 5), False)):
            with self.subTest(hasta=hasta):
                self.assertEqual(self._recibo(contrato, desde, hasta)._ne_retencion_es_cierre(), cierra)

    def test_mensual_siempre_cierra(self):
        contrato = self._contrato('monthly')
        self.assertTrue(self._recibo(contrato, date(2026, 4, 1), date(2026, 4, 30))._ne_retencion_es_cierre())

    # ── pago MENSUAL: igual que antes (el mes completo) ──────────────
    def test_mensual_retiene_el_mes_completo(self):
        recibo = self._recibo(self._contrato('monthly'), date(2026, 4, 1), date(2026, 4, 30))
        res = recibo._ne_retencion_mes({'DEV_SAL': SALARIO})
        self.assertAlmostEqual(res['retencion'], 642432.0, delta=1.0)
        self.assertEqual(res['reintegro'], 0.0)
        self.assertTrue(res['es_cierre'])
        self.assertAlmostEqual(res['base_devengado'], SALARIO, delta=0.01)

    def test_salario_de_6_millones_no_retiene_en_ninguna_quincena(self):
        contrato = self._contrato('semi-monthly', salario=6000000.0)
        primera = self._recibo(contrato, date(2026, 4, 1), date(2026, 4, 15))
        self.assertEqual(primera._ne_retencion_mes({'DEV_SAL': 3000000.0})['retencion'], 0.0)
        self._confirmar(primera, 3000000.0)
        segunda = self._recibo(contrato, date(2026, 4, 16), date(2026, 4, 30))
        res = segunda._ne_retencion_mes({'DEV_SAL': 3000000.0})
        self.assertEqual((res['retencion'], res['reintegro']), (0.0, 0.0))

    # ── pago QUINCENAL: 50 % y saldo; el mes suma lo mismo que el mensual ──
    def test_quincenal_la_primera_retiene_la_mitad_de_la_retencion_del_mes(self):
        primera = self._recibo(self._contrato(), date(2026, 4, 1), date(2026, 4, 15))
        res = primera._ne_retencion_mes({'DEV_SAL': MEDIO})
        self.assertFalse(res['es_cierre'])
        self.assertAlmostEqual(res['retencion'], 321216.0, delta=1.0)      # antes: 743.232
        self.assertEqual(res['reintegro'], 0.0)

    def test_quincenal_la_segunda_retiene_el_saldo_y_el_mes_suma_642432(self):
        contrato = self._contrato()
        self._previo(contrato, date(2026, 4, 1), date(2026, 4, 15), MEDIO, retenido=321216.0)
        segunda = self._recibo(contrato, date(2026, 4, 16), date(2026, 4, 30))
        res = segunda._ne_retencion_mes({'DEV_SAL': MEDIO})
        self.assertTrue(res['es_cierre'])
        self.assertAlmostEqual(res['retencion'], 321216.0, delta=1.0)
        self.assertAlmostEqual(321216.0 + res['retencion'], 642432.0, delta=1.0)     # antes: 1.486.464
        self.assertEqual(res['reintegro'], 0.0)

    def test_extras_solo_en_la_segunda_se_ajustan_en_la_segunda(self):
        """La 1.ª no cambia (321.216). La 2.ª trae 1.000.000 de extras: mes real 13.000.000 -> retención 835.632; la 2.ª
        retiene 835.632 - 321.216 = 514.416, y el mes suma lo mismo que un pago mensual de 13.000.000."""
        contrato = self._contrato()
        self._previo(contrato, date(2026, 4, 1), date(2026, 4, 15), MEDIO, retenido=321216.0)
        segunda = self._recibo(contrato, date(2026, 4, 16), date(2026, 4, 30))
        res = segunda._ne_retencion_mes({'DEV_SAL': MEDIO + 1000000.0})
        self.assertAlmostEqual(res['retencion'], 514416.0, delta=1.0)
        mensual = self.env['l10n.co.retefuente.uvt']._ne_config_del_anio('2026', self.company).compute_retefuente(
            segunda.employee_id, 13000000.0, 13000000.0, 13000000.0, self.company, force_procedure='1')
        self.assertAlmostEqual(321216.0 + res['retencion'], mensual['retencion_pesos'], delta=1.0)

    def test_exceso_retenido_en_la_primera_se_devuelve_en_la_segunda(self):
        """Mes real 8.000.000 (la 2.ª solo devenga 2.000.000): retención del mes 103.449 < 321.216 ya retenidos -> la 2.ª
        retiene 0 y devuelve 217.767. Nunca ambos distintos de 0."""
        contrato = self._contrato()
        self._previo(contrato, date(2026, 4, 1), date(2026, 4, 15), MEDIO, retenido=321216.0)
        segunda = self._recibo(contrato, date(2026, 4, 16), date(2026, 4, 30))
        res = segunda._ne_retencion_mes({'DEV_SAL': 2000000.0})
        self.assertEqual(res['retencion'], 0.0)
        self.assertAlmostEqual(res['reintegro'], 217767.0, delta=1.0)

    # ── mes de date_to: un periodo que cruza de mes (pagos los 5 y 20) ──
    def test_5_y_20_el_recibo_que_cruza_cuenta_para_el_mes_de_date_to(self):
        """21-mar -> 5-abr es el 1.er pago de abril (15/30 de la proyección); 6 -> 20-abr cierra abril restando SOLO lo
        retenido en el del 5-abr: el recibo 6 -> 20-mar (con 100.000 retenidos) es de marzo y no se mezcla."""
        contrato = self._contrato()
        self._previo(contrato, date(2026, 3, 6), date(2026, 3, 20), MEDIO, retenido=100000.0)
        cruza = self._recibo(contrato, date(2026, 3, 21), date(2026, 4, 5))
        res = cruza._ne_retencion_mes({'DEV_SAL': MEDIO})
        self.assertFalse(res['es_cierre'])
        self.assertAlmostEqual(res['retencion'], 321216.0, delta=1.0)
        self._confirmar(cruza, MEDIO, retenido=321216.0)
        cierre = self._recibo(contrato, date(2026, 4, 6), date(2026, 4, 20))
        res_cierre = cierre._ne_retencion_mes({'DEV_SAL': MEDIO})
        self.assertTrue(res_cierre['es_cierre'])
        self.assertAlmostEqual(res_cierre['retencion'], 321216.0, delta=1.0)

    # ── semanal: 7/30 por recibo y el último del mes ajusta ──────────
    def test_semanal_cada_recibo_retiene_7_30_y_el_ultimo_ajusta(self):
        """Salario 12.000.000, 2.800.000 por semana. Las 3 primeras retienen 7/30 de 642.432 = 149.901 (suma 449.703). El
        cierre de abril (22-28; 4 semanas = 11.200.000, retención del mes 522.969) retiene 522.969 - 449.703 = 73.266."""
        contrato = self._contrato('weekly')
        primera = self._recibo(contrato, date(2026, 4, 1), date(2026, 4, 7))
        self.assertAlmostEqual(primera._ne_retencion_mes({'DEV_SAL': 2800000.0})['retencion'], 149901.0, delta=1.0)
        self._confirmar(primera, 2800000.0, retenido=149901.0)
        for desde, hasta in ((8, 14), (15, 21)):
            self._previo(contrato, date(2026, 4, desde), date(2026, 4, hasta), 2800000.0, retenido=149901.0)
        cierre = self._recibo(contrato, date(2026, 4, 22), date(2026, 4, 28))
        res = cierre._ne_retencion_mes({'DEV_SAL': 2800000.0})
        self.assertTrue(res['es_cierre'])
        self.assertAlmostEqual(res['retencion'], 73266.0, delta=2.0)

    # ── contrato que empieza a mitad de mes ──────────────────────────
    def test_contrato_que_empieza_el_12_proyecta_con_los_dias_bajo_contrato(self):
        """Ingreso el 12-abr (19 días de abril). El recibo 12 -> 15 trae 4 días (1.600.000): proyección 1.600.000 + 15 x
        400.000 = 7.600.000, retención 51.009; el recibo retiene 4/19 de eso = 10.739."""
        contrato = self._contrato(ingreso=date(2026, 4, 12))
        recibo = self._recibo(contrato, date(2026, 4, 12), date(2026, 4, 15))
        res = recibo._ne_retencion_mes({'DEV_SAL': 1600000.0})
        self.assertAlmostEqual(res['retencion'], 10739.0, delta=1.0)

    # ── exento de pensión voluntaria + AFC: incremental por recibo ───
    def test_el_exento_de_pension_voluntaria_y_afc_se_guarda_incremental(self):
        """Voluntaria 1.000.000 + AFC 1.000.000 (< 30 %): exento del mes 2.000.000 y retención del mes 342.849. La 1.ª guarda
        la mitad (1.000.000), la 2.ª el resto (2.000.000 - 1.000.000): el acumulado anual suma 12 meses, no 24 quincenas."""
        contrato = self._contrato(l10n_co_ne_pension_voluntaria=1000000.0, l10n_co_ne_afc=1000000.0)
        primera = self._recibo(contrato, date(2026, 4, 1), date(2026, 4, 15))
        res1 = primera._ne_retencion_mes({'DEV_SAL': MEDIO})
        self.assertAlmostEqual(res1['exento_vol_pension_afc'], 1000000.0, delta=1.0)
        self._confirmar(primera, MEDIO, retenido=res1['retencion'], exento=res1['exento_vol_pension_afc'])
        segunda = self._recibo(contrato, date(2026, 4, 16), date(2026, 4, 30))
        res2 = segunda._ne_retencion_mes({'DEV_SAL': MEDIO})
        self.assertAlmostEqual(res2['exento_vol_pension_afc'], 1000000.0, delta=1.0)
        self.assertAlmostEqual(res1['retencion'] + res2['retencion'], 342849.0, delta=1.0)

    # ── recibos previos en borrador / sin calcular / cancelados ──────
    def test_previo_en_borrador_ya_calculado_se_usa_en_el_cierre(self):
        """Se calculan las dos quincenas y luego se confirman: el cierre lee las líneas ya calculadas del borrador."""
        contrato = self._contrato()
        self._previo(contrato, date(2026, 4, 1), date(2026, 4, 15), MEDIO, retenido=321216.0, estado='draft')
        segunda = self._recibo(contrato, date(2026, 4, 16), date(2026, 4, 30))
        res = segunda._ne_retencion_mes({'DEV_SAL': MEDIO})
        self.assertAlmostEqual(res['retencion'], 321216.0, delta=1.0)

    def test_previo_sin_calcular_en_el_cierre_da_un_error_que_lo_nombra(self):
        contrato = self._contrato()
        previo = self._recibo(contrato, date(2026, 4, 1), date(2026, 4, 15))
        segunda = self._recibo(contrato, date(2026, 4, 16), date(2026, 4, 30))
        with self.assertRaises(UserError) as error:
            segunda._ne_retencion_mes({'DEV_SAL': MEDIO})
        self.assertIn(previo.display_name, str(error.exception))

    def test_previo_en_borrador_no_impide_calcular_un_recibo_que_no_cierra(self):
        contrato = self._contrato('weekly')
        self._previo(contrato, date(2026, 4, 1), date(2026, 4, 7), 2800000.0, retenido=149901.0, estado='draft')
        segundo = self._recibo(contrato, date(2026, 4, 8), date(2026, 4, 14))
        res = segundo._ne_retencion_mes({'DEV_SAL': 2800000.0})
        self.assertAlmostEqual(res['retencion'], 149901.0, delta=1.0)

    def test_previo_cancelado_se_ignora(self):
        contrato = self._contrato()
        self._previo(contrato, date(2026, 4, 1), date(2026, 4, 15), MEDIO, retenido=999999.0, estado='cancel')
        segunda = self._recibo(contrato, date(2026, 4, 16), date(2026, 4, 30))
        res = segunda._ne_retencion_mes({'DEV_SAL': SALARIO})
        self.assertAlmostEqual(res['retencion'], 642432.0, delta=1.0)

    # ── qué entra en la base ─────────────────────────────────────────
    def test_la_base_suma_salarial_vacaciones_e_incapacidades_y_deja_fuera_lo_no_salarial(self):
        recibo = self._recibo(self._contrato('monthly'), date(2026, 4, 1), date(2026, 4, 30))
        res = recibo._ne_retencion_mes({'DEV_SAL': 9000000.0, 'VAC': 1000000.0, 'INC': 500000.0, 'DEV_NOSAL': 300000.0})
        self.assertAlmostEqual(res['base_devengado'], 10500000.0, delta=0.01)

    def test_las_categorias_de_la_base_incluyen_horas_extra_y_excluyen_lo_no_salarial(self):
        codigos = set(self._recibo(self._contrato('monthly'), date(2026, 4, 1), date(2026, 4, 30))
                      ._ne_retencion_categorias_base().mapped('code'))
        self.assertTrue({'DEV_SAL', 'HEX', 'VAC', 'INC'} <= codigos)
        self.assertFalse({'DEV_NOSAL', 'PREST', 'DEV'} & codigos)

    def test_un_previo_con_horas_extra_y_no_salariales_suma_solo_lo_que_entra_en_la_base(self):
        """Previo: básico 5.000.000 + horas extra 1.000.000 (HEX, hija de DEV_SAL) + auxilio de transporte 300.000 (DEV_NOSAL):
        la base previa es 6.000.000 (no 6.300.000). Con el cierre de 6.000.000 el mes real es 12.000.000 -> 642.432 - 321.216."""
        contrato = self._contrato()
        previo = self._recibo(contrato, date(2026, 4, 1), date(2026, 4, 15), estado='paid')
        self._linea(previo, 'CO_BASICO', 5000000.0)
        self._linea(previo, 'CO_HED', 1000000.0)
        self._linea(previo, 'CO_AUX_TRANS', 300000.0)
        self._linea(previo, 'CO_RETEFUENTE_BASE_IBC', MEDIO)
        self._linea(previo, 'CO_RETEFUENTE', -321216.0)
        segunda = self._recibo(contrato, date(2026, 4, 16), date(2026, 4, 30))
        res = segunda._ne_retencion_mes({'DEV_SAL': MEDIO})
        self.assertAlmostEqual(res['retencion'], 321216.0, delta=1.0)

    # ── R-2b (doc 59 §20.9 y §25): reintegro de retención ────────────
    def test_un_reintegro_anterior_se_resta_de_lo_retenido(self):
        """Recibo previo con retención 321.216 y un reintegro de 100.000 (línea CO_REINTEGRO_RETE de un cierre anterior del
        mismo mes): lo retenido neto es 221.216; el cierre retiene 642.432 - 221.216 = 421.216."""
        contrato = self._contrato()
        previo = self._previo(contrato, date(2026, 4, 1), date(2026, 4, 15), MEDIO, retenido=321216.0)
        self._linea(previo, 'CO_REINTEGRO_RETE', 100000.0)
        segunda = self._recibo(contrato, date(2026, 4, 16), date(2026, 4, 30))
        res = segunda._ne_retencion_mes({'DEV_SAL': MEDIO})
        self.assertAlmostEqual(res['retencion'], 421216.0, delta=1.0)

    def test_la_regla_de_reintegro_va_antes_del_total_devengados_y_despues_de_todos_los_devengados(self):
        reglas = self.struct.with_context(active_test=False).rule_ids
        reintegro = reglas.filtered(lambda r: r.code == 'CO_REINTEGRO_RETE')
        self.assertEqual(len(reintegro), 1)
        self.assertLess(reintegro.sequence, reglas.filtered(lambda r: r.code == 'CO_BRUTO').sequence)
        devengados = reglas.filtered(lambda r: r.category_id.code in ('DEV_SAL', 'HEX', 'VAC', 'INC', 'DEV_NOSAL', 'PREST'))
        self.assertGreater(reintegro.sequence, max(devengados.mapped('sequence')))

    def test_el_reintegro_suma_al_neto_pero_no_a_la_base_ni_al_ibc(self):
        reintegro = self.struct.with_context(active_test=False).rule_ids.filtered(lambda r: r.code == 'CO_REINTEGRO_RETE')
        self.assertEqual(reintegro.category_id.code, 'REINT')
        self.assertEqual(reintegro.category_id.parent_id.code, 'DEV')           # cuenta en CO_BRUTO y CO_NETO (categories['DEV'])
        recibo = self._recibo(self._contrato('monthly'), date(2026, 4, 1), date(2026, 4, 30))
        codigos = set(recibo._ne_retencion_categorias_base().mapped('code'))
        self.assertNotIn('REINT', codigos)                                        # no entra a la base de la retención
        self.assertFalse({'DEV_SAL', 'DEV_NOSAL'} & {reintegro.category_id.code, reintegro.category_id.parent_id.code})

    def test_el_reintegro_se_reporta_a_la_dian_como_devengado_reintegro_y_con_tercero_dian(self):
        reintegro = self.struct.with_context(active_test=False).rule_ids.filtered(lambda r: r.code == 'CO_REINTEGRO_RETE')
        self.assertEqual(reintegro.l10n_co_ne_dian_concept, 'Reintegro')
        self.assertEqual(reintegro.l10n_co_tercero_origen, 'company_dian')
