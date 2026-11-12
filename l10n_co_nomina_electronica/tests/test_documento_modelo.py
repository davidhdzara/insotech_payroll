# -*- coding: utf-8 -*-
"""Etapa 1b (doc 53 §3, §16.2, §18.6): modelo l10n.co.ne.documento + intento, enlace del recibo, reglas multiempresa y
migracion legacy 1:1. Valores a mano."""

from datetime import date, datetime
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

CUNE_A = 'a' * 96
CUNE_B = 'b' * 96
RESPUESTA_RECHAZO = (
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><GetStatusZipResponse '
    'xmlns="http://wcf.dian.colombia"><GetStatusZipResult xmlns:b="http://schemas.datacontract.org/2004/07/DianResponse">'
    '<b:DianResponse><b:ErrorMessage><c:string xmlns:c="http://schemas.microsoft.com/2003/10/Serialization/Arrays">'
    'Regla: NIAE191a, Rechazo: Documento a Reemplazar no se encuentra recibido en la Base de Datos.</c:string></b:ErrorMessage>'
    '<b:IsValid>false</b:IsValid><b:StatusCode>99</b:StatusCode>'
    '<b:StatusDescription>Validación contiene errores en campos mandatorios.</b:StatusDescription>'
    '<b:StatusMessage>Documento con errores en campos mandatorios.</b:StatusMessage></b:DianResponse>'
    '</GetStatusZipResult></GetStatusZipResponse></s:Body></s:Envelope>')


@tagged('post_install', '-at_install')
class TestDocumentoModelo(TransactionCase):

    @classmethod
    def _crear_compania(cls, nombre):
        return cls.env['res.company'].create({
            'name': nombre, 'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_tipo_aportante': '1',
            'l10n_co_pila_forma_presentacion': 'U', 'l10n_co_pila_clase_riesgo': '1', 'l10n_co_ne_febrero_modo': 'real'})

    @classmethod
    def _crear_empleado(cls, nombre, company):
        return cls.env['hr.employee'].create({
            'name': nombre, 'company_id': company.id, 'l10n_co_ne_worker_type': '01',
            'l10n_co_ne_worker_subtype': '00', 'l10n_co_ne_payment_method': '10'})

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._crear_compania('Compañía Documento A')
        cls.company_b = cls._crear_compania('Compañía Documento B')
        cls.structure_type = cls.env['hr.payroll.structure.type'].create({
            'name': 'Estructura Documento', 'country_id': cls.env.ref('base.co').id})
        cls.employee = cls._crear_empleado('Empleado Documento', cls.company)
        cls.employee2 = cls._crear_empleado('Otro Empleado Documento', cls.company)
        cls.employee_b = cls._crear_empleado('Empleado Documento B', cls.company_b)
        cls.contract = cls.env['hr.contract'].create({
            'name': 'Contrato Documento', 'employee_id': cls.employee.id, 'company_id': cls.company.id,
            'structure_type_id': cls.structure_type.id, 'l10n_co_ne_contract_type': '2',
            'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00',
            'wage': 3000000.0, 'date_start': date(2025, 1, 1), 'state': 'open'})
        cls.contract2 = cls.env['hr.contract'].create({
            'name': 'Contrato Documento 2', 'employee_id': cls.employee2.id, 'company_id': cls.company.id,
            'structure_type_id': cls.structure_type.id, 'l10n_co_ne_contract_type': '2',
            'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00',
            'wage': 3000000.0, 'date_start': date(2025, 1, 1), 'state': 'open'})
        cls.struct = cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')

    def _recibo(self, mes, employee=None, **vals):
        employee = employee or self.employee
        contract = {self.employee: self.contract, self.employee2: self.contract2}.get(employee)
        datos = {
            'name': 'Recibo %s' % mes, 'employee_id': employee.id, 'company_id': employee.company_id.id,
            'struct_id': self.struct.id, 'date_from': date(2026, mes, 1), 'date_to': date(2026, mes, 28)}
        if contract:
            datos['contract_id'] = contract.id
        datos.update(vals)
        return self.env['hr.payslip'].create(datos)

    def _documento(self, mes=3, employee=None, **vals):
        datos = {'company_id': self.company.id, 'employee_id': (employee or self.employee).id,
                 'period': date(2026, mes, 1)}
        datos.update(vals)
        return self.env['l10n.co.ne.documento'].create(datos)

    def _intento(self, doc, estado, dt, **vals):
        datos = {'documento_id': doc.id, 'state': estado, 'datetime': dt}
        datos.update(vals)
        return self.env['l10n.co.ne.documento.intento'].create(datos)

    # ── Estado ───────────────────────────────────────────────────────
    def test_estado_sin_intentos_es_la_etapa(self):
        doc = self._documento()
        self.assertEqual(doc.state, 'draft')
        doc.etapa = 'ready'
        self.assertEqual(doc.state, 'ready')

    def test_estado_es_el_del_ultimo_intento(self):
        doc = self._documento()
        self._intento(doc, 'invoice_pending', datetime(2026, 4, 1, 10, 0))
        self.assertEqual(doc.state, 'invoice_pending')
        self._intento(doc, 'invoice_accepted', datetime(2026, 4, 1, 11, 0))
        self.assertEqual(doc.state, 'invoice_accepted')
        # un intento anterior (por fecha) no cambia el estado
        self._intento(doc, 'invoice_rejected', datetime(2026, 4, 1, 9, 0))
        self.assertEqual(doc.state, 'invoice_accepted')

    def test_estado_incierto_y_eliminado_tienen_prioridad(self):
        doc = self._documento()
        self._intento(doc, 'invoice_pending', datetime(2026, 4, 1, 10, 0))
        doc.incierto = True
        self.assertEqual(doc.state, 'uncertain')
        doc.eliminado = True
        self.assertEqual(doc.state, 'eliminated')

    def test_nombre_y_cola(self):
        doc = self._documento()
        self.assertEqual(doc.name, 'Empleado Documento 2026-03')
        self.assertFalse(doc.is_being_sent)
        doc.sending_data = {'intentos': 0}
        self.assertTrue(doc.is_being_sent)
        doc.alertas = [{'key': 'a', 'level': 'danger', 'message': 'Falta <b>x</b>'}]
        self.assertIn('Bloqueo: Falta &lt;b&gt;x&lt;/b&gt;', str(doc.alertas_texto))

    # ── Restricciones ────────────────────────────────────────────────
    def test_mes_debe_ser_primer_dia(self):
        with self.assertRaises(ValidationError):
            self._documento(period=date(2026, 3, 15))

    def test_un_original_por_empleado_y_mes(self):
        self._documento(3)
        with self.assertRaises(ValidationError):
            self._documento(3)
        self._documento(4)                       # otro mes: ok
        self._documento(3, employee=self.employee2)  # otro empleado: ok

    def test_ajuste_legacy_y_eliminado_no_cuentan_para_la_unicidad(self):
        original = self._documento(3)
        self._documento(3, is_adjustment=True, adjustment_type='1', adjustment_ref_cune=CUNE_A)
        self._documento(3, legacy=True)
        original.eliminado = True
        original.flush_recordset()   # el UPDATE pendiente debe llegar a la base antes del INSERT del nuevo
        self._documento(3)  # el eliminado ya no cuenta

    def test_ajuste_exige_cune_de_referencia(self):
        with self.assertRaises(ValidationError):
            self._documento(3, is_adjustment=True, adjustment_type='1')

    def test_compania_no_colombiana_no_tiene_documentos(self):
        with patch.object(type(self.company), '_ne_es_colombia', lambda s: False):
            with self.assertRaises(ValidationError):
                self._documento(3)

    def test_recibo_de_otro_empleado_no_entra(self):
        doc = self._documento(3)
        otro = self._recibo(3, employee=self.employee2)
        with self.assertRaises(ValidationError):
            otro.l10n_co_ne_documento_id = doc

    def test_recibo_enlazado_refleja_el_estado(self):
        doc = self._documento(3)
        slip = self._recibo(3)
        slip.l10n_co_ne_documento_id = doc
        self.assertEqual(doc.payslip_ids, slip)
        self.assertEqual(slip.l10n_co_ne_documento_state, 'draft')
        self._intento(doc, 'invoice_accepted', datetime(2026, 4, 1, 10, 0))
        self.assertEqual(slip.l10n_co_ne_documento_state, 'invoice_accepted')
        self.assertEqual(slip.l10n_co_ne_intento_ids, doc.intento_ids)

    def test_borrar_solo_sin_historia(self):
        self._documento(3).unlink()
        con_intento = self._documento(4)
        self._intento(con_intento, 'invoice_pending', datetime(2026, 5, 1))
        with self.assertRaises(UserError):
            con_intento.unlink()
        with self.assertRaises(UserError):
            self._documento(5, legacy=True).unlink()

    def test_intento_motivo_desde_message_json(self):
        doc = self._documento(3)
        intento = self._intento(doc, 'invoice_rejected', datetime(2026, 4, 1), message_json={
            'status': 'Rechazado', 'detail': '', 'errors': ['Regla: NIAE191a, Rechazo: x'], 'status_code': '99',
            'is_valid': False, 'transport': False, 'fault': []})
        self.assertIn('Regla: NIAE191a', intento.message)
        self.assertIn('Regla: NIAE191a', doc.message)
        self.assertFalse(self._intento(doc, 'invoice_pending', datetime(2026, 3, 1)).show_button_get_status)
        self.assertTrue(self._intento(doc, 'invoice_pending', datetime(2026, 3, 2), zip_key='Z1').show_button_get_status)

    # ── Multiempresa ─────────────────────────────────────────────────
    def test_regla_multiempresa(self):
        doc_a = self._documento(3)
        doc_b = self.env['l10n.co.ne.documento'].create({
            'company_id': self.company_b.id, 'employee_id': self.employee_b.id, 'period': date(2026, 3, 1)})
        grupo = self.env.ref('hr_payroll.group_hr_payroll_manager')
        usuario = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Usuario Solo A', 'login': 'solo_a_documento', 'company_id': self.company.id,
            'company_ids': [(6, 0, self.company.ids)],
            'groups_id': [(6, 0, [grupo.id, self.env.ref('base.group_user').id])]})
        visibles = self.env['l10n.co.ne.documento'].with_user(usuario).search(
            [('id', 'in', (doc_a | doc_b).ids)])
        self.assertEqual(visibles, doc_a)

    # ── Migración legacy ─────────────────────────────────────────────
    def _legacy(self, mes, estado, **vals):
        datos = {'l10n_co_ne_state': estado}
        datos.update(vals)
        return self._recibo(mes, **datos)

    def test_migracion_sin_filas(self):
        # no depende de la base: la base real ya tiene documentos legacy creados por la migracion .191
        self.assertFalse(self.env['l10n.co.ne.documento']._ne_migrar_legacy(self.env['hr.payslip']))
        borrador = self._recibo(4)   # sin historia: nada que migrar
        self.assertFalse(self.env['l10n.co.ne.documento']._ne_migrar_legacy(borrador))

    def test_migracion_aceptado_uno_a_uno_e_idempotente(self):
        slip = self._legacy(3, 'accepted', l10n_co_ne_cune=CUNE_A, l10n_co_ne_consecutive='NE1',
                            l10n_co_ne_zip_key='Z1', l10n_co_ne_hab_set_id='SET1')
        borrador = self._recibo(4)   # sin historia: no se migra
        creados = self.env['l10n.co.ne.documento']._ne_migrar_legacy(slip | borrador)
        doc = slip.l10n_co_ne_documento_id
        self.assertEqual(creados, doc)
        self.assertFalse(borrador.l10n_co_ne_documento_id)
        self.assertTrue(doc.legacy)
        self.assertEqual((doc.cune, doc.consecutive, doc.zip_key, doc.hab_set_id), (CUNE_A, 'NE1', 'Z1', 'SET1'))
        self.assertEqual(doc.period, date(2026, 3, 1))
        self.assertEqual(doc.state, 'invoice_accepted')
        self.assertEqual(doc.intento_ids.state, 'invoice_accepted')
        self.assertEqual(doc.intento_ids.identifier, CUNE_A)
        self.assertEqual(doc.intento_ids.numero, 'NE1')
        self.assertTrue(doc.intento_ids.certification_process)
        # no se quita nada del recibo
        self.assertEqual((slip.l10n_co_ne_state, slip.l10n_co_ne_cune, slip.l10n_co_ne_consecutive),
                         ('accepted', CUNE_A, 'NE1'))
        self.assertEqual(slip.l10n_co_ne_documento_state, 'invoice_accepted')
        # idempotente
        self.assertFalse(self.env['l10n.co.ne.documento']._ne_migrar_legacy(slip | borrador))
        self.assertEqual(self.env['l10n.co.ne.documento'].search_count([('legacy', '=', True), ('cune', '=', CUNE_A)]), 1)

    def test_migracion_mapa_de_estados(self):
        esperado = {2: ('generated', 'ready'), 3: ('sent', 'invoice_pending'), 4: ('uncertain', 'uncertain'),
                    5: ('rejected', 'invoice_rejected'), 6: ('eliminated', 'eliminated')}
        recibos = {mes: self._legacy(mes, estado, l10n_co_ne_consecutive='NE%s' % mes)
                   for mes, (estado, _) in esperado.items()}
        self.env['l10n.co.ne.documento']._ne_migrar_legacy(self.env['hr.payslip'].concat(*recibos.values()))
        for mes, (_estado, estado_doc) in esperado.items():
            self.assertEqual(recibos[mes].l10n_co_ne_documento_id.state, estado_doc, 'mes %s' % mes)
        self.assertFalse(recibos[2].l10n_co_ne_documento_id.intento_ids)   # generado: sin intento
        self.assertEqual(len(recibos[3].l10n_co_ne_documento_id.intento_ids), 1)

    def test_migracion_motivo_reparseado_de_la_respuesta_guardada(self):
        slip = self._legacy(3, 'rejected', l10n_co_ne_cune=CUNE_A, l10n_co_ne_dian_response=RESPUESTA_RECHAZO)
        self.env['l10n.co.ne.documento']._ne_migrar_legacy(slip)
        intento = slip.l10n_co_ne_documento_id.intento_ids
        self.assertIn('Regla: NIAE191a', intento.message)
        self.assertEqual(intento.message_json['status_code'], '99')

    def test_migracion_respuesta_ilegible_no_bloquea(self):
        slip = self._legacy(3, 'sent', l10n_co_ne_cune=CUNE_A, l10n_co_ne_dian_response='esto no es xml')
        self.env['l10n.co.ne.documento']._ne_migrar_legacy(slip)
        self.assertEqual(slip.l10n_co_ne_documento_id.intento_ids.message_json['status_code'], 'PARSE_ERROR')

    def test_migracion_nota_de_ajuste_apunta_a_su_original(self):
        original = self._legacy(3, 'accepted', l10n_co_ne_cune=CUNE_A, l10n_co_ne_consecutive='NE1')
        ajuste = self._legacy(4, 'accepted', l10n_co_ne_cune=CUNE_B, l10n_co_ne_consecutive='NA1',
                              l10n_co_ne_is_adjustment=True, l10n_co_ne_adjustment_type='2',
                              l10n_co_ne_adjustment_ref_cune=CUNE_A)
        self.env['l10n.co.ne.documento']._ne_migrar_legacy(original | ajuste)
        doc_aj = ajuste.l10n_co_ne_documento_id
        self.assertEqual(doc_aj.parent_id, original.l10n_co_ne_documento_id)
        self.assertEqual(doc_aj.adjustment_type, '2')
        self.assertEqual(original.l10n_co_ne_documento_id.eliminado_por_id, doc_aj)

    def test_migracion_compania_no_colombiana_no_se_toca(self):
        slip = self._legacy(3, 'accepted', l10n_co_ne_cune=CUNE_A)
        with patch.object(type(self.company), '_ne_es_colombia', lambda s: False):
            self.assertFalse(self.env['l10n.co.ne.documento']._ne_migrar_legacy(slip))
        self.assertFalse(slip.l10n_co_ne_documento_id)

    # ── Vistas ───────────────────────────────────────────────────────
    def test_vistas_del_documento_cargan(self):
        for tipo in ('form', 'list', 'search'):
            vista = self.env['l10n.co.ne.documento'].get_view(view_type=tipo)
            self.assertTrue(vista['arch'], tipo)
        recibo = self.env['hr.payslip'].get_view(view_type='form')
        self.assertIn('l10n_co_ne_documento_state', recibo['arch'])
        self.assertIn('edi_documents', recibo['arch'])
        self.assertTrue(self.env.ref('l10n_co_nomina_electronica.menu_l10n_co_ne_documento'))
