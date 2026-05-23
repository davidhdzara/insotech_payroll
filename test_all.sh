#!/bin/bash
# =============================================================
# SET DE PRUEBAS COMPLETO - ODOO 18 STAGING
# Ejecutar con: cat test_all.sh | ssh <server> bash
# =============================================================

echo "================================================================"
echo "  SET DE PRUEBAS - l10n_co_nomina_electronica"
echo "  Servidor: guapante-staging-dev-32580182"
echo "  Fecha: $(date)"
echo "================================================================"

# ──────────────────────────────────────────────────────────────
# BLOQUE 1: SERVICIOS PUROS (Python sin ORM)
# ──────────────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo "  BLOQUE 1: SERVICIOS PYTHON PUROS"
echo "================================================================"

python3 << 'PYEOF'
import sys, traceback
sys.path.insert(0, '/home/odoo/src/user/l10n_co_nomina_electronica')

results = []
def test(name, fn):
    try:
        fn()
        results.append(("PASS", name))
    except Exception as e:
        results.append(("FAIL", f"{name}: {e}"))

# --- CUNE ---
def t_cune_import():
    from services.cune import compute_cune, compute_software_security_code
    assert callable(compute_cune)
    assert callable(compute_software_security_code)
test("CUNE: Import", t_cune_import)

def t_cune_compute():
    from services.cune import compute_cune
    cune, cadena = compute_cune('NE001','2026-01-15','10:30:00-05:00','3500000.00','500000.00','3000000.00','900123456','1020422294','102','2')
    assert isinstance(cune, str) and len(cune) == 96, f"CUNE len={len(cune)}"
test("CUNE: compute_cune SHA-384 (96 chars)", t_cune_compute)

def t_cune_security():
    from services.cune import compute_software_security_code
    code = compute_software_security_code("SOFT123", "PIN456", "NE001")
    assert isinstance(code, str) and len(code) == 96
test("CUNE: compute_software_security_code", t_cune_security)

def t_cune_different_inputs():
    from services.cune import compute_cune
    c1, _ = compute_cune('NE001','2026-01-15','10:30:00-05:00','100.00','50.00','50.00','900123456','1020422294','102','2')
    c2, _ = compute_cune('NE002','2026-01-15','10:30:00-05:00','100.00','50.00','50.00','900123456','1020422294','102','2')
    assert c1 != c2, "CUNEs con diferente numero deben ser diferentes"
test("CUNE: Unicidad por numero de documento", t_cune_different_inputs)

# --- DIAN UTILS ---
def t_dv():
    from services.dian_utils import compute_dv
    dv = compute_dv("900123456")
    assert dv is not None
    dv2 = compute_dv("800199436")
    assert dv2 is not None
test("DIAN Utils: compute_dv NIT normal", t_dv)

def t_dv_long():
    from services.dian_utils import compute_dv
    dv = compute_dv("123456789012345")
    assert dv is not None
test("DIAN Utils: compute_dv NIT 15 digitos", t_dv_long)

def t_clean_nit():
    from services.dian_utils import clean_nit
    assert clean_nit("900.123.456-7") == "900123456"
    assert clean_nit("  900123456  ") == "900123456"
    assert clean_nit("9001234567") == "900123456"
    assert clean_nit("900123456") == "900123456"
test("DIAN Utils: clean_nit (puntos, DV, espacios)", t_clean_nit)

def t_split_name_4():
    from services.dian_utils import split_name
    r = split_name("DAVID ALEXANDER HERNANDEZ ARANGO")
    assert r.get("primer_nombre") == "DAVID"
    assert r.get("primer_apellido") is not None
test("DIAN Utils: split_name 4 partes", t_split_name_4)

def t_split_name_2():
    from services.dian_utils import split_name
    r = split_name("DAVID HERNANDEZ")
    assert r.get("primer_nombre") == "DAVID"
test("DIAN Utils: split_name 2 partes", t_split_name_2)

def t_split_name_1():
    from services.dian_utils import split_name
    r = split_name("DAVID")
    assert r.get("primer_nombre") == "DAVID"
test("DIAN Utils: split_name 1 parte", t_split_name_1)

def t_format_amount():
    from services.dian_utils import format_amount
    r = format_amount(1500000.50)
    assert isinstance(r, str) and "1500000" in r
test("DIAN Utils: format_amount", t_format_amount)

def t_format_amount_zero():
    from services.dian_utils import format_amount
    r = format_amount(0)
    assert isinstance(r, str)
test("DIAN Utils: format_amount cero", t_format_amount_zero)

def t_format_amount_negative():
    from services.dian_utils import format_amount
    r = format_amount(-500000)
    assert isinstance(r, str)
test("DIAN Utils: format_amount negativo", t_format_amount_negative)

def t_doc_type():
    from services.dian_utils import get_doc_type_code
    cc = get_doc_type_code("CC")
    assert cc is not None
test("DIAN Utils: get_doc_type_code CC", t_doc_type)

def t_doc_type_map():
    from services.dian_utils import DOC_TYPE_MAP
    assert "CC" in DOC_TYPE_MAP
    assert "NI" in DOC_TYPE_MAP or "TI" in DOC_TYPE_MAP
test("DIAN Utils: DOC_TYPE_MAP cobertura", t_doc_type_map)

def t_compute_worked_time():
    from services.dian_utils import compute_worked_time
    r = compute_worked_time("2026-01-01", "2026-01-31")
    assert r is not None
test("DIAN Utils: compute_worked_time enero", t_compute_worked_time)

def t_wsdl_url():
    from services.dian_utils import get_nomina_wsdl_url
    url_hab = get_nomina_wsdl_url("2")
    assert "habilitacion" in url_hab.lower() or "hab" in url_hab.lower() or "https" in url_hab
    url_prod = get_nomina_wsdl_url("1")
    assert url_hab != url_prod
test("DIAN Utils: get_nomina_wsdl_url hab vs prod", t_wsdl_url)

# --- PILA GENERATOR ---
def t_pila_import():
    from services.pila_generator import generate_pila_file, generate_tipo_1, generate_tipo_2
    assert callable(generate_pila_file)
test("PILA: Import funciones", t_pila_import)

def t_pila_normalize():
    from services.pila_generator import normalize_text
    assert normalize_text("Hernandez") == "HERNANDEZ"
    assert normalize_text("cafe") == "CAFE"
test("PILA: normalize_text mayusculas", t_pila_normalize)

def t_pila_normalize_empty():
    from services.pila_generator import normalize_text
    r = normalize_text("")
    assert r == ""
test("PILA: normalize_text vacio", t_pila_normalize_empty)

def t_pila_tipo1():
    from services.pila_generator import generate_tipo_1
    aportante = {
        "tipo_planilla": "E", "nit": "900123456", "dv": "7",
        "razon_social": "INSOTECH SAS", "tipo_documento": "NI",
        "forma_presentacion": "U", "codigo_arl": "14-11",
        "periodo_salud": "2026-05", "periodo_otros": "2026-04",
        "tipo_aportante": "2", "total_cotizantes": 5, "total_nomina": 15000000,
    }
    result = generate_tipo_1(aportante)
    assert isinstance(result, str) and len(result) > 10
test("PILA: generate_tipo_1 encabezado", t_pila_tipo1)

def t_pila_tipo2():
    from services.pila_generator import generate_tipo_2
    cotizante = {
        "tipo_documento": "CC", "numero_documento": "1020422294",
        "tipo_cotizante": "01", "subtipo_cotizante": "00",
        "primer_apellido": "HERNANDEZ", "segundo_apellido": "ARANGO",
        "primer_nombre": "DAVID", "segundo_nombre": "ALEXANDER",
        "departamento": "11", "municipio": "001",
        "salario": 3500000, "dias_pension": 30, "dias_salud": 30,
        "dias_arl": 30, "dias_ccf": 30,
        "ibc_pension": 3500000, "ibc_salud": 3500000,
        "ibc_arl": 3500000, "ibc_ccf": 3500000,
        "tarifa_pension": "16.000", "tarifa_salud": "12.500",
        "tarifa_arl": "0.522", "tarifa_ccf": "4.000",
        "codigo_eps": "EPS001", "codigo_afp": "AFP001",
        "codigo_arl": "ARL001", "codigo_ccf": "CCF001",
        "horas_laboradas": 240, "extranjero": "N",
        "residente_exterior": "N", "salario_integral": "N",
        "salario_variable": "N",
    }
    result = generate_tipo_2(cotizante)
    assert isinstance(result, str) and len(result) > 50
test("PILA: generate_tipo_2 cotizante", t_pila_tipo2)

# --- XML BUILDER ---
def t_xml_builder():
    from services.nomina_xml_builder import build_nomina_individual, build_nota_ajuste
    assert callable(build_nomina_individual)
    assert callable(build_nota_ajuste)
test("XML Builder: Import", t_xml_builder)

# --- SOAP CLIENT ---
def t_soap():
    from services.soap_client import send_nomina_sync, send_test_set_async, get_status_zip
    from services.soap_client import DIAN_ENDPOINT_HAB, DIAN_ENDPOINT_PROD
    assert callable(send_nomina_sync)
    assert "dian" in DIAN_ENDPOINT_HAB.lower() or "https" in DIAN_ENDPOINT_HAB
test("SOAP Client: Import y endpoints", t_soap)

# --- XML SIGNER ---
def t_signer():
    from services.xml_signer import sign_xml, load_p12
    assert callable(sign_xml)
    assert callable(load_p12)
test("XML Signer: Import", t_signer)

# --- PRINT ---
print("")
passed = sum(1 for s,_ in results if s == "PASS")
failed = sum(1 for s,_ in results if s == "FAIL")
for status, name in results:
    icon = "OK" if status == "PASS" else "XX"
    print(f"  [{icon}] {name}")
print(f"\n  Servicios Python: {passed} PASS, {failed} FAIL de {len(results)}")
PYEOF

# ──────────────────────────────────────────────────────────────
# BLOQUE 2: VERIFICACION DE ESQUEMA DB
# ──────────────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo "  BLOQUE 2: ESQUEMA DE BASE DE DATOS"
echo "================================================================"

psql -t -A << 'SQLEOF'
-- Test 2.1: Modulo instalado
SELECT '  [' || CASE WHEN state='installed' THEN 'OK' ELSE 'XX' END || '] Modulo instalado: ' || state
FROM ir_module_module WHERE name = 'l10n_co_nomina_electronica';

-- Test 2.2: Company fields
SELECT '  [' || CASE WHEN count(*) >= 18 THEN 'OK' ELSE 'XX' END || '] Company: ' || count(*) || ' campos l10n_co_*'
FROM information_schema.columns WHERE table_name = 'res_company' AND column_name LIKE 'l10n_co_%';

-- Test 2.3: Contract fields
SELECT '  [' || CASE WHEN count(*) >= 9 THEN 'OK' ELSE 'XX' END || '] Contract: ' || count(*) || ' campos PILA'
FROM information_schema.columns WHERE table_name = 'hr_contract' AND column_name LIKE 'l10n_co_pila%';

-- Test 2.4: Employee fields
SELECT '  [' || CASE WHEN count(*) >= 20 THEN 'OK' ELSE 'XX' END || '] Employee: ' || count(*) || ' campos l10n_co_*'
FROM information_schema.columns WHERE table_name = 'hr_employee' AND column_name LIKE 'l10n_co_%';

-- Test 2.5: Payslip fields
SELECT '  [' || CASE WHEN count(*) >= 10 THEN 'OK' ELSE 'XX' END || '] Payslip: ' || count(*) || ' campos NE'
FROM information_schema.columns WHERE table_name = 'hr_payslip' AND column_name LIKE 'l10n_co_%';

-- Test 2.6: Salary rule fields
SELECT '  [' || CASE WHEN count(*) >= 5 THEN 'OK' ELSE 'XX' END || '] Salary Rule: ' || count(*) || ' campos DIAN/UGPP'
FROM information_schema.columns WHERE table_name = 'hr_salary_rule' AND column_name LIKE 'l10n_co_%';

-- Test 2.7: Embargo table
SELECT '  [' || CASE WHEN count(*) >= 14 THEN 'OK' ELSE 'XX' END || '] Tabla embargo: ' || count(*) || ' columnas'
FROM information_schema.columns WHERE table_name = 'l10n_co_hr_embargo';

-- Test 2.8: Provision table with currency_id
SELECT '  [' || CASE WHEN count(*) > 0 THEN 'OK' ELSE 'XX' END || '] Provision: currency_id existe'
FROM information_schema.columns WHERE table_name = 'l10n_co_hr_provision' AND column_name = 'currency_id';

-- Test 2.9: Liquidacion table
SELECT '  [' || CASE WHEN count(*) >= 25 THEN 'OK' ELSE 'XX' END || '] Tabla liquidacion: ' || count(*) || ' columnas'
FROM information_schema.columns WHERE table_name = 'l10n_co_hr_liquidacion';

-- Test 2.10: Liquidacion currency_id
SELECT '  [' || CASE WHEN count(*) > 0 THEN 'OK' ELSE 'XX' END || '] Liquidacion: currency_id existe'
FROM information_schema.columns WHERE table_name = 'l10n_co_hr_liquidacion' AND column_name = 'currency_id';

-- Test 2.11: UGPP table
SELECT '  [' || CASE WHEN count(*) > 0 THEN 'OK' ELSE 'XX' END || '] Tabla UGPP existe'
FROM information_schema.columns WHERE table_name = 'l10n_co_nomina_ugpp';

-- Test 2.12: Retefuente UVT table
SELECT '  [' || CASE WHEN count(*) > 0 THEN 'OK' ELSE 'XX' END || '] Tabla Retefuente UVT existe'
FROM information_schema.columns WHERE table_name = 'l10n_co_retefuente_uvt';

-- Test 2.13: PILA wizard table
SELECT '  [' || CASE WHEN count(*) > 0 THEN 'OK' ELSE 'XX' END || '] Tabla PILA wizard existe'
FROM information_schema.columns WHERE table_name = 'l10n_co_hr_pila_wizard';

-- Test 2.14: Provision wizard table
SELECT '  [' || CASE WHEN count(*) > 0 THEN 'OK' ELSE 'XX' END || '] Tabla Provision wizard existe'
FROM information_schema.columns WHERE table_name = 'l10n_co_hr_provision_wizard';
SQLEOF

# ──────────────────────────────────────────────────────────────
# BLOQUE 3: DATOS CARGADOS
# ──────────────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo "  BLOQUE 3: DATOS CARGADOS"
echo "================================================================"

psql -t -A << 'SQLEOF'
-- Test 3.1: Estructura salarial
SELECT '  [' || CASE WHEN count(*) > 0 THEN 'OK' ELSE 'XX' END || '] Estructura: Nomina Colombia - General'
FROM hr_payroll_structure WHERE name::text LIKE '%Colombia%';

-- Test 3.2: Reglas salariales con concepto DIAN
SELECT '  [' || CASE WHEN count(*) >= 40 THEN 'OK' ELSE 'XX' END || '] Reglas salariales con DIAN concept: ' || count(*)
FROM hr_salary_rule WHERE l10n_co_ne_dian_concept IS NOT NULL;

-- Test 3.3: Categorias salariales CO
SELECT '  [' || CASE WHEN count(*) > 0 THEN 'OK' ELSE 'XX' END || '] Categorias salariales CO_*: ' || count(*)
FROM hr_salary_rule_category WHERE code LIKE 'CO_%';

-- Test 3.4: Secuencia NE
SELECT '  [' || CASE WHEN count(*) > 0 THEN 'OK' ELSE 'XX' END || '] Secuencia NE (Nomina Electronica)'
FROM ir_sequence WHERE prefix = 'NE';

-- Test 3.5: Secuencia NA
SELECT '  [' || CASE WHEN count(*) > 0 THEN 'OK' ELSE 'XX' END || '] Secuencia NA (Nota Ajuste)'
FROM ir_sequence WHERE prefix = 'NA';

-- Test 3.6: Retefuente UVT datos
SELECT '  [' || CASE WHEN count(*) > 0 THEN 'OK' ELSE 'XX' END || '] Retefuente UVT: ' || count(*) || ' registros'
FROM l10n_co_retefuente_uvt;

-- Test 3.7: Vistas del modulo
SELECT '  [' || CASE WHEN count(*) >= 20 THEN 'OK' ELSE 'XX' END || '] Vistas registradas: ' || count(*)
FROM ir_ui_view WHERE name LIKE '%.ne%' OR name LIKE 'l10n_co%';

-- Test 3.8: ACLs del modulo
SELECT '  [' || CASE WHEN count(*) >= 10 THEN 'OK' ELSE 'XX' END || '] ACLs registradas: ' || count(*)
FROM ir_model_access WHERE name LIKE 'l10n_co%';

-- Test 3.9: Reglas salariales con UGPP type
SELECT '  [' || CASE WHEN count(*) > 0 THEN 'OK' ELSE 'XX' END || '] Reglas con UGPP payment type: ' || count(*)
FROM hr_salary_rule WHERE l10n_co_ugpp_payment_type IS NOT NULL;
SQLEOF

# ──────────────────────────────────────────────────────────────
# BLOQUE 4: PRUEBAS ORM (odoo-bin shell)
# ──────────────────────────────────────────────────────────────
echo ""
echo "================================================================"
echo "  BLOQUE 4: PRUEBAS ORM (Odoo Shell)"
echo "================================================================"

odoo-bin shell -d guapante-staging-dev-32580182 --no-http --log-level=error << 'ORMEOF'
import traceback

results = []
def test(name, fn):
    try:
        fn()
        results.append(("PASS", name))
    except Exception as e:
        results.append(("FAIL", f"{name}: {e}"))

# --- 4.1 Crear embargo ---
def t_crear_embargo():
    emp = env['hr.employee'].search([], limit=1)
    if not emp:
        results.append(("SKIP", "Crear embargo: No hay empleados"))
        return
    embargo = env['l10n.co.hr.embargo'].create({
        'name': 'TEST-EMB-001',
        'employee_id': emp.id,
        'tipo_embargo': 'civil',
        'valor_fijo': 500000,
        'juzgado': 'Juzgado 1 Civil',
        'date_start': '2026-01-01',
    })
    assert embargo.id > 0
    assert embargo.state == 'active'
    embargo.unlink()
test("ORM: Crear embargo civil", t_crear_embargo)

# --- 4.2 Crear embargo alimentos ---
def t_embargo_alimentos():
    emp = env['hr.employee'].search([], limit=1)
    if not emp:
        return
    embargo = env['l10n.co.hr.embargo'].create({
        'name': 'TEST-EMB-ALI-001',
        'employee_id': emp.id,
        'tipo_embargo': 'alimentos',
        'porcentaje': 30.0,
        'juzgado': 'Juzgado de Familia',
        'date_start': '2026-01-01',
    })
    assert embargo.tipo_embargo == 'alimentos'
    assert embargo.porcentaje == 30.0
    embargo.unlink()
test("ORM: Crear embargo alimentos con %", t_embargo_alimentos)

# --- 4.3 Company fields ---
def t_company_fields():
    company = env['res.company'].search([], limit=1)
    assert hasattr(company, 'l10n_co_ne_smmlv')
    assert hasattr(company, 'l10n_co_ne_aux_transporte')
    assert hasattr(company, 'l10n_co_ne_uvt')
    assert hasattr(company, 'l10n_co_ne_software_id')
    assert hasattr(company, 'l10n_co_ne_environment')
    assert hasattr(company, 'l10n_co_pila_tipo_aportante')
    assert hasattr(company, 'l10n_co_pila_arl_code')
test("ORM: Company tiene campos NE y PILA", t_company_fields)

# --- 4.4 Configurar SMMLV ---
def t_config_smmlv():
    company = env['res.company'].search([], limit=1)
    company.write({
        'l10n_co_ne_smmlv': 1423500,
        'l10n_co_ne_aux_transporte': 200000,
        'l10n_co_ne_uvt': 49799,
    })
    company.invalidate_recordset()
    assert company.l10n_co_ne_smmlv == 1423500
    assert company.l10n_co_ne_aux_transporte == 200000
    assert company.l10n_co_ne_uvt == 49799
test("ORM: Configurar SMMLV, Aux Transporte, UVT", t_config_smmlv)

# --- 4.5 Employee NE fields ---
def t_employee_ne():
    emp = env['hr.employee'].search([], limit=1)
    if not emp:
        return
    assert hasattr(emp, 'l10n_co_ne_document_type')
    assert hasattr(emp, 'l10n_co_ne_worker_type')
    assert hasattr(emp, 'l10n_co_ne_payment_method')
    assert hasattr(emp, 'l10n_co_pila_eps_code')
    assert hasattr(emp, 'l10n_co_pila_afp_code')
    assert hasattr(emp, 'l10n_co_ne_colombian_abroad')
test("ORM: Employee tiene campos NE y PILA", t_employee_ne)

# --- 4.6 Configurar Employee NE ---
def t_config_employee():
    emp = env['hr.employee'].search([], limit=1)
    if not emp:
        return
    emp.write({
        'l10n_co_ne_document_type': 'CC',
        'l10n_co_ne_worker_type': '01',
        'l10n_co_ne_payment_method': '1',
        'l10n_co_pila_eps_code': 'EPS010',
        'l10n_co_pila_afp_code': 'AFP001',
    })
    emp.invalidate_recordset()
    assert emp.l10n_co_ne_document_type == 'CC'
test("ORM: Configurar Employee datos colombianos", t_config_employee)

# --- 4.7 Contract PILA fields ---
def t_contract_pila():
    contract = env['hr.contract'].search([('state', '=', 'open')], limit=1)
    if not contract:
        contract = env['hr.contract'].search([], limit=1)
    if not contract:
        results.append(("SKIP", "Contract PILA: No hay contratos"))
        return
    assert hasattr(contract, 'l10n_co_pila_tipo_cotizante')
    assert hasattr(contract, 'l10n_co_pila_subtipo_cotizante')
    assert hasattr(contract, 'l10n_co_pila_clase_riesgo')
    assert hasattr(contract, 'l10n_co_ne_contract_type')
    assert hasattr(contract, 'l10n_co_ne_integral_salary')
    assert hasattr(contract, 'l10n_co_payroll_period')
test("ORM: Contract tiene campos PILA", t_contract_pila)

# --- 4.8 Configurar Contract PILA ---
def t_config_contract():
    contract = env['hr.contract'].search([('state', '=', 'open')], limit=1)
    if not contract:
        contract = env['hr.contract'].search([], limit=1)
    if not contract:
        return
    contract.write({
        'l10n_co_pila_tipo_cotizante': '01',
        'l10n_co_pila_subtipo_cotizante': '00',
        'l10n_co_pila_clase_riesgo': '1',
    })
    contract.invalidate_recordset()
    assert contract.l10n_co_pila_tipo_cotizante == '01'
test("ORM: Configurar Contract datos PILA", t_config_contract)

# --- 4.9 Payslip NE fields ---
def t_payslip_ne():
    payslip = env['hr.payslip'].search([], limit=1)
    if not payslip:
        results.append(("SKIP", "Payslip NE: No hay nominas"))
        return
    assert hasattr(payslip, 'l10n_co_ne_state')
    assert hasattr(payslip, 'l10n_co_ne_cune')
    assert hasattr(payslip, 'l10n_co_ne_consecutive')
    assert hasattr(payslip, 'l10n_co_ne_is_adjustment')
test("ORM: Payslip tiene campos NE", t_payslip_ne)

# --- 4.10 Salary rules loaded ---
def t_salary_rules():
    rules = env['hr.salary.rule'].search([('l10n_co_ne_dian_concept', '!=', False)])
    assert len(rules) >= 40, f"Solo {len(rules)} reglas con concepto DIAN"
    concepts = rules.mapped('l10n_co_ne_dian_concept')
    assert 'Sueldo' in concepts, "Falta concepto Sueldo"
    assert 'Salud' in concepts, "Falta concepto Salud"
    assert 'FondoPension' in concepts, "Falta concepto FondoPension"
    assert 'Transporte' in concepts, "Falta concepto Transporte"
test("ORM: 40+ reglas salariales con concepto DIAN", t_salary_rules)

# --- 4.11 UGPP wizard ---
def t_ugpp_wizard():
    wiz = env['l10n_co_nomina.ugpp.wizard'].create({
        'date_from': '2026-01-01',
        'date_to': '2026-01-31',
    })
    assert wiz.id > 0
    wiz.unlink()
test("ORM: Crear wizard UGPP", t_ugpp_wizard)

# --- 4.12 Provision ---
def t_provision_create():
    company = env['res.company'].search([], limit=1)
    prov = env['l10n.co.hr.provision'].create({
        'name': 'TEST-PROV-2026-01',
        'year': 2026,
        'month': '01',
        'company_id': company.id,
    })
    assert prov.id > 0
    assert prov.state == 'draft'
    assert prov.currency_id, "currency_id debe estar via related"
    prov.unlink()
test("ORM: Crear provision con currency_id", t_provision_create)

# --- 4.13 Liquidacion ---
def t_liquidacion_create():
    emp = env['hr.employee'].search([], limit=1)
    contract = env['hr.contract'].search([], limit=1)
    company = env['res.company'].search([], limit=1)
    if not emp or not contract:
        results.append(("SKIP", "Liquidacion: No hay empleados/contratos"))
        return
    liq = env['l10n.co.hr.liquidacion'].create({
        'employee_id': emp.id,
        'contract_id': contract.id,
        'company_id': company.id,
        'date_start': '2025-01-01',
        'date_end': '2026-01-15',
        'cause': 'sin_justa',
    })
    assert liq.id > 0
    assert liq.state == 'draft'
    assert liq.currency_id, "currency_id debe estar via related"
    liq.unlink()
test("ORM: Crear liquidacion con currency_id", t_liquidacion_create)

# --- 4.14 Retefuente UVT ---
def t_retefuente_uvt():
    uvts = env['l10n.co.retefuente.uvt'].search([])
    assert len(uvts) > 0, "No hay registros UVT"
test("ORM: Tabla Retefuente UVT tiene datos", t_retefuente_uvt)

# --- 4.15 PILA wizard ---
def t_pila_wizard():
    wiz = env['l10n.co.hr.pila.wizard'].create({
        'date_from': '2026-01-01',
        'date_to': '2026-01-31',
    })
    assert wiz.id > 0
    wiz.unlink()
test("ORM: Crear wizard PILA", t_pila_wizard)

# --- 4.16 Salary rule computed field ---
def t_salary_rule_computed():
    rule = env['hr.salary.rule'].search([('l10n_co_ne_dian_concept', '=', 'Salud')], limit=1)
    if rule:
        assert rule.l10n_co_ne_is_deduction == True, "Salud debe ser deduccion"
    rule2 = env['hr.salary.rule'].search([('l10n_co_ne_dian_concept', '=', 'Sueldo')], limit=1)
    if rule2:
        assert rule2.l10n_co_ne_is_deduction == False, "Sueldo no debe ser deduccion"
test("ORM: Campo computado is_deduction", t_salary_rule_computed)

# --- 4.17 Embargo states ---
def t_embargo_states():
    emp = env['hr.employee'].search([], limit=1)
    if not emp:
        return
    embargo = env['l10n.co.hr.embargo'].create({
        'name': 'TEST-STATE',
        'employee_id': emp.id,
        'tipo_embargo': 'civil',
        'valor_fijo': 100000,
        'juzgado': 'Test',
        'date_start': '2026-01-01',
    })
    assert embargo.state == 'active'
    embargo.write({'state': 'suspended'})
    assert embargo.state == 'suspended'
    embargo.write({'state': 'closed'})
    assert embargo.state == 'closed'
    embargo.unlink()
test("ORM: Embargo transiciones de estado", t_embargo_states)

# --- PRINT ---
print("")
passed = sum(1 for s,_ in results if s == "PASS")
failed = sum(1 for s,_ in results if s == "FAIL")
skipped = sum(1 for s,_ in results if s == "SKIP")
for status, name in results:
    icon = {"PASS": "OK", "FAIL": "XX", "SKIP": "--"}.get(status, "??")
    print(f"  [{icon}] {name}")
print(f"\n  Pruebas ORM: {passed} PASS, {failed} FAIL, {skipped} SKIP de {len(results)}")

env.cr.rollback()
ORMEOF

echo ""
echo "================================================================"
echo "  SET DE PRUEBAS COMPLETADO"
echo "================================================================"
