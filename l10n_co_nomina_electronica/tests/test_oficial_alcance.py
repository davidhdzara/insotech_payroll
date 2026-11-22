# -*- coding: utf-8 -*-
"""Frente 6, P6-3 (doc 59 4.4, F6-ROL), alineada a v19 (orden de TL, 2026-11-22): la visibilidad del documento mensual, sus intentos, el IBC mensual y el
reparto por tercero es la del recibo NATIVO de v19. La regla nativa del oficial, ``hr_payroll_rule_officer``, es ``[(1,'=',1)]``
(``enterprise/hr_payroll/security/hr_payroll_security.xml:37-42``) y la del administrador, ``hr_payslip_rule_manager``, también (:44-49): el oficial de nómina
VE TODO dentro de las compañías permitidas (en v18 se limitaba por empleado propio, sin departamento o jefe del departamento) y solo queda la regla
multicompañía (``company_id in company_ids``). Un usuario de OTRA compañía no ve nada; un usuario interno sin rol de nómina no ve nada. Usuarios REALES
con correo. NO EJECUTADAS en Odoo."""

import ast
from datetime import date

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from .common_documento import DocumentoFixture

CUNE = 'c' * 96


@tagged('post_install', '-at_install')
class TestOficialAlcance(DocumentoFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture_documento('Compañía Alcance Oficial')
        grupo_base = cls.env.ref('base.group_user').id

        # ``groups_id`` en Odoo 18, ``group_ids`` en 19 (NO VERIFICADO el nombre en 19): se elige por ``_fields``, como ``common_version.crear_usuario_nomina``.
        campo_grupos = 'group_ids' if 'group_ids' in cls.env['res.users']._fields else 'groups_id'
        cls.company_b = cls.env['res.company'].create({'name': 'Compañía B Alcance Oficial', 'country_id': cls.env.ref('base.co').id})

        def usuario(clave, grupo=None, compania=None):
            compania = compania or cls.company
            grupos = [grupo_base] + ([cls.env.ref(grupo).id] if grupo else [])
            return cls.env['res.users'].with_context(no_reset_password=True).create({
                'name': 'Alcance %s' % clave, 'login': 'alcance_%s' % clave,
                'email': 'alcance_%s@example.com' % clave, 'company_id': compania.id,
                'company_ids': [(6, 0, compania.ids)], campo_grupos: [(6, 0, grupos)]})

        cls.oficial = usuario('oficial', 'hr_payroll.group_hr_payroll_user')
        cls.oficial_otra_compania = usuario('oficial_b', 'hr_payroll.group_hr_payroll_user', cls.company_b)
        cls.administrador = usuario('administrador', 'hr_payroll.group_hr_payroll_manager')
        cls.interno = usuario('interno')
        cls.gerente_ajeno = usuario('gerente_ajeno')
        depto_ajeno = cls.env['hr.department'].create({
            'name': 'Departamento ajeno alcance', 'company_id': cls.company.id,
            'manager_id': cls.env['hr.employee'].create({
                'name': 'Gerente ajeno', 'company_id': cls.company.id, 'user_id': cls.gerente_ajeno.id,
                'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00'}).id})
        depto_propio = cls.env['hr.department'].create({
            'name': 'Departamento propio alcance', 'company_id': cls.company.id,
            'manager_id': cls.env['hr.employee'].create({
                'name': 'Gerente oficial', 'company_id': cls.company.id, 'user_id': cls.oficial.id,
                'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00'}).id})
        cls.docs = {}
        for clave, depto in (('sin_departamento', False), ('del_oficial', depto_propio), ('ajeno', depto_ajeno)):
            doc = DocumentoFixture._documento(cls, date(2024, 3, 1))
            doc.employee_id.department_id = depto.id if depto else False
            cls.docs[clave] = doc
            cls.env['l10n.co.ne.documento.intento'].create({
                'documento_id': doc.id, 'state': 'invoice_pending', 'identifier': CUNE, 'numero': 'NE15',
                'datetime': '2026-04-05 10:00:00'})
            cls.env['l10n.co.ibc.mensual'].create({
                'company_id': cls.company.id, 'employee_id': doc.employee_id.id, 'period': date(2026, 3, 1)})
            cls.env['l10n.co.payslip.tercero'].create({
                'slip_id': doc.payslip_ids[:1].id, 'rule_code': 'ALCANCE_%s' % clave})

    def _ver(self, usuario, modelo):
        return self.env[modelo].with_user(usuario).with_context(allowed_company_ids=usuario.company_ids.ids)

    def _claves_visibles(self, usuario):
        """Claves de los 3 empleados cuyo recibo, documento, intento, IBC y tercero ve el usuario (deben coincidir)."""
        visibles = {}
        visibles['recibo'] = {
            k for k, d in self.docs.items() if self._ver(usuario, 'hr.payslip').search([('id', 'in', d.payslip_ids.ids)])}
        visibles['documento'] = {
            k for k, d in self.docs.items() if self._ver(usuario, 'l10n.co.ne.documento').search([('id', '=', d.id)])}
        visibles['intento'] = {
            k for k, d in self.docs.items() if self._ver(usuario, 'l10n.co.ne.documento.intento').search(
                [('documento_id', '=', d.id)])}
        visibles['ibc'] = {
            k for k, d in self.docs.items() if self._ver(usuario, 'l10n.co.ibc.mensual').search(
                [('employee_id', '=', d.employee_id.id)])}
        visibles['tercero'] = {
            k for k, d in self.docs.items() if self._ver(usuario, 'l10n.co.payslip.tercero').search(
                [('slip_id', 'in', d.payslip_ids.ids)])}
        for modelo, valor in visibles.items():
            self.assertEqual(valor, visibles['documento'], '%s debe ver lo mismo que el documento y el recibo' % modelo)
        return visibles['documento']

    def test_administrador_ve_todo(self):
        self.assertEqual(self._claves_visibles(self.administrador), {'sin_departamento', 'del_oficial', 'ajeno'})

    def test_oficial_ve_todo_incluido_el_recibo_y_lo_de_otro_departamento(self):
        """v19: el oficial de un departamento distinto al del empleado, y el que no es su jefe, ve el recibo y todo lo que cuelga de él."""
        self.assertEqual(self._claves_visibles(self.oficial), {'sin_departamento', 'del_oficial', 'ajeno'})

    def test_oficial_de_otra_compania_no_ve_nada(self):
        """Solo queda la regla multicompañía: un oficial cuya compañía no es la del documento no ve ni el recibo ni el documento ni sus dependientes."""
        self.assertEqual(self._claves_visibles(self.oficial_otra_compania), set())

    def test_oficial_de_otra_compania_no_lee_el_documento_con_error_claro(self):
        doc = self.docs['ajeno'].with_user(self.oficial_otra_compania).with_context(allowed_company_ids=self.company_b.ids)
        with self.assertRaises(AccessError):
            doc.read(['period'])

    def test_las_reglas_del_oficial_son_las_nativas_del_recibo_y_solo_queda_la_multicompania(self):
        """El dominio del oficial en los 7 modelos propios es el de ``hr_payroll_rule_officer`` (v19: ``[(1,'=',1)]``, hr_payroll_security.xml:37-42) y cada
        modelo conserva su regla global multicompañía. ``l10n.co.payslip.calculo`` (.294, «Cálculo del salario») entró en el port de .291-.298: su regla de v18 (empleado,
        departamento, jefe) dejaría la pestaña vacía para un oficial que en v19 sí ve el recibo."""
        nativa = ast.literal_eval(self.env.ref('hr_payroll.hr_payroll_rule_officer').domain_force)
        self.assertEqual(nativa, [(1, '=', 1)], 'Premisa: la regla nativa del oficial de v19 ve todo')
        modelos = ('l10n.co.ne.documento', 'l10n.co.ne.documento.intento', 'l10n.co.ibc.mensual', 'l10n.co.payslip.tercero',
                   'l10n.co.payslip.ajuste', 'l10n.co.payslip.concepto', 'l10n.co.payslip.calculo')
        grupo = self.env.ref('hr_payroll.group_hr_payroll_user')
        for modelo in modelos:
            reglas = self.env['ir.rule'].sudo().search([('model_id.model', '=', modelo)])
            del_oficial = reglas.filtered(lambda r: grupo in r.groups)
            self.assertTrue(del_oficial, '%s: falta la regla del oficial' % modelo)
            for regla in del_oficial:
                self.assertEqual(ast.literal_eval(regla.domain_force), nativa, '%s: la regla del oficial debe ser la nativa' % modelo)
            globales = reglas.filtered(lambda r: not r.groups)
            self.assertTrue(globales, '%s: falta la regla multicompañía' % modelo)
            self.assertTrue(all('company_id' in r.domain_force for r in globales), '%s: la regla global es la de compañía' % modelo)

    def test_usuario_interno_sin_rol_no_ve_nada(self):
        for modelo in ('l10n.co.ne.documento', 'l10n.co.ne.documento.intento', 'l10n.co.ibc.mensual',
                       'l10n.co.payslip.tercero'):
            with self.assertRaises(AccessError, msg=modelo):
                self.env[modelo].with_user(self.interno).search([])

    def test_adjuntos_siguen_el_acceso_al_documento_padre(self):
        """F6-EMP-001 / B3: el adjunto sigue el acceso al registro padre (ir.attachment.check). v19: el oficial de la compañía lee el de cualquier departamento;
        el de otra compañía y el usuario interno sin rol, no."""
        adjuntos = {}
        for clave in ('ajeno', 'sin_departamento'):
            adjuntos[clave] = self.env['ir.attachment'].create({
                'name': 'adjunto_%s.xml' % clave, 'raw': b'<x/>', 'res_model': 'l10n.co.ne.documento',
                'res_id': self.docs[clave].id})
        ver = lambda usuario, adjunto: adjunto.with_user(usuario).with_context(  # noqa: E731
            allowed_company_ids=usuario.company_ids.ids).read(['name'])
        with self.assertRaises(AccessError):
            ver(self.oficial_otra_compania, adjuntos['ajeno'])
        with self.assertRaises(AccessError):
            ver(self.interno, adjuntos['sin_departamento'])
        self.assertTrue(ver(self.oficial, adjuntos['ajeno']))
        self.assertTrue(ver(self.oficial, adjuntos['sin_departamento']))
        self.assertTrue(ver(self.administrador, adjuntos['ajeno']))
