# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.

"""Avisos del panel de Nomina ampliados (.180): el registro de aviso de parametros del anio en curso
esta en un bloque noupdate, asi que la actualizacion no reescribiria su codigo de evaluacion.
Se le quita la marca noupdate ANTES de cargar los datos, para que el -u lo actualice (idempotente)."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_model_data SET noupdate = false
        WHERE module = 'l10n_co_nomina_electronica'
          AND model = 'hr.payroll.dashboard.warning'
          AND name = 'hr_payroll_dashboard_warning_co_params_ano_actual'
          AND noupdate = true
    """)
    _logger.info('Aviso de parametros del anio: %s registro(s) liberados de noupdate.', cr.rowcount)
