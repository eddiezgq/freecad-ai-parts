// 企业功能的提议在 ERPNext 里怎么执行（本仓库 ADR-0068，M19）。共有的 lib/erp.js 有这个文件就把这里的动作登记上；
// 问渠仓库没有它。每个动作以 ERP 实例为 this 调用：(preview, { out, created, opt })，往 out 放发回总线的 erp.doc、
// 往 created 记建了什么。
'use strict';

module.exports = ({ WH }) => ({
  // 本仓库 ADR-0061：FreeCAD 方案转为生产物料——建供应商、物料、BOM（自下而上）；已有的不重建（BOM 按方案版本，ADR-0062）
  async cad_to_erp(pv, { out, created, opt }) {
    const company = await this.getCompany();
    for (const sp of pv.suppliers || []) {
      if (!(await this.list('Supplier', [['name', '=', sp.name]], ['name'])).length) {
        const doc = await this.insert('Supplier', { supplier_name: sp.name, supplier_group: sp.supplier_group,
          supplier_type: 'Company' });
        created.push(['Supplier', doc.name]);
      }
    }
    for (const it of pv.items || []) {
      if ((await this.list('Item', [['name', '=', it.item_code]], ['name'])).length) continue;
      const doc = await this.insert('Item', { item_code: it.item_code, item_name: it.item_name, item_group: it.item_group,
        stock_uom: it.uom, is_stock_item: 1, include_item_in_manufacturing: 1, description: it.description || it.item_name,
        ...(it.price != null ? { standard_rate: it.price } : {}) });
      out.push(this.doc('Item', doc, 'created', opt));
      created.push(['Item', doc.name]);
    }
    // ADR-0062：BOM 按“产品 + 方案版本”识别（写在说明里）——同一版本不重建；新版本设为默认，ERPNext 自动撤下旧的默认
    const tag = `FreeCAD AI Parts 方案 ${pv.design} 第 ${pv.revision} 版`;
    for (const b of pv.boms || []) {
      if ((await this.list('BOM', [['item', '=', b.item], ['description', '=', tag], ['docstatus', '=', 1]], ['name'])).length) continue;
      const ops = (pv.routings[b.routing] || []).map(([op, mins], i) => ({ operation: op, workstation: pv.operations[op],
        time_in_mins: Number(mins), sequence_id: i + 1 }));
      const doc = await this.insert('BOM', { item: b.item, quantity: 1, company, is_active: 1, is_default: 1,
        description: tag, with_operations: 1, inspection_required: 0, docstatus: 1,
        items: b.items.map(([c, q]) => ({ item_code: c, qty: Number(q) })), operations: ops });
      out.push(this.doc('BOM', doc, 'submitted', opt));
      created.push(['BOM', doc.name]);
    }
    if (!out.length) out.push(this.doc('Item', { name: pv.code, item_code: pv.code }, 'snapshot', opt));
  },

  // 演示：供应商送货到原材料库（ERPNext 物料收货单）
  async material_receipt(pv, { out, created, opt }) {
    const company = await this.getCompany();
    const se = await this.insert('Stock Entry', { stock_entry_type: 'Material Receipt', purpose: 'Material Receipt', company,
      docstatus: 1, items: pv.items.map((r) => ({ item_code: r.item_code, qty: r.qty, uom: r.uom, stock_uom: r.uom,
        conversion_factor: 1, t_warehouse: WH.raw })) });
    out.push(this.doc('Stock Entry', se, 'submitted', opt));
    created.push(['Stock Entry', se.name]);
  },
});
