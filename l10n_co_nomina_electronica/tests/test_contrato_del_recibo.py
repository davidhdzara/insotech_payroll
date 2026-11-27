# -*- coding: utf-8 -*-
"""Q-15 (.332): un recibo de una compañía colombiana solo admite una versión de contrato de su empleado y de su compañía, también por RPC, importación o código.
Porte v19 (``version_id``). NO ejecutado en Odoo."""

from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from .common_version import crear_empleado_con_contrato


@tagged('post_install', '-at_install')
class TestContratoDelRecibo(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        valores = {'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U',
                   'l10n_co_pila_clase_riesgo': '1', 'l10n_co_ne_febrero_modo': 'real'}
        cls.compania = cls.env['res.company'].create(dict(valores, name='Compañía Contrato del Recibo'))
        cls.otra = cls.env['res.company'].create(dict(valores, name='Compañía Ajena del Recibo'))
        cls.tipo = cls.env['hr.payroll.structure.type'].create({'name': 'Tipo Contrato del Recibo', 'country_id': cls.env.ref('base.co').id})
        cls.estructura = cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')

    def _empleado(self, nombre, compania, tipo=None):
        return crear_empleado_con_contrato(self.env, compania, 3000000.0, date(2025, 1, 1), tipo or self.tipo, nombre=nombre)

    def _recibo(self, empleado, version, estructura=None):
        return self.env['hr.payslip'].create({
            'name': 'Recibo de %s' % empleado.name, 'employee_id': empleado.id, 'version_id': version.id, 'company_id': empleado.company_id.id,
            'struct_id': (estructura or self.estructura).id, 'date_from': date(2026, 3, 1), 'date_to': date(2026, 3, 15)})

    def test_el_contrato_propio_se_acepta(self):
        empleado, version = self._empleado('Propia', self.compania)
        recibo = self._recibo(empleado, version)
        self.assertEqual((recibo.version_id, recibo.company_id), (version, self.compania))

    def test_el_contrato_de_otro_empleado_se_rechaza_al_crear_y_al_cambiar(self):
        empleado, version = self._empleado('Titular', self.compania)
        _ajeno, version_ajena = self._empleado('Vecino', self.compania)
        with self.assertRaises(ValidationError) as error:
            self._recibo(empleado, version_ajena)
        for texto in ('Recibo de Titular', 'Titular', 'Vecino'):
            self.assertIn(texto, error.exception.args[0])
        recibo = self._recibo(empleado, version)
        with self.assertRaisesRegex(ValidationError, 'otro empleado o de otra'):
            recibo.version_id = version_ajena

    def test_el_contrato_de_otra_compania_se_rechaza(self):
        empleado, version = self._empleado('Trasladada', self.compania)
        # Escrito por debajo del ORM: el caso (datos importados) no depende de lo que el nativo deje escribir en la versión.
        self.env.flush_all()
        self.env.cr.execute('UPDATE hr_version SET company_id = %s WHERE id = %s', (self.otra.id, version.id))
        version.invalidate_recordset(['company_id'])
        with self.assertRaisesRegex(ValidationError, 'otro empleado o de otra'):
            self._recibo(empleado, version)

    def test_fuera_de_colombia_no_se_exige(self):
        mexico = self.env['res.company'].create({'name': 'Compañía Mexicana del Recibo', 'country_id': self.env.ref('base.mx').id})
        tipo = self.env['hr.payroll.structure.type'].create({'name': 'Tipo MX del Recibo', 'country_id': self.env.ref('base.mx').id})
        estructura = self.env['hr.payroll.structure'].create({'name': 'Estructura MX del Recibo', 'type_id': tipo.id})
        empleado, _version = self._empleado('Titular MX', mexico, tipo)
        _ajeno, version_ajena = self._empleado('Vecino MX', mexico, tipo)
        recibo = self._recibo(empleado, version_ajena, estructura)
        self.assertEqual(recibo.version_id, version_ajena)
