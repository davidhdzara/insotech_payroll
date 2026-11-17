# -*- coding: utf-8 -*-
"""E-10 (doc 64, H-QA-030): el botón nativo «Pagar» del recibo y la cuenta del neto en la regla nativa ``NET``.

DECISIÓN (TL, 2026-11-16, opción C1): la cuenta del neto va en la regla nativa ``NET`` de cada estructura y se deja VACÍA en
``CO_NETO``/``CO_LIQ_NETO``/``CO_PRIMA_NETO``/``CO_BON_NETO``; una guarda impide configurar la cuenta en las dos (duplicaría el
crédito del neto) y ``_ne_fechas_pagos_contables`` solo mira la línea del neto (cuenta de ``NET`` + partner del empleado).

ESTADO: este archivo se escribió ANTES del código de producción (pruebas «rojas por escrito»). No ejecutadas (no hay Odoo local).
- **ROJAS a propósito hasta que exista E-10 (2):** ``test_la_guarda_...`` y ``test_un_pago_a_un_tercero_...``.
- **De CARACTERIZACIÓN del comportamiento nativo en que C1 se apoya (se esperan VERDES hoy y después):** si alguna falla por el
  fixture contable, se ajusta el fixture ANTES de escribir código, porque son el contrato de que «NET con cuenta por pagar» sirve.
NO regresionar esta rama hasta que E-10 esté implementado.

Texto nativo (consultor v19, v18 y v19): ``hr_payroll_account/models/hr_payslip.py`` ``action_register_payment`` (chequeo de la regla de
código ``NET``, cuenta bancaria de confianza, asiento publicado, estado distinto de ``paid``) y ``_prepare_line_values`` (el partner
del empleado solo se asigna a la línea cuya regla es ``NET``); ``account.payment.register.default_get`` solo acepta cuentas por
pagar/por cobrar con saldo pendiente.
"""

from datetime import date

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

NETOS = (
    ('hr_payroll_structure_co_nomina', 'CO_NETO'), ('hr_payroll_structure_co_liquidacion', 'CO_LIQ_NETO'),
    ('hr_payroll_structure_co_prima', 'CO_PRIMA_NETO'), ('hr_payroll_structure_co_bonificacion', 'CO_BON_NETO'))


@tagged('post_install', '-at_install')
class TestPagarNeto(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U',
            'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_clase_riesgo': '1', 'l10n_co_ne_febrero_modo': 'real',
            'l10n_co_ne_redondeo_dias': 'DOWN', 'name': 'Compañía Pagar Neto'})
        cls.env = cls.company.with_company(cls.company).env
        Account, Journal = cls.env['account.account'], cls.env['account.journal']

        def cuenta(code, name, tipo, **extra):
            return Account.create(dict({
                'code': code, 'name': name, 'account_type': tipo, 'company_ids': [(6, 0, [cls.company.id])]}, **extra))
        cls.gasto = cuenta('510505', 'Sueldos prueba', 'expense')
        cls.neto_por_pagar = cuenta('250510', 'Neto por pagar (por pagar)', 'liability_payable')
        cls.neto_pasivo = cuenta('250511', 'Neto pasivo corriente (no por pagar)', 'liability_current')
        cls.eps_por_pagar = cuenta('237005', 'EPS por pagar (por pagar)', 'liability_payable')
        cls.otra_cuenta_neto = cuenta('250512', 'Otra cuenta de neto', 'liability_payable')
        cls.liquidez = cuenta('111005', 'Banco prueba', 'asset_cash')
        cls.pagos_pendientes = cuenta('111010', 'Pagos pendientes', 'asset_current', reconcile=True)
        cls.diario_nomina = Journal.create({
            'name': 'Salarios prueba', 'code': 'SLPT', 'type': 'general', 'company_id': cls.company.id})
        valores_banco = {
            'name': 'Banco prueba', 'code': 'BNKT', 'type': 'bank', 'company_id': cls.company.id,
            'default_account_id': cls.liquidez.id}
        if 'suspense_account_id' in Journal._fields:        # el diario bancario lo pide en Odoo 18 si la compañía no tiene plan
            valores_banco['suspense_account_id'] = cuenta('111015', 'Suspenso prueba', 'asset_current', reconcile=True).id
        cls.banco = Journal.create(valores_banco)
        cls.banco.outbound_payment_method_line_ids.write({'payment_account_id': cls.pagos_pendientes.id})
        cls.eps = cls.env['res.partner'].create({'name': 'EPS Pagar Neto'})

        cls.estructura = cls.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
        Regla = cls.env['hr.salary.rule']
        cls.regla_net = Regla.search([('code', '=', 'NET'), ('struct_id', '=', cls.estructura.id)])
        cls.regla_co_neto = Regla.search([('code', '=', 'CO_NETO'), ('struct_id', '=', cls.estructura.id)])
        cls.regla_basico = Regla.search([('code', '=', 'CO_BASICO'), ('struct_id', '=', cls.estructura.id)])
        cls.regla_basico.write({'account_debit': cls.gasto.id})

        cls.empleado = cls.env['hr.employee'].create({
            'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00', 'name': 'Empleado Pagar Neto',
            'company_id': cls.company.id, 'l10n_co_ne_payment_method': '10'})
        banco_empleado = cls.env['res.partner.bank'].create({
            'acc_number': '123456789', 'partner_id': cls.empleado.work_contact_id.id, 'allow_out_payment': True})
        cls.empleado.write({'bank_account_id': banco_empleado.id, 'l10n_co_ne_payment_method': '1'})
        contrato = cls.env['hr.contract'].create({
            'l10n_co_ne_contract_type': '2', 'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00',
            'name': 'Contrato Pagar Neto', 'employee_id': cls.empleado.id, 'company_id': cls.company.id, 'wage': 3000000,
            'date_start': '2026-01-01', 'state': 'draft'})
        cls.recibo = cls.env['hr.payslip'].create({
            'name': 'Recibo Pagar Neto', 'employee_id': cls.empleado.id, 'contract_id': contrato.id,
            'company_id': cls.company.id, 'struct_id': cls.estructura.id,
            'date_from': '2026-03-01', 'date_to': '2026-03-31'})

    # ── fixtures ─────────────────────────────────────────────────────
    def _cuenta_del_neto(self, regla, cuenta):
        regla.with_company(self.company).write({'account_credit': cuenta.id if cuenta else False})

    def _linea(self, regla, total, recibo=None):
        recibo = recibo or self.recibo
        return self.env['hr.payslip.line'].create({
            'slip_id': recibo.id, 'salary_rule_id': regla.id, 'code': regla.code, 'name': regla.name,
            'category_id': regla.category_id.id, 'employee_id': recibo.employee_id.id, 'contract_id': recibo.contract_id.id,
            'total': total, 'amount': total, 'quantity': 1, 'rate': 100})

    def _entradas(self, recibo=None):
        recibo = recibo or self.recibo
        return recibo._prepare_slip_lines(recibo.date_to, [])

    def _asiento_publicado(self, neto=900000.0, eps=100000.0):
        """Asiento del recibo ya publicado y ligado a él: gasto contra neto por pagar (partner = empleado) y un pasivo con la EPS
        (cuenta por pagar CONCILIABLE: es el caso que hoy contaminaría la fecha de pago)."""
        asiento = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.diario_nomina.id, 'date': date(2026, 3, 31),
            'line_ids': [
                (0, 0, {'account_id': self.gasto.id, 'debit': neto + eps, 'credit': 0.0, 'name': 'Sueldo'}),
                (0, 0, {'account_id': self.neto_por_pagar.id, 'debit': 0.0, 'credit': neto, 'name': 'Neto a pagar',
                        'partner_id': self.empleado.work_contact_id.id}),
                (0, 0, {'account_id': self.eps_por_pagar.id, 'debit': 0.0, 'credit': eps, 'name': 'Aporte salud',
                        'partner_id': self.eps.id})]})
        asiento.action_post()
        self.recibo.write({'move_id': asiento.id})
        return asiento

    def _linea_de(self, asiento, cuenta):
        return asiento.line_ids.filtered(lambda l: l.account_id == cuenta)

    def _pagar(self, linea, partner, monto, fecha):
        """Pago saliente publicado y conciliado con ``linea`` (un pago contable real, como el del asistente nativo)."""
        pago = self.env['account.payment'].create({
            'payment_type': 'outbound', 'partner_type': 'supplier', 'partner_id': partner.id, 'amount': monto,
            'date': fecha, 'journal_id': self.banco.id, 'destination_account_id': linea.account_id.id})
        pago.action_post()
        (pago.move_id.line_ids.filtered(lambda l: l.account_id == linea.account_id) + linea).reconcile()
        return pago

    # ── prerrequisito: C1 se apoya en que cada estructura propia tiene su regla NET ─────────────────
    def test_cada_estructura_propia_tiene_una_sola_regla_net(self):
        for xmlid, codigo in NETOS:
            with self.subTest(estructura=xmlid):
                estructura = self.env.ref('l10n_co_nomina_electronica.%s' % xmlid)
                self.assertEqual(len(estructura.rule_ids.filtered(lambda r: r.code == 'NET')), 1)
                self.assertEqual(len(estructura.rule_ids.filtered(lambda r: r.code == codigo)), 1)

    # ── asiento con la cuenta en NET (caracteriza el nativo en que se apoya C1; se espera VERDE) ───────────────
    def test_con_la_cuenta_en_net_el_neto_va_en_una_sola_linea_con_el_partner_del_empleado_y_el_asiento_cuadra(self):
        self._cuenta_del_neto(self.regla_net, self.neto_por_pagar)
        self._cuenta_del_neto(self.regla_co_neto, False)
        self._linea(self.regla_basico, 1000000.0)
        self._linea(self.regla_net, 1000000.0)          # E-3a: NET vale lo mismo que CO_NETO
        self._linea(self.regla_co_neto, 1000000.0)
        entradas = self._entradas()
        netos = [e for e in entradas if e['account_id'] == self.neto_por_pagar.id]
        self.assertEqual(len(netos), 1, 'El neto debe ir en UNA sola línea (la de NET): no duplicar el crédito.')
        self.assertAlmostEqual(netos[0]['credit'], 1000000.0, places=2)
        self.assertEqual(netos[0]['partner_id'], self.empleado.work_contact_id.id)   # saldo por empleado
        self.assertAlmostEqual(sum(e['debit'] for e in entradas), sum(e['credit'] for e in entradas), places=2)

    def test_solo_con_la_cuenta_en_co_neto_el_asiento_sale_como_hoy_sin_partner(self):
        """Compatibilidad (decisión TL: la guarda NO bloquea esta configuración): el neto sale por CO_NETO y sin partner, y «Pagar»
        sigue sin habilitarse."""
        self._cuenta_del_neto(self.regla_net, False)
        self._cuenta_del_neto(self.regla_co_neto, self.neto_por_pagar)
        self._linea(self.regla_basico, 1000000.0)
        self._linea(self.regla_net, 1000000.0)
        self._linea(self.regla_co_neto, 1000000.0)
        netos = [e for e in self._entradas() if e['account_id'] == self.neto_por_pagar.id]
        self.assertEqual(len(netos), 1)
        self.assertFalse(netos[0]['partner_id'])

    # ── la guarda (ROJA hasta E-10) ──────────────────────────────────
    def test_la_guarda_da_error_si_la_cuenta_esta_en_net_y_en_la_regla_del_modulo_y_nombra_las_dos(self):
        self._cuenta_del_neto(self.regla_net, self.neto_por_pagar)
        self._cuenta_del_neto(self.regla_co_neto, self.otra_cuenta_neto)
        self._linea(self.regla_basico, 1000000.0)
        self._linea(self.regla_net, 1000000.0)
        self._linea(self.regla_co_neto, 1000000.0)
        with self.assertRaises(UserError) as error:
            self._entradas()
        mensaje = str(error.exception)
        self.assertIn('NET', mensaje)
        self.assertIn('CO_NETO', mensaje)
        self.assertIn(self.estructura.name, mensaje)
        self.assertIn(self.company.name, mensaje)

    def test_la_guarda_es_por_estructura_la_cuenta_en_net_de_una_no_choca_con_el_neto_de_otra(self):
        liquidacion = self.env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_liquidacion')
        regla_liq = self.env['hr.salary.rule'].search([('code', '=', 'CO_LIQ_NETO'), ('struct_id', '=', liquidacion.id)])
        self._cuenta_del_neto(self.regla_net, self.neto_por_pagar)
        self._cuenta_del_neto(self.regla_co_neto, False)
        self._cuenta_del_neto(regla_liq, self.otra_cuenta_neto)
        self._linea(self.regla_basico, 1000000.0)
        self._linea(self.regla_net, 1000000.0)
        self.assertTrue(self._entradas())               # no lanza

    # ── detección del pago (la 1.ª es ROJA hasta E-10) ───────────────
    def test_un_pago_a_un_tercero_no_fija_la_fecha_de_pago_del_recibo(self):
        """El pago a la EPS (cuenta por pagar conciliable del mismo asiento) NO cuenta: solo el de la línea del neto."""
        self._cuenta_del_neto(self.regla_net, self.neto_por_pagar)
        asiento = self._asiento_publicado()
        self._pagar(self._linea_de(asiento, self.eps_por_pagar), self.eps, 100000.0, date(2026, 4, 2))
        self.assertEqual(self.recibo._ne_fechas_pagos_contables(), [], 'Un pago a la EPS no es pago del neto del empleado.')
        self._pagar(self._linea_de(asiento, self.neto_por_pagar), self.empleado.work_contact_id, 900000.0, date(2026, 4, 5))
        self.assertEqual(self.recibo._ne_fechas_pagos_contables(), [date(2026, 4, 5)])

    def test_pagos_parciales_del_neto_suman_sus_fechas(self):
        self._cuenta_del_neto(self.regla_net, self.neto_por_pagar)
        asiento = self._asiento_publicado()
        linea = self._linea_de(asiento, self.neto_por_pagar)
        self._pagar(linea, self.empleado.work_contact_id, 400000.0, date(2026, 4, 5))
        self._pagar(linea, self.empleado.work_contact_id, 500000.0, date(2026, 4, 20))
        self.assertEqual(self.recibo._ne_fechas_pagos_contables(), [date(2026, 4, 5), date(2026, 4, 20)])

    def test_sin_pagos_no_hay_fechas(self):
        self._cuenta_del_neto(self.regla_net, self.neto_por_pagar)
        self._asiento_publicado()
        self.assertEqual(self.recibo._ne_fechas_pagos_contables(), [])

    # ── el botón nativo «Pagar» (caracterizan el nativo; se esperan VERDES) ──────────────────────
    def test_pagar_con_la_cuenta_por_pagar_en_net_abre_el_asistente_nativo_con_la_linea_del_neto(self):
        self._cuenta_del_neto(self.regla_net, self.neto_por_pagar)
        asiento = self._asiento_publicado()
        self.recibo.write({'state': 'done'})
        accion = self.recibo.action_register_payment()
        self.assertEqual(accion['res_model'], 'account.payment.register')
        self.assertEqual(accion['context']['default_partner_id'], self.empleado.work_contact_id.id)
        self.assertIn(self._linea_de(asiento, self.neto_por_pagar).id, accion['context']['active_ids'])

    def test_pagar_sin_cuenta_en_net_da_el_error_nativo_y_no_se_sobrescribe(self):
        """Control: con la cuenta solo en CO_NETO el mensaje es el NATIVO («not reconciliable»): el módulo no lo reemplaza."""
        self._cuenta_del_neto(self.regla_net, False)
        self._cuenta_del_neto(self.regla_co_neto, self.neto_por_pagar)
        self._asiento_publicado()
        self.recibo.write({'state': 'done'})
        with self.assertRaisesRegex(UserError, 'not reconciliable'):
            self.recibo.action_register_payment()

    def test_pagar_con_una_cuenta_que_no_es_por_pagar_no_ofrece_lineas_en_el_asistente(self):
        """Obstáculo 2 del doc 64: cuenta de pasivo corriente (aunque fuera conciliable) -> «nothing left to pay»."""
        asiento = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': self.diario_nomina.id, 'date': date(2026, 3, 31),
            'line_ids': [
                (0, 0, {'account_id': self.gasto.id, 'debit': 1000.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.neto_pasivo.id, 'debit': 0.0, 'credit': 1000.0,
                        'partner_id': self.empleado.work_contact_id.id})]})
        asiento.action_post()
        with self.assertRaisesRegex(UserError, 'nothing left to pay'):
            self.env['account.payment.register'].with_context(
                active_model='account.move.line', active_ids=asiento.line_ids.ids).create({})

    def test_pagar_deja_el_recibo_en_hecho_sin_fecha_de_pago_y_la_fecha_sale_de_contabilidad(self):
        """«Pagar» NO escribe de vuelta al recibo (doc 53 §20.3 y texto nativo): estado y paid_date quedan como estaban."""
        self._cuenta_del_neto(self.regla_net, self.neto_por_pagar)
        asiento = self._asiento_publicado()
        self.recibo.write({'state': 'done'})
        linea = self._linea_de(asiento, self.neto_por_pagar)
        asistente = self.env['account.payment.register'].with_context(
            active_model='account.move.line', active_ids=linea.ids).create({
                'payment_date': date(2026, 4, 5), 'journal_id': self.banco.id})
        asistente._create_payments()
        self.assertEqual(self.recibo.state, 'done')
        self.assertFalse(self.recibo.paid_date)
        self.assertEqual(self.recibo._ne_fechas_pagos_contables(), [date(2026, 4, 5)])

    # ── con E-5 (orden: primero Pagar, luego Registrar fecha de pago) ──
    def test_registrar_la_fecha_de_pago_despues_de_pagar_pasa_el_recibo_a_pagado(self):
        self.company.l10n_co_ne_fuente_fecha_pago = 'recibo'
        self._cuenta_del_neto(self.regla_net, self.neto_por_pagar)
        asiento = self._asiento_publicado()
        self._pagar(self._linea_de(asiento, self.neto_por_pagar), self.empleado.work_contact_id, 900000.0, date(2026, 4, 5))
        self.recibo.write({'state': 'done'})
        self.env['hr.payslip.registrar.pago'].create({
            'payslip_ids': [(6, 0, self.recibo.ids)], 'fecha': date(2026, 4, 5)}).action_registrar_pago()
        self.assertEqual(self.recibo.state, 'paid')
        self.assertEqual(self.recibo.paid_date, date(2026, 4, 5))

    def test_pagar_un_recibo_ya_marcado_como_pagado_lo_rechaza_el_nativo(self):
        self._cuenta_del_neto(self.regla_net, self.neto_por_pagar)
        self._asiento_publicado()
        self.recibo.write({'state': 'paid'})
        with self.assertRaisesRegex(UserError, 'unpaid documents'):
            self.recibo.action_register_payment()
