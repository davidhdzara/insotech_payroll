# -*- coding: utf-8 -*-
"""v19 (H-V19-14, bloque 2): la ficha del empleado es la pantalla del contrato. Cada campo propio de la versión aparece UNA sola vez; la propuesta y el aviso de la clase de
riesgo ARL funcionan en la ficha (los ``onchange`` de ``hr.version`` no corren en el formulario del empleado); el botón del Procedimiento 2 actúa sobre la versión que la ficha
muestra. NO ejecutadas al escribirlas (no hay Odoo local)."""

from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.tests import Form
from odoo.tests.common import TransactionCase, tagged

from .common_version import crear_aumento, crear_empleado_con_contrato

_CAMPOS_EN_LA_FICHA = (
    'l10n_co_ne_contract_type', 'l10n_co_ne_integral_salary',
    'l10n_co_pila_tipo_cotizante', 'l10n_co_pila_subtipo_cotizante', 'l10n_co_pila_salario_variable', 'l10n_co_pila_clase_riesgo', 'l10n_co_pila_centro_trabajo',
    'l10n_co_pila_actividad_economica', 'l10n_co_pila_tarifa_especial_afp',
    'l10n_co_ne_sindicato', 'l10n_co_ne_sindicato_partner_id', 'l10n_co_ne_afc', 'l10n_co_ne_afc_partner_id',
    'l10n_co_ne_pension_voluntaria', 'l10n_co_ne_pension_voluntaria_partner_id', 'l10n_co_ne_plan_complementario', 'l10n_co_ne_plan_complementario_partner_id',
    'l10n_co_ne_cooperativa', 'l10n_co_ne_cooperativa_partner_id', 'l10n_co_ne_educacion', 'l10n_co_ne_educacion_partner_id',
    'l10n_co_ne_retention_procedure', 'l10n_co_ne_retention_procedure2_ids')


@tagged('post_install', '-at_install')
class TestFichaContratoV19(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Ciiu = cls.env['l10n.co.pila.ciiu']
        cls.act_bajo = Ciiu.create({'code': 'V0001', 'name': 'Actividad de ficha de oficina', 'risk_class': '1'})
        cls.act_alto = Ciiu.create({'code': 'V0002', 'name': 'Actividad de ficha de minería', 'risk_class': '5'})
        cls.company = cls.env['res.company'].create({
            'name': 'Compañía Ficha Contrato', 'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U',
            'l10n_co_pila_clase_riesgo': '1', 'l10n_co_ne_febrero_modo': 'real', 'l10n_co_ne_redondeo_dias': 'DOWN'})
        estructura_tipo = cls.env['hr.payroll.structure.type'].create({'name': 'Prueba Ficha Contrato', 'country_id': cls.env.ref('base.co').id})
        cls.empleado, cls.version = crear_empleado_con_contrato(
            cls.env, cls.company, 1800000.0, date(2024, 1, 1), estructura_tipo, nombre='Empleado Ficha Contrato')
        cls.oficial = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Oficial Ficha', 'login': 'ficha_oficial', 'email': 'ficha_oficial@example.com', 'company_id': cls.company.id,
            'company_ids': [(6, 0, cls.company.ids)],
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('hr_payroll.group_hr_payroll_user').id])]})

    def _arch_ficha(self):
        vista = self.env.ref('hr.view_employee_form')
        return etree.fromstring(self.env['hr.employee'].get_view(vista.id, 'form')['arch'].encode())

    def _ficha_del_oficial(self):
        return self.empleado.with_user(self.oficial).with_context(allowed_company_ids=self.company.ids)

    def test_cada_campo_del_contrato_aparece_una_sola_vez_en_la_pestana_nomina(self):
        arch = self._arch_ficha()
        for campo in _CAMPOS_EN_LA_FICHA:
            with self.subTest(campo=campo):
                self.assertEqual(len(arch.xpath("//field[@name='%s']" % campo)), 1)
                self.assertEqual(len(arch.xpath("//page[@name='payroll_information']//field[@name='%s']" % campo)), 1)

    def test_alto_riesgo_del_contrato_no_se_muestra(self):
        """Decisión del TL: duplicaría «Pensión Alto Riesgo» del empleado, que es la que va al XML y a la UGPP."""
        arch = self._arch_ficha()
        self.assertFalse(arch.xpath("//field[@name='l10n_co_pila_indicador_alto_riesgo']"))
        self.assertEqual(len(arch.xpath("//field[@name='l10n_co_ne_high_risk_pension']")), 1)

    def test_la_ficha_propone_la_clase_de_riesgo_de_la_actividad(self):
        ficha = Form(self._ficha_del_oficial(), view='hr.view_employee_form')
        ficha.l10n_co_pila_actividad_economica = self.act_alto
        self.assertEqual(ficha.l10n_co_pila_clase_riesgo, '5')
        ficha.l10n_co_pila_clase_riesgo = '2'       # sigue editable
        self.assertEqual(ficha.l10n_co_pila_clase_riesgo, '2')

    def test_la_ficha_avisa_con_la_misma_logica_que_la_version(self):
        self.assertIn('l10n_co_pila_actividad_economica', self.env['hr.employee']._onchange_methods)
        self.assertIn('l10n_co_pila_clase_riesgo', self.env['hr.employee']._onchange_methods)
        self.empleado.write({'l10n_co_pila_actividad_economica': self.act_alto.id, 'l10n_co_pila_clase_riesgo': '2'})
        self.assertEqual(self.empleado.version_id.l10n_co_pila_clase_riesgo, '2', 'Premisa: la ficha escribe en la versión')
        aviso = self._ficha_del_oficial()._onchange_pila_clase_riesgo_vs_actividad()
        self.assertIn('warning', aviso)
        self.assertIn('V0002', aviso['warning']['message'])
        version = self.empleado.version_id.with_user(self.oficial).with_context(allowed_company_ids=self.company.ids)
        self.assertEqual(version._onchange_pila_clase_riesgo_vs_actividad(), aviso)
        self.empleado.write({'l10n_co_pila_clase_riesgo': '5'})
        self.assertFalse(self._ficha_del_oficial()._onchange_pila_clase_riesgo_vs_actividad())

    def test_boton_del_procedimiento_2_actua_sobre_la_version_que_muestra_la_ficha(self):
        antigua = self.version
        nueva = crear_aumento(self.env, self.empleado, antigua, date(2025, 1, 1), 2000000.0)
        self.assertEqual(self.empleado.current_version_id, nueva, 'Premisa: la versión actual es la nueva')
        self.assertEqual(len(self._arch_ficha().xpath("//button[@name='action_calculate_retention_procedure2']")), 1)
        llamadas = []

        def espia(version):
            llamadas.append(version.id)
            return True

        with patch.object(type(self.env['hr.version']), 'action_calculate_retention_procedure2', autospec=True, side_effect=espia):
            self.empleado.with_context(version_id=antigua.id).action_calculate_retention_procedure2()
            self.empleado.action_calculate_retention_procedure2()
        self.assertEqual(llamadas, [antigua.id, nueva.id])
