# -*- coding: utf-8 -*-
"""R-2a (doc 59 §20.7-§20.10 y §25): retención en la fuente de la nómina general sobre la base del MES y repartida entre
los pagos del mes.

Decisión de David (2026-11-14; el texto normativo lo aportó él y NO está verificado en el repositorio: Art. 383 y 385 ET,
num. 10 art. 206, DUR 1625 de 2016): la retención se calcula SIEMPRE sobre la base del mes completo (depuración + tabla del
Art. 383) y se reparte entre los pagos: los que no cierran el mes retienen su parte proporcional de una PROYECCIÓN y el
que cierra el mes retiene el saldo (retención del mes real menos lo ya retenido). Así un empleado quincenal retiene lo mismo
que el mismo empleado pagado mensual (antes retenía 2,3 veces: el mes completo en cada quincena).

Un solo lugar de cálculo: las reglas ``CO_RETEFUENTE``, ``CO_EXENTO_PENSION_AFC`` y ``CO_RETEFUENTE_BASE_GROSS`` leen el
resultado de ``_ne_retencion_mes`` en vez de repetir la fórmula tres veces en el XML.
"""

from datetime import timedelta

from odoo import _, models
from odoo.exceptions import UserError

# Categorías cuya suma es la base salarial del mes (David/TL, §20.7): ``HEX`` es hija de ``DEV_SAL`` (ya va dentro);
# ``VAC`` e ``INC`` son hijas de ``DEV``. ``DEV_NOSAL`` (auxilio de transporte y no salariales) queda FUERA.
_CATEGORIAS_BASE = ('DEV_SAL', 'VAC', 'INC')


class HrPayslipRetencion(models.Model):
    _inherit = 'hr.payslip'

    def _ne_retencion_periodicidad(self):
        contrato = self.contract_id
        return contrato.schedule_pay or contrato.structure_type_id.default_schedule_pay or 'monthly'

    def _ne_retencion_es_cierre(self):
        """El recibo cierra el mes (por ``date_to``, regla D4)? Mensual y mayores: siempre. Quincenal y cada 14 días:
        ``date_to`` desde el día 16 (1→15 y 21→5 no cierran; 6→20 y 16→fin sí). Semanal y diario: el siguiente periodo
        (7 o 1 día después) ya cae en otro mes."""
        self.ensure_one()
        periodicidad = self._ne_retencion_periodicidad()
        if periodicidad in ('semi-monthly', 'bi-weekly'):
            return self.date_to.day >= 16
        if periodicidad in ('weekly', 'daily'):
            dias = 7 if periodicidad == 'weekly' else 1
            return (self.date_to + timedelta(days=dias)).month != self.date_to.month
        return True

    def _ne_retencion_categorias_base(self):
        """Categorías de la base y sus descendientes (para filtrar líneas de recibos ya guardados)."""
        categorias = self.env['hr.salary.rule.category'].search([('code', 'in', _CATEGORIAS_BASE)])
        todas, pendientes = categorias, categorias
        while pendientes:
            pendientes = self.env['hr.salary.rule.category'].search([('parent_id', 'in', pendientes.ids)]) - todas
            todas |= pendientes
        return todas

    def _ne_retencion_previos_del_mes(self):
        """Recibos del mismo empleado, estructura y compañía cuyo ``date_to`` cae en el mes de este recibo y que lo
        anteceden (orden ``date_to``, ``id``), en cualquier estado menos cancelado: el cierre lee sus líneas ya calculadas
        aunque sigan en borrador (se calculan las dos quincenas y luego se confirman); si cambia uno, hay que recalcular el
        cierre (limitación conocida, doc 59 §20.7 punto 3)."""
        self.ensure_one()
        inicio = self.date_to.replace(day=1)
        fin = self.date_to.replace(day=self._ne_dias_en_mes_calendario(self.date_to.year, self.date_to.month))
        candidatos = self.search([
            ('employee_id', '=', self.employee_id.id), ('struct_id', '=', self.struct_id.id),
            ('company_id', '=', self.company_id.id), ('date_to', '>=', inicio), ('date_to', '<=', fin),
            ('id', '!=', self.id), ('state', '!=', 'cancel')])
        return candidatos.filtered(lambda s: (s.date_to, s.id) < (self.date_to, self.id))

    def _ne_retencion_dias_del_mes(self):
        """Días comerciales del mes de ``date_to`` en que el contrato estuvo vigente (30 en un mes completo)."""
        self.ensure_one()
        inicio = self.date_to.replace(day=1)
        fin = self.date_to.replace(day=self._ne_dias_en_mes_calendario(self.date_to.year, self.date_to.month))
        contrato = self.contract_id
        desde = max(inicio, contrato.date_start)
        hasta = min(fin, contrato.date_end or fin)
        return self._ne_dias_comerciales(desde, hasta) if desde <= hasta else 0

    def _ne_retencion_mes(self, categories):
        """Retención en la fuente de ESTE recibo de la nómina general (R-2a, doc 59 §25).

        :param categories: las categorías del cálculo del recibo (``localdict['categories']``).
        :returns: dict con ``retencion`` (pesos retenidos en este recibo, >= 0), ``reintegro`` (pesos que se devuelven al
            trabajador por exceso retenido en recibos anteriores del mes, >= 0; nunca ambos distintos de 0),
            ``exento_vol_pension_afc`` (lo que este recibo suma al acumulado anual de exentos, incremental),
            ``base_devengado`` (devengado salarial real de este recibo, aditivo por recibo) y ``es_cierre``.
        """
        self.ensure_one()
        contrato = self.contract_id
        config = self._ne_retefuente_config()
        es_cierre = self._ne_retencion_es_cierre()

        # --- lo de ESTE recibo (de las categorías del cálculo, no de líneas guardadas) ---
        base_este = sum(categories.get(codigo, 0.0) or 0.0 for codigo in _CATEGORIAS_BASE)
        integral = bool(contrato.l10n_co_ne_integral_salary)
        if integral:
            ibc_este = contrato.wage * self._rule_parameter('l10n_co_factor_integral_salary', self.date_from)
        else:
            ibc_este = categories.get('DEV_SAL', contrato.wage)

        def calcular(bruto, ibc):
            return config.compute_retefuente(
                self.employee_id, bruto, ibc, ibc, self.employee_id.company_id,
                contract=contrato, payslip=self, fecha_mes=self.date_to)

        if not es_cierre:
            # Parte proporcional de la retención de la PROYECCIÓN del mes: devengado de este recibo + el resto de los días del
            # mes al salario del contrato; sin extrapolar variables futuras.
            dias_mes = self._ne_retencion_dias_del_mes()
            dias_este = self._ne_dias_bajo_contrato()
            if dias_mes <= 0 or dias_este <= 0:
                return {'retencion': 0.0, 'reintegro': 0.0, 'exento_vol_pension_afc': 0.0,
                        'base_devengado': base_este, 'es_cierre': False}
            dias_comerciales = self._rule_parameter('l10n_co_dias_mes_comercial', self._ne_fecha_parametros())
            restante = max(dias_mes - dias_este, 0) * contrato.wage / dias_comerciales
            proporcion = min(dias_este / dias_mes, 1.0)
            resultado = calcular(base_este + restante, ibc_este if integral else ibc_este + restante)
            return {
                'retencion': round(proporcion * resultado['retencion_pesos'], 0),
                'reintegro': 0.0,
                'exento_vol_pension_afc': round(proporcion * resultado['exento_vol_pension_afc'], 2),
                'base_devengado': base_este, 'es_cierre': False}

        # --- recibo de CIERRE del mes: retención del mes real menos lo ya retenido ---
        previos = self._ne_retencion_previos_del_mes()
        sin_calcular = previos.filtered(lambda s: not s.line_ids)
        if sin_calcular:
            raise UserError(_(
                'La retención en la fuente de "%(recibo)s" (%(empleado)s) cierra el mes y necesita lo ya retenido en los '
                'recibos anteriores del mismo mes, pero todavía no están calculados: %(previos)s. Calcúlelos primero (en '
                'orden) y vuelva a calcular este recibo.',
                recibo=self.display_name, empleado=self.employee_id.display_name,
                previos=', '.join(sin_calcular.mapped('display_name'))))
        lineas = previos.mapped('line_ids')
        categorias_base = self._ne_retencion_categorias_base()
        base_previa = sum(l.total for l in lineas if l.category_id in categorias_base)
        ibc_previo = sum(l.total for l in lineas if l.code == 'CO_RETEFUENTE_BASE_IBC')
        retenido_previo = -sum(l.total for l in lineas if l.code == 'CO_RETEFUENTE')
        reintegrado_previo = sum(l.total for l in lineas if l.code == 'CO_REINTEGRO_RETE')
        exento_previo = sum(l.total for l in lineas if l.code == 'CO_EXENTO_PENSION_AFC')

        resultado = calcular(base_previa + base_este, ibc_este if integral else ibc_previo + ibc_este)
        saldo = resultado['retencion_pesos'] - (retenido_previo - reintegrado_previo)
        return {
            'retencion': max(saldo, 0.0),
            'reintegro': max(-saldo, 0.0),
            'exento_vol_pension_afc': round(resultado['exento_vol_pension_afc'] - exento_previo, 2),
            'base_devengado': base_este, 'es_cierre': True}
