# -*- coding: utf-8 -*-
"""H-001 (2026-11-09, doc 31): flujo "Eliminar" de las notas de ajuste (Anexo Técnico 5.5.8,
TipoNota=2).

- Eliminar lleva solo lo que el XSD admite (predecesor, secuencia, lugar, proveedor, QR,
  información general, notas, empleador), sin CodigoTrabajador, PeriodoNomina ni TipoMoneda.
- El XML construido valida contra NominaIndividualDeAjusteElectronicaXSDV1.0.6.xsd.
- Aceptada la nota Eliminar, el original pasa a 'eliminated'; 'eliminated' no se degrada.
- El CUNE de Eliminar NO está definido en el Anexo: generar el XML levanta un UserError explícito.
"""

import base64
import os
from datetime import date
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.l10n_co_nomina_electronica.services import nomina_xml_builder


class _FakeCertificate:
    date_end = False

    def __bool__(self):
        return True


def _ruta_xsd():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(
        base, 'DIAN', 'Caja-de-Herramientas-Nomina-Electronica-V1-0', 'XSD',
        'NominaIndividualDeAjusteElectronicaXSDV1.0.6.xsd')


class TestNotaAjusteEliminar(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        co = cls.env.ref('base.co')
        cop = cls.env['res.currency'].search([('name', '=', 'COP')], limit=1)
        cls.company = cls.env['res.company'].create({
            'name': 'Compañía de Prueba Eliminar',
            'currency_id': cop.id,
            'vat': '900123456-7',
        })
        state = cls.env['res.country.state'].search([('country_id', '=', co.id)], limit=1)
        if not state:
            state = cls.env['res.country.state'].create({
                'name': 'Departamento Prueba Eliminar', 'code': 'PE', 'country_id': co.id})
        city = cls.env['res.city'].create({
            'name': 'Ciudad Prueba Eliminar', 'state_id': state.id, 'country_id': co.id})
        cls.company.partner_id.write({
            'country_id': co.id, 'state_id': state.id, 'city_id': city.id,
            'street': 'Calle Prueba Eliminar # 1-1',
        })
        cls.env['l10n.co.ne.operation_mode'].create({
            'company_id': cls.company.id,
            'software_id': 'SOFTWARE-TEST-ID',
            'software_pin': 'PIN-TEST',
        })
        cls.structure_type = cls.env['hr.payroll.structure.type'].create({
            'name': 'Prueba Estructura Eliminar', 'country_id': co.id})
        cls.structure = cls.env['hr.payroll.structure'].create({
            'name': 'Nómina Prueba Eliminar', 'type_id': cls.structure_type.id})

    def setUp(self):
        super().setUp()
        patcher = patch(
            'odoo.addons.l10n_co_nomina_electronica.models.res_company.'
            'ResCompany._get_ne_certificate', return_value=_FakeCertificate())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _payslip(self, vals_extra=None):
        employee = self.env['hr.employee'].create({
            'name': 'Empleado Eliminar',
            'identification_id': '70' + str(self.env['hr.employee'].search_count([])),
            'company_id': self.company.id,
            'l10n_co_ne_payment_method': '10',
        })
        employee.l10n_co_ne_identification_type_id = self.env.ref('l10n_co.national_citizen_id').id
        contract = self.env['hr.contract'].create({
            'name': 'Contrato Eliminar', 'employee_id': employee.id,
            'company_id': self.company.id, 'structure_type_id': self.structure_type.id,
            'wage': 1800000.0, 'date_start': date(2024, 1, 1), 'state': 'open',
        })
        vals = {
            'name': 'Nómina Eliminar', 'employee_id': employee.id, 'contract_id': contract.id,
            'company_id': self.company.id, 'struct_id': self.structure.id,
            'date_from': date(2026, 9, 1), 'date_to': date(2026, 9, 30),
        }
        vals.update(vals_extra or {})
        return self.env['hr.payslip'].create(vals)

    def _original_aceptado(self):
        original = self._payslip()
        xml = (b'<NominaIndividual><InformacionGeneral FechaGen="2026-09-30"/></NominaIndividual>')
        adjunto = self.env['ir.attachment'].create({
            'name': 'original.xml', 'datas': base64.b64encode(xml),
            'res_model': 'hr.payslip', 'res_id': original.id})
        original.write({
            'l10n_co_ne_cune': 'CUNE-ORIGINAL-PRUEBA',
            'l10n_co_ne_consecutive': 'NE00000001',
            'l10n_co_ne_xml_attachment_id': adjunto.id,
            'l10n_co_ne_state': 'accepted',
        })
        return original

    def _nota_eliminar(self, original, **extra):
        vals = {
            'l10n_co_ne_is_adjustment': True,
            'l10n_co_ne_adjustment_type': '2',
            'l10n_co_ne_adjustment_ref_cune': original.l10n_co_ne_cune,
        }
        vals.update(extra)
        return self._payslip(vals)

    def test_datos_de_eliminar_solo_las_secciones_permitidas(self):
        nota = self._nota_eliminar(self._original_aceptado())
        data = nota._collect_payslip_data()
        self.assertEqual(data['tipo_nota'], '2')
        self.assertIn('eliminar', data)
        self.assertNotIn('reemplazar', data)
        self.assertEqual(
            set(data['eliminar']),
            {'predecesor', 'numero_secuencia', 'lugar_generacion', 'proveedor_xml',
             'informacion_general', 'empleador'})
        self.assertNotIn('CodigoTrabajador', data['eliminar']['numero_secuencia'])
        self.assertEqual(data['eliminar']['predecesor']['CUNEPred'], 'CUNE-ORIGINAL-PRUEBA')
        self.assertEqual(data['eliminar']['predecesor']['NumeroPred'], 'NE00000001')
        self.assertEqual(data['eliminar']['predecesor']['FechaGenPred'], '2026-09-30')

    def test_reemplazar_sigue_igual(self):
        original = self._original_aceptado()
        nota = self._nota_eliminar(original, l10n_co_ne_adjustment_type='1')
        data = nota._collect_payslip_data()
        self.assertEqual(data['tipo_nota'], '1')
        self.assertIn('reemplazar', data)
        self.assertNotIn('eliminar', data)

    def test_xml_de_eliminar_valida_contra_el_xsd(self):
        nota = self._nota_eliminar(self._original_aceptado())
        xml = nomina_xml_builder.build_nota_ajuste_v2(nota._collect_payslip_data())
        doc = etree.fromstring(xml)
        info = doc.find('.//{*}Eliminar/{*}InformacionGeneral')
        self.assertIsNotNone(info)
        self.assertNotIn('PeriodoNomina', info.attrib)
        self.assertNotIn('TipoMoneda', info.attrib)
        secuencia = doc.find('.//{*}Eliminar/{*}NumeroSecuenciaXML')
        self.assertNotIn('CodigoTrabajador', secuencia.attrib)
        esquema = etree.XMLSchema(etree.parse(_ruta_xsd()))
        esquema.validate(doc)
        errores = [str(e) for e in esquema.error_log]
        self.assertEqual(errores, [], 'El XML de Eliminar no valida contra el XSD: %s' % errores)

    def test_aceptar_la_nota_eliminar_marca_el_original_eliminado(self):
        original = self._original_aceptado()
        nota = self._nota_eliminar(original)
        nota.l10n_co_ne_state = 'accepted'
        nota._ne_marcar_original_eliminado()
        self.assertEqual(original.l10n_co_ne_state, 'eliminated')

    def test_nota_reemplazar_aceptada_no_elimina_el_original(self):
        original = self._original_aceptado()
        nota = self._nota_eliminar(original, l10n_co_ne_adjustment_type='1')
        nota.l10n_co_ne_state = 'accepted'
        nota._ne_marcar_original_eliminado()
        self.assertEqual(original.l10n_co_ne_state, 'accepted')

    def test_generar_xml_de_eliminar_levanta_usererror_por_cune_sin_definir(self):
        nota = self._nota_eliminar(self._original_aceptado())
        nota.state = 'done'
        with self.assertRaises(UserError) as exc:
            nota._validate_ne_prerequisites()
        self.assertIn('CUNE', str(exc.exception))

    def test_no_se_puede_eliminar_una_nota_de_ajuste(self):
        original = self._original_aceptado()
        nota = self._nota_eliminar(original)
        nota.l10n_co_ne_state = 'accepted'
        with self.assertRaises(UserError):
            nota.action_create_elimination()

    def test_botones_abren_el_tipo_correcto(self):
        original = self._original_aceptado()
        accion = original.action_create_elimination()
        self.assertEqual(accion['context']['default_l10n_co_ne_adjustment_type'], '2')
        accion = original.action_create_adjustment()
        self.assertEqual(accion['context']['default_l10n_co_ne_adjustment_type'], '1')
