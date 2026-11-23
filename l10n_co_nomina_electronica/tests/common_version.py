# -*- coding: utf-8 -*-
"""Fixtures de empleado con versión (Odoo 19) para las pruebas del módulo. NO ejecutado en Odoo.

En Odoo 18 las pruebas creaban un ``hr.employee`` y luego un ``hr.contract`` (``state='open'``, ``date_start``). En Odoo 19 no existe
``hr.contract``: el contrato es un rango de ``hr.version`` (``contract_date_start/_end``) y ``hr.employee`` hace
``_inherits = {'hr.version': 'version_id'}`` (``odoo/addons/hr/models/hr_employee.py:45``), así que los campos de la versión se pasan en el
``create`` del empleado y el marco crea la versión subyacente (``hr_employee.py:1409-1410``, texto en
``.claude/fuentes_odoo19_lectura/07_lecturas_bloque0a3_v19_2026-11-18.txt``, L5a).

Reglas de estos fixtures (lecturas L3 y L5 de ``fichas_entrega_v19/00_lecturas_v19.md``):
* ``date_version`` = ``contract_date_start`` = ``inicio``. ``date_version`` es obligatorio y su defecto es HOY
  (``odoo/addons/hr/models/hr_version.py:64``); ``date_start`` es ``max(date_version, contract_date_start)`` (``:561-580``). Si ``date_version``
  quedara en hoy, ``_get_version(date_from)`` de un recibo de un mes pasado caería en ``versions[0]`` (``hr_employee.py:566-576``).
* Sin ``state``: ``hr.version`` no tiene estado (T4 de ``odoo19_migracion/02_inventario_campos_hr_contract.md``).
* Siempre se pasa la fecha a ``_get_version``: su defecto se evalúa al importar (``hr_employee.py:566``).
* Los tres campos que exige la restricción D-A del módulo (tipo de contrato y tipo/subtipo de cotizante) van en el mismo ``create``, porque
  la restricción corre al crear la versión.
"""

# Campos de empleado y de contrato que las pruebas del módulo daban siempre igual (valores de ``test_provisiones_periodo`` y ``test_dias_por_asistencia``).
VALORES_COLOMBIA = {
    'l10n_co_ne_worker_type': '01', 'l10n_co_ne_worker_subtype': '00', 'l10n_co_ne_payment_method': '10',
    'l10n_co_ne_contract_type': '2', 'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00',
}


def crear_empleado_con_contrato(env, compania, wage, inicio, estructura_tipo, nombre='Empleado de prueba', fin=None, integral=False,
                                **valores):
    """Crea un empleado colombiano con su contrato (versión) y devuelve ``(empleado, version)``.

    ``inicio`` / ``fin``: ``contract_date_start`` / ``contract_date_end`` (``date_version`` = ``inicio``). ``integral``: se escribe DESPUÉS del
    ``create`` (como hacían las pruebas con ``hr.contract``), porque el piso del salario integral se valida al escribir. ``valores``
    sobrescribe cualquier otro campo (de empleado o de versión)."""
    vals = dict(VALORES_COLOMBIA)
    vals.update({
        'name': nombre, 'company_id': compania.id, 'wage': wage, 'structure_type_id': estructura_tipo.id,
        'date_version': inicio, 'contract_date_start': inicio})
    if fin:
        vals['contract_date_end'] = fin
    vals.update(valores)
    empleado = env['hr.employee'].create(vals)
    version = empleado._get_version(inicio)
    if integral:
        version.write({'l10n_co_ne_integral_salary': True})
    return empleado, version


# Tipos que la restricción D-A del módulo exige en cuanto una versión tiene ``contract_date_start`` (tipo de contrato y tipo/subtipo de cotizante).
TIPOS_CONTRATO_DEFECTO = {
    'l10n_co_ne_contract_type': '2', 'l10n_co_pila_tipo_cotizante': '01', 'l10n_co_pila_subtipo_cotizante': '00'}


def crear_contrato(env, vals, completar_tipos=True):
    """Equivalente v19 de ``env['hr.contract'].create(vals)`` de las pruebas de v18: devuelve la ``hr.version`` del contrato. NO ejecutado en Odoo.

    ``vals`` trae las claves de v18 y se traducen así (``hr.contract`` no existe en v19; ver el encabezado de este archivo):
    * ``employee_id`` (id o registro): el empleado. ``company_id`` se descarta y la compañía de la versión es la del empleado (en el ``create`` se fija explícita).
    * ``date_start`` -> ``date_version`` y, si el contrato es vigente o vencido, ``contract_date_start``. ``date_end`` -> ``contract_date_end``.
    * ``state``: ``hr.version`` no tiene estado (T4 de ``odoo19_migracion/02_inventario_campos_hr_contract.md``). ``'open'`` y ``'close'`` son contrato
      (llevan ``contract_date_start``); ``'draft'`` y ``'cancel'`` NO: la versión queda sin fechas de contrato, que es lo más cercano a «En proceso».
    * Si hay ``contract_date_start`` y faltan los tipos de la restricción D-A, se completan con ``TIPOS_CONTRATO_DEFECTO`` (``completar_tipos=True``).
      Las pruebas que comprueban justamente la AUSENCIA de esos tipos pasan ``completar_tipos=False``.
    * El resto de las claves (``wage``, ``structure_type_id``, ``name``, ``l10n_co_*``...) son campos de ``hr.version`` y pasan tal cual.

    El empleado ya trae una versión «vacía» (la crea el marco con el empleado, ``date_version`` = hoy). La primera llamada para un empleado la
    reutiliza (``write``); las siguientes crean otra ``hr.version`` (historial de contratos del mismo empleado). NO VERIFICADO: el ``create`` de
    ``hr.version`` ni su ``write`` (``hr_version.py``: cuerpo sin leer, ver el encabezado)."""
    vals = dict(vals)
    empleado = vals.pop('employee_id')
    if not hasattr(empleado, 'ids'):
        empleado = env['hr.employee'].browse(empleado)
    estado = vals.pop('state', 'open')
    vals.pop('company_id', None)
    inicio = vals.pop('date_start', None)
    fin = vals.pop('date_end', None)
    if inicio:
        vals['date_version'] = inicio
    if estado in ('open', 'close') and inicio:
        vals['contract_date_start'] = inicio
        if fin:
            vals['contract_date_end'] = fin
        for campo, valor in (TIPOS_CONTRATO_DEFECTO.items() if completar_tipos else ()):
            vals.setdefault(campo, valor)
    versiones = empleado.with_context(active_test=False).version_ids
    if len(versiones) == 1 and not versiones.contract_date_start:
        versiones.write(vals)
        return versiones
    vals['employee_id'] = empleado.id
    # ``hr.version.company_id`` es ``compute`` + ``default=env.company`` (``hr/models/hr_version.py:52-53``): al CREAR, el default gana y el compute no corre; sin esto la
    # versión nueva quedaba en la compañía actual y no en la del empleado (la «renovación» del pacto no encontraba la clase de riesgo ARL de la compañía del empleado).
    vals.setdefault('company_id', empleado.company_id.id)
    return env['hr.version'].create(vals)


def crear_usuario_nomina(env, compania, login):
    """Usuario OFICIAL de nómina (``hr_payroll.group_hr_payroll_user``, sin ``hr.group_hr_manager`` ni ``hr_payroll.group_hr_payroll_manager``)
    de ``compania``. Las pruebas corren como superusuario y esconden los AccessError de campos con grupos (``wage``, ``contract_date_*``:
    ``hr_payroll/models/hr_version.py:23-29``); el humo del motor se repite con ``recibo.with_user(este_usuario)``.

    El campo de grupos de ``res.users`` se llama ``groups_id`` en Odoo 18 y ``group_ids`` en Odoo 19: VERIFICADO el nombre en 19 (``ir_model_fields`` del servidor 42494857: ``res.users.group_ids``; solo
    se vio ``group_ids`` en acciones, ``odoo/addons/base/models/ir_actions.py:329``); se elige por ``_fields`` en vez de suponerlo."""
    campo_grupos = 'group_ids' if 'group_ids' in env['res.users']._fields else 'groups_id'
    return env['res.users'].with_context(no_reset_password=True).create({
        'name': 'Usuario de nómina %s' % login, 'login': login, 'email': '%s@example.com' % login,
        'company_id': compania.id, 'company_ids': [(6, 0, compania.ids)],
        campo_grupos: [(6, 0, [env.ref('base.group_user').id, env.ref('hr_payroll.group_hr_payroll_user').id])]})
