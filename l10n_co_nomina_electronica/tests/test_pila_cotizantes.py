# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""PILA con más de un recibo por empleado en el mes (.330, hallazgo del TL): el encabezado (registro tipo 1) y el resumen de la validación cuentan COTIZANTES, no recibos, y los totales del resumen son
los de los registros tipo 2 (el IBC del mes una sola vez). Fixture: un empleado con las dos quincenas de septiembre y otro con una sola; los valores esperados salen a mano del salario."""

import base64
from datetime import date

from odoo.addons.l10n_co_nomina_electronica.services import pila_generator_v2
from odoo.tests.common import TransactionCase, tagged

from .test_pila_ubicacion_laboral import direccion_de_trabajo, ubicaciones_de_prueba

SALARIO = 3000000.0          # con 16 % de pensión (empleado + empleador): 480.000 el mes completo y 240.000 una quincena


@tagged('post_install', '-at_install')
class TestPilaCotizantesPorEmpleado(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env['res.partner']
        cls.entidades = {
            tipo: Partner.create({'name': '%s Cotizantes' % tipo.upper(), 'l10n_co_entity_type': tipo, 'l10n_co_pila_entity_code': codigo})
            for tipo, codigo in (('eps', 'EPS778'), ('afp', 'AFP778'), ('ccf', 'CCF778'), ('arl', '14-78'))}
        cls.company = cls.env['res.company'].create({
            'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U', 'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_clase_riesgo': '1',
            'l10n_co_ne_febrero_modo': 'real', 'l10n_co_ne_redondeo_dias': 'DOWN', 'name': 'Compañía Cotizantes PILA', 'l10n_co_pila_ccf_por_empleado': True,
            'l10n_co_pila_arl_id': cls.entidades['arl'].id, 'l10n_co_pila_operador_code': '89'})
        cls.env = cls.company.with_company(cls.company).env
        (departamento, ciudad), = ubicaciones_de_prueba(cls.env, 1)
        cls.company.partner_id.with_context(no_vat_validation=True).write({'vat': '900123456-8'})
        cls.lugar = direccion_de_trabajo(cls.env, 'Sede Cotizantes PILA', departamento, ciudad)
        cls.tipo_quincenal = cls.env['hr.payroll.structure.type'].create({
            'name': 'Cotizantes PILA quincenal', 'country_id': cls.env.ref('base.co').id, 'default_schedule_pay': 'semi-monthly'})
        cls.nomina = cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
        cls.env['l10n.co.retefuente.uvt'].create({'year': '2026', 'company_id': cls.company.id, 'procedure': '1'})

    def _contrato(self, nombre, documento):
        empleado = self.env['hr.employee'].create({
            'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00', 'name': nombre, 'company_id': self.company.id, 'l10n_co_ne_payment_method': '10',
            'identification_id': documento, 'l10n_co_primer_nombre': nombre, 'l10n_co_primer_apellido': 'Prueba', 'address_id': self.lugar.id,
            'l10n_co_pila_eps_id': self.entidades['eps'].id, 'l10n_co_pila_afp_id': self.entidades['afp'].id, 'l10n_co_pila_ccf_id': self.entidades['ccf'].id})
        return self._contrato_de(empleado)

    def _contrato_de(self, empleado, salario=SALARIO, desde=date(2024, 1, 1)):
        contrato = self.env['hr.contract'].create({
            'l10n_co_ne_contract_type': '2', 'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00', 'l10n_co_pila_centro_trabajo': '1',
            'name': 'Contrato %s %s' % (empleado.name, desde), 'employee_id': empleado.id, 'company_id': self.company.id, 'structure_type_id': self.tipo_quincenal.id,
            'wage': salario, 'date_start': desde, 'state': 'open'})
        contrato.generate_work_entries(date(2026, 9, 1), date(2026, 9, 30))
        return contrato

    def _confirmado(self, contrato, desde, hasta):
        recibo = self.env['hr.payslip'].create({
            'name': 'Recibo %s %s' % (contrato.employee_id.name, desde), 'employee_id': contrato.employee_id.id, 'contract_id': contrato.id,
            'company_id': self.company.id, 'struct_id': self.nomina.id, 'date_from': desde, 'date_to': hasta})
        recibo.compute_sheet()
        recibo.state = 'done'
        return recibo

    def _planilla_del_mes(self):
        """Dos empleados y tres recibos; devuelve el asistente validado."""
        dos = self._contrato('DosQuincenas', '1000000001')
        uno = self._contrato('UnaQuincena', '1000000002')
        self._confirmado(dos, date(2026, 9, 1), date(2026, 9, 15))
        self._confirmado(dos, date(2026, 9, 16), date(2026, 9, 30))
        self._confirmado(uno, date(2026, 9, 1), date(2026, 9, 15))
        asistente = self.env['l10n.co.hr.pila.wizard.v2'].create({'company_id': self.company.id, 'year': '2026', 'month': '09', 'tipo_planilla': 'E'})
        self.assertEqual(len(asistente._get_period_payslips(self.company, 2026, 9)), 3, 'Premisa: tres recibos confirmados de dos empleados')
        asistente.action_validate()
        self.assertTrue(asistente.validation_ok, asistente.validation_errors)
        return asistente

    def _archivo(self, asistente):
        asistente.action_generate_pila()
        lineas = base64.b64decode(asistente.file_data).decode('utf-8').splitlines()
        encabezado = [linea.split('|') for linea in lineas if linea.startswith('01|')]
        detalle = [linea.split('|') for linea in lineas if linea.startswith('02|')]
        self.assertEqual(len(encabezado), 1)
        return encabezado[0], detalle

    @staticmethod
    def _campo(definicion, linea, nombre):
        return linea[[campo for campo, _formato in definicion].index(nombre)]

    def test_el_encabezado_cuenta_cotizantes_y_no_recibos(self):
        encabezado, detalle = self._archivo(self._planilla_del_mes())
        self.assertEqual(len(detalle), 2)
        self.assertEqual(self._campo(pila_generator_v2._TIPO_01_FIELDS, encabezado, 'numero_total_cotizantes'), '2')

    def test_el_resumen_cuenta_cotizantes_y_no_repite_el_ibc_del_mes(self):
        asistente = self._planilla_del_mes()
        self.assertEqual(asistente.summary_total_employees, 2)
        self.assertAlmostEqual(asistente.summary_total_ibc, SALARIO * 1.5, delta=1.0)          # mes completo + una quincena
        self.assertAlmostEqual(asistente.summary_total_pension, SALARIO * 1.5 * 0.16, delta=100.0)

    def test_los_totales_del_resumen_son_los_del_archivo(self):
        asistente = self._planilla_del_mes()
        _encabezado, detalle = self._archivo(asistente)
        for total, campo in (('summary_total_ibc', 'ibc_pension'), ('summary_total_pension', 'cotizacion_pension'), ('summary_total_salud', 'cotizacion_salud')):
            en_el_archivo = sum(float(self._campo(pila_generator_v2._TIPO_02_FIELDS, linea, campo)) for linea in detalle)
            self.assertAlmostEqual(asistente[total], en_el_archivo, delta=2.0, msg=total)

    # ── el recibo del que salen los datos de la línea (H-F1-10) ──────
    def _con_aumento_en_la_segunda_quincena(self):
        """Otrosí: el contrato inicial termina el 15 y el nuevo, con 4.000.000, empieza el 16."""
        anterior = self._contrato('Aumento', '1000000003')
        anterior.write({'date_end': date(2026, 9, 15), 'state': 'close'})
        nuevo = self._contrato_de(anterior.employee_id, salario=4000000.0, desde=date(2026, 9, 16))
        return self._confirmado(anterior, date(2026, 9, 1), date(2026, 9, 15)) | self._confirmado(nuevo, date(2026, 9, 16), date(2026, 9, 30))

    def test_el_recibo_mas_reciente_no_depende_del_orden_en_que_llegan(self):
        recibos = self._con_aumento_en_la_segunda_quincena()
        segundo = recibos.filtered(lambda recibo: recibo.date_from == date(2026, 9, 16))
        asistente = self.env['l10n.co.hr.pila.wizard.v2']
        for entrada in (recibos, recibos.sorted('date_from'), recibos.sorted('date_from', reverse=True)):
            self.assertEqual(asistente._ne_recibo_mas_reciente(entrada), segundo)

    def test_la_linea_lleva_los_datos_del_recibo_mas_reciente(self):
        self._con_aumento_en_la_segunda_quincena()
        asistente = self.env['l10n.co.hr.pila.wizard.v2'].create({'company_id': self.company.id, 'year': '2026', 'month': '09', 'tipo_planilla': 'E'})
        asistente.action_validate()
        self.assertTrue(asistente.validation_ok, asistente.validation_errors)
        _encabezado, detalle = self._archivo(asistente)
        self.assertEqual(len(detalle), 1)
        self.assertEqual(self._campo(pila_generator_v2._TIPO_02_FIELDS, detalle[0], 'salario_basico'), '4000000')

