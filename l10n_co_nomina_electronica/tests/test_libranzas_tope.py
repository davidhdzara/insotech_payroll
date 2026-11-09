# -*- coding: utf-8 -*-
"""Libranzas por asignacion salarial con tope de la Ley 1527/2012.

cupo = 50% x neto de ley - embargos; atrasado primero (mas antiguo), luego la
cuota del periodo; lo que no cabe queda como saldo pendiente. Nivel de
verificacion: metodo de calculo y aplicacion/reversion sobre asignaciones
reales; la regla salarial completa se prueba al correr -u + suite en servidor.
"""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestLibranzasTope(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({'name': 'Empleado Libranzas'})
        cls.contract = cls.env['hr.contract'].create({
            'name': 'Contrato Libranzas', 'employee_id': cls.employee.id,
            'wage': 5000000, 'date_start': '2026-01-01', 'state': 'draft'})
        cls.slip = cls.env['hr.payslip'].create({
            'name': 'Nomina Libranzas', 'employee_id': cls.employee.id,
            'contract_id': cls.contract.id,
            'struct_id': cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina').id,
            'date_from': '2026-03-01', 'date_to': '2026-03-31'})
        cls.tipo = cls.env.ref('l10n_co_nomina_electronica.input_l10n_co_libranza')
        cls.entidad1 = cls.env['res.partner'].create({'name': 'Banco Uno'})
        cls.entidad2 = cls.env['res.partner'].create({'name': 'Banco Dos'})

    def _libranza(self, cuota, entidad, inicio='2026-01-01', saldo=0.0):
        return self.env['hr.salary.attachment'].create({
            'description': 'Libranza %s' % entidad.name,
            'employee_ids': [(6, 0, [self.employee.id])],
            'other_input_type_id': self.tipo.id, 'monthly_amount': cuota,
            'date_start': inicio, 'no_end_date': True,
            'l10n_co_partner_id': entidad.id, 'l10n_co_saldo_pendiente': saldo})

    def _filas(self):
        return {r.attachment_id: r for r in self.env['l10n.co.payslip.tercero'].search(
            [('slip_id', '=', self.slip.id), ('rule_code', '=', 'CO_LIBRANZAS')])}

    def test_tope_sobre_la_suma_y_cupo_con_embargo(self):
        # neto de ley 4.600.000, embargo 1.000.000 -> cupo 1.300.000
        a1 = self._libranza(800000, self.entidad1, '2026-01-01')
        a2 = self._libranza(700000, self.entidad2, '2026-02-01')
        total = self.slip._ne_libranzas_calcular(4600000.0, 1000000.0)
        self.assertAlmostEqual(total, 1300000.0)
        filas = self._filas()
        self.assertAlmostEqual(filas[a1].amount, 800000.0)
        self.assertAlmostEqual(filas[a2].amount, 500000.0)
        self.assertAlmostEqual(filas[a2].deferred, 200000.0)
        self.assertEqual(filas[a2].partner_id, self.entidad2)

    def test_sin_embargo_ejemplo_de_david(self):
        # neto de ley 4.600.000 -> maximo descontable 2.300.000
        self._libranza(1500000, self.entidad1)
        self._libranza(1500000, self.entidad2, '2026-02-01')
        self.assertAlmostEqual(self.slip._ne_libranzas_calcular(4600000.0, 0.0), 2300000.0)

    def test_atrasado_primero_y_luego_cuota(self):
        a1 = self._libranza(500000, self.entidad1, '2026-01-01', saldo=300000)
        a2 = self._libranza(500000, self.entidad2, '2026-02-01')
        # cupo 600.000: atraso 300.000 de a1, luego cuota a1 300.000 y a2 0
        total = self.slip._ne_libranzas_calcular(1200000.0, 0.0)
        self.assertAlmostEqual(total, 600000.0)
        filas = self._filas()
        self.assertAlmostEqual(filas[a1].arrears_paid, 300000.0)
        self.assertAlmostEqual(filas[a1].amount, 600000.0)
        self.assertAlmostEqual(filas[a1].deferred, 200000.0)
        self.assertAlmostEqual(filas[a2].amount, 0.0)
        self.assertAlmostEqual(filas[a2].deferred, 500000.0)

    def test_aplicar_y_revertir_saldo_pendiente(self):
        a1 = self._libranza(500000, self.entidad1, '2026-01-01', saldo=300000)
        self.slip._ne_libranzas_calcular(1200000.0, 0.0)
        self.slip._ne_aplicar_libranzas()
        self.assertAlmostEqual(a1.l10n_co_saldo_pendiente, 200000.0)  # 300-300+200
        self.assertAlmostEqual(a1.paid_amount, 600000.0)
        self.slip._ne_aplicar_libranzas(revertir=True)
        self.assertAlmostEqual(a1.l10n_co_saldo_pendiente, 300000.0)
        self.assertAlmostEqual(a1.paid_amount, 0.0)

    def test_libranza_sin_entidad_da_error_claro(self):
        a = self._libranza(100000, self.entidad1)
        a.l10n_co_partner_id = False
        with self.assertRaises(UserError) as e:
            self.slip._ne_libranzas_calcular(4600000.0, 0.0)
        self.assertIn('Juzgado / Entidad', str(e.exception))

    def test_secuencia_embargo_antes_que_libranzas(self):
        reglas = self.env['hr.salary.rule']
        emb = reglas.search([('code', '=', 'CO_EMBARGO'), ('struct_id', '=', self.slip.struct_id.id)])
        lib = reglas.search([('code', '=', 'CO_LIBRANZAS'), ('struct_id', '=', self.slip.struct_id.id)])
        self.assertEqual(len(lib), 1)
        self.assertLess(emb.sequence, lib.sequence)
        for codigo in ('CO_SINDICATO', 'CO_AFC', 'CO_PENSION_VOL', 'CO_COOPERATIVA'):
            r = reglas.search([('code', '=', codigo), ('struct_id', '=', self.slip.struct_id.id)])
            self.assertLess(lib.sequence, r.sequence)
