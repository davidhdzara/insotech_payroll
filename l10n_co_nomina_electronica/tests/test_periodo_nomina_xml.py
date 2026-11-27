# -*- coding: utf-8 -*-
"""Q-17 (.332): «PeriodoNomina» del XML (Anexo V1.0, tabla 5.5.1) sale del calendario de pago de la versión del recibo, no de los días del recibo.
Porte v19 (hr.version.schedule_pay). NO ejecutado en Odoo."""

from datetime import date
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from .common_version import confirmar_a_mano, crear_empleado_con_contrato


@tagged('post_install', '-at_install')
class TestPeriodoNominaDelCalendario(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        compania = cls.env['res.company'].create({
            'name': 'Compañía Periodo Nómina', 'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_tipo_aportante': '1',
            'l10n_co_pila_forma_presentacion': 'U', 'l10n_co_pila_clase_riesgo': '1', 'l10n_co_ne_febrero_modo': 'real'})
        cls.tipo = cls.env['hr.payroll.structure.type'].create({'name': 'Tipo Periodo Nómina', 'country_id': cls.env.ref('base.co').id})
        estructura = cls.env['hr.payroll.structure'].create({'name': 'Estructura Periodo Nómina', 'type_id': cls.tipo.id})
        empleado, cls.version = crear_empleado_con_contrato(
            cls.env, compania, 3000000.0, date(2025, 1, 1), cls.tipo, nombre='Empleado Periodo', identification_id='1020304050')
        cls.recibo = cls.env['hr.payslip'].create({
            'name': 'Recibo Periodo', 'employee_id': empleado.id, 'version_id': cls.version.id, 'company_id': compania.id,
            'struct_id': estructura.id, 'date_from': date(2026, 2, 16), 'date_to': date(2026, 2, 28)})

    def _sin_calendario(self):
        self.tipo.default_schedule_pay = False
        self.version.schedule_pay = False

    def _sin_otros_requisitos(self):
        """Aísla el requisito del calendario: lo demás del XML (configuración, cuenta, nombres) se prueba aparte."""
        for objetivo, atributo in ((type(self.recibo), '_validate_company_ne_config'), (type(self.recibo), '_ne_validar_cuenta_transferencia'),
                                   (type(self.recibo.employee_id), '_l10n_co_nombre_dian')):
            parche = patch.object(objetivo, atributo, lambda *a, **k: None)
            parche.start()
            self.addCleanup(parche.stop)
        confirmar_a_mano(self.recibo)

    def test_el_codigo_sale_del_calendario_y_no_de_los_dias(self):
        # El recibo es del 16 al 28 de febrero (13 días): antes salía 3 con cualquier calendario.
        for calendario, codigo in (('weekly', '1'), ('bi-weekly', '3'), ('semi-monthly', '4'), ('monthly', '5'), ('daily', '6'),
                                   ('bi-monthly', '6'), ('quarterly', '6'), ('semi-annually', '6'), ('annually', '6')):
            with self.subTest(calendario=calendario):
                self.version.schedule_pay = calendario
                self.assertEqual(self.recibo._ne_periodo_nomina(), codigo)

    def test_un_mensual_que_ingresa_a_mitad_de_mes_sigue_siendo_mensual(self):
        self.version.schedule_pay = 'monthly'
        for desde, hasta in ((date(2026, 3, 20), date(2026, 3, 31)), (date(2026, 3, 26), date(2026, 3, 31))):
            self.recibo.write({'date_from': desde, 'date_to': hasta})
            self.assertEqual(self.recibo._ne_periodo_nomina(), '5')

    def test_sin_calendario_en_la_version_vale_el_del_tipo_de_estructura(self):
        self.tipo.default_schedule_pay = 'semi-monthly'
        self.version.schedule_pay = False
        self.assertEqual(self.recibo._ne_periodo_nomina(), '4')

    def test_sin_ningun_calendario_el_xml_por_recibo_se_detiene_sin_gastar_el_consecutivo(self):
        self._sin_otros_requisitos()
        self._sin_calendario()
        self.assertFalse(self.recibo._ne_periodo_nomina())
        with self.assertRaises(UserError) as error:
            self.recibo.action_generate_ne_xml()
        for texto in ('Empleado Periodo', 'Calendario de pago'):
            self.assertIn(texto, error.exception.args[0])
        self.assertFalse(self.recibo.l10n_co_ne_consecutive)

    def test_con_calendario_o_nota_eliminar_no_se_exige(self):
        self._sin_otros_requisitos()
        self.version.schedule_pay = 'monthly'
        self.recibo._validate_ne_prerequisites()
        self._sin_calendario()
        self.recibo.write({'l10n_co_ne_is_adjustment': True, 'l10n_co_ne_adjustment_type': '2', 'l10n_co_ne_adjustment_ref_cune': 'a' * 96})
        self.recibo._validate_ne_prerequisites()          # la nota «Eliminar» no lleva PeriodoNomina
        self.recibo.l10n_co_ne_adjustment_type = '1'
        with self.assertRaisesRegex(UserError, 'Calendario de pago'):
            self.recibo._validate_ne_prerequisites()      # la nota «Reemplazar» sí
