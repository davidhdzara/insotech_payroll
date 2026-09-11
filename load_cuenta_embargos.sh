#!/bin/bash
# ================================================================
# Doc 23 SS3: crea la cuenta contable real 239500 "Embargos y libranzas
# por pagar" en el plan de cuentas de Guapante -- David confirmo el
# codigo tal cual. Mismo tipo/naturaleza que 238095 (verificado antes
# de escribir este script: account_type='liability_current',
# reconcile=False, deprecated=False, sin tag_ids ni moneda propia).
#
# A diferencia de los test_*.sh de este ciclo, este script SI commitea
# -- es carga de datos real, no una prueba (regla del proyecto:
# escrituras de produccion durante pruebas se dejan commiteadas para
# revision, no se revierten solas).
#
# NO toca ninguna regla salarial todavia -- eso queda para el script de
# carga del mapeo completo, pendiente de que Tech Lead confirme la
# correccion de diseno que le mando por separado (debito/credito de un
# solo lado por regla en la mayoria de las categorias, no ambos lados
# como sugeria el borrador original de doc 23 SS3).
# ================================================================
set -e

odoo-bin shell -d guapante-staging-produccion-37396060 --no-http <<'PYEOF'
env = self.env
cr = env.cr
company = env.user.company_id
Account = env['account.account']

existing = Account.search([('code', '=', '239500'), ('company_ids', 'in', company.id)], limit=1)
if existing:
    print(f"La cuenta 239500 ya existe (id {existing.id}, '{existing.name}') -- no se crea de nuevo.")
else:
    ref_account = Account.search([('code', '=', '238095'), ('company_ids', 'in', company.id)], limit=1)
    assert ref_account, "No se encontro 238095 para copiar account_type/reconcile -- ajustar el script"

    new_account = Account.create({
        'code': '239500',
        'name': 'Embargos y libranzas por pagar',
        'account_type': ref_account.account_type,
        'reconcile': ref_account.reconcile,
        'company_ids': [(6, 0, company.ids)],
    })
    cr.commit()
    print(f"Cuenta 239500 creada: id={new_account.id}, account_type={new_account.account_type}, reconcile={new_account.reconcile}")

PYEOF
