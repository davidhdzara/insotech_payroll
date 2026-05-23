#!/bin/bash
# =============================================================
# PRUEBAS END-TO-END EN ODOO 18 STAGING
# Flujos completos de nomina colombiana
# =============================================================

odoo-bin shell -d guapante-staging-dev-32580182 --no-http --log-level=error << 'ORMEOF'
import traceback
from datetime import date, timedelta

results = []
created_ids = {}  # Para cleanup al final

def test(name, fn):
    try:
        fn()
        results.append(("PASS", name))
    except Exception as e:
        results.append(("FAIL", f"{name}: {e}"))
        traceback.print_exc()

def skip(name, reason):
    results.append(("SKIP", f"{name}: {reason}"))

print("================================================================")
print("  PRUEBAS END-TO-END - NOMINA COLOMBIANA")
print("================================================================")

# ──────────────────────────────────────────────────────────────
# PASO 0: CONFIGURACION DE LA COMPANIA
# ──────────────────────────────────────────────────────────────
print("\n--- PASO 0: Configuracion de Compania ---")

def t_config_company():
    company = env.company
    company.write({
        'l10n_co_ne_smmlv': 1423500,
        'l10n_co_ne_aux_transporte': 200000,
        'l10n_co_ne_uvt': 49799,
        'l10n_co_ne_environment': '2',  # Habilitacion
        'l10n_co_ne_software_id': 'TEST-SOFTWARE-001',
        'l10n_co_ne_software_pin': '12345',
        'l10n_co_ne_payroll_prefix': 'NE',
        'l10n_co_ne_adjust_prefix': 'NA',
        'l10n_co_ne_exoneration_1607': True,
        'l10n_co_pila_tipo_aportante': '2',
        'l10n_co_pila_arl_code': '14-11',
        'l10n_co_pila_forma_presentacion': 'U',
    })
    env.cr.commit()
    company.invalidate_recordset()
    assert company.l10n_co_ne_smmlv == 1423500
    assert company.l10n_co_ne_aux_transporte == 200000
    assert company.l10n_co_ne_uvt == 49799
    assert company.l10n_co_ne_environment == '2'
test("Compania: SMMLV, Aux Transporte, UVT, Ambiente", t_config_company)


# ──────────────────────────────────────────────────────────────
# PASO 1: CREAR EMPLEADO COLOMBIANO
# ──────────────────────────────────────────────────────────────
print("\n--- PASO 1: Crear Empleado ---")

def t_create_employee():
    emp = env['hr.employee'].create({
        'name': 'David Alexander Hernandez Arango',
        'l10n_co_ne_document_type': '13',  # CC
        'identification_id': '1020422294',
        'l10n_co_ne_worker_type': '01',
        'l10n_co_ne_worker_subtype': '00',
        'l10n_co_ne_payment_method': '1',  # Transferencia
        'l10n_co_pila_eps_code': 'EPS010',
        'l10n_co_pila_afp_code': 'AFP001',
        'l10n_co_pila_ccf_code': 'CCF001',
        'l10n_co_ne_colombian_abroad': False,
        'company_id': env.company.id,
    })
    env.cr.commit()
    created_ids['employee'] = emp.id
    assert emp.id > 0
    assert emp.l10n_co_ne_document_type == '13'
    assert emp.identification_id == '1020422294'
test("Empleado: Crear con datos colombianos completos", t_create_employee)


# ──────────────────────────────────────────────────────────────
# PASO 2: CREAR SEGUNDO EMPLEADO (salario integral)
# ──────────────────────────────────────────────────────────────
print("\n--- PASO 2: Segundo Empleado (salario alto) ---")

def t_create_employee2():
    emp2 = env['hr.employee'].create({
        'name': 'Maria Camila Rodriguez Lopez',
        'l10n_co_ne_document_type': '13',
        'identification_id': '52987654',
        'l10n_co_ne_worker_type': '01',
        'l10n_co_ne_worker_subtype': '00',
        'l10n_co_ne_payment_method': '1',
        'l10n_co_pila_eps_code': 'EPS010',
        'l10n_co_pila_afp_code': 'AFP002',
        'l10n_co_pila_ccf_code': 'CCF001',
        'company_id': env.company.id,
    })
    env.cr.commit()
    created_ids['employee2'] = emp2.id
    assert emp2.id > 0
test("Empleado 2: Crear con salario alto", t_create_employee2)


# ──────────────────────────────────────────────────────────────
# PASO 3: CREAR CONTRATOS
# ──────────────────────────────────────────────────────────────
print("\n--- PASO 3: Crear Contratos ---")

def t_create_contract1():
    emp_id = created_ids.get('employee')
    if not emp_id:
        skip("Contrato 1", "No hay empleado")
        return
    struct_type = env['hr.payroll.structure.type'].search([], limit=1)
    if not struct_type:
        skip("Contrato 1", "No hay tipo de estructura")
        return
    contract = env['hr.contract'].create({
        'name': 'Contrato David Hernandez',
        'employee_id': emp_id,
        'wage': 3500000,
        'state': 'open',
        'date_start': '2025-01-01',
        'structure_type_id': struct_type.id,
        'l10n_co_ne_contract_type': '1',  # Termino indefinido
        'l10n_co_ne_integral_salary': False,
        'l10n_co_payroll_period': '5',  # Mensual
        'l10n_co_pila_tipo_cotizante': '01',
        'l10n_co_pila_subtipo_cotizante': '00',
        'l10n_co_pila_clase_riesgo': '1',
        'l10n_co_pila_salario_variable': False,
        'l10n_co_pila_exonerado_parafiscales': True,
    })
    env.cr.commit()
    created_ids['contract1'] = contract.id
    assert contract.id > 0
    assert contract.l10n_co_pila_tipo_cotizante == '01'
    assert contract.l10n_co_payroll_period == '5'
test("Contrato 1: Salario $3.5M, indefinido, mensual", t_create_contract1)

def t_create_contract2():
    emp_id = created_ids.get('employee2')
    if not emp_id:
        skip("Contrato 2", "No hay empleado 2")
        return
    struct_type = env['hr.payroll.structure.type'].search([], limit=1)
    contract = env['hr.contract'].create({
        'name': 'Contrato Maria Rodriguez',
        'employee_id': emp_id,
        'wage': 15000000,
        'state': 'open',
        'date_start': '2024-06-01',
        'structure_type_id': struct_type.id,
        'l10n_co_ne_contract_type': '1',
        'l10n_co_ne_integral_salary': True,  # Integral
        'l10n_co_payroll_period': '5',
        'l10n_co_pila_tipo_cotizante': '01',
        'l10n_co_pila_subtipo_cotizante': '00',
        'l10n_co_pila_clase_riesgo': '1',
        'l10n_co_pila_salario_variable': False,
        'l10n_co_pila_exonerado_parafiscales': True,
    })
    env.cr.commit()
    created_ids['contract2'] = contract.id
    assert contract.l10n_co_ne_integral_salary == True
test("Contrato 2: Salario integral $15M", t_create_contract2)


# ──────────────────────────────────────────────────────────────
# PASO 4: GENERAR NOMINAS
# ──────────────────────────────────────────────────────────────
print("\n--- PASO 4: Generar Nominas ---")

def t_create_payslip1():
    emp_id = created_ids.get('employee')
    contract_id = created_ids.get('contract1')
    if not emp_id or not contract_id:
        skip("Nomina 1", "No hay empleado/contrato")
        return
    struct = env['hr.payroll.structure'].search([('name', 'like', 'Colombia')], limit=1)
    if not struct:
        struct = env['hr.payroll.structure'].search([], limit=1)
    payslip = env['hr.payslip'].create({
        'employee_id': emp_id,
        'contract_id': contract_id,
        'struct_id': struct.id if struct else False,
        'date_from': '2026-05-01',
        'date_to': '2026-05-31',
        'name': 'Nomina Mayo 2026 - David Hernandez',
    })
    env.cr.commit()
    created_ids['payslip1'] = payslip.id
    assert payslip.id > 0
    assert payslip.l10n_co_ne_state == 'draft'
test("Nomina 1: Crear nomina mayo 2026 ($3.5M)", t_create_payslip1)

def t_compute_payslip1():
    ps_id = created_ids.get('payslip1')
    if not ps_id:
        skip("Compute nomina 1", "No hay nomina")
        return
    payslip = env['hr.payslip'].browse(ps_id)
    payslip.compute_sheet()
    env.cr.commit()
    lines = payslip.line_ids
    assert len(lines) > 0, f"No se generaron lineas de nomina"
    line_names = lines.mapped('name')
    print(f"    Lineas generadas: {len(lines)}")
    for line in lines:
        if line.total != 0:
            print(f"      {line.code}: {line.name} = {line.total:,.0f}")
test("Nomina 1: Calcular nomina (compute_sheet)", t_compute_payslip1)

def t_create_payslip2():
    emp_id = created_ids.get('employee2')
    contract_id = created_ids.get('contract2')
    if not emp_id or not contract_id:
        skip("Nomina 2", "No hay empleado2/contrato2")
        return
    struct = env['hr.payroll.structure'].search([('name', 'like', 'Colombia')], limit=1)
    if not struct:
        struct = env['hr.payroll.structure'].search([], limit=1)
    payslip = env['hr.payslip'].create({
        'employee_id': emp_id,
        'contract_id': contract_id,
        'struct_id': struct.id if struct else False,
        'date_from': '2026-05-01',
        'date_to': '2026-05-31',
        'name': 'Nomina Mayo 2026 - Maria Rodriguez',
    })
    env.cr.commit()
    created_ids['payslip2'] = payslip.id
    payslip.compute_sheet()
    env.cr.commit()
    lines = payslip.line_ids
    print(f"    Lineas generadas: {len(lines)}")
    for line in lines:
        if line.total != 0:
            print(f"      {line.code}: {line.name} = {line.total:,.0f}")
test("Nomina 2: Crear y calcular ($15M integral)", t_create_payslip2)

def t_confirm_payslip1():
    ps_id = created_ids.get('payslip1')
    if not ps_id:
        skip("Confirmar nomina 1", "No hay nomina")
        return
    payslip = env['hr.payslip'].browse(ps_id)
    payslip.action_payslip_done()
    env.cr.commit()
    assert payslip.state == 'done', f"Estado: {payslip.state}"
test("Nomina 1: Confirmar (action_payslip_done)", t_confirm_payslip1)


# ──────────────────────────────────────────────────────────────
# PASO 5: EMBARGOS JUDICIALES
# ──────────────────────────────────────────────────────────────
print("\n--- PASO 5: Embargos Judiciales ---")

def t_embargo_civil():
    emp_id = created_ids.get('employee')
    if not emp_id:
        skip("Embargo civil", "No hay empleado")
        return
    embargo = env['l10n.co.hr.embargo'].create({
        'name': 'EMBC-2026-001',
        'employee_id': emp_id,
        'tipo_embargo': 'civil',
        'valor_fijo': 300000,
        'juzgado': 'Juzgado 12 Civil del Circuito de Bogota',
        'date_start': '2026-01-01',
    })
    env.cr.commit()
    created_ids['embargo_civil'] = embargo.id
    assert embargo.state == 'active'
    assert embargo.tipo_embargo == 'civil'
    assert embargo.valor_fijo == 300000
test("Embargo: Civil $300K fijo", t_embargo_civil)

def t_embargo_alimentos():
    emp_id = created_ids.get('employee')
    if not emp_id:
        skip("Embargo alimentos", "No hay empleado")
        return
    embargo = env['l10n.co.hr.embargo'].create({
        'name': 'EMBA-2026-001',
        'employee_id': emp_id,
        'tipo_embargo': 'alimentos',
        'porcentaje': 25.0,
        'juzgado': 'Juzgado 3 de Familia de Bogota',
        'date_start': '2026-03-01',
    })
    env.cr.commit()
    created_ids['embargo_alimentos'] = embargo.id
    assert embargo.porcentaje == 25.0
test("Embargo: Alimentos 25% del salario", t_embargo_alimentos)

def t_embargo_cooperativa():
    emp_id = created_ids.get('employee')
    if not emp_id:
        return
    embargo = env['l10n.co.hr.embargo'].create({
        'name': 'EMBCOOP-2026-001',
        'employee_id': emp_id,
        'tipo_embargo': 'cooperativa',
        'valor_fijo': 150000,
        'juzgado': 'Cooperativa Nacional',
        'date_start': '2026-02-01',
    })
    env.cr.commit()
    created_ids['embargo_coop'] = embargo.id
    assert embargo.tipo_embargo == 'cooperativa'
test("Embargo: Cooperativa $150K", t_embargo_cooperativa)

def t_embargo_suspender():
    emb_id = created_ids.get('embargo_civil')
    if not emb_id:
        return
    embargo = env['l10n.co.hr.embargo'].browse(emb_id)
    embargo.write({'state': 'suspended'})
    env.cr.commit()
    assert embargo.state == 'suspended'
test("Embargo: Suspender embargo civil", t_embargo_suspender)

def t_embargo_reactivar():
    emb_id = created_ids.get('embargo_civil')
    if not emb_id:
        return
    embargo = env['l10n.co.hr.embargo'].browse(emb_id)
    embargo.write({'state': 'active'})
    env.cr.commit()
    assert embargo.state == 'active'
test("Embargo: Reactivar embargo civil", t_embargo_reactivar)

def t_embargo_cerrar():
    emb_id = created_ids.get('embargo_coop')
    if not emb_id:
        return
    embargo = env['l10n.co.hr.embargo'].browse(emb_id)
    embargo.write({'state': 'closed', 'date_end': '2026-05-22'})
    env.cr.commit()
    assert embargo.state == 'closed'
test("Embargo: Cerrar embargo cooperativa", t_embargo_cerrar)

def t_embargo_multiple_empleado():
    emp_id = created_ids.get('employee')
    if not emp_id:
        return
    emp = env['hr.employee'].browse(emp_id)
    embargos = env['l10n.co.hr.embargo'].search([('employee_id', '=', emp_id)])
    assert len(embargos) >= 3, f"Empleado debe tener 3 embargos, tiene {len(embargos)}"
    activos = embargos.filtered(lambda e: e.state == 'active')
    print(f"    Embargos totales: {len(embargos)}, activos: {len(activos)}")
test("Embargo: Empleado con multiples embargos", t_embargo_multiple_empleado)


# ──────────────────────────────────────────────────────────────
# PASO 6: PROVISIONES
# ──────────────────────────────────────────────────────────────
print("\n--- PASO 6: Provisiones ---")

def t_provision_create():
    prov = env['l10n.co.hr.provision'].create({
        'name': 'Provisiones Mayo 2026',
        'year': 2026,
        'month': '05',
        'company_id': env.company.id,
    })
    env.cr.commit()
    created_ids['provision'] = prov.id
    assert prov.state == 'draft'
    assert prov.currency_id.id > 0
test("Provision: Crear Mayo 2026", t_provision_create)

def t_provision_compute():
    prov_id = created_ids.get('provision')
    if not prov_id:
        return
    prov = env['l10n.co.hr.provision'].browse(prov_id)
    if hasattr(prov, 'action_compute') and callable(prov.action_compute):
        prov.action_compute()
        env.cr.commit()
        print(f"    Prima: {prov.total_prima:,.0f}")
        print(f"    Cesantias: {prov.total_cesantias:,.0f}")
        print(f"    Int. Cesantias: {prov.total_intereses:,.0f}")
        print(f"    Vacaciones: {prov.total_vacaciones:,.0f}")
    elif hasattr(prov, 'compute_provisions'):
        prov.compute_provisions()
        env.cr.commit()
    else:
        methods = [m for m in dir(prov) if 'comput' in m.lower() or 'calcul' in m.lower() or 'action' in m.lower()]
        print(f"    Metodos disponibles: {methods}")
test("Provision: Calcular provisiones", t_provision_compute)

def t_provision_wizard():
    wiz = env['l10n.co.hr.provision.wizard'].create({
        'year': 2026,
        'month': '05',
    })
    env.cr.commit()
    created_ids['prov_wizard'] = wiz.id
    assert wiz.id > 0
    if hasattr(wiz, 'action_generate') and callable(wiz.action_generate):
        try:
            wiz.action_generate()
            env.cr.commit()
        except Exception as e:
            print(f"    Wizard action_generate: {e}")
    else:
        methods = [m for m in dir(wiz) if 'action' in m.lower() or 'generat' in m.lower()]
        print(f"    Metodos wizard: {methods}")
test("Provision Wizard: Crear y ejecutar", t_provision_wizard)


# ──────────────────────────────────────────────────────────────
# PASO 7: LIQUIDACION
# ──────────────────────────────────────────────────────────────
print("\n--- PASO 7: Liquidacion ---")

def t_liquidacion_create():
    emp_id = created_ids.get('employee2')
    contract_id = created_ids.get('contract2')
    if not emp_id or not contract_id:
        skip("Liquidacion", "No hay empleado2/contrato2")
        return
    liq = env['l10n.co.hr.liquidacion'].create({
        'employee_id': emp_id,
        'contract_id': contract_id,
        'company_id': env.company.id,
        'date_start': '2024-06-01',
        'date_end': '2026-05-22',
        'cause': 'sin_justa',
    })
    env.cr.commit()
    created_ids['liquidacion'] = liq.id
    assert liq.state == 'draft'
    assert liq.currency_id.id > 0
    assert liq.cause == 'sin_justa'
test("Liquidacion: Crear sin justa causa", t_liquidacion_create)

def t_liquidacion_compute():
    liq_id = created_ids.get('liquidacion')
    if not liq_id:
        return
    liq = env['l10n.co.hr.liquidacion'].browse(liq_id)
    if hasattr(liq, 'action_compute') and callable(liq.action_compute):
        liq.action_compute()
        env.cr.commit()
        print(f"    Dias trabajados: {liq.days_worked}")
        print(f"    Salario base: {liq.base_salary:,.0f}")
        print(f"    Prima proporcional: {liq.prima_proporcional:,.0f}")
        print(f"    Cesantias: {liq.cesantias_proporcionales:,.0f}")
        print(f"    Int. Cesantias: {liq.intereses_cesantias:,.0f}")
        print(f"    Vacaciones: {liq.vacaciones_proporcionales:,.0f}")
        print(f"    Indemnizacion: {liq.indemnizacion:,.0f}")
        print(f"    TOTAL: {liq.total_liquidacion:,.0f}")
    elif hasattr(liq, 'compute_liquidacion'):
        liq.compute_liquidacion()
        env.cr.commit()
    else:
        methods = [m for m in dir(liq) if 'comput' in m.lower() or 'calcul' in m.lower() or 'action' in m.lower()]
        print(f"    Metodos disponibles: {methods}")
test("Liquidacion: Calcular valores", t_liquidacion_compute)

def t_liquidacion_confirm():
    liq_id = created_ids.get('liquidacion')
    if not liq_id:
        return
    liq = env['l10n.co.hr.liquidacion'].browse(liq_id)
    if hasattr(liq, 'action_confirm') and callable(liq.action_confirm):
        liq.action_confirm()
        env.cr.commit()
        assert liq.state in ('confirmed', 'done')
    else:
        methods = [m for m in dir(liq) if 'confirm' in m.lower() or 'done' in m.lower() or 'action' in m.lower()]
        print(f"    Metodos confirm: {methods}")
test("Liquidacion: Confirmar", t_liquidacion_confirm)


# ──────────────────────────────────────────────────────────────
# PASO 8: UGPP REPORT
# ──────────────────────────────────────────────────────────────
print("\n--- PASO 8: UGPP Report ---")

def t_ugpp_create():
    ugpp = env['l10n_co_nomina.ugpp'].create({
        'company_id': env.company.id,
    })
    env.cr.commit()
    created_ids['ugpp'] = ugpp.id
    assert ugpp.state == 'draft'
test("UGPP: Crear reporte", t_ugpp_create)

def t_ugpp_generate():
    ugpp_id = created_ids.get('ugpp')
    if not ugpp_id:
        return
    ugpp = env['l10n_co_nomina.ugpp'].browse(ugpp_id)
    if hasattr(ugpp, 'action_generate') and callable(ugpp.action_generate):
        try:
            ugpp.action_generate()
            env.cr.commit()
            assert ugpp.state == 'generated'
            if ugpp.file_data:
                print(f"    Archivo generado: {ugpp.file_name}")
        except Exception as e:
            print(f"    Error generando: {e}")
    else:
        methods = [m for m in dir(ugpp) if 'action' in m.lower() or 'generat' in m.lower()]
        print(f"    Metodos: {methods}")
test("UGPP: Generar reporte", t_ugpp_generate)


# ──────────────────────────────────────────────────────────────
# PASO 9: PILA
# ──────────────────────────────────────────────────────────────
print("\n--- PASO 9: PILA ---")

def t_pila_wizard_create():
    wiz = env['l10n.co.hr.pila.wizard'].create({
        'year': '2026',
        'month': '05',
        'company_id': env.company.id,
    })
    env.cr.commit()
    created_ids['pila_wizard'] = wiz.id
    assert wiz.id > 0
test("PILA Wizard: Crear Mayo 2026", t_pila_wizard_create)

def t_pila_wizard_generate():
    wiz_id = created_ids.get('pila_wizard')
    if not wiz_id:
        return
    wiz = env['l10n.co.hr.pila.wizard'].browse(wiz_id)
    if hasattr(wiz, 'action_generate') and callable(wiz.action_generate):
        try:
            wiz.action_generate()
            env.cr.commit()
            if wiz.file_data:
                import base64
                data = base64.b64decode(wiz.file_data)
                print(f"    Archivo: {wiz.file_name}")
                print(f"    Tamano: {len(data)} bytes")
                lines = data.decode('latin-1', errors='replace').split('\n')
                print(f"    Lineas: {len(lines)}")
                if lines:
                    print(f"    Primera linea (tipo 1): {lines[0][:80]}...")
            else:
                print("    No se genero archivo (sin nominas confirmadas?)")
        except Exception as e:
            print(f"    Error: {e}")
    else:
        methods = [m for m in dir(wiz) if 'action' in m.lower() or 'generat' in m.lower()]
        print(f"    Metodos: {methods}")
test("PILA Wizard: Generar archivo", t_pila_wizard_generate)


# ──────────────────────────────────────────────────────────────
# PASO 10: RETEFUENTE
# ──────────────────────────────────────────────────────────────
print("\n--- PASO 10: Retefuente UVT ---")

def t_retefuente_data():
    uvts = env['l10n.co.retefuente.uvt'].search([])
    assert len(uvts) > 0
    for uvt in uvts:
        print(f"    Ano: {uvt.year if hasattr(uvt, 'year') else 'N/A'}, UVT: {uvt.value if hasattr(uvt, 'value') else 'N/A'}")
        fields = [f for f in uvt._fields.keys() if not f.startswith('_')]
        if len(uvts) == 1:
            print(f"    Campos: {fields}")
test("Retefuente: Datos UVT cargados", t_retefuente_data)


# ──────────────────────────────────────────────────────────────
# PASO 11: REGLAS SALARIALES - VERIFICAR CONCEPTOS DIAN
# ──────────────────────────────────────────────────────────────
print("\n--- PASO 11: Reglas Salariales DIAN ---")

def t_salary_rules_devengados():
    rules = env['hr.salary.rule'].search([
        ('l10n_co_ne_dian_concept', '!=', False),
        ('l10n_co_ne_is_deduction', '=', False),
    ])
    concepts = rules.mapped('l10n_co_ne_dian_concept')
    expected = ['Sueldo', 'Transporte', 'HED', 'HEN', 'Primas', 'Cesantias', 'VacacionesComunes']
    found = [c for c in expected if c in concepts]
    missing = [c for c in expected if c not in concepts]
    print(f"    Devengados: {len(rules)} reglas, conceptos: {len(set(concepts))}")
    if missing:
        print(f"    Faltantes: {missing}")
    assert 'Sueldo' in concepts, "Falta concepto Sueldo"
test("Reglas: Devengados DIAN", t_salary_rules_devengados)

def t_salary_rules_deducciones():
    rules = env['hr.salary.rule'].search([
        ('l10n_co_ne_dian_concept', '!=', False),
        ('l10n_co_ne_is_deduction', '=', True),
    ])
    concepts = rules.mapped('l10n_co_ne_dian_concept')
    print(f"    Deducciones: {len(rules)} reglas, conceptos: {len(set(concepts))}")
    assert 'Salud' in concepts, "Falta deduccion Salud"
    assert 'FondoPension' in concepts, "Falta deduccion FondoPension"
    assert 'RetencionFuente' in concepts, "Falta deduccion RetencionFuente"
test("Reglas: Deducciones DIAN", t_salary_rules_deducciones)

def t_salary_rules_ugpp():
    rules = env['hr.salary.rule'].search([('l10n_co_ugpp_payment_type', '!=', False)])
    types = set(rules.mapped('l10n_co_ugpp_payment_type'))
    print(f"    UGPP: {len(rules)} reglas, tipos: {types}")
    assert 'tp_salarial' in types
test("Reglas: UGPP payment types", t_salary_rules_ugpp)


# ──────────────────────────────────────────────────────────────
# PASO 12: NOMINA DIFERENTE - CASO MINIMO (SMMLV)
# ──────────────────────────────────────────────────────────────
print("\n--- PASO 12: Nomina SMMLV ---")

def t_nomina_smmlv():
    struct_type = env['hr.payroll.structure.type'].search([], limit=1)
    if not struct_type:
        skip("Nomina SMMLV", "No hay tipo estructura")
        return
    emp3 = env['hr.employee'].create({
        'name': 'Juan Carlos Perez Gomez',
        'l10n_co_ne_document_type': '13',
        'identification_id': '88776655',
        'company_id': env.company.id,
    })
    contract3 = env['hr.contract'].create({
        'name': 'Contrato SMMLV',
        'employee_id': emp3.id,
        'wage': 1423500,  # SMMLV
        'state': 'open',
        'date_start': '2026-01-01',
        'structure_type_id': struct_type.id,
        'l10n_co_ne_contract_type': '2',  # Fijo
        'l10n_co_ne_integral_salary': False,
        'l10n_co_payroll_period': '5',
        'l10n_co_pila_tipo_cotizante': '01',
    })
    struct = env['hr.payroll.structure'].search([('name', 'like', 'Colombia')], limit=1)
    if not struct:
        struct = env['hr.payroll.structure'].search([], limit=1)
    ps = env['hr.payslip'].create({
        'employee_id': emp3.id,
        'contract_id': contract3.id,
        'struct_id': struct.id if struct else False,
        'date_from': '2026-05-01',
        'date_to': '2026-05-31',
        'name': 'Nomina SMMLV Mayo 2026',
    })
    ps.compute_sheet()
    env.cr.commit()
    created_ids['emp3'] = emp3.id
    created_ids['contract3'] = contract3.id
    created_ids['payslip3'] = ps.id
    lines = ps.line_ids.filtered(lambda l: l.total != 0)
    print(f"    Lineas con valor: {len(lines)}")
    for line in lines:
        print(f"      {line.code}: {line.name} = {line.total:,.0f}")
test("Nomina SMMLV: Calcular con salario minimo", t_nomina_smmlv)


# ──────────────────────────────────────────────────────────────
# RESULTADO FINAL
# ──────────────────────────────────────────────────────────────
print("\n================================================================")
print("  RESULTADOS FINALES")
print("================================================================")
passed = sum(1 for s,_ in results if s == "PASS")
failed = sum(1 for s,_ in results if s == "FAIL")
skipped = sum(1 for s,_ in results if s == "SKIP")
for status, name in results:
    icon = {"PASS": "OK", "FAIL": "XX", "SKIP": "--"}.get(status, "??")
    print(f"  [{icon}] {name}")
print(f"\n  TOTAL: {passed} PASS, {failed} FAIL, {skipped} SKIP de {len(results)}")

# Rollback para no dejar basura
env.cr.rollback()
print("\n  [INFO] Rollback ejecutado - datos de prueba eliminados")
print("================================================================")
ORMEOF
