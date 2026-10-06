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
            source_warehouse: WH.raw, wip_warehouse: WH.wip, fg_warehouse: MAKE_WH[w.production_item] || WH.semi,
            use_multi_level_bom: 0,
          });
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
    if (d.operation === INSPECTION_OP) {
      // 检验工序：先等这张工单的检验单都建好（在锁外等，建检验单也要用同一把锁）
      for (let i = 0; i < 160 && this.qiPending(d.work_order); i++) await new Promise((r) => setTimeout(r, 250));
    }
    const jc = await this.withLock(`${d.work_order}|${d.operation}`, async () => {
      const name = await this.jobCard(d.work_order, d.operation);
      if (!name) return null;
      const doc = await this.get('Job Card', name);
      if (doc.docstatus !== 0) return name;
      const patch = { docstatus: 1 };
      if (d.operation === INSPECTION_OP) {
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
    return this.withLock(`${d.work_order}|${INSPECTION_OP}`, () => this.createQi1(d, buf, m));
  }

  async createQi1(d, buf, m) {
    const jc = await this.jobCard(d.work_order, INSPECTION_OP);
    if (!jc) return [];
    const ok = buf.every((x) => x.result === 'pass');
    const doc = await this.insert('Quality Inspection', {
      report_date: erpDate(d.factory_ts || m.ts), inspection_type: 'In Process', reference_type: 'Job Card',
      reference_name: jc, item_code: d.item, sample_size: 1, inspected_by: 'Administrator',
      status: ok ? 'Accepted' : 'Rejected', manual_inspection: 1, remarks: `零件 ${d.part_serial}（三坐标自动测量，经统一数据总线）`,
      ...(QI_TEMPLATE[d.item] ? { quality_inspection_template: QI_TEMPLATE[d.item] } : {}),
      readings: buf.filter((x) => QI_PARAM[x.characteristic]).map((x) => ({
        specification: QI_PARAM[x.characteristic], numeric: 1, manual_inspection: 1,
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
    if (!rows.length) await this.insert('Custom Field', { dt, fieldname, ...spec });
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
    for (const dt of ['Sales Order', 'Work Order', 'Material Request', 'Purchase Order']) {
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
        items: (d.items || []).map((i) => ({ item_code: i.item_code, qty: i.qty, delivered_qty: i.delivered_qty || 0 })) };
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
    default:
      return {};
  }
}

module.exports = { ERP, ErpError, summarize, erpDatetime, WH, QI_PARAM };
