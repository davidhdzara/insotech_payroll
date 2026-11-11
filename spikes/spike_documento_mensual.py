#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SPIKE etapa 3 (doc 53 §18.5): documento mensual de UN empleado con dos quincenas.

Sin Odoo ni base de datos. Construye los diccionarios de dos recibos con la FORMA exacta que produce
``HrPayslip._collect_payslip_data()`` (valores de ejemplo calculados a mano), los fusiona con
``services/documento_merge.py``, arma el XML con el constructor ACTUAL (build_nomina_individual_v2) y lo valida
contra el XSD v1.0.6 de la caja de herramientas DIAN. Uso:
    python3 spikes/spike_documento_mensual.py [ruta_al_XSD] [--guardar salida.xml]
Provisional (a decidir por David): D3 = Periodo = mes calendario recortado al contrato.
"""

import copy
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

sys.modules.setdefault('pytz', types.SimpleNamespace(timezone=lambda nombre: None))  # services/__init__ lo importa
RAIZ = Path(__file__).resolve().parents[1] / 'l10n_co_nomina_electronica'
sys.path.insert(0, str(RAIZ))

from lxml import etree  # noqa: E402
from services import documento_merge, nomina_xml_builder  # noqa: E402

XSD_POR_DEFECTO = os.path.expanduser(
    '~/GoogleDrive/insotech/Mi unidad/05. Obsidian Notes/InSoTech/NORMATIVIDAD COLOMBIANA/DIAN/'
    'NOMINA ELECTRONICA/Caja-de-Herramientas-Nomina-Electronica-V1-0/XSD/'
    'NominaIndividualElectronicaXSDV1.0.6.xsd')


def recibo(fecha_ini, fecha_fin, sueldo, transporte, dias, salud, pension, extras=None):
    """Diccionario con la forma de _collect_payslip_data() (secciones y llaves del motor)."""
    devengados = {
        'Basico': {'DiasTrabajados': str(dias), 'SueldoTrabajado': '%.2f' % sueldo},
        'Transporte': {'AuxilioTransporte': '%.2f' % transporte},
    }
    deducciones = {
        'Salud': {'Porcentaje': '4.00', 'Deduccion': '%.2f' % salud},
        'FondoPension': {'Porcentaje': '4.00', 'Deduccion': '%.2f' % pension},
    }
    if extras:
        for clave, valor in extras.get('devengados', {}).items():
            devengados[clave] = valor
        for clave, valor in extras.get('deducciones', {}).items():
            deducciones[clave] = valor
    total_dev = sueldo + transporte + sum(
        float(v.get('Pago', 0)) for v in [devengados.get('Primas', {})])
    total_ded = salud + pension + float(deducciones.get('RetencionFuente', 0) or 0)
    return {
        'informacion_general': {
            'Version': 'V1.0: Documento Soporte de Pago de Nómina Electrónica', 'Ambiente': '2',
            'TipoXML': '102', 'CUNE': 'A' * 96, 'EncripCUNE': 'CUNE-SHA384', 'FechaGen': '2026-04-02',
            'HoraGen': '10:00:00-05:00', 'PeriodoNomina': '4', 'TipoMoneda': 'COP', 'TRM': '0'},
        'numero_secuencia': {'Prefijo': 'NE', 'Consecutivo': '1', 'Numero': 'NE1', 'CodigoTrabajador': '7'},
        'lugar_generacion': {'Pais': 'CO', 'DepartamentoEstado': '05', 'MunicipioCiudad': '05001',
                             'Idioma': 'es'},
        'proveedor_xml': {'RazonSocial': 'Empresa de Prueba SAS', 'NIT': '900123456', 'DV': '8',
                          'SoftwareID': 'SOFT-ID', 'SoftwareSC': 'B' * 96},
        'empleador': {'RazonSocial': 'Empresa de Prueba SAS', 'NIT': '900123456', 'DV': '8', 'Pais': 'CO',
                      'DepartamentoEstado': '05', 'MunicipioCiudad': '05001', 'Direccion': 'Calle 1 # 2-3'},
        'trabajador': {
            'TipoTrabajador': '01', 'SubTipoTrabajador': '00', 'AltoRiesgoPension': 'false',
            'TipoDocumento': '13', 'NumeroDocumento': '1020304050', 'PrimerApellido': 'Perez',
            'SegundoApellido': 'Gomez', 'PrimerNombre': 'Ana', 'LugarTrabajoPais': 'CO',
            'LugarTrabajoDepartamentoEstado': '05', 'LugarTrabajoMunicipioCiudad': '05001',
            'LugarTrabajoDireccion': 'Calle 1 # 2-3', 'SalarioIntegral': 'false', 'TipoContrato': '2',
            'Sueldo': '3000000.00', 'CodigoTrabajador': '7'},
        'pago': {'Forma': '1', 'Metodo': '10'},
        'periodo': {'FechaIngreso': '2024-03-01', 'FechaLiquidacionInicio': str(fecha_ini),
                    'FechaLiquidacionFin': str(fecha_fin), 'TiempoLaborado': '25', 'FechaGen': '2026-04-02'},
        'fechas_pagos': [str(fecha_fin)],
        'devengados': devengados, 'deducciones': deducciones,
        'devengados_total': total_dev, 'deducciones_total': total_ded,
        'comprobante_total': total_dev - total_ded,
        'codigo_qr': 'https://catalogo-vpfe-hab.dian.gov.co/document/searchqr?documentkey=' + 'A' * 96,
    }


def periodo_mes(base, ini, fin, tiempo='25'):
    periodo = copy.deepcopy(base['periodo'])
    periodo.update({'FechaLiquidacionInicio': ini, 'FechaLiquidacionFin': fin, 'TiempoLaborado': tiempo})
    return periodo


def construir_esquema(ruta_xsd, tmp):
    """El XSD importa ../common/UBL-*.xsd: se reproduce esa disposicion en un directorio temporal con los
    esquemas UBL de la carpeta hermana 'Schemes' de la caja de herramientas."""
    origen = Path(ruta_xsd).resolve()
    (Path(tmp) / 'xsd').mkdir()
    shutil.copy(origen, Path(tmp) / 'xsd' / origen.name)
    shutil.copytree(origen.parent.parent / 'Schemes', Path(tmp) / 'common')
    return etree.XMLSchema(etree.parse(str(Path(tmp) / 'xsd' / origen.name)))


def validar(nombre, doc, esquema, guardar=None):
    xml = nomina_xml_builder.build_nomina_individual_v2(doc)
    if guardar:
        Path(guardar).write_bytes(xml)
    raiz = etree.fromstring(xml)
    # El constructor deja UBLExtensions vacio: la firma (xml_signer) lo llena despues. Para validar el CUERPO
    # contra el XSD se agregan dos UBLExtension de relleno (ExtensionContent exige un hijo de otro namespace).
    ns_ext = 'urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2'
    extensiones = raiz.find('{%s}UBLExtensions' % ns_ext)
    if extensiones is not None and len(extensiones) == 0:
        for _ in range(2):
            ext = etree.SubElement(extensiones, '{%s}UBLExtension' % ns_ext)
            contenido = etree.SubElement(ext, '{%s}ExtensionContent' % ns_ext)
            etree.SubElement(contenido, '{urn:spike:relleno}Firma')  # ##other, lax
    valido = esquema.validate(etree.ElementTree(raiz))
    print('[%s] valido contra el XSD v1.0.6: %s' % (nombre, valido))
    for error in esquema.error_log:
        print('   -', error.line, error.message[:230])
    return valido, raiz


def caso_dos_quincenas():
    q1 = recibo('2026-03-01', '2026-03-15', 1500000, 124547.5, 15, 60000, 60000)
    q2 = recibo('2026-03-16', '2026-03-31', 1500000, 124547.5, 15, 60000, 60000)
    doc = documento_merge.fusionar_documento(
        [q1, q2], fechas_pagos=['2026-03-15', '2026-03-31'],
        periodo=periodo_mes(q1, '2026-03-01', '2026-03-31'))
    return doc


def caso_prima_con_quincena_y_novedades():
    """15-jun: quincena 1 + prima (mismo pago); 30-jun: quincena 2 con horas extra e incapacidad."""
    q1 = recibo('2026-06-01', '2026-06-15', 1500000, 124547.5, 15, 60000, 60000)
    prima = recibo('2026-01-01', '2026-06-30', 0, 0, 0, 0, 0)
    prima['devengados'] = {'Primas': {'Cantidad': '178', 'Pago': '1624547.50'}}  # sin Basico: es un recibo de prima
    prima['deducciones'] = {}
    prima['devengados_total'] = 1624547.50
    prima['deducciones_total'] = 0.0
    prima['comprobante_total'] = 1624547.50
    extras = {'devengados': {
        'HEDs': [{'Cantidad': '4', 'Porcentaje': '25.00', 'Pago': '48000.00',
                  'HoraInicio': '2026-06-20T18:00:00', 'HoraFin': '2026-06-20T22:00:00'}],
        'Incapacidades': [{'Cantidad': '2', 'Tipo': '1', 'Pago': '66666.67',
                           'FechaInicio': '2026-06-25', 'FechaFin': '2026-06-26'}]}}
    q2 = recibo('2026-06-16', '2026-06-30', 1500000, 124547.5, 15, 60000, 60000, extras)
    q2['devengados_total'] += 48000.00 + 66666.67
    q2['comprobante_total'] = q2['devengados_total'] - q2['deducciones_total']
    return documento_merge.fusionar_documento(
        [q1, prima, q2], fechas_pagos=['2026-06-15', '2026-06-15', '2026-06-30'],
        periodo=periodo_mes(q1, '2026-06-01', '2026-06-30'))


def main(argv):
    ruta_xsd = next((a for a in argv if a.endswith('.xsd')), XSD_POR_DEFECTO)
    guardar = argv[argv.index('--guardar') + 1] if '--guardar' in argv else None
    if not os.path.exists(ruta_xsd):
        print('XSD no encontrado:', ruta_xsd)
        return 2
    resultados = []
    with tempfile.TemporaryDirectory() as tmp:
        esquema = construir_esquema(ruta_xsd, tmp)
        for nombre, caso in (('dos quincenas', caso_dos_quincenas),
                             ('prima con quincena y novedades', caso_prima_con_quincena_y_novedades)):
            doc = caso()
            print('==', nombre)
            print('   Basico:', doc['devengados'].get('Basico'), '| Transporte:', doc['devengados'].get('Transporte'))
            print('   Primas:', doc['devengados'].get('Primas'), '| HEDs:', len(doc['devengados'].get('HEDs', [])),
                  '| Incapacidades:', len(doc['devengados'].get('Incapacidades', [])))
            print('   Salud:', doc['deducciones']['Salud'], '| FechasPagos:', doc['fechas_pagos'])
            print('   Totales:', doc['totales'])
            valido, _raiz = validar(nombre, doc, esquema, guardar if nombre == 'dos quincenas' else None)
            resultados.append(valido)
    return 0 if all(resultados) else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
