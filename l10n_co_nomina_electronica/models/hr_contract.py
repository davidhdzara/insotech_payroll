# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.

"""
Extensión de hr.version para Nómina Electrónica DIAN (Odoo 19; en Odoo 18 era hr.contract).

Agrega los campos requeridos por el nodo ``<Trabajador>`` del XML de nómina
electrónica que dependen del contrato laboral: tipo de contrato y si el
salario es integral. En v19 no existe ``hr.contract``: el contrato es un rango de
fechas (``contract_date_start/_end``) sobre ``hr.version``, que además es versionado
por fecha (``date_version``); los campos propios quedan versionados con él.

Referencia: Anexo Técnico – Documento Soporte de Pago de Nómina Electrónica
V1.0, sección 6.2.8, atributos TipoContrato y SalarioIntegral.
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round
from odoo.tools.misc import format_amount

from .res_company import NE_CLASES_RIESGO


def _ne_proponer_clase_riesgo(registro):
    """Propone la Clase de Riesgo ARL de la actividad elegida; el campo sigue editable. ``registro`` es la versión (``hr.version``) o la ficha (``hr.employee``), que expone los mismos
    campos por ``_inherits``: los ``onchange`` de la versión NO corren en el formulario del empleado, por eso los dos modelos llaman a la misma lógica."""
    actividad = registro.l10n_co_pila_actividad_economica
    if actividad:
        registro.l10n_co_pila_clase_riesgo = actividad.risk_class


def _ne_aviso_clase_riesgo_distinta(registro):
    """Aviso (sin bloquear) si la clase editada a mano no coincide con la de la actividad. ``registro``: versión o ficha, como en ``_ne_proponer_clase_riesgo``."""
    actividad = registro.l10n_co_pila_actividad_economica
    if actividad and registro.l10n_co_pila_clase_riesgo != actividad.risk_class:
        # ``_description_selection`` sirve en los dos modelos: en la ficha el campo es heredado y su ``selection`` no es una lista.
        etiquetas = dict(registro._fields['l10n_co_pila_clase_riesgo']._description_selection(registro.env))
        return {'warning': {
            'title': registro.env._('Clase de riesgo distinta a la de la actividad'),
            'message': registro.env._(
                'La actividad %(actividad)s está clasificada en %(esperada)s, pero el contrato '
                'tiene %(actual)s. Puede guardar, pero verifique que sea correcto.',
                actividad=actividad.display_name,
                esperada=etiquetas.get(actividad.risk_class, actividad.risk_class),
                actual=etiquetas.get(registro.l10n_co_pila_clase_riesgo, registro.l10n_co_pila_clase_riesgo or ''),
            ),
        }}


class HrVersion(models.Model):
    """Campos del contrato laboral (versión del empleado) para Nómina Electrónica DIAN."""

    _inherit = 'hr.version'

    # ──────────────────────────────────────────────────────────────────
    # Tipo de Contrato (codificación DIAN)
    # ──────────────────────────────────────────────────────────────────
    l10n_co_ne_contract_type = fields.Selection(
        selection=[
            ('1', 'Término Fijo'),
            ('2', 'Término Indefinido'),
            ('3', 'Obra o Labor'),
            ('4', 'Aprendizaje'),
            ('5', 'Prácticas o Pasantía'),
        ],
        string='Tipo de Contrato DIAN',
        help='Tipo de contrato laboral según la codificación del anexo '
             'técnico de nómina electrónica de la DIAN.\n'
             '• 1 - Término Fijo: con fecha de terminación definida.\n'
             '• 2 - Término Indefinido: sin fecha de terminación.\n'
             '• 3 - Obra o Labor: duración atada a una obra específica.\n'
             '• 4 - Aprendizaje: contrato de aprendizaje SENA.\n'
             '• 5 - Prácticas o Pasantía: vinculación por práctica académica.',
        groups='hr_payroll.group_hr_payroll_user',
    )

    # ──────────────────────────────────────────────────────────────────
    # Salario Integral
    # ──────────────────────────────────────────────────────────────────
    l10n_co_ne_integral_salary = fields.Boolean(
        string='Salario Integral',
        default=False,
        help='Indica si el trabajador devenga salario integral '
             '(Art. 132 CST). El salario integral incluye el factor '
             'prestacional y no genera derecho a auxilio de transporte, '
             'cesantías, intereses a las cesantías ni prima de servicios.\n'
             'Se refleja en el atributo SalarioIntegral del nodo '
             '<Trabajador> del XML.',
        groups='hr_payroll.group_hr_payroll_user',
    )


    # ──────────────────────────────────────────────────────────────────
    # PILA — Datos de Cotización
    # ──────────────────────────────────────────────────────────────────
    l10n_co_pila_tipo_cotizante = fields.Selection(
        selection=[
            ('01', '01 - Dependiente'),
            ('02', '02 - Servicio Doméstico'),
            ('03', '03 - Independiente'),
            ('04', '04 - Madre Comunitaria'),
            ('12', '12 - Aprendiz del SENA en etapa lectiva'),
            ('19', '19 - Aprendiz del SENA en etapa productiva'),
            ('21', '21 - Estudiante (Ley 789/2002)'),
            ('22', '22 - Profesor de establecimiento particular'),
            ('30', '30 - Dependiente entidades o universidades públicas'),
            ('31', '31 - Cooperado o precooperativa'),
            ('51', '51 - Trabajador de tiempo parcial'),
        ],
        string='Tipo Cotizante',
        help='Tipo de cotizante según tabla PILA.',
        groups='hr_payroll.group_hr_payroll_user',
    )
    l10n_co_pila_subtipo_cotizante = fields.Selection(
        selection=[
            ('00', '00 - No aplica'),
            ('01', '01 - Dependiente pensionado por vejez activo'),
            ('02', '02 - Independiente pensionado por vejez activo'),
        ],
        string='Subtipo Cotizante',
        groups='hr_payroll.group_hr_payroll_user',
    )
    l10n_co_pila_salario_variable = fields.Boolean(
        string='Salario Variable',
        default=False,
        help='Marcar si el trabajador tiene salario variable.',
        groups='hr_payroll.group_hr_payroll_user',
    )
    l10n_co_pila_clase_riesgo = fields.Selection(
        selection=NE_CLASES_RIESGO,
        string='Clase de Riesgo ARL',
        help='Solo si este contrato tiene una clase distinta de la general de la empresa '
             '(Nómina > Configuración > Ajustes). Vacío: se usa la general.',
        groups='hr_payroll.group_hr_payroll_user',
    )
    l10n_co_pila_centro_trabajo = fields.Char(
        string='Centro de Trabajo',
        help='Código del centro de trabajo para ARL. Vacío: se usa el general de la empresa '
             '(Nómina > Configuración > Ajustes).',
        groups='hr_payroll.group_hr_payroll_user',
    )
    l10n_co_pila_actividad_economica = fields.Many2one(
        'l10n.co.pila.ciiu',
        string='Actividad Económica ARL',
        domain="['|', ('date_end', '=', False), ('date_end', '>=', context_today().strftime('%Y-%m-%d'))]",
        help='Actividad económica del Decreto 768 de 2022 (busque por código o por descripción). '
             'Al elegirla se propone la Clase de Riesgo ARL de esa actividad.',
        groups='hr_payroll.group_hr_payroll_user',
    )
    l10n_co_pila_indicador_alto_riesgo = fields.Boolean(
        string='Alto Riesgo Pensional',
        default=False,
        help='Indica si el empleado aplica para pensión de alto riesgo.',
        groups='hr_payroll.group_hr_payroll_user',
    )
    l10n_co_pila_tarifa_especial_afp = fields.Char(
        string='Tarifa Especial AFP',
        help='Tarifa especial de AFP si aplica.',
        groups='hr_payroll.group_hr_payroll_user',
    )

    # ──────────────────────────────────────────────────────────────────
    # Piso del salario integral (CST art. 132 num. 2)
    # ──────────────────────────────────────────────────────────────────
    def _ne_validar_piso_integral(self, fecha=None):
        """Un contrato de salario integral no puede pagar menos del piso: l10n_co_piso_salario_
        integral_smmlv (13 SMMLV, 10 de salario + 30 % de factor prestacional) x SMMLV de la
        fecha. fecha: la del SMMLV; sin ella, la de inicio del contrato (``contract_date_start``: en
        v19 ``date_start`` es la vigencia de la VERSIÓN, no el ingreso; T2, doc 02,
        ``hr/models/hr_version.py:561-580``)."""
        # H-V19-14 (acceso): la marca, la fecha de ingreso y el salario son de usuarios de nómina (``groups``), pero la validación corre para quien cree o edite la versión (p. ej. un
        # responsable de Empleados sin nómina al dar de alta): se leen con sudo SOLO para validar el piso; no se escriben ni se devuelven.
        Parametro = self.env['hr.rule.parameter'].sudo()
        for contrato in self.sudo().filtered(
                lambda c: c.l10n_co_ne_integral_salary and c.company_id._ne_es_colombia()):
            fecha_smmlv = fecha or contrato.contract_date_start
            if not fecha_smmlv:
                continue
            veces = Parametro._get_parameter_from_code(
                'l10n_co_piso_salario_integral_smmlv', fecha_smmlv)
            smmlv = Parametro._get_parameter_from_code('l10n_co_smmlv', fecha_smmlv)
            piso = veces * smmlv
            moneda = contrato.company_id.currency_id
            salario = contrato.wage          # ``contrato`` ya va con sudo (ver arriba)
            if salario < piso:
                raise ValidationError(_(
                    "El contrato de %(empleado)s (versión vigente desde el %(version)s) es de salario "
                    "integral con un salario de %(salario)s, por debajo del piso de %(piso)s "
                    "(%(veces)s SMMLV de %(smmlv)s, vigente el %(fecha)s; CST art. 132). Corrija el "
                    "Salario del contrato o quite la marca \"Salario Integral\".",
                    empleado=contrato.employee_id.name or contrato.display_name,
                    version=contrato.date_version,
                    salario=format_amount(self.env, salario, moneda),
                    piso=format_amount(self.env, piso, moneda), veces=veces,
                    smmlv=format_amount(self.env, smmlv, moneda), fecha=fecha_smmlv))

    @api.model_create_multi
    def create(self, vals_list):
        contratos = super().create(vals_list)
        contratos._ne_validar_piso_integral()
        return contratos

    def write(self, vals):
        resultado = super().write(vals)
        if {'wage', 'l10n_co_ne_integral_salary', 'contract_date_start'} & set(vals):
            # Un cambio solo de salario se valida con el SMMLV de hoy; si se toca el ingreso o
            # la marca de integral, con el SMMLV de la fecha de inicio del contrato.
            solo_salario = 'wage' in vals and not {'l10n_co_ne_integral_salary', 'contract_date_start'} & set(vals)
            self._ne_validar_piso_integral(fields.Date.context_today(self) if solo_salario else None)
        return resultado

    def _ne_valor_obligatorio(self, campo):
        """Valor de un campo que el contrato debe tener: sin el, error claro (nunca se asume un
        tipo de contrato o de cotizante por defecto)."""
        self.ensure_one()
        valor = self[campo]
        if not valor:
            raise UserError(_(
                'El contrato de %(empleado)s (versión vigente desde el %(version)s) no tiene "%(campo)s". '
                'Elíjalo en el contrato (nunca se asume un valor por defecto).',
                empleado=self.employee_id.name or self.display_name, version=self.date_version,
                campo=self._fields[campo].string))
        return valor

    _NE_CAMPOS_OBLIGATORIOS_EN_PROCESO = (
        'l10n_co_ne_contract_type', 'l10n_co_pila_tipo_cotizante', 'l10n_co_pila_subtipo_cotizante')

    @api.constrains('contract_date_start', *_NE_CAMPOS_OBLIGATORIOS_EN_PROCESO)
    def _check_tipos_obligatorios_en_proceso(self):
        """Una versión colombiana CON contrato (``contract_date_start`` definida) exige tipo de
        contrato DIAN, tipo y subtipo de cotizante: no tienen valor por defecto (antes salian
        'indefinido', 'dependiente').

        Sustituto v19 de «En proceso»: en v18 la restricción valía para ``state == 'open'``, pero
        ``hr.version`` no tiene ``state`` (doc 02, T4); el contrato se deriva de las fechas.
        Decisión D-A, Tech Lead 2026-11-18."""
        # H-V19-14 (acceso): los tres campos y la fecha de ingreso son de usuarios de nómina; la restricción debe dar su error también a quien no lo es, así que se leen con sudo (el mensaje solo
        # nombra al empleado, la versión y los campos que faltan).
        for contrato in self.sudo():
            if not contrato.contract_date_start or not contrato.company_id._ne_es_colombia():
                continue
            faltan = [contrato._fields[c].string for c in self._NE_CAMPOS_OBLIGATORIOS_EN_PROCESO
                      if not contrato[c]]
            if faltan:
                raise ValidationError(_(
                    'El contrato de %(empleado)s (versión vigente desde el %(version)s) no puede tener '
                    'fecha de inicio del contrato sin: %(faltan)s. Complételos en la ficha del empleado '
                    '(pestaña Nómina, grupos «Contrato DIAN» y «PILA - Cotización»).',
                    empleado=contrato.employee_id.name or contrato.display_name,
                    version=contrato.date_version, faltan=', '.join(faltan)))

    def _ne_clase_riesgo(self):
        """Clase de riesgo ARL efectiva: la del contrato y, si no tiene, la general de la
        empresa. Única fuente para el aporte ARL y para PILA. Sin ninguna: UserError."""
        self.ensure_one()
        clase = self.l10n_co_pila_clase_riesgo or self.company_id.l10n_co_pila_clase_riesgo
        if not clase:
            raise UserError(_(
                'No hay Clase de Riesgo ARL para el contrato de %(employee)s: ni el contrato '
                '(ficha del empleado, pestaña Nómina, grupo «PILA - Cotización») ni la empresa %(company)s (Nómina > Configuración > Ajustes, '
                'bloque PILA) la tienen configurada.',
                employee=self.employee_id.name, company=self.company_id.name))
        return clase

    def _ne_horas_semanales(self):
        """Horas semanales del HORARIO DE TRABAJO de la versión: el campo NATIVO ``resource.calendar.hours_per_week`` de su calendario (v19, ``resource/models/resource_calendar.py:104-106``, lectura R1 del
        consultor). En un horario fijo lo calcula el nativo de las asistencias (``_get_hours_per_week``: solo las de trabajo, sin el almuerzo ni las secciones; en un horario de dos semanas, la suma de las dos / 2); en uno
        FLEXIBLE es el dato que la persona declaró. Se lee del calendario y no de ``hr.version.hours_per_week`` (ese relacionado lleva ``groups="hr.group_hr_user"``, ``hr_payroll/models/hr_version.py:39``).
        Cero si la versión no tiene calendario o no se declararon horas. Decisión del TL (22-nov): opción A (campo nativo) sobre repetir la suma propia de v18."""
        self.ensure_one()
        return self.resource_calendar_id.hours_per_week or 0.0

    def _ne_horas_laboradas_pila(self, dias, fecha):
        """Número de horas laboradas del registro tipo 2 de la PILA (campo 96; H-F2-02, decisión del TL del 22-nov, corregida por él mismo): UNA sola fuente, sin el 8 fijo de antes. Son las horas SEMANALES del horario de
        trabajo del contrato (``_ne_horas_semanales``) / 7 por los días cotizados ``dias`` (los de CCF/SENA/ICBF, ``CO_DIAS_PARAF``), redondeado a entero: la misma jornada de 42 h da 180 en 30 días trabaje 5 o 6 días a la
        semana (una fórmula de horas por día × días cotizados cuenta como trabajados los días de descanso). Sin horario o sin horas semanales (calendario sin asistencias ni horas declaradas), el campo va VACÍO: es opcional para la mayoría de los tipos
        de cotizante y no se inventa un valor. Si el tipo de cotizante del contrato es de los que lo exigen (parámetro ``l10n_co_pila_horas_laboradas_tipos``, p. ej. el 51 de tiempo parcial) y no hay de dónde sacarlo, error
        claro que nombra al empleado y qué completar. Devuelve un entero o ``''``. Con la opción A (v19) un horario flexible con las horas declaradas SÍ da el dato (v18 lo dejaba vacío). NO VERIFICADO: la lista de tipos que lo exigen (Resolución 980 de 2017, art. 2; texto consolidado del Anexo Técnico 2 sin leer) y
        qué espera el operador PILA en el campo."""
        self.ensure_one()
        semanales = self._ne_horas_semanales()
        if semanales > 0:
            return int(float_round(semanales / 7 * dias, precision_digits=0))
        try:
            exigidos = self.env['hr.rule.parameter']._get_parameter_from_code('l10n_co_pila_horas_laboradas_tipos', fecha)
        except UserError:
            raise UserError(_(
                'Falta el parámetro de nómina «Colombia: Tipos de Cotizante que Exigen las Horas Laboradas en la PILA» (código l10n_co_pila_horas_laboradas_tipos) para el %(fecha)s, que se necesita para '
                'armar el campo de horas laboradas de %(empleado)s. Actualice el módulo de nómina electrónica o créelo en Nómina > Configuración > Parámetros de reglas.',
                fecha=fecha, empleado=self.employee_id.name)) from None
        if self.l10n_co_pila_tipo_cotizante in exigidos:
            raise UserError(_(
                'El tipo de cotizante %(tipo)s de %(empleado)s exige el número de horas laboradas en la PILA (campo 96) y su versión del contrato vigente desde el %(version)s no tiene horas semanales: '
                'asigne un horario de trabajo o declare las horas de la semana del horario flexible.',
                tipo=self.l10n_co_pila_tipo_cotizante, empleado=self.employee_id.name or self.display_name, version=self.date_version))      # v19: la versión se nombra por su fecha (``hr.version.name`` no se leyó)
        return ''

    def _ne_centro_trabajo(self):
        """Centro de trabajo ARL efectivo (contrato -> empresa). Sin ninguno: UserError."""
        self.ensure_one()
        centro = self.l10n_co_pila_centro_trabajo or self.company_id.l10n_co_pila_centro_trabajo
        if not centro:
            raise UserError(_(
                'No hay Centro de Trabajo ARL para el contrato de %(employee)s: ni el contrato '
                '(ficha del empleado, pestaña Nómina, grupo «PILA - Cotización») ni la empresa %(company)s (Nómina > Configuración > Ajustes, '
                'bloque PILA) lo tienen configurado.',
                employee=self.employee_id.name, company=self.company_id.name))
        return centro

    @api.onchange('l10n_co_pila_actividad_economica')
    def _onchange_pila_actividad_economica(self):
        _ne_proponer_clase_riesgo(self)

    @api.onchange('l10n_co_pila_clase_riesgo')
    def _onchange_pila_clase_riesgo_vs_actividad(self):
        return _ne_aviso_clase_riesgo_distinta(self)


class HrEmployeeRiesgoArl(models.Model):
    """v19 (H-V19-14): la actividad y la clase de riesgo se editan en la ficha del empleado; misma lógica que en la versión."""

    _inherit = 'hr.employee'

    @api.onchange('l10n_co_pila_actividad_economica')
    def _onchange_pila_actividad_economica(self):
        _ne_proponer_clase_riesgo(self)

    @api.onchange('l10n_co_pila_clase_riesgo')
    def _onchange_pila_clase_riesgo_vs_actividad(self):
        return _ne_aviso_clase_riesgo_distinta(self)
