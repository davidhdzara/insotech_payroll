# -*- coding: utf-8 -*-
"""Los campos y botones colombianos de contrato, empleado y recibo se ocultan fuera de Colombia
(doc 51, .179). Se comprueba el arch de las vistas heredadas: cada elemento colombiano lleva una
condicion `invisible` por pais (el mismo patron de l10n_mx_hr_payroll: country_code != 'MX')."""

from lxml import etree

from odoo.tests.common import TransactionCase


class TestVistasPorPais(TransactionCase):
    def _arch(self, modelo):
        return etree.fromstring(
            self.env[modelo].get_view(view_type='form')['arch'].encode())

    def _invisible(self, arbol, xpath):
        nodos = arbol.xpath(xpath)
        self.assertTrue(nodos, 'No esta en la vista: %s' % xpath)
        return nodos[0].get('invisible') or ''

    def test_contrato_oculta_lo_colombiano_fuera_de_colombia(self):
        arch = self._arch('hr.contract')
        self.assertIn("country_code != 'CO'", self._invisible(
            arch, "//group[@name='l10n_co_ne_contract_fields']"))
        self.assertIn("country_code != 'CO'", self._invisible(arch, "//page[@name='pila']"))

    def test_empleado_oculta_lo_colombiano_fuera_de_colombia(self):
        arch = self._arch('hr.employee')
        for grupo in ('dian_identification', 'work_location', 'payment_data',
                      'pila_administradoras'):
            self.assertIn("company_country_code != 'CO'", self._invisible(
                arch, "//group[@name='%s']" % grupo), grupo)

    def test_recibo_oculta_pagina_botones_y_estado_dian_fuera_de_colombia(self):
        arch = self._arch('hr.payslip')
        self.assertIn("country_code != 'CO'", self._invisible(
            arch, "//page[@name='nomina_electronica']"))
        self.assertIn("country_code != 'CO'", self._invisible(
            arch, "//div[@name='ne_statusbar']"))
        for boton in ('action_generate_ne_xml', 'action_regenerate_ne_xml', 'action_send_ne_dian',
                      'action_check_dian_status', 'action_create_adjustment',
                      'action_create_elimination'):
            self.assertIn("country_code != 'CO'", self._invisible(
                arch, "//button[@name='%s']" % boton), boton)
