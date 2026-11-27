# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""R-2 (doc 108, opción C; David, 25-nov; porte a v19 de v18 .325-.327): la retención del Procedimiento 1 se calcula sobre los pagos gravables del MES y se descuenta completa en el recibo que cierra el
mes. Los anteriores no retienen y no hay reintegros. Qué entra en la base sale del parámetro ``l10n_co_retefuente_base_mes``. Si la retención no cabe en el recibo de cierre se retiene lo disponible y
confirmar exige la autorización del administrador de nómina; ningún recibo colombiano se confirma con neto negativo. Mes partido (H-F1-10, decisión del TL del 26-nov, opción A): no cierra el recibo que
tiene otra versión posterior en el mes; el cierre suma los anteriores calculados con él y se confirma junto con ellos. Valores a mano con la UVT 2026 (52.374): 12.000.000 mensuales retienen 642.432.
NO EJECUTADAS en Odoo 19 al escribirlas."""

import re
from datetime import date
from unittest.mock import patch

from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from .common_version import confirmar_a_mano, crear_aumento, crear_empleado_con_contrato, crear_usuario_nomina

NATIVO = 'odoo.addons.hr_payroll.models.hr_payslip.HrPayslip.action_payslip_done'
PARAMETRO = 'l10n_co_retefuente_base_mes'
PREFIJO = 'l10n_co_nomina_electronica.'
BASE_APROBADA = {
    'categorias': ['DEV_SAL', 'VAC', 'INC', 'DEV_NOSAL'],
    'reglas_excluidas': ['CO_AUX_TRANS', 'CO_AUX_ALIM', 'CO_VIATICOS_NOSAL', 'CO_DOTACION', 'CO_TELETRABAJO', 'CO_BONIF_RET', 'CO_INDEMNIZ'],
    'reglas_adicionales_liquidacion': ['CO_LIQ_CESANTIAS', 'CO_LIQ_INT_CES'],
}
RETENCION_12M = 642432.0
INGRESO = date(2024, 1, 1)


class MontajeRetencionMes(TransactionCase):
    """Montaje compartido (sin pruebas propias)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U', 'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_clase_riesgo': '1',
            'l10n_co_ne_febrero_modo': 'real', 'l10n_co_ne_redondeo_dias': 'DOWN', 'name': 'Compañía Retención del Mes'})
        cls.env = cls.company.with_company(cls.company).env
        cls.env.user.group_ids = [Command.link(cls.env.ref('hr_payroll.group_hr_payroll_manager').id)]          # cancelar un recibo confirmado lo exige
        cls.config = cls.env['l10n.co.retefuente.uvt'].create({'year': '2026', 'company_id': cls.company.id, 'procedure': '1'})
        cls.tipo = cls.env['hr.payroll.structure.type'].create({'name': 'Retención del Mes', 'country_id': cls.env.ref('base.co').id})
        cls.general = cls.env.ref(PREFIJO + 'hr_payroll_structure_co_nomina')
        cls.bonificacion = cls.env.ref(PREFIJO + 'hr_payroll_structure_co_bonificacion')
        cls.liquidacion = cls.env.ref(PREFIJO + 'hr_payroll_structure_co_liquidacion')
        cls.entidad = cls.env['res.partner'].create({'name': 'Entidad Retención del Mes', 'l10n_co_entity_type': 'other'})
        cls.n = 0

    # ── fixtures ─────────────────────────────────────────────────────
    def _contrato(self, salario=12000000.0, periodicidad='semi-monthly', fin=None, tipo=None, **extra):
        """La versión del contrato. ``schedule_pay`` va explícito: en v19 la versión nace mensual aunque el tipo de estructura diga otra cosa."""
        type(self).n += 1
        _empleado, version = crear_empleado_con_contrato(
            self.env, self.company, salario, INGRESO, tipo or self.tipo, nombre='Empleado Retención %s' % self.n, fin=fin, schedule_pay=periodicidad, **extra)
        version.generate_work_entries(date(2026, 8, 1), date(2026, 10, 31))
        return version

    def _procedimiento_2(self, contrato, porcentaje=10.0, semestre=date(2026, 7, 1)):
        """El procedimiento se fija por SQL: por ORM solo se cambia en junio o diciembre."""
        contrato.flush_recordset()
        self.env.cr.execute('UPDATE hr_version SET l10n_co_ne_retention_procedure = %s WHERE id = %s', ('2', contrato.id))
        contrato.invalidate_recordset(['l10n_co_ne_retention_procedure'])
        return self.env['l10n.co.retefuente.procedure2'].create({
            'employee_id': contrato.employee_id.id, 'semester_start': semestre, 'fixed_percentage': porcentaje, 'months_considered': 12})

    def _recibo(self, contrato, desde, hasta, estructura=None, novedades=(), calculado=True, **extra):
        type(self).n += 1
        entradas = [Command.create({
            'input_type_id': self.env.ref(PREFIJO + 'input_%s' % codigo.lower()).id, 'amount': monto}) for codigo, monto in novedades]
        recibo = self.env['hr.payslip'].create(dict({
            'name': 'Recibo Retención %s' % self.n, 'employee_id': contrato.employee_id.id, 'version_id': contrato.id, 'company_id': self.company.id,
            'struct_id': (estructura or self.general).id, 'date_from': desde, 'date_to': hasta, 'input_line_ids': entradas}, **extra))
        if calculado:
            recibo.compute_sheet()
        return recibo

    def _primera(self, contrato, **extra):
        return self._recibo(contrato, date(2026, 9, 1), date(2026, 9, 15), **extra)

    def _segunda(self, contrato, **extra):
        return self._recibo(contrato, date(2026, 9, 16), date(2026, 9, 30), **extra)

    def _hecho(self, recibo):
        confirmar_a_mano(recibo)
        return recibo

    def _total(self, recibo, codigo):
        return sum(recibo.line_ids.filtered(lambda l: l.code == codigo).mapped('total'))

    def _oraculo(self, recibo, base, ibc, **extra):
        """La depuración y la tabla de siempre (``compute_retefuente``) sobre una base escrita a mano en la prueba; sin ``aporte_salud``/``aporte_pension``, los aportes salen de ``ibc``."""
        return self.config.compute_retefuente(
            recibo.employee_id, base, ibc, ibc, self.company, contract=recibo.version_id, payslip=recibo, **extra)['retencion_pesos']

    def _aportes(self, *recibos):
        """Salud y pensión del trabajador efectivamente descontadas en ``recibos`` (códigos de la nómina, escritos a mano)."""
        return {'aporte_salud': -sum(self._total(r, 'CO_SALUD_EMP') for r in recibos), 'aporte_pension': -sum(self._total(r, 'CO_PENSION_EMP') for r in recibos)}

    def _ausencia(self, contrato, xmlid, desde, hasta):
        ausencia = self.env['hr.leave'].create({
            'employee_id': contrato.employee_id.id, 'holiday_status_id': self.env.ref(PREFIJO + xmlid).id,
            'request_date_from': desde, 'request_date_to': hasta})
        ausencia.action_approve(check_state=False)
        self.assertEqual(ausencia.state, 'validate')

    def _confirmar(self, recibos):
        """Confirma con lo ajeno a la retención parchado; devuelve el parche del nativo (llamado = pasaron las comprobaciones)."""
        tipo = type(recibos)
        nombres = ['_ne_validar_duracion_periodo', '_ne_validar_sin_solape', '_ne_validar_cuenta_neto', '_ne_validar_pacto_no_salarial', '_ne_validar_afiliaciones',
                   '_ne_aplicar_libranzas', '_ne_refrescar_ibc_mensual']
        if hasattr(tipo, '_action_create_account_move'):
            nombres.append('_action_create_account_move')
        parches = [patch.object(tipo, nombre) for nombre in nombres]
        for parche in parches:
            parche.start()
        try:
            with patch(NATIVO, return_value=True) as nativo:
                recibos.action_payslip_done()
        finally:
            for parche in parches:
                parche.stop()
        return nativo

    # ── ayudas de anulación ──────────────────────────────────────────
    def _mes_cerrado(self):
        contrato = self._contrato()
        return self._hecho(self._primera(contrato)), self._hecho(self._segunda(contrato))

    def _reembolso_de(self, recibo):
        return self.env['hr.payslip'].search([('origin_payslip_id', '=', recibo.id), ('credit_note', '=', True)])

    def _no_se_anula(self, recibo, cierre):
        """Ni cancelar, ni volver a borrador (por la acción o escribiendo el estado, como el lote), ni reembolsar: error que nombra el cierre y el recibo queda como estaba."""
        estado = recibo.state
        for operacion in ('action_payslip_cancel', 'action_payslip_draft', 'refund_sheet'):
            with self.subTest(operacion=operacion), self.assertRaisesRegex(UserError, re.escape(cierre._ne_referencia())):
                getattr(recibo, operacion)()
        with self.subTest(operacion='write'), self.assertRaisesRegex(UserError, re.escape(cierre._ne_referencia())):
            recibo.write({'state': 'draft'})
        self.assertEqual(recibo.state, estado)
        self.assertFalse(self._reembolso_de(recibo))


@tagged('post_install', '-at_install')
class TestRetefuenteMes(MontajeRetencionMes):

    # ── qué recibo cierra el mes ─────────────────────────────────────
    def test_cierra_el_mes_segun_la_periodicidad_y_el_fin_del_contrato(self):
        casos = {
            'monthly': ((date(2026, 9, 1), date(2026, 9, 30), True),),
            'semi-monthly': ((date(2026, 9, 1), date(2026, 9, 15), False), (date(2026, 9, 16), date(2026, 9, 30), True),
                             (date(2026, 8, 21), date(2026, 9, 5), False), (date(2026, 9, 6), date(2026, 9, 20), True)),
            'weekly': ((date(2026, 9, 15), date(2026, 9, 21), False), (date(2026, 9, 22), date(2026, 9, 28), True)),
            'bi-weekly': ((date(2026, 8, 29), date(2026, 9, 11), False), (date(2026, 9, 12), date(2026, 9, 25), True)),
        }
        for periodicidad, periodos in casos.items():
            contrato = self._contrato(periodicidad=periodicidad)
            for desde, hasta, cierra in periodos:
                with self.subTest(periodicidad=periodicidad, hasta=hasta):
                    self.assertEqual(self._recibo(contrato, desde, hasta, calculado=False)._ne_rete_es_cierre(), cierra)
        retirado = self._contrato(fin=date(2026, 9, 10))
        self.assertTrue(self._primera(retirado, calculado=False)._ne_rete_es_cierre(), 'El contrato termina dentro del periodo: ese recibo cierra')

    # ── el cálculo del mes ───────────────────────────────────────────
    def test_mensual_retiene_el_mes_completo(self):
        recibo = self._recibo(self._contrato(periodicidad='monthly'), date(2026, 9, 1), date(2026, 9, 30))
        self.assertAlmostEqual(self._total(recibo, 'CO_RETEFUENTE'), -RETENCION_12M, delta=1.0)
        self.assertAlmostEqual(self._total(recibo, 'CO_RETEFUENTE_BASE_GROSS'), 12000000.0, delta=1.0)
        self.assertEqual(recibo.l10n_co_ne_rete_faltante, 0.0)

    def test_quincenal_la_primera_no_retiene_y_la_de_cierre_retiene_el_mes(self):
        contrato = self._contrato()
        primera = self._primera(contrato)
        self.assertFalse(primera.line_ids.filtered(lambda l: l.code == 'CO_RETEFUENTE'), 'D4: el recibo que no cierra no lleva línea')
        self.assertAlmostEqual(self._total(primera, 'CO_RETEFUENTE_BASE_GROSS'), 6000000.0, delta=1.0)
        self.assertAlmostEqual(self._total(primera, 'CO_RETEFUENTE_BASE_IBC'), 6000000.0, delta=1.0)
        self._hecho(primera)
        segunda = self._segunda(contrato)
        self.assertAlmostEqual(self._total(segunda, 'CO_RETEFUENTE'), -RETENCION_12M, delta=1.0)
        self.assertAlmostEqual(self._total(segunda, 'CO_RETEFUENTE_BASE_GROSS'), 6000000.0, delta=1.0, msg='La base guardada es la del propio recibo')

    def test_el_cierre_con_un_anterior_sin_confirmar_es_un_error_que_lo_nombra(self):
        contrato = self._contrato()
        primera = self._primera(contrato)
        segunda = self._segunda(contrato, calculado=False)
        with self.assertRaisesRegex(UserError, re.escape(primera._ne_referencia())):
            segunda.compute_sheet()
        self.assertFalse(segunda.line_ids)

    def test_lo_ya_retenido_en_el_mes_se_resta_y_nunca_sale_negativo(self):
        for retenido, esperado in ((200000.0, RETENCION_12M - 200000.0), (900000.0, 0.0)):
            contrato = self._contrato()
            primera = self._hecho(self._primera(contrato))
            regla = self.general.rule_ids.filtered(lambda r: r.code == 'CO_RETEFUENTE')
            self.env['hr.payslip.line'].create({
                'slip_id': primera.id, 'salary_rule_id': regla.id, 'code': 'CO_RETEFUENTE', 'name': regla.name, 'version_id': contrato.id,
                'employee_id': contrato.employee_id.id, 'quantity': 1.0, 'rate': 100.0, 'amount': -retenido, 'total': -retenido})
            self.assertAlmostEqual(self._total(self._segunda(contrato), 'CO_RETEFUENTE'), -esperado, delta=1.0)

    def test_las_comisiones_de_la_segunda_quincena_entran_en_el_mes(self):
        contrato = self._contrato()
        self._hecho(self._primera(contrato))
        segunda = self._segunda(contrato, novedades=[('CO_COMISIONES', 3000000.0)])
        self.assertAlmostEqual(-self._total(segunda, 'CO_RETEFUENTE'), self._oraculo(segunda, 15000000.0, 15000000.0), delta=1.0)

    def test_procedimiento_2_retiene_en_cada_recibo_sobre_sus_propios_pagos(self):
        contrato = self._contrato()
        self._procedimiento_2(contrato)
        primera = self._primera(contrato)
        esperado = self._oraculo(primera, 6000000.0, 6000000.0)
        self.assertGreater(esperado, 0.0)
        self.assertAlmostEqual(-self._total(primera, 'CO_RETEFUENTE'), esperado, delta=1.0)
        segunda = self._segunda(contrato)         # no exige confirmar la primera: no lee otros recibos
        self.assertAlmostEqual(-self._total(segunda, 'CO_RETEFUENTE'), esperado, delta=1.0)

    # ── la depuración resta los aportes efectivamente descontados ────
    def _comprobar_mes_con_aportes_reales(self, primera, segunda):
        """La retención del cierre resta los aportes descontados de verdad, mayores que los que saldrían de la base salarial."""
        base, ibc = (self._total(primera, c) + self._total(segunda, c) for c in ('CO_RETEFUENTE_BASE_GROSS', 'CO_RETEFUENTE_BASE_IBC'))
        reales = self._aportes(primera, segunda)
        self.assertGreater(reales['aporte_salud'], ibc * 0.04 + 1.0, 'Premisa: se cotizó sobre más que la base salarial')
        esperado = self._oraculo(segunda, base, ibc, fecha_mes=date(2026, 9, 30), **reales)
        self.assertGreater(esperado, 0.0)
        self.assertAlmostEqual(-self._total(segunda, 'CO_RETEFUENTE'), esperado, delta=1.0)
        # Discrimina: con los aportes calculados sobre la base salarial saldría otro valor. No siempre mayor: en 150 UVT la tabla del art. 383 baja de 10,45 a 10 UVT.
        self.assertNotAlmostEqual(esperado, self._oraculo(segunda, base, ibc, fecha_mes=date(2026, 9, 30)), delta=1.0)

    def test_vacaciones_disfrutadas_en_el_mes_restan_sus_aportes(self):
        contrato = self._contrato()
        self._ausencia(contrato, 'hr_leave_type_co_vac', date(2026, 9, 7), date(2026, 9, 11))
        primera = self._hecho(self._primera(contrato))
        self.assertGreater(self._total(primera, 'CO_VAC'), 0.0, 'Premisa: la quincena paga vacaciones')
        self._comprobar_mes_con_aportes_reales(primera, self._segunda(contrato))

    def test_la_incapacidad_en_el_mes_resta_sus_aportes(self):
        contrato = self._contrato()
        self._ausencia(contrato, 'hr_leave_type_co_inc_comun', date(2026, 9, 7), date(2026, 9, 11))
        primera = self._hecho(self._primera(contrato))
        self.assertGreater(self._total(primera, 'CO_INC_COMUN'), 0.0, 'Premisa: la quincena paga incapacidad')
        segunda = self._segunda(contrato)
        self._comprobar_mes_con_aportes_reales(primera, segunda)
        # A mano (UVT 52.374): básico 4.000.000 + incapacidad 1.333.400 (5 días x 400.000 x 66,67 %) + segunda quincena 6.000.000 = 11.333.400; salud y pensión 453.336 + 453.336; 25 % de 10.426.728 = 2.606.682;
        # base 7.820.046 = 149,3116 UVT; (149,3116 - 95) x 19 % = 10,3192 UVT = 540.458. Con aportes sobre los 10.000.000 salariales: base 7.900.050 = 150,8392 UVT = 10 + 0,8392 x 28 % = 536.046 (salto en 150).
        self.assertAlmostEqual(-self._total(segunda, 'CO_RETEFUENTE'), 540458.0, delta=1.0)

    def test_el_exceso_del_40_por_ciento_resta_sus_aportes(self):
        recibo = self._recibo(self._contrato(periodicidad='monthly'), date(2026, 9, 1), date(2026, 9, 30), novedades=[('CO_BONIF_NOSAL', 20000000.0)])
        reales = self._aportes(recibo)
        self.assertGreater(reales['aporte_salud'], 480000.0 + 1.0, 'Premisa: el exceso del 40 % sumó a los aportes')
        self.assertAlmostEqual(-self._total(recibo, 'CO_RETEFUENTE'), self._oraculo(recibo, 32000000.0, 12000000.0, **reales), delta=1.0)

    def test_el_porcentaje_fijo_promedia_meses_confirmados_y_pagados_con_los_aportes_descontados(self):
        """v19: antes el promedio solo tomaba ``validated`` y promediaba recibos; los pagados también entran y la unidad es el mes."""
        contrato = self._contrato()
        semestre = self._procedimiento_2(contrato, porcentaje=0.0)
        primera = self._primera(contrato, novedades=[('CO_BONIF_NOSAL', 20000000.0)])
        confirmar_a_mano(primera, 'paid', paid_date=date(2026, 9, 15))
        recibos = [primera, self._hecho(self._segunda(contrato))]
        base, ibc = (sum(self._total(r, c) for r in recibos) for c in ('CO_RETEFUENTE_BASE_GROSS', 'CO_RETEFUENTE_BASE_IBC'))
        with freeze_time('2026-06-15'):
            contrato.action_calculate_retention_procedure2()
        calculo = self.config.compute_retefuente(
            contrato.employee_id, base, ibc, ibc, self.company, contract=contrato, force_procedure='1', **self._aportes(*recibos))
        self.assertEqual(semestre.months_considered, 1)
        self.assertAlmostEqual(semestre.average_gross, base, delta=1.0)
        self.assertAlmostEqual(semestre.fixed_percentage, calculo['retencion_uvt'] / calculo['base_uvt'] * 100, places=2)

    def test_el_porcentaje_fijo_usa_la_tabla_vigente_el_dia_del_calculo(self):
        """.334: en diciembre se calcula el semestre siguiente (UVT de ese año) con la tabla vigente ese día, no con la que ya esté cargada para el 1 de enero. Tablas planas: el porcentaje es el de la tabla."""
        contrato = self._contrato()
        self._procedimiento_2(contrato, porcentaje=0.0)          # el recibo de septiembre necesita el porcentaje de su semestre
        self.env['l10n.co.retefuente.uvt'].create({'year': '2027', 'company_id': self.company.id, 'procedure': '1'})
        self._hecho(self._primera(contrato, novedades=[('CO_BONIF_NOSAL', 20000000.0)]))
        tabla = self.env.ref(PREFIJO + 'rule_parameter_tabla_retencion_art383')
        for desde, tarifa in ((date(2026, 12, 1), '0.20'), (date(2027, 1, 1), '0.30')):
            self.env['hr.rule.parameter.value'].create({'rule_parameter_id': tabla.id, 'date_from': desde, 'parameter_value': '[(0, None, %s, 0)]' % tarifa})
        with freeze_time('2026-12-10'):
            contrato.action_calculate_retention_procedure2()
        semestre = self.env['l10n.co.retefuente.procedure2'].search([('employee_id', '=', contrato.employee_id.id), ('semester_start', '=', date(2027, 1, 1))])
        self.assertAlmostEqual(semestre.fixed_percentage, 20.0, places=2)

    def test_la_prima_en_procedimiento_2_usa_el_porcentaje_del_contrato(self):
        contrato = self._contrato(salario=20000000.0)
        self._procedimiento_2(contrato)
        prima = self._recibo(contrato, date(2026, 7, 1), date(2026, 12, 31), estructura=self.env.ref(PREFIJO + 'hr_payroll_structure_co_prima'))
        valor = self._total(prima, 'CO_PRIMA_VALOR')
        extra = {'fecha_mes': date(2026, 12, 31), 'sin_aportes_voluntarios': True}
        esperado = self._oraculo(prima, valor, 0.0, **extra)
        self.assertGreater(esperado, 0.0)
        self.assertNotAlmostEqual(esperado, self._oraculo(prima, valor, 0.0, force_procedure='1', **extra), delta=1.0)
        self.assertAlmostEqual(-self._total(prima, 'CO_PRIMA_RETE'), esperado, delta=1.0)

    # ── reembolsos ───────────────────────────────────────────────────
    def test_un_reembolso_confirmado_deja_en_cero_la_base_y_la_retencion_del_recibo(self):
        contrato = self._contrato(periodicidad='monthly')
        original = self._hecho(self._recibo(contrato, date(2026, 9, 1), date(2026, 9, 30)))
        original.refund_sheet()
        reembolso = self._reembolso_de(original)
        self.assertEqual((len(reembolso), reembolso.state), (1, 'draft'))
        self.assertAlmostEqual(self._total(reembolso, 'CO_RETEFUENTE'), RETENCION_12M, delta=1.0)
        nuevo = self._recibo(contrato, date(2026, 9, 1), date(2026, 9, 30), calculado=False)
        with self.assertRaisesRegex(UserError, re.escape(reembolso._ne_referencia())):
            nuevo.compute_sheet()
        self._hecho(reembolso)
        for indice, cifras in enumerate(zip(nuevo._ne_rete_cifras_de(original), nuevo._ne_rete_cifras_de(reembolso))):
            with self.subTest(cifra=indice):
                self.assertAlmostEqual(sum(cifras), 0.0, delta=0.01)
        nuevo.compute_sheet()
        self.assertAlmostEqual(-self._total(nuevo, 'CO_RETEFUENTE'), RETENCION_12M, delta=1.0)

    # ── un devengado calculado después de la retención ───────────────
    def test_un_concepto_calculado_despues_de_la_retencion_detiene_el_calculo(self):
        self.env['hr.salary.rule'].create({
            'name': 'Bono Tardío de la Empresa', 'code': 'X_BONO_TARDIO', 'struct_id': self.general.id, 'sequence': 115,
            'category_id': self.env.ref(PREFIJO + 'hr_salary_rule_category_devengados_no_salariales').id,
            'condition_select': 'none', 'amount_select': 'fix', 'amount_fix': 1.0, 'quantity': '1.0', 'l10n_co_pila_origen_no_salarial': 'naturaleza'})
        recibo = self._primera(self._contrato(), calculado=False)
        with self.assertRaisesRegex(UserError, 'X_BONO_TARDIO'):
            recibo.compute_sheet()

    # ── bonificaciones (D1) ──────────────────────────────────────────
    def _bono(self, contrato, dia=20, monto=2000000.0, **extra):
        return self._recibo(contrato, date(2026, 9, dia), date(2026, 9, dia), estructura=self.bonificacion, novedades=[('CO_BON_VALOR', monto)],
                            l10n_co_ne_is_salarial=True, **extra)

    def test_bonificacion_antes_del_cierre_no_retiene_y_el_cierre_la_incluye(self):
        contrato = self._contrato()
        self._hecho(self._primera(contrato))
        bono = self._bono(contrato)
        self.assertFalse(bono.line_ids.filtered(lambda l: l.code == 'CO_BON_RETE'))
        segunda = self._segunda(contrato, calculado=False)
        with self.assertRaisesRegex(UserError, re.escape(bono._ne_referencia())):
            segunda.compute_sheet()
        self._hecho(bono)
        segunda.compute_sheet()
        self.assertAlmostEqual(-self._total(segunda, 'CO_RETEFUENTE'), self._oraculo(segunda, 14000000.0, 14000000.0), delta=1.0)

    def test_bonificacion_despues_del_cierre_retiene_el_saldo_en_5_y_20(self):
        contrato = self._contrato()
        primera = self._hecho(self._recibo(contrato, date(2026, 8, 21), date(2026, 9, 5)))
        cierre = self._hecho(self._recibo(contrato, date(2026, 9, 6), date(2026, 9, 20)))
        retenido = -self._total(cierre, 'CO_RETEFUENTE')
        self.assertGreater(retenido, 0.0)
        base, ibc = (self._total(primera, c) + self._total(cierre, c) for c in ('CO_RETEFUENTE_BASE_GROSS', 'CO_RETEFUENTE_BASE_IBC'))
        bono = self._bono(contrato, dia=28)
        self.assertAlmostEqual(-self._total(bono, 'CO_BON_RETE'), self._oraculo(bono, base + 2000000.0, ibc + 2000000.0, fecha_mes=date(2026, 9, 28)) - retenido, delta=1.0)

    def test_no_se_confirman_juntos_dos_recibos_del_mes_si_la_retencion_no_tuvo_en_cuenta_a_uno(self):
        contrato = self._contrato()
        self._hecho(self._primera(contrato))
        cierre = self._segunda(contrato)
        bono = self._bono(contrato)
        with self.assertRaisesRegex(UserError, 'uno por uno'):
            self._confirmar(cierre | bono)

    # ── un cierre confirmado no deja anular lo que sumó ──────────────
    def test_el_cierre_guarda_los_recibos_que_sumo_y_nadie_los_escribe_por_fuera(self):
        primera, segunda = self._mes_cerrado()
        self.assertEqual(segunda.l10n_co_ne_rete_sumados_ids, primera)
        self.assertFalse(primera.l10n_co_ne_rete_sumados_ids)
        with self.assertRaises(UserError):
            segunda.write({'l10n_co_ne_rete_sumados_ids': [Command.clear()]})

    def test_no_se_anula_un_recibo_que_el_cierre_confirmado_sumo(self):
        primera, segunda = self._mes_cerrado()
        self._no_se_anula(primera, segunda)

    def test_el_cierre_pagado_tambien_bloquea(self):
        primera, segunda = self._mes_cerrado()
        segunda.write({'state': 'paid'})
        self._no_se_anula(primera, segunda)

    def test_volver_a_borrador_el_lote_tampoco_anula_lo_sumado(self):
        primera, segunda = self._mes_cerrado()
        lote = self.env['hr.payslip.run'].create({
            'name': 'Lote Retención', 'date_start': date(2026, 9, 1), 'date_end': date(2026, 9, 15), 'company_id': self.company.id})
        primera.write({'payslip_run_id': lote.id})
        with self.assertRaisesRegex(UserError, re.escape(segunda._ne_referencia())):
            lote.action_draft()
        self.assertEqual(primera.state, 'validated')

    def test_el_asistente_de_ajuste_no_revierte_ni_corrige_lo_sumado(self):
        contrato = self._contrato()
        primera = self._hecho(self._primera(contrato))
        segunda = self._hecho(self._segunda(contrato))
        asistente = self.env['hr.payslip.correction.wizard'].create({'employee_id': contrato.employee_id.id, 'payslip_id': primera.id})
        for accion in ('action_revert_payslips', 'action_correct_payslips'):
            with self.subTest(accion=accion), self.assertRaisesRegex(UserError, re.escape(segunda._ne_referencia())):
                getattr(asistente, accion)()
        self.assertFalse(self._reembolso_de(primera))

    def test_corregir_el_recibo_que_cierra_dice_que_se_cancele_el_original(self):
        """El asistente calcula el recibo corregido con el reembolso en borrador: el mensaje dice qué hacer. La estructura del corregido sale del tipo de estructura colombiano."""
        contrato = self._contrato(periodicidad='monthly', tipo=self.env.ref(PREFIJO + 'hr_payroll_structure_type_co'))
        original = self._hecho(self._recibo(contrato, date(2026, 9, 1), date(2026, 9, 30)))
        asistente = self.env['hr.payslip.correction.wizard'].create({'employee_id': contrato.employee_id.id, 'payslip_id': original.id})
        with self.assertRaisesRegex(UserError, 'Cancele primero el recibo original') as error:
            asistente.action_correct_payslips()
        self.assertIn(original._ne_referencia(), str(error.exception))

    def test_el_cierre_en_borrador_no_bloquea(self):
        contrato = self._contrato()
        primera = self._hecho(self._primera(contrato))
        self._segunda(contrato)
        primera.action_payslip_cancel()
        self.assertEqual(primera.state, 'cancel')

    def test_la_bonificacion_que_el_cierre_sumo_no_se_anula_y_la_posterior_si(self):
        contrato = self._contrato()
        self._hecho(self._primera(contrato))
        antes = self._hecho(self._bono(contrato))
        segunda = self._hecho(self._segunda(contrato))
        despues = self._hecho(self._bono(contrato, dia=25))
        self._no_se_anula(antes, segunda)
        despues.action_payslip_cancel()
        self.assertEqual(despues.state, 'cancel')

    def test_el_propio_cierre_se_cancela_y_despues_lo_que_sumo(self):
        primera, segunda = self._mes_cerrado()
        segunda.action_payslip_cancel()
        primera.action_payslip_cancel()
        self.assertEqual((primera | segunda).mapped('state'), ['cancel', 'cancel'])

    def test_con_el_cierre_reembolsado_se_permite(self):
        primera, segunda = self._mes_cerrado()
        segunda.refund_sheet()
        self._no_se_anula(primera, segunda)          # el reembolso del cierre sin confirmar todavía no lo anula
        self._hecho(self._reembolso_de(segunda))
        primera.refund_sheet()
        self.assertTrue(self._reembolso_de(primera))
        primera.action_payslip_cancel()
        self.assertEqual(primera.state, 'cancel')

    def test_la_misma_operacion_que_incluye_el_cierre_no_se_bloquea(self):
        primera, segunda = self._mes_cerrado()
        (primera | segunda).refund_sheet()
        self.assertTrue(self._reembolso_de(primera) and self._reembolso_de(segunda))
        primera, segunda = self._mes_cerrado()
        (primera | segunda).action_payslip_cancel()
        self.assertEqual((primera | segunda).mapped('state'), ['cancel', 'cancel'])

    def test_un_reembolso_creado_antes_del_cierre_no_se_confirma_sin_el_del_cierre(self):
        contrato = self._contrato()
        primera = self._hecho(self._primera(contrato))
        segunda = self._segunda(contrato)
        primera.refund_sheet()                       # el cierre aún no está confirmado
        self._hecho(segunda)
        reembolso = self._reembolso_de(primera)
        with self.assertRaisesRegex(UserError, re.escape(segunda._ne_referencia())):
            self._confirmar(reembolso)
        segunda.refund_sheet()
        self.assertTrue(self._confirmar(reembolso | self._reembolso_de(segunda)).called)

    def test_en_procedimiento_2_no_se_bloquea(self):
        contrato = self._contrato()
        self._procedimiento_2(contrato)
        primera = self._hecho(self._primera(contrato))
        segunda = self._hecho(self._segunda(contrato))
        self.assertFalse(segunda.l10n_co_ne_rete_sumados_ids)
        primera.action_payslip_cancel()
        self.assertEqual(primera.state, 'cancel')

    def test_en_una_compania_no_colombiana_no_se_bloquea(self):
        primera, _segunda = self._mes_cerrado()
        with patch.object(type(self.company), '_ne_es_colombia', lambda compania: False):
            primera.action_payslip_cancel()
        self.assertEqual(primera.state, 'cancel')

    # ── huella (C-24) ────────────────────────────────────────────────
    def test_cancelar_un_recibo_anterior_deja_el_cierre_desactualizado(self):
        contrato = self._contrato()
        primera = self._hecho(self._primera(contrato))
        segunda = self._segunda(contrato)
        self.assertEqual(segunda.l10n_co_ne_huella_calculo, segunda._ne_huella_calculo())
        primera.write({'state': 'paid'})
        self.assertEqual(segunda.l10n_co_ne_huella_calculo, segunda._ne_huella_calculo(), 'Pagar el anterior no cambia sus cifras')
        primera.write({'state': 'cancel'})
        self.assertNotEqual(segunda.l10n_co_ne_huella_calculo, segunda._ne_huella_calculo())

    # ── parámetro de la base ─────────────────────────────────────────
    def _nuevo_valor(self, valor, desde=date(2026, 9, 1)):
        parametro = self.env.ref(PREFIJO + 'rule_parameter_retefuente_base_mes')
        return self.env['hr.rule.parameter.value'].create({'rule_parameter_id': parametro.id, 'date_from': desde, 'parameter_value': repr(valor)})

    def test_el_parametro_trae_la_base_aprobada(self):
        self.assertEqual(self._primera(self._contrato(), calculado=False)._ne_rete_parametro(), BASE_APROBADA)

    def test_parametro_con_otra_forma_es_un_error_que_lo_nombra(self):
        contrato = self._contrato(periodicidad='monthly')
        sin_clave = {k: v for k, v in BASE_APROBADA.items() if k != 'reglas_excluidas'}
        for dia, malo in enumerate((sin_clave, dict(BASE_APROBADA, otra=[]), dict(BASE_APROBADA, categorias=[]), dict(BASE_APROBADA, reglas_excluidas='CO_AUX_TRANS'), ['DEV_SAL']), 1):
            self._nuevo_valor(malo, desde=date(2026, 8, dia))
            recibo = self._recibo(contrato, date(2026, 8, dia), date(2026, 8, 31), calculado=False)
            with self.subTest(valor=malo), self.assertRaisesRegex(UserError, PARAMETRO):
                recibo._ne_rete_parametro()

    def test_regla_incluida_y_regla_excluida(self):
        recibo = self._recibo(self._contrato(periodicidad='monthly'), date(2026, 9, 1), date(2026, 9, 30),
                              novedades=[('CO_BONIF_NOSAL', 1000000.0), ('CO_AUX_ALIM', 500000.0)])
        self.assertAlmostEqual(self._total(recibo, 'CO_RETEFUENTE_BASE_GROSS'), 13000000.0, delta=1.0)
        self.assertAlmostEqual(-self._total(recibo, 'CO_RETEFUENTE'), self._oraculo(recibo, 13000000.0, 12000000.0), delta=1.0)

    def test_un_concepto_no_salarial_de_la_empresa_entra_y_un_valor_nuevo_lo_excluye(self):
        self.env['hr.salary.rule'].create({
            'name': 'Bono Propio de la Empresa', 'code': 'X_BONO_PROPIO', 'struct_id': self.general.id, 'sequence': 45,
            'category_id': self.env.ref(PREFIJO + 'hr_salary_rule_category_devengados_no_salariales').id,
            'condition_select': 'none', 'amount_select': 'fix', 'amount_fix': 700000.0, 'quantity': '1.0', 'l10n_co_pila_origen_no_salarial': 'naturaleza'})
        contrato = self._contrato(periodicidad='monthly')
        recibo = self._recibo(contrato, date(2026, 9, 1), date(2026, 9, 30))
        self.assertAlmostEqual(self._total(recibo, 'CO_RETEFUENTE_BASE_GROSS'), 12700000.0, delta=1.0)
        self._nuevo_valor(dict(BASE_APROBADA, reglas_excluidas=BASE_APROBADA['reglas_excluidas'] + ['X_BONO_PROPIO']))
        recibo.compute_sheet()
        self.assertAlmostEqual(self._total(recibo, 'CO_RETEFUENTE_BASE_GROSS'), 12000000.0, delta=1.0)

    def test_el_apoyo_del_aprendiz_cuenta_una_sola_vez(self):
        contrato = self._contrato(salario=1750905.0, periodicidad='monthly', l10n_co_pila_tipo_cotizante='19')
        recibo = self._recibo(contrato, date(2026, 9, 1), date(2026, 9, 30))
        self.assertAlmostEqual(self._total(recibo, 'CO_RETEFUENTE_BASE_GROSS'), 1750905.0, delta=1.0)

    # ── liquidación ──────────────────────────────────────────────────
    def test_en_la_liquidacion_salen_la_prima_y_se_mantienen_cesantias_intereses_apoyo_e_indemnizacion(self):
        recibo = self._recibo(self._contrato(), INGRESO, date(2026, 9, 15), estructura=self.liquidacion, calculado=False)
        codigos = recibo._ne_rete_codigos_base(self.liquidacion.rule_ids)
        self.assertTrue({'CO_LIQ_SALARIOS', 'CO_LIQ_CESANTIAS', 'CO_LIQ_INT_CES', 'CO_APOYO_SOST', 'CO_LIQ_INDEMNIZACION', 'CO_LIQ_VACACIONES'} <= codigos)
        self.assertNotIn('CO_LIQ_PRIMA', codigos)
        self.assertNotIn('CO_AUX_TRANS', codigos)

    def test_liquidacion_retiene_el_mes_sin_sumar_dos_veces_los_dias_pagados_y_sin_la_prima(self):
        contrato = self._contrato(salario=20000000.0, fin=date(2026, 9, 30))
        primera = self._hecho(self._primera(contrato))
        liquidacion = self._recibo(contrato, INGRESO, date(2026, 9, 30), estructura=self.liquidacion)
        self.assertAlmostEqual(self._total(liquidacion, 'CO_LIQ_SALARIOS'), 10000000.0, delta=1.0, msg='P0: solo los 15 días que faltan')
        propia = sum(self._total(liquidacion, c) for c in liquidacion._ne_rete_codigos_base(self.liquidacion.rule_ids))
        salarial = sum(liquidacion.line_ids.filtered(lambda l: l.category_id.code in ('DEV_SAL', 'HEX')).mapped('total'))
        reales = self._aportes(primera)
        reales['aporte_salud'] -= self._total(liquidacion, 'CO_LIQ_SALUD')
        reales['aporte_pension'] -= self._total(liquidacion, 'CO_LIQ_PENSION')
        esperado = self._oraculo(liquidacion, propia + self._total(primera, 'CO_RETEFUENTE_BASE_GROSS'),
                                 salarial + self._total(primera, 'CO_RETEFUENTE_BASE_IBC'), fecha_mes=date(2026, 9, 30), **reales)
        self.assertGreater(esperado, 0.0)
        self.assertAlmostEqual(liquidacion.l10n_co_ne_rete_a_descontar, esperado, delta=1.0)
        self.assertGreater(self._total(liquidacion, 'CO_LIQ_PRIMA'), 0.0, 'Premisa: la liquidación trae prima')
        self.assertEqual(liquidacion.l10n_co_ne_rete_sumados_ids, primera)
        self._hecho(liquidacion)
        self._no_se_anula(primera, liquidacion)

    # ── la retención no cabe en el recibo de cierre ──────────────────
    def _no_cabe(self):
        contrato = self._contrato()
        self._hecho(self._primera(contrato, novedades=[('CO_COMISIONES', 30000000.0)]))
        return self._segunda(contrato)

    def test_se_retiene_lo_disponible_y_el_neto_queda_en_cero(self):
        recibo = self._no_cabe()
        disponible = self._total(recibo, 'CO_BASICO') + self._total(recibo, 'CO_SALUD_EMP') + self._total(recibo, 'CO_PENSION_EMP') + self._total(recibo, 'CO_FSP')
        self.assertAlmostEqual(recibo.l10n_co_ne_rete_disponible, disponible, delta=0.01)
        self.assertAlmostEqual(-self._total(recibo, 'CO_RETEFUENTE'), disponible, delta=0.01)
        self.assertAlmostEqual(recibo.l10n_co_ne_rete_faltante, recibo.l10n_co_ne_rete_a_descontar - disponible, delta=0.01)
        self.assertGreater(recibo.l10n_co_ne_rete_faltante, 0.0)
        self.assertAlmostEqual(self._total(recibo, 'CO_NETO'), 0.0, delta=0.01)

    def test_confirmar_sin_autorizacion_es_un_error_con_las_tres_cifras(self):
        recibo = self._no_cabe()
        with self.assertRaisesRegex(UserError, 'Autorizo confirmar con retención incompleta') as error:
            self._confirmar(recibo)
        self.assertIn(recibo.employee_id.name, str(error.exception))
        self.assertEqual(recibo.state, 'draft')

    def test_solo_el_administrador_de_nomina_autoriza(self):
        recibo = self._no_cabe()
        oficial = crear_usuario_nomina(self.env, self.company, 'oficial_retencion_%s' % self.n)
        with self.assertRaises(UserError):
            recibo.with_user(oficial).write({'l10n_co_ne_rete_autorizada': True})
        for campo, valor in (('l10n_co_ne_rete_autorizada', True), ('l10n_co_ne_rete_faltante', 1.0), ('l10n_co_ne_rete_autorizada_por', self.env.uid)):
            with self.subTest(campo=campo), self.assertRaises(UserError):
                self._primera(self._contrato(), calculado=False, **{campo: valor})
        with self.assertRaises(UserError):
            self.env['hr.payslip'].with_context(default_l10n_co_ne_rete_autorizada=True).create({
                'name': 'Con default', 'employee_id': recibo.employee_id.id, 'version_id': recibo.version_id.id, 'company_id': self.company.id,
                'struct_id': self.general.id, 'date_from': date(2026, 10, 1), 'date_to': date(2026, 10, 15)})
        administrador = crear_usuario_nomina(self.env, self.company, 'administrador_retencion_%s' % self.n, administrador=True)
        for campo in ('l10n_co_ne_rete_faltante', 'l10n_co_ne_rete_a_descontar', 'l10n_co_ne_rete_autorizada_fecha', 'l10n_co_ne_rete_autorizada_disponible'):
            with self.subTest(campo=campo), self.assertRaises(UserError):
                recibo.with_user(administrador).write({campo: False})
        recibo.with_user(administrador).write({'l10n_co_ne_rete_autorizada': True})
        self.assertEqual(recibo.l10n_co_ne_rete_autorizada_por, administrador)
        self.assertTrue(recibo.l10n_co_ne_rete_autorizada_fecha)
        self.assertTrue(self._confirmar(recibo).called)

    def test_no_se_autoriza_un_recibo_al_que_no_le_falta_nada(self):
        recibo = self._primera(self._contrato())
        with self.assertRaises(UserError):
            recibo.with_user(crear_usuario_nomina(self.env, self.company, 'administrador_sin_faltante_%s' % self.n, administrador=True)).write(
                {'l10n_co_ne_rete_autorizada': True})

    def test_la_autorizacion_se_conserva_con_las_mismas_cifras_y_se_borra_si_cambian(self):
        recibo = self._no_cabe()
        administrador = crear_usuario_nomina(self.env, self.company, 'administrador_conserva_%s' % self.n, administrador=True)
        recibo.with_user(administrador).write({'l10n_co_ne_rete_autorizada': True})
        recibo.compute_sheet()
        self.assertTrue(recibo.l10n_co_ne_rete_autorizada)
        self.assertFalse(recibo.copy().l10n_co_ne_rete_autorizada)
        self.env['hr.payslip.input'].create({
            'payslip_id': recibo.id, 'input_type_id': self.env.ref(PREFIJO + 'input_co_comisiones').id, 'amount': 100000.0})
        self.assertFalse(recibo.l10n_co_ne_rete_autorizada)
        self.assertFalse(recibo.l10n_co_ne_rete_autorizada_por)

    # ── neto negativo ────────────────────────────────────────────────
    def test_neto_negativo_no_se_confirma_y_nombra_las_deducciones(self):
        recibo = self._primera(self._contrato(l10n_co_ne_sindicato_partner_id=self.entidad.id), novedades=[('CO_SINDICATO', 9000000.0)])
        regla = self.general.rule_ids.filtered(lambda r: r.code == 'CO_SINDICATO')
        with self.assertRaisesRegex(UserError, 'neto negativo') as error:
            self._confirmar(recibo)
        self.assertIn(regla.name, str(error.exception))
        recibo.input_line_ids.write({'amount': 1000.0})
        recibo.compute_sheet()
        self.assertTrue(self._confirmar(recibo).called)

    def test_el_neto_negativo_no_se_revisa_en_reembolsos_ni_en_recibos_confirmados(self):
        recibo = self._primera(self._contrato(l10n_co_ne_sindicato_partner_id=self.entidad.id), novedades=[('CO_SINDICATO', 9000000.0)])
        with self.assertRaises(UserError):
            recibo._ne_validar_neto_no_negativo()
        recibo.write({'credit_note': True})
        recibo._ne_validar_neto_no_negativo()
        recibo.write({'credit_note': False})
        confirmar_a_mano(recibo)
        recibo._ne_validar_neto_no_negativo()


@tagged('post_install', '-at_install')
class TestRetefuenteMesPartido(MontajeRetencionMes):
    """H-F1-10 con R-2 (decisión del TL del 26-nov, opción A)."""

    def _partido(self, periodicidad='monthly', cambio=date(2026, 9, 16), fin=None):
        """Contrato de 12.000.000 con aumento a 14.000.000 desde ``cambio``, con el tipo de estructura colombiano (el lote lo exige). Devuelve ``(version_a, version_b)``."""
        version_a = self._contrato(periodicidad=periodicidad, tipo=self.env.ref(PREFIJO + 'hr_payroll_structure_type_co'))
        version_b = crear_aumento(self.env, version_a.employee_id, version_a, cambio, 14000000.0)
        version_b.write({'schedule_pay': periodicidad})
        if fin:          # el fin es del contrato: de sus dos versiones
            (version_a | version_b).write({'contract_date_end': fin})
        return version_a, version_b

    def _lote(self, empleado, desde=date(2026, 9, 1), hasta=date(2026, 9, 30), periodicidad=None):
        """El lote nativo solo toma las versiones de SU calendario de pago (``hr_payroll/models/hr_payslip_run.py:141-142``); sin indicarlo es el del tipo de estructura (mensual)."""
        lote = self.env['hr.payslip.run'].create(dict(
            {'name': 'Lote Retención Partido', 'date_start': desde, 'date_end': hasta, 'company_id': self.company.id, 'structure_id': self.general.id},
            **({'schedule_pay': periodicidad} if periodicidad else {})))
        lote.generate_payslips(employee_ids=empleado.ids)
        return lote.slip_ids.sorted('date_from')

    def _mes(self, recibo, *recibos):
        """La retención esperada de ``recibo`` sobre la suma de ``recibos`` (incluido él), con los aportes descontados de verdad."""
        base, ibc = (sum(self._total(r, c) for r in recibos) for c in ('CO_RETEFUENTE_BASE_GROSS', 'CO_RETEFUENTE_BASE_IBC'))
        return self._oraculo(recibo, base, ibc, fecha_mes=recibo.date_to, **self._aportes(*recibos))

    def test_no_cierra_el_recibo_con_otra_version_posterior_en_el_mes(self):
        va, vb = self._partido()
        self.assertFalse(self._recibo(va, date(2026, 9, 1), date(2026, 9, 15), calculado=False)._ne_rete_es_cierre())
        self.assertTrue(self._recibo(vb, date(2026, 9, 16), date(2026, 9, 30), calculado=False)._ne_rete_es_cierre())
        va, _vb = self._partido(periodicidad='semi-monthly', cambio=date(2026, 9, 20))
        self.assertFalse(self._recibo(va, date(2026, 9, 16), date(2026, 9, 19), calculado=False)._ne_rete_es_cierre(), 'Quincenal con cambio el 20: el tramo 16-19 no cierra')

    def test_un_cambio_el_dia_31_no_quita_el_cierre(self):
        va, _vb = self._partido(cambio=date(2026, 10, 31))
        self.assertTrue(self._recibo(va, date(2026, 10, 1), date(2026, 10, 30), calculado=False)._ne_rete_es_cierre())

    def test_el_fin_de_una_version_no_es_un_retiro(self):
        """``date_end`` de la versión A cae dentro del periodo (cambio el 11); el contrato no termina: el tramo no cierra una quincena."""
        va, _vb = self._partido(periodicidad='semi-monthly', cambio=date(2026, 9, 11))
        self.assertFalse(self._recibo(va, date(2026, 9, 1), date(2026, 9, 15), calculado=False)._ne_rete_es_cierre())

    def test_el_lote_mensual_genera_los_dos_tramos_y_el_segundo_retiene_el_mes(self):
        va, vb = self._partido()
        recibos = self._lote(va.employee_id)
        a, b = recibos
        self.assertEqual((a.version_id, b.version_id), (va, vb))
        self.assertFalse(a.line_ids.filtered(lambda l: l.code == 'CO_RETEFUENTE'))
        self.assertGreater(-self._total(b, 'CO_RETEFUENTE'), 0.0)
        self.assertAlmostEqual(-self._total(b, 'CO_RETEFUENTE'), self._mes(b, a, b), delta=1.0)
        self.assertEqual(b.l10n_co_ne_rete_sumados_ids, a)
        self.assertTrue(self._confirmar(recibos).called, 'El lote se valida en un paso')

    def test_el_cierre_que_sumo_un_borrador_no_se_confirma_solo(self):
        va, _vb = self._partido()
        a, b = self._lote(va.employee_id)
        with self.assertRaisesRegex(UserError, 'Confírmelos juntos') as error:
            self._confirmar(b)
        self.assertIn(a._ne_referencia(), str(error.exception))
        confirmar_a_mano(a)
        self.assertTrue(self._confirmar(b).called, 'Con el primero confirmado, el cierre se confirma solo y su hoja sigue al día')

    def test_calcular_solo_el_cierre_con_el_primero_en_borrador_es_un_error_y_juntos_no(self):
        va, _vb = self._partido()
        a, b = self._lote(va.employee_id)
        with self.assertRaisesRegex(UserError, 'calcular juntos'):
            b.compute_sheet()
        (a | b).compute_sheet()
        self.assertEqual(b.l10n_co_ne_rete_sumados_ids, a)

    def test_recalcular_el_primero_deja_el_cierre_desactualizado(self):
        va, _vb = self._partido()
        a, b = self._lote(va.employee_id)
        self.env['hr.payslip.input'].create({
            'payslip_id': a.id, 'input_type_id': self.env.ref(PREFIJO + 'input_co_comisiones').id, 'amount': 1000000.0})
        self.assertNotEqual(b.l10n_co_ne_huella_calculo, b._ne_huella_calculo())
        with self.assertRaisesRegex(UserError, 'no está al día'):
            self._confirmar(a | b)

    def test_quincenal_con_cambio_el_20_el_cierre_suma_la_primera_confirmada_y_el_tramo_del_lote(self):
        va, vb = self._partido(periodicidad='semi-monthly', cambio=date(2026, 9, 20))
        primera = self._hecho(self._primera(va))
        a, b = self._lote(va.employee_id, date(2026, 9, 16), date(2026, 9, 30), periodicidad='semi-monthly')
        self.assertEqual((a.date_to, b.date_from, b.version_id), (date(2026, 9, 19), date(2026, 9, 20), vb))
        self.assertFalse(a.line_ids.filtered(lambda l: l.code == 'CO_RETEFUENTE'))
        self.assertAlmostEqual(-self._total(b, 'CO_RETEFUENTE'), self._mes(b, primera, a, b), delta=1.0)
        self.assertEqual(b.l10n_co_ne_rete_sumados_ids, primera | a)
        self.assertTrue(self._confirmar(a | b).called)

    def test_el_lote_con_cambio_el_dia_31_genera_un_recibo_que_cierra_y_se_confirma(self):
        va, _vb = self._partido(cambio=date(2026, 10, 31))
        recibos = self._lote(va.employee_id, date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual([(r.version_id, r.date_to) for r in recibos], [(va, date(2026, 10, 30))])
        self.assertAlmostEqual(-self._total(recibos, 'CO_RETEFUENTE'), RETENCION_12M, delta=1.0)
        self.assertTrue(self._confirmar(recibos).called)

    def test_retiro_en_un_mes_partido_cierra_el_ultimo_tramo(self):
        va, vb = self._partido(fin=date(2026, 9, 25))
        recibos = self._lote(va.employee_id)
        a, b = recibos
        self.assertEqual((a.version_id, b.version_id), (va, vb))
        self.assertFalse(a._ne_rete_es_cierre())
        self.assertTrue(b._ne_rete_es_cierre())
        self.assertAlmostEqual(-self._total(b, 'CO_RETEFUENTE'), self._mes(b, a, b), delta=1.0)
        self.assertTrue(self._confirmar(recibos).called)
