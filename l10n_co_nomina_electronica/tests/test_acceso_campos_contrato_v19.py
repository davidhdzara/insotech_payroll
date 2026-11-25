# -*- coding: utf-8 -*-
"""v19 (H-V19-14, decisión del TL del 25-nov): los 23 campos propios de la versión del contrato son SOLO de usuarios de nómina (``hr_payroll.group_hr_payroll_user``), en la versión y en la
ficha del empleado. En v19 los responsables de Empleados (``hr.group_hr_user``) tienen permiso completo sobre ``hr.version``: sin ``groups`` leían y escribían aporte sindical, AFC,
pensión voluntaria, etc. En v18 vivían en ``hr.contract``. El campo heredado de la ficha NO se redeclara: Odoo copia los ``groups`` y lo crea sin ``related_sudo``; si en el servidor no
fuera así, ``test_la_ficha_hereda_los_grupos_de_la_version`` falla. NO ejecutadas al escribirlas (no hay Odoo local)."""

from datetime import date

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from . import test_documento_generar_real as real
from .common_version import crear_empleado_con_contrato

GRUPO_NOMINA = 'hr_payroll.group_hr_payroll_user'
_CAMPOS = (
    'l10n_co_ne_contract_type', 'l10n_co_ne_integral_salary',
    'l10n_co_pila_tipo_cotizante', 'l10n_co_pila_subtipo_cotizante', 'l10n_co_pila_salario_variable', 'l10n_co_pila_clase_riesgo', 'l10n_co_pila_centro_trabajo',
    'l10n_co_pila_actividad_economica', 'l10n_co_pila_indicador_alto_riesgo', 'l10n_co_pila_tarifa_especial_afp',
    'l10n_co_ne_sindicato', 'l10n_co_ne_sindicato_partner_id', 'l10n_co_ne_afc', 'l10n_co_ne_afc_partner_id',
    'l10n_co_ne_pension_voluntaria', 'l10n_co_ne_pension_voluntaria_partner_id', 'l10n_co_ne_plan_complementario', 'l10n_co_ne_plan_complementario_partner_id',
    'l10n_co_ne_cooperativa', 'l10n_co_ne_cooperativa_partner_id', 'l10n_co_ne_educacion', 'l10n_co_ne_educacion_partner_id',
    'l10n_co_ne_retention_procedure')


def _usuario(env, compania, login, *grupos):
    refs = ('base.group_user',) + grupos
    return env['res.users'].with_context(no_reset_password=True).create({
        'name': login, 'login': login, 'email': '%s@example.com' % login, 'company_id': compania.id, 'company_ids': [(6, 0, compania.ids)],
        'group_ids': [(6, 0, [env.ref(g).id for g in refs])]})


@tagged('post_install', '-at_install')
class TestAccesoCamposContratoV19(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Compañía Acceso Contrato', 'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U',
            'l10n_co_pila_clase_riesgo': '1', 'l10n_co_ne_febrero_modo': 'real', 'l10n_co_ne_redondeo_dias': 'DOWN'})
        cls.estructura_tipo = cls.env['hr.payroll.structure.type'].create({'name': 'Prueba Acceso Contrato', 'country_id': cls.env.ref('base.co').id})
        cls.empleado, cls.version = crear_empleado_con_contrato(
            cls.env, cls.company, 30000000.0, date(2024, 1, 1), cls.estructura_tipo, nombre='Empleado Acceso Contrato')
        cls.rrhh = _usuario(cls.env, cls.company, 'acceso_empleados', 'hr.group_hr_user')
        cls.oficial = _usuario(cls.env, cls.company, 'acceso_oficial', GRUPO_NOMINA)

    def _como(self, registro, usuario):
        return registro.with_user(usuario).with_context(allowed_company_ids=self.company.ids)

    def _sql_en_la_version(self, version, columna, valor):
        """Escribe un dato directamente en la base (salta las validaciones del ORM) para montar un contrato que ya incumple."""
        self.env.flush_all()
        self.env.cr.execute('UPDATE hr_version SET %s = %%s WHERE id = %%s' % columna, [valor, version.id])
        self.env.invalidate_all()

    def test_la_ficha_hereda_los_grupos_de_la_version(self):
        for campo in _CAMPOS:
            with self.subTest(campo=campo):
                self.assertEqual(self.env['hr.version']._fields[campo].groups, GRUPO_NOMINA)
                heredado = self.env['hr.employee']._fields[campo]
                self.assertTrue(heredado.inherited)
                self.assertEqual(heredado.groups, GRUPO_NOMINA)
                self.assertFalse(heredado.compute_sudo, 'El campo heredado no puede leer con sudo (related_sudo)')

    def test_empleados_sin_nomina_no_lee_ni_escribe_por_la_ficha_ni_por_la_version(self):
        self.assertTrue(self.rrhh.has_group('hr.group_hr_user'), 'Premisa: responsable de Empleados')
        self.assertFalse(self.rrhh.has_group(GRUPO_NOMINA), 'Premisa: sin nómina')
        ficha, version = self._como(self.empleado, self.rrhh), self._como(self.version, self.rrhh)
        for campo in _CAMPOS:
            for via, registro in (('ficha', ficha), ('version', version)):
                with self.subTest(campo=campo, via=via, operacion='leer'):
                    with self.assertRaises(AccessError):
                        registro.read([campo])
                with self.subTest(campo=campo, via=via, operacion='escribir'):
                    with self.assertRaises(AccessError):
                        registro.write({campo: False})

    def test_el_oficial_de_nomina_lee_y_escribe(self):
        ficha, version = self._como(self.empleado, self.oficial), self._como(self.version, self.oficial)
        self.assertEqual(len(ficha.read(list(_CAMPOS))), 1)
        self.assertEqual(len(version.read(list(_CAMPOS))), 1)
        ficha.write({'l10n_co_pila_centro_trabajo': 'CT-1'})
        self.assertEqual(self.version.l10n_co_pila_centro_trabajo, 'CT-1')
        version.write({'l10n_co_pila_centro_trabajo': 'CT-2'})
        self.assertEqual(self.empleado.l10n_co_pila_centro_trabajo, 'CT-2')

    def test_empleados_sin_nomina_cambia_la_version_sin_access_error(self):
        self._como(self.empleado, self.rrhh).write({'job_title': 'Cargo cambiado por Empleados'})
        self.assertEqual(self.version.job_title, 'Cargo cambiado por Empleados')
        nueva = self._como(self.empleado, self.rrhh).create_version({'date_version': date(2025, 6, 1)})
        self.assertNotEqual(nueva.id, self.version.id)

    def test_empleados_sin_nomina_da_de_alta_un_empleado_colombiano(self):
        empleado = self._como(self.env['hr.employee'], self.rrhh).create({
            'name': 'Alta por Empleados', 'company_id': self.company.id,
            'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00', 'l10n_co_ne_payment_method': '10'})
        self.assertTrue(empleado.id)

    def test_la_version_nueva_creada_por_empleados_conserva_los_valores(self):
        """Si la copia saltara los campos restringidos, la nómina dejaría de descontar sin avisar."""
        actividad = self.env['l10n.co.pila.ciiu'].create({'code': 'A0001', 'name': 'Actividad de acceso', 'risk_class': '3'})
        valores = {
            'l10n_co_ne_contract_type': '1', 'l10n_co_ne_integral_salary': True, 'l10n_co_pila_tipo_cotizante': '51', 'l10n_co_pila_subtipo_cotizante': '01',
            'l10n_co_pila_salario_variable': True, 'l10n_co_pila_clase_riesgo': '3', 'l10n_co_pila_centro_trabajo': 'CT-9',
            'l10n_co_pila_actividad_economica': actividad.id, 'l10n_co_pila_indicador_alto_riesgo': True, 'l10n_co_pila_tarifa_especial_afp': 'T-1'}
        for orden, nombre in enumerate(('sindicato', 'afc', 'pension_voluntaria', 'plan_complementario', 'cooperativa', 'educacion'), 1):
            tercero = self.env['res.partner'].create({'name': 'Entidad %s' % nombre, 'l10n_co_entity_type': 'other'})
            valores.update({'l10n_co_ne_%s' % nombre: 1000.0 * orden, 'l10n_co_ne_%s_partner_id' % nombre: tercero.id})
        self.version.write(valores)
        self._sql_en_la_version(self.version, 'l10n_co_ne_retention_procedure', '2')   # el cambio por ORM solo se admite en junio o diciembre
        self.assertEqual(set(valores) | {'l10n_co_ne_retention_procedure'}, set(_CAMPOS), 'Premisa: se llenan los 23')
        nueva = self._como(self.empleado, self.rrhh).create_version({'date_version': date(2025, 6, 1)}).sudo()
        self.assertNotEqual(nueva.id, self.version.id)
        for campo in _CAMPOS:
            with self.subTest(campo=campo):
                self.assertTrue(self.version[campo], 'Premisa: el campo tiene valor')
                self.assertEqual(nueva[campo], self.version[campo])

    def test_la_restriccion_de_tipos_da_su_error_a_quien_no_es_de_nomina(self):
        self._sql_en_la_version(self.version, 'l10n_co_pila_tipo_cotizante', None)
        with self.assertRaises(ValidationError):
            self._como(self.version, self.rrhh)._check_tipos_obligatorios_en_proceso()
        with self.assertRaises(ValidationError):
            self._como(self.empleado, self.rrhh).create_version({'date_version': date(2025, 6, 1)})

    def test_el_piso_integral_da_su_error_a_quien_no_es_de_nomina(self):
        self._sql_en_la_version(self.version, 'wage', 1800000.0)
        self._sql_en_la_version(self.version, 'l10n_co_ne_integral_salary', True)
        with self.assertRaises(ValidationError):
            self._como(self.version, self.rrhh)._ne_validar_piso_integral()
        with self.assertRaises(ValidationError):
            self._como(self.empleado, self.rrhh).create_version({'date_version': date(2025, 6, 1)})


@tagged('post_install', '-at_install')
class TestOficialCalculaSinAccessError(real.TestDocumentoGenerarReal):
    """El Oficial de Nómina (sin ser administrador) calcula con los campos restringidos. Hereda la fixture de ``TestDocumentoGenerarReal`` (compañía, empleado, contrato y recibos
    reales). Generar o transmitir el XML y el asistente de la PILA siguen siendo del ADMINISTRADOR de nómina (guarda H-F2-03 y ACL del asistente): aquí se ejercen con el oficial el
    cálculo del recibo, la recolección de datos del XML, las lecturas del contrato que usa la PILA y el comprobante."""

    def test_el_oficial_calcula_recibo_datos_del_xml_pila_y_reporte(self):
        oficial = _usuario(self.env, self.company, 'acceso_oficial_calculo', GRUPO_NOMINA)
        self.contrato.write({'l10n_co_pila_centro_trabajo': 'CT-1'})
        contexto = {'allowed_company_ids': self.company.ids}
        recibo = self.env['hr.payslip'].with_user(oficial).with_context(**contexto).create({
            'name': 'Q abril del oficial', 'employee_id': self.empleado.id, 'version_id': self.contrato.id, 'company_id': self.company.id,
            'struct_id': self.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina').id,
            'date_from': date(2026, 4, 1), 'date_to': date(2026, 4, 15)})
        recibo.compute_sheet()
        self.assertTrue(recibo.line_ids)

        datos = recibo._collect_payslip_data()
        self.assertEqual(datos['trabajador']['TipoContrato'], '2')
        self.assertEqual(datos['trabajador']['SalarioIntegral'], 'false')

        version = self.contrato.with_user(oficial).with_context(**contexto)
        self.assertEqual(version._ne_valor_obligatorio('l10n_co_pila_tipo_cotizante'), '01')
        self.assertEqual(version._ne_valor_obligatorio('l10n_co_pila_subtipo_cotizante'), '00')
        self.assertEqual(version._ne_clase_riesgo(), '1')
        self.assertEqual(version._ne_centro_trabajo(), 'CT-1')
        version._ne_horas_laboradas_pila(15, date(2026, 4, 15))

        html, _tipo = self.env['ir.actions.report'].with_user(oficial).with_context(**contexto)._render_qweb_html(
            'l10n_co_nomina_electronica.action_report_payslip_ne', recibo.ids)
        self.assertIn(self.empleado.name.encode(), html)
