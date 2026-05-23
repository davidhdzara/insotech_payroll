#!/bin/bash
echo "=== Buscando deferred_time_off_manager ==="
grep -rn 'deferred_time_off_manager' /home/odoo/src/enterprise/ /home/odoo/src/odoo/ 2>/dev/null | grep -v '.po:' | grep -v '.pyc' | head -20
echo "=== Estado de modulos relacionados ==="
psql -t -A -c "SELECT name, state FROM ir_module_module WHERE name IN ('hr_holidays','hr_holidays_attendance','hr_payroll_holidays') ORDER BY name"
echo "=== Dependencias de nuestro modulo ==="
psql -t -A -c "SELECT d.name FROM ir_module_module_dependency d JOIN ir_module_module m ON m.id=d.module_id WHERE m.name='l10n_co_nomina_electronica' ORDER BY d.name"
