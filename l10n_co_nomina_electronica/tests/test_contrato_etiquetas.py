# -*- coding: utf-8 -*-
"""H12 (2026-11-09): los campos que agregamos a la pantalla del contrato se veían sin etiqueta porque se inyectaban directo en un grupo EXTERIOR; Odoo solo genera la celda de
etiqueta dentro de un grupo INTERIOR (sin subgrupos). Se verifica el arch guardado de la vista y la vista combinada real.

v19 (H-V19-14, bloque 2): no hay formulario de ``hr.contract``; los campos de la versión se editan en la ficha del empleado, en un grupo propio de la pestaña nativa «Nómina»."""

from lxml import etree

from odoo.tests.common import TransactionCase, tagged

_CAMPOS = ('l10n_co_ne_contract_type', 'l10n_co_ne_integral_salary')
_GRUPO = 'l10n_co_ne_contract_fields'


@tagged('post_install', '-at_install')
class TestContratoEtiquetas(TransactionCase):
    def test_campos_dentro_de_un_grupo_interior_en_el_arch_guardado(self):
        arch = etree.fromstring(
            self.env.ref('l10n_co_nomina_electronica.view_employee_form_ne_contrato').arch_db.encode('utf-8'))
        for campo in _CAMPOS:
            nodo = arch.xpath("//group[@name='%s']/field[@name='%s']" % (_GRUPO, campo))
            self.assertEqual(len(nodo), 1, campo)
            self.assertEqual(nodo[0].getparent().tag, 'group', 'Falta el <group> interior de %s' % campo)
            self.assertFalse(nodo[0].getparent().xpath('./group'), 'El grupo de %s tiene subgrupos: seria exterior y sin etiqueta' % campo)

    def test_campos_en_la_vista_combinada_dentro_de_payroll_information(self):
        combinada = self.env['hr.employee'].get_view(self.env.ref('hr.view_employee_form').id, 'form')['arch']
        arch = etree.fromstring(combinada.encode('utf-8'))
        for campo in _CAMPOS:
            nodo = arch.xpath("//page[@name='payroll_information']//group[@name='%s']/field[@name='%s']" % (_GRUPO, campo))
            self.assertEqual(len(nodo), 1, 'El campo %s no quedó en su grupo interior de la pestaña Nómina.' % campo)
