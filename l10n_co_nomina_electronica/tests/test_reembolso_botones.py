# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""Q-96 (.341): reembolsos con los botones reales, como administrador de nómina, sobre recibos calculados por las reglas y con su asiento (Procedimiento 2: así un recibo abierto del mes no frena el cálculo de otro).

Un reembolso solo anula un recibo con exactamente sus líneas en contrario; ese recibo no se elimina ni vuelve a borrador (tampoco desde su lote) mientras el reembolso no esté cancelado, y el lote sigue con los demás. La salida
que dan los mensajes (cancelar el reembolso) funciona también si está pagado, publicado o en un periodo bloqueado."""

from datetime import date

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

PREFIJO = 'l10n_co_nomina_electronica.'


@tagged('post_install', '-at_install')
class TestReembolsoBotones(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'l10n_co_pila_tipo_aportante': '1', 'l10n_co_pila_forma_presentacion': 'U', 'country_id': cls.env.ref('base.co').id, 'l10n_co_pila_clase_riesgo': '1',
            'l10n_co_ne_febrero_modo': 'real', 'l10n_co_ne_redondeo_dias': 'DOWN', 'name': 'Compañía Reembolso con Botones'})
        cls.env = cls.company.with_company(cls.company).env
        cls.env.user.groups_id = [Command.link(cls.env.ref('hr_payroll.group_hr_payroll_manager').id)]
        cls.env['l10n.co.retefuente.uvt'].create({'year': '2026', 'company_id': cls.company.id, 'procedure': '1'})

        def cuenta(code, name, tipo):
            return cls.env['account.account'].create({'code': code, 'name': name, 'account_type': tipo, 'company_ids': [(6, 0, [cls.company.id])]})
        cls.gasto = cuenta('510506', 'Sueldos reembolso', 'expense')
        cls.neto = neto = cuenta('250520', 'Neto reembolso', 'liability_payable')
        diario = cls.env['account.journal'].create({
            'name': 'Salarios reembolso', 'code': 'SLRB', 'type': 'general', 'company_id': cls.company.id, 'default_account_id': cuenta('519520', 'Ajuste reembolso', 'expense').id})
        cls.general = cls.env.ref(PREFIJO + 'hr_payroll_structure_co_nomina')
        cls.general.journal_id = diario
        Regla = cls.env['hr.salary.rule']
        Regla.search([('code', '=', 'NET'), ('struct_id', '=', cls.general.id)]).account_credit = neto
        Regla.search([('code', '=', 'CO_BASICO'), ('struct_id', '=', cls.general.id)]).account_debit = cls.gasto
        cls.tipo = cls.env['hr.payroll.structure.type'].create({'name': 'Reembolso con Botones', 'country_id': cls.env.ref('base.co').id})
        def usuario(login, *grupos):
            return cls.env['res.users'].with_context(no_reset_password=True).create({
                'name': login, 'login': login, 'company_id': cls.company.id, 'company_ids': [(6, 0, [cls.company.id])],
                'groups_id': [(6, 0, [cls.env.ref(grupo).id for grupo in ('base.group_user', 'hr_payroll.group_hr_payroll_manager') + grupos])]})
        # Sin correo a propósito. Cancelar un recibo con asiento exige además permiso de Contabilidad (regla del nativo).
        cls.administrador = usuario('ne_admin_reembolso', 'account.group_account_invoice')
        cls.solo_nomina = usuario('ne_solo_nomina_reembolso')
        cls.n = 0

    def setUp(self):
        super().setUp()
        for nombre in ('_ne_validar_pacto_no_salarial', '_ne_validar_afiliaciones'):          # ajenas a lo que se prueba
            self.patch(type(self.env['hr.payslip']), nombre, lambda s: None)

    # ── utilidades: todo por los botones, con el rol que los usa ─────
    def _contrato(self):
        type(self).n += 1
        empleado = self.env['hr.employee'].create({
            'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00', 'name': 'Reembolsado %s' % self.n, 'company_id': self.company.id, 'l10n_co_ne_payment_method': '10'})
        contrato = self.env['hr.contract'].create({
            'l10n_co_ne_retention_procedure': '2', 'l10n_co_ne_contract_type': '2', 'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00', 'name': 'Contrato Reembolsado %s' % self.n,
            'employee_id': empleado.id, 'company_id': self.company.id, 'structure_type_id': self.tipo.id, 'wage': 3000000.0, 'date_start': date(2026, 1, 1), 'state': 'open'})
        self.env['l10n.co.retefuente.procedure2'].create({'contract_id': contrato.id, 'semester_start': date(2026, 1, 1), 'fixed_percentage': 1.0, 'months_considered': 12})
        contrato.generate_work_entries(date(2026, 5, 1), date(2026, 5, 31))
        return contrato

    def _calculado(self, contrato, bono=0.0, **extra):
        type(self).n += 1
        vals = {'name': 'Recibo Botones %s' % self.n, 'employee_id': contrato.employee_id.id, 'contract_id': contrato.id, 'company_id': self.company.id, 'struct_id': self.general.id,
                'date_from': date(2026, 5, 1), 'date_to': date(2026, 5, 31)}
        if bono:
            vals['input_line_ids'] = [(0, 0, {'input_type_id': self.env.ref(PREFIJO + 'input_co_bonif_nosal').id, 'code': 'CO_BONIF_NOSAL', 'amount': bono})]
        recibo = self.env['hr.payslip'].create(dict(vals, **extra))
        recibo.compute_sheet()
        return recibo

    def _como(self, recibos):
        return recibos.with_user(self.administrador).with_company(self.company)

    def _confirmado(self, contrato, **extra):
        recibo = self._calculado(contrato, **extra)
        self._como(recibo).action_payslip_done()
        return recibo

    def _reembolsar(self, recibo, confirmar=True):
        accion = self._como(recibo).refund_sheet()
        reembolso = self.env['hr.payslip'].browse(accion['domain'][0][2])
        if confirmar:
            self._como(reembolso).action_payslip_done()
        return reembolso

    def _saldo_gasto(self):
        return sum(self.env['account.move.line'].search([('account_id', '=', self.gasto.id), ('parent_state', '=', 'posted')]).mapped('balance'))

    def _formulario(self, usuario):
        return self.env['hr.payslip'].with_user(usuario).get_view(self.env.ref('hr_payroll.view_hr_payslip_form').id, 'form')['arch']

    def _anulados_y_dudas(self, recibos):
        anulados, dudas = recibos._ne_reembolsos()
        return anulados, ' '.join(dudas)

    # ── el reembolso nativo de un recibo calculado ───────────────────
    def test_el_reembolso_nativo_de_un_recibo_calculado_coincide_exacto(self):
        recibo = self._confirmado(self._contrato(), bono=200000.0)
        reembolso = self._reembolsar(recibo)
        self.assertGreater(len(recibo._ne_huella_de_lineas()), 5, 'Premisa: recibo calculado por las reglas')
        self.assertEqual(reembolso._ne_huella_de_lineas(-1), recibo._ne_huella_de_lineas())
        self.assertEqual(recibo._ne_reembolsos(), (recibo, []))

    # ── la salida de los mensajes ────────────────────────────────────
    def test_el_administrador_cancela_el_reembolso_aunque_este_publicado_pagado_o_en_periodo_bloqueado(self):
        casos = (('asiento en borrador', False, False, False), ('publicado', True, False, False), ('publicado y pagado', True, True, False), ('periodo bloqueado', True, False, True))
        for nombre, publicado, pagado, bloqueado in casos:
            with self.subTest(nombre):
                recibo = self._confirmado(self._contrato())
                recibo.move_id.action_post()
                antes = self._saldo_gasto()
                reembolso = self._reembolsar(recibo)
                asiento = reembolso.move_id
                self.assertTrue(asiento, 'Premisa: el reembolso confirmado tiene su asiento')
                if publicado:
                    asiento.action_post()
                    self.assertNotAlmostEqual(self._saldo_gasto(), antes, delta=0.01)
                if pagado:
                    self._como(reembolso).action_payslip_paid()
                    with self.assertRaisesRegex(UserError, r'(?s)1\) quite el pago de .*id %s\) con su botón «Sin pagar».*2\) cancele ' % reembolso.id):
                        self._como(recibo).write({'state': 'draft'})
                    for boton in ('action_payslip_unpaid', 'action_payslip_cancel'):          # los dos botones existen para ese rol
                        self.assertIn('name="%s"' % boton, self._formulario(self.administrador))
                    self._como(reembolso).action_payslip_unpaid()
                    self.assertEqual(reembolso.state, 'done')
                if bloqueado:
                    self.company.sudo().fiscalyear_lock_date = date(2026, 5, 31)
                self._como(reembolso).action_payslip_cancel()
                self.assertEqual(reembolso.state, 'cancel')
                self.assertAlmostEqual(self._saldo_gasto(), antes, delta=0.01)
                self.assertEqual(recibo._ne_reembolsos(), (recibo.browse(), []))
                self.company.sudo().fiscalyear_lock_date = False

    def test_sin_permiso_de_contabilidad_el_nativo_no_deja_cancelar_un_reembolso_con_asiento(self):
        recibo = self._confirmado(self._contrato())
        reembolso = self._reembolsar(recibo)
        with self.assertRaises(AccessError):
            reembolso.with_user(self.solo_nomina).with_company(self.company).action_payslip_cancel()
        self.assertEqual(reembolso.state, 'done')
        with self.assertRaisesRegex(UserError, 'con permiso de Contabilidad si tiene asiento'):          # el mensaje avisa a quien no lo tiene
            recibo.with_user(self.solo_nomina).with_company(self.company).write({'state': 'draft'})
        self._como(reembolso).action_payslip_cancel()
        self.assertEqual(reembolso.state, 'cancel')

    def test_con_un_pago_contable_conciliado_la_salida_tambien_funciona(self):
        def cuenta(code, tipo, **extra):
            return self.env['account.account'].create(dict({'code': code, 'name': 'Reembolso %s' % code, 'account_type': tipo, 'company_ids': [(6, 0, [self.company.id])]}, **extra))
        valores = {'name': 'Banco reembolso', 'code': 'BNRB', 'type': 'bank', 'company_id': self.company.id, 'default_account_id': cuenta('111020', 'asset_cash').id}
        if 'suspense_account_id' in self.env['account.journal']._fields:
            valores['suspense_account_id'] = cuenta('111025', 'asset_current', reconcile=True).id
        banco = self.env['account.journal'].create(valores)
        banco.inbound_payment_method_line_ids.write({'payment_account_id': cuenta('111030', 'asset_current', reconcile=True).id})
        recibo = self._confirmado(self._contrato())
        recibo.move_id.action_post()
        antes = self._saldo_gasto()
        reembolso = self._reembolsar(recibo)
        reembolso.move_id.action_post()
        linea = reembolso.move_id.line_ids.filtered(lambda l: l.account_id == self.neto)
        self.assertTrue(linea.debit, 'Premisa: el reembolso deja el neto por cobrar al empleado')
        pago = self.env['account.payment'].create({
            'payment_type': 'inbound', 'partner_type': 'supplier', 'partner_id': linea.partner_id.id, 'amount': linea.debit, 'date': date(2026, 5, 31), 'journal_id': banco.id,
            'destination_account_id': self.neto.id})
        pago.action_post()
        (pago.move_id.line_ids.filtered(lambda l: l.account_id == self.neto) + linea).reconcile()
        self.assertTrue(linea.reconciled, 'Premisa: hay un pago conciliado')
        self._como(reembolso).action_payslip_paid()
        self._como(reembolso).action_payslip_unpaid()
        self._como(reembolso).action_payslip_cancel()
        self.assertEqual(reembolso.state, 'cancel')
        self.assertAlmostEqual(self._saldo_gasto(), antes, delta=0.01)
        self.assertTrue(pago.exists())          # el pago queda en Contabilidad, sin conciliar: no se borra
        self.assertEqual(recibo._ne_reembolsos(), (recibo.browse(), []))

    # ── eliminar o volver a borrador ─────────────────────────────────
    def test_ningun_camino_elimina_ni_vuelve_editable_un_recibo_con_reembolso(self):
        contrato = self._contrato()
        recibo = self._confirmado(contrato)
        reembolso = self._reembolsar(recibo, confirmar=False)          # basta con que exista sin cancelar
        mensaje = (r'(?s)No se puede eliminar ni volver a borrador .*id %s\).*tiene el reembolso .*id %s\).*En este orden: 1\) cancele .*id %s\) con su botón «Cancelar».*2\) decida sobre .*id %s\)'
                   % (recibo.id, reembolso.id, reembolso.id, recibo.id))
        for estado in ('draft', 'verify'):                              # sobre el recibo hecho, por escritura directa
            with self.subTest(escritura=estado), self.assertRaisesRegex(UserError, mensaje):
                self._como(recibo).write({'state': estado})
        self._como(recibo).action_payslip_cancel()                      # cancelar no cambia con la .341
        for nombre, camino in (('botón borrador', self._como(recibo).action_payslip_draft), ('eliminar', self._como(recibo).unlink)):
            with self.subTest(nombre), self.assertRaisesRegex(UserError, mensaje):
                camino()
        self.assertEqual((recibo.exists(), recibo.state), (recibo, 'cancel'))
        self._como(reembolso).action_payslip_cancel()                   # la salida que dice el mensaje
        self._como(recibo).action_payslip_draft()
        self.assertEqual(recibo.state, 'draft')
        self._como(recibo).unlink()
        self.assertFalse(recibo.exists())

    def test_la_marca_del_lote_no_abre_el_bloqueo(self):
        recibo = self._confirmado(self._contrato())
        self._reembolsar(recibo)
        con_marca = self._como(recibo).with_context(ne_lote_conserva_reembolsados=True)          # como la mandaría una llamada externa
        for vals in ({'state': 'draft'}, {'state': 'verify', 'name': 'Otro nombre'}):
            with self.subTest(vals=vals), self.assertRaisesRegex(UserError, 'tiene el reembolso'):
                con_marca.write(vals)
        con_marca.write({'state': 'verify'})          # con la marca ni siquiera hay error: simplemente no cambia
        self.assertEqual(recibo.state, 'done')
        self._como(recibo).action_payslip_cancel()
        for nombre, camino in (('botón borrador', con_marca.action_payslip_draft), ('eliminar', con_marca.unlink)):
            with self.subTest(nombre), self.assertRaisesRegex(UserError, 'tiene el reembolso'):
                camino()
        con_marca.write({'state': 'verify'})
        self.assertEqual((recibo.exists(), recibo.state), (recibo, 'cancel'))

    # ── el lote ──────────────────────────────────────────────────────
    def _lote(self, recibos):
        type(self).n += 1
        lote = self.env['hr.payslip.run'].create({'name': 'Lote reembolso %s' % self.n, 'date_start': date(2026, 5, 1), 'date_end': date(2026, 5, 31), 'company_id': self.company.id})
        recibos.payslip_run_id = lote
        return lote

    def test_generar_confirmar_y_validar_el_lote_siguen_para_los_demas(self):
        hecho = self._confirmado(self._contrato())
        self._reembolsar(hecho)
        cancelado = self._confirmado(self._contrato())
        self._reembolsar(cancelado)
        self._como(cancelado).action_payslip_cancel()
        normal = self._calculado(self._contrato())
        lote = self._lote(hecho | cancelado | normal)
        nuevo = self._contrato()
        self.env['hr.payslip.employees'].with_user(self.administrador).with_company(self.company).with_context(active_id=lote.id).create({
            'employee_ids': [(6, 0, nuevo.employee_id.ids)], 'structure_id': self.general.id}).compute_sheet()
        generado = lote.slip_ids - hecho - cancelado - normal
        self.assertEqual(len(generado), 1)
        todos = hecho | cancelado | normal | generado
        self.assertEqual(todos.mapped('state'), ['done', 'cancel', 'verify', 'verify'])
        self.assertIn('tiene el reembolso', ' '.join(cancelado.message_ids.mapped('body')))
        self._como(lote).action_confirm()
        self.assertEqual(todos.mapped('state'), ['done', 'cancel', 'verify', 'verify'])
        self._como(lote).action_validate()
        self.assertEqual(todos.mapped('state'), ['done', 'cancel', 'done', 'done'])
        self.assertEqual((hecho | cancelado)._ne_reembolsos(), (hecho | cancelado, []))

    def test_el_lote_no_vuelve_a_borrador_ni_se_elimina_con_recibos_reembolsados(self):
        cancelado = self._confirmado(self._contrato())
        reembolso = self._reembolsar(cancelado)
        self._como(cancelado).action_payslip_cancel()
        normal = self._calculado(self._contrato())
        lote = self._lote(cancelado | normal)
        mensaje = r'(?s)hay recibos reembolsados.*id %s\).*id %s\).*En este orden: 1\) cancele .*id %s\)' % (cancelado.id, reembolso.id, reembolso.id)
        with self.assertRaisesRegex(UserError, mensaje):
            self._como(lote).action_draft()
        self.assertEqual((cancelado.state, normal.state), ('cancel', 'verify'))
        self._como(normal).action_payslip_cancel()
        with self.assertRaisesRegex(UserError, mensaje):
            self._como(lote).unlink()
        self.assertEqual((lote.exists(), len(lote.slip_ids)), (lote, 2))
        self._como(reembolso).action_payslip_cancel()
        self._como(lote).unlink()
        self.assertFalse(cancelado.exists())

    def test_solo_se_protege_el_que_el_reembolso_podria_anular(self):
        contrato = self._contrato()
        distinto = self._calculado(contrato, bono=300000.0)             # creado antes, con otras líneas
        original = self._confirmado(contrato)
        reembolso = self._reembolsar(original)
        posterior = self._calculado(contrato)                           # idéntico, creado después del reembolso
        for nombre, recibo in (('otras líneas', distinto), ('creado después', posterior)):
            with self.subTest(nombre):
                self._como(recibo).action_payslip_cancel()
                self._como(recibo).action_payslip_draft()
                self._como(recibo).unlink()
                self.assertFalse(recibo.exists())
        self.assertEqual(original._ne_reembolsos(), (original, []))
        self.assertEqual(reembolso.state, 'done')

    # ── el escenario del consultor ───────────────────────────────────
    def test_sin_el_original_otro_recibo_con_otras_lineas_no_queda_anulado_y_la_salida_destraba(self):
        contrato = self._contrato()
        corregido = self._calculado(contrato, bono=200000.0)            # creado antes del reembolso
        original = self._confirmado(contrato)
        reembolso = self._reembolsar(original)
        self._como(original).action_payslip_cancel()
        self._como(corregido).compute_sheet()
        self._como(corregido).action_payslip_done()
        self.assertEqual(corregido._ne_reembolsos(), (corregido.browse(), []))
        with self.assertRaisesRegex(UserError, 'tiene el reembolso'):
            self._como(original).unlink()
        with self.subTest('un original eliminado antes de esta versión'):
            self.patch(type(original), '_ne_exigir_que_ningun_reembolso_lo_anule', lambda *args, **kwargs: None)
            original.unlink()
            anulados, dudas = self._anulados_y_dudas(corregido)
            self.assertFalse(anulados)
            for texto in ('no son exactamente las contrarias', 'id %s' % corregido.id, 'En este orden: 1) cancele «', 'sin eliminarlos'):
                self.assertIn(texto, dudas)
            self._como(reembolso).action_payslip_cancel()
            self.assertEqual(corregido._ne_reembolsos(), (corregido.browse(), []))

    def test_con_dos_identicos_la_duda_se_destraba_cancelando_el_reembolso(self):
        contrato = self._contrato()
        otro = self._calculado(contrato)                                # idéntico, creado antes del reembolso
        original = self._confirmado(contrato)
        reembolso = self._reembolsar(original)
        self._como(original).action_payslip_cancel()
        self._como(otro).compute_sheet()
        self._como(otro).action_payslip_done()
        self.assertEqual(otro._ne_huella_de_lineas(), original._ne_huella_de_lineas(), 'Premisa: son idénticos')
        anulados, dudas = self._anulados_y_dudas(original | otro)
        self.assertFalse(anulados)
        for texto in ('puede ser cualquiera', 'En este orden: 1) cancele «', 'sin eliminarlos'):
            self.assertIn(texto, dudas)
        self.assertNotIn('Elimine', dudas)
        with self.assertRaisesRegex(UserError, 'tiene el reembolso'):          # eliminarlo dejaría anulado al otro sin avisar
            self._como(original).unlink()
        self._como(reembolso).action_payslip_cancel()
        self.assertEqual((original | otro)._ne_reembolsos(), (original.browse(), []))
        self.assertEqual((original.state, otro.state), ('cancel', 'done'))

    def test_un_reembolso_modificado_no_anula_el_recibo(self):
        recibo = self._confirmado(self._contrato())
        reembolso = self._reembolsar(recibo, confirmar=False)
        linea = reembolso.line_ids.filtered(lambda l: l.code == 'CO_BASICO')
        linea.write({'total': linea.total / 2, 'amount': linea.amount / 2})          # devolución parcial digitada a mano
        self._como(reembolso).action_payslip_done()
        anulados, dudas = self._anulados_y_dudas(recibo)
        self.assertFalse(anulados)
        self.assertIn('no son exactamente las contrarias', dudas)
        self._como(reembolso).action_payslip_cancel()
        self.assertEqual(recibo._ne_reembolsos(), (recibo.browse(), []))
