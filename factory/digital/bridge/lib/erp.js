// 问渠数字工厂 · ERPNext ↔ 统一数据总线 桥接逻辑（Node-RED 的函数节点调用这里）
//
// 读写 ERPNext 只走它的 REST 接口（/api/resource、/api/method），结果一律作为 erp.doc 发回总线。
// 规则（附录 A.4）：只有人确认过的 ai.proposal 才写入订单类单据；车间和质检的事实（完工事件、测量值）
// 直接记成作业卡工时、质量检验单和完工入库。
'use strict';
const wq = require('./wq');

const TZ = process.env.WQ_TZ || 'America/New_York';
const ABBR = process.env.WQ_ERP_ABBR || 'WQ';
const WH = {
  raw: `原材料库 Raw - ${ABBR}`,
  purchased: `外购件库 Purchased - ${ABBR}`,
  semi: `半成品库 Semi-finished - ${ABBR}`,
  wip: `在制品库 WIP - ${ABBR}`,
  fg: `成品库 Finished - ${ABBR}`,
};
const INSPECTION_OP = '零件检验 Part inspection';
// 总线上的检验特性 → ERPNext 质量检验参数（与工厂数据 factory/data.py 的检验模板一致）
const QI_PARAM = {
  bearing_seat_d35: '轴承位直径 Bearing seat Ø35 k6 (mm)',
  gear_seat_d40: '齿轮位直径 Gear seat Ø40 k6 (mm)',
  keyway_width_12: '键槽宽 Keyway 12 N9 (mm)',
};
const QI_TEMPLATE = { 'SH-301': '零件检验-输出轴' };
const MAKE_WH = { 'SH-301': WH.semi };
// 扩展（第 30 轮 H-8）：freecad-ai-parts 独有的提议（CAD 方案转为生产物料、到货入库）在它的 lib/erp_enterprise.js；问渠这边没有这个文件
const EXTRA_ACTIONS = {};
try {
  Object.assign(EXTRA_ACTIONS, require('./erp_enterprise')({ WH }));
} catch (e) {
  if (e.code !== 'MODULE_NOT_FOUND' || !String(e.message).includes('erp_enterprise')) throw e;
}

// ERPNext 的日期时间：站点时区的 "YYYY-MM-DD HH:MM:SS"
function erpDatetime(iso) {
  const d = new Date(iso);
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    second: '2-digit', hourCycle: 'h23',
  }).formatToParts(d).map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
}
const erpDate = (iso) => erpDatetime(iso).slice(0, 10);

class ErpError extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

class ERP {
  constructor({ url, apiKey, apiSecret, mode, log } = {}) {
    this.url = (url || process.env.WQ_ERPNEXT_API || 'http://localhost:8090').replace(/\/$/, '');
    this.auth = `token ${apiKey || process.env.WQ_ERP_API_KEY || ''}:${apiSecret || process.env.WQ_ERP_API_SECRET || ''}`;
    this.mode = mode || process.env.WQ_MODE || 'teach';
    this.log = log || ((...a) => console.log('[bridge]', ...a));
    this.company = process.env.WQ_ERP_COMPANY || null;
    this.qiOps = new Set();        // 工单|工序：这道工序有检验单（按测量特性建，第 45 轮）
    this.qiBuffer = new Map();     // 零件序列号 → 已收到的测量
    this.qiInFlight = 0;
    this.locks = new Map();        // 同一张作业卡的更新排队进行
    this.missing = new Set();      // 找不到的工单（例如教学情景里的演示工单），不再反复查
    this.lastModified = {};        // 轮询：每种单据看到的最后修改时间
    this.binSeen = new Map();
    this.published = new Map();    // 刚由桥接发出的单据 → modified，轮询时跳过
  }

  // ------------------------------------------------------------ REST
  // 数据库冲突（多个请求同时改同一张作业卡）时 ERPNext 返回 500 QueryDeadlockError：稍等重试
  async req(method, path, body, attempt = 0) {
    try {
      return await this.req1(method, path, body);
    } catch (e) {
      const deadlock = e instanceof ErpError && e.status >= 500 && /Deadlock|Record has changed since last read/i.test(e.message);
      if (!deadlock || attempt >= 4) throw e;
      await new Promise((r) => setTimeout(r, 400 * (attempt + 1) + Math.random() * 400));
      return this.req(method, path, body, attempt + 1);
    }
  }

  async req1(method, path, body) {
    const r = await fetch(this.url + path, {
      method,
      headers: { Authorization: this.auth, 'Content-Type': 'application/json', Accept: 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await r.text();
    let json = null;
    try { json = text ? JSON.parse(text) : null; } catch (e) { json = { raw: text }; }
    if (!r.ok) {
      let msg = (json && (json.exception || json.message)) || text;
      try {
        const sm = JSON.parse(json._server_messages || '[]').map((m) => JSON.parse(m).message);
        if (sm.length) msg = sm.join('；');
      } catch (e) { /* 保留原信息 */ }
      throw new ErpError(r.status, `ERPNext ${method} ${path.split('?')[0]} 失败（${r.status}）：${String(msg).slice(0, 300)}`, json);
    }
    return json;
  }

  async list(doctype, filters, fields = ['name'], extra = {}) {
    const q = new URLSearchParams({ filters: JSON.stringify(filters || []), fields: JSON.stringify(fields),
      limit_page_length: String(extra.limit || 500), ...(extra.order_by ? { order_by: extra.order_by } : {}) });
    return (await this.req('GET', `/api/resource/${encodeURIComponent(doctype)}?${q}`)).data;
  }

  async get(doctype, name) {
    return (await this.req('GET', `/api/resource/${encodeURIComponent(doctype)}/${encodeURIComponent(name)}`)).data;
  }

  async insert(doctype, doc) {
    return (await this.req('POST', `/api/resource/${encodeURIComponent(doctype)}`, doc)).data;
  }

  async update(doctype, name, doc) {
    return (await this.req('PUT', `/api/resource/${encodeURIComponent(doctype)}/${encodeURIComponent(name)}`, doc)).data;
  }

  async method(name, body) {
    return (await this.req('POST', `/api/method/${name}`, body)).message;
  }

  async getCompany() {
    if (!this.company) {
      const rows = await this.list('Company', [], ['name']);
      if (!rows.length) throw new Error('ERPNext 里还没有公司，请先完成设置向导并运行 seed.py');
      this.company = rows[0].name;
    }
    return this.company;
  }

  async withLock(key, fn) {
    const prev = this.locks.get(key) || Promise.resolve();
    const next = prev.catch(() => {}).then(fn);
    this.locks.set(key, next);
    try { return await next; } finally { if (this.locks.get(key) === next) this.locks.delete(key); }
  }

  // ------------------------------------------------------------ erp.doc
  doc(doctype, d, action, { corr = null, mode = null, extra = {} } = {}) {
    if (d && d.modified) this.published.set(`${doctype}|${d.name}`, d.modified);
    const data = { doctype, name: d.name, action, ...summarize(doctype, d), ...extra };
    return { topic: wq.erpTopic(doctype), payload: wq.make('erp.doc', 'erpnext', data, { mode: mode || this.mode, corr }) };
  }

  failed(doctype, err, { corr, mode, extra = {} } = {}) {
    const data = { doctype, name: extra.name || '-', action: 'failed', error: String(err.message || err), ...extra };
    return { topic: wq.erpTopic(doctype), payload: wq.make('erp.doc', 'erpnext', data, { mode: mode || this.mode, corr }) };
  }

  // ------------------------------------------------------------ 1. 执行已确认的提议
  async execProposal(m) {
    const d = m.data;
    if (d.status !== 'confirmed') return [];
    const pid = d.proposal_id;
    const opt = { corr: pid, mode: m.mode };
    const out = [];
    const created = [];
    try {
      if (d.action === 'create_order_and_plan') {
        const company = await this.getCompany();
        const pv = d.preview;
        const so = pv.sales_order;
        const soDoc = await this.insert('Sales Order', {
          customer: so.customer, company, transaction_date: so.transaction_date, delivery_date: so.delivery_date,
          order_type: 'Sales', docstatus: 1,
          items: [{ item_code: so.item_code, qty: so.qty, delivery_date: so.delivery_date,
            ...(so.rate ? { rate: so.rate } : {}), warehouse: WH.fg }],
        });
        out.push(this.doc('Sales Order', soDoc, 'submitted', opt));
        created.push(['Sales Order', soDoc.name]);
        if (pv.contract) {        // 第 18 轮 E1：合同转订单，订单号回填到合同
          await this.ensureCrmFields();
          out.push(this.doc('Contract', await this.update('Contract', pv.contract, { wq_sales_order: soDoc.name }), 'updated', opt));
        }
        for (const w of pv.work_orders || []) {
          const bom = await this.defaultBom(w.production_item);
          // ERPNext 只允许生产“订单上那个物料”的工单填 sales_order；零件工单（如 SH-301）把订单号记在
          // 自定义字段 wq_sales_order 里，看板照样能把订单和工单对上（第 3 轮演练发现）
          const direct = w.production_item === so.item_code;
          if (!direct) {
            await this.ensureCustomField('Work Order', 'wq_sales_order', { label: '对应销售订单 For sales order',
              fieldtype: 'Link', options: 'Sales Order', insert_after: 'sales_order', read_only: 1 });
          }
          const wo = await this.withBomOperations({
            production_item: w.production_item, bom_no: bom, qty: w.qty, company,
            ...(direct ? { sales_order: soDoc.name } : { wq_sales_order: soDoc.name }),
            planned_start_date: `${w.planned_start_date} 08:00:00`,
            expected_delivery_date: w.expected_delivery_date, skip_transfer: 1,
            source_warehouse: WH.raw, wip_warehouse: WH.wip,
            fg_warehouse: MAKE_WH[w.production_item] || (w.warehouse === 'fg' ? WH.fg : WH.semi),
            use_multi_level_bom: 0,
          });
          if (w.sources) {     // 领料仓库按算料给出的 sources：semi 半成品库、purchased 外购件库、raw 原材料库（第 45 轮加外购件库）
            wo.required_items = (wo.required_items || []).map((r) => ({ ...r,
              source_warehouse: WH[w.sources[r.item_code]] || WH.raw }));
          }
          const woDoc = await this.insert('Work Order', { ...wo, docstatus: 1 });
          out.push(this.doc('Work Order', woDoc, 'submitted', opt));
          created.push(['Work Order', woDoc.name]);
        }
        if ((pv.material_requests || []).length) {
          const mr = await this.materialRequest(company, pv.material_requests, so.transaction_date);
          out.push(this.doc('Material Request', mr, 'submitted', opt));
          created.push(['Material Request', mr.name]);
        }
      } else if (d.action === 'purchase_request') {
        const company = await this.getCompany();
        const mr = await this.materialRequest(company, d.preview.material_requests, erpDate(new Date().toISOString()));
        out.push(this.doc('Material Request', mr, 'submitted', opt));
        created.push(['Material Request', mr.name]);
      } else if (d.action === 'so_comment') {
        // 第 17 轮 C 期：厂情中枢的“分批交货”等动作，在 ERPNext 销售订单上留一条备注（不改已提交的订单）
        const pv = d.preview;
        const c = await this.insert('Comment', { comment_type: 'Comment', reference_doctype: 'Sales Order',
          reference_name: pv.sales_order, content: pv.content });
        out.push(this.doc('Comment', c, 'created', opt));
        created.push(['Comment', c.name]);
      } else if (d.action === 'twin_service_order') {
        // 第 15 轮：数字孪生开的维修单 → ERPNext 服务工单（Issue），设备序列号记在自定义字段里
        const pv = d.preview;
        await this.ensureCustomField('Issue', 'wq_serial', { label: '设备序列号 Serial', fieldtype: 'Data', insert_after: 'subject' });
        const iss = await this.insert('Issue', { subject: pv.subject, description: `${pv.customer || ''}\n${pv.description}`.trim(),
          status: 'Open', wq_serial: pv.serial });
        out.push(this.doc('Issue', iss, 'created', opt));
        created.push(['Issue', iss.name]);
      } else if (d.action === 'twin_service_done') {
        const pv = d.preview;
        const iss = await this.update('Issue', pv.issue, { status: 'Resolved',
          resolution_details: `已完成：${pv.what}${pv.note ? '。' + pv.note : ''}（问渠数字工厂 · 数字孪生）` });
        out.push(this.doc('Issue', iss, 'updated', opt));
        created.push(['Issue', iss.name]);
      } else if (['maint_setup', 'maint_log', 'asset_repair', 'asset_repair_done', 'maint_interval'].includes(d.action)) {
        // 第 18 轮 E3：设备台账、保养计划、保养记录、维修单
        for (const r of await this.maintService(d.action, d.preview)) {
          out.push(this.doc(r[0], r[1], r[2], opt));
          created.push([r[0], r[1].name]);
        }
      } else if (['supply_setup', 'purchase_order', 'incoming_receipt'].includes(d.action)) {
        // 第 18 轮 E5：备选供应商、采购单、收货 + 来料检验
        const at = out.length;
        for (const r of await this.supplyService(d.action, d.preview)) {
          out.push(this.doc(r[0], r[1], r[2], opt));
          created.push([r[0], r[1].name]);
        }
        // 入库后库存马上更新（放在前面：最后一条要带“提议完成”的标记）
        if (d.action === 'incoming_receipt') out.splice(at, 0, ...await this.bins());
      } else if (['sales_invoice', 'purchase_invoice', 'payment', 'dunning_note'].includes(d.action)) {
        // 第 18 轮 E7：销售发票、采购发票、收付款、催款记录
        for (const r of await this.financeService(d.action, d.preview)) {
          out.push(this.doc(r[0], r[1], r[2], opt));
          created.push([r[0], r[1].name]);
        }
      } else if (d.action === 'people_setup') {
        // 第 18 轮 E4：部门、岗位、员工档案
        for (const r of await this.peopleService(d.action, d.preview)) {
          out.push(this.doc(r[0], r[1], r[2], opt));
          created.push([r[0], r[1].name]);
        }
      } else if (d.action.startsWith('crm_') || ['complaint_issue', 'service_orders', 'service_order_done', 'spare_ship'].includes(d.action)) {
        // 第 18 轮 E1：客户与服务（线索、商机、报价、合同、投诉、服务工单、备件出库）
        for (const r of await this.crmService(d.action, d.preview)) {
          out.push(this.doc(r[0], r[1], r[2], opt));
          created.push([r[0], r[1].name]);
        }
      } else if (EXTRA_ACTIONS[d.action]) {
        await EXTRA_ACTIONS[d.action].call(this, d.preview, { out, created, opt });
      } else {
        return [];      // 其他提议（如下达工单）由工作台的 MES 执行
      }
    } catch (e) {
      this.log('执行提议失败', pid, e.message);
      out.push(this.failed('Proposal', e, { ...opt, extra: { proposal_id: pid, created } }));
      return out;
    }
    const last = out[out.length - 1].payload.data;
    last.proposal_done = true;
    last.created = created;
    return out;
  }

  // ------------------------------------------------------------ 第 18 轮 E1：客户与服务
  async ensureCrmFields() {
    const F = [
      ['Lead', 'wq_note', { label: '备注 Note', fieldtype: 'Small Text', insert_after: 'company_name' }],
      ['Contract', 'wq_penalty_per_day', { label: '延期违约金 $/天 Penalty per day', fieldtype: 'Currency', insert_after: 'end_date' }],
      ['Contract', 'wq_response_h', { label: '投诉响应时限（小时）Response hours', fieldtype: 'Float', insert_after: 'wq_penalty_per_day' }],
      ['Contract', 'wq_warranty_months', { label: '保修期（月）Warranty months', fieldtype: 'Int', insert_after: 'wq_response_h' }],
      ['Contract', 'wq_amount', { label: '合同金额 Amount', fieldtype: 'Currency', insert_after: 'wq_warranty_months' }],
      ['Contract', 'wq_quotation', { label: '报价单 Quotation', fieldtype: 'Data', insert_after: 'wq_amount' }],
      ['Contract', 'wq_sales_order', { label: '销售订单 Sales order', fieldtype: 'Data', insert_after: 'wq_quotation', allow_on_submit: 1 }],
      ['Issue', 'wq_serial', { label: '设备序列号 Serial', fieldtype: 'Data', insert_after: 'subject' }],
      ['Issue', 'wq_kind', { label: '类别 Kind', fieldtype: 'Data', insert_after: 'wq_serial' }],
      ['Issue', 'wq_engineer', { label: '服务工程师 Engineer', fieldtype: 'Data', insert_after: 'wq_kind' }],
      ['Issue', 'wq_day', { label: '计划上门日 Visit day', fieldtype: 'Date', insert_after: 'wq_engineer' }],
    ];
    for (const [dt, f, spec] of F) await this.ensureCustomField(dt, f, spec);
  }

  async customerFor(name) {
    const rows = await this.list('Customer', [['name', '=', name]], ['name']);
    if (rows.length) return name;
    const terr = await this.list('Territory', [['is_group', '=', 1], ['parent_territory', 'in', ['', null]]], ['name']);
    const doc = await this.insert('Customer', { customer_name: name, customer_type: 'Company', customer_group: '减速器客户 Gearbox Customers',
      ...(terr.length ? { territory: terr[0].name } : {}) });
    return doc.name;
  }

  async crmService(action, pv) {
    await this.ensureCrmFields();
    const company = await this.getCompany();
    const today = erpDate(new Date().toISOString());
    const out = [];
    if (action === 'crm_lead') {
      const lead = await this.insert('Lead', { lead_name: pv.lead_name, company_name: pv.company_name, status: 'Lead', wq_note: pv.note || '' });
      out.push(['Lead', lead, 'created']);
    } else if (action === 'crm_opportunity') {
      const opp = await this.insert('Opportunity', { opportunity_from: pv.from, party_name: pv.party, status: 'Open', company,
        transaction_date: today, currency: 'USD', opportunity_amount: pv.amount || 0, expected_closing: pv.expected_closing || null });
      out.push(['Opportunity', opp, 'created']);
      if (pv.from === 'Lead') out.push(['Lead', await this.update('Lead', pv.party, { status: 'Opportunity' }), 'updated']);
    } else if (action === 'crm_quotation') {
      let to = pv.quotation_to || 'Customer';
      let party = pv.party;
      if (to === 'Customer') party = await this.customerFor(party);
      const q = await this.insert('Quotation', { quotation_to: to, party_name: party, company, transaction_date: today,
        valid_till: pv.valid_till, order_type: 'Sales', ...(pv.opportunity ? { opportunity: pv.opportunity } : {}),
        items: pv.items.map((i) => ({ item_code: i.item_code, qty: i.qty, rate: i.rate })), docstatus: 1 });
      out.push(['Quotation', q, 'submitted']);
      if (pv.opportunity) out.push(['Opportunity', await this.get('Opportunity', pv.opportunity), 'updated']);
    } else if (action === 'crm_contract') {
      const cust = await this.customerFor(pv.customer);
      const c = await this.insert('Contract', { party_type: 'Customer', party_name: cust, contract_terms: pv.text,
        start_date: pv.start, end_date: pv.end, is_signed: 1, signee: pv.signee || cust,
        ...(pv.quotation ? { document_type: 'Quotation', document_name: pv.quotation } : {}),
        wq_penalty_per_day: pv.penalty_per_day || 0, wq_response_h: pv.response_h || 24, wq_warranty_months: pv.warranty_months || 12,
        wq_amount: pv.amount || 0, wq_quotation: pv.quotation || '', docstatus: 1 });
      out.push(['Contract', c, 'submitted']);
    } else if (action === 'crm_contract_order') {
      out.push(['Contract', await this.update('Contract', pv.contract, { wq_sales_order: pv.sales_order }), 'updated']);
    } else if (action === 'complaint_issue') {
      const iss = await this.insert('Issue', { subject: pv.subject, description: `${pv.customer || ''}\n${pv.description || ''}`.trim(),
        status: 'Open', wq_serial: pv.serial || '', wq_kind: '投诉 complaint' });
      out.push(['Issue', iss, 'created']);
    } else if (action === 'service_orders') {
      for (const o of pv.orders) {
        const iss = await this.insert('Issue', { subject: o.subject, description: `${o.customer || ''}\n${o.description || ''}`.trim(),
          status: 'Open', wq_serial: o.serial || '', wq_kind: o.kind || '服务 service', wq_engineer: o.engineer || '', wq_day: o.day || null });
        out.push(['Issue', iss, 'created']);
      }
    } else if (action === 'service_order_done') {
      out.push(['Issue', await this.update('Issue', pv.issue, { status: 'Resolved', resolution_details: pv.text || '已完成' }), 'updated']);
    } else if (action === 'spare_ship') {
      const se = await this.insert('Stock Entry', { stock_entry_type: 'Material Issue', purpose: 'Material Issue', company,
        remarks: pv.note || '', items: pv.items.map((i) => ({ item_code: i.item_code, qty: i.qty, s_warehouse: WH.purchased })), docstatus: 1 });
      out.push(['Stock Entry', se, 'submitted']);
    }
    return out;
  }

  // ------------------------------------------------------------ 第 18 轮 E3：设备维护与资产
  async ensureAssetSetup() {
    if (this.assetSetup) return this.assetSetup;
    const company = await this.getCompany();
    const loc = '问渠车间 Workshop';
    if (!(await this.list('Location', [['name', '=', loc]])).length) await this.insert('Location', { location_name: loc });
    const cat = '生产设备 Production machinery';
    if (!(await this.list('Asset Category', [['name', '=', cat]])).length) {
      const acc = await this.list('Account', [['account_type', '=', 'Fixed Asset'], ['is_group', '=', 0], ['company', '=', company]], ['name']);
      if (!acc.length) throw new Error('ERPNext 里找不到“固定资产”类型的科目，建不了资产分类');
      await this.insert('Asset Category', { asset_category_name: cat, accounts: [{ company_name: company, fixed_asset_account: acc[0].name }] });
    }
    const item = 'AST-MACHINE';
    if (!(await this.list('Item', [['name', '=', item]])).length) {
      const grp = (await this.list('Item Group', [['is_group', '=', 0]], ['name'], { limit: 1 }))[0];
      await this.insert('Item', { item_code: item, item_name: '生产设备 Production machine', stock_uom: 'Nos', is_stock_item: 0,
        is_fixed_asset: 1, asset_category: cat, ...(grp ? { item_group: grp.name } : {}) });
    }
    // 保养任务要指派给一个用户：ERPNext 按“用户的邮箱”找人建待办，Administrator 的邮箱不是用户名，所以建一个设备组的用户
    const user = 'maint@wenquest.local';
    const roles = await this.list('Role', [['name', 'in', ['Maintenance User', 'Maintenance Manager', 'System Manager']]], ['name']);
    const role = roles.length ? roles[0].name : 'System Manager';
    if (!(await this.list('User', [['name', '=', user]])).length) {
      try {
        await this.insert('User', { email: user, first_name: '设备组', last_name: 'Maintenance', send_welcome_email: 0, enabled: 1,
          user_type: 'System User', roles: [{ role }] });
      } catch (e) {
        if (!(await this.list('User', [['name', '=', user]])).length) throw e;
      }
    }
    const team = '设备组 Maintenance team';
    const members = [{ team_member: 'Administrator', maintenance_role: role }, { team_member: user, maintenance_role: role }];
    if (!(await this.list('Asset Maintenance Team', [['name', '=', team]])).length) {
      await this.insert('Asset Maintenance Team', { maintenance_team_name: team, company, maintenance_manager: user, maintenance_team_members: members });
    } else {
      const t = await this.get('Asset Maintenance Team', team);
      if (!(t.maintenance_team_members || []).some((m) => m.team_member === user)) {
        await this.update('Asset Maintenance Team', team, { maintenance_team_members: [...(t.maintenance_team_members || []), members[1]] });
      }
    }
    await this.ensureCustomField('Asset Maintenance Task', 'wq_interval_h', { label: '周期（运行小时）Interval (run hours)', fieldtype: 'Float',
      insert_after: 'periodicity' });
    this.assetSetup = { company, loc, cat, item, team, user };
    return this.assetSetup;
  }

  // ------------------------------------------------------------ 第 18 轮 E5：供应链
  async supplyService(action, pv) {
    const company = await this.getCompany();
    const out = [];
    const wh = (code) => (code.startsWith('RM-') ? WH.raw : WH.purchased);
    if (action === 'supply_setup') {
      // 备选供应商（可以重发：按名称跳过已建的）
      for (const sp of pv.suppliers || []) {
        const had = (await this.list('Supplier', [['name', '=', sp.name]], ['name']))[0];
        const doc = had ? await this.get('Supplier', had.name) : await this.insert('Supplier', { supplier_name: sp.name, supplier_type: 'Company',
          ...(sp.group ? { supplier_group: sp.group } : {}) });
        out.push(['Supplier', doc, had ? 'updated' : 'created']);
      }
    } else if (action === 'purchase_order') {
      const date = erpDate(new Date().toISOString());
      const po = await this.insert('Purchase Order', { supplier: pv.supplier, company, transaction_date: date, schedule_date: pv.schedule_date,
        set_warehouse: wh(pv.items[0].item_code), docstatus: 1,
        items: pv.items.map((i) => ({ item_code: i.item_code, qty: i.qty, rate: i.rate, schedule_date: pv.schedule_date, warehouse: wh(i.item_code),
          ...(i.material_request ? { material_request: i.material_request, material_request_item: i.material_request_item } : {}) })) });
      out.push(['Purchase Order', po, 'submitted']);
    } else if (action === 'incoming_receipt') {
      // 按采购单生成收货单（批号记在自定义字段）；要检验的物料先建来料检验单；合格（或让步接收）才提交收货单入库
      await this.ensureCustomField('Purchase Receipt', 'wq_lot', { label: '批号 Lot', fieldtype: 'Data', insert_after: 'supplier' });
      const made = await this.method('erpnext.buying.doctype.purchase_order.purchase_order.make_purchase_receipt', { source_name: pv.purchase_order });
      const pr0 = { ...made };
      delete pr0.name;
      delete pr0.__islocal;
      const row = (pr0.items || []).find((i) => i.item_code === pv.item_code);
      if (!row) throw new Error(`采购单 ${pv.purchase_order} 里没有待收的 ${pv.item_code}`);
      const qty = pv.accept ? pv.accept_qty : pv.qty;
      const clean = { ...row };
      for (const k of ['name', '__islocal', '__unsaved', 'parent', 'parenttype', 'parentfield', 'idx', 'docstatus']) delete clean[k];
      pr0.items = [{ ...clean, qty, received_qty: qty, rejected_qty: 0 }];
      pr0.posting_date = erpDate(new Date().toISOString());
      pr0.wq_lot = pv.lot;
      pr0.remarks = `批号 ${pv.lot}${pv.remarks ? '；' + pv.remarks : ''}`;
      const pr = await this.insert('Purchase Receipt', pr0);
      out.push(['Purchase Receipt', pr, 'created']);
      let qi = null;
      if (pv.inspect) {
        qi = await this.insert('Quality Inspection', { report_date: pr0.posting_date, inspection_type: 'Incoming', reference_type: 'Purchase Receipt',
          reference_name: pr.name, item_code: pv.item_code, sample_size: pv.sample_size || 1, inspected_by: 'Administrator', status: pv.status,
          manual_inspection: 1, remarks: `批号 ${pv.lot}：${pv.remarks || ''}`.slice(0, 500),
          ...(pv.template ? { quality_inspection_template: pv.template } : {}),
          readings: (pv.readings || []).map((r) => (r.numeric ? { specification: r.specification, numeric: 1, manual_inspection: 1, min_value: r.min,
            max_value: r.max, reading_1: String(r.value), status: r.ok ? 'Accepted' : 'Rejected' }
            : { specification: r.specification, numeric: 0, manual_inspection: 1, value: r.value, reading_value: r.value, status: r.ok ? 'Accepted' : 'Rejected' })),
          docstatus: 1 });
        out.push(['Quality Inspection', qi, 'submitted']);
      }
      if (pv.accept) {
        const cur = await this.get('Purchase Receipt', pr.name);
        const items = (cur.items || []).map((i) => (i.item_code === pv.item_code && qi ? { ...i, quality_inspection: qi.name } : i));
        const done = await this.update('Purchase Receipt', pr.name, { items, docstatus: 1 });
        out.push(['Purchase Receipt', done, 'submitted']);
      }
    }
    return out;
  }

  // ------------------------------------------------------------ 第 18 轮 E7：经营与财务
  async financeService(action, pv) {
    const out = [];
    const strip = (x) => {
      const r = { ...x };
      for (const k of ['name', '__islocal', '__unsaved', 'parent', 'parenttype', 'parentfield', 'idx', 'docstatus']) delete r[k];
      return r;
    };
    const clean = (doc) => {
      const d = strip(doc);
      if (Array.isArray(d.items)) d.items = d.items.map(strip);
      return d;
    };
    if (action === 'sales_invoice') {
      // 按销售订单开票（可以重发：这张订单已有提交的发票就不再开）
      const had = (await this.list('Sales Invoice', [['Sales Invoice Item', 'sales_order', '=', pv.sales_order], ['docstatus', '=', 1]], ['name']))[0];
      if (had) return [['Sales Invoice', await this.get('Sales Invoice', had.name), 'updated']];
      const made = clean(await this.method('erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice', { source_name: pv.sales_order }));
      if (!(made.items || []).length) throw new Error(`销售订单 ${pv.sales_order} 已经全部开票`);
      const today = erpDate(new Date().toISOString());
      made.posting_date = today;
      made.set_posting_time = 1;
      made.due_date = pv.due_date && pv.due_date >= today ? pv.due_date : today;
      made.payment_terms_template = null;
      made.payment_schedule = [];
      made.remarks = `问渠数字工厂：订单 ${pv.sales_order} 做完开票${pv.remarks ? '；' + pv.remarks : ''}`;
      made.docstatus = 1;
      out.push(['Sales Invoice', await this.insert('Sales Invoice', made), 'submitted']);
    } else if (action === 'purchase_invoice') {
      const had = (await this.list('Purchase Invoice', [['Purchase Invoice Item', 'purchase_receipt', '=', pv.purchase_receipt], ['docstatus', '=', 1]], ['name']))[0];
      if (had) return [['Purchase Invoice', await this.get('Purchase Invoice', had.name), 'updated']];
      const made = clean(await this.method('erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_invoice', { source_name: pv.purchase_receipt }));
      const today = erpDate(new Date().toISOString());
      made.posting_date = today;
      made.set_posting_time = 1;
      made.due_date = pv.due_date && pv.due_date >= today ? pv.due_date : today;
      made.bill_no = pv.bill_no || `WQ-${pv.purchase_receipt}`;
      made.bill_date = today;
      made.payment_terms_template = null;
      made.payment_schedule = [];
      made.remarks = `问渠数字工厂：收货单 ${pv.purchase_receipt}（批号 ${pv.lot || '—'}）的供应商发票`;
      made.docstatus = 1;
      out.push(['Purchase Invoice', await this.insert('Purchase Invoice', made), 'submitted']);
    } else if (action === 'payment') {
      // 按发票收款 / 付款（可以重发：发票已经付清就不再建）
      const inv = await this.get(pv.doctype, pv.invoice);
      if (Number(inv.outstanding_amount || 0) <= 0.005) return [[pv.doctype, inv, 'updated']];
      const made = await this.method('erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry', { dt: pv.doctype, dn: pv.invoice });
      const pe = { ...made };
      for (const k of ['name', '__islocal', '__unsaved', 'docstatus']) delete pe[k];
      pe.references = (pe.references || []).map(strip);
      const today = erpDate(new Date().toISOString());
      pe.posting_date = today;
      pe.reference_no = pv.reference_no || `WQ-${pv.invoice}`;
      pe.reference_date = today;
      pe.remarks = pv.remarks || `问渠数字工厂：${pv.doctype === 'Sales Invoice' ? '收款' : '付款'} ${pv.invoice}`;
      pe.docstatus = 1;
      out.push(['Payment Entry', await this.insert('Payment Entry', pe), 'submitted']);
      out.push([pv.doctype, await this.get(pv.doctype, pv.invoice), 'updated']);
    } else if (action === 'dunning_note') {
      const c = await this.insert('Comment', { comment_type: 'Comment', reference_doctype: 'Sales Invoice', reference_name: pv.invoice,
        content: pv.content });
      out.push(['Sales Invoice', await this.get('Sales Invoice', pv.invoice), 'updated']);
      void c;
    }
    return out;
  }

  // ------------------------------------------------------------ 第 18 轮 E4：人员与组织
  async peopleService(action, pv) {
    const company = await this.getCompany();
    const out = [];
    const deptName = {};
    for (const dpt of pv.departments || []) {
      const had = (await this.list('Department', [['department_name', '=', dpt.name], ['company', '=', company]], ['name']))[0];
      const doc = had ? await this.get('Department', had.name) : await this.insert('Department', { department_name: dpt.name, company });
      deptName[dpt.name] = doc.name;
      out.push(['Department', doc, had ? 'updated' : 'created']);
    }
    for (const g of pv.designations || []) {
      const had = (await this.list('Designation', [['name', '=', g.name]], ['name']))[0];
      const doc = had ? await this.get('Designation', had.name) : await this.insert('Designation', { designation_name: g.name, description: g.en });
      out.push(['Designation', doc, had ? 'updated' : 'created']);
    }
    for (const e of pv.employees || []) {
      // 可以重发：工号（employee_number）已有的不再建
      const had = (await this.list('Employee', [['employee_number', '=', e.id]], ['name']))[0];
      const doc = had ? await this.get('Employee', had.name) : await this.insert('Employee', { naming_series: 'HR-EMP-', first_name: e.name,
        employee_number: e.id, company, status: 'Active', gender: e.gender, date_of_birth: e.born, date_of_joining: e.hired,
        ...(deptName[e.dept] ? { department: deptName[e.dept] } : {}), designation: e.post, cell_number: e.phone });
      out.push(['Employee', doc, had ? 'updated' : 'created']);
    }
    return out;
  }

  async maintService(action, pv) {
    const S = await this.ensureAssetSetup();
    const today = erpDate(new Date().toISOString());
    const out = [];
    if (action === 'maint_setup') {
      for (const a of pv.assets) {
        // 可以重发：已经建过的资产、维护计划不再建（上一次提议可能在 ERPNext 还没就绪时丢了、或执行到一半）
        const had = (await this.list('Asset', [['asset_name', '=', a.asset_name], ['docstatus', '!=', 2]], ['name']))[0];
        const asset = had ? await this.get('Asset', had.name) : await this.insert('Asset', { asset_name: a.asset_name, item_code: S.item,
          asset_category: S.cat, company: S.company, location: S.loc, asset_type: 'Existing Asset', purchase_date: a.purchase_date,
          available_for_use_date: a.purchase_date, net_purchase_amount: a.value, calculate_depreciation: 0, maintenance_required: 1, docstatus: 1 });
        out.push(['Asset', asset, had ? 'updated' : 'submitted']);
        const hadMt = (await this.list('Asset Maintenance', [['asset_name', '=', asset.name]], ['name']))[0];
        if (hadMt) {
          out.push(['Asset Maintenance', await this.get('Asset Maintenance', hadMt.name), 'updated']);
          continue;
        }
        const mt = await this.insert('Asset Maintenance', { asset_name: asset.name, company: S.company, maintenance_team: S.team,
          asset_maintenance_tasks: [{ maintenance_task: a.task.slice(0, 140), maintenance_type: 'Preventive Maintenance', maintenance_status: 'Planned',
            start_date: today, periodicity: 'Monthly', assign_to: S.user, description: a.task, wq_interval_h: a.interval_h }] });
        out.push(['Asset Maintenance', mt, 'created']);
      }
    } else if (action === 'maint_log') {
      const lg = await this.insert('Asset Maintenance Log', { asset_maintenance: pv.asset_maintenance, task: pv.task, task_name: pv.task_name,
        periodicity: pv.periodicity || 'Monthly', due_date: pv.date, description: pv.description || pv.task_name, task_assignee_email: S.user,
        maintenance_status: 'Completed', completion_date: pv.date, actions_performed: pv.actions || '', docstatus: 1 });
      out.push(['Asset Maintenance Log', lg, 'submitted']);
    } else if (action === 'asset_repair') {
      const r = await this.insert('Asset Repair', { asset: pv.asset, company: S.company, failure_date: pv.failure_date, repair_status: 'Pending',
        description: pv.description || '' });
      out.push(['Asset Repair', r, 'created']);
    } else if (action === 'asset_repair_done') {
      const r = await this.update('Asset Repair', pv.repair, { repair_status: 'Completed', completion_date: pv.completion_date,
        actions_performed: pv.actions || '' });
      out.push(['Asset Repair', r, 'updated']);
    } else if (action === 'maint_interval') {
      const mt = await this.get('Asset Maintenance', pv.asset_maintenance);
      const tasks = (mt.asset_maintenance_tasks || []).map((t, i) => (i === 0 ? { ...t, wq_interval_h: pv.interval_h } : t));
      out.push(['Asset Maintenance', await this.update('Asset Maintenance', pv.asset_maintenance, { asset_maintenance_tasks: tasks }), 'updated']);
    }
    return out;
  }

  async materialRequest(company, rows, date) {
    return this.insert('Material Request', {
      material_request_type: 'Purchase', company, transaction_date: date,
      schedule_date: rows.map((r) => r.schedule_date).sort()[0], docstatus: 1,
      items: rows.map((r) => ({ item_code: r.item_code, qty: r.qty, schedule_date: r.schedule_date,
        warehouse: r.uom === 'Kg' || r.item_code.startsWith('RM-') ? WH.raw : WH.purchased })),
    });
  }

  // 与 ERPNext 网页上选 BOM 时一样：请 ERPNext 从 BOM 带出工序和所需物料（get_items_and_operations_from_bom）。
  // 工单里没有工序，ERPNext 提交时就不会生成作业卡（第 3 轮真 ERPNext 演练发现）
  async withBomOperations(wo) {
    const r = await this.req('POST', '/api/method/run_doc_method', {
      docs: JSON.stringify({ doctype: 'Work Order', __islocal: 1, ...wo }), method: 'get_items_and_operations_from_bom',
    });
    const full = ((r && r.docs) || [])[0];
    if (!full || !(full.operations || []).length) {
      throw new Error(`工单 ${wo.production_item}：从 BOM ${wo.bom_no} 带不出工序`);
    }
    const drop = ['name', 'owner', 'creation', 'modified', 'modified_by', '__islocal', '__unsaved', '__onload', 'idx',
      'parent', 'parenttype', 'parentfield', 'docstatus'];
    const clean = (o) => Object.fromEntries(Object.entries(o).filter(([k, v]) => !drop.includes(k) && v !== null));
    const out = clean(full);
    for (const k of ['operations', 'required_items']) if (Array.isArray(full[k])) out[k] = full[k].map(clean);
    // 工序顺序号全部设为 1（ERPNext 允许相同顺序号，表示可并行）。顺序号不同时，ERPNext 要求前一道工序的
    // 作业卡提交后后一道才能记完工数；车间是流水作业（一件做完就进下一道），逐件报工会被拒。
    // 顺序号留空也不行：ERPNext 会自动按行号编成 1、2、3…（第 3 轮真 ERPNext 演练发现）
    out.operations = out.operations.map((o) => ({ ...o, sequence_id: 1 }));
    return out;
  }

  async defaultBom(item) {
    const rows = await this.list('BOM', [['item', '=', item], ['is_default', '=', 1], ['docstatus', '=', 1]], ['name']);
    if (!rows.length) throw new Error(`物料 ${item} 没有生效的默认 BOM`);
    return rows[0].name;
  }

  // ------------------------------------------------------------ 2. 车间报工 → 作业卡
  async jobCard(workOrder, operation) {
    if (this.missing.has(workOrder)) return null;
    const rows = await this.list('Job Card', [['work_order', '=', workOrder], ['operation', '=', operation]], ['name']);
    if (!rows.length) {
      // 工单不在这个 ERPNext 里（例如教学情景的演示工单），记下后不再查询
      const wo = await this.list('Work Order', [['name', '=', workOrder]], ['name']);
      if (!wo.length) this.missing.add(workOrder);
      return null;
    }
    return rows[0].name;
  }

  // 同一工单同一工序的事件按到达顺序逐个处理（先排队、再查询），避免“最后一件的工时”和“工序完工提交”抢先后
  async onCycleEnd(m) {
    const d = m.data;
    return this.withLock(`${d.work_order}|${d.operation}`, async () => {
      const jc = await this.jobCard(d.work_order, d.operation);
      if (!jc) return [];
      const doc = await this.get('Job Card', jc);
      if (doc.docstatus !== 0) return [];
      const logs = (doc.time_logs || []).map((l) => ({ from_time: l.from_time, to_time: l.to_time,
        completed_qty: l.completed_qty }));
      const start = d.factory_start_ts || new Date(Date.parse(d.factory_ts || m.ts) - d.cycle_time_s * 1000).toISOString();
      logs.push({ from_time: erpDatetime(start), to_time: erpDatetime(d.factory_ts || m.ts), completed_qty: 1 });
      const upd = await this.update('Job Card', jc, { time_logs: logs });
      return [this.doc('Job Card', upd, 'updated', { corr: m.corr, mode: m.mode })];
    });
  }

  async onOpComplete(m) {
    const d = m.data;
    const out = [];
    // 有检验单的工序（演示工厂的零件检验；清单里写了测量特性的工序，第 45 轮）
    const gated = d.operation === INSPECTION_OP || this.qiOps.has(`${d.work_order}|${d.operation}`);
    if (gated) {
      // 检验工序：先等这张工单的检验单都建好（在锁外等，建检验单也要用同一把锁）
      for (let i = 0; i < 160 && this.qiPending(d.work_order); i++) await new Promise((r) => setTimeout(r, 250));
    }
    const jc = await this.withLock(`${d.work_order}|${d.operation}`, async () => {
      const name = await this.jobCard(d.work_order, d.operation);
      if (!name) return null;
      const doc = await this.get('Job Card', name);
      if (doc.docstatus !== 0) return name;
      const patch = { docstatus: 1 };
      if (gated) {
        // 作业卡只能关联一张检验单；ERPNext 默认“检验单判不合格就不许提交”，所以关联最近一张合格的
        //（不合格的零件已在总线上走不合格品处置，完工入库只按合格数）
        const qi = await this.list('Quality Inspection', [['reference_type', '=', 'Job Card'], ['reference_name', '=', name],
          ['docstatus', '=', 1]], ['name', 'status'], { order_by: 'creation asc' });
        const ok = qi.filter((q) => q.status === 'Accepted');
        const pick = ok.length ? ok[ok.length - 1] : qi[qi.length - 1];
        if (pick) patch.quality_inspection = pick.name;
      }
      const upd = await this.update('Job Card', name, patch);
      out.push(this.doc('Job Card', upd, 'submitted', { corr: m.corr, mode: m.mode }));
      return name;
    });
    if (!jc) return [];
    if (d.last_op && d.qty_good > 0) {
      out.push(...await this.manufacture(d.work_order, d.qty_good, m));
    }
    return out;
  }

  qiPending(workOrder) {
    for (const buf of this.qiBuffer.values()) if (buf.some((x) => x.work_order === workOrder)) return true;
    return this.qiInFlight > 0;
  }

  async manufacture(workOrder, qty, m) {
    const se = await this.method('erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry',
      { work_order_id: workOrder, purpose: 'Manufacture', qty });
    delete se.name;
    // 完工入库单从 BOM 继承了“需要检验”，会要求成品行再挂一张检验单；本厂的检验在“零件检验”工序逐件完成
    //（每件一张检验单，挂在该工序作业卡上，入库数量就是合格数），这里不再重复要求（第 3 轮演练发现）
    se.inspection_required = 0;
    se.remarks = `${se.remarks ? se.remarks + '；' : ''}检验已在“零件检验”工序逐件完成（见该工序作业卡的检验单），入库数量为合格数`;
    se.docstatus = 1;
    const doc = await this.insert('Stock Entry', se);
    const wo = await this.get('Work Order', workOrder);
    const out = [this.doc('Stock Entry', doc, 'submitted', { corr: m.corr, mode: m.mode }),
      this.doc('Work Order', wo, 'updated', { corr: m.corr, mode: m.mode })];
    out.push(...await this.bins());
    return out;
  }

  // ------------------------------------------------------------ 3. 测量值 → 质量检验单
  async onMeasurement(m) {
    const d = m.data;
    if (d.template && d.operation) this.qiOps.add(`${d.work_order}|${d.operation}`);
    const buf = this.qiBuffer.get(d.part_serial) || [];
    buf.push(d);
    this.qiBuffer.set(d.part_serial, buf);
    if (buf.length < (d.n_chars || 3)) return [];
    this.qiBuffer.delete(d.part_serial);
    this.qiInFlight += 1;
    try {
      return await this.createQi(d, buf, m);
    } finally {
      this.qiInFlight -= 1;
    }
  }

  async createQi(d, buf, m) {
    if (!d.work_order) return [];
    // 建检验单时 ERPNext 会回写检验工序的作业卡：与该作业卡的报工排队进行，避免数据库冲突（第 3 轮演练发现）
    return this.withLock(`${d.work_order}|${d.operation || INSPECTION_OP}`, () => this.createQi1(d, buf, m));
  }

  async createQi1(d, buf, m) {
    // 演示工厂在“零件检验”工序测；清单第 2 版的工厂按测量特性写的工序（关节测试、整机标定…，第 45 轮）
    const jc = await this.jobCard(d.work_order, d.template ? d.operation : INSPECTION_OP);
    if (!jc) return [];
    const tmpl = QI_TEMPLATE[d.item] || d.template;
    const spec = (x) => QI_PARAM[x.characteristic] || x.spec;
    const ok = buf.every((x) => x.result === 'pass');
    const doc = await this.insert('Quality Inspection', {
      report_date: erpDate(d.factory_ts || m.ts), inspection_type: 'In Process', reference_type: 'Job Card',
      reference_name: jc, item_code: d.item, sample_size: 1, inspected_by: 'Administrator',
      status: ok ? 'Accepted' : 'Rejected', manual_inspection: 1, remarks: `零件 ${d.part_serial}（${d.template ? d.operation + '自动测量' : '三坐标自动测量'}，经统一数据总线）`,
      ...(tmpl ? { quality_inspection_template: tmpl } : {}),
      readings: buf.filter((x) => spec(x)).map((x) => ({
        specification: spec(x), numeric: 1, manual_inspection: 1,
        min_value: x.lower_tol_mm, max_value: x.upper_tol_mm, reading_1: String(x.value_mm),
        status: x.result === 'pass' ? 'Accepted' : 'Rejected',
      })),
      docstatus: 1,
    });
    return [this.doc('Quality Inspection', doc, 'submitted', { corr: m.corr, mode: m.mode, extra: { part_serial: d.part_serial } })];
  }

  // ------------------------------------------------------------ 4. 设计发布 → 物料版本、BOM、附件
  async ensureCustomField(dt, fieldname, spec) {
    const key = `${dt}.${fieldname}`;
    if (this.fieldsOk && this.fieldsOk.has(key)) return;
    const rows = await this.list('Custom Field', [['dt', '=', dt], ['fieldname', '=', fieldname]], ['name']);
    if (!rows.length) {
      try {
        await this.insert('Custom Field', { dt, fieldname, ...spec });
      } catch (e) {
        // 两张提议同时第一次用到这个字段时会并发建：另一张已经建好就不算错
        const again = await this.list('Custom Field', [['dt', '=', dt], ['fieldname', '=', fieldname]], ['name']);
        if (!again.length) throw e;
      }
    }
    (this.fieldsOk = this.fieldsOk || new Set()).add(key);
  }

  async ensureRevisionField() {
    await this.ensureCustomField('Item', 'wq_revision', { label: '设计版本 Design revision',
      fieldtype: 'Int', insert_after: 'item_name', read_only: 1 });
  }

  async onRelease(m) {
    const d = m.data;
    const out = [];
    await this.ensureRevisionField();
    const item = await this.update('Item', d.item, { wq_revision: d.revision });
    out.push(this.doc('Item', item, 'updated', { corr: m.corr, mode: m.mode }));
    if (Array.isArray(d.bom) && d.bom.length) {
      const cur = await this.get('BOM', await this.defaultBom(d.item));
      const same = cur.items.length === d.bom.length && d.bom.every((b) => cur.items.some(
        (c) => c.item_code === b.item_code && Math.abs(Number(c.qty) - Number(b.qty)) < 1e-6));
      if (!same) {
        const nb = await this.insert('BOM', {
          item: d.item, quantity: 1, company: await this.getCompany(), is_active: 1, is_default: 1,
          with_operations: cur.with_operations, inspection_required: cur.inspection_required,
          ...(cur.quality_inspection_template ? { quality_inspection_template: cur.quality_inspection_template } : {}),
          items: d.bom.map((b) => ({ item_code: b.item_code, qty: b.qty })),
          operations: (cur.operations || []).map((o) => ({ operation: o.operation, workstation: o.workstation,
            time_in_mins: o.time_in_mins })),
          docstatus: 1,
        });
        out.push(this.doc('BOM', nb, 'submitted', { corr: m.corr, mode: m.mode, extra: { revision: d.revision } }));
      }
    }
    for (const f of d.files || []) out.push(...await this.attach(d.item, f, m));
    return out;
  }

  // 工艺规程生效（第 13 轮）：物料不变，BOM 的工序与工时换成新工艺，建新版默认 BOM——新工单的计划工时和成本随之改变
  async onProcess(m) {
    const d = m.data;
    const cur = await this.get('BOM', await this.defaultBom(d.item));
    const ops = d.operations.map((o, i) => ({ operation: o.operation, workstation: o.workstation,
      time_in_mins: Number(o.minutes), sequence_id: i + 1 }));
    const same = (cur.operations || []).length === ops.length && ops.every((o, i) => cur.operations[i].operation === o.operation
      && cur.operations[i].workstation === o.workstation && Math.abs(Number(cur.operations[i].time_in_mins) - o.time_in_mins) < 1e-6);
    if (same) return [];
    const nb = await this.insert('BOM', {
      item: d.item, quantity: 1, company: await this.getCompany(), is_active: 1, is_default: 1, with_operations: 1,
      inspection_required: cur.inspection_required,
      ...(cur.quality_inspection_template ? { quality_inspection_template: cur.quality_inspection_template } : {}),
      items: (cur.items || []).map((b) => ({ item_code: b.item_code, qty: b.qty })),
      operations: ops, docstatus: 1,
    });
    const was = (cur.operations || []).reduce((a, o) => a + Number(o.time_in_mins || 0), 0);
    return [this.doc('BOM', nb, 'submitted', { corr: m.corr, mode: m.mode,
      extra: { process_revision: d.revision, minutes_before: was, minutes_after: ops.reduce((a, o) => a + o.time_in_mins, 0) } })];
  }

  async onGcode(m) {
    const d = m.data;
    if (!d.gcode_url) return [];
    // 第 13 轮：数控编程随工艺规程下发的程序带程序号（一道工序两次装夹就有两个程序）
    const prog = d.program ? `-O${String(d.program).padStart(4, '0')}` : '';
    return this.attach(d.item, { name: `${d.item}-rev${d.revision}-${d.operation}${prog}.nc`, url: d.gcode_url }, m);
  }

  async attach(item, f, m) {
    const base = (process.env.WQ_HUB_PUBLIC_URL || 'http://localhost:8100').replace(/\/$/, '');
    const url = /^https?:/.test(f.url) ? f.url : base + f.url;
    const doc = await this.insert('File', { file_name: f.name, file_url: url, attached_to_doctype: 'Item',
      attached_to_name: item, is_private: 0 });
    return [this.doc('File', doc, 'created', { corr: m.corr, mode: m.mode, extra: { item } })];
  }

  // ------------------------------------------------------------ 5. ERPNext → 总线（轮询）
  async poll() {
    const out = [];
    for (const dt of ['Sales Order', 'Work Order', 'Material Request', 'Purchase Order', 'Lead', 'Opportunity', 'Quotation', 'Contract', 'Issue',
      'Asset', 'Asset Maintenance', 'Asset Repair', 'Asset Maintenance Log', 'Employee', 'Department', 'Designation', 'Purchase Receipt',
      'Sales Invoice', 'Purchase Invoice', 'Payment Entry']) {
      const since = this.lastModified[dt];
      const filters = since ? [['modified', '>', since]] : [];
      const rows = await this.list(dt, filters, ['name', 'modified'], { order_by: 'modified asc', limit: 200 });
      for (const r of rows) {
        if (!this.lastModified[dt] || r.modified > this.lastModified[dt]) this.lastModified[dt] = r.modified;
        if (this.published.get(`${dt}|${r.name}`) === r.modified) continue;
        const doc = await this.get(dt, r.name);
        out.push(this.doc(dt, doc, since ? 'updated' : 'snapshot'));
      }
    }
    return out;
  }

  async bins() {
    const rows = await this.list('Bin', [], ['item_code', 'warehouse', 'actual_qty', 'ordered_qty', 'reserved_qty',
      'projected_qty', 'stock_uom'], { limit: 2000 });
    const out = [];
    for (const b of rows) {
      const key = `${b.item_code}@${b.warehouse}`;
      const sig = `${b.actual_qty}|${b.ordered_qty}|${b.reserved_qty}|${b.projected_qty}`;
      if (this.binSeen.get(key) === sig) continue;
      this.binSeen.set(key, sig);
      out.push(this.doc('Bin', { name: key, ...b }, 'snapshot'));
    }
    return out;
  }
}

// erp.doc 的 data：只放看板和 AI 需要的字段
function summarize(doctype, d) {
  const pick = (keys) => Object.fromEntries(keys.filter((k) => d[k] !== undefined).map((k) => [k, d[k]]));
  switch (doctype) {
    case 'Sales Order':
      return { ...pick(['customer', 'delivery_date', 'transaction_date', 'status', 'docstatus', 'per_delivered']),
        items: (d.items || []).map((i) => ({ item_code: i.item_code, qty: i.qty, delivered_qty: i.delivered_qty || 0, rate: i.rate })), ...pick(['per_billed']) };
    case 'Work Order':
      return { ...pick(['production_item', 'qty', 'produced_qty', 'status', 'docstatus', 'bom_no',
        'expected_delivery_date']), planned_start_date: String(d.planned_start_date || '').slice(0, 10),
        ...((d.sales_order || d.wq_sales_order) ? { sales_order: d.sales_order || d.wq_sales_order } : {}) };
    case 'Material Request':
      return { ...pick(['material_request_type', 'status', 'docstatus', 'transaction_date', 'schedule_date']),
        items: (d.items || []).map((i) => ({ item_code: i.item_code, qty: i.qty, schedule_date: i.schedule_date })) };
    case 'Purchase Order':
      return { ...pick(['supplier', 'status', 'docstatus']),
        items: (d.items || []).map((i) => ({ item_code: i.item_code, qty: i.qty, received_qty: i.received_qty || 0,
          schedule_date: i.schedule_date })) };
    case 'Job Card':
      return pick(['work_order', 'operation', 'workstation', 'for_quantity', 'total_completed_qty', 'total_time_in_mins',
        'status', 'docstatus', 'quality_inspection']);
    case 'Quality Inspection':
      return { ...pick(['item_code', 'reference_type', 'reference_name', 'status', 'docstatus', 'report_date']),
        readings: (d.readings || []).map((r) => ({ specification: r.specification, reading_1: r.reading_1, status: r.status })) };
    case 'Stock Entry':
      return pick(['purpose', 'stock_entry_type', 'work_order', 'fg_completed_qty', 'docstatus']);
    case 'Item':
      return pick(['item_code', 'item_name', 'wq_revision']);
    case 'BOM':
      return { ...pick(['item', 'is_default', 'is_active', 'docstatus']),
        items: (d.items || []).map((i) => ({ item_code: i.item_code, qty: i.qty })) };
    case 'Bin':
      return pick(['item_code', 'warehouse', 'actual_qty', 'ordered_qty', 'reserved_qty', 'projected_qty', 'stock_uom']);
    case 'File':
      return pick(['file_name', 'file_url', 'attached_to_doctype', 'attached_to_name']);
    case 'Lead':
      return pick(['lead_name', 'company_name', 'status', 'wq_note', 'creation']);
    case 'Opportunity':
      return pick(['opportunity_from', 'party_name', 'status', 'opportunity_amount', 'expected_closing', 'transaction_date']);
    case 'Quotation':
      return { ...pick(['quotation_to', 'party_name', 'status', 'docstatus', 'valid_till', 'grand_total', 'total', 'opportunity', 'transaction_date']),
        items: (d.items || []).map((i) => ({ item_code: i.item_code, qty: i.qty, rate: i.rate })) };
    case 'Contract':
      return pick(['party_type', 'party_name', 'status', 'docstatus', 'is_signed', 'start_date', 'end_date', 'wq_penalty_per_day',
        'wq_response_h', 'wq_warranty_months', 'wq_amount', 'wq_quotation', 'wq_sales_order']);
    case 'Issue':
      return pick(['subject', 'status', 'customer', 'opening_date', 'resolution_date', 'wq_serial', 'wq_kind', 'wq_engineer', 'wq_day']);
    case 'Purchase Receipt':            // 第 18 轮 E5
      return { ...pick(['supplier', 'status', 'docstatus', 'posting_date', 'wq_lot']),
        items: (d.items || []).map((i) => ({ item_code: i.item_code, qty: i.qty, purchase_order: i.purchase_order, quality_inspection: i.quality_inspection })) };
    case 'Sales Invoice':               // 第 18 轮 E7
      return { ...pick(['customer', 'status', 'docstatus', 'posting_date', 'due_date', 'grand_total', 'outstanding_amount']),
        sales_orders: [...new Set((d.items || []).map((i) => i.sales_order).filter(Boolean))] };
    case 'Purchase Invoice':
      return { ...pick(['supplier', 'status', 'docstatus', 'posting_date', 'due_date', 'grand_total', 'outstanding_amount', 'bill_no']),
        purchase_receipts: [...new Set((d.items || []).map((i) => i.purchase_receipt).filter(Boolean))] };
    case 'Payment Entry':
      return { ...pick(['payment_type', 'party_type', 'party', 'paid_amount', 'posting_date', 'docstatus']),
        references: (d.references || []).map((r) => ({ reference_doctype: r.reference_doctype, reference_name: r.reference_name, allocated_amount: r.allocated_amount })) };
    case 'Employee':                    // 第 18 轮 E4（只带工作上的字段：不带生日、电话）
      return pick(['employee_name', 'first_name', 'employee_number', 'department', 'designation', 'status', 'date_of_joining', 'company']);
    case 'Department':
      return pick(['department_name', 'company', 'parent_department', 'is_group']);
    case 'Designation':
      return pick(['designation_name']);
    case 'Asset':                       // 第 18 轮 E3
      return pick(['asset_name', 'status', 'location', 'net_purchase_amount', 'purchase_date', 'asset_category', 'docstatus']);
    case 'Asset Maintenance':
      return { ...pick(['asset_name', 'maintenance_team']),
        asset_maintenance_tasks: (d.asset_maintenance_tasks || []).map((t) => ({ name: t.name, maintenance_task: t.maintenance_task,
          periodicity: t.periodicity, description: t.description, next_due_date: t.next_due_date, last_completion_date: t.last_completion_date,
          wq_interval_h: t.wq_interval_h })) };
    case 'Asset Repair':
      return pick(['asset', 'repair_status', 'failure_date', 'completion_date', 'description', 'docstatus']);
    case 'Asset Maintenance Log':
      return pick(['asset_maintenance', 'task_name', 'maintenance_status', 'completion_date', 'docstatus']);
    default:
      return {};
  }
}

module.exports = { ERP, ErpError, summarize, erpDatetime, WH, QI_PARAM };
