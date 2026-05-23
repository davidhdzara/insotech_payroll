#!/bin/bash
echo "=== Instalando hr_payroll_holidays ==="
odoo-bin --stop-after-init -d guapante-staging-dev-32580182 --http-interface=127.0.0.1 -i hr_payroll_holidays --log-level=warn 2>&1
echo "EXIT_CODE=$?"
