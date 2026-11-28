# -*- coding: utf-8 -*-
"""Etapa 3 (doc 53 §5.3, §19): datos del documento mensual por fusion de los recibos, Periodo (D3), TiempoLaborado
360/30 inclusivo (D19, Anexo §8.3.1) y alertas del XML (D4). Valores a mano; los datos por recibo se simulan con
la forma de _collect_payslip_data."""

from datetime import date
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.l10n_co_nomina_electronica.services import documento_merge, dian_utils, nomina_xml_builder

from .common_documento import DocumentoFixture
from .common_version import confirmar_a_mano
from .test_documento_merge import _recibo as _datos_recibo


@tagged('post_install', '-at_install')
class TestDocumentoXml(DocumentoFixture, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._fixture_documento('Compañía XML Documento')

    def _datos(self, doc, **patches):
        fabrica = patches.get('recibo', _datos_recibo)
        with patch.object(type(self.env['hr.payslip']), '_collect_payslip_data', lambda s: fabrica()), \
                patch.object(dian_utils, 'compute_software_security_code', lambda *a: 'SC'):
            return doc._collect_documento_data(consecutivo='NE15')

    # ── Periodo (D3) y TiempoLaborado (D19) ──────────────────────────
    def test_periodo_contrato_antiguo_mes_completo(self):
        datos = self._datos(self._documento(date(2024, 3, 1)))
        periodo = datos['periodo']
        self.assertEqual(
            (periodo['FechaIngreso'], periodo['FechaRetiro'], periodo['FechaLiquidacionInicio'],
             periodo['FechaLiquidacionFin'], periodo['TiempoLaborado']),
            ('2024-03-01', '', '2026-03-01', '2026-03-31', '750'))

    def test_periodo_ingreso_el_10_recorta_el_inicio(self):
        datos = self._datos(self._documento(date(2026, 3, 10)))
        self.assertEqual(datos['periodo']['FechaLiquidacionInicio'], '2026-03-10')
        self.assertEqual(datos['periodo']['FechaLiquidacionFin'], '2026-03-31')
        self.assertEqual(datos['periodo']['TiempoLaborado'], '21')   # dias comerciales 10..30

    def test_periodo_contrato_que_termina_en_el_mes_cierra_ahi_y_sin_liquidacion_no_lleva_retiro(self):
        datos = self._datos(self._documento(date(2025, 1, 1), retiro=date(2026, 3, 20)))
        self.assertEqual(datos['periodo']['FechaRetiro'], '')          # la fecha final del contrato no es un retiro (.339)
        self.assertEqual(datos['periodo']['FechaLiquidacionFin'], '2026-03-20')
        # 01-ene-2025 a 20-mar-2026 inclusivo: 1 anio (360) + 2 meses (60) + 20 dias = 440
        self.assertEqual(datos['periodo']['TiempoLaborado'], '440')

    def test_periodo_retiro_en_otro_mes_no_recorta(self):
        datos = self._datos(self._documento(date(2025, 1, 1), retiro=date(2026, 6, 30)))
        self.assertEqual(datos['periodo']['FechaLiquidacionFin'], '2026-03-31')
        self.assertEqual(datos['periodo']['FechaRetiro'], '')          # término fijo vigente: el mes normal no lleva retiro

    # ── FechaRetiro (.339, NIE003): solo de las liquidaciones que van en el documento ──
    def _liquidacion(self, doc, retiro, pago=None, **vals):
        """Recibo de liquidación de contrato (del inicio del contrato a ``retiro``) pagado y enlazado al documento."""
        slip = self.env['hr.payslip'].create({
            'name': 'Liquidación Doc', 'employee_id': doc.employee_id.id, 'version_id': doc.version_id.id, 'company_id': self.company.id,
            'struct_id': self.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_liquidacion').id,
            'date_from': doc.version_id.contract_date_start, 'date_to': retiro})
        confirmar_a_mano(slip, 'paid', **dict({'paid_date': pago or doc.period.replace(day=28), 'l10n_co_ne_documento_id': doc.id}, **vals))
        return slip

    def test_la_liquidacion_del_documento_da_la_fecha_de_retiro(self):
        for fin_de_contrato in (None, date(2026, 3, 20), date(2026, 12, 31)):
            with self.subTest(fin_de_contrato=fin_de_contrato):
                doc = self._documento(date(2025, 1, 1), retiro=fin_de_contrato, pagos=())
                self._liquidacion(doc, date(2026, 3, 20))
                self.assertEqual(self._datos(doc)['periodo']['FechaRetiro'], '2026-03-20')

    def test_con_varias_liquidaciones_va_la_ultima_fecha(self):
        doc = self._documento(date(2025, 1, 1), pagos=())
        self._liquidacion(doc, date(2026, 3, 20))
        self._liquidacion(doc, date(2026, 3, 10))
        self.assertEqual(self._datos(doc)['periodo']['FechaRetiro'], '2026-03-20')

    def test_una_liquidacion_reembolsada_no_es_un_retiro(self):
        doc = self._documento(date(2025, 1, 1))
        liquidacion = self._liquidacion(doc, date(2026, 3, 20))
        self.assertEqual(doc.payslip_ids._ne_fecha_retiro(), '2026-03-20')
        # v19: el reembolso nativo queda ligado a su original por ``origin_payslip_id`` y de ahí lo lee ``_ne_liq_reembolsado``.
        self._liquidacion(doc, date(2026, 3, 20), credit_note=True, l10n_co_ne_documento_id=False, origin_payslip_id=liquidacion.id)
        self.assertTrue(liquidacion._ne_liq_reembolsado())
        self.assertEqual(doc.payslip_ids._ne_fecha_retiro(), '')

    def test_periodo_de_un_mes_posterior_al_retiro_no_queda_con_el_inicio_despues_del_fin(self):
        for ingreso, inicio in ((date(2025, 1, 1), '2026-02-01'), (date(2026, 2, 10), '2026-02-10')):
            with self.subTest(ingreso=ingreso):
                doc = self._documento(ingreso, retiro=date(2026, 2, 20), mes=3, pagos=())
                self._liquidacion(doc, date(2026, 2, 20), pago=date(2026, 3, 5))
                periodo = self._datos(doc)['periodo']
                self.assertEqual((periodo['FechaLiquidacionInicio'], periodo['FechaLiquidacionFin'], periodo['FechaRetiro']),
                                 (inicio, '2026-02-20', '2026-02-20'))

    def test_periodo_de_un_segmento_con_dias_del_mes_anterior_no_queda_invertido(self):
        doc = self._documento(date(2025, 1, 1), pagos=())
        slip = self.env['hr.payslip'].create({
            'name': 'Recibo atrasado', 'employee_id': doc.employee_id.id, 'version_id': doc.version_id.id, 'company_id': self.company.id,
            'struct_id': self.struct.id, 'date_from': date(2026, 2, 16), 'date_to': date(2026, 2, 28)})
        confirmar_a_mano(slip, 'paid', paid_date=date(2026, 3, 5), l10n_co_ne_documento_id=doc.id)
        with patch.object(type(doc), '_ne_segmentar', lambda *a: [slip, slip]):
            periodo = doc._ne_periodo(doc.version_id)
        self.assertEqual((periodo['FechaLiquidacionInicio'], periodo['FechaLiquidacionFin']), ('2026-02-16', '2026-02-28'))

    # ── Fusion ───────────────────────────────────────────────────────
    def test_fusion_dos_quincenas(self):
        datos = self._datos(self._documento(date(2024, 3, 1)))
        self.assertEqual(datos['informacion_general']['PeriodoNomina'], '5')
        self.assertEqual(datos['fechas_pagos'], ['2026-03-15', '2026-03-31'])
        self.assertEqual(datos['devengados']['Basico'], {'DiasTrabajados': '30', 'SueldoTrabajado': '3000000.00'})
        self.assertEqual(datos['totales'], {
            'DevengadosTotal': '3249095.00', 'DeduccionesTotal': '240000.00', 'ComprobanteTotal': '3009095.00'})

    def test_fechas_de_pago_distintas_se_deduplican(self):
        datos = self._datos(self._documento(date(2024, 3, 1), pagos=((15, 15), (31, 15))))
        self.assertEqual(datos['fechas_pagos'], ['2026-03-15'])

    def test_numeracion_del_documento(self):
        doc = self._documento(date(2024, 3, 1))
        datos = self._datos(doc)
        self.assertEqual(datos['numero_secuencia']['Prefijo'], 'NE')
        self.assertEqual(datos['numero_secuencia']['Numero'], 'NE15')
        self.assertEqual(datos['numero_secuencia']['Consecutivo'], '15')
        self.assertEqual(datos['proveedor_xml']['SoftwareSC'], 'SC')
        # con consecutivo propio, manda el del documento
        doc.consecutive = 'NE99'
        self.assertEqual(self._datos(doc)['numero_secuencia']['Consecutivo'], '99')

    def test_sin_recibos_o_ajuste_error_claro(self):
        doc = self._documento(date(2024, 3, 1), pagos=())
        with self.assertRaises(UserError):
            doc._collect_documento_data()
        doc2 = self._documento(date(2024, 3, 1))
        doc2.write({'is_adjustment': True, 'adjustment_type': '1', 'adjustment_ref_cune': 'x' * 96})
        with self.assertRaises(UserError):
            doc2._collect_documento_data()

    def test_recibos_incompatibles_error_de_fusion_con_mensaje(self):
        doc = self._documento(date(2024, 3, 1))
        llamadas = []

        def distinto():
            llamadas.append(1)
            datos = _datos_recibo()
            # H-F1-10: el Sueldo puede cambiar en el mes (test_documento_merge lo fija); cualquier otro dato del trabajador sigue siendo único.
            datos['trabajador'] = dict(datos['trabajador'], NumeroDocumento='9999999999' if len(llamadas) == 2 else '1020304050')
            return datos
        with self.assertRaisesRegex(UserError, "La seccion 'trabajador' difiere"):
            self._datos(doc, recibo=distinto)

    def test_xml_sin_firmar_usa_el_builder_con_los_datos_fusionados(self):
        doc = self._documento(date(2024, 3, 1))
        with patch.object(type(self.env['hr.payslip']), '_collect_payslip_data', lambda s: _datos_recibo()), \
                patch.object(dian_utils, 'compute_software_security_code', lambda *a: 'SC'), \
                patch.object(nomina_xml_builder, 'build_nomina_individual_v2', lambda d: d['numero_secuencia']['Numero'].encode()):
            self.assertEqual(doc._ne_xml_sin_firmar('NE7'), b'NE7')

    # ── Alertas del XML (D4) ─────────────────────────────────────────
    def test_alerta_sin_seguridad_social_es_advertencia(self):
        doc = self._documento(date(2024, 3, 1))

        def solo_prima():
            datos = _datos_recibo()
            datos['deducciones'] = {}
            # Totales COHERENTES con los nodos: sin nodos de deducción el total de deducciones es 0
            # (si no, la conciliación de totales -- correctamente -- avisa 'totales_nodos').
            datos['deducciones_total'] = 0.00
            return datos
        with patch.object(type(self.env['hr.payslip']), '_collect_payslip_data', lambda s: solo_prima()), \
                patch.object(dian_utils, 'compute_software_security_code', lambda *a: 'SC'), \
                patch.object(type(doc), '_ne_conciliar_comprobantes', lambda s: []):    # la conciliación va aparte (C4)
            alertas = doc._ne_validar_xml()
        self.assertEqual([(a['key'], a['level']) for a in alertas], [('sin_seguridad_social', 'warning')])

    def test_sin_alertas_con_salud_y_pension(self):
        doc = self._documento(date(2024, 3, 1))
        with patch.object(type(self.env['hr.payslip']), '_collect_payslip_data', lambda s: _datos_recibo()), \
                patch.object(dian_utils, 'compute_software_security_code', lambda *a: 'SC'), \
                patch.object(type(doc), '_ne_conciliar_comprobantes', lambda s: []):    # la conciliación va aparte (C4)
            self.assertEqual(doc._ne_validar_xml(), [])

    def test_error_de_fusion_es_bloqueo(self):
        doc = self._documento(date(2024, 3, 1))
        with patch.object(type(self.env['hr.payslip']), '_collect_payslip_data', lambda s: _datos_recibo()), \
                patch.object(documento_merge, 'fusionar_documento',
                             side_effect=documento_merge.ErrorFusion('Porcentaje distinto')):
            alertas = doc._ne_validar_xml()
        self.assertEqual([(a['key'], a['level']) for a in alertas], [('xml', 'danger')])
        self.assertIn('Porcentaje distinto', alertas[0]['message'])

    # ── TiempoLaborado en el XML POR RECIBO (760 -> 750) ──────────────
    def test_tiempo_laborado_del_recibo_es_360_30_inclusivo(self):
        doc = self._documento(date(2024, 3, 1), pagos=((31, 31),))
        slip = doc.payslip_ids
        slip.date_to = date(2026, 3, 31)
        hr_payslip = type(slip)
        with patch.object(hr_payslip, '_map_salary_rules_to_xml', lambda s: ({}, {})), \
                patch.object(hr_payslip, '_ne_trabajador', lambda s: {}), \
                patch.object(hr_payslip, '_ne_pago', lambda s: {}), \
                patch.object(hr_payslip, '_ne_company_nit_dv', lambda s: ('900123456', '8')), \
                patch.object(dian_utils, 'get_department_code', lambda *a: '11'), \
                patch.object(dian_utils, 'get_city_code', lambda *a: '11001'), \
                patch.object(hr_payslip, '_ne_codigos_ubicacion', lambda *a: ('11', '11001')), \
                patch.object(dian_utils, 'compute_software_security_code', lambda *a: 'SC'):
            datos = slip._collect_payslip_data()
        self.assertEqual(datos['periodo']['TiempoLaborado'], '750')   # el calendario daba 760

    # ── Tipo de documento del trabajador (Frente 6, doc 59 §18) ──────────
    def _alertas_con_tipo(self, ref_tipo):
        doc = self._documento(date(2024, 3, 1))
        doc.employee_id.work_contact_id.sudo().l10n_latam_identification_type_id = self.env.ref(ref_tipo).id
        with patch.object(type(self.env['hr.payslip']), '_collect_payslip_data', lambda s: _datos_recibo()), \
                patch.object(dian_utils, 'compute_software_security_code', lambda *a: 'SC'), \
                patch.object(type(doc), '_ne_conciliar_comprobantes', lambda s: []):
            return doc, doc._ne_validar_xml()

    def test_empleado_con_nit_alerta_danger_que_lo_nombra(self):
        """F6-DOC-002: el codigo 31 pasa el esquema (Anexo, tabla 5.2.1) pero un trabajador (persona natural) no se
        identifica con NIT: regla de negocio de InSoTech."""
        doc, alertas = self._alertas_con_tipo('l10n_co.rut')
        nit = [a for a in alertas if a['key'] == 'tipo_documento_trabajador']
        self.assertEqual([a['level'] for a in nit], ['danger'])
        self.assertIn(doc.employee_id.name, nit[0]['message'])
        self.assertIn('Contactos', nit[0]['message'])

    def test_empleado_con_cedula_no_tiene_alerta_de_tipo_de_documento(self):
        _doc, alertas = self._alertas_con_tipo('l10n_co.national_citizen_id')
        self.assertFalse([a for a in alertas if a['key'] == 'tipo_documento_trabajador'])

    def test_empleado_con_vat_generico_no_tiene_codigo_dian_y_el_error_lo_nombra(self):
        """F6-DOC-001: el tipo generico (VAT) no tiene equivalente DIAN: el XML se bloquea nombrando al empleado."""
        doc = self._documento(date(2024, 3, 1))
        doc.employee_id.work_contact_id.sudo().l10n_latam_identification_type_id = self.env.ref(
            'l10n_latam_base.it_vat').id
        with self.assertRaises(UserError) as error:
            doc.payslip_ids[:1]._ne_tipo_documento()
        self.assertIn(doc.employee_id.name, str(error.exception))
