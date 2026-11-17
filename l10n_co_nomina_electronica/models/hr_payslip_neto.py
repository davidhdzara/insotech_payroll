# -*- coding: utf-8 -*-
# Part of InSoTech. See LICENSE file for full copyright and licensing details.
"""E-8 (H-QA-025): el neto del recibo sale de las líneas REDONDEADAS, tal como las guarda Odoo.

Defecto (reproducido por QA en dos liquidaciones reales): el motor de nómina calcula el total de cada regla SIN redondear
(``amount x quantity x rate / 100``), suma ese valor exacto a ``categories`` y solo al guardar la línea lo redondea a los
decimales de la moneda. Las reglas de neto (``categories['DEV'] + categories['DEDU']``) sumaban los valores exactos, así que el
neto guardado podía diferir en un centavo de la suma de las líneas que el recibo muestra y que el asiento contable lee:

- Acevedo (recibo 63679): prima y cesantías valen 166.666,666…, cada una se guarda 166.666,67 (hacia arriba): neto 2.018.786,98
  frente a 2.018.786,99 de la suma de las líneas.
- Orozco (empleado 51690): cesantías y prima valen 611.111,111… (hacia abajo) y vacaciones 559.316,875: neto 2.877.834,90
  frente a 2.877.834,91.

El asiento nativo (``hr_payroll_account._prepare_slip_lines``) debita los devengados guardados y acredita las deducciones y el
neto guardados: con un centavo de diferencia no cuadra y no se crea. Aquí el neto es la suma de las líneas ya redondeadas:
una sola fuente (la línea guardada) para lo que se ve, lo que se suma a mano y lo que se contabiliza.
"""

from odoo import _, models
from odoo.exceptions import UserError


class HrPayslipNeto(models.Model):
    _inherit = 'hr.payslip'

    def _ne_redondear_moneda(self, valor):
        """Redondea como Odoo guarda el total de una línea: a los decimales de la moneda de la compañía del recibo."""
        self.ensure_one()
        return self.company_id.currency_id.round(valor)

    def _ne_total_regla(self, result_rules, codigo):
        """Total SIN redondear que el motor ya calculó para la regla ``codigo``, o 0.0 si no se evaluó. LECTURA SIN MUTAR.

        ``result_rules`` es un ``DefaultDictPayroll`` (``hr_payroll/models/hr_payslip.py:23-27``, instanciado en ``:833``): su
        ``get(clave, default)`` INSERTA el default cuando la clave falta y el default no es ``None``, así que
        ``result_rules.get(codigo, {})`` deja un ``{}`` sin ``total`` (causa del ``KeyError: 'total'`` de la regresión bv).
        Aquí se pregunta con ``in`` (no inserta) y se lee con ``[]`` solo lo presente. El motor guarda siempre
        ``{'total', 'amount', 'quantity', 'rate'}`` por regla evaluada (``:998``) y ``__missing__`` crea el mismo conjunto; una
        entrada sin ``total`` significa que otra fórmula la modificó: error claro, no un cero en silencio."""
        if codigo not in result_rules:
            return 0.0
        entrada = result_rules[codigo]
        if not isinstance(entrada, dict) or 'total' not in entrada:
            raise UserError(_(
                'La regla "%(codigo)s" aparece en el resultado del cálculo sin su total (tipo %(tipo)s, claves %(claves)s). '
                'El motor guarda siempre total, importe, cantidad y tasa de una regla evaluada: otra fórmula modificó '
                'ese resultado. Revise las fórmulas que lo leen o lo escriben (por ejemplo result_rules.get(código, {}) '
                'deja una entrada vacía).',
                codigo=codigo, tipo=type(entrada).__name__,
                claves=sorted(entrada) if isinstance(entrada, dict) else '-'))
        return entrada['total']

    def _ne_suma_lineas_redondeadas(self, result_rules, codigo_categoria):
        """Suma de las líneas de la categoría ``codigo_categoria`` y de sus descendientes (la misma agrupación de
        ``categories[codigo]``: Odoo suma cada regla a su categoría y a todos sus ancestros), con cada línea redondeada.

        El motor evalúa SOLO las reglas de la estructura del recibo (``sorted(payslip.struct_id.rule_ids, ...)``,
        ``hr_payroll/models/hr_payslip.py:944``): en este Odoo 18 ``hr.payroll.structure`` no tiene estructura padre ni herencia de
        reglas, así que ``struct_id.rule_ids`` es exactamente el conjunto que suma ``categories``.

        :param result_rules: ``result_rules`` del cálculo del recibo: totales SIN redondear de las reglas ya evaluadas (las que
            no cumplieron su condición no están y no suman, igual que en ``categories``).
        :param codigo_categoria: código de la categoría (``DEV``, ``PREST``, ``DEDU``).
        """
        self.ensure_one()
        Categoria = self.env['hr.salary.rule.category']
        categorias = Categoria.search([
            ('id', 'child_of', Categoria.search([('code', '=', codigo_categoria)]).ids)])
        total, vistos = 0.0, set()
        for regla in self.struct_id.rule_ids:
            if regla.code in vistos or regla.category_id not in categorias or regla.code not in result_rules:
                continue
            vistos.add(regla.code)          # un código evaluado dos veces deja un solo total (el último)
            total += self._ne_redondear_moneda(self._ne_total_regla(result_rules, regla.code))
        return total

    def _ne_neto_redondeado(self, result_rules, categoria_devengado='DEV'):
        """Neto = devengados + deducciones (estas son negativas), cada línea redondeada a los decimales de la moneda.

        Reemplaza a ``categories[categoria_devengado] + categories['DEDU']`` en las reglas de neto de las 4 estructuras propias
        (``CO_NETO``, ``CO_LIQ_NETO``, ``CO_BON_NETO``: ``DEV``; ``CO_PRIMA_NETO``: ``PREST``). No cambia el importe de ninguna
        otra línea.
        """
        self.ensure_one()
        return self._ne_redondear_moneda(
            self._ne_suma_lineas_redondeadas(result_rules, categoria_devengado)
            + self._ne_suma_lineas_redondeadas(result_rules, 'DEDU'))
