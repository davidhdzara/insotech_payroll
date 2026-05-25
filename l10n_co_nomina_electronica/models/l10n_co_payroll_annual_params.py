# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class L10nCoPayrollAnnualParams(models.Model):
    _name = 'l10n.co.payroll.annual.params'
    _description = 'Parametros Anuales de Nomina Colombiana'
    _order = 'year desc'
    _sql_constraints = [
        ('unique_year_company',
         'unique(year, company_id)',
         'Solo puede existir un registro de parametros por ano y compania.'),
    ]

    year = fields.Integer(
        string='Ano',
        required=True,
        default=lambda self: fields.Date.context_today(self).year,
        help='Ano fiscal al que aplican estos parametros.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compania',
        required=True,
        default=lambda self: self.env.company,
        help='Compania a la que pertenecen estos parametros.',
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        string='Moneda',
    )
    smmlv = fields.Monetary(
        string='SMMLV',
        required=True,
        currency_field='currency_id',
        help='Salario Minimo Mensual Legal Vigente para este ano. '
             'Decreto del Gobierno Nacional publicado en diciembre del ano anterior.',
    )
    aux_transporte = fields.Monetary(
        string='Auxilio de Transporte',
        required=True,
        currency_field='currency_id',
        help='Valor mensual del auxilio de transporte para este ano. '
             'Aplica a trabajadores con salario igual o inferior a 2 SMMLV.',
    )
    uvt = fields.Monetary(
        string='Valor UVT',
        required=True,
        currency_field='currency_id',
        help='Unidad de Valor Tributario vigente para este ano. '
             'Publicado por la DIAN mediante resolucion.',
    )

    @api.constrains('year')
    def _check_year(self):
        for rec in self:
            if rec.year < 2000 or rec.year > 2100:
                raise ValidationError(
                    _('El ano debe estar entre 2000 y 2100.')
                )

    def name_get(self):
        return [(r.id, '%d - %s' % (r.year, r.company_id.name)) for r in self]
