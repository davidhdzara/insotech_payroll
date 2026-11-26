# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""H-F1-10 (opción A; diseño aprobado por el TL el 25-nov): el lote nativo no generaba el recibo del tramo nuevo tras un cambio de versión dentro del contrato y creaba los recibos con las fechas del lote, así que dos
recibos del mismo mes no se podían confirmar. Ahora (solo Colombia y estructura general) A llega hasta la víspera, B sale desde el cambio y no se duplica. NO EJECUTADAS en Odoo al escribirlas."""

from datetime import date

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

    def test_la_prima_no_se_parte(self):
        empleado, version_a, _b = self._empleado()
        lote = self._lote(self.prima)
        self.assertEqual(lote._ne_versiones_por_tramo([version_a.id], MES[0], MES[1], self.prima.id, self.company.id), [version_a.id])
