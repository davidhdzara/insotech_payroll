# InSoTech Payroll - Nomina Electronica Colombia

Modulo de nomina para Odoo 18 con integracion completa ante la DIAN, generacion de PILA, gestion de embargos judiciales, y cumplimiento normativo laboral colombiano.

**Autor:** InSoTech - Infinity Solutions Technology S.A.S  
**Licencia:** LGPL-3  
**Version:** 18.0.2.0.0  
**Compatibilidad:** Odoo 18 Community / Enterprise  

---

## Que es este proyecto

Sistema integral de nomina electronica colombiana que cubre todo el ciclo:
desde el calculo de la nomina con 52+ reglas salariales, pasando por la generacion
del XML firmado digitalmente para la DIAN, hasta la produccion del archivo plano
PILA para el pago de seguridad social.

El modulo esta disenado para empresas colombianas que necesitan:
- Transmitir nomina electronica a la DIAN (Resolucion 000013 de 2021)
- Generar el archivo plano PILA (Resolucion 2388)
- Calcular retencion en la fuente automaticamente (Art. 383 y 387 ET)
- Liquidar contratos laborales conforme al CST
- Gestionar provisiones de prestaciones sociales
- Controlar embargos judiciales con topes legales

---

## Estructura del repositorio

```
insotech_payroll/
  l10n_co_nomina_electronica/    # Modulo principal
    models/                       # 11 modelos Odoo
    services/                     # 6 servicios Python puro (sin Odoo)
    wizard/                       # 4 asistentes
    views/                        # 10 vistas XML
    data/                         # Reglas salariales, retenciones, parametros
    report/                       # Comprobante de pago PDF con QR
    security/                     # 18 reglas de acceso (ACL)
    tests/                        # Tests unitarios
    DIAN/                         # XSD y ejemplificaciones oficiales
    doc_tecnica_desarrollo/       # Documentacion tecnica interna
    doc_legal_info_importante_desarrollo/  # Referencias normativas
  l10n_co_portal_empleado/        # Portal web del empleado (complementario)
  l10n_co_ugpp/                   # Reportes UGPP (complementario)
```

---

## Funcionalidades implementadas

### Nomina Electronica DIAN
- Generacion de XML UBL 2.1 conforme al Anexo Tecnico
- Firma digital XAdES-BES con certificado .p12
- Envio al WebService DIAN (habilitacion y produccion)
- Calculo de CUNE (Codigo Unico de Nomina Electronica) SHA-384
- Notas de ajuste (reemplazar/eliminar)
- Comprobante de pago PDF con codigo QR

### Reglas Salariales (52+ reglas preconfiguradas)
- Sueldo basico con periodos configurables (semanal/decenal/quincenal/mensual)
- Auxilio de transporte (parametrizado, no hardcoded)
- 7 tipos de horas extra y recargos (HED, HEN, HRN, HEDDF, HENDF, HRDDF, HRNDF)
- Comisiones, bonificaciones salariales y no salariales
- Auxilios, viaticos, dotacion, teletrabajo
- Incapacidades (comun, laboral, accidente)
- Licencias (maternidad, paternidad, remunerada)
- Vacaciones (disfrutadas y compensadas)
- Prestaciones (prima, cesantias, intereses)
- Deducciones SS empleado (salud 4%, pension 4%, FSP escalonado)
- Aportes empresa (salud 8.5%, pension 12%, ARL, CCF 4%, SENA 2%, ICBF 3%)
- Retencion en la fuente automatica (Art. 383 ET)
- Embargos con topes legales (Art. 155 CST)
- Fondo de Solidaridad Pensional con escala desde 4 SMMLV

### PILA - Archivo Plano de Seguridad Social
- Generacion del archivo TXT con separador pipe (|)
- Registro Tipo 1 (encabezado del aportante, 22 campos)
- Registro Tipo 2 (detalle por cotizante, 98 campos)
- Registros Tipo 8-12 (resumenes por administradora)
- Normalizacion de texto (tildes, enie, mayusculas)
- Compatible con SOI, SuAporte, Mi Planilla

### Retencion en la Fuente
- Procedimiento 1 (Art. 383 ET) - Tabla marginal por rangos UVT
- Procedimiento 2 (Art. 385 ET) - Porcentaje fijo semestral
- Depuracion completa de base gravable (Art. 387 ET)
- Tabla de UVT configurable por ano
- Simulador interactivo de retencion

### Provisiones de Prestaciones Sociales
- Calculo automatico mensual: prima, cesantias, intereses, vacaciones
- Detalle por empleado con lineas individuales
- Flujo de aprobacion (borrador -> calculado -> aprobado)

### Liquidacion de Contrato
- Calculo automatico de todos los conceptos (Art. 64 CST)
- Tipos: terminacion sin justa causa, renuncia, mutuo acuerdo, justa causa, fin de obra
- Indemnizacion automatica segun tipo de contrato
- Detalle de cada concepto liquidado

### Embargos Judiciales
- Modelo completo con tipos: civil, alimentos, cooperativa
- Topes legales automaticos Art. 155 CST y Art. 594 CPC
- Civil: maximo 1/5 del excedente sobre SMMLV
- Alimentos: hasta 50% del salario total
- Flujo de estados (activo/suspendido/cerrado)

### Reportes UGPP
- Generacion de archivo Excel para la UGPP
- Detalle por empleado con IBC y aportes
- Mapeo de tipos de documento DIAN a UGPP

### Parametrizacion
- SMMLV configurable por empresa (no hardcoded)
- Auxilio de transporte configurable
- Periodos de nomina: semanal (7), decenal (10), catorcenal (14), quincenal (15), mensual (30)
- Exoneracion Ley 1607/2012 configurable

---

## Dependencias

### Modulos Odoo requeridos
- `hr_payroll` - Nomina base de Odoo
- `l10n_co` - Localizacion colombiana
- `hr_holidays` - Gestion de ausencias

### Librerias Python
- `cryptography` - Firma digital XAdES
- `lxml` - Generacion y validacion XML
- `requests` - Comunicacion con DIAN
- `openpyxl` - Generacion de reportes UGPP (opcional)

---

## Instalacion

1. Clonar el repositorio en la carpeta de addons de Odoo:
```bash
git clone git@github.com:davidhdzara/insotech_payroll.git
```

2. Agregar la ruta al `addons_path` en `odoo.conf`:
```
addons_path = ...,/path/to/insotech_payroll
```

3. Instalar dependencias Python:
```bash
pip install cryptography lxml requests openpyxl
```

4. Reiniciar Odoo y actualizar la lista de modulos.

5. Instalar el modulo `Nomina Electronica Colombia - DIAN` desde el menu de Apps.

---

## Configuracion inicial

1. **Empresa:** Ir a Configuracion > Empresas y completar:
   - NIT y digito de verificacion
   - Certificado digital .p12 y contrasena
   - Software ID y PIN asignados por la DIAN
   - SMMLV y auxilio de transporte vigentes
   - Codigo ARL y tipo de aportante PILA

2. **Empleados:** En cada ficha de empleado completar:
   - Tipo y numero de documento
   - Codigos de EPS, AFP y CCF (seccion PILA)
   - Datos bancarios para pago

3. **Contratos:** En cada contrato configurar:
   - Periodo de nomina (semanal/quincenal/mensual)
   - Tipo de cotizante y subtipo
   - Clase de riesgo ARL
   - Salario integral si aplica

---

## Lo que falta por desarrollar

### Prioridad alta
- [ ] **Certificado 220** - Certificado de Ingresos y Retenciones (obligatorio por ley, se entrega anualmente a cada empleado)
- [ ] **Formato 2276** - Exogena / Medios magneticos para la DIAN (reporte anual obligatorio)

### Prioridad media
- [ ] **Reportes adicionales** - Resumen de nomina, libro de salarios, reporte de aportes a seguridad social
- [ ] **Dashboard** - Panel visual con KPIs de costo laboral, headcount, tendencias
- [ ] **Integracion prestamos** - Leer cuotas de prestamos/libranzas desde el modulo de contabilidad

### Prioridad baja
- [ ] **Integracion operadores PILA** - Envio directo del archivo plano a SOI/SuAporte via API
- [ ] **App Store packaging** - Icono, screenshots, index.html para publicacion en Odoo Apps
- [ ] **Tests unitarios completos** - Cobertura actual es minima, necesita expansion significativa

---

## Arquitectura

El modulo sigue una arquitectura de **servicios desacoplados**:

- **Models** (`models/`): Logica de Odoo, campos, vistas, flujos de estado
- **Services** (`services/`): Python puro sin dependencias de Odoo. Incluye:
  - `cune.py` - Calculo de CUNE SHA-384
  - `dian_utils.py` - Utilidades DIAN (DV, NIT, periodos)
  - `nomina_xml_builder.py` - Constructor de XML UBL 2.1
  - `xml_signer.py` - Firma digital XAdES-BES
  - `soap_client.py` - Cliente SOAP para WebService DIAN
  - `pila_generator.py` - Generador de archivo plano PILA

Esta separacion permite testear los servicios sin necesidad de un entorno Odoo.

---

## Normativa de referencia

| Norma | Tema |
|---|---|
| Resolucion DIAN 000013 de 2021 | Nomina Electronica |
| Anexo Tecnico Nomina Electronica v1.0 | Especificacion XML UBL 2.1 |
| Resolucion 2388 de 2016 | Planilla PILA |
| Art. 383 ET | Retencion en la fuente - Procedimiento 1 |
| Art. 385 ET | Retencion en la fuente - Procedimiento 2 |
| Art. 387 ET | Depuracion de base gravable |
| Art. 155 CST | Embargabilidad del salario |
| Art. 594 CPC | Inembargabilidad del SMMLV |
| Art. 64 CST | Indemnizacion por despido |
| Art. 249 CST | Auxilio de cesantias |
| Art. 306 CST | Prima de servicios |
| Art. 186 CST | Vacaciones |

---

## Contacto

**InSoTech - Infinity Solutions Technology S.A.S**  
Web: https://insotech.it  
Repositorio: https://github.com/davidhdzara/insotech_payroll
