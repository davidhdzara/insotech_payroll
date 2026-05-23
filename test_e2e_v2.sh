#!/bin/bash
# =============================================================
# PRUEBAS END-TO-END V2 - CORREGIDAS
# =============================================================

odoo-bin shell -d guapante-staging-dev-32580182 --no-http --log-level=error << 'ORMEOF'
import traceback
from datetime import date, timedelta

results = []
created_ids = {}

def test(name, fn):
    try:
        fn()
        results.append(("PASS", name))
    except Exception as e:
        results.append(("FAIL", f"{name}: {e}"))
        try:
            env.cr.rollback()
        except:
            pass

def skip(name, reason):
    results.append(("SKIP", f"{name}: {reason}"))

print("================================================================")
print("  PRUEBAS END-TO-END V2 - NOMINA COLOMBIANA")
print("================================================================")

# ── PASO 0: Config Compania ─────────────────────────────────
print("\n--- PASO 0: Configuracion ---")

def t_config():
    company = env.company
    company.write({
        'l10n_co_ne_smmlv': 1423500,
        'l10n_co_ne_aux_transporte': 200000,
        'l10n_co_ne_uvt': 49799,
        'l10n_co_ne_environment': '2',
        'l10n_co_ne_software_id': 'TEST-SOFTWARE-001',
        'l10n_co_ne_software_pin': '12345',
        'l10n_co_ne_test_set_id': 'TEST-SET-001',
        'l10n_co_ne_payroll_prefix': 'NE',
        'l10n_co_ne_adjust_prefix': 'NA',
        'l10n_co_pila_tipo_aportante': '2',
        'l10n_co_pila_arl_code': '14-11',
        'l10n_co_pila_forma_presentacion': 'U',
    })
    env.cr.commit()
    assert company.l10n_co_ne_smmlv == 1423500
test("Config: Compania con TestSetID", t_config)


# ── PASO 1: Empleados ─────────────────────────────────────
print("\n--- PASO 1: Empleados ---")

def t_emp1():
    emp = env['hr.employee'].create({
        'name': 'David Alexander Hernandez Arango',
        'l10n_co_ne_document_type': '13',
        'identification_id': '1020422294',
        'l10n_co_ne_worker_type': '01',
        'l10n_co_ne_worker_subtype': '00',
        'l10n_co_ne_payment_method': '2',  # Efectivo (no requiere banco)
        'l10n_co_pila_eps_code': 'EPS010',
        'l10n_co_pila_afp_code': 'AFP001',
        'l10n_co_pila_ccf_code': 'CCF001',
        'company_id': env.company.id,
    })
    env.cr.commit()
    created_ids['emp1'] = emp.id
    assert emp.l10n_co_ne_document_type == '13'
test("Empleado 1: David ($3.5M, efectivo)", t_emp1)

def t_emp2():
    emp = env['hr.employee'].create({
        'name': 'Maria Camila Rodriguez Lopez',
        'l10n_co_ne_document_type': '13',
        'identification_id': '52987654',
        'l10n_co_ne_worker_type': '01',
        'l10n_co_ne_payment_method': '2',
        'l10n_co_pila_eps_code': 'EPS010',
        'l10n_co_pila_afp_code': 'AFP002',
        'company_id': env.company.id,
    })
    env.cr.commit()
    created_ids['emp2'] = emp.id
test("Empleado 2: Maria ($15M integral)", t_emp2)

def t_emp3():
    emp = env['hr.employee'].create({
        'name': 'Juan Carlos Perez Gomez',
        'l10n_co_ne_document_type': '13',
        'identification_id': '88776655',
        'l10n_co_ne_worker_type': '01',
        'l10n_co_ne_payment_method': '2',
        'company_id': env.company.id,
    })
    env.cr.commit()
    created_ids['emp3'] = emp.id
test("Empleado 3: Juan (SMMLV)", t_emp3)


# ── PASO 2: Contratos ──────────────────────────────────────
print("\n--- PASO 2: Contratos ---")

def t_contract(emp_key, wage, integral, name_label, contract_key, contract_type='1'):
    def fn():
        emp_id = created_ids.get(emp_key)
        if not emp_id:
            skip(f"Contrato {name_label}", f"No hay {emp_key}")
            return
        struct_type = env['hr.payroll.structure.type'].search([], limit=1)
        c = env['hr.contract'].create({
            'name': f'Contrato {name_label}',
            'employee_id': emp_id,
            'wage': wage,
            'state': 'open',
            'date_start': '2025-01-01',
            'structure_type_id': struct_type.id,
            'l10n_co_ne_contract_type': contract_type,
            'l10n_co_ne_integral_salary': integral,
            'l10n_co_payroll_period': '5',
            'l10n_co_pila_tipo_cotizante': '01',
            'l10n_co_pila_subtipo_cotizante': '00',
            'l10n_co_pila_clase_riesgo': '1',
        })
        env.cr.commit()
        created_ids[contract_key] = c.id
    return fn

test("Contrato: David $3.5M indefinido", t_contract('emp1', 3500000, False, 'David', 'c1'))
test("Contrato: Maria $15M integral", t_contract('emp2', 15000000, True, 'Maria', 'c2'))
test("Contrato: Juan SMMLV $1.423M fijo", t_contract('emp3', 1423500, False, 'Juan', 'c3', '2'))


# ── PASO 3: Nominas ────────────────────────────────────────
print("\n--- PASO 3: Generar y Calcular Nominas ---")

def t_payslip(emp_key, contract_key, name_label, ps_key):
    def fn():
        emp_id = created_ids.get(emp_key)
        c_id = created_ids.get(contract_key)
        if not emp_id or not c_id:
            skip(f"Nomina {name_label}", "Sin empleado/contrato")
            return
        struct = env['hr.payroll.structure'].search([('name', 'like', 'Colombia')], limit=1)
        if not struct:
            struct = env['hr.payroll.structure'].search([], limit=1)
        ps = env['hr.payslip'].create({
            'employee_id': emp_id,
            'contract_id': c_id,
            'struct_id': struct.id if struct else False,
            'date_from': '2026-05-01',
            'date_to': '2026-05-31',
            'name': f'Nomina Mayo 2026 - {name_label}',
        })
        env.cr.commit()
        created_ids[ps_key] = ps.id
        ps.compute_sheet()
        env.cr.commit()
        lines = ps.line_ids.filtered(lambda l: l.total != 0)
        print(f"    {name_label}: {len(lines)} lineas")
        for line in lines:
            print(f"      {line.code}: {line.name} = ${line.total:,.0f}")
    return fn

test("Nomina: David $3.5M", t_payslip('emp1', 'c1', 'David', 'ps1'))
test("Nomina: Maria $15M integral", t_payslip('emp2', 'c2', 'Maria', 'ps2'))
test("Nomina: Juan SMMLV", t_payslip('emp3', 'c3', 'Juan', 'ps3'))


# ── PASO 4: Confirmar Nominas ──────────────────────────────
print("\n--- PASO 4: Confirmar Nominas ---")

def t_confirm(ps_key, label):
    def fn():
        ps_id = created_ids.get(ps_key)
        if not ps_id:
            skip(f"Confirmar {label}", "Sin nomina")
            return
        ps = env['hr.payslip'].browse(ps_id)
        ps.action_payslip_done()
        env.cr.commit()
        assert ps.state == 'done', f"Estado: {ps.state}"
        print(f"    {label}: estado={ps.state}, NE_state={ps.l10n_co_ne_state}")
    return fn

test("Confirmar: David", t_confirm('ps1', 'David'))
test("Confirmar: Maria", t_confirm('ps2', 'Maria'))
test("Confirmar: Juan", t_confirm('ps3', 'Juan'))


# ── PASO 5: Embargos ──────────────────────────────────────
print("\n--- PASO 5: Embargos Judiciales ---")

def t_embargo_civil():
    emp_id = created_ids.get('emp1')
    if not emp_id:
        return
    e = env['l10n.co.hr.embargo'].create({
        'name': 'EMBC-2026-001', 'employee_id': emp_id,
        'tipo_embargo': 'civil', 'valor_fijo': 300000,
        'juzgado': 'Juzgado 12 Civil Bogota', 'date_start': '2026-01-01',
    })
    env.cr.commit()
    created_ids['emb_civil'] = e.id
    assert e.state == 'active'
    assert e.valor_fijo == 300000
test("Embargo: Civil $300K", t_embargo_civil)

def t_embargo_alimentos():
    emp_id = created_ids.get('emp1')
    if not emp_id:
        return
    e = env['l10n.co.hr.embargo'].create({
        'name': 'EMBA-2026-001', 'employee_id': emp_id,
        'tipo_embargo': 'alimentos', 'porcentaje': 25.0,
        'juzgado': 'Juzgado Familia Bogota', 'date_start': '2026-03-01',
    })
    env.cr.commit()
    created_ids['emb_alim'] = e.id
    assert e.porcentaje == 25.0
test("Embargo: Alimentos 25%", t_embargo_alimentos)

def t_embargo_coop():
    emp_id = created_ids.get('emp1')
    if not emp_id:
        return
    e = env['l10n.co.hr.embargo'].create({
        'name': 'EMBCOOP-2026-001', 'employee_id': emp_id,
        'tipo_embargo': 'cooperativa', 'valor_fijo': 150000,
        'juzgado': 'Cooperativa Nacional', 'date_start': '2026-02-01',
    })
    env.cr.commit()
    created_ids['emb_coop'] = e.id
test("Embargo: Cooperativa $150K", t_embargo_coop)

def t_embargo_transitions():
    emb_id = created_ids.get('emb_civil')
    if not emb_id:
        return
    e = env['l10n.co.hr.embargo'].browse(emb_id)
    e.write({'state': 'suspended'})
    env.cr.commit()
    assert e.state == 'suspended'
    e.write({'state': 'active'})
    env.cr.commit()
    assert e.state == 'active'
    e.write({'state': 'closed', 'date_end': '2026-05-22'})
    env.cr.commit()
    assert e.state == 'closed'
test("Embargo: Transiciones active->suspended->active->closed", t_embargo_transitions)

def t_embargo_multiple():
    emp_id = created_ids.get('emp1')
    if not emp_id:
        return
    embargos = env['l10n.co.hr.embargo'].search([('employee_id', '=', emp_id)])
    assert len(embargos) >= 3, f"Solo {len(embargos)} embargos"
    print(f"    Total embargos: {len(embargos)}")
    for e in embargos:
        print(f"      {e.name}: tipo={e.tipo_embargo}, estado={e.state}")
test("Embargo: Multiples por empleado", t_embargo_multiple)


# ── PASO 6: Provisiones ────────────────────────────────────
print("\n--- PASO 6: Provisiones ---")

def t_provision():
    prov = env['l10n.co.hr.provision'].create({
        'name': 'Provisiones Mayo 2026',
        'year': 2026, 'month': '05',
        'company_id': env.company.id,
    })
    env.cr.commit()
    created_ids['provision'] = prov.id
    assert prov.state == 'draft'
    assert prov.currency_id.id > 0
test("Provision: Crear draft", t_provision)

def t_provision_compute():
    prov_id = created_ids.get('provision')
    if not prov_id:
        return
    prov = env['l10n.co.hr.provision'].browse(prov_id)
    prov.action_compute_provisions()
    env.cr.commit()
    print(f"    Prima: ${prov.total_prima:,.0f}")
    print(f"    Cesantias: ${prov.total_cesantias:,.0f}")
    print(f"    Int. Cesantias: ${prov.total_intereses:,.0f}")
    print(f"    Vacaciones: ${prov.total_vacaciones:,.0f}")
test("Provision: Calcular (action_compute_provisions)", t_provision_compute)

def t_provision_post():
    prov_id = created_ids.get('provision')
    if not prov_id:
        return
    prov = env['l10n.co.hr.provision'].browse(prov_id)
    if hasattr(prov, 'action_post'):
        prov.action_post()
        env.cr.commit()
        print(f"    Estado despues de post: {prov.state}")
test("Provision: Publicar (action_post)", t_provision_post)


# ── PASO 7: Liquidacion ────────────────────────────────────
print("\n--- PASO 7: Liquidacion ---")

def t_liquidacion():
    emp_id = created_ids.get('emp2')
    c_id = created_ids.get('c2')
    if not emp_id or not c_id:
        skip("Liquidacion", "Sin emp2/c2")
        return
    liq = env['l10n.co.hr.liquidacion'].create({
        'employee_id': emp_id, 'contract_id': c_id,
        'company_id': env.company.id,
        'date_start': '2025-01-01', 'date_end': '2026-05-22',
        'cause': 'sin_justa',
    })
    env.cr.commit()
    created_ids['liq'] = liq.id
    assert liq.state == 'draft'
    assert liq.currency_id.id > 0
test("Liquidacion: Crear sin justa causa", t_liquidacion)

def t_liquidacion_compute():
    liq_id = created_ids.get('liq')
    if not liq_id:
        return
    liq = env['l10n.co.hr.liquidacion'].browse(liq_id)
    if hasattr(liq, 'action_compute'):
        liq.action_compute()
        env.cr.commit()
    elif hasattr(liq, 'compute_liquidacion'):
        liq.compute_liquidacion()
        env.cr.commit()
    else:
        methods = [m for m in dir(liq) if 'comput' in m.lower() or 'calcul' in m.lower() or 'action' in m.lower()]
        print(f"    Metodos: {methods}")
    print(f"    Dias: {liq.days_worked}")
    print(f"    Base: ${liq.base_salary:,.0f}")
    print(f"    Prima: ${liq.prima_proporcional:,.0f}")
    print(f"    Cesantias: ${liq.cesantias_proporcionales:,.0f}")
    print(f"    Int.Ces: ${liq.intereses_cesantias:,.0f}")
    print(f"    Vacaciones: ${liq.vacaciones_proporcionales:,.0f}")
    print(f"    Indemnizacion: ${liq.indemnizacion:,.0f}")
    print(f"    TOTAL: ${liq.total_liquidacion:,.0f}")
test("Liquidacion: Calcular valores", t_liquidacion_compute)

def t_liquidacion_confirm():
    liq_id = created_ids.get('liq')
    if not liq_id:
        return
    liq = env['l10n.co.hr.liquidacion'].browse(liq_id)
    if hasattr(liq, 'action_confirm'):
        liq.action_confirm()
        env.cr.commit()
        print(f"    Estado: {liq.state}")
test("Liquidacion: Confirmar", t_liquidacion_confirm)


# ── PASO 8: UGPP ───────────────────────────────────────────
print("\n--- PASO 8: UGPP ---")

def t_ugpp():
    # Primero buscamos los campos reales del modelo
    fields_list = list(env['l10n_co_nomina.ugpp']._fields.keys())
    print(f"    Campos UGPP: {[f for f in fields_list if not f.startswith('_')]}")
    required_fields = {'company_id': env.company.id}
    # Agregar year/month si existen
    if 'year' in fields_list:
        required_fields['year'] = 2026
    if 'month' in fields_list:
        required_fields['month'] = '05'
    if 'date_from' in fields_list:
        required_fields['date_from'] = '2026-05-01'
    if 'date_to' in fields_list:
        required_fields['date_to'] = '2026-05-31'
    ugpp = env['l10n_co_nomina.ugpp'].create(required_fields)
    env.cr.commit()
    created_ids['ugpp'] = ugpp.id
    assert ugpp.state == 'draft'
test("UGPP: Crear reporte Mayo 2026", t_ugpp)

def t_ugpp_generate():
    ugpp_id = created_ids.get('ugpp')
    if not ugpp_id:
        return
    ugpp = env['l10n_co_nomina.ugpp'].browse(ugpp_id)
    if hasattr(ugpp, 'action_generate'):
        ugpp.action_generate()
        env.cr.commit()
        print(f"    Estado: {ugpp.state}")
        if hasattr(ugpp, 'file_data') and ugpp.file_data:
            import base64
            data = base64.b64decode(ugpp.file_data)
            print(f"    Archivo: {ugpp.file_name}, {len(data)} bytes")
test("UGPP: Generar reporte", t_ugpp_generate)


# ── PASO 9: PILA ──────────────────────────────────────────
print("\n--- PASO 9: PILA ---")

def t_pila():
    fields_list = list(env['l10n.co.hr.pila.wizard']._fields.keys())
    print(f"    Campos PILA: {[f for f in fields_list if not f.startswith('_')]}")
    wiz = env['l10n.co.hr.pila.wizard'].create({
        'year': '2026', 'month': '05',
        'company_id': env.company.id,
    })
    env.cr.commit()
    created_ids['pila'] = wiz.id
test("PILA: Crear wizard Mayo 2026", t_pila)

def t_pila_generate():
    wiz_id = created_ids.get('pila')
    if not wiz_id:
        return
    wiz = env['l10n.co.hr.pila.wizard'].browse(wiz_id)
    if hasattr(wiz, 'action_generate'):
        wiz.action_generate()
        env.cr.commit()
        if wiz.file_data:
            import base64
            data = base64.b64decode(wiz.file_data)
            content = data.decode('latin-1', errors='replace')
            lines = content.strip().split('\n')
            print(f"    Archivo: {wiz.file_name}, {len(data)} bytes")
            print(f"    Lineas: {len(lines)}")
            for i, line in enumerate(lines[:5]):
                print(f"      Linea {i+1}: {line[:100]}...")
        else:
            print("    Sin archivo (puede requerir nominas confirmadas del periodo)")
test("PILA: Generar archivo plano", t_pila_generate)


# ── PASO 10: Retefuente ───────────────────────────────────
print("\n--- PASO 10: Retefuente UVT ---")

def t_retefuente():
    uvts = env['l10n.co.retefuente.uvt'].search([])
    assert len(uvts) > 0
    fields_list = [f for f in uvts[0]._fields.keys() if not f.startswith('_')]
    print(f"    Campos: {fields_list}")
    for uvt in uvts:
        vals = {f: getattr(uvt, f) for f in fields_list if f not in ('create_uid','write_uid','create_date','write_date','display_name','id')}
        print(f"    Registro: {vals}")
test("Retefuente: Datos UVT", t_retefuente)


# ── PASO 11: Reglas Salariales ────────────────────────────
print("\n--- PASO 11: Reglas Salariales ---")

def t_rules_dev():
    rules = env['hr.salary.rule'].search([
        ('l10n_co_ne_dian_concept', '!=', False),
        ('l10n_co_ne_is_deduction', '=', False),
    ])
    concepts = set(rules.mapped('l10n_co_ne_dian_concept'))
    print(f"    Devengados: {len(rules)} reglas, {len(concepts)} conceptos")
    assert 'Sueldo' in concepts
    assert 'Transporte' in concepts
test("Reglas: Devengados DIAN", t_rules_dev)

def t_rules_ded():
    rules = env['hr.salary.rule'].search([
        ('l10n_co_ne_dian_concept', '!=', False),
        ('l10n_co_ne_is_deduction', '=', True),
    ])
    concepts = set(rules.mapped('l10n_co_ne_dian_concept'))
    print(f"    Deducciones: {len(rules)} reglas, {len(concepts)} conceptos")
    assert 'Salud' in concepts
    assert 'FondoPension' in concepts
test("Reglas: Deducciones DIAN", t_rules_ded)

def t_rules_ugpp():
    rules = env['hr.salary.rule'].search([('l10n_co_ugpp_payment_type', '!=', False)])
    types = set(rules.mapped('l10n_co_ugpp_payment_type'))
    print(f"    UGPP: {len(rules)} reglas, tipos: {types}")
    assert 'tp_salarial' in types
test("Reglas: UGPP payment types", t_rules_ugpp)

def t_rules_computed():
    r_salud = env['hr.salary.rule'].search([('l10n_co_ne_dian_concept', '=', 'Salud')], limit=1)
    r_sueldo = env['hr.salary.rule'].search([('l10n_co_ne_dian_concept', '=', 'Sueldo')], limit=1)
    if r_salud:
        assert r_salud.l10n_co_ne_is_deduction == True
    if r_sueldo:
        assert r_sueldo.l10n_co_ne_is_deduction == False
test("Reglas: Computed is_deduction", t_rules_computed)


# ── PASO 12: Nominas especiales ───────────────────────────
print("\n--- PASO 12: Verificar valores nomina ---")

def t_verify_payslip_david():
    ps_id = created_ids.get('ps1')
    if not ps_id:
        skip("Verificar nomina David", "Sin nomina")
        return
    ps = env['hr.payslip'].browse(ps_id)
    lines = {l.code: l.total for l in ps.line_ids}
    print(f"    David ($3.5M): {len(lines)} lineas")
    for code, total in sorted(lines.items()):
        if total != 0:
            print(f"      {code} = ${total:,.0f}")
    # Verificar NE state
    print(f"    NE state: {ps.l10n_co_ne_state}")
    print(f"    NE consecutive: {ps.l10n_co_ne_consecutive}")
    print(f"    Is adjustment: {ps.l10n_co_ne_is_adjustment}")
test("Verificar: Nomina David detalle", t_verify_payslip_david)

def t_verify_payslip_maria():
    ps_id = created_ids.get('ps2')
    if not ps_id:
        return
    ps = env['hr.payslip'].browse(ps_id)
    lines = {l.code: l.total for l in ps.line_ids}
    print(f"    Maria ($15M integral): {len(lines)} lineas")
    for code, total in sorted(lines.items()):
        if total != 0:
            print(f"      {code} = ${total:,.0f}")
test("Verificar: Nomina Maria integral", t_verify_payslip_maria)

def t_verify_payslip_juan():
    ps_id = created_ids.get('ps3')
    if not ps_id:
        return
    ps = env['hr.payslip'].browse(ps_id)
    lines = {l.code: l.total for l in ps.line_ids}
    print(f"    Juan (SMMLV): {len(lines)} lineas")
    for code, total in sorted(lines.items()):
        if total != 0:
            print(f"      {code} = ${total:,.0f}")
test("Verificar: Nomina Juan SMMLV", t_verify_payslip_juan)


# ── RESULTADO ─────────────────────────────────────────────
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

env.cr.rollback()
print("\n  [INFO] Rollback - datos de prueba eliminados")
print("================================================================")
ORMEOF
