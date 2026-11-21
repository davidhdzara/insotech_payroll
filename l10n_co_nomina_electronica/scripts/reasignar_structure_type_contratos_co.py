# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.

"""Script de UN SOLO USO -- NO se ejecuta solo (no vive en migrations/ a propósito).

Reasigna ``structure_type_id`` de las VERSIONES (v19: el contrato vive en ``hr.version``) de compañías
colombianas que quedaron con un tipo de estructura genérico (sin país), al tipo "Empleado Colombia" de este
módulo (``l10n_co_nomina_electronica.hr_payroll_structure_type_co``).

POR QUÉ HACE FALTA (causa raíz, leída por el Tech Lead en v18 el 2026-11-09 y confirmada para v19 en
``odoo/addons/hr/models/hr_version.py:548-550``): ``_compute_structure_type_id`` solo corrige un tipo si NO
hay uno o si el tipo tiene un país DISTINTO al de la compañía. Una versión que ya tiene el tipo genérico
("Employee", ``country_id`` vacío) nunca se vuelve a evaluar: ni instalar el módulo ni poner
``default_struct_id`` lo arregla. Por eso el fix del módulo (default_struct_id) es necesario
pero NO alcanza para versiones que ya existen.

ALCANCE (acotado a propósito -- no toca otras localizaciones):
- Solo versiones de compañías cuyo país (``partner_id.country_id``) es Colombia.
- Solo versiones cuyo ``structure_type_id`` es ``False`` o tiene ``country_id`` vacío
  (genérico). Un contrato con un tipo de OTRO país o con un tipo colombiano distinto no se
  toca. Se incluyen versiones archivadas (``active_test=False``).
- Idempotente: lo que ya apunta al tipo colombiano se omite.

USO (solo con autorización puntual de David sobre el ambiente que sea; NO en producción
sin su orden explícita):

    # 1) Simulación (por defecto): lista qué cambiaría y NO escribe nada.
    odoo-bin shell -d <base> --no-http --http-port=<libre> < reasignar_structure_type_contratos_co.py

    # 2) Aplicar (revise primero la simulación y tenga un respaldo de la base):
    APLICAR=1 odoo-bin shell -d <base> --no-http --http-port=<libre> < reasignar_structure_type_contratos_co.py

Notas: en el shell de Odoo.sh NO pase --addons-path (data_dir real: /home/odoo/data).
El script hace commit solo con APLICAR=1.
"""

import os

_XMLID = 'l10n_co_nomina_electronica.hr_payroll_structure_type_co'


def _reasignar(env, aplicar):
    tipo_co = env.ref(_XMLID)
    contratos = env['hr.version'].with_context(active_test=False).search([
        ('company_id.partner_id.country_id.code', '=', 'CO'),
        '|', ('structure_type_id', '=', False), ('structure_type_id.country_id', '=', False),
    ])
    print('Tipo destino: %s (id=%s)' % (tipo_co.display_name, tipo_co.id))
    print('Versiones (contratos) colombianas con tipo genérico o vacío: %d' % len(contratos))
    for c in contratos:
        print('  versión id=%s | %s | empleado=%s | tipo actual=%s | vigente desde=%s' % (
            c.id, c.display_name, c.employee_id.name,
            c.structure_type_id.display_name or '(vacío)', c.date_version))
    if aplicar and contratos:
        contratos.write({'structure_type_id': tipo_co.id})
        env.cr.commit()
        print('APLICADO y confirmado (commit) sobre %d versiones.' % len(contratos))
    else:
        print('SIMULACIÓN: no se escribió nada. Use APLICAR=1 para aplicar.')
    return contratos


# En "odoo-bin shell" la variable ``env`` ya existe.
_reasignar(env, aplicar=os.environ.get('APLICAR') == '1')  # noqa: F821
