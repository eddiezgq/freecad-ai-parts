// 按单设计（ETO，第 139 轮）在 ERPNext 里的写入：只用 ERPNext 自带单据，不改源码。
//   eto_quote：作业号 = Project；这一单专用的物料（编号 = 作业号，名称 = 客户要的东西）；报价单（自定义字段 wq_job 记作业号，
//              数量阶梯与付款条件写进条款）。重复执行时已有的 Project、物料不重建。
//   eto_order：销售订单（挂 Project、引用报价单，付款计划按里程碑）。
//   eto_release：设计发布——新物料、物料清单（带工序，子件先建）并设为默认；同一指纹的物料清单已有就不重建。
//   eto_change（第 150 轮）：设计变更处理——工单取消 / 停止，请购单取消，采购单改量 / 取消 / 关闭；“照用”不动 ERPNext。
// 共有文件（问渠与 freecad-ai-parts 两边一样）；erp.js 加载后，方法里的 this 是 ERP 实例。
const erpToday = () => new Date().toISOString().slice(0, 10);


// 请购单：每行挂作业号（Project）；仓库按物料类别（原材料库 / 外购件库；外协服务挂外购件库，不进库存）
async function etoRequest(company, jn, rows, { out, created, opt }, WH) {
  if (!(rows || []).length) return;
  const today = new Date().toISOString().slice(0, 10);
  const mr = await this.insert('Material Request', { material_request_type: 'Purchase', company, transaction_date: today,
    schedule_date: rows.map((r) => r.schedule_date).sort()[0], docstatus: 1,
    items: rows.map((r) => ({ item_code: r.item_code, qty: r.qty, schedule_date: r.schedule_date, project: jn,
      warehouse: r.wh === 'raw' ? WH.raw : WH.purchased })) });
  out.push(this.doc('Material Request', mr, 'submitted', opt));
  created.push(['Material Request', mr.name]);
}

const WHK = { make: 'semi', buy: 'purchased', raw: 'raw' };

module.exports = ({ WH }) => ({
  async eto_quote(pv, { out, created, opt }) {
    const company = await this.getCompany();
    const customer = await this.customerFor(pv.quotation.party);
    await this.ensureCustomField('Quotation', 'wq_job', { label: '作业号 Job', fieldtype: 'Data', insert_after: 'party_name', read_only: 1 });
    const jobNo = pv.job.job_no;
    // 作业号 = Project（ERPNext 默认按项目名称命名）
    let proj = (await this.list('Project', [['project_name', '=', pv.project.project_name]], ['name']))[0];
    if (proj) {
      proj = await this.get('Project', proj.name);
    } else {
      proj = await this.insert('Project', { project_name: pv.project.project_name, company, customer, status: 'Open',
        ...(pv.project.expected_end_date ? { expected_end_date: pv.project.expected_end_date } : {}),
        notes: pv.project.notes || '' });
      out.push(this.doc('Project', proj, 'created', opt));
    }
    created.push(['Project', proj.name]);
    // 这一单专用的物料：设计发布前没有物料清单（第 139b 段补）
    const it = pv.item;
    let item;
    if ((await this.list('Item', [['name', '=', it.item_code]])).length) {
      item = await this.get('Item', it.item_code);
    } else {
      item = await this.insert('Item', { item_code: it.item_code, item_name: it.item_name, item_group: it.item_group,
        stock_uom: it.stock_uom || 'Nos', is_stock_item: 1, include_item_in_manufacturing: 1, description: it.description || it.item_name });
      out.push(this.doc('Item', item, 'created', opt));
    }
    created.push(['Item', item.name]);
    const q = pv.quotation;
    const qt = await this.insert('Quotation', { quotation_to: 'Customer', party_name: customer, company,
      transaction_date: q.transaction_date || erpToday(), valid_till: q.valid_till, order_type: 'Sales', wq_job: jobNo,
      terms: q.terms, items: [{ item_code: it.item_code, qty: q.qty, rate: q.rate }], docstatus: 1 });
    out.push(this.doc('Quotation', qt, 'submitted', opt));
    created.push(['Quotation', qt.name]);
  },

  async eto_order(pv, { out, created, opt }) {
    const company = await this.getCompany();
    const so = pv.sales_order;
    const customer = await this.customerFor(so.customer);
    const doc = await this.insert('Sales Order', { customer, company, transaction_date: so.transaction_date, delivery_date: so.delivery_date,
      order_type: 'Sales', project: so.project, docstatus: 1,
      items: [{ item_code: so.item_code, qty: so.qty, rate: so.rate, delivery_date: so.delivery_date, warehouse: WH.fg,
        ...(so.quotation ? { prevdoc_docname: so.quotation } : {}) }],
      ...((so.payment_schedule || []).length ? { payment_schedule: so.payment_schedule.map((p) => ({ due_date: p.due_date,
        invoice_portion: p.invoice_portion, payment_amount: p.payment_amount, description: p.description })) } : {}) });
    out.push(this.doc('Sales Order', doc, 'submitted', opt));
    created.push(['Sales Order', doc.name]);
  },

  async eto_release(pv, { out, created, opt }) {
    const company = await this.getCompany();
    await this.ensureCustomField('BOM', 'wq_fingerprint', { label: '设计指纹 Design fingerprint', fieldtype: 'Data', insert_after: 'item', read_only: 1 });
    for (const it of pv.items) {
      if ((await this.list('Item', [['name', '=', it.code]])).length) continue;
      const doc = await this.insert('Item', { item_code: it.code, item_name: it.name, item_group: it.item_group, stock_uom: it.uom,
        is_stock_item: 1, include_item_in_manufacturing: 1, description: `${it.name}（按单设计 ${pv.job.job_no}）`,
        is_purchase_item: it.kind === 'make' ? 0 : 1, default_material_request_type: it.kind === 'make' ? 'Manufacture' : 'Purchase',
        item_defaults: [{ company, default_warehouse: WH[WHK[it.kind]], ...(it.supplier ? { default_supplier: it.supplier } : {}) }],
        ...(it.supplier ? { supplier_items: [{ supplier: it.supplier }] } : {}),
        ...(it.price !== null && it.price !== undefined ? { valuation_rate: it.price } : {}),
        ...(it.lead ? { lead_time_days: it.lead } : {}) });
      out.push(this.doc('Item', doc, 'created', opt));
      created.push(['Item', doc.name]);
    }
    const made = {};
    for (const b of pv.boms) {        // 子件先建
      const have = await this.list('BOM', [['item', '=', b.item], ['wq_fingerprint', '=', pv.fingerprint], ['docstatus', '=', 1]], ['name']);
      if (have.length) {
        made[b.item] = have[0].name;
        // 已经建过（同一指纹）：只确保它是默认；也发一条回总线，提议照样有“执行完”的标记
        const doc = b.item === pv.job.job_no ? await this.update('BOM', have[0].name, { is_default: 1 }) : await this.get('BOM', have[0].name);
        out.push(this.doc('BOM', doc, 'updated', opt));
        created.push(['BOM', doc.name]);
        continue;
      }
      const items = [];
      for (const c of b.components) {
        const row = { item_code: c.item_code, qty: c.qty, uom: c.uom };
        if (made[c.item_code]) row.bom_no = made[c.item_code];
        else if (!c.new && (await this.list('BOM', [['item', '=', c.item_code], ['is_default', '=', 1], ['docstatus', '=', 1]], ['name'])).length) {
          row.bom_no = await this.defaultBom(c.item_code);
        }
        items.push(row);
      }
      const doc = await this.insert('BOM', { item: b.item, quantity: 1, company, is_active: 1, is_default: 1, with_operations: 1,
        rm_cost_as_per: 'Valuation Rate', wq_fingerprint: pv.fingerprint, project: pv.job.project || pv.job.job_no,
        operations: b.operations.map((o, i) => ({ ...o, sequence_id: i + 1 })), items, docstatus: 1 });
      made[b.item] = doc.name;
      out.push(this.doc('BOM', doc, 'submitted', opt));
      created.push(['BOM', doc.name]);
    }
  },

  // 第 150 轮 150a：设计变更处理。每条按人选的做；已经是目标状态的跳过（重发不重做）
  async eto_change(pv, { out, created, opt }) {
    for (const a of pv.actions) {
      if (a.action === 'keep') continue;
      const cur = await this.get(a.doctype, a.name);
      if (Number(cur.docstatus) === 2 || ['Cancelled', 'Closed', 'Stopped'].includes(cur.status)) {
        out.push(this.doc(a.doctype, cur, 'updated', opt));
        continue;
      }
      if (a.action === 'cancel' || a.action === 'renew') {
        await this.method('frappe.client.cancel', { doctype: a.doctype, name: a.name });
      } else if (a.action === 'stop') {
        await this.method('erpnext.manufacturing.doctype.work_order.work_order.stop_unstop', { work_order: a.name, status: 'Stopped' });
      } else if (a.action === 'close') {
        await this.method('erpnext.buying.doctype.purchase_order.purchase_order.update_status', { status: 'Closed', name: a.name });
      } else if (a.action === 'qty') {
        const want = Object.fromEntries((a.lines || []).map((l) => [l.item_code, Number(l.qty)]));
        const rows = (cur.items || []).filter((r) => !(r.item_code in want) || want[r.item_code] > 1e-9).map((r) => ({
          docname: r.name, item_code: r.item_code, qty: r.item_code in want ? want[r.item_code] : r.qty, rate: r.rate,
          conversion_factor: r.conversion_factor, uom: r.uom, schedule_date: r.schedule_date, description: r.description }));
        await this.method('erpnext.controllers.accounts_controller.update_child_qty_rate', { parent_doctype: a.doctype,
          trans_items: JSON.stringify(rows), parent_doctype_name: a.name, child_docname: 'items' });
      } else {
        throw new Error(`不认识的处理方式 ${a.action}`);
      }
      const doc = await this.get(a.doctype, a.name);
      out.push(this.doc(a.doctype, doc, 'updated', opt));
      created.push([a.doctype, a.name]);
    }
  },

  async eto_materials(pv, { out, created, opt }) {
    const company = await this.getCompany();
    const jn = pv.job.job_no;
    for (const sv of pv.service_items || []) {          // 外协服务：不进库存的物料
      if ((await this.list('Item', [['name', '=', sv.code]])).length) continue;
      const grp = (await this.list('Item Group', [['is_group', '=', 0]], ['name'], { limit: 1 }))[0];
      const it = await this.insert('Item', { item_code: sv.code, item_name: sv.name, stock_uom: 'Nos', is_stock_item: 0, is_purchase_item: 1,
        description: `${sv.name}（按单设计 ${jn}）`, ...(grp ? { item_group: grp.name } : {}) });
      out.push(this.doc('Item', it, 'created', opt));
      created.push(['Item', it.name]);
    }
    for (const w of pv.work_orders || []) {
      const top = w.production_item === pv.job.job_no;
      if (!top) {
        await this.ensureCustomField('Work Order', 'wq_sales_order', { label: '对应销售订单 For sales order',
          fieldtype: 'Link', options: 'Sales Order', insert_after: 'sales_order', read_only: 1 });
      }
      const wo = await this.withBomOperations({ production_item: w.production_item, bom_no: await this.defaultBom(w.production_item),
        qty: w.qty, company, project: pv.job.project || jn, ...(top ? { sales_order: pv.job.sales_order } : { wq_sales_order: pv.job.sales_order }),
        planned_start_date: `${w.planned_start_date} 08:00:00`, expected_delivery_date: w.expected_delivery_date, skip_transfer: 1,
        source_warehouse: WH.raw, wip_warehouse: WH.wip, fg_warehouse: w.warehouse === 'fg' ? WH.fg : WH.semi, use_multi_level_bom: 0 });
      if (w.sources) wo.required_items = (wo.required_items || []).map((r) => ({ ...r, source_warehouse: WH[w.sources[r.item_code]] || WH.raw }));
      const doc = await this.insert('Work Order', { ...wo, docstatus: 1 });
      out.push(this.doc('Work Order', doc, 'submitted', opt));
      created.push(['Work Order', doc.name]);
    }
    await etoRequest.call(this, company, pv.job.project || jn, pv.material_requests, { out, created, opt }, WH);
  },

  async eto_early_buy(pv, { out, created, opt }) {
    const company = await this.getCompany();
    for (const r of pv.material_requests) {          // 设计里的新外购件：先在 ERPNext 建物料
      const it = r.new_item;
      if (!it || (await this.list('Item', [['name', '=', it.code]])).length) continue;
      const doc = await this.insert('Item', { item_code: it.code, item_name: it.name, item_group: it.item_group, stock_uom: it.uom,
        is_stock_item: 1, is_purchase_item: 1, description: `${it.name}（按单设计 ${pv.job.job_no}）`,
        item_defaults: [{ company, default_warehouse: it.kind === 'raw' ? WH.raw : WH.purchased }],
        ...(it.price !== null && it.price !== undefined ? { valuation_rate: it.price } : {}), ...(it.lead ? { lead_time_days: it.lead } : {}) });
      out.push(this.doc('Item', doc, 'created', opt));
      created.push(['Item', doc.name]);
    }
    await etoRequest.call(this, company, pv.job.project || pv.job.job_no, pv.material_requests, { out, created, opt }, WH);
  },


  async eto_hours(pv, { out, created, opt }) {
    const company = await this.getCompany();
    const act = '设计 Engineering';
    if (!(await this.list('Activity Type', [['name', '=', act]])).length) await this.insert('Activity Type', { activity_type: act });
    const ts = await this.insert('Timesheet', { company, parent_project: pv.job.project, note: pv.note || '',
      time_logs: [{ activity_type: act, hours: pv.hours, from_time: `${pv.day} 09:00:00`, project: pv.job.project,
        description: `${pv.who}：${pv.note || '设计'}` }], docstatus: 1 });
    out.push(this.doc('Timesheet', ts, 'submitted', opt));
    created.push(['Timesheet', ts.name]);
  },

  // 检验记录 → ERPNext 质量检验单（挂这张工单最后一道工序的作业卡）
  async eto_inspection(pv, { out, created, opt }) {
    for (const r of pv.readings) {
      if (!(await this.list('Quality Inspection Parameter', [['name', '=', r.spec]], ['name'])).length) {
        await this.insert('Quality Inspection Parameter', { parameter: r.spec });
      }
    }
    const jc = await this.jobCard(pv.work_order, pv.operation);
    if (!jc) throw new Error(`工单 ${pv.work_order} 的工序 ${pv.operation} 没有作业卡（工单下达车间了吗？）`);
    const qi = await this.insert('Quality Inspection', { report_date: pv.day, inspection_type: 'In Process', reference_type: 'Job Card',
      reference_name: jc, item_code: pv.item, sample_size: 1, inspected_by: 'Administrator', manual_inspection: 1,
      status: pv.result === 'pass' ? 'Accepted' : 'Rejected',
      remarks: `作业 ${pv.job.job_no} ${pv.kind === 'fai' ? '首件检验' : '终检'} 第 ${pv.piece} 件，检验员 ${pv.inspector}（问渠数字工厂）`,
      readings: pv.readings.map((r) => ({ specification: r.spec, numeric: 1, manual_inspection: 1, min_value: r.lo, max_value: r.hi,
        reading_1: r.value === null ? '' : String(r.value), status: r.result === 'pass' ? 'Accepted' : 'Rejected' })),
      docstatus: 1 });
    out.push(this.doc('Quality Inspection', qi, 'submitted', opt));
    created.push(['Quality Inspection', qi.name]);
  },

  // 发货：按销售订单生成发货单，发这一单的件数（终检合格的关口在平台上判过）
  async eto_ship(pv, { out, created, opt }) {
    const draft = await this.method('erpnext.selling.doctype.sales_order.sales_order.make_delivery_note', { source_name: pv.sales_order });
    draft.items = (draft.items || []).filter((i) => i.item_code === pv.job.job_no).map((i) => ({ ...i, qty: pv.qty }));
    if (!draft.items.length) throw new Error(`销售订单 ${pv.sales_order} 上没有 ${pv.job.job_no} 待发`);
    delete draft.__islocal;
    const dn = await this.insert('Delivery Note', { ...draft, remarks: `作业 ${pv.job.job_no}：终检合格 ${pv.qty} 件，合格证见问渠数字工厂`, docstatus: 1 });
    out.push(this.doc('Delivery Note', dn, 'submitted', opt));
    created.push(['Delivery Note', dn.name]);
  },

  // 第 139g 段：按里程碑分期开票。按销售订单生成发票骨架，只留作业这一行，数量 1、单价 = 本期金额（ERPNext 按金额防超开）
  async eto_invoice(pv, { out, created, opt }) {
    const mark = `作业 ${pv.job.job_no} 分期 ${pv.key}`;
    const had = (await this.list('Sales Invoice', [['remarks', 'like', `%${mark}：%`], ['docstatus', '=', 1]], ['name']))[0];
    if (had) {                                   // 重发：这一期已经开过，就用开好的那张
      out.push(this.doc('Sales Invoice', await this.get('Sales Invoice', had.name), 'updated', opt));
      created.push(['Sales Invoice', had.name]);
      return;
    }
    const made = await this.method('erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice', { source_name: pv.sales_order });
    // ERPNext v16 按“已开票数量”算剩余：前两期各开 1 件后，订单这一行就不再带出来（金额其实还没开满）。
    // 带不出来时直接按销售订单的那一行补上；超开仍由 ERPNext 按金额（billed_amt）挡住。
    let row = (made.items || []).find((i) => i.item_code === pv.job.job_no);
    if (!row) {
      const so = await this.get('Sales Order', pv.sales_order);
      const it = (so.items || []).find((i) => i.item_code === pv.job.job_no);
      if (!it) throw new Error(`销售订单 ${pv.sales_order} 里没有作业 ${pv.job.job_no} 这一行`);
      row = { item_code: it.item_code, item_name: it.item_name, uom: it.uom, stock_uom: it.stock_uom,
        conversion_factor: it.conversion_factor, sales_order: so.name, so_detail: it.name,
        ...(it.warehouse ? { warehouse: it.warehouse } : {}), ...(it.cost_center ? { cost_center: it.cost_center } : {}) };
    }
    for (const k of ['name', '__islocal', '__unsaved', 'idx', 'docstatus']) delete made[k];
    for (const k of ['name', '__islocal', '__unsaved', 'parent', 'parenttype', 'parentfield', 'idx', 'docstatus', 'amount', 'base_amount']) delete row[k];
    made.items = [{ ...row, qty: 1, rate: pv.amount, price_list_rate: pv.amount, discount_percentage: 0,
      description: `${pv.job.title}：${pv.description}（${pv.pct}%）` }];
    made.posting_date = pv.posting_date;
    made.set_posting_time = 1;
    made.due_date = pv.due_date;
    made.payment_terms_template = null;
    made.payment_schedule = [];
    if (pv.job.project) made.project = pv.job.project;
    made.remarks = `${mark}：${pv.description} ${pv.pct}%（问渠数字工厂）`;
    made.docstatus = 1;
    const si = await this.insert('Sales Invoice', made);
    out.push(this.doc('Sales Invoice', si, 'submitted', opt));
    created.push(['Sales Invoice', si.name]);
  },
});
