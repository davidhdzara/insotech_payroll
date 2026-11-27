# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""PILA con más de un recibo por empleado en el mes (.330, hallazgo del TL): el encabezado (registro tipo 1) y el resumen de la validación cuentan COTIZANTES, no recibos, y los totales del resumen son
los de los registros tipo 2 (el IBC del mes una sola vez). Fixture: un empleado con las dos quincenas de septiembre y otro con una sola; los valores esperados salen a mano del salario.
Porte v19 (versiones: ``contract_date_start/_end``; un cambio de sueldo es un registro nuevo del mismo contrato). NO ejecutado en Odoo."""

import base64
from datetime import date

from odoo.addons.l10n_co_nomina_electronica.services import pila_generator_v2
from odoo.fields import Command
from odoo.tests.common import TransactionCase, tagged

from .common_version import confirmar_a_mano, crear_empleado_con_contrato
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

    def _contrato(self, nombre, documento, desde=date(2024, 1, 1)):
        """Empleado con su contrato (devuelve la versión)."""
        _empleado, version = crear_empleado_con_contrato(
            self.env, self.company, SALARIO, desde, self.tipo_quincenal, nombre=nombre, identification_id=documento, l10n_co_primer_nombre=nombre,
            l10n_co_primer_apellido='Prueba', address_id=self.lugar.id, l10n_co_pila_eps_id=self.entidades['eps'].id, l10n_co_pila_afp_id=self.entidades['afp'].id,
            l10n_co_pila_ccf_id=self.entidades['ccf'].id, l10n_co_pila_centro_trabajo='1')
        version.generate_work_entries(date(2026, 9, 1), date(2026, 9, 30))
        return version

    def _registro_nuevo(self, anterior, desde, salario=SALARIO):
        """Cambio en la ficha desde ``desde`` dentro del mismo contrato (otrosí): versión nueva con la copia nativa de la vigente."""
        nueva = anterior.employee_id.create_version({'date_version': desde, 'wage': salario})
        self.assertNotEqual(nueva, anterior, 'Premisa: es un registro nuevo')
        nueva.generate_work_entries(date(2026, 9, 1), date(2026, 9, 30))
        return nueva

    def _confirmado(self, contrato, desde, hasta):
        recibo = self.env['hr.payslip'].create({
            'name': 'Recibo %s %s' % (contrato.employee_id.name, desde), 'employee_id': contrato.employee_id.id, 'version_id': contrato.id,
            'company_id': self.company.id, 'struct_id': self.nomina.id, 'date_from': desde, 'date_to': hasta})
        recibo.compute_sheet()
        confirmar_a_mano(recibo)
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
        """Aumento a 4.000.000 desde el 16: registro nuevo del mismo contrato."""
        anterior = self._contrato('Aumento', '1000000003')
        nuevo = self._registro_nuevo(anterior, date(2026, 9, 16), 4000000.0)
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

    # ── las novedades salen de todos los recibos del mes ─────────────
    def _sin_calcular(self, contrato, desde, hasta, estructura=None):
        return self.env['hr.payslip'].create({
            'name': 'Recibo %s %s' % (contrato.employee_id.name, hasta), 'employee_id': contrato.employee_id.id, 'version_id': contrato.id,
            'company_id': self.company.id, 'struct_id': (estructura or self.nomina).id, 'date_from': desde, 'date_to': hasta})

    def _quincenas(self, contrato):
        return self._sin_calcular(contrato, date(2026, 9, 1), date(2026, 9, 15)), self._sin_calcular(contrato, date(2026, 9, 16), date(2026, 9, 30))

    def _novedades(self, de_la_linea, recibos):
        return self.env['l10n.co.hr.pila.wizard.v2']._detect_novedades(de_la_linea, recibos)

    def test_una_ausencia_de_la_primera_quincena_se_marca_aunque_la_linea_salga_de_la_segunda(self):
        contrato = self._contrato('Incapacidad', '1000000004')
        ausencia = self.env['hr.leave'].create({
            'employee_id': contrato.employee_id.id, 'holiday_status_id': self.env.ref('l10n_co_nomina_electronica.hr_leave_type_co_inc_comun').id,
            'request_date_from': date(2026, 9, 3), 'request_date_to': date(2026, 9, 4)})
        ausencia.action_approve(check_state=False)
        primera, segunda = self._quincenas(contrato)
        novedades = self._novedades(segunda, primera | segunda)
        self.assertEqual((novedades['ige'], novedades['fecha_inicio_ige'], novedades['fecha_fin_ige']), ('X', '2026-09-03', '2026-09-04'))

    def test_el_aporte_voluntario_de_cualquier_recibo_del_mes_se_marca(self):
        primera, segunda = self._quincenas(self._contrato('Voluntario', '1000000005'))
        regla = self.env['hr.salary.rule'].search([('struct_id', '=', self.nomina.id), ('code', '=', 'CO_PENSION_VOL')], limit=1)
        primera.write({'line_ids': [Command.create({
            'name': regla.name, 'code': regla.code, 'salary_rule_id': regla.id, 'version_id': primera.version_id.id, 'employee_id': primera.employee_id.id,
            'sequence': regla.sequence, 'amount': -100000.0, 'quantity': 1.0, 'rate': 100.0, 'total': -100000.0})]})
        self.assertEqual(self._novedades(segunda, primera | segunda)['avp'], 'X')

    def test_un_otrosi_dentro_del_mes_no_es_ingreso_ni_retiro(self):
        anterior = self._contrato('Otrosi', '1000000006')
        nuevo = self._registro_nuevo(anterior, date(2026, 9, 16))
        primera = self._sin_calcular(anterior, date(2026, 9, 1), date(2026, 9, 15))
        segunda = self._sin_calcular(nuevo, date(2026, 9, 16), date(2026, 9, 30))
        novedades = self._novedades(segunda, primera | segunda)
        self.assertEqual((novedades['ing'], novedades['ret']), ('', ''))

    def test_el_retiro_con_liquidacion_marca_retiro_y_no_ingreso(self):
        """En la liquidación «Desde» es el inicio del contrato: el mes de la planilla sale del «Hasta»."""
        contrato = self._contrato('Retiro', '1000000007')
        contrato.write({'contract_date_end': date(2026, 9, 20)})
        primera = self._sin_calcular(contrato, date(2026, 9, 1), date(2026, 9, 15))
        liquidacion = self._sin_calcular(contrato, date(2024, 1, 1), date(2026, 9, 20), self.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_liquidacion'))
        novedades = self._novedades(liquidacion, primera | liquidacion)
        self.assertEqual((novedades['ret'], novedades['fecha_ret'], novedades['ing']), ('X', '2026-09-20', ''))

    def test_el_ingreso_en_el_mes_se_marca_con_su_fecha(self):
        contrato = self._contrato('Ingreso', '1000000008', desde=date(2026, 9, 1))
        primera, segunda = self._quincenas(contrato)
        novedades = self._novedades(segunda, primera | segunda)
        self.assertEqual((novedades['ing'], novedades['fecha_ing'], novedades['ret']), ('X', '2026-09-01', ''))
