# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""Pantallas del lote 1 de mejoras: solo componentes nativos."""

from lxml import etree

from odoo.tests.common import TransactionCase, tagged

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
