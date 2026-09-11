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
# Usa el MAPEO REAL ya cargado por load_cuenta_embargos.sh +
# load_mapeo_contable.sh (correr AMBOS antes de este script) -- ya NO
# usa una config temporal en CO_BASICO. Se abandono ese enfoque: dar a
# una regla que YA tiene cuenta de debito en el mapeo real (todo
# Devengado) TAMBIEN una cuenta de credito de prueba no "autobalancea"
# esa regla -- para un monto POSITIVO con ambas cuentas configuradas,
# el motor nativo SUMA el monto a AMBOS lados (no los cancela, es el
# mismo mecanismo que usa Aportes Empresa a proposito, con cuentas
# reales que empiezan en cero) -- si la regla ya tenia debito real
# configurado, agregarle un credito de prueba queda como una suma
# nueva de un solo lado, desbalanceando el asiento real. Se prueba
# directo contra el mapeo real en su lugar.
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
# doc 23 (incluye el manifest con el nuevo depends hr_payroll_account,
# y el fix de CO_BRUTO/CO_NETO) antes de correr este script. Requiere
# ademas que load_cuenta_embargos.sh y load_mapeo_contable.sh ya hayan
# corrido (commiteado) contra la misma base.
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
        # nivel de base de datos sin pasar por esas protecciones de la
        # ORM, y recupera la conexion si un error real de Postgres (no
        # solo un AssertionError de Python) dejo la transaccion
        # abortada para los tests siguientes.
        try:
            cr.rollback()
        except Exception:
            pass

company = env.user.company_id
struct_regular = env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_nomina')
struct_liq = env.ref('l10n_co_nomina_electronica.hr_payroll_structure_co_liquidacion')

Account = env['account.account']
acc_salarios = Account.search([('code', '=', '510505'), ('company_ids', 'in', company.id)], limit=1)
acc_salarios_por_pagar = Account.search([('code', '=', '250505'), ('company_ids', 'in', company.id)], limit=1)
assert acc_salarios, "No se encontro la cuenta real 510505 (Salarios) -- ajustar el script"
assert acc_salarios_por_pagar, "No se encontro la cuenta real 250505 (Salarios por pagar) -- ajustar el script"

contract = env['hr.contract'].search([
    ('state', '=', 'open'), ('company_id', '=', company.id),
], limit=1)
assert contract, "No hay contrato abierto real -- no se puede probar"
emp = contract.employee_id

def _make_payslip(name, date_from, date_to, struct=None):
    return env['hr.payslip'].create({
        'name': name,
        'employee_id': emp.id,
        'contract_id': contract.id,
        'struct_id': (struct or struct_regular).id,
        'date_from': date_from,
        'date_to': date_to,
    })

def _line_by_name(move, rule_name):
    return move.line_ids.filtered(lambda l: l.name == rule_name)

# ================================================================
# TEST A: confirmar 1 solo payslip real -- hoy no genera ningun
# asiento (silencioso). Con el fix debe generar exactamente 1
# account.move, balanceado, usando el mapeo real ya cargado (CO_BASICO
# debita 510505, CO_NETO acredita 250505 -- Salarios por pagar).
#
# El move queda en 'draft', NO 'posted' -- verificado contra el codigo
# nativo completo (_action_create_account_move()/_create_account_move()
# en hr_payroll_account/models/hr_payslip.py): no hay ningun
# action_post() en esa ruta. Es el patron estandar de separacion de
# funciones de Odoo (el contador revisa y contabiliza manualmente, no
# se auto-postea solo por confirmar la nomina) -- confirmado corriendo
# este mismo test contra el servidor real.
# ================================================================
def test_a():
    today = datetime.date.today()
    ps = _make_payslip('TEST Contabilidad A', today.replace(day=1), today)
    ps.compute_sheet()
    basico_line = ps.line_ids.filtered(lambda l: l.code == 'CO_BASICO')
    neto_line = ps.line_ids.filtered(lambda l: l.code == 'CO_NETO')
    assert basico_line and basico_line.total > 0, "CO_BASICO deberia tener un monto > 0 para probar el asiento"
    assert neto_line and neto_line.total > 0, "CO_NETO deberia tener un monto > 0 para probar el asiento"

    ps.action_payslip_done()

    assert ps.move_id, "El payslip deberia tener move_id seteado tras action_payslip_done()"
    move = ps.move_id
    assert move.state == 'draft', \
        f"El asiento nativo queda en 'draft' (Odoo no auto-postea), esta {move.state}"

    total_debit = sum(move.line_ids.mapped('debit'))
    total_credit = sum(move.line_ids.mapped('credit'))
    assert abs(total_debit - total_credit) < 0.01, \
        f"Asiento desbalanceado: debito={total_debit}, credito={total_credit}"

    debit_lines = move.line_ids.filtered(lambda l: l.account_id.id == acc_salarios.id and l.debit > 0)
    credit_lines = move.line_ids.filtered(lambda l: l.account_id.id == acc_salarios_por_pagar.id and l.credit > 0)
    assert debit_lines, f"No hay linea de debito en {acc_salarios.code} (CO_BASICO)"
    assert credit_lines, f"No hay linea de credito en {acc_salarios_por_pagar.code} (CO_NETO)"
test("1 solo payslip confirmado genera exactamente 1 asiento en draft y balanceado", test_a)

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
        assert move.state == 'draft', \
            f"El asiento nativo queda en 'draft' (Odoo no auto-postea), esta {move.state}"
        total_debit = sum(move.line_ids.mapped('debit'))
        total_credit = sum(move.line_ids.mapped('credit'))
        assert abs(total_debit - total_credit) < 0.01, \
            f"Asiento {move.name} desbalanceado: debito={total_debit}, credito={total_credit}"
test("2 payslips confirmados juntos: sin crash, 2 asientos separados y balanceados", test_b)

# ================================================================
# TEST C: cancelar un payslip con asiento en 'draft' (no 'posted',
# confirmado en test_a/test_b -- Odoo no auto-postea). Verificado
# contra el codigo nativo real (account_move.py::_unlink_or_reverse()):
# un move en estado 'draft' que _can_be_unlinked() y no esta protegido
# por audit-trail se ELIMINA directo (unlink()), no se reversa -- el
# reverso solo aplica a moves 'posted'/'cancel'.
# ================================================================
def test_c():
    today = datetime.date.today()
    ps = _make_payslip('TEST Contabilidad C', today.replace(day=1), today)
    ps.compute_sheet()
    ps.action_payslip_done()
    original_move = ps.move_id
    original_move_id = original_move.id
    assert original_move and original_move.state == 'draft'

    ps.action_payslip_cancel()

    assert ps.state == 'cancel', f"El payslip deberia quedar cancel, esta {ps.state}"
    assert not env['account.move'].browse(original_move_id).exists(), \
        "El asiento en draft deberia haberse eliminado directo (_unlink_or_reverse -> unlink()), no reversado"
    assert not ps.move_id, "El payslip no deberia seguir apuntando a un move eliminado"
test("Cancelar payslip con asiento en draft lo elimina (no lo reversa)", test_c)

# ================================================================
# TEST D: verifica el MAPEO REAL cargado por load_mapeo_contable.sh --
# 3 casos representativos del criterio corregido de doc 23 §3:
#   - Aportes Empresa (CO_SALUD_CIA): unico caso normal con AMBOS
#     lados (gasto 510555 + pasivo 238095), no pasa por el NET.
#   - Deduccion (CO_SALUD_EMP): efecto SOLO credito (238095) -- el
#     campo real usado es account_debit, no account_credit (correccion
#     empirica de signo, ver cabecera de load_mapeo_contable.sh: para
#     un monto NEGATIVO, account_debit produce la columna credito
#     correcta).
#   - Liquidacion (CO_LIQ_CESANTIAS): debito contra el PASIVO
#     acumulado (251005), liquidandolo -- no contra una cuenta de
#     gasto -- y CO_LIQ_NETO con el credito final (250505).
# ================================================================
def test_d():
    rule_salud_cia = env['hr.salary.rule'].search([
        ('code', '=', 'CO_SALUD_CIA'), ('struct_id', '=', struct_regular.id),
    ], limit=1)
    rule_salud_emp = env['hr.salary.rule'].search([
        ('code', '=', 'CO_SALUD_EMP'), ('struct_id', '=', struct_regular.id),
    ], limit=1)
    assert rule_salud_cia.with_company(company).account_debit and rule_salud_cia.with_company(company).account_credit, \
        "CO_SALUD_CIA deberia tener AMBOS campos configurados (mapeo real) -- corre load_mapeo_contable.sh primero"
    assert rule_salud_emp.with_company(company).account_debit and not rule_salud_emp.with_company(company).account_credit, \
        "CO_SALUD_EMP deberia tener SOLO account_debit configurado (mapeo real, correccion de signo) -- corre load_mapeo_contable.sh primero"

    today = datetime.date.today()
    ps = _make_payslip('TEST Contabilidad D - Regular', today.replace(day=1), today)
    ps.compute_sheet()
    ps.action_payslip_done()
    move = ps.move_id
    assert move, "El payslip deberia tener move_id"

    salud_cia_line = ps.line_ids.filtered(lambda l: l.code == 'CO_SALUD_CIA')
    salud_emp_line = ps.line_ids.filtered(lambda l: l.code == 'CO_SALUD_EMP')
    assert salud_cia_line.total > 0, "CO_SALUD_CIA deberia tener monto > 0 para probar el mapeo"
    assert salud_emp_line.total < 0, "CO_SALUD_EMP deberia tener monto NEGATIVO (es un descuento)"

    # Aportes Empresa: debito Y credito en cuentas distintas
    debit_move_line = _line_by_name(move, rule_salud_cia.name).filtered(lambda l: l.debit > 0)
    credit_move_line = _line_by_name(move, rule_salud_cia.name).filtered(lambda l: l.credit > 0)
    assert debit_move_line and debit_move_line.account_id.code == '510555', \
        "CO_SALUD_CIA deberia generar linea de debito en 510555"
    assert credit_move_line and credit_move_line.account_id.code == '238095', \
        "CO_SALUD_CIA deberia generar linea de credito en 238095"

    # Deduccion: efecto SOLO credito (columna), sin ninguna linea de
    # debito con ese nombre -- independiente de que el campo real usado
    # sea account_debit (ver nota arriba).
    dedu_lines = _line_by_name(move, rule_salud_emp.name)
    assert dedu_lines and all(l.credit > 0 and l.debit == 0 for l in dedu_lines), \
        "CO_SALUD_EMP deberia generar SOLO linea(s) de credito, ninguna de debito"
    assert dedu_lines.account_id.code == '238095', \
        "CO_SALUD_EMP deberia acreditar 238095"

    # Liquidacion: CO_LIQ_CESANTIAS liquida el pasivo acumulado (debito
    # contra 251005, NO contra una cuenta de gasto), CO_LIQ_NETO
    # credita Salarios por pagar.
    ps_liq = _make_payslip('TEST Contabilidad D - Liquidacion', contract.date_start, today, struct=struct_liq)
    ps_liq.compute_sheet()
    cesantias_line = ps_liq.line_ids.filtered(lambda l: l.code == 'CO_LIQ_CESANTIAS')
    neto_line = ps_liq.line_ids.filtered(lambda l: l.code == 'CO_LIQ_NETO')
    assert cesantias_line and cesantias_line.total > 0, "CO_LIQ_CESANTIAS deberia tener monto > 0"
    assert neto_line and neto_line.total > 0, "CO_LIQ_NETO deberia tener monto > 0"

    ps_liq.action_payslip_done()
    move_liq = ps_liq.move_id
    assert move_liq, "El payslip de liquidacion deberia tener move_id"

    rule_liq_cesantias = env['hr.salary.rule'].search([
        ('code', '=', 'CO_LIQ_CESANTIAS'), ('struct_id', '=', struct_liq.id),
    ], limit=1)
    rule_liq_neto = env['hr.salary.rule'].search([
        ('code', '=', 'CO_LIQ_NETO'), ('struct_id', '=', struct_liq.id),
    ], limit=1)

    cesantias_move_line = _line_by_name(move_liq, rule_liq_cesantias.name).filtered(lambda l: l.debit > 0)
    assert cesantias_move_line and cesantias_move_line.account_id.code == '251005', \
        "CO_LIQ_CESANTIAS deberia debitar 251005 (pasivo acumulado, liquidandolo), no una cuenta de gasto"

    neto_move_line = _line_by_name(move_liq, rule_liq_neto.name).filtered(lambda l: l.credit > 0)
    assert neto_move_line and neto_move_line.account_id.code == '250505', \
        "CO_LIQ_NETO deberia acreditar 250505 (Salarios por pagar)"
test("Mapeo real: Aportes Empresa (ambos lados), deduccion (efecto solo credito), liquidacion liquida pasivo acumulado", test_d)

# ================================================================
# RESULTADOS -- los payslips/moves de los 4 tests NUNCA se commitean,
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
