# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""Pantallas del lote 1 de mejoras: solo componentes nativos."""

from lxml import etree

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPantallasLote1(TransactionCase):

    def _arbol(self, modelo, xmlid):
        return etree.fromstring(self.env[modelo].get_view(self.env.ref(xmlid).id, 'form')['arch'].encode())

    def test_la_actividad_arl_va_encima_de_la_clase_de_riesgo(self):
        """Q-59. v19: los campos del contrato se editan en la ficha del empleado."""
        arbol = self._arbol('hr.employee', 'hr.view_employee_form')
        actividad, = arbol.xpath("//group[@name='pila_cotizacion']//field[@name='l10n_co_pila_actividad_economica']")
        clase, = arbol.xpath("//group[@name='pila_cotizacion']//field[@name='l10n_co_pila_clase_riesgo']")
        self.assertEqual(actividad.getparent(), clase.getparent())
        hermanos = list(actividad.getparent())
        self.assertEqual(hermanos.index(clase), hermanos.index(actividad) + 1)
