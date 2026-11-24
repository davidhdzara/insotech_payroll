# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""H-F2-02 (decision del TL del 22-nov, corregida por el mismo TL): el numero de horas laboradas del registro tipo 2 de la PILA (campo 96) ya no es ``dias * 8`` fijo: sale de UNA funcion,
``HrVersion._ne_horas_laboradas_pila(dias, fecha)``: las horas SEMANALES del calendario de trabajo de la version (v19, opcion A del TL: el campo NATIVO ``resource.calendar.hours_per_week``; en un horario fijo lo
calcula el nativo de las asistencias de trabajo, sin el almuerzo ni las secciones, y en uno de dos semanas es la suma de las dos / 2; en uno FLEXIBLE es el dato que la persona declaro) / 7 por los dias cotizados
de CCF/SENA/ICBF, a entero. La misma jornada da el mismo resultado trabaje 5 o 6 dias a la semana (la formula «horas por dia x dias cotizados» daba 252 y 210 para 42 h). Sin horas semanales el campo va VACIO
(es opcional para la mayoria de los tipos). Si el tipo de cotizante lo exige (parametro ``l10n_co_pila_horas_laboradas_tipos``, de fabrica el 51) y no hay de donde sacarlo, error claro que nombra al empleado.

Valores a mano (30 dias cotizados): 42 h semanales (en 5 o en 6 dias) -> 42 / 7 x 30 = 180; 48 h -> 205,71 -> 206; 40 h con una hora de almuerzo por dia (que no cuenta) -> 171,43 -> 171; horario de dos semanas
de 36 h y 48 h -> (84 / 2 = 42) -> 180; flexible con 42 h declaradas -> 180 (en v18 daba vacio: divergencia aceptada, v19 declara las horas). Premisas por confirmar en la N1 (NO VERIFICADAS al escribir): que
``hours_per_week`` se calcule asi con estos fixtures, que un calendario creado con ``schedule_type='flexible'`` y ``hours_per_week`` en el mismo ``create`` conserve el valor, y que la restriccion de los
horarios de dos semanas acepte el fixture (secciones al inicio de cada semana)."""

from datetime import date

from odoo.addons.l10n_co_nomina_electronica.services import pila_generator_v2 as generador
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from . import test_pension_no_exigida as pension
from .common_version import confirmar_a_mano
from .test_pila_ubicacion_laboral import ubicaciones_de_prueba

FECHA = date(2026, 3, 1)
PARAMETRO_VALOR = 'l10n_co_nomina_electronica.rule_parameter_pila_horas_laboradas_tipos_v'


@tagged('post_install', '-at_install')
class TestPilaHorasLaboradas(pension.TestPensionNoExigida):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # H-F4-08: el registro tipo 2 ahora exige la Direccion de Trabajo completa (campos 9 y 10 de la PILA; por defecto, la del contacto de la compañia, antes de crear a los empleados).
        [(departamento, ciudad)] = ubicaciones_de_prueba(cls.env, 1)
        cls.company.partner_id.write({'country_id': cls.env.ref('base.co').id, 'state_id': departamento.id, 'city_id': ciudad.id, 'street': 'Calle de prueba # 1-1'})
        cls.cal_42 = cls._calendario('42 horas en 6 dias', (0, 1, 2, 3, 4, 5), ((8.0, 12.0), (13.0, 16.0)))                          # 6 dias de 7 h
        cls.cal_42_en_5 = cls._calendario('42 horas en 5 dias', (0, 1, 2, 3, 4), ((8.0, 12.0), (13.0, 17.4)))                       # 5 dias de 8,4 h
        cls.cal_48 = cls._calendario('48 horas en 6 dias', (0, 1, 2, 3, 4, 5), ((8.0, 12.0), (13.0, 17.0)))                         # 6 dias de 8 h
        cls.cal_40_con_almuerzo = cls._calendario('40 horas con almuerzo', (0, 1, 2, 3, 4), ((8.0, 12.0), (13.0, 17.0)), almuerzo=True)
        cls.cal_dos_semanas = cls._calendario_dos_semanas('36 y 48 horas')
        # v19: horario FLEXIBLE = ``schedule_type='flexible'`` y las horas de la semana que la persona declara en ``hours_per_week`` (sin asistencias); el nativo no las calcula
        cls.cal_flexible = cls.env['resource.calendar'].create({'name': 'Flexible 42 horas', 'tz': 'America/Bogota', 'schedule_type': 'flexible', 'hours_per_week': 42.0})
        cls.cal_flexible_sin_horas = cls.env['resource.calendar'].create({'name': 'Flexible sin horas', 'tz': 'America/Bogota', 'schedule_type': 'flexible'})

    @classmethod
    def _calendario(cls, nombre, dias, franjas, almuerzo=False):
        lineas = []
        for dia in dias:
            for numero, (desde, hasta) in enumerate(franjas):
                lineas.append((0, 0, {'name': '%s %s %s' % (nombre, dia, numero), 'dayofweek': str(dia), 'hour_from': desde, 'hour_to': hasta, 'day_period': 'morning' if numero == 0 else 'afternoon'}))
            if almuerzo:
                lineas.append((0, 0, {'name': '%s %s almuerzo' % (nombre, dia), 'dayofweek': str(dia), 'hour_from': 12.0, 'hour_to': 13.0, 'day_period': 'lunch'}))
        return cls.env['resource.calendar'].create({'name': nombre, 'tz': 'America/Bogota', 'attendance_ids': lineas})

    @classmethod
    def _calendario_dos_semanas(cls, nombre):
        """Semana 1: 6 dias de 6 h (36 h); semana 2: 6 dias de 8 h (48 h). Cada semana va bajo su seccion (el nativo exige que todas las asistencias esten en secciones)."""
        lineas = []
        for semana, (secuencia, franjas) in enumerate(((0, ((8.0, 12.0), (13.0, 15.0))), (25, ((8.0, 12.0), (13.0, 17.0))))):
            lineas.append((0, 0, {'name': 'Semana %s' % (semana + 1), 'dayofweek': '0', 'sequence': secuencia, 'hour_from': 0.0, 'hour_to': 0.0, 'day_period': 'morning', 'week_type': str(semana), 'display_type': 'line_section'}))
            for dia in range(6):
                for numero, (desde, hasta) in enumerate(franjas):
                    lineas.append((0, 0, {'name': 'S%s %s %s' % (semana + 1, dia, numero), 'dayofweek': str(dia), 'sequence': secuencia + 1, 'hour_from': desde, 'hour_to': hasta,
                                          'day_period': 'morning' if numero == 0 else 'afternoon', 'week_type': str(semana)}))
        return cls.env['resource.calendar'].create({'name': nombre, 'tz': 'America/Bogota', 'two_weeks_calendar': True, 'attendance_ids': lineas})

    def _contrato(self, nombre, calendario, tipo='01'):
        """Contrato de un empleado con el horario dado (``None`` = sin horario) y el tipo de cotizante."""
        _empleado, recibo = self._empleado_y_recibo(nombre, tipo=tipo, eps=self.eps, afp=self.afp, ccf=self.ccf, desde=FECHA, hasta=date(2026, 3, 31))
        contrato = recibo.version_id
        contrato.write({'resource_calendar_id': calendario.id if calendario else False})
        if not calendario:
            self.assertFalse(contrato.resource_calendar_id, 'Premisa: el contrato queda sin horario de trabajo')
        return contrato

    # ── la funcion ──
    def test_42_horas_semanales_dan_180_en_30_dias_trabaje_5_o_6_dias(self):
        """La misma jornada de 42 h da lo mismo con 5 dias de 8,4 h que con 6 dias de 7 h (con horas por dia x dias cotizados daba 252 y 210)."""
        en_6 = self._contrato('Cuarenta y Dos en Seis', self.cal_42)
        en_5 = self._contrato('Cuarenta y Dos en Cinco', self.cal_42_en_5)
        self.assertAlmostEqual(en_6._ne_horas_semanales(), 42.0, places=6)
        self.assertAlmostEqual(en_5._ne_horas_semanales(), 42.0, places=6)
        for contrato in (en_6, en_5):
            self.assertEqual(contrato._ne_horas_laboradas_pila(30, FECHA), 180)
            self.assertEqual(contrato._ne_horas_laboradas_pila(15, FECHA), 90)
            self.assertEqual(contrato._ne_horas_laboradas_pila(28, FECHA), 168)

    def test_horario_de_48_horas_semanales_da_206_en_30_dias_y_se_redondea_a_entero(self):
        contrato = self._contrato('Cuarenta y Ocho', self.cal_48)
        self.assertAlmostEqual(contrato._ne_horas_semanales(), 48.0, places=6)
        self.assertEqual(contrato._ne_horas_laboradas_pila(30, FECHA), 206)                  # 205,71
        self.assertEqual(contrato._ne_horas_laboradas_pila(15, FECHA), 103)                  # 102,86
        self.assertEqual(contrato._ne_horas_laboradas_pila(28, FECHA), 192)

    def test_el_almuerzo_no_cuenta(self):
        contrato = self._contrato('Con Almuerzo', self.cal_40_con_almuerzo)
        self.assertAlmostEqual(contrato._ne_horas_semanales(), 40.0, places=6)               # 5 dias de 8 h; las 5 horas de almuerzo no suman
        self.assertEqual(contrato._ne_horas_laboradas_pila(30, FECHA), 171)                  # 171,43

    def test_horario_de_dos_semanas_es_la_suma_de_las_dos_dividida_por_2(self):
        contrato = self._contrato('Dos Semanas', self.cal_dos_semanas)
        self.assertAlmostEqual(contrato._ne_horas_semanales(), 42.0, places=6)               # (36 + 48) / 2; las secciones no suman
        self.assertEqual(contrato._ne_horas_laboradas_pila(30, FECHA), 180)

    def test_sin_horario_el_campo_va_vacio_si_el_tipo_no_lo_exige(self):
        self.assertEqual(self._contrato('Sin Horario', None)._ne_horas_laboradas_pila(30, FECHA), '')

    def test_horario_flexible_con_horas_declaradas_da_las_horas_y_sin_declarar_el_campo_va_vacio(self):
        """v19 (opcion A del TL): el flexible SI declara horas: 42 h = 180 en 30 dias (v18 lo dejaba vacio). Un flexible sin horas declaradas (0) va vacio."""
        con_horas = self._contrato('Flexible Con Horas', self.cal_flexible)
        self.assertEqual(self.cal_flexible.schedule_type, 'flexible')
        self.assertAlmostEqual(con_horas._ne_horas_semanales(), 42.0, places=6)              # premisa: el create conserva las horas declaradas
        self.assertEqual(con_horas._ne_horas_laboradas_pila(30, FECHA), 180)
        sin_horas = self._contrato('Flexible Sin Horas', self.cal_flexible_sin_horas)
        self.assertEqual(sin_horas._ne_horas_laboradas_pila(30, FECHA), '')

    def test_el_tipo_51_sin_horas_semanales_da_error_que_nombra_al_empleado_y_la_version(self):
        """Sin calendario o con un flexible sin horas declaradas: el tipo 51 exige el campo 96 y el error nombra al empleado, dice «horas semanales» y la fecha de la version (v19)."""
        for nombre, calendario in (('Cincuenta y Uno Sin Horario', None), ('Cincuenta y Uno Flexible Sin Horas', self.cal_flexible_sin_horas)):
            with self.subTest(nombre):
                contrato = self._contrato(nombre, calendario, tipo='51')
                with self.assertRaises(UserError) as exc:
                    contrato._ne_horas_laboradas_pila(30, FECHA)
                texto = str(exc.exception)
                for esperado in (nombre, 'campo 96', 'horas semanales', '51', str(contrato.date_version)):
                    self.assertIn(esperado, texto)

    def test_el_tipo_51_con_horario_da_las_horas_sin_error(self):
        self.assertEqual(self._contrato('Cincuenta y Uno Con Horario', self.cal_42, tipo='51')._ne_horas_laboradas_pila(30, FECHA), 180)

    # ── la lista de tipos es un dato ──
    def test_quitar_el_tipo_del_parametro_deja_el_campo_vacio_y_agregarlo_lo_exige(self):
        contrato_51 = self._contrato('Quitado 51', None, tipo='51')
        contrato_22 = self._contrato('Agregado 22', None, tipo='22')           # el 18 no es un valor del tipo de cotizante del contrato (N2 «dc»: ``Wrong value for l10n_co_pila_tipo_cotizante: '18'``); el 22 si
        self.assertEqual(contrato_22._ne_horas_laboradas_pila(30, FECHA), '')                # de fabrica solo el 51
        self.env.ref(PARAMETRO_VALOR).parameter_value = "['22']"
        self.assertEqual(contrato_51._ne_horas_laboradas_pila(30, FECHA), '')
        with self.assertRaisesRegex(UserError, 'campo 96'):
            contrato_22._ne_horas_laboradas_pila(30, FECHA)

    def test_sin_el_parametro_un_error_que_lo_nombra(self):
        contrato = self._contrato('Sin Parametro', None)
        self.env['hr.rule.parameter'].search([('code', '=', 'l10n_co_pila_horas_laboradas_tipos')]).unlink()
        with self.assertRaisesRegex(UserError, 'l10n_co_pila_horas_laboradas_tipos'):
            contrato._ne_horas_laboradas_pila(30, FECHA)

    # ── el registro del archivo ──
    def test_el_generador_deja_vacio_el_campo_96_sin_dato_y_no_cambia_los_demas_enteros(self):
        posicion = [nombre for nombre, _tipo in generador._TIPO_02_FIELDS].index('horas_laboradas')
        self.assertEqual(posicion + 1, 96)                                                   # el campo 96 del registro tipo 2
        for valor, esperado in ((210, '210'), ('', ''), (None, ''), (0, '0')):
            campos = generador.generate_tipo_02({'horas_laboradas': valor}).split(generador.PIPE)
            self.assertEqual(campos[posicion], esperado, valor)
        otro = generador.generate_tipo_02({}).split(generador.PIPE)
        self.assertEqual(otro[[nombre for nombre, _tipo in generador._TIPO_02_FIELDS].index('dias_pension')], '0')     # un entero obligatorio sin dato sigue en 0

    # ── el asistente de PILA la usa ──
    def test_el_asistente_arma_el_campo_con_el_horario_del_contrato(self):
        """Mes completo de marzo (30 dias cotizados): con el horario de 42 h el cotizante lleva 180 y sin horario el campo va vacio. Premisas por confirmar en la N1: el armado del cotizante con un recibo
        confirmado de este fixture (centro de trabajo del contrato, caja por empleado) no pide mas datos."""
        for nombre, calendario, esperado in (('Asistente Con Horario', self.cal_42, 180), ('Asistente Sin Horario', None, '')):
            with self.subTest(nombre):
                empleado, recibo = self._calculado(nombre, eps=self.eps, afp=self.afp, ccf=self.ccf)
                empleado.write({'l10n_co_primer_nombre': 'Asistente', 'l10n_co_primer_apellido': 'Horario'})       # un nombre de tres palabras no se parte solo (``_l10n_co_nombre_dian`` los exige)
                recibo.version_id.write({'resource_calendar_id': calendario.id if calendario else False, 'l10n_co_pila_centro_trabajo': '1'})
                confirmar_a_mano(recibo)                                    # v19: 'done' no existe
                datos = self.env['l10n.co.hr.pila.wizard.v2'].new({'company_id': self.company.id})._build_cotizante_data(recibo, 1)
                self.assertEqual(datos['dias_ccf'], 30)
                self.assertEqual(datos['horas_laboradas'], esperado)
