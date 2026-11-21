# -*- coding: utf-8 -*-
"""Sin valores por defecto silenciosos (.181): tipo de contrato DIAN, tipo y subtipo de cotizante,
tipo y subtipo de trabajador, tipo de aportante y forma de presentacion PILA. v19: una versión colombiana
no pasa a tener contrato (``contract_date_start``, sustituto de 'En proceso', decisión D-A) sin ellos
(ValidationError); el XML y la PILA fallan con un error claro. Estas pruebas usan ``completar_tipos=False``."""

from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from .common_version import crear_contrato

CAMPOS_CONTRATO = ('l10n_co_ne_contract_type', 'l10n_co_pila_tipo_cotizante',
                   'l10n_co_pila_subtipo_cotizante')


@tagged('post_install', '-at_install')
class TestDefaultsSinAsumir(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        datos = {'l10n_co_pila_clase_riesgo': '1', 'l10n_co_ne_febrero_modo': 'real',
                 'l10n_co_ne_redondeo_dias': 'DOWN'}
        cls.co = cls.env['res.company'].create({
            'name': 'Empresa CO Defaults', 'country_id': cls.env.ref('base.co').id, **datos})
        cls.mx = cls.env['res.company'].create({
            'name': 'Empresa MX Defaults', 'country_id': cls.env.ref('base.mx').id})
        cls.tipo = cls.env['hr.payroll.structure.type'].create({
            'name': 'Prueba Defaults', 'country_id': cls.env.ref('base.co').id})

    def _vals(self, company, state='open', **extra):
        empleado = self.env['hr.employee'].create({
            'name': 'Emp %s %s' % (company.name, state), 'company_id': company.id})
        vals = {'name': 'Contrato Defaults', 'employee_id': empleado.id,
                'company_id': company.id, 'structure_type_id': self.tipo.id, 'wage': 2000000.0,
                'date_start': date(2026, 1, 1), 'state': state}
        vals.update(extra)
        return vals

    def _completos(self):
        return {'l10n_co_ne_contract_type': '2', 'l10n_co_pila_tipo_cotizante': '01',
                'l10n_co_pila_subtipo_cotizante': '00'}

    def test_los_campos_ya_no_traen_valor_por_defecto(self):
        contrato = self.env['hr.version'].default_get(list(CAMPOS_CONTRATO))
        self.assertEqual({k: v for k, v in contrato.items() if v}, {})
        empleado = self.env['hr.employee'].default_get(
            ['l10n_co_ne_worker_type', 'l10n_co_ne_worker_subtype'])
        self.assertEqual({k: v for k, v in empleado.items() if v}, {})
        compania = self.env['res.company'].default_get(
            ['l10n_co_pila_tipo_aportante', 'l10n_co_pila_forma_presentacion'])
        self.assertEqual({k: v for k, v in compania.items() if v}, {})

    def test_contrato_colombiano_en_proceso_sin_tipos_falla_nombrando_los_tres(self):
        vals = self._vals(self.co)
        with self.assertRaises(ValidationError) as exc:
            crear_contrato(self.env, vals, completar_tipos=False)
        msg = str(exc.exception)
        self.assertIn(self.env['hr.employee'].browse(vals['employee_id']).name, msg)
        for campo in CAMPOS_CONTRATO:
            self.assertIn(self.env['hr.version']._fields[campo].string, msg)

    def test_contrato_en_borrador_sin_tipos_guarda_y_no_pasa_a_en_proceso(self):
        contrato = crear_contrato(self.env, self._vals(self.co, state='draft'), completar_tipos=False)
        self.assertFalse(contrato.contract_date_start)
        with self.assertRaises(ValidationError):
            contrato.contract_date_start = date(2026, 1, 1)
        contrato.write(self._completos())
        contrato.contract_date_start = date(2026, 1, 1)
        self.assertEqual(contrato.contract_date_start, date(2026, 1, 1))

    def test_contrato_en_proceso_con_los_tres_campos_guarda(self):
        self.assertTrue(crear_contrato(self.env, self._vals(self.co, **self._completos())))

    def test_contrato_mexicano_no_exige_los_tipos_colombianos(self):
        self.assertTrue(crear_contrato(self.env, self._vals(self.mx), completar_tipos=False))

    def test_el_xml_y_la_pila_fallan_con_error_claro_si_falta_el_dato(self):
        contrato = crear_contrato(self.env, self._vals(self.co, state='draft'), completar_tipos=False)
        with self.assertRaises(UserError) as exc:
            contrato._ne_valor_obligatorio('l10n_co_ne_contract_type')
        self.assertIn(contrato.employee_id.name, str(exc.exception))
        self.assertIn('Tipo de Contrato DIAN', str(exc.exception))
        empleado = contrato.employee_id
        with self.assertRaises(UserError) as exc:
            empleado._ne_valor_obligatorio('l10n_co_ne_worker_type')
        self.assertIn(empleado.name, str(exc.exception))
        with self.assertRaises(UserError) as exc:
            self.co._ne_valor_obligatorio('l10n_co_pila_tipo_aportante')
        self.assertIn('Empresa CO Defaults', str(exc.exception))
        self.co.l10n_co_pila_tipo_aportante = '1'
        self.assertEqual(self.co._ne_valor_obligatorio('l10n_co_pila_tipo_aportante'), '1')
