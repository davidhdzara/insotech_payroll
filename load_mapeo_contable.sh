#!/bin/bash
# ================================================================
# Doc 23 §3 (mapeo contable), criterio CORREGIDO confirmado por Tech
# Lead: la mayoria de las categorias van de un solo lado (Devengados =
# solo debito, Deducciones = solo credito), NET carga el credito final
# que balancea el asiento (Salarios por pagar = Devengados - Deducciones).
# Solo Aportes Empresa y Provisiones llevan los 2 lados (son gasto Y
# obligacion nuevos, no pasan por el NET).
#
# CORRECCION EMPIRICA (verificada contra _prepare_slip_lines() real,
# sin ella el asiento queda desbalanceado): el signo del monto de la
# linea, no el nombre del campo, decide en que COLUMNA cae en la cuenta
# configurada. Para un monto NEGATIVO (toda linea de categoria
# Deducciones/SS Empleado en este modulo), account_credit produce un
# DEBITO (columna equivocada) y account_debit produce el CREDITO
# correcto -- exactamente al reves de lo intuitivo por el nombre del
# campo. Verificado en vivo: CO_SALUD_EMP con account_credit=238095
# generaba debit=23345.4/credit=0 (mal); con account_debit=238095
# genera debit=0/credit=23345.4 (correcto). Por eso todas las
# Deducciones/SS Empleado abajo usan account_debit (NO account_credit)
# apuntando a la MISMA cuenta de pasivo -- el campo es solo "la cuenta
# que usa esta regla", la columna la decide el signo del monto en
# tiempo de ejecucion, no la eleccion de debit vs credit aqui.
#
# Busca cada regla por CODE (no por xmlid) porque el mismo codigo (ej.
# CO_BASICO) existe como un hr.salary.rule DISTINTO por cada estructura
# (Nomina General/Prima/Liquidacion/Bonificaciones) -- hay que configurar
# TODAS las instancias de ese codigo, no solo una.
#
# Cuentas reales de Guapante, todas verificadas por SSH antes de este
# script (rango completo 510xxx + 25xxxx + 236xxx-238xxx). Decisiones de
# David aplicadas: 51xxxx (Administracion) como default, SENA/ICBF
# consolidados en 238095, embargos/libranzas en la cuenta nueva 239500
# (creada por load_cuenta_embargos.sh -- correr ESE script primero).
#
# SI commitea -- es carga de datos real (regla del proyecto: escrituras
# de produccion durante pruebas se dejan commiteadas para revision).
# ================================================================
set -e

odoo-bin shell -d guapante-staging-produccion-37396060 --no-http <<'PYEOF'
env = self.env
cr = env.cr
company = env.user.company_id
Account = env['account.account']
Rule = env['hr.salary.rule']

def acc(code):
    a = Account.search([('code', '=', code), ('company_ids', 'in', company.id)], limit=1)
    assert a, f"No se encontro la cuenta {code} -- ajustar el script"
    return a

# Cuentas reales usadas en el mapeo
A_SALARIOS = acc('510505')
A_SALARIOS_INTEGRALES = acc('510510')
A_HORAS_EXTRA = acc('510515')
A_COMISIONES = acc('510520')
A_AUX_TRANSPORTE = acc('510525')
A_CESANTIAS_GASTO = acc('510530')
A_INT_CESANTIAS_GASTO = acc('510535')
A_PRIMA_GASTO = acc('510540')
A_VACACIONES_GASTO = acc('510545')
A_ARL_GASTO = acc('510550')
A_SALUD_GASTO = acc('510555')
A_PENSION_GASTO = acc('510560')
A_CCF_GASTO = acc('510565')
A_ICBF_GASTO = acc('510570')
A_SENA_GASTO = acc('510575')
A_OTROS_GASTO = acc('510595')
A_PROVISIONES_GASTO = acc('519900')

A_SALARIOS_POR_PAGAR = acc('250505')
A_CESANTIAS_PASIVO = acc('251005')
A_INT_CESANTIAS_PASIVO = acc('251505')
A_PRIMA_PASIVO = acc('252005')
A_VACACIONES_PASIVO = acc('252505')
A_RETEFUENTE_SALARIOS = acc('236505')
A_FSP = acc('238001')
A_APORTES_CONSOLIDADO = acc('238095')  # EPS/AFP/ARL/CCF/SENA/ICBF, decision David
A_EMBARGOS = acc('239500')  # nueva, creada por load_cuenta_embargos.sh

# ================================================================
# Mapeo: code -> (debit_account_or_None, credit_account_or_None)
# ================================================================
MAPEO = {
    # ---- Devengados Salariales (solo debito) ----
    'CO_BASICO': (A_SALARIOS, None),
    'CO_COMISIONES': (A_COMISIONES, None),
    'CO_BONIF_SAL': (A_SALARIOS, None),
    'CO_VIATICOS_SAL': (A_SALARIOS, None),
    'CO_LIQ_SALARIOS': (A_SALARIOS, None),
    'CO_BON_VALOR': (A_SALARIOS, None),

    # ---- Horas Extra y Recargos (solo debito) ----
    'CO_HED': (A_HORAS_EXTRA, None),
    'CO_HEN': (A_HORAS_EXTRA, None),
    'CO_HRN': (A_HORAS_EXTRA, None),
    'CO_HEDDF': (A_HORAS_EXTRA, None),
    'CO_HENDF': (A_HORAS_EXTRA, None),
    'CO_HRDDF': (A_HORAS_EXTRA, None),
    'CO_HRNDF': (A_HORAS_EXTRA, None),

    # ---- Prestaciones Sociales, version REGULAR (SIN cuenta --
    # informativas, el efecto contable real ya lo cubre Provisiones) ----
    'CO_PRIMA': (None, None),
    'CO_CESANTIAS': (None, None),
    'CO_INT_CES': (None, None),
    'CO_PRIMA_BASE': (None, None),
    'CO_PRIMA_VALOR': (None, None),

    # ---- Prestaciones Sociales, version LIQUIDACION (debito contra el
    # pasivo acumulado -- se esta liquidando lo ya provisionado) ----
    'CO_LIQ_PRIMA': (A_PRIMA_PASIVO, None),
    'CO_LIQ_CESANTIAS': (A_CESANTIAS_PASIVO, None),
    'CO_LIQ_INT_CES': (A_INT_CESANTIAS_PASIVO, None),

    # ---- Vacaciones regular (SI son gasto real del periodo, a
    # diferencia de prima/cesantias -- se pagan cuando se disfrutan, no
    # se difieren) ----
    'CO_VAC': (A_VACACIONES_GASTO, None),
    'CO_VAC_COMP': (A_VACACIONES_GASTO, None),
    # Vacaciones en Liquidacion: debito contra el pasivo acumulado.
    'CO_LIQ_VACACIONES': (A_VACACIONES_PASIVO, None),

    # ---- Incapacidades y Licencias (sin cuenta propia en el PUC,
    # tratadas como Salarios) ----
    'CO_INC_COMUN': (A_SALARIOS, None),
    'CO_INC_LABORAL': (A_SALARIOS, None),
    'CO_LIC_MAT': (A_SALARIOS, None),
    'CO_LIC_PAT': (A_SALARIOS, None),
    'CO_LIC_REM': (A_SALARIOS, None),
    'CO_LIC_NR': (A_SALARIOS, None),

    # ---- Devengados No Salariales (sin cuenta 51xxxx dedicada excepto
    # auxilio transporte -- se usa 510595 "Otros" para el resto, catch-all
    # real del PUC, no inventado) ----
    'CO_AUX_TRANS': (A_AUX_TRANSPORTE, None),
    'CO_BONIF_NOSAL': (A_OTROS_GASTO, None),
    'CO_AUX_ALIM': (A_OTROS_GASTO, None),
    'CO_VIATICOS_NOSAL': (A_OTROS_GASTO, None),
    'CO_DOTACION': (A_OTROS_GASTO, None),
    'CO_TELETRABAJO': (A_OTROS_GASTO, None),
    'CO_APOYO_SOST': (A_OTROS_GASTO, None),
    'CO_BONIF_RET': (A_OTROS_GASTO, None),
    'CO_INDEMNIZ': (A_OTROS_GASTO, None),
    # CO_LIQ_INDEMNIZACION: NO provisionamos indemnizacion mensualmente
    # (no existe CO_PROV_INDEMNIZACION), asi que es un devengado NUEVO
    # en la liquidacion, no la liquidacion de un pasivo ya acumulado --
    # va a Otros (gasto), NO a 254000 (esa cuenta seria para una
    # provision que no existe en este modulo). Correccion respecto al
    # borrador original de doc 23 §3.
    'CO_LIQ_INDEMNIZACION': (A_OTROS_GASTO, None),

    # ---- Deducciones (efecto: solo credito al pasivo -- monto negativo,
    # por eso el campo usado es account_debit, ver nota de correccion
    # empirica arriba) ----
    'CO_RETEFUENTE': (A_RETEFUENTE_SALARIOS, None),
    'CO_PRIMA_RETE': (A_RETEFUENTE_SALARIOS, None),
    'CO_LIQ_RETE': (A_RETEFUENTE_SALARIOS, None),
    'CO_BON_RETE': (A_RETEFUENTE_SALARIOS, None),
    'CO_LIBRANZAS': (A_EMBARGOS, None),
    'CO_SINDICATO': (A_EMBARGOS, None),
    'CO_AFC': (A_EMBARGOS, None),
    'CO_PENSION_VOL': (A_EMBARGOS, None),
    'CO_COOPERATIVA': (A_EMBARGOS, None),
    'CO_EMBARGO': (A_EMBARGOS, None),
    'CO_PLAN_COMP': (A_EMBARGOS, None),
    'CO_EDUCACION': (A_EMBARGOS, None),
    'CO_OTRAS_DED': (A_EMBARGOS, None),

    # ---- Seguridad Social Empleado (efecto: solo credito al pasivo
    # consolidado -- monto negativo, mismo campo account_debit) ----
    'CO_SALUD_EMP': (A_APORTES_CONSOLIDADO, None),
    'CO_PENSION_EMP': (A_APORTES_CONSOLIDADO, None),
    'CO_FSP': (A_FSP, None),
    'CO_PRIMA_SALUD': (A_APORTES_CONSOLIDADO, None),
    'CO_PRIMA_PENSION': (A_APORTES_CONSOLIDADO, None),
    'CO_LIQ_SALUD': (A_APORTES_CONSOLIDADO, None),
    'CO_LIQ_PENSION': (A_APORTES_CONSOLIDADO, None),
    'CO_BON_SALUD': (A_APORTES_CONSOLIDADO, None),
    'CO_BON_PENSION': (A_APORTES_CONSOLIDADO, None),

    # ---- Aportes Empresa (ambos lados -- gasto Y obligacion nuevos) ----
    'CO_SALUD_CIA': (A_SALUD_GASTO, A_APORTES_CONSOLIDADO),
    'CO_PENSION_CIA': (A_PENSION_GASTO, A_APORTES_CONSOLIDADO),
    'CO_ARL_CIA': (A_ARL_GASTO, A_APORTES_CONSOLIDADO),
    'CO_CCF_CIA': (A_CCF_GASTO, A_APORTES_CONSOLIDADO),
    'CO_SENA_CIA': (A_SENA_GASTO, A_APORTES_CONSOLIDADO),
    'CO_ICBF_CIA': (A_ICBF_GASTO, A_APORTES_CONSOLIDADO),

    # ---- Provisiones Prestaciones Sociales (ambos lados -- accrual real) ----
    'CO_PROV_PRIMA': (A_PROVISIONES_GASTO, A_PRIMA_PASIVO),
    'CO_PROV_CESANTIAS': (A_PROVISIONES_GASTO, A_CESANTIAS_PASIVO),
    'CO_PROV_INT_CES': (A_PROVISIONES_GASTO, A_INT_CESANTIAS_PASIVO),
    'CO_PROV_VACACIONES': (A_PROVISIONES_GASTO, A_VACACIONES_PASIVO),

    # ---- NET / variantes (solo credito -- la linea que balancea) ----
    'CO_NETO': (None, A_SALARIOS_POR_PAGAR),
    'CO_PRIMA_NETO': (None, A_SALARIOS_POR_PAGAR),
    'CO_LIQ_NETO': (None, A_SALARIOS_POR_PAGAR),
    'CO_BON_NETO': (None, A_SALARIOS_POR_PAGAR),

    # CO_BRUTO: subtotal puro de Devengados (display), sin cuenta propia
    # -- ya cuenta cada devengado individual, darle cuenta duplicaria.
    'CO_BRUTO': (None, None),
}

updated = 0
skipped_no_change = 0
missing_codes = []

for code, (debit, credit) in MAPEO.items():
    rules = Rule.search([('code', '=', code), ('struct_id.country_id.code', '=', 'CO')])
    if not rules:
        missing_codes.append(code)
        continue
    vals = {
        'account_debit': debit.id if debit else False,
        'account_credit': credit.id if credit else False,
    }
    rules.with_company(company).write(vals)
    updated += len(rules)

cr.commit()

print(f"Reglas actualizadas: {updated}")
print(f"Codigos del mapeo sin ninguna regla real encontrada: {missing_codes}")

# Reglas nativas boilerplate (BASIC/GROSS/NET/etc) -- confirmar que
# siguen SIN cuenta, no se tocaron.
for code in ('BASIC', 'GROSS', 'NET', 'REIMBURSEMENT', 'DEDUCTION', 'ATTACH_SALARY', 'ASSIG_SALARY', 'CHILD_SUPPORT'):
    rules = Rule.search([('code', '=', code), ('struct_id.country_id.code', '=', 'CO')])
    for r in rules.with_company(company):
        assert not r.account_debit and not r.account_credit, \
            f"{code} (id {r.id}) NO deberia tener cuenta -- es boilerplate nativo sin usar"
print("Confirmado: reglas nativas boilerplate (BASIC/GROSS/NET/etc) siguen sin cuenta.")
PYEOF
