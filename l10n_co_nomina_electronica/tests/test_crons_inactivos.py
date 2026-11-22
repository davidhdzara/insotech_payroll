# -*- coding: utf-8 -*-
"""Los 4 crons del módulo se instalan INACTIVOS y en ``noupdate`` (v19; decisión de TL, 2026-11-22). NO ejecutadas en Odoo.

Una instalación nueva no envía nada a la DIAN, y menos la habilitación, hasta que el administrador del sistema active el cron (``sin valores por defecto silenciosos``).
Con ``noupdate="1"`` un ``-u`` posterior no apaga un cron que un cliente ya activó. Llevar a v18 al final de la ruta, con ``noupdate`` obligatorio (en Guapante
producción están pausados a mano).

Las pruebas NO dependen del estado de la base donde corren (lección de la regresión de .283: en la copia de producción los crons estaban archivados): la definición se
comprueba leyendo los XML del módulo y, en la base, solo se exige que un cron que NADIE ha modificado desde su creación (``write_date`` = ``create_date``) esté inactivo."""

import os
from lxml import etree

from odoo.tests.common import TransactionCase, tagged

CRONES = {
    'ir_cron_ne_habilitacion': 'ir_cron_habilitacion.xml',
    'ir_cron_ne_documento_send': 'ir_cron_documento_send.xml',
    'ir_cron_ne_documento_recheck': 'ir_cron_documento_send.xml',
    'ir_cron_ne_dian_status_recheck': 'ir_cron_dian_status_recheck.xml',
}
DIRECTORIO_DATOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, 'data')


@tagged('post_install', '-at_install')
class TestCronsInactivos(TransactionCase):

    def _registros_xml(self):
        """{id: (elemento ``record``, valor de ``noupdate`` del ``data`` que lo contiene)} de los XML de crons del módulo."""
        registros = {}
        for archivo in sorted(set(CRONES.values())):
            arbol = etree.parse(os.path.join(DIRECTORIO_DATOS, archivo))
            for registro in arbol.xpath("//record[@model='ir.cron']"):
                contenedor = registro.getparent()
                registros[registro.get('id')] = (registro, contenedor.get('noupdate') if contenedor.tag == 'data' else None)
        return registros

    def test_01_los_cuatro_crons_existen(self):
        for nombre in CRONES:
            cron = self.env.ref('l10n_co_nomina_electronica.%s' % nombre, raise_if_not_found=False)
            self.assertTrue(cron, nombre)
            self.assertEqual(cron._name, 'ir.cron', nombre)

    def test_02_los_xml_instalan_los_crons_inactivos_y_en_noupdate(self):
        registros = self._registros_xml()
        self.assertEqual(set(registros), set(CRONES), 'Los XML definen exactamente los 4 crons del módulo')
        for nombre, (registro, noupdate) in registros.items():
            self.assertEqual(noupdate, '1', '%s debe ir dentro de <data noupdate="1">' % nombre)
            campos = registro.xpath("field[@name='active']")
            self.assertEqual(len(campos), 1, '%s debe declarar active' % nombre)
            self.assertEqual(campos[0].get('eval'), 'False', '%s debe instalarse inactivo' % nombre)

    def test_03_los_registros_quedaron_en_noupdate_en_la_base(self):
        datos = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'l10n_co_nomina_electronica'), ('model', '=', 'ir.cron'), ('name', 'in', list(CRONES))])
        self.assertEqual(len(datos), len(CRONES))
        self.assertTrue(all(dato.noupdate for dato in datos), 'Con noupdate, un -u no apaga un cron que el cliente activó')

    def test_04_un_cron_sin_modificar_desde_la_instalacion_esta_inactivo(self):
        """Instalación nueva (o base pausada por la fase ``pausar_crons`` del script de la N1): ningún cron del módulo arranca activo. Un cron que un administrador
        modificó después (``write_date`` posterior a ``create_date``) no se evalúa: es decisión del cliente."""
        for nombre in CRONES:
            cron = self.env.ref('l10n_co_nomina_electronica.%s' % nombre).sudo()
            if cron.write_date and cron.create_date and cron.write_date > cron.create_date:
                continue
            self.assertFalse(cron.active, '%s debe estar inactivo mientras nadie lo haya modificado' % nombre)
