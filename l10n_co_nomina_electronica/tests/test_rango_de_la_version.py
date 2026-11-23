# -*- coding: utf-8 -*-
"""H-F1-10 (solo v19, motor; doc 82; registro §11.2): el recorte de un recibo por la vigencia de su VERSIÓN, no por el contrato. NO EJECUTADAS en Odoo al escribirlas.

El nativo da UN recibo por empleado y contrato con la versión vigente al INICIO del periodo y marca ``OUT`` los días posteriores a ``version.date_end``; los días con el sueldo
nuevo de un aumento a mitad del periodo van en OTRO recibo (``date_from`` = la fecha del aumento, versión nueva). El módulo contaba por el contrato: pagaba la versión vieja
completa y contaba dos veces las ausencias posteriores al aumento. ``HrPayslip._ne_rango_de_la_version`` es la ÚNICA fuente de la intersección y la usan
``_ne_rango_activo``, ``_ne_ausencia_calendario``, ``_ne_incapacidad_cadenas`` y ``_ne_ausencia_habil``.

Fixture: un empleado con dos versiones del MISMO contrato (A hasta el día anterior al aumento, B desde el aumento; B se crea con ``hr.version.create`` directo: NO VERIFICADO) y
DOS recibos del mismo periodo (A: ``date_from`` = inicio del periodo; B: ``date_from`` = el aumento). Septiembre de 2026 empieza en martes; el aumento es el miércoles 16 (15 días
comerciales de A y 15 de B). Sueldos A 3.000.000 (100.000 por día) y B 3.300.000 (110.000 por día).

Casos (los de la instrucción del TL): 1) aumento a mitad del periodo; 2) aumento a mitad de una incapacidad común; 3) aumento a mitad de una vacación de días hábiles (con la
prueba 13 de .300, que cubre el recibo de B por separado); 4) un recibo TODO dentro de una versión no cambia; 5) liquidación: sin recorte por versión; 6) ING/RET: el recibo de B
informa ``FechaIngreso`` del contrato, no de la versión; y una versión sin contrato recorta por ``date_version``."""

from datetime import date, timedelta

from odoo.tests.common import TransactionCase, tagged

from .common_version import VALORES_COLOMBIA, crear_empleado_con_contrato

AUMENTO = date(2026, 9, 16)
INGRESO = date(2024, 1, 1)
SUELDO_A = 3000000.0
SUELDO_B = 3300000.0
_CODIGO_FRACCION = 'l10n_co_ausencia_fraccion_dia'


@tagged('post_install', '-at_install')
class TestRangoDeLaVersion(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U', 'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_clase_riesgo': '1',
            'l10n_co_ne_febrero_modo': 'real', 'l10n_co_ne_redondeo_dias': 'DOWN', 'name': 'Compañía Rango de la Versión'})
        # El entorno y los datos comparten compañía: la conversión nativa de hr.leave a hr.work.entry filtra por la compañía de la versión.
        cls.env = cls.company.with_company(cls.company).env
        # ``_collect_payslip_data`` exige país, departamento y municipio en la dirección de trabajo (el mismo montaje que ``test_ausencias_nomina``).
        pais = cls.env.ref('base.co')
        departamento = cls.env['res.country.state'].search([('country_id', '=', pais.id)], limit=1) or cls.env['res.country.state'].create({
            'name': 'Departamento Prueba Rango', 'code': 'PR', 'country_id': pais.id})
        ciudad = cls.env['res.city'].create({'name': 'Ciudad Prueba Rango', 'state_id': departamento.id, 'country_id': pais.id})
        cls.company.partner_id.write({'country_id': pais.id, 'state_id': departamento.id, 'city_id': ciudad.id, 'street': 'Calle Prueba Rango # 1-1'})
        cls.structure_type = cls.env['hr.payroll.structure.type'].create({'name': 'Prueba Estructura Rango', 'country_id': pais.id})
        ref = cls.env.ref
        cls.general = ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
        cls.liquidacion = ref('l10n_co_nomina_electronica.hr_payroll_structure_co_liquidacion')
        cls.leave_vac = ref('l10n_co_nomina_electronica.hr_leave_type_co_vac')
        cls.leave_inc_comun = ref('l10n_co_nomina_electronica.hr_leave_type_co_inc_comun')
        cls.n = 0

    def setUp(self):
        super().setUp()
        # En una N1 sin ``-u`` la base aún no trae el parámetro del XML (.300): se crea dentro de la transacción de la prueba, con días enteros.
        Parametro = self.env['hr.rule.parameter']
        parametro = Parametro.search([('code', '=', _CODIGO_FRACCION)], limit=1) or Parametro.create({
            'name': 'Colombia: Ausencias de Días Hábiles por Fracción de Día', 'code': _CODIGO_FRACCION, 'country_id': self.env.ref('base.co').id})
        if parametro.parameter_version_ids:
            parametro.parameter_version_ids.write({'parameter_value': '0'})
        else:
            self.env['hr.rule.parameter.value'].create({'rule_parameter_id': parametro.id, 'parameter_value': '0', 'date_from': date(2020, 1, 1)})

    # ── fixtures ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
    def _empleado(self, aumento=AUMENTO, sueldo_a=SUELDO_A, sueldo_b=SUELDO_B):
        """Empleado colombiano con la versión A (contrato desde ``INGRESO``) y la versión B (el aumento en ``aumento``, MISMO contrato). Devuelve ``(empleado, va, vb)``."""
        type(self).n += 1
        empleado, version_a = crear_empleado_con_contrato(
            self.env, self.company, sueldo_a, INGRESO, self.structure_type, nombre='Empleado Rango %s' % self.n,
            l10n_co_primer_nombre='Prueba', l10n_co_primer_apellido='Fixture', identification_id='81%s' % self.n)
        empleado.l10n_co_ne_identification_type_id = self.env.ref('l10n_co.national_citizen_id').id
        valores_b = {campo: valor for campo, valor in VALORES_COLOMBIA.items() if campo in self.env['hr.version']._fields}
        version_b = self.env['hr.version'].create(dict(
            valores_b, employee_id=empleado.id, date_version=aumento, contract_date_start=version_a.contract_date_start, wage=sueldo_b,
            structure_type_id=self.structure_type.id))
        self.assertEqual(empleado._get_version(aumento - timedelta(days=1)), version_a, 'Premisa: antes del aumento rige la versión A')
        self.assertEqual(empleado._get_version(aumento), version_b, 'Premisa: desde el aumento rige la versión B')
        return empleado, version_a, version_b

    def _recibo(self, empleado, version, desde, hasta, estructura=None):
        return self.env['hr.payslip'].create({
            'name': 'Recibo Rango %s' % desde, 'employee_id': empleado.id, 'version_id': version.id, 'company_id': self.company.id,
            'struct_id': (estructura or self.general).id, 'date_from': desde, 'date_to': hasta})

    def _ausencia(self, empleado, versiones, tipo, desde, hasta):
        """Ausencia validada: primero las entradas de trabajo de cada versión (como el cron diario) y luego el ``hr.leave``."""
        for version in versiones:
            version.generate_work_entries(desde, hasta)
        ausencia = self.env['hr.leave'].create({
            'employee_id': empleado.id, 'holiday_status_id': tipo.id, 'request_date_from': desde, 'request_date_to': hasta})
        ausencia.action_approve(check_state=False)
        self.assertEqual(ausencia.state, 'validate')
        return ausencia

    def _total(self, recibo, codigo):
        return sum(recibo.line_ids.filtered(lambda l: l.code == codigo).mapped('total'))

    def _cantidad(self, recibo, codigo):
        return sum(recibo.line_ids.filtered(lambda l: l.code == codigo).mapped('quantity'))

    # ── 1) aumento a mitad del periodo ───────────────────────────────────────────────────────────────────────────────────────
    def test_01_aumento_a_mitad_del_periodo_los_dias_de_los_dos_recibos_suman_exactamente_el_periodo(self):
        empleado, va, vb = self._empleado()
        a = self._recibo(empleado, va, date(2026, 9, 1), date(2026, 9, 30))
        b = self._recibo(empleado, vb, AUMENTO, date(2026, 9, 30))
        self.assertEqual((a.version_id, b.version_id), (va, vb))
        self.assertEqual(a._ne_rango_activo(), (date(2026, 9, 1), date(2026, 9, 15)), 'A: hasta el día anterior al aumento')
        self.assertEqual(b._ne_rango_activo(), (date(2026, 9, 16), date(2026, 9, 30)), 'B: desde el aumento')
        self.assertEqual((a._ne_dias_bajo_contrato(), b._ne_dias_bajo_contrato()), (15, 15))
        a.compute_sheet()
        b.compute_sheet()
        self.assertEqual(a._ne_dias_pagables() + b._ne_dias_pagables(), 30, 'Sin pagar de más ni de menos: los 30 días comerciales del periodo')
        self.assertAlmostEqual(self._cantidad(a, 'CO_BASICO'), 15.0, places=4)
        self.assertAlmostEqual(self._cantidad(b, 'CO_BASICO'), 15.0, places=4)
        self.assertAlmostEqual(self._total(a, 'CO_BASICO'), 15 * SUELDO_A / 30.0, delta=0.01, msg='A paga SU tramo con SU sueldo')
        self.assertAlmostEqual(self._total(b, 'CO_BASICO'), 15 * SUELDO_B / 30.0, delta=0.01, msg='B paga SU tramo con SU sueldo')
        salida = a.worked_days_line_ids.filtered(lambda w: w.code == 'OUT')
        self.assertTrue(salida and salida.number_of_days > 0, 'La línea OUT de A cubre los días desde el aumento (la agrega el nativo)')
        self.assertFalse(b.worked_days_line_ids.filtered(lambda w: w.code == 'OUT'), 'B empieza en el aumento: no hay días fuera de su versión')

    # ── 2) aumento a mitad de una incapacidad común ──────────────────────────────────────────────────────────────────────────
    def test_02_aumento_a_mitad_de_una_incapacidad_suma_los_dias_de_la_ausencia_sin_doble_pago_y_la_cadena_continua_en_b(self):
        """Incapacidad común del 10 al 25 de septiembre (16 días calendario): 10 a 15 en A (6 días) y 16 a 25 en B (10 días). La cadena sigue por EMPLEADO, pero los
        ``previos`` de B cuentan los 6 días de antes del aumento: ocupan las posiciones 1..6 y los de B las siguientes (los 2 días del empleador no se repiten)."""
        empleado, va, vb = self._empleado()
        self._ausencia(empleado, (va, vb), self.leave_inc_comun, date(2026, 9, 10), date(2026, 9, 25))
        a = self._recibo(empleado, va, date(2026, 9, 1), date(2026, 9, 30))
        b = self._recibo(empleado, vb, AUMENTO, date(2026, 9, 30))
        self.assertEqual(a._ne_ausencia_calendario('CO_INC_COMUN')[0], 6)
        self.assertEqual(b._ne_ausencia_calendario('CO_INC_COMUN')[0], 10)
        self.assertEqual(a._ne_ausencia_calendario('CO_INC_COMUN')[0] + b._ne_ausencia_calendario('CO_INC_COMUN')[0], 16, 'Los días de la ausencia, ni uno más ni uno menos')
        self.assertEqual(a._ne_incapacidad_cadenas(), [(0, 6)])
        self.assertEqual(b._ne_incapacidad_cadenas(), [(6, 10)], 'Los tramos continúan en B: 6 días previos y 10 propios')
        self.assertEqual(a._ne_dias_pagables() + b._ne_dias_pagables() + 16, 30, 'Básico + incapacidad = el periodo; sin doble pago')

    # ── 3) aumento a mitad de una vacación (días hábiles) ────────────────────────────────────────────────────────────────────
    def test_03_aumento_a_mitad_de_una_vacacion_suma_los_dias_de_la_vacacion(self):
        """Vacación de martes 8 a viernes 11 de septiembre (4 días hábiles, calendario de la compañía de lunes a viernes) y aumento el jueves 10: 2 días en A (8 y 9) y 2 en B
        (10 y 11). La prueba 13 de .300 mira el recibo de B por separado."""
        empleado, va, vb = self._empleado(aumento=date(2026, 9, 10))
        self._ausencia(empleado, (va, vb), self.leave_vac, date(2026, 9, 8), date(2026, 9, 11))
        a = self._recibo(empleado, va, date(2026, 9, 1), date(2026, 9, 30))
        b = self._recibo(empleado, vb, date(2026, 9, 10), date(2026, 9, 30))
        dias_a, detalle_a = a._ne_ausencia_habil('CO_VAC')
        dias_b, detalle_b = b._ne_ausencia_habil('CO_VAC')
        self.assertEqual((dias_a, dias_b), (2, 2))
        self.assertEqual(dias_a + dias_b, 4, 'Los días de la vacación, sin contar ninguno en los dos recibos')
        self.assertEqual((detalle_a[0][2], detalle_a[0][3]), (date(2026, 9, 8), date(2026, 9, 9)), 'Las fechas del detalle también se recortan a la versión')
        self.assertEqual((detalle_b[0][2], detalle_b[0][3]), (date(2026, 9, 10), date(2026, 9, 11)))

    # ── 4) un recibo TODO dentro de una versión: sin cambio (regresión) ─────────────────────────────────────────────────────
    def test_04_un_recibo_todo_dentro_de_una_version_no_cambia(self):
        empleado, va, vb = self._empleado()
        agosto = self._recibo(empleado, va, date(2026, 8, 1), date(2026, 8, 31))
        octubre = self._recibo(empleado, vb, date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(agosto._ne_rango_activo(), (date(2026, 8, 1), date(2026, 8, 31)))
        self.assertEqual(octubre._ne_rango_activo(), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual((agosto._ne_dias_bajo_contrato(), octubre._ne_dias_bajo_contrato()), (30, 30), 'Mes completo = 30 días comerciales, como antes')

    # ── 5) liquidación: sin recorte por versión ──────────────────────────────────────────────────────────────────────────────
    def test_05_la_liquidacion_no_se_recorta_por_la_version_sino_por_el_contrato(self):
        """La liquidación va de ``contract_date_start`` al retiro y el asistente la crea con la versión MÁS RECIENTE (B): recortar por el rango de B la dejaría sin los meses
        anteriores. El recorte es el del contrato (más el mes de ``date_to`` que ya hacía ``_ne_tramo_pagable_periodo``): del 1 al 30 de septiembre, no del 16 al 30. Una vacación
        de A (8 y 9 de septiembre) SÍ cuenta en la liquidación hecha con la versión B."""
        empleado, va, vb = self._empleado()
        self._ausencia(empleado, (va,), self.leave_vac, date(2026, 9, 8), date(2026, 9, 9))
        liquidacion = self._recibo(empleado, vb, INGRESO, date(2026, 9, 30), estructura=self.liquidacion)
        self.assertTrue(liquidacion._ne_es_liquidacion())
        self.assertEqual(liquidacion._ne_rango_activo(), (date(2026, 9, 1), date(2026, 9, 30)), 'Sin recorte por el rango de la versión B (16 al 30)')
        self.assertEqual(liquidacion._ne_dias_bajo_contrato(), 30)
        self.assertEqual(liquidacion._ne_ausencia_habil_tramo('CO_VAC')[0], 2, 'La vacación de la versión A cuenta: en liquidación manda el contrato')
        regular = self._recibo(empleado, vb, AUMENTO, date(2026, 9, 30))
        self.assertEqual(regular._ne_rango_activo(), (AUMENTO, date(2026, 9, 30)), 'En cambio un recibo regular de B sí se recorta a su versión')

    # ── 6) ING/RET: fechas del contrato ─────────────────────────────────────────────────────────────────────────────────────
    def test_06_el_recibo_de_b_informa_la_fecha_de_ingreso_del_contrato_no_la_de_la_version(self):
        empleado, va, vb = self._empleado()
        b = self._recibo(empleado, vb, AUMENTO, date(2026, 9, 30))
        b.compute_sheet()
        periodo = b._collect_payslip_data()['periodo']
        self.assertEqual(periodo['FechaIngreso'], str(INGRESO), 'El contrato empezó en 2024: el aumento no es un ingreso')
        self.assertEqual(periodo['FechaRetiro'], '')
        self.assertEqual(periodo['FechaLiquidacionInicio'], str(AUMENTO), 'El periodo que informa el recibo sí es el del recibo')
        self.assertEqual(vb.date_start, AUMENTO, 'Premisa: la vigencia de B (date_start) sí empieza en el aumento')

    def test_07_una_version_sin_contrato_recorta_por_su_date_version(self):
        """Sin ``contract_date_start`` el núcleo da ``date_start = date_version`` (``hr/models/hr_version.py:566-568``): el recorte sigue valiendo."""
        type(self).n += 1
        empleado = self.env['hr.employee'].create({'name': 'Empleado Sin Contrato Rango %s' % self.n, 'company_id': self.company.id, 'date_version': date(2026, 10, 10)})
        version = empleado._get_version(date(2026, 10, 10))
        self.assertFalse(version.contract_date_start, 'Premisa: la versión no tiene contrato')
        recibo = self._recibo(empleado, version, date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(recibo._ne_rango_de_la_version(date(2026, 10, 1), date(2026, 10, 31)), (date(2026, 10, 10), date(2026, 10, 31)))
        self.assertEqual(recibo._ne_rango_de_la_version(date(2026, 11, 1), date(2026, 11, 30)), (date(2026, 11, 1), date(2026, 11, 30)), 'Un periodo posterior no se toca')

    def test_08_el_metodo_es_la_unica_fuente_de_la_interseccion(self):
        """Los 4 sitios llaman a ``_ne_rango_de_la_version``; ninguno reimplementa la intersección con ``contract_date_start/_end``."""
        import inspect
        modelo = type(self.env['hr.payslip'])
        for nombre in ('_ne_rango_activo', '_ne_ausencia_calendario', '_ne_incapacidad_cadenas', '_ne_ausencia_habil'):
            codigo = '\n'.join(l for l in inspect.getsource(getattr(modelo, nombre)).splitlines() if not l.strip().startswith('#'))
            self.assertIn('_ne_rango_de_la_version(', codigo, nombre)
            self.assertNotIn('contract_date_start', codigo.split('"""')[-1], '%s no recorta por el contrato' % nombre)
            self.assertNotIn('contract_date_end', codigo.split('"""')[-1], '%s no recorta por el contrato' % nombre)
