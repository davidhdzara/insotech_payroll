# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""Pantallas del lote 1 de mejoras: solo componentes nativos."""

from datetime import datetime

from lxml import etree

from odoo.tests.common import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

PREFIJO = 'l10n_co_nomina_electronica.'


@tagged('post_install', '-at_install')
class TestPantallasLote1(TransactionCase):

    def _arbol(self, modelo, xmlid):
        return etree.fromstring(self.env[modelo].get_view(self.env.ref(xmlid).id, 'form')['arch'])

    def test_la_actividad_arl_va_encima_de_la_clase_de_riesgo(self):
        """Q-59."""
        arbol = self._arbol('hr.contract', 'hr_contract.hr_contract_view_form')
        actividad, = arbol.xpath("//page[@name='pila']//field[@name='l10n_co_pila_actividad_economica']")
        clase, = arbol.xpath("//page[@name='pila']//field[@name='l10n_co_pila_clase_riesgo']")
        self.assertEqual(actividad.getparent(), clase.getparent())
        hermanos = list(actividad.getparent())
        self.assertEqual(hermanos.index(clase), hermanos.index(actividad) + 1)

    def test_las_filas_que_genera_la_actualizacion_salen_en_espanol(self):
        """Q-38: ``-u`` corre en inglés y las filas son texto guardado («Attendance»)."""
        self.env['res.lang']._activate_lang('es_CO')
        idiomas = []
        modelo = type(self.env['hr.payslip'])
        self.patch(modelo, '_ne_regenerar_conceptos', lambda recibos: idiomas.append(recibos.env.lang))
        self.env['hr.payslip'].with_context(lang='en_US')._ne_generar_conceptos_pendientes()
        self.assertEqual(idiomas, ['es_CO'])

    def test_en_una_compania_colombiana_el_asistente_solo_ofrece_estructuras_de_colombia(self):
        """Q-48; en una compañía de otro país queda igual que en el nativo (sin filtro)."""
        Asistente = self.env['hr.payslip.employees']
        arbol = self._arbol('hr.payslip.employees', 'hr_payroll.view_hr_payslip_by_employees')
        for campo in arbol.xpath("//field[@name='structure_id']"):
            self.assertFalse(campo.get('domain'), 'La vista nativa no impone otro filtro que tape el del campo')
        for pais, colombiana in (('base.co', True), ('base.mx', False)):
            with self.subTest(pais):
                company = self.env['res.company'].create({'name': 'Compañía Estructuras %s' % pais, 'country_id': self.env.ref(pais).id})
                dominio = Asistente.with_company(company).fields_get(['structure_id'])['structure_id'].get('domain')
                estructuras = self.env['hr.payroll.structure'].with_context(active_test=True).search(list(dominio or []))
                if colombiana:
                    self.assertEqual(set(estructuras.mapped('country_id.code')), {'CO'})
                else:
                    self.assertFalse(dominio)

    def test_la_entrada_de_trabajo_se_valida_desde_su_ficha(self):
        """Q-58: botón con la validación nativa, solo en borrador."""
        arbol = self._arbol('hr.work.entry', 'hr_work_entry.hr_work_entry_view_form')
        boton, = arbol.xpath("//header/button[@name='action_validate']")
        self.assertEqual((boton.get('type'), boton.get('invisible'), boton.get('string')), ('object', "state != 'draft'", 'Validar'))
        empleado = self.env['hr.employee'].create({'name': 'Entrada de trabajo', 'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00', 'l10n_co_ne_payment_method': '10'})
        contrato = self.env['hr.contract'].create({
            'name': 'Contrato entrada', 'employee_id': empleado.id, 'wage': 3000000.0, 'date_start': datetime(2026, 1, 1).date(), 'state': 'open',
            'l10n_co_ne_contract_type': '2', 'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00'})
        entrada = self.env['hr.work.entry'].create({
            'name': 'Asistencia de prueba', 'employee_id': empleado.id, 'contract_id': contrato.id, 'date_start': datetime(2026, 10, 5, 13), 'date_stop': datetime(2026, 10, 5, 17),
            'work_entry_type_id': self.env.ref('hr_work_entry.work_entry_type_attendance').id})
        entrada.action_validate()
        self.assertEqual(entrada.state, 'validated')

    def test_enviar_y_procesar_sale_en_un_recibo_pagado_sin_documento(self):
        """Q-73: en Producción; en habilitación el ciclo por recibo exige «Hecho»."""
        arbol = self._arbol('hr.payslip', 'hr_payroll.view_hr_payslip_form')
        boton, = [b for b in arbol.xpath("//header/button[@string='Enviar y Procesar']")]
        base = {'country_code': 'CO', 'l10n_co_ne_documento_id': False, 'l10n_co_ne_state': 'draft', 'l10n_co_ne_en_produccion': True}
        casos = (({'state': 'paid'}, False), ({'state': 'done'}, False), ({'state': 'paid', 'l10n_co_ne_en_produccion': False}, True),
                 ({'state': 'done', 'l10n_co_ne_en_produccion': False}, False), ({'state': 'verify'}, True), ({'state': 'paid', 'l10n_co_ne_state': 'accepted'}, True),
                 ({'state': 'paid', 'country_code': 'MX'}, True))
        for cambios, oculto in casos:
            with self.subTest(**cambios):
                self.assertEqual(bool(safe_eval(boton.get('invisible'), dict(base, **cambios))), oculto)
