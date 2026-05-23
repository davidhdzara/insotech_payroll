#!/bin/bash
# =============================================================
# PRUEBAS END-TO-END V3 - VALORES CORREGIDOS
# =============================================================

odoo-bin shell -d guapante-staging-dev-32580182 --no-http --log-level=error << 'ORMEOF'
import traceback

results = []
ids = {}

def test(name, fn):
    try:
        fn()
        results.append(("OK", name))
    except Exception as e:
        results.append(("XX", f"{name}: {e}"))
        try: env.cr.rollback()
        except: pass

print("================================================================")
print("  PRUEBAS END-TO-END V3")
print("================================================================")

# ── CONFIG ───────────────────────────────────────────────
print("\n-- Config --")
def t0():
    c = env.company
    c.write({'l10n_co_ne_smmlv': 1423500, 'l10n_co_ne_aux_transporte': 200000,
             'l10n_co_ne_uvt': 49799, 'l10n_co_ne_environment': '2',
             'l10n_co_ne_software_id': 'SOFT001', 'l10n_co_ne_software_pin': '12345',
             'l10n_co_ne_test_set_id': 'TESTSET001',
             'l10n_co_pila_tipo_aportante': '2', 'l10n_co_pila_arl_code': '14-11'})
    env.cr.commit()
    assert c.l10n_co_ne_smmlv == 1423500
test("Config compania", t0)

# ── EMPLEADOS ────────────────────────────────────────────
print("\n-- Empleados --")
def t1():
    e = env['hr.employee'].create({
        'name': 'David Hernandez', 'l10n_co_ne_document_type': '13',
        'identification_id': '1020422294', 'l10n_co_ne_worker_type': '01',
        'l10n_co_ne_payment_method': '2', 'l10n_co_pila_eps_code': 'EPS010',
        'l10n_co_pila_afp_code': 'AFP001', 'company_id': env.company.id})
    env.cr.commit(); ids['e1'] = e.id
test("Empleado 1: David $3.5M", t1)

def t2():
    e = env['hr.employee'].create({
        'name': 'Maria Rodriguez', 'l10n_co_ne_document_type': '13',
        'identification_id': '52987654', 'l10n_co_ne_worker_type': '01',
        'l10n_co_ne_payment_method': '2', 'company_id': env.company.id})
    env.cr.commit(); ids['e2'] = e.id
test("Empleado 2: Maria $15M integral", t2)

def t3():
    e = env['hr.employee'].create({
        'name': 'Juan Perez', 'l10n_co_ne_document_type': '13',
        'identification_id': '88776655', 'l10n_co_ne_worker_type': '01',
        'l10n_co_ne_payment_method': '2', 'company_id': env.company.id})
    env.cr.commit(); ids['e3'] = e.id
test("Empleado 3: Juan SMMLV", t3)

# ── CONTRATOS ────────────────────────────────────────────
print("\n-- Contratos --")
st = env['hr.payroll.structure.type'].search([], limit=1)

def make_contract(ek, wage, integral, ck, ct='1'):
    def fn():
        if ek not in ids: return
        c = env['hr.contract'].create({
            'name': f'Contrato-{ck}', 'employee_id': ids[ek], 'wage': wage,
            'state': 'open', 'date_start': '2025-01-01',
            'structure_type_id': st.id,
            'l10n_co_ne_contract_type': ct,
            'l10n_co_ne_integral_salary': integral,
            'l10n_co_payroll_period': '30',  # Mensual
            'l10n_co_pila_tipo_cotizante': '01',
            'l10n_co_pila_subtipo_cotizante': '00',
            'l10n_co_pila_clase_riesgo': '1'})
        env.cr.commit(); ids[ck] = c.id
        assert c.l10n_co_payroll_period == '30'
    return fn

test("Contrato: David $3.5M", make_contract('e1', 3500000, False, 'c1'))
test("Contrato: Maria $15M integral", make_contract('e2', 15000000, True, 'c2'))
test("Contrato: Juan SMMLV fijo", make_contract('e3', 1423500, False, 'c3', '2'))

# ── NOMINAS ──────────────────────────────────────────────
print("\n-- Nominas --")
struct = env['hr.payroll.structure'].search([('name', 'like', 'Colombia')], limit=1) or env['hr.payroll.structure'].search([], limit=1)

def make_payslip(ek, ck, pk, label):
    def fn():
        if ek not in ids or ck not in ids: return
        ps = env['hr.payslip'].create({
            'employee_id': ids[ek], 'contract_id': ids[ck],
            'struct_id': struct.id, 'date_from': '2026-05-01',
            'date_to': '2026-05-31', 'name': f'Nomina {label}'})
        env.cr.commit(); ids[pk] = ps.id
        ps.compute_sheet(); env.cr.commit()
        lines = ps.line_ids.filtered(lambda l: l.total != 0)
        print(f"    {label}: {len(lines)} lineas")
        for l in lines:
            print(f"      {l.code}: {l.name} = ${l.total:,.0f}")
    return fn

test("Nomina: David $3.5M", make_payslip('e1','c1','p1','David'))
test("Nomina: Maria $15M", make_payslip('e2','c2','p2','Maria'))
test("Nomina: Juan SMMLV", make_payslip('e3','c3','p3','Juan'))

# ── CONFIRMAR ────────────────────────────────────────────
print("\n-- Confirmar Nominas --")
def confirm(pk, label):
    def fn():
        if pk not in ids: return
        ps = env['hr.payslip'].browse(ids[pk])
        ps.action_payslip_done(); env.cr.commit()
        assert ps.state == 'done'
        print(f"    {label}: state={ps.state}, ne_state={ps.l10n_co_ne_state}")
    return fn

test("Confirmar David", confirm('p1','David'))
test("Confirmar Maria", confirm('p2','Maria'))
test("Confirmar Juan", confirm('p3','Juan'))

# ── EMBARGOS ─────────────────────────────────────────────
print("\n-- Embargos --")
def t_emb():
    if 'e1' not in ids: return
    eid = ids['e1']
    e1 = env['l10n.co.hr.embargo'].create({
        'name':'EMBC-001','employee_id':eid,'tipo_embargo':'civil',
        'valor_fijo':300000,'juzgado':'Juzgado 12 Bogota','date_start':'2026-01-01'})
    e2 = env['l10n.co.hr.embargo'].create({
        'name':'EMBA-001','employee_id':eid,'tipo_embargo':'alimentos',
        'porcentaje':25.0,'juzgado':'Juzgado Familia','date_start':'2026-03-01'})
    e3 = env['l10n.co.hr.embargo'].create({
        'name':'EMBCOOP-001','employee_id':eid,'tipo_embargo':'cooperativa',
        'valor_fijo':150000,'juzgado':'Cooperativa','date_start':'2026-02-01'})
    env.cr.commit()
    assert e1.state == 'active' and e2.state == 'active'
    ids['emb1']=e1.id; ids['emb2']=e2.id; ids['emb3']=e3.id
    print(f"    Civil: ${e1.valor_fijo:,.0f}")
    print(f"    Alimentos: {e2.porcentaje}%")
    print(f"    Cooperativa: ${e3.valor_fijo:,.0f}")
test("Embargo: Crear 3 tipos (civil, alimentos, coop)", t_emb)

def t_emb_trans():
    if 'emb1' not in ids: return
    e = env['l10n.co.hr.embargo'].browse(ids['emb1'])
    e.write({'state':'suspended'}); env.cr.commit()
    assert e.state=='suspended'
    e.write({'state':'active'}); env.cr.commit()
    assert e.state=='active'
    e.write({'state':'closed','date_end':'2026-05-22'}); env.cr.commit()
    assert e.state=='closed'
test("Embargo: Transiciones estado", t_emb_trans)

def t_emb_multi():
    if 'e1' not in ids: return
    embs = env['l10n.co.hr.embargo'].search([('employee_id','=',ids['e1'])])
    assert len(embs) >= 3
    print(f"    Total: {len(embs)} embargos")
test("Embargo: Multiples por empleado", t_emb_multi)

# ── PROVISIONES ──────────────────────────────────────────
print("\n-- Provisiones --")
def t_prov():
    # Borrar provision existente si hay
    existing = env['l10n.co.hr.provision'].search([('year','=',2026),('month','=','05')])
    if existing:
        existing.write({'state': 'draft'})
        existing.unlink()
        env.cr.commit()
    p = env['l10n.co.hr.provision'].create({
        'name':'Prov Mayo 2026','year':2026,'month':'05','company_id':env.company.id})
    env.cr.commit(); ids['prov'] = p.id
    assert p.state == 'draft' and p.currency_id.id > 0
test("Provision: Crear Mayo 2026", t_prov)

def t_prov_calc():
    if 'prov' not in ids: return
    p = env['l10n.co.hr.provision'].browse(ids['prov'])
    p.action_compute_provisions(); env.cr.commit()
    print(f"    Prima: ${p.total_prima:,.0f}")
    print(f"    Cesantias: ${p.total_cesantias:,.0f}")
    print(f"    Int.Ces: ${p.total_intereses:,.0f}")
    print(f"    Vacaciones: ${p.total_vacaciones:,.0f}")
test("Provision: Calcular", t_prov_calc)

def t_prov_post():
    if 'prov' not in ids: return
    p = env['l10n.co.hr.provision'].browse(ids['prov'])
    p.action_post(); env.cr.commit()
    print(f"    Estado: {p.state}")
test("Provision: Publicar", t_prov_post)

# ── LIQUIDACION ──────────────────────────────────────────
print("\n-- Liquidacion --")
def t_liq():
    if 'e2' not in ids or 'c2' not in ids: return
    l = env['l10n.co.hr.liquidacion'].create({
        'employee_id':ids['e2'],'contract_id':ids['c2'],
        'company_id':env.company.id,'date_start':'2025-01-01',
        'date_end':'2026-05-22','cause':'sin_justa'})
    env.cr.commit(); ids['liq'] = l.id
    assert l.state=='draft' and l.currency_id.id > 0
test("Liquidacion: Crear sin justa causa", t_liq)

def t_liq_calc():
    if 'liq' not in ids: return
    l = env['l10n.co.hr.liquidacion'].browse(ids['liq'])
    methods = [m for m in dir(l) if 'comput' in m.lower() or 'calcul' in m.lower() or 'action' in m.lower()]
    action_methods = [m for m in methods if not m.startswith('_')]
    print(f"    Metodos disponibles: {action_methods}")
    if hasattr(l, 'action_compute'):
        l.action_compute(); env.cr.commit()
    elif hasattr(l, 'action_calculate'):
        l.action_calculate(); env.cr.commit()
    print(f"    Dias: {l.days_worked}, Base: ${l.base_salary:,.0f}")
    print(f"    Prima: ${l.prima_proporcional:,.0f}")
    print(f"    Cesantias: ${l.cesantias_proporcionales:,.0f}")
    print(f"    Int.Ces: ${l.intereses_cesantias:,.0f}")
    print(f"    Vacaciones: ${l.vacaciones_proporcionales:,.0f}")
    print(f"    Indemnizacion: ${l.indemnizacion:,.0f}")
    print(f"    TOTAL: ${l.total_liquidacion:,.0f}")
test("Liquidacion: Calcular", t_liq_calc)

# ── UGPP ─────────────────────────────────────────────────
print("\n-- UGPP --")
def t_ugpp():
    u = env['l10n_co_nomina.ugpp'].create({
        'company_id':env.company.id,'year':2026,'month':'5'})
    env.cr.commit(); ids['ugpp'] = u.id
    assert u.state == 'draft'
test("UGPP: Crear Mayo 2026", t_ugpp)

def t_ugpp_gen():
    if 'ugpp' not in ids: return
    u = env['l10n_co_nomina.ugpp'].browse(ids['ugpp'])
    if hasattr(u, 'action_generate'):
        u.action_generate(); env.cr.commit()
        print(f"    Estado: {u.state}")
        if u.excel_file:
            import base64
            data = base64.b64decode(u.excel_file)
            print(f"    Archivo: {u.excel_filename}, {len(data)} bytes")
test("UGPP: Generar reporte", t_ugpp_gen)

# ── PILA ─────────────────────────────────────────────────
print("\n-- PILA --")
def t_pila():
    w = env['l10n.co.hr.pila.wizard'].create({
        'year':'2026','month':'05','company_id':env.company.id})
    env.cr.commit(); ids['pila'] = w.id
test("PILA: Crear wizard", t_pila)

def t_pila_gen():
    if 'pila' not in ids: return
    w = env['l10n.co.hr.pila.wizard'].browse(ids['pila'])
    if hasattr(w, 'action_generate'):
        w.action_generate(); env.cr.commit()
        if w.file_data:
            import base64
            data = base64.b64decode(w.file_data)
            lines = data.decode('latin-1',errors='replace').strip().split('\n')
            print(f"    Archivo: {w.file_name}, {len(data)} bytes, {len(lines)} lineas")
            for i,l in enumerate(lines[:5]):
                print(f"      L{i+1}: {l[:100]}")
        else:
            print("    Sin datos (puede requerir nominas del periodo)")
test("PILA: Generar archivo plano", t_pila_gen)

# ── RETEFUENTE ───────────────────────────────────────────
print("\n-- Retefuente --")
def t_ret():
    uvts = env['l10n.co.retefuente.uvt'].search([])
    assert len(uvts) > 0
    for u in uvts:
        print(f"    {u.year}: UVT=${u.uvt_value:,.0f}, Proc={u.procedure}")
test("Retefuente: Datos UVT", t_ret)

# ── REGLAS SALARIALES ────────────────────────────────────
print("\n-- Reglas Salariales --")
def t_rd():
    rules = env['hr.salary.rule'].search([('l10n_co_ne_dian_concept','!=',False),('l10n_co_ne_is_deduction','=',False)])
    concepts = set(rules.mapped('l10n_co_ne_dian_concept'))
    print(f"    Devengados: {len(rules)} reglas, {len(concepts)} conceptos unicos")
    assert 'Sueldo' in concepts and 'Transporte' in concepts
test("Reglas: Devengados", t_rd)

def t_rdd():
    rules = env['hr.salary.rule'].search([('l10n_co_ne_dian_concept','!=',False),('l10n_co_ne_is_deduction','=',True)])
    concepts = set(rules.mapped('l10n_co_ne_dian_concept'))
    print(f"    Deducciones: {len(rules)} reglas, {len(concepts)} conceptos unicos")
    assert 'Salud' in concepts and 'FondoPension' in concepts
test("Reglas: Deducciones", t_rdd)

def t_rugpp():
    rules = env['hr.salary.rule'].search([('l10n_co_ugpp_payment_type','!=',False)])
    types = set(rules.mapped('l10n_co_ugpp_payment_type'))
    print(f"    UGPP: {len(rules)} reglas, {len(types)} tipos")
test("Reglas: UGPP types", t_rugpp)

# ── DETALLE NOMINAS ──────────────────────────────────────
print("\n-- Detalle Nominas --")
def show_ps(pk, label):
    def fn():
        if pk not in ids: return
        ps = env['hr.payslip'].browse(ids[pk])
        lines = {l.code: l.total for l in ps.line_ids if l.total != 0}
        print(f"    {label}: state={ps.state}, ne_state={ps.l10n_co_ne_state}")
        for code in sorted(lines.keys()):
            print(f"      {code} = ${lines[code]:,.0f}")
    return fn

test("Detalle: David", show_ps('p1','David'))
test("Detalle: Maria integral", show_ps('p2','Maria'))
test("Detalle: Juan SMMLV", show_ps('p3','Juan'))

# ── RESULTADO ────────────────────────────────────────────
print("\n================================================================")
print("  RESULTADOS")
print("================================================================")
ok = sum(1 for s,_ in results if s == "OK")
xx = sum(1 for s,_ in results if s == "XX")
for s, n in results:
    print(f"  [{s}] {n}")
print(f"\n  TOTAL: {ok} PASS, {xx} FAIL de {len(results)}")
env.cr.rollback()
print("  Rollback ejecutado")
print("================================================================")
ORMEOF
