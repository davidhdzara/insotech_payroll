# -*- coding: utf-8 -*-
"""H12 (2026-11-09): los 3 campos que agregamos a la pestaña "Detalles" del contrato se veían sin
etiqueta porque se inyectaban directo en el grupo EXTERIOR contract_details (col="2"); Odoo solo
genera la celda de etiqueta dentro de un grupo INTERIOR. Se verifica el arch guardado de la vista
y la vista combinada real: cada campo está dentro de un <group> interior."""

import unittest
from lxml import etree

from odoo.tests.common import TransactionCase, tagged

_CAMPOS = ('l10n_co_ne_contract_type', 'l10n_co_ne_integral_salary')


MOTIVO_BLOQUE_2 = (
    'H-V19-14: vistas de hr.version pendientes de portar. Registro de impacto v19: fila «Bloque 2 vistas del contrato» (tabla bajo '
    '«Bloque 1 — R2, X-1, Y-2») y §14. Las vistas del contrato (hr_contract_views.xml, hr_contract_deductions_views.xml y hr_contract_retefuente_views.xml) NO '
    'estan en el manifest (TL 2026-11-18, __manifest__.py:111-116): hr.contract y su formulario no existen y la pantalla de la version la decide David; sin '
    'esa vista no hay que probar. HUECO ABIERTO de F1 en v19, no un cierre: se reactiva y se reconvierte a hr.version cuando se porte la vista.')


@unittest.skip(MOTIVO_BLOQUE_2)
@tagged('post_install', '-at_install')
class TestContratoEtiquetas(TransactionCase):
    def test_campos_dentro_de_un_grupo_interior_en_el_arch_guardado(self):
        arch = etree.fromstring(
            self.env.ref('l10n_co_nomina_electronica.view_contract_form_ne').arch_db.encode('utf-8'))
        for campo in _CAMPOS:
            nodo = arch.xpath("//xpath[@expr=\"//group[@name='contract_details']\"]//field[@name='%s']" % campo)
            self.assertEqual(len(nodo), 1, campo)
            self.assertEqual(nodo[0].getparent().tag, 'group', 'Falta el <group> interior de %s' % campo)

    def test_campos_en_la_vista_combinada_dentro_de_contract_details(self):
        combinada = self.env['hr.contract'].get_view(
            self.env.ref('hr_contract.hr_contract_view_form').id, 'form')['arch']
        arch = etree.fromstring(combinada.encode('utf-8'))
        for campo in _CAMPOS:
            nodo = arch.xpath("//group[@name='contract_details']//group//field[@name='%s']" % campo)
            self.assertTrue(nodo, 'El campo %s no quedó en un grupo interior de contract_details.' % campo)
