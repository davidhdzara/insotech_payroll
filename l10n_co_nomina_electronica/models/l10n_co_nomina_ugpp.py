# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.

"""
Modelo para generación de reportes UGPP – Storm User.

La UGPP (Unidad de Gestión Pensional y Parafiscales) requiere que las
empresas presenten información periódica sobre sus aportes a seguridad
social. Este modelo genera el archivo Excel con 3 hojas que alimenta
el aplicativo Storm User:

1. **nomina-aportante**: Información general del aportante (empresa).
2. **nomina-conceptos de pago**: Mapeo de reglas salariales a conceptos
   de pago UGPP con sus cuentas contables.
3. **nomina**: Detalle consolidado por empleado de los valores de nómina
   del período, con desglose de IBC y aportes.

Referencia: Manual Storm User – UGPP.
"""

import base64
import io
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services import dian_utils

_logger = logging.getLogger(__name__)

try:
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
except ImportError:
    openpyxl = None
    _logger.warning(
        'La librería openpyxl no está instalada. No se podrán generar '
        'los reportes UGPP en formato Excel.'
    )

# ──────────────────────────────────────────────────────────────────────────
# Constantes UGPP
# ──────────────────────────────────────────────────────────────────────────
# SMMLV – valor de respaldo si no está configurado en la empresa.


# Marco del libro Storm User: copia de la plantilla oficial ``Anexo_1.xlsx`` de la UGPP (Guía V-20.1 §1.3: no se
# cambia el nombre ni la estructura del archivo). Por hoja: nombre, formulario (preámbulo C2), su descripción (D2) y
# el título de la fila 8. Los nombres de hoja son los de la plantilla (la 2.ª, truncada a 31 caracteres por Excel).
_UGPP_HOJAS = {
    'aportante': ('Formulario Nómina - Aportante', 7001, 'Formulario Nómina - Aportante',
                  '0 Formulario Nómina - Aportante'),
    'conceptos': ('Formulario Nómina - Concepto...', 7003, 'Formulario Nómina - Concepto Pago Aportante ',
                  '0 Formulario Nómina - Concepto Pago Aportante'),
    'nomina': ('Formulario Nómina', 7002, 'Formulario Nómina', '0 Formulario Nómina'),
}
# Código de columna (fila 9) de la hoja ``nomina`` para las 32 primeras columnas fijas; las 3 siguientes de la
# plantilla (fechas de permiso, suspensión y huelga: 148/152/156) las agrega U5. Observaciones = 184; el concepto N
# de la plantilla = 276 + 4 × (N - 1).
_UGPP_COD_NOMINA = (8, 12, 16, 24, 28, 32, 36, 40, 52, 56, 60, 64, 68, 72, 76, 80, 84, 88, 92, 96, 100, 104, 108,
                    112, 116, 120, 124, 128, 132, 136, 140, 144)
_UGPP_COD_OBSERVACIONES = 184
_UGPP_COD_CONCEPTO_1 = 276
_UGPP_PRIMERA_FILA = 11


# Listas de la Guía UGPP V-20.1 para el formulario del aportante (7001). Clave = valor del campo de la compañía.
_UGPP_NATURALEZA = {
    'publica': 1, 'privada': 2, 'mixta': 3, 'organismo_multilateral': 4, 'publica_extranjera': 5,
}
_UGPP_TIPO_APORTANTE = {
    'empleador': 1, 'entidad_publica_especial': 3, 'agremiacion': 4, 'cooperativa': 5, 'mision_diplomatica': 6,
    'hogares_bienestar': 7, 'pagador_concejales': 8, 'pagador_sindical': 9, 'pagador_reincorporacion': 10,
    'pagador_magisterio': 11, 'pagador_humanitaria': 12,
}
# Tipo de documento del aportante (Guía p. 14): código DIAN del tipo de identificación del contacto de la compañía →
# código UGPP. Los códigos CD y SC no tienen equivalente en el catálogo DIAN del módulo: no se mapean por conjetura.
_UGPP_DOC_APORTANTE = {'31': 'NI', '13': 'CC', '22': 'CE', '12': 'TI', '41': 'PA', '47': 'PE'}

# Tipo de pago (formulario 7003, columna 19) y clasificación de pagos no salariales (columna 20): texto EXACTO de las
# listas de la plantilla ``Anexo_1.xlsx`` (número + nombre). Los tipos 12 a 15 (ingreso bruto, independiente, contratista,
# contratista ARL) son de independientes y no se cargan.
_UGPP_TIPO_PAGO = {
    'tp_salarial': '1 TP SALARIAL',
    'tp_no_salarial': '2 TP NO SALARIAL',
    'tp_compensacion_ord': '3 TP COMPENSACIÓN ORDINARIA',
    'tp_compensacion_ext': '4 TP COMPENSACIÓN EXTRAORDINARIA',
    'tp_no_compensacion': '5 TP NO COMPENSACIÓN',
    'tp_descanso_anual': '6 TP DESCANSO ANUAL',
    'tp_incapacidad': '7 TP INCAPACIDAD',
    'tp_vacaciones': '8 TP VACACIONES',
    'tp_vacaciones_terminacion': '9 TP VACACIONES TERMINACION DE CONTRATO',
    'tp_licencia_remunerada': '10 TP LICENCIA REMUNERADA',
    'tp_estudiantes': '11 TP A ESTUDIANTES O APRENDICES',
    'tp_licencia_mat_pat': '16 TP LICENCIA MAT O PAT',
    'tp_prestaciones': '17 TP PRESTACIONES',
}
_UGPP_CLASE_NO_SALARIAL = {
    'mera_liberalidad': '1 Mera liberalidad',
    'pacto_colectivo': '2 Pacto colectivo',
    'contrato': '3 Contrato',
    'otrosi': '4 Otrosí',
}
# Guía §1.3: "No utilice caracteres especiales (¡!"#$%&) en ninguno de los campos".
_UGPP_CARACTERES_PROHIBIDOS = dict.fromkeys(map(ord, '¡!"”“#$%&'), None)
_UGPP_MAX_CUENTAS = 200      # largo máximo del campo "cuenta contable" en la plantilla


# Mapeo de tipo de documento DIAN → código corto UGPP (columna del trabajador; U5 lo alinea con la lista de la Guía)
_DOC_TYPE_UGPP_MAP = {
    '13': 'CC',
    '22': 'CE',
    '12': 'TI',
    '41': 'PA',
    '11': 'RC',
    '21': 'TE',
    '31': 'NIT',
    '42': 'DIE',
    '47': 'PEP',
    '48': 'PPT',
    '50': 'NITP',
    '91': 'NUIP',
}


class L10nCoNominaUgpp(models.Model):
    """Generador de reportes UGPP para Storm User."""

    _name = 'l10n_co_nomina.ugpp'
    _check_company_auto = True
    _description = 'Reporte UGPP – Storm User'
    _order = 'year desc, month desc'

    # ──────────────────────────────────────────────────────────────────
    # Campos principales
    # ──────────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Nombre',
        compute='_compute_name',
        store=True,
        help='Nombre descriptivo del reporte UGPP.',
    )
    year = fields.Integer(
        string='Año',
        required=True,
        default=lambda self: fields.Date.today().year,
        help='Año del período a reportar.',
    )
    month = fields.Selection(
        selection=[
            ('1', 'Enero'),
            ('2', 'Febrero'),
            ('3', 'Marzo'),
            ('4', 'Abril'),
            ('5', 'Mayo'),
            ('6', 'Junio'),
            ('7', 'Julio'),
            ('8', 'Agosto'),
            ('9', 'Septiembre'),
            ('10', 'Octubre'),
            ('11', 'Noviembre'),
            ('12', 'Diciembre'),
        ],
        string='Mes',
        required=True,
        help='Mes del período a reportar.',
    )
    date_from = fields.Date(
        string='Fecha Inicio',
        required=True,
        help='Fecha de inicio del período de reporte.',
    )
    date_to = fields.Date(
        string='Fecha Fin',
        required=True,
        help='Fecha de fin del período de reporte.',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Empresa',
        required=True,
        default=lambda self: self.env.company,
        help='Empresa para la que se genera el reporte UGPP.',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Borrador'),
            ('generated', 'Generado'),
        ],
        string='Estado',
        default='draft',
        required=True,
        help='Estado del reporte. Cambia a "Generado" cuando se crea '
             'el archivo Excel exitosamente.',
    )
    excel_file = fields.Binary(
        string='Archivo Excel',
        readonly=True,
        help='Archivo Excel generado con las 3 hojas del reporte UGPP.',
    )
    excel_filename = fields.Char(
        string='Nombre Archivo Excel',
        readonly=True,
    )

    # ──────────────────────────────────────────────────────────────────
    # SQL Constraints
    # ──────────────────────────────────────────────────────────────────
    _sql_constraints = [
        (
            'unique_period_company',
            'UNIQUE(year, month, company_id)',
            'Ya existe un reporte UGPP para este período y empresa.',
        ),
    ]

    # ──────────────────────────────────────────────────────────────────
    # Campos computados
    # ──────────────────────────────────────────────────────────────────
    @api.depends('year', 'month', 'company_id')
    def _compute_name(self):
        """Genera nombre descriptivo: 'UGPP - Empresa - Mes Año'."""
        month_names = dict(self._fields['month'].selection)
        for record in self:
            company_name = record.company_id.name or ''
            month_name = month_names.get(record.month, '')
            record.name = 'UGPP - %s - %s %s' % (
                company_name, month_name, record.year or ''
            )

    # ──────────────────────────────────────────────────────────────────
    # Validaciones
    # ──────────────────────────────────────────────────────────────────
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        """Valida que la fecha inicio sea anterior a la fecha fin."""
        for record in self:
            if record.date_from and record.date_to:
                if record.date_from > record.date_to:
                    raise UserError(_(
                        'La fecha de inicio debe ser anterior o igual a '
                        'la fecha de fin.'
                    ))

    # ══════════════════════════════════════════════════════════════════
    # ACCIÓN PRINCIPAL: Generar reporte Excel
    # ══════════════════════════════════════════════════════════════════

    def action_generate_report(self):
        """
        Genera el archivo Excel UGPP con 3 hojas para Storm User.

        Flujo:
        1. Busca las nóminas confirmadas del período.
        2. Genera la hoja 'Formulario Nómina - Aportante' con datos de la empresa.
        3. Genera la hoja 'Formulario Nómina - Concepto...' con el mapeo de
           reglas salariales a conceptos UGPP.
        4. Genera la hoja 'Formulario Nómina' con el detalle consolidado por
           empleado.
        5. Guarda el archivo Excel en el campo binario.
        """
        self.ensure_one()

        if not openpyxl:
            raise UserError(_(
                'La librería openpyxl no está instalada. Ejecute: '
                'pip install openpyxl'
            ))

        # Buscar nóminas del período
        payslips = self.env['hr.payslip'].search([
            ('company_id', '=', self.company_id.id),
            # date_to y no date_from: la liquidacion tiene date_from = inicio de contrato
            # (H-017b); y los recibos pagados tambien se reportan.
            ('date_to', '>=', self.date_from),
            ('date_to', '<=', self.date_to),
            ('state', 'in', ('done', 'paid')),
            # doc 39 (2026-10-04): excluir empleados sintéticos del
            # wizard de habilitación DIAN -- nunca son personal real,
            # no deben contarse en un reporte UGPP real.
            ('employee_id.l10n_co_ne_is_habilitacion_test', '=', False),
        ])

        if not payslips:
            raise UserError(_(
                'No se encontraron nóminas confirmadas para el período '
                '%s - %s en la empresa %s.',
                self.date_from, self.date_to, self.company_id.name,
            ))

        # Crear workbook
        wb = openpyxl.Workbook()

        # Estilos
        header_font = Font(bold=True, color='FFFFFF', size=11)
        header_fill = PatternFill(
            start_color='4472C4', end_color='4472C4', fill_type='solid'
        )
        header_alignment = Alignment(
            horizontal='center', vertical='center', wrap_text=True
        )
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin'),
        )

        # ── Hoja 1: nomina-aportante ─────────────────────────────────
        ws_aportante = wb.active
        ws_aportante.title = _UGPP_HOJAS['aportante'][0]
        self._generate_sheet_aportante(
            ws_aportante, header_font, header_fill,
            header_alignment, thin_border,
        )

        # ── Hoja 2: nomina-conceptos de pago ─────────────────────────
        ws_conceptos = wb.create_sheet(_UGPP_HOJAS['conceptos'][0])
        self._generate_sheet_conceptos(
            ws_conceptos, header_font, header_fill,
            header_alignment, thin_border,
        )

        # ── Hoja 3: nomina ───────────────────────────────────────────
        ws_nomina = wb.create_sheet(_UGPP_HOJAS['nomina'][0])
        self._generate_sheet_nomina(
            ws_nomina, payslips, header_font, header_fill,
            header_alignment, thin_border,
        )

        # Guardar en memoria
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        # Almacenar archivo
        month_names = dict(self._fields['month'].selection)
        filename = 'UGPP_%s_%s_%s.xlsx' % (
            (self.company_id.vat or 'NIT').replace('-', ''),
            month_names.get(self.month, self.month),
            self.year,
        )

        self.write({
            'excel_file': base64.b64encode(output.read()),
            'excel_filename': filename,
            'state': 'generated',
        })

        _logger.info(
            'Reporte UGPP generado: %s (%d nóminas procesadas)',
            filename, len(payslips),
        )

        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/excel_file/%s?download=true' % (
                self._name.replace('.', '_'), self.id, filename,
            ),
            'target': 'new',
        }

    # ══════════════════════════════════════════════════════════════════
    # GENERACIÓN DE HOJAS INDIVIDUALES
    # ══════════════════════════════════════════════════════════════════

    def _ugpp_marco(self, ws, clave, columnas, header_font, header_fill, header_alignment, thin_border):
        """Escribe el marco de la plantilla Storm User (``Anexo_1.xlsx``) en la hoja ``ws`` y devuelve la primera fila
        de datos.

        Filas 1-6: preámbulo (tipo de modalidad 7000, formulario, moneda 1, NIT del aportante SIN dígito de
        verificación, fecha de corte = último día del periodo, periodicidad 0 Ocasional); fila 8: título; fila 9:
        código de cada columna (``None`` si la columna aún no existe en el formato); fila 10: encabezados; datos
        desde la fila 11 con el número de fila en A y ``FILA_n`` en B, y los valores desde la columna C.
        ``columnas``: lista de ``(código, encabezado)``. Nivel de verificación: copia de la estructura leída de la
        plantilla; que Storm User acepte un libro generado se prueba solo con Storm real (piloto)."""
        self.ensure_one()
        _nombre, formulario, descripcion, titulo = _UGPP_HOJAS[clave]
        nit = dian_utils.clean_nit(self.company_id.vat)
        preambulo = (
            ('Tipo Modalidad', 7000, 'Informe Nomina - UGPP'),
            ('Formulario', formulario, descripcion),
            ('Moneda Informe', 1, None),
            ('Entidad', int(nit) if nit.isdigit() else nit, None),
            ('Fecha', self.date_to, None),
            ('Periodicidad', 0, 'Ocasional'),
        )
        for fila, (etiqueta, valor, detalle) in enumerate(preambulo, 1):
            ws.cell(row=fila, column=2, value=etiqueta)
            celda = ws.cell(row=fila, column=3, value=valor)
            if fila == 5:
                celda.number_format = 'dd/mm/yyyy'
            if detalle:
                ws.cell(row=fila, column=4, value=detalle)
        ws.cell(row=8, column=1, value='[1]')
        ws.cell(row=8, column=2, value=titulo)
        for col_num, (codigo, encabezado) in enumerate(columnas, 3):
            if codigo is not None:
                ws.cell(row=9, column=col_num, value=codigo)
            cell = ws.cell(row=10, column=col_num, value=encabezado)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
        return _UGPP_PRIMERA_FILA

    def _ugpp_escribir_fila(self, ws, fila, valores, thin_border):
        """Una fila de datos del marco: número de fila en A, ``FILA_n`` en B y los valores desde la columna C."""
        n = fila - _UGPP_PRIMERA_FILA + 1
        ws.cell(row=fila, column=1, value=n)
        ws.cell(row=fila, column=2, value='FILA_%d' % n)
        for col_num, valor in enumerate(valores, 3):
            cell = ws.cell(row=fila, column=col_num, value=valor)
            cell.border = thin_border
            if isinstance(valor, float):
                cell.number_format = '#,##0.00'

    def _ugpp_datos_aportante(self):
        """Los 6 valores del aportante (formulario 7001) a partir de la compañía. Todos son obligatorios para la
        UGPP: lo que falte se pide con un error que nombra la compañía y dónde completarlo (sin valores por
        defecto)."""
        self.ensure_one()
        company = self.company_id
        faltan = []
        tipo_id = company.partner_id.l10n_latam_identification_type_id
        codigo_dian = tipo_id.l10n_co_ne_dian_document_code or ''
        tipo_doc = _UGPP_DOC_APORTANTE.get(codigo_dian)
        if not tipo_doc:
            faltan.append(_('un tipo de identificación del contacto de la compañía que tenga equivalente en la UGPP '
                            '(NIT, cédula, extranjería, tarjeta de identidad, pasaporte o PEP)'))
        numero = dian_utils.clean_nit(company.vat, strip_dv=(tipo_doc == 'NI'))
        if not numero:
            faltan.append(_('el número de identificación (NIT) de la compañía'))
        if company.l10n_co_ugpp_legal_nature not in _UGPP_NATURALEZA:
            faltan.append(_('la naturaleza jurídica'))
        if company.l10n_co_ugpp_contributor_type not in _UGPP_TIPO_APORTANTE:
            faltan.append(_('el tipo de aportante'))
        if faltan:
            raise UserError(_(
                'Para el reporte UGPP de la compañía "%(compania)s" falta: %(faltan)s. Complételo en Nómina > '
                'Configuración > Ajustes (bloque UGPP) o en el contacto de la compañía.',
                compania=company.display_name, faltan='; '.join(faltan)))
        return [
            tipo_doc,
            int(numero) if numero.isdigit() and tipo_doc in ('NI', 'CC', 'CE') else numero,
            company.name or '',
            _UGPP_NATURALEZA[company.l10n_co_ugpp_legal_nature],
            _UGPP_TIPO_APORTANTE[company.l10n_co_ugpp_contributor_type],
            self._ugpp_autoretencion(),
        ]

    def _ugpp_autoretencion(self):
        """'SI' o 'NO' del campo 28 del aportante (Guía p. 15: 'exonerado del pago de aportes parafiscales según el
        artículo 114-1 del ET'). Misma fuente que la exoneración de SENA/ICBF de la nómina y la PILA."""
        self.ensure_one()
        return 'SI' if self.company_id.l10n_co_ne_exoneration_1607 else 'NO'

    def _generate_sheet_aportante(
        self, ws, header_font, header_fill, header_alignment, thin_border
    ):
        """
        Genera la hoja del aportante (formulario 7001) con información de la empresa.

        Columnas:
        - Tipo Documento, Número Documento, Razón Social
        - Naturaleza Jurídica, Tipo Aportante
        - Autorretención Especial (exoneración del art. 114-1 ET)
        """
        # Los 6 campos del formulario 7001 (Guía V-20.1 §1.3.1) con el código de columna de la plantilla.
        headers = [
            (4, 'TIPO DOCUMENTO APORTANTE'),
            (8, 'NÚMERO DOCUMENTO APORTANTE'),
            (12, 'RAZÓN SOCIAL'),
            (16, 'NATURALEZA JURÍDICA'),
            (20, 'TIPO DE APORTANTE'),
            (28, 'AUTORRETENCIÓN ESPECIAL'),
        ]
        fila_datos = self._ugpp_marco(
            ws, 'aportante', headers, header_font, header_fill, header_alignment, thin_border)
        row_data = self._ugpp_datos_aportante()

        self._ugpp_escribir_fila(ws, fila_datos, row_data, thin_border)

        # Ajustar anchos
        for col in ws.columns:
            max_length = max(
                len(str(cell.value or '')) for cell in col
            )
            ws.column_dimensions[col[0].column_letter].width = (
                min(max_length + 2, 40)
            )

    def _ugpp_cuentas_regla(self, rule):
        """Códigos de las cuentas contables de la regla (débito y crédito, sin repetir) para la compañía del reporte,
        separados por ';'. Misma fuente que el asiento de nómina: no hay un campo aparte."""
        rule = rule.with_company(self.company_id)
        codigos = []
        for cuenta in (rule.account_debit, rule.account_credit):
            codigo = cuenta.with_company(self.company_id).code
            if codigo and codigo not in codigos:
                codigos.append(codigo)
        return ';'.join(codigos)

    def _ugpp_filas_conceptos(self, salary_rules):
        """Filas ``[concepto, nombre, cuentas, tipo de pago, clasificación]`` del formulario 7003. Todos los campos son
        obligatorios para la UGPP: las reglas a las que les falte algo se listan juntas en un solo error (sin valores
        por defecto)."""
        self.ensure_one()
        sin_cuenta, sin_clase, cuentas_largas = [], [], []
        filas = []
        for idx, rule in enumerate(salary_rules, 1):
            cuentas = self._ugpp_cuentas_regla(rule)
            if not cuentas:
                sin_cuenta.append(rule.display_name)
            elif len(cuentas) > _UGPP_MAX_CUENTAS:
                cuentas_largas.append(rule.display_name)
            clase = ''
            if rule.l10n_co_ugpp_payment_type == 'tp_no_salarial':
                clase = _UGPP_CLASE_NO_SALARIAL.get(rule.l10n_co_ugpp_non_salary_class, '')
                if not clase:
                    sin_clase.append(rule.display_name)
            filas.append([
                idx,
                (rule.name or '').translate(_UGPP_CARACTERES_PROHIBIDOS),
                cuentas,
                _UGPP_TIPO_PAGO[rule.l10n_co_ugpp_payment_type],
                clase,
            ])
        problemas = []
        if sin_cuenta:
            problemas.append(_('sin cuenta contable (débito o crédito) para la compañía "%(compania)s": %(reglas)s',
                               compania=self.company_id.display_name, reglas=', '.join(sin_cuenta)))
        if cuentas_largas:
            problemas.append(_('con las cuentas contables más largas de %(max)s caracteres: %(reglas)s',
                               max=_UGPP_MAX_CUENTAS, reglas=', '.join(cuentas_largas)))
        if sin_clase:
            problemas.append(_('TP NO Salarial sin clasificación: %s', ', '.join(sin_clase)))
        if problemas:
            raise UserError(_(
                'No se puede generar la hoja de conceptos del reporte UGPP. Reglas salariales %s. Corríjalo en '
                'Nómina > Configuración > Cuentas Contables por Regla y en la regla (Tipo de pago UGPP).',
                '; '.join(problemas)))
        return filas

    def _get_ugpp_salary_rules(self):
        """Retorna las reglas salariales con tipo de pago UGPP, ordenadas."""
        return self.env['hr.salary.rule'].search([
            ('l10n_co_ugpp_payment_type', '!=', False),
        ], order='sequence, code')

    def _generate_sheet_conceptos(
        self, ws, header_font, header_fill, header_alignment, thin_border
    ):
        """
        Genera la hoja de conceptos de pago (formulario 7003) según la Guía UGPP V-20.1.

        Columnas:
        1. Concepto (auto-numerado)
        2. Nombre concepto
        3. Cuenta contable
        4. Tipo pago
        5. Clasificación TP NO SALARIAL
        """
        headers = [
            (4, 'Concepto'),
            (8, 'Nombre concepto'),
            (12, 'Cuenta contable'),
            (19, 'Tipo pago'),
            (20, 'Clasificación TP NO SALARIAL'),
        ]
        fila_datos = self._ugpp_marco(
            ws, 'conceptos', headers, header_font, header_fill, header_alignment, thin_border)

        salary_rules = self._get_ugpp_salary_rules()
        filas = self._ugpp_filas_conceptos(salary_rules)
        for idx, row_data in enumerate(filas, 1):
            self._ugpp_escribir_fila(ws, fila_datos + idx - 1, row_data, thin_border)

        # Ajustar anchos
        for col in ws.columns:
            max_length = max(
                len(str(cell.value or '')) for cell in col
            )
            ws.column_dimensions[col[0].column_letter].width = (
                min(max_length + 2, 50)
            )

    # ──────────────────────────────────────────────────────────────────
    # IBC Calculation
    # ──────────────────────────────────────────────────────────────────

    # ──────────────────────────────────────────────────────────────────
    # Hoja 3: nomina – UGPP Storm User V-20.1
    # ──────────────────────────────────────────────────────────────────

    @api.model
    def _dias_ugpp(self, consolidado):
        """Días del empleado-mes para las columnas 19-26 del reporte.

        Total = ``consolidado.dias_sp`` (misma fuente que PILA). Cada novedad se suma de las
        mismas funciones de días que usan las reglas de nómina y PILA, sobre los recibos del
        consolidado; los días trabajados son lo que resta del total (sin negativos).
        ``huelga`` no tiene fuente en el módulo y queda en 0."""
        dias = dict.fromkeys(
            ('incapacidad', 'lic_mat', 'lic_rem', 'suspension', 'vacaciones', 'huelga'), 0)
        for slip in consolidado.payslip_ids:
            for codigo in ('CO_INC_COMUN', 'CO_INC_LABORAL'):
                dias['incapacidad'] += slip._ne_ausencia_calendario(codigo)[0]
            for codigo in ('CO_LIC_MAT', 'CO_LIC_PAT'):
                dias['lic_mat'] += slip._ne_ausencia_calendario(codigo)[0]
            dias['suspension'] += slip._ne_dias_sln()
            for wd in slip.worked_days_line_ids:
                codigo = wd.work_entry_type_id.code
                if codigo == 'CO_LIC_REM':
                    dias['lic_rem'] += wd.number_of_days
                elif codigo == 'CO_VAC':
                    dias['vacaciones'] += wd.number_of_days
        dias = {k: int(v) for k, v in dias.items()}
        total = int(consolidado.dias_sp)
        dias['total'] = total
        dias['trabajados'] = max(0, total - sum(
            v for k, v in dias.items() if k != 'total'))
        return dias

    def _generate_sheet_nomina(
        self, ws, payslips, header_font, header_fill,
        header_alignment, thin_border
    ):
        """
        Genera la hoja 'nomina' según la guía UGPP Storm User V-20.1.

        Estructura de columnas:
        - 33 columnas fijas (datos del cotizante, novedades, días, fechas)
        - N columnas dinámicas (una por regla salarial con tipo UGPP)
        - 4 columnas IBC (Salud, Pensión, ARL, CCF)
        """
        # ── Columnas fijas ───────────────────────────────────────────
        fixed_headers = [
            'Tipo cotizante',                           # 1
            'Subtipo cotizante',                        # 2
            'Condición especial empresa',               # 3
            'Extranjero no obligado pensión',           # 4
            'Colombiano en el exterior',                # 5
            'Actividad alto riesgo pensión',            # 6
            'Tipo documento cotizante',                 # 7
            'Número documento cotizante',               # 8
            'Nombre cotizante',                         # 9
            'Cargo del trabajador',                     # 10
            'Año',                                      # 11
            'Mes',                                      # 12
            'Salario integral',                         # 13
            'Novedad incapacidad',                      # 14
            'Novedad licencia mat o pat',               # 15
            'Novedad permiso o licencia remunerada',    # 16
            'Novedad de suspensión',                    # 17
            'Novedad vacaciones',                       # 18
            'Número días trabajados',                   # 19
            'Número días incapacidades',                # 20
            'Número días licencia mat o pat',           # 21
            'Número días permiso o lic remuneradas',    # 22
            'Número días suspensión/lic no remunerada', # 23
            'Número días vacaciones',                   # 24
            'Número días huelga',                       # 25
            'Total días reportados',                    # 26
            'Ingreso',                                  # 27
            'Fecha ingreso',                            # 28
            'Retiro',                                   # 29
            'Fecha retiro',                             # 30
            'Fecha inicio vacaciones',                  # 31
            'Fecha terminación vacaciones',             # 32
            'Observaciones aportante',                  # 33
        ]

        # ── Columnas dinámicas (conceptos de pago) ───────────────────
        ugpp_rules = self._get_ugpp_salary_rules()
        concept_headers = [rule.name or rule.code or '' for rule in ugpp_rules]

        # ── Columnas IBC ─────────────────────────────────────────────
        ibc_headers = ['IBC Salud', 'IBC Pensión', 'IBC ARL', 'IBC CCF']

        all_headers = fixed_headers + concept_headers + ibc_headers
        # Códigos de columna de la plantilla; None = columna que el formato no tiene (las 4 de IBC: U5 las retira).
        codigos = (list(_UGPP_COD_NOMINA) + [_UGPP_COD_OBSERVACIONES]
                   + [_UGPP_COD_CONCEPTO_1 + 4 * i for i in range(len(concept_headers))]
                   + [None] * len(ibc_headers))
        fila_datos = self._ugpp_marco(
            ws, 'nomina', list(zip(codigos, all_headers)), header_font, header_fill, header_alignment, thin_border)

        # ── Preparar mapeos ──────────────────────────────────────────
        period_start = self.date_from
        period_end = self.date_to

        # ── Iterar nóminas ───────────────────────────────────────────
        row_num = fila_datos
        ibc_reportados = set()
        for payslip in payslips.sorted(
            key=lambda p: (p.employee_id.name, p.number or '')
        ):
            employee = payslip.employee_id
            contract = payslip.contract_id

            # -- Totales por tipo de pago UGPP -------------------------
            total_salarial = 0.0
            total_no_salarial = 0.0

            # Acumular monto por regla salarial (rule.id → total)
            rule_totals = {}
            for line in payslip.line_ids:
                rule = line.salary_rule_id
                ugpp_type = rule.l10n_co_ugpp_payment_type
                if ugpp_type:
                    rule_totals[rule.id] = (
                        rule_totals.get(rule.id, 0.0) + line.total
                    )
                    if ugpp_type == 'tp_salarial':
                        total_salarial += line.total
                    elif ugpp_type == 'tp_no_salarial':
                        total_no_salarial += line.total
                    elif ugpp_type in (
                        'tp_compensacion_ord', 'tp_compensacion_ext',
                    ):
                        # Compensaciones son salariales para IBC
                        total_salarial += line.total

            # -- Días e IBC: del consolidado mensual (H-017b / UGPP días) ----
            # El consolidado es por empleado y mes: PILA, nómina y este reporte comparten la
            # misma fuente. Si hay varios recibos, días e IBC van solo en la primera fila de
            # ese empleado y mes; las siguientes en 0 para no duplicar.
            clave_ibc = (employee.id, payslip.date_to.strftime('%Y-%m'))
            if clave_ibc in ibc_reportados:
                ibc_data = [0.0, 0.0, 0.0, 0.0]
                dias = dict.fromkeys(
                    ('trabajados', 'incapacidad', 'lic_mat', 'lic_rem', 'suspension',
                     'vacaciones', 'huelga', 'total'), 0)
            else:
                consolidado = self.env['l10n.co.ibc.mensual']._refrescar(
                    payslip.company_id, employee, payslip.date_to)
                if not consolidado:
                    raise UserError(_(
                        'No hay IBC consolidado para %(empleado)s en %(mes)s: ningun '
                        'recibo confirmado trae las lineas de IBC. Recalcule y confirme '
                        'la nomina.',
                        empleado=employee.name, mes=payslip.date_to.strftime('%Y-%m')))
                ibc_reportados.add(clave_ibc)
                ibc_data = [consolidado.ibc_sp, consolidado.ibc_sp,
                            consolidado.ibc_arl, consolidado.ibc_paraf]
                dias = self._dias_ugpp(consolidado)

            dias_trabajados = dias['trabajados']
            dias_incapacidad = dias['incapacidad']
            dias_licencia_mat = dias['lic_mat']
            dias_lic_remunerada = dias['lic_rem']
            dias_suspension = dias['suspension']
            dias_vacaciones = dias['vacaciones']
            dias_huelga = dias['huelga']
            total_dias = dias['total']

            # -- Novedades (X / vacío) ---------------------------------
            nov_incapacidad = 'X' if dias_incapacidad > 0 else ''
            nov_lic_mat = 'X' if dias_licencia_mat > 0 else ''
            nov_lic_rem = 'X' if dias_lic_remunerada > 0 else ''
            nov_suspension = 'X' if dias_suspension > 0 else ''
            nov_vacaciones = 'X' if dias_vacaciones > 0 else ''

            # -- Nombre: APELLIDO1 APELLIDO2 NOMBRE1 NOMBRE2 -----------
            name_parts = employee._l10n_co_nombre_dian()
            nombre_cotizante = ' '.join(filter(None, [
                name_parts.get('primer_apellido', ''),
                name_parts.get('segundo_apellido', ''),
                name_parts.get('primer_nombre', ''),
                name_parts.get('otros_nombres', ''),
            ]))

            # -- Tipo documento → código corto UGPP --------------------
            # UX-02 (2026-10-11): el código DIAN ya no sale de un Selection propio --
            # sale del tipo de identificación nativo de Contactos (work_contact_id),
            # igual que HrPayslip._ne_tipo_documento() (sin el UserError de ahí: este
            # reporte tolera un tipo vacío/sin equivalente, igual que antes).
            dian_code = (
                employee.work_contact_id.l10n_latam_identification_type_id
                .l10n_co_ne_dian_document_code or ''
            )
            tipo_doc_ugpp = _DOC_TYPE_UGPP_MAP.get(dian_code, '')

            # -- Ingreso / Retiro en el período ------------------------
            es_ingreso = False
            fecha_ingreso = ''
            if contract and contract.date_start:
                if period_start <= contract.date_start <= period_end:
                    es_ingreso = True
                    fecha_ingreso = contract.date_start.strftime('%d/%m/%Y')

            es_retiro = False
            fecha_retiro = ''
            if contract and contract.date_end:
                if period_start <= contract.date_end <= period_end:
                    es_retiro = True
                    fecha_retiro = contract.date_end.strftime('%d/%m/%Y')

            # -- Vacaciones: fechas (simplificado) ---------------------
            fecha_ini_vac = ''
            fecha_fin_vac = ''
            # Futuro: extraer de hr.leave si se requiere detalle.

            # -- Cargo del trabajador ----------------------------------
            cargo = (
                employee.job_title
                or (employee.job_id.name if employee.job_id else '')
                or ''
            )

            # -- Salario integral --------------------------------------
            integral = (
                'X'
                if contract and contract.l10n_co_ne_integral_salary
                else ''
            )

            # ═════════════════════════════════════════════════════════
            # Construir fila de datos fijos (33 columnas)
            # ═════════════════════════════════════════════════════════
            fixed_data = [
                employee.l10n_co_ne_worker_type or '',              # 1
                employee.l10n_co_ne_worker_subtype or '',           # 2
                '',                                                 # 3  Condición especial empresa
                'X' if employee.l10n_co_ne_foreigner_no_pension else '',  # 4
                'X' if employee.l10n_co_ne_colombian_abroad else '',      # 5
                'X' if employee.l10n_co_ne_high_risk_pension else '',     # 6
                tipo_doc_ugpp,                                      # 7
                employee.identification_id or '',                   # 8
                nombre_cotizante,                                   # 9
                cargo,                                              # 10
                self.year,                                          # 11
                int(self.month),                                    # 12
                integral,                                           # 13
                nov_incapacidad,                                    # 14
                nov_lic_mat,                                        # 15
                nov_lic_rem,                                        # 16
                nov_suspension,                                     # 17
                nov_vacaciones,                                     # 18
                dias_trabajados,                                    # 19
                dias_incapacidad,                                   # 20
                dias_licencia_mat,                                  # 21
                dias_lic_remunerada,                                # 22
                dias_suspension,                                    # 23
                dias_vacaciones,                                    # 24
                dias_huelga,                                        # 25
                total_dias,                                         # 26
                'X' if es_ingreso else '',                          # 27
                fecha_ingreso,                                      # 28
                'X' if es_retiro else '',                           # 29
                fecha_retiro,                                       # 30
                fecha_ini_vac,                                      # 31
                fecha_fin_vac,                                      # 32
                '',                                                 # 33 Observaciones
            ]

            # ═════════════════════════════════════════════════════════
            # Columnas dinámicas: monto por regla salarial UGPP
            # ═════════════════════════════════════════════════════════
            concept_data = [
                rule_totals.get(rule.id, 0.0) for rule in ugpp_rules
            ]

            # ═════════════════════════════════════════════════════════
            # Escribir fila completa
            # ═════════════════════════════════════════════════════════
            row_data = fixed_data + concept_data + ibc_data

            self._ugpp_escribir_fila(ws, row_num, row_data, thin_border)

            row_num += 1

        # Ajustar anchos
        for col in ws.columns:
            max_length = max(
                len(str(cell.value or '')) for cell in col
            )
            ws.column_dimensions[col[0].column_letter].width = (
                min(max_length + 2, 40)
            )

        _logger.info(
            'Hoja "nomina" generada con %d filas (%d columnas: '
            '%d fijas + %d conceptos + 4 IBC)',
            row_num - fila_datos,
            len(all_headers),
            len(fixed_headers),
            len(concept_headers),
        )
