# -*- coding: utf-8 -*-
"""Etapa 1a del documento mensual (.190): el ciclo DIAN vive en el mixin l10n.co.ne.documento.mixin y
hr.payslip lo hereda sin cambiar de nombre ni de columnas. Prueba de carga: el registro tiene el mixin, el
modelo sigue siendo hr.payslip y conserva los campos y metodos del ciclo."""

from odoo.addons.l10n_co_nomina_electronica.models.l10n_co_ne_documento_mixin import (
    L10nCoNeDocumentoMixin)
from odoo.tests.common import TransactionCase, tagged

CAMPOS = (
    'l10n_co_ne_state', 'l10n_co_ne_cune', 'l10n_co_ne_xml_attachment_id', 'l10n_co_ne_dian_request',
    'l10n_co_ne_dian_response', 'l10n_co_ne_zip_key', 'l10n_co_ne_exchange_ids',
    'l10n_co_ne_is_adjustment', 'l10n_co_ne_adjustment_type', 'l10n_co_ne_hab_set_id',
    'l10n_co_ne_adjustment_ref_cune', 'l10n_co_ne_consecutive')
METODOS = (
    'action_generate_ne_xml', 'action_send_ne_dian', 'action_check_dian_status',
    'action_regenerate_ne_xml', 'action_send_test_set', 'action_create_adjustment',
    'action_create_elimination', '_cron_recheck_sent_status', '_get_next_ne_consecutive',
    '_ne_corrida_en_seco', '_validate_company_ne_config', '_ne_expected_prefix')


@tagged('post_install', '-at_install')
class TestDocumentoMixinCarga(TransactionCase):
    def test_el_mixin_esta_en_el_registro_y_es_abstracto(self):
        self.assertIn('l10n.co.ne.documento.mixin', self.env.registry)
        self.assertTrue(self.env.registry['l10n.co.ne.documento.mixin']._abstract)

    def test_el_recibo_sigue_siendo_hr_payslip_y_hereda_el_mixin(self):
        modelo = self.env['hr.payslip']
        self.assertEqual(modelo._name, 'hr.payslip')
        # el registro fusiona _inherit: la herencia real se ve en las clases base del modelo
        self.assertTrue(issubclass(type(modelo), L10nCoNeDocumentoMixin))
        self.assertIn('l10n_co_ne_state', modelo._fields)

    def test_el_recibo_conserva_los_campos_del_ciclo_dian(self):
        for campo in CAMPOS:
            self.assertIn(campo, self.env['hr.payslip']._fields, campo)

    def test_el_recibo_conserva_los_metodos_del_ciclo_dian(self):
        modelo = self.env['hr.payslip']
        for metodo in METODOS:
            self.assertTrue(callable(getattr(modelo, metodo, None)), metodo)

    def test_las_restricciones_unicas_del_cune_y_el_consecutivo_siguen_en_el_recibo(self):
        """v19 (X-1): ``_sql_constraints`` ya no crea nada; son ``models.Constraint`` declaradas en ``HrPayslip`` (el mixin es abstracto y no hay
        lectura de si una ``Constraint`` de un abstracto se aplica al modelo que lo hereda). Nombre en PostgreSQL = ``{tabla}_{nombre}``
        (``orm/table_objects.py:29,55-58``); ``_table_objects`` las indexa con ese nombre (``orm/model_classes.py:457-462``). Se comprueba en el
        registro Y en la base de datos."""
        esperadas = {'hr_payslip_l10n_co_ne_cune_unique', 'hr_payslip_l10n_co_ne_consecutive_company_unique'}
        self.assertLessEqual(esperadas, set(self.env['hr.payslip']._table_objects))
        self.env.cr.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'hr_payslip'::regclass")
        self.assertLessEqual(esperadas, {fila[0] for fila in self.env.cr.fetchall()})
