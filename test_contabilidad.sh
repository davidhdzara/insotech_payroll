#!/bin/bash
# ================================================================
# Test exhaustivo: migracion al motor contable nativo (doc 23,
# resuelve la colision de _create_account_move entre nuestro
# hr_payslip_account.py (eliminado) y hr_payroll_account nativo).
#
# Verifica los 2 escenarios reales que hoy fallan:
# - Confirmar 1 solo payslip: hoy no genera NINGUN asiento, silencioso.
# - Confirmar 2+ payslips juntos: hoy revienta con
#   "ValueError: Expected singleton".
#
# Usa 2 cuentas reales del plan de Guapante (510505 Salarios /
# 250505 Salarios por pagar) configuradas TEMPORALMENTE en
# CO_BASICO.account_debit/account_credit para probar el mecanismo de
# punta a punta -- NO es el mapeo final de doc 23 SS3 (todavia
# pendiente de aprobacion de David), es solo la prueba tecnica de que
# el motor nativo genera el asiento correctamente una vez que
# CUALQUIER cuenta este configurada.
#
# IMPORTANTE -- leccion de test_provisiones.sh T7 (check_account_audit_trail):
# una vez que un account.move queda posted_before=True, Odoo protege su
# chatter permanentemente y button_draft()/unlink() fallan, COMMIT o no.
# Por eso este script NO llama cr.commit() en ningun punto, y NO intenta
# deshacer manualmente los moves/payslips creados -- se deja todo en la
# misma transaccion y se hace un unico cr.rollback() al final, que
# descarta todo a nivel de base de datos sin pasar por esas protecciones
# de la ORM.
#
# NOTA: /tmp/ne_params.tar.gz debe estar actualizado con el diff de
# doc 23 (incluye el manifest con el nuevo depends hr_payroll_account)
# antes de correr este script.
# ================================================================
set -e

# Extraer modulo
cd /home/odoo/src/user/l10n_co_nomina_electronica
rm -rf models/ views/ data/ wizard/ services/ tests/ security/ report/ static/ migrations/ __pycache__/
cd /home/odoo/src/user
tar xzf /tmp/ne_params.tar.gz -C l10n_co_nomina_electronica/

# Actualizar modulo
cd /home/odoo
odoo-bin -d guapante-staging-produccion-37396060 -u l10n_co_nomina_electronica --stop-after-init --no-http 2>&1 | tail -20

echo "========================================"
echo "  MODULO ACTUALIZADO - INICIANDO TESTS"
echo "========================================"

odoo-bin shell -d guapante-staging-produccion-37396060 --no-http <<'PYEOF'
import datetime

env = self.env
cr = env.cr
PASS = 0
FAIL = 0
results = []

def test(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        results.append(f"  [OK] {name}")
    except Exception as e:
        FAIL += 1
        results.append(f"  [FAIL] {name}: {e}")
        # cr.rollback() es seguro aca (a diferencia de button_draft()/
        # unlink() sobre un move posted_before=True, leccion T7 de
        # test_provisiones.sh) -- descarta la transaccion completa a
        # nivel de base de datos sin pasar por la ORM, y recupera la
        # conexion si un error real de Postgres (no solo un AssertionError
        # de Python) dejo la transaccion abortada para los tests
        # siguientes.
        try:
            cr.rollback()
        except Exception:
            pass

company = env.user.company_id
struct_regular = env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
rule_basico = env.ref('l10n_co_nomina_electronica.hr_salary_rule_co_basico')

Account = env['account.account']
debit_account = Account.search([('code', '=', '510505'), ('company_ids', 'in', company.id)], limit=1)
credit_account = Account.search([('code', '=', '250505'), ('company_ids', 'in', company.id)], limit=1)
assert debit_account, "No se encontro la cuenta real 510505 (Salarios) -- ajustar el script"
assert credit_account, "No se encontro la cuenta real 250505 (Salarios por pagar) -- ajustar el script"

contract = env['hr.contract'].search([
    ('state', '=', 'open'), ('company_id', '=', company.id),
], limit=1)
assert contract, "No hay contrato abierto real -- no se puede probar"
emp = contract.employee_id

# Configuracion TEMPORAL (no es el mapeo final de doc 23 SS3): ambas
# cuentas en la MISMA regla balancea automaticamente por linea, sin
# necesitar journal_id.default_account_id (que hoy esta vacio en el
# diario "Salarios", prerequisito real senalado en doc 23 SS4).
#
# A diferencia de los account.move que generan los tests (nunca se
# commitean, ver nota de test() arriba), esto SI se commitea: es un
# campo company_dependent normal en hr.salary.rule, sin ninguna
# proteccion tipo audit-trail -- se puede restaurar con un write()
# normal sin problema. Se commitea ANTES de correr los tests para que
# sobreviva si algun test falla y dispara el cr.rollback() del wrapper
# (que si no, tambien deshace esta config y hace fallar en cascada los
# tests siguientes).
rule_basico_company = rule_basico.with_company(company)
original_debit = rule_basico_company.account_debit
original_credit = rule_basico_company.account_credit
rule_basico_company.write({
    'account_debit': debit_account.id,
    'account_credit': credit_account.id,
})
cr.commit()

def _make_payslip(name, date_from, date_to):
    return env['hr.payslip'].create({
        'name': name,
        'employee_id': emp.id,
        'contract_id': contract.id,
        'struct_id': struct_regular.id,
        'date_from': date_from,
        'date_to': date_to,
    })

# ================================================================
# TEST A: confirmar 1 solo payslip real -- hoy no genera ningun
# asiento (silencioso). Con el fix debe generar exactamente 1
# account.move, posted, balanceado, con lineas en las 2 cuentas reales
# configuradas.
# ================================================================
def test_a():
    today = datetime.date.today()
    ps = _make_payslip('TEST Contabilidad A', today.replace(day=1), today)
    ps.compute_sheet()
    basico_line = ps.line_ids.filtered(lambda l: l.code == 'CO_BASICO')
    assert basico_line and basico_line.total > 0, "CO_BASICO deberia tener un monto > 0 para probar el asiento"

    ps.action_payslip_done()

    assert ps.move_id, "El payslip deberia tener move_id seteado tras action_payslip_done()"
    move = ps.move_id
    assert move.state == 'posted', f"El asiento deberia quedar posted, esta {move.state}"

    total_debit = sum(move.line_ids.mapped('debit'))
    total_credit = sum(move.line_ids.mapped('credit'))
    assert abs(total_debit - total_credit) < 0.01, \
        f"Asiento desbalanceado: debito={total_debit}, credito={total_credit}"

    debit_lines = move.line_ids.filtered(lambda l: l.account_id.id == debit_account.id and l.debit > 0)
    credit_lines = move.line_ids.filtered(lambda l: l.account_id.id == credit_account.id and l.credit > 0)
    assert debit_lines, f"No hay linea de debito en {debit_account.code}"
    assert credit_lines, f"No hay linea de credito en {credit_account.code}"
test("1 solo payslip confirmado genera exactamente 1 asiento posted y balanceado", test_a)

# ================================================================
# TEST B: confirmar 2 payslips JUNTOS (el caso que hoy revienta con
# ValueError: Expected singleton). company.batch_payroll_move_lines es
# False en la config real de Guapante -- nativo NO los agrupa, deben
# quedar 2 account.move separados, cada uno balanceado.
# ================================================================
def test_b():
    assert not company.batch_payroll_move_lines, \
        "Este test asume batch_payroll_move_lines=False (config real de Guapante) -- ajustar si cambio"

    today = datetime.date.today()
    ps1 = _make_payslip('TEST Contabilidad B1', today.replace(day=1), today)
    ps2 = _make_payslip('TEST Contabilidad B2', today.replace(day=1), today)
    (ps1 | ps2).compute_sheet()

    (ps1 | ps2).action_payslip_done()  # antes del fix: ValueError: Expected singleton

    assert ps1.move_id and ps2.move_id, "Ambos payslips deberian tener move_id seteado"
    assert ps1.move_id.id != ps2.move_id.id, \
        "Deberian quedar 2 account.move SEPARADOS (batch_payroll_move_lines=False), no 1 combinado"
    for move in (ps1.move_id, ps2.move_id):
        assert move.state == 'posted'
        total_debit = sum(move.line_ids.mapped('debit'))
        total_credit = sum(move.line_ids.mapped('credit'))
        assert abs(total_debit - total_credit) < 0.01, \
            f"Asiento {move.name} desbalanceado: debito={total_debit}, credito={total_credit}"
test("2 payslips confirmados juntos: sin crash, 2 asientos separados y balanceados", test_b)

# ================================================================
# TEST C: cancelar un payslip con asiento posted -- debe reversarlo
# (no eliminarlo, ya esta posted), mismo comportamiento nativo que
# _unlink_or_reverse() ya maneja.
# ================================================================
def test_c():
    today = datetime.date.today()
    ps = _make_payslip('TEST Contabilidad C', today.replace(day=1), today)
    ps.compute_sheet()
    ps.action_payslip_done()
    original_move = ps.move_id
    assert original_move and original_move.state == 'posted'

    ps.action_payslip_cancel()

    assert ps.state == 'cancel', f"El payslip deberia quedar cancel, esta {ps.state}"
    assert original_move.state == 'posted', \
        "El asiento original NO deberia eliminarse (ya estaba posted) -- debe quedar reversado, no borrado"
    reversal = env['account.move'].search([
        ('reversed_entry_id', '=', original_move.id),
    ], limit=1)
    assert reversal, "Deberia existir un asiento de reverso apuntando al original"
    assert reversal.state == 'posted', "El asiento de reverso deberia quedar posted"
test("Cancelar payslip con asiento posted lo reversa (no lo elimina)", test_c)

# ================================================================
# LIMPIEZA: restaurar CO_BASICO a su configuracion original (esto SI
# se commitea, es la config real de la regla, no un move posted).
# ================================================================
rule_basico_company.write({
    'account_debit': original_debit.id if original_debit else False,
    'account_credit': original_credit.id if original_credit else False,
})
cr.commit()

# ================================================================
# RESULTADOS -- los payslips/moves de los 3 tests NUNCA se commitean,
# se descartan con este rollback final (leccion T7 de
# test_provisiones.sh: un move posted_before=True bloquea
# button_draft()/unlink() incluso sin commit, asi que ni se intenta --
# cr.rollback() es seguro porque opera por debajo de la ORM).
# ================================================================
print()
print("=" * 60)
for r in results:
    print(r)
print()
print(f"  TOTAL: {PASS} PASS, {FAIL} FAIL de {PASS+FAIL}")
print("=" * 60)

cr.rollback()

PYEOF
