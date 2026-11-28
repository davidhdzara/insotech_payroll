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
