# -*- coding: utf-8 -*-
"""Pruebas del helper ``tests/common_version.crear_contrato`` (v19). NO ejecutado en Odoo.

Es el equivalente v19 de ``env['hr.contract'].create(vals)`` con el que se migraron ~98 llamadas de las pruebas del módulo. La N1 de las clases
de provisiones y de días por asistencia NO lo ejercita (usan ``crear_empleado_con_contrato``); estas pruebas existen para que la N1 cubra el
helper antes de fiarnos de esas 98 llamadas (decisión de TL, 2026-11-21). Hipótesis que comprueban, todas SIN LEER en el servidor (el cuerpo de
``hr.version.create/write`` no está leído): el marco crea una versión vacía con el empleado (``_inherits``, ``hr_employee.py:45, :1409-1410``), la
restricción D-A corre al escribir ``contract_date_start`` y ``hr.version`` no tiene ``state``."""

from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from .common_version import TIPOS_CONTRATO_DEFECTO, crear_contrato


@tagged('post_install', '-at_install')
class TestCrearContrato(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.co = cls.env['res.company'].create({
            'name': 'Empresa CO Helper', 'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_clase_riesgo': '1',
            'l10n_co_ne_febrero_modo': 'real', 'l10n_co_ne_redondeo_dias': 'DOWN'})
        cls.tipo = cls.env['hr.payroll.structure.type'].create({
            'name': 'Prueba Helper', 'country_id': cls.env.ref('base.co').id})

    def _empleado(self, nombre='Empleado Helper'):
        return self.env['hr.employee'].create({'name': nombre, 'company_id': self.co.id})

    def _versiones(self, empleado):
        return empleado.with_context(active_test=False).version_ids

    def _vals(self, empleado, inicio=date(2026, 1, 1), **extra):
        vals = {'name': 'Contrato Helper', 'employee_id': empleado.id, 'company_id': self.co.id,
                'structure_type_id': self.tipo.id, 'wage': 2000000.0, 'date_start': inicio, 'state': 'open'}
        vals.update(extra)
        return vals

    def test_la_primera_llamada_reutiliza_la_version_vacia_del_empleado(self):
        empleado = self._empleado()
        vacia = self._versiones(empleado)
        self.assertEqual(len(vacia), 1)
        self.assertFalse(vacia.contract_date_start)
        version = crear_contrato(self.env, self._vals(empleado))
        self.assertEqual(version, vacia)
        self.assertEqual(len(self._versiones(empleado)), 1)
        self.assertEqual((version.contract_date_start, version.date_version), (date(2026, 1, 1), date(2026, 1, 1)))
        self.assertEqual(version.wage, 2000000.0)
        self.assertEqual(version.structure_type_id, self.tipo)

    def test_la_segunda_llamada_crea_otra_version_y_get_version_elige_por_fecha(self):
        empleado = self._empleado()
        primera = crear_contrato(self.env, self._vals(empleado, state='close', date_end=date(2026, 6, 30)))
        segunda = crear_contrato(self.env, self._vals(empleado, inicio=date(2026, 7, 1)))
        self.assertNotEqual(primera, segunda)
        self.assertEqual(len(self._versiones(empleado)), 2)
        self.assertEqual(empleado._get_version(date(2026, 3, 1)), primera)
        self.assertEqual(empleado._get_version(date(2026, 8, 1)), segunda)

    def test_en_borrador_la_version_no_lleva_fechas_de_contrato(self):
        empleado = self._empleado()
        version = crear_contrato(self.env, self._vals(empleado, state='draft', date_end=date(2026, 6, 30)))
        self.assertFalse(version.contract_date_start)
        self.assertFalse(version.contract_date_end)
        self.assertEqual(version.date_version, date(2026, 1, 1))

    def test_sin_completar_tipos_la_restriccion_d_a_falla_y_por_defecto_los_completa(self):
        with self.assertRaises(ValidationError):
            crear_contrato(self.env, self._vals(self._empleado()), completar_tipos=False)
        version = crear_contrato(self.env, self._vals(self._empleado('Otro empleado helper')))
        for campo, valor in TIPOS_CONTRATO_DEFECTO.items():
            self.assertEqual(version[campo], valor, campo)

    def test_el_cierre_usa_contract_date_end_sin_state_y_la_compania_sale_del_empleado(self):
        empleado = self._empleado()
        version = crear_contrato(self.env, self._vals(empleado, state='close', date_end=date(2026, 3, 31)))
        self.assertEqual(version.contract_date_end, date(2026, 3, 31))
        self.assertEqual(version.company_id, self.co)
        self.assertEqual(version.name, 'Contrato Helper')
        self.assertNotIn('state', self.env['hr.version']._fields)       # premisa T4: hr.version no tiene estado
