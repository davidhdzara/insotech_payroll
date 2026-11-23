# -*- coding: utf-8 -*-
"""E2b (.300, doc 72 §3): los días de vacaciones, licencias y tipos sin sueldo se cuentan por FECHA con entrada de la ausencia, no por horas ÷ horas por día.

Horario de prueba = el de Guapante en pequeño: martes a domingo, lunes de descanso: martes a viernes 7,5 h, sábado y domingo 7 h = 44 h en 6 días, es decir
7,33 h por día (``resource.calendar.hours_per_day`` redondea a 2 decimales). Con ese horario las horas de una ausencia NO dividen en días enteros: cuatro días de
martes a viernes son 30 h = 4,09 días de «horas ÷ horas por día» (lo que pagaba el nativo) y 4 por fecha; un domingo de 7 h son 0,95 días y 1 por fecha.

Septiembre de 2026 empieza en martes: la quincena del 1 al 15 tiene dos lunes de descanso (7 y 14); sueldo 3.000.000 → 100.000 por día; 15 días comerciales.
Hereda los fixtures de ``TestDiasPorAsistencia`` (no sus pruebas: Odoo no recoge los métodos heredados). NO EJECUTADAS en Odoo al escribirlas; necesitan ``-u``
(el parámetro ``l10n_co_ausencia_fraccion_dia`` es un dato del módulo): en una N1 sin ``-u`` cada prueba lo crea dentro de su transacción.

v19 (port de la pieza, §10.13 U2): el empleado se crea con su versión (``common_version``, no hay ``hr.contract``); la entrada de trabajo es de UN día (``date``,
``duration``; ``hr_work_entry/models/hr_work_entry.py:28-29``), así que la prueba 07 de v18 (el turno nocturno 22:00-06:00 y la fecha UTC) ya no tiene sentido y se
reemplazó por la de una entrada con ``duration`` 0; y la prueba del medio día arma las horas con ``duration`` en vez de con ``date_start``. La prueba 13 es la del
caso «empleado con dos versiones en el periodo y la ausencia en la otra» (HIPÓTESIS del consultor v19, §10.13 U2; prueba OBLIGATORIA por decisión del TL)."""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common_version import VALORES_COLOMBIA, crear_empleado_con_contrato
from .test_dias_por_asistencia import TestDiasPorAsistencia

_CODIGO = 'l10n_co_ausencia_fraccion_dia'


@tagged('post_install', '-at_install')
class TestAusenciaPorFecha(TestDiasPorAsistencia):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        asistencias = []
        for dia, tarde_hasta in (('1', 16.5), ('2', 16.5), ('3', 16.5), ('4', 16.5), ('5', 16.0), ('6', 16.0)):     # martes a domingo
            asistencias.append((0, 0, {'name': 'Mañana %s' % dia, 'dayofweek': dia, 'hour_from': 8.0, 'hour_to': 12.0, 'day_period': 'morning'}))
            asistencias.append((0, 0, {'name': 'Tarde %s' % dia, 'dayofweek': dia, 'hour_from': 13.0, 'hour_to': tarde_hasta, 'day_period': 'afternoon'}))
        cls.calendario = cls.env['resource.calendar'].create({
            'name': 'Mar-Dom E2b', 'company_id': cls.company.id, 'tz': 'America/Bogota', 'attendance_ids': asistencias})
        cls.company.resource_calendar_id = cls.calendario

    def setUp(self):
        super().setUp()
        self._fraccion(0)

    # ── fixtures ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
    def _contrato(self, ingreso=date(2024, 1, 1), fin=None, wage=3000000.0, tipo=None):
        """Como el del padre, pero con el horario martes a domingo en la versión del empleado desde su creación (antes de generar entradas).
        v19: devuelve ``(empleado, version)``."""
        type(self).n += 1
        return crear_empleado_con_contrato(
            self.env, self.company, wage, ingreso, tipo or self.tipo, nombre='Empleado Ausencia Fecha %s' % self.n, fin=fin,
            resource_calendar_id=self.calendario.id, tz='America/Bogota')

    def _fraccion(self, valor):
        """Fija el interruptor (en la N1 sin ``-u`` la base aún no trae el parámetro del XML: se crea dentro de la transacción de la prueba)."""
        Parametro = self.env['hr.rule.parameter']
        parametro = Parametro.search([('code', '=', _CODIGO)], limit=1) or Parametro.create({
            'name': 'Colombia: Ausencias de Días Hábiles por Fracción de Día', 'code': _CODIGO, 'country_id': self.env.ref('base.co').id})
        if parametro.parameter_version_ids:
            parametro.parameter_version_ids.write({'parameter_value': str(valor)})
        else:
            self.env['hr.rule.parameter.value'].create({'rule_parameter_id': parametro.id, 'parameter_value': str(valor), 'date_from': date(2020, 1, 1)})

    def _recibo_con(self, tipo_ausencia, desde, hasta, periodo=(date(2026, 9, 1), date(2026, 9, 15))):
        """Quincena con una ausencia validada: las líneas de días y la hoja se generan al refrescar desde las entradas de trabajo."""
        recibo = self._recibo(desde=periodo[0], hasta=periodo[1], calcular=False)
        self._ausencia(recibo, tipo_ausencia, desde, hasta)
        recibo.action_refresh_from_work_entries()
        return recibo

    def _total(self, recibo, codigo):
        return sum(recibo.line_ids.filtered(lambda l: l.code == codigo).mapped('total'))

    def _cantidad(self, recibo, codigo):
        return sum(recibo.line_ids.filtered(lambda l: l.code == codigo).mapped('quantity'))

    # ── A, B, D: las cifras del doc 72 §3.2 con el horario de prueba ──────────────────────────────────────────────────────────
    def test_01_vacacion_de_martes_a_viernes_son_4_dias_de_las_fechas_no_los_de_las_horas(self):
        """Caso A: 4 fechas, 30 h. Nativo: 30 h ÷ 7,33 = 4,09 días. Por fecha: 4. El total de los 15 días comerciales no cambia; solo se mueve el auxilio."""
        recibo = self._recibo_con(self.leave_vac, date(2026, 9, 8), date(2026, 9, 11))
        dia = recibo.version_id.wage / 30.0
        self.assertEqual(self._dias(recibo, 'CO_VAC'), 4.0)
        self.assertEqual(self._cantidad(recibo, 'CO_VAC'), 4.0)
        self.assertAlmostEqual(self._total(recibo, 'CO_VAC'), 4 * dia, delta=0.01)
        self.assertEqual(self._cantidad(recibo, 'CO_BASICO'), 11.0)
        self.assertAlmostEqual(self._total(recibo, 'CO_BASICO'), 11 * dia, delta=0.01)
        self.assertAlmostEqual(self._total(recibo, 'CO_VAC') + self._total(recibo, 'CO_BASICO'), 15 * dia, delta=0.01, msg='Los 15 días comerciales no cambian')
        aux = recibo._rule_parameter('l10n_co_aux_transporte', recibo.date_from)
        self.assertEqual(self._cantidad(recibo, 'CO_AUX_TRANS'), 11.0)
        self.assertAlmostEqual(self._total(recibo, 'CO_AUX_TRANS'), aux / 30.0 * 11, delta=0.01)
        self.assertEqual(recibo._ne_dias_pagables(), 11.0)
        # «antes» = el nativo: horas ÷ horas por día del calendario (otra cosa que 4)
        nativo = 30.0 / self.calendario.hours_per_day
        self.assertNotAlmostEqual(nativo, 4.0, places=2, msg='Premisa: el nativo contaba otra cosa')
        self._como_antes(recibo)
        self.assertAlmostEqual(self._dias(recibo, 'CO_VAC'), nativo, places=3)
        self._como_ahora(recibo)
        self.assertEqual(self._dias(recibo, 'CO_VAC'), 4.0, 'Recalcular vuelve a las fechas')

    def test_02_un_domingo_de_vacacion_cuenta_1_dia_y_no_0_95(self):
        recibo = self._recibo_con(self.leave_vac, date(2026, 9, 6), date(2026, 9, 6))
        dia = recibo.version_id.wage / 30.0
        self.assertEqual(self._dias(recibo, 'CO_VAC'), 1.0)
        self.assertAlmostEqual(self._total(recibo, 'CO_VAC'), dia, delta=0.01)
        self.assertEqual(self._cantidad(recibo, 'CO_BASICO'), 14.0)
        self._como_antes(recibo)
        self.assertAlmostEqual(self._dias(recibo, 'CO_VAC'), 7.0 / self.calendario.hours_per_day, places=3)
        self.assertLess(self._dias(recibo, 'CO_VAC'), 1.0, 'Premisa: el nativo pagaba menos de un día')

    def test_03_una_semana_de_martes_a_lunes_son_6_dias_habiles_y_el_lunes_de_descanso_no_cuenta(self):
        """C-19 (criterio de H-013/H-014 vigente): el domingo cuenta como día hábil del calendario y el lunes de descanso no."""
        recibo = self._recibo_con(self.leave_vac, date(2026, 9, 8), date(2026, 9, 14))
        self.assertEqual(self._dias(recibo, 'CO_VAC'), 6.0)
        self.assertEqual(self._cantidad(recibo, 'CO_BASICO'), 9.0)

    def test_04_la_linea_el_pago_y_el_xml_dicen_los_mismos_dias_en_los_tres_modos_de_redondeo(self):
        recibo = self._recibo_con(self.leave_vac, date(2026, 9, 8), date(2026, 9, 11))
        dias, detalle = recibo._ne_ausencia_habil_tramo('CO_VAC')
        self.assertEqual((dias, len(detalle)), (4, 1))
        self.assertEqual(dias, self._dias(recibo, 'CO_VAC'))
        self.assertEqual(dias, self._cantidad(recibo, 'CO_VAC'))
        for modo in ('UP', 'DOWN', 'HALF-UP'):
            recibo.company_id.l10n_co_ne_redondeo_dias = modo
            self.assertEqual(recibo._ne_dias_xml(recibo._ne_dias_pagables()) + recibo._ne_dias_xml(dias), 15, modo)

    def test_05_la_suma_de_horas_y_de_importes_el_ibc_y_los_dias_pagados_no_cambian(self):
        recibo = self._recibo_con(self.leave_vac, date(2026, 9, 8), date(2026, 9, 11))
        despues = dict(self._cifras(recibo), ibc=self._total(recibo, 'CO_IBC_SALARIAL'), horas=sum(recibo.worked_days_line_ids.mapped('number_of_hours')))
        self.assertEqual(self._dias_pagados(recibo), recibo._ne_dias_pagables())
        self._como_antes(recibo)
        antes = dict(self._cifras(recibo), ibc=self._total(recibo, 'CO_IBC_SALARIAL'), horas=sum(recibo.worked_days_line_ids.mapped('number_of_hours')))
        for clave in ('suma', 'basic', 'gross', 'horas'):
            self.assertAlmostEqual(despues[clave], antes[clave], delta=0.05, msg=clave)
        # con el último IBC igual al sueldo (primera nómina) el IBC salarial se compensa: los dos movimientos suman lo mismo
        self.assertAlmostEqual(despues['ibc'], antes['ibc'], delta=0.05, msg='ibc')

    # ── la fecha: zona, estados, bordes ──────────────────────────────────────────────────────────────────────────────────────
    def test_06_una_entrada_cancelada_o_en_conflicto_de_una_ausencia_validada_no_cuenta(self):
        recibo = self._recibo_con(self.leave_vac, date(2026, 9, 8), date(2026, 9, 11))
        self.assertEqual(recibo._ne_ausencia_habil('CO_VAC')[0], 4)
        entradas = self._entradas_del_dia(recibo, date(2026, 9, 9)).filtered('leave_id')
        self.assertTrue(entradas)
        # N1 sobre staging_dev (22-nov): ``entradas.write({'state': 'cancelled'})`` por el ORM cancela la AUSENCIA entera (``hr_work_entry_holidays`` borra su
        # ``resource.calendar.leaves`` y las entradas): daba 0 días, no 3. Para probar qué cuenta ``_ne_ausencia_habil`` según el estado de la entrada se escribe el
        # estado directo en la base, sin los ganchos del ORM.
        for estado in ('cancelled', 'conflict'):
            self.env.flush_all()
            self.env.cr.execute('UPDATE hr_work_entry SET state = %s WHERE id IN %s', (estado, tuple(entradas.ids)))
            entradas.invalidate_recordset(['state'])
            self.assertEqual(recibo._ne_ausencia_habil('CO_VAC')[0], 3, estado)
        self.env.flush_all()
        self.env.cr.execute("UPDATE hr_work_entry SET state = 'validated' WHERE id IN %s", (tuple(entradas.ids),))
        entradas.invalidate_recordset(['state'])
        self.assertEqual(recibo._ne_ausencia_habil('CO_VAC')[0], 4, 'Validada otra vez: vuelve a contar')

    def test_07_una_entrada_de_la_ausencia_con_duracion_cero_no_cuenta_la_fecha(self):
        """v19: la entrada es de un día y pesa ``duration``; la fecha cuenta si la suma de las horas de la ausencia ese día es mayor que 0 (criterio de v19, que
        reemplaza el de la fecha local del turno nocturno de v18). Con el interruptor apagado y con el encendido."""
        recibo = self._recibo_con(self.leave_vac, date(2026, 9, 8), date(2026, 9, 11))
        entradas = self._entradas_del_dia(recibo, date(2026, 9, 9)).filtered('leave_id')
        self.assertTrue(entradas)
        self.env.flush_all()
        self.env.cr.execute('UPDATE hr_work_entry SET duration = 0 WHERE id IN %s', (tuple(entradas.ids),))
        entradas.invalidate_recordset(['duration'])
        self.assertEqual(recibo._ne_ausencia_habil('CO_VAC')[0], 3, 'Apagado: la fecha sin horas no cuenta')
        self._fraccion(1)
        self.assertEqual(recibo._ne_ausencia_habil('CO_VAC')[0], 3, 'Encendido: tampoco')

    def test_08_la_ausencia_que_cruza_el_periodo_cuenta_solo_las_fechas_del_tramo(self):
        """Vacación del lunes 14 al viernes 18: en la quincena del 1 al 15 solo cuenta el martes 15; en la del 16 al 30, el 16, 17 y 18."""
        primera = self._recibo_con(self.leave_vac, date(2026, 9, 14), date(2026, 9, 18))
        self.assertEqual(primera._ne_ausencia_habil('CO_VAC')[0], 1)
        self.assertEqual(self._dias(primera, 'CO_VAC'), 1.0)
        segunda = self.env['hr.payslip'].create({
            'name': 'Segunda quincena', 'employee_id': primera.employee_id.id, 'version_id': primera.version_id.id, 'company_id': self.company.id,
            'struct_id': self.general.id, 'date_from': date(2026, 9, 16), 'date_to': date(2026, 9, 30)})
        self.assertEqual(segunda._ne_ausencia_habil('CO_VAC')[0], 3)

    def test_09_sin_una_ausencia_validada_la_linea_queda_como_la_del_nativo(self):
        recibo = self._recibo(calcular=False)
        recibo.version_id.generate_work_entries(date(2026, 9, 1), date(2026, 9, 15))
        self._entradas_del_dia(recibo, date(2026, 9, 8)).write({'work_entry_type_id': self.tipo_vac.id})       # entrada suelta: sin hr.leave
        recibo.action_refresh_from_work_entries()
        self.assertEqual(recibo._ne_ausencia_habil('CO_VAC'), (0, []))
        self.assertAlmostEqual(self._dias(recibo, 'CO_VAC'), 7.5 / self.calendario.hours_per_day, places=3, msg='La línea queda como la calculó el nativo')

    # ── el interruptor de fracciones ─────────────────────────────────────────────────────────────────────────────────────────
    def _medio_dia(self):
        """Vacación del martes 8 con 4 h de ausencia y 3,5 h de asistencia ese mismo día. v19: la entrada es de un día y las del mismo tipo y fecha se
        fusionan; la ausencia tiene UNA entrada con ``duration`` y la asistencia se crea aparte (otro tipo): 4 h de ausencia sobre 7,5 h de entradas."""
        recibo = self._recibo_con(self.leave_vac, date(2026, 9, 8), date(2026, 9, 8))
        entrada = self._entradas_del_dia(recibo, date(2026, 9, 8)).filtered('leave_id')
        self.assertEqual(len(entrada), 1, 'Premisa: una entrada del día ligada a la ausencia')
        self.env.flush_all()
        self.env.cr.execute('UPDATE hr_work_entry SET duration = 4.0 WHERE id = %s', (entrada.id,))
        entrada.invalidate_recordset(['duration'])
        self.env['hr.work.entry'].create({
            'name': 'Asistencia de la tarde', 'employee_id': recibo.employee_id.id, 'version_id': recibo.version_id.id,
            'work_entry_type_id': recibo._ne_tipo_asistencia().id, 'date': date(2026, 9, 8), 'duration': 3.5})
        return recibo

    def test_10_con_el_interruptor_apagado_un_medio_dia_cuenta_un_dia_y_encendido_su_fraccion(self):
        recibo = self._medio_dia()
        self.assertEqual(recibo._ne_ausencia_habil('CO_VAC')[0], 1, 'Apagado (de fábrica): días enteros')
        self._fraccion(1)
        fraccion = recibo._ne_ausencia_habil('CO_VAC')[0]
        self.assertAlmostEqual(fraccion, 4.0 / 7.5, places=6, msg='Encendido: horas de la ausencia ÷ horas de todas las entradas de esa fecha')
        self.assertLess(fraccion, 1.0)

    def test_11_sin_el_parametro_hay_un_error_claro_que_dice_donde_crearlo(self):
        recibo = self._recibo_con(self.leave_vac, date(2026, 9, 8), date(2026, 9, 11))
        self.env['hr.rule.parameter'].search([('code', '=', _CODIGO)]).unlink()
        self.env.registry.clear_cache()
        with self.assertRaisesRegex(UserError, _CODIGO):
            recibo._ne_ausencia_habil('CO_VAC')
        recibo_sin_ausencias = self._recibo()
        self.assertTrue(recibo_sin_ausencias.worked_days_line_ids, 'Sin ausencias no se lee el parámetro: el cálculo normal no falla')

    # ── el aviso de líneas desactualizadas ───────────────────────────────────────────────────────────────────────────────────
    def test_12_el_aviso_dice_cuando_los_dias_de_la_pestana_no_coinciden_con_las_fechas(self):
        recibo = self._recibo_con(self.leave_vac, date(2026, 9, 8), date(2026, 9, 11))
        recibo.invalidate_recordset(['l10n_co_ne_aviso_dias'])
        self.assertFalse(recibo.l10n_co_ne_aviso_dias, 'Con las líneas al día no hay aviso')
        self._como_antes(recibo)                                  # líneas como las calculaba el nativo (4,09): quedan desactualizadas
        recibo.invalidate_recordset(['l10n_co_ne_aviso_dias'])
        avisos = recibo._ne_avisos_ausencias_desactualizadas()
        self.assertEqual(len(avisos), 1)
        self.assertIn(self.tipo_vac.name, avisos[0])
        self.assertIn('Recalcular la hoja entera', avisos[0])
        self.assertIn('Recalcular la hoja entera', recibo.l10n_co_ne_aviso_dias)
        self._como_ahora(recibo)
        recibo.invalidate_recordset(['l10n_co_ne_aviso_dias'])
        self.assertFalse(recibo._ne_avisos_ausencias_desactualizadas())
        self.assertFalse(recibo.l10n_co_ne_aviso_dias)

    # ── v19: el empleado con dos versiones en el periodo (HIPÓTESIS del consultor, §10.13 U2; prueba OBLIGATORIA, decisión del TL) ───────────────
    def test_13_empleado_con_dos_versiones_en_el_periodo_la_ausencia_cuenta_solo_las_fechas_de_la_version_del_recibo(self):
        """En v19 el recibo es de UNA versión (``version_id``) y los días fuera de ella salen en la línea ``OUT``; pero el dominio de ``_ne_ausencia_habil`` es por
        EMPLEADO (a propósito: la liquidación cruza versiones del mismo contrato). Empleado con la versión A hasta el lunes 8 de septiembre y la B desde el martes 9
        (mismo contrato), recibo de la quincena del 1 al 15 de la versión B y vacación del martes 8 al viernes 11: la fecha del 8 es de la versión A (1 entrada) y las
        del 9, 10 y 11 de la B (3 entradas). La línea de vacaciones del recibo de la B dice las MISMAS fechas que sus horas (3), no las del empleado (4).
        Si falla en la N1, es el defecto que el consultor sospechaba: .300 mezcla fechas del empleado con horas de la versión del recibo.

        H-F1-10: con ``_ne_rango_de_la_version`` (``_ne_ausencia_habil`` recorta la ventana a la vigencia de la versión del recibo) esta prueba debe PASAR; es el caso del recibo de B
        de la prueba 3 de ``test_rango_de_la_version`` (que suma además los dos recibos)."""
        empleado, version_a = self._contrato()
        valores_b = {campo: valor for campo, valor in VALORES_COLOMBIA.items() if campo in self.env['hr.version']._fields}
        version_b = self.env['hr.version'].create(dict(
            valores_b, employee_id=empleado.id, date_version=date(2026, 9, 9), contract_date_start=version_a.contract_date_start, wage=version_a.wage,
            structure_type_id=self.tipo.id, resource_calendar_id=self.calendario.id))
        self.assertEqual(empleado._get_version(date(2026, 9, 8)), version_a, 'Premisa: el 8 es de la versión A')
        self.assertEqual(empleado._get_version(date(2026, 9, 9)), version_b, 'Premisa: el 9 es de la versión B')
        recibo = self.env['hr.payslip'].create({
            'name': 'Recibo de la versión B', 'employee_id': empleado.id, 'version_id': version_b.id, 'company_id': self.company.id,
            'struct_id': self.general.id, 'date_from': date(2026, 9, 1), 'date_to': date(2026, 9, 15)})
        for version in (version_a, version_b):
            version.generate_work_entries(date(2026, 9, 1), date(2026, 9, 15))
        ausencia = self.env['hr.leave'].create({
            'employee_id': empleado.id, 'holiday_status_id': self.leave_vac.id, 'request_date_from': date(2026, 9, 8), 'request_date_to': date(2026, 9, 11)})
        ausencia.action_approve(check_state=False)
        recibo.action_refresh_from_work_entries()
        entradas = self.env['hr.work.entry'].search([('leave_id', '=', ausencia.id), ('state', 'in', ('draft', 'validated'))])
        fechas_de_la_version = {e.date for e in entradas if e.version_id == version_b and e.duration > 0}
        self.assertEqual(fechas_de_la_version, {date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11)}, 'Premisa: la versión B tiene 3 fechas de la ausencia')
        self.assertEqual(len({e.date for e in entradas}), 4, 'Premisa: el empleado tiene 4 fechas (la del 8 es de la versión A)')
        horas_de_la_version = sum(e.duration for e in entradas if e.version_id == version_b)
        self.assertEqual(self._dias(recibo, 'CO_VAC'), len(fechas_de_la_version), 'Los días de la línea son los de la versión del recibo')
        dia = version_b.wage / 30.0
        self.assertAlmostEqual(self._total(recibo, 'CO_VAC'), len(fechas_de_la_version) * dia, delta=0.01,
                               msg='El importe sale de los días de la versión del recibo (%s h)' % horas_de_la_version)
