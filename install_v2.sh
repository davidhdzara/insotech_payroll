#!/bin/bash
echo "=== Verifying selection values ==="
grep l10n_co_ne_dian_concept /home/odoo/src/user/l10n_co_nomina_electronica/data/hr_payroll_structure_data.xml | grep -oP '>\K[^<]+' | sort -u
echo "=== Installing module ==="
odoo-bin --stop-after-init -d guapante-staging-dev-32580182 --http-interface=127.0.0.1 -i l10n_co_nomina_electronica --log-level=warn 2>&1
echo "=== EXIT CODE: $? ==="
