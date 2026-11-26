# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""H-F1-10 (opción A; diseño aprobado por el TL el 25-nov): el lote nativo no generaba el recibo del tramo nuevo tras un cambio de versión dentro del contrato y creaba los recibos con las fechas del lote, así que dos
recibos del mismo mes no se podían confirmar. Ahora (solo Colombia y estructura general) A llega hasta la víspera, B sale desde el cambio y no se duplica. NO EJECUTADAS en Odoo al escribirlas."""

from datetime import date, timedelta
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from .common_version import crear_empleado_con_contrato

MES = (date(2026, 9, 1), date(2026, 9, 30))
CAMBIO = date(2026, 9, 10)


class MontajeLotePorTramo(TransactionCase):
    """Montaje compartido (sin pruebas propias)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U', 'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_clase_riesgo': '1',
            'l10n_co_ne_febrero_modo': 'real', 'l10n_co_ne_redondeo_dias': 'DOWN', 'name': 'Compañía Lote por Tramo'})
        cls.env = cls.company.with_company(cls.company).env
        cls.general = cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
        cls.prima = cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_prima')
        cls.n = 0

    def _empleado(self, aumento=True):
        type(self).n += 1
        empleado, version_a = crear_empleado_con_contrato(
            self.env, self.company, 3000000.0, date(2026, 1, 1), self.general.type_id, nombre='Empleado Tramo %s' % self.n)
        version_b = empleado.create_version({'date_version': CAMBIO, 'wage': 3600000.0}) if aumento else None
        return empleado, version_a, version_b

    def _lote(self, estructura=None):
        return self.env['hr.payslip.run'].create({
            'name': 'Lote Tramo', 'date_start': MES[0], 'date_end': MES[1], 'company_id': self.company.id, 'structure_id': (estructura or self.general).id})


@tagged('post_install', '-at_install')
class TestLotePorTramo(MontajeLotePorTramo):

    def test_el_lote_genera_a_hasta_la_vispera_y_b_desde_el_cambio(self):
        empleado, version_a, version_b = self._empleado()
        lote = self._lote()
        self.assertEqual(set(lote._get_valid_version_ids(employee_ids=empleado.ids)), {version_a.id, version_b.id})
        lote.generate_payslips(employee_ids=empleado.ids)
        recibos = lote.slip_ids.sorted('date_from')
        self.assertEqual([(r.version_id, r.date_from, r.date_to) for r in recibos],
                         [(version_a, MES[0], date(2026, 9, 9)), (version_b, CAMBIO, MES[1])])

    def test_repetir_la_seleccion_no_ofrece_lo_que_ya_tiene_recibo(self):
        empleado, _a, _b = self._empleado()
        lote = self._lote()
        lote.generate_payslips(employee_ids=empleado.ids)
        self.assertFalse(lote._get_valid_version_ids(employee_ids=empleado.ids))
        self.assertFalse(self._lote()._get_valid_version_ids(employee_ids=empleado.ids))

    def test_con_una_sola_version_las_fechas_son_las_del_lote(self):
        empleado, version_a, _b = self._empleado(aumento=False)
        lote = self._lote()
        lote.generate_payslips(employee_ids=empleado.ids)
        self.assertEqual([(r.version_id, r.date_from, r.date_to) for r in lote.slip_ids], [(version_a, MES[0], MES[1])])

    def _confirmar(self, recibos):
        """Confirma con las demás validaciones, el asiento y el nativo parchados: solo actúan los tramos y el solape. Devuelve el parche del nativo."""
        tipo = type(recibos)
        nombres = ['_ne_validar_duracion_periodo', '_ne_validar_cuenta_neto', '_ne_validar_pacto_no_salarial', '_ne_validar_afiliaciones', '_ne_validar_hoja_al_dia',
                   '_ne_aplicar_libranzas', '_ne_refrescar_ibc_mensual']
        if hasattr(tipo, '_action_create_account_move'):
            nombres.append('_action_create_account_move')
        parches = [patch.object(tipo, nombre) for nombre in nombres]
        for parche in parches:
            parche.start()
        try:
            with patch('odoo.addons.hr_payroll.models.hr_payslip.HrPayslip.action_payslip_done', return_value=True) as nativo:
                recibos.action_payslip_done()
        finally:
            for parche in parches:
                parche.stop()
        return nativo

    def _recibos_del_lote(self):
        empleado, version_a, version_b = self._empleado()
        lote = self._lote()
        lote.generate_payslips(employee_ids=empleado.ids)
        return empleado, version_a, lote.slip_ids.sorted('date_from')

    def test_a_y_b_del_lote_se_confirman_juntos(self):
        _empleado, _version, recibos = self._recibos_del_lote()
        self.assertEqual(len(recibos), 2)
        self.assertTrue(self._confirmar(recibos).called)

    def test_confirmar_sin_el_recibo_de_un_tramo_dice_cual_falta(self):
        empleado, _version, recibos = self._recibos_del_lote()
        for queda, falta in ((recibos[0], recibos[1]), ):
            desde = falta.date_from
            falta.unlink()
            with self.assertRaisesRegex(UserError, 'Falta el recibo') as caso:
                self._confirmar(queda)
            self.assertIn(empleado.name, str(caso.exception))
            self.assertIn(str(desde), str(caso.exception))

    def test_confirmar_b_sin_a_tambien_lo_dice(self):
        _empleado, _version, recibos = self._recibos_del_lote()
        recibos[0].unlink()
        with self.assertRaisesRegex(UserError, 'Falta el recibo'):
            self._confirmar(recibos[1])

    def test_un_recibo_que_incluye_el_cambio_no_se_confirma(self):
        empleado, version_a, _b = self._empleado()
        recibo = self.env['hr.payslip'].create({
            'name': 'Recibo completo', 'employee_id': empleado.id, 'version_id': version_a.id, 'company_id': self.company.id, 'struct_id': self.general.id,
            'date_from': MES[0], 'date_to': MES[1]})
        with self.assertRaisesRegex(UserError, 'incluye un cambio') as caso:
            self._confirmar(recibo)
        self.assertIn(str(CAMBIO), str(caso.exception))

    def test_la_pila_toma_los_datos_del_recibo_mas_reciente(self):
        _empleado, _version, recibos = self._recibos_del_lote()
        asistente = self.env['l10n.co.hr.pila.wizard.v2']
        for entrada in (recibos, recibos.sorted('date_from', reverse=True)):
            self.assertEqual(asistente._ne_recibo_mas_reciente(entrada), recibos[1])

    def _avisos_de_mes_partido(self, recibo):
        return [aviso for aviso in recibo._get_warnings_by_slip()[recibo] if 'Mes partido' in aviso['message']]

    def test_los_recibos_partidos_avisan_lo_que_se_repite_sin_bloquear(self):
        empleado, version_a, _b = self._empleado(aumento=False)
        version_a.write({'l10n_co_ne_sindicato': 50000.0})
        empleado.create_version({'date_version': CAMBIO, 'wage': 3600000.0})
        lote = self._lote()
        lote.generate_payslips(employee_ids=empleado.ids)
        recibos = lote.slip_ids
        self.assertEqual(len(recibos), 2)
        for recibo in recibos:
            avisos = self._avisos_de_mes_partido(recibo)
            self.assertEqual([aviso['level'] for aviso in avisos], ['warning'])
            sindicato = recibo.line_ids.filtered(lambda l: l.code == 'CO_SINDICATO')
            self.assertTrue(sindicato, 'Premisa: la cuota sindical sale en cada recibo')
            for fragmento in (sindicato.name, 'solidaridad', 'exoneración'):
                self.assertIn(fragmento, avisos[0]['message'])
        self.assertTrue(self._confirmar(recibos).called, 'El aviso no bloquea')

    def test_un_recibo_del_mes_completo_no_avisa(self):
        empleado, _a, _b = self._empleado(aumento=False)
        lote = self._lote()
        lote.generate_payslips(employee_ids=empleado.ids)
        self.assertFalse(self._avisos_de_mes_partido(lote.slip_ids))

    def test_la_prima_no_se_parte(self):
        empleado, version_a, _b = self._empleado()
        lote = self._lote(self.prima)
        self.assertEqual(lote._ne_versiones_por_tramo([version_a.id], MES[0], MES[1], self.prima.id, self.company.id), [version_a.id])


@tagged('post_install', '-at_install')
class TestDiasDelMesPartido(MontajeLotePorTramo):
    """H-F1-10: los dos tramos de un mes suman 30 días comerciales también si el cambio cae el último día (el mes comercial mapea ese día al 30: en febrero faltaban 2 días, 1 en bisiesto; en un mes de 31 sobraba 1)."""

    def _partido(self, cambio):
        empleado, version_a = self._empleado(aumento=False)[:2]
        version_b = empleado.create_version({'date_version': cambio, 'wage': 3600000.0})
        primero = cambio.replace(day=1)
        ultimo = (primero + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return [self.env['hr.payslip'].create({
            'name': 'Tramo %s' % desde, 'employee_id': empleado.id, 'version_id': version.id, 'company_id': self.company.id, 'struct_id': self.general.id, 'date_from': desde, 'date_to': hasta})
            for version, desde, hasta in ((version_a, primero, cambio - timedelta(days=1)), (version_b, cambio, ultimo))]

    def test_los_dos_tramos_suman_30_dias_en_febrero_bisiesto_y_mes_de_31(self):
        for cambio in (date(2026, 2, 28), date(2026, 2, 15), date(2028, 2, 29), date(2028, 2, 15), date(2026, 10, 31), date(2026, 10, 16), date(2026, 9, 30)):
            with self.subTest(cambio=cambio):
                a, b = self._partido(cambio)
                self.assertEqual(a._ne_dias_bajo_contrato() + b._ne_dias_bajo_contrato(), 30)

    def test_el_lote_con_cambio_el_ultimo_dia_de_febrero_paga_30_dias_de_sueldo(self):
        empleado, _version_a = self._empleado(aumento=False)[:2]
        empleado.create_version({'date_version': date(2026, 2, 28), 'wage': 3600000.0})
        lote = self.env['hr.payslip.run'].create({
            'name': 'Lote Febrero', 'date_start': date(2026, 2, 1), 'date_end': date(2026, 2, 28), 'company_id': self.company.id, 'structure_id': self.general.id})
        lote.generate_payslips(employee_ids=empleado.ids)
        basico = lote.slip_ids.line_ids.filtered(lambda linea: linea.code == 'CO_BASICO')
        self.assertEqual(sum(basico.mapped('quantity')), 30)
        self.assertAlmostEqual(sum(basico.mapped('total')), 3000000.0 / 30 * 27 + 3600000.0 / 30 * 3, delta=0.05)

    def test_una_ausencia_que_llega_al_fin_de_febrero_cuenta_como_en_el_mes_entero(self):
        a, b = self._partido(date(2026, 2, 28))

        def dias(recibo, desde, hasta):
            return recibo._ne_dias_corridos_en_tramo(desde, hasta, recibo.date_from, recibo.date_to, 30)

        self.assertEqual(dias(a, date(2026, 2, 27), date(2026, 2, 28)) + dias(b, date(2026, 2, 27), date(2026, 2, 28)), 4)
        self.assertEqual(dias(b, date(2026, 2, 28), date(2026, 2, 28)), 1)

    def test_un_recibo_solo_del_dia_31_con_ausencia_queda_en_cero_dias_y_nunca_negativo(self):
        _a, b = self._partido(date(2026, 10, 31))
        self.assertEqual(b._ne_dias_bajo_contrato(), 0)
        self.assertEqual(b._ne_dias_corridos_en_tramo(date(2026, 10, 31), date(2026, 10, 31), b.date_from, b.date_to, 30), 0)
        with patch.object(type(b), '_ne_dias_habiles_excluidos', return_value=1):       # ausencia de dias habiles el 31
            self.assertEqual(b._ne_dias_pagables(), 0)
