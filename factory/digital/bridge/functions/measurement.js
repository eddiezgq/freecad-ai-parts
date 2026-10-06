// 三坐标测量值 → ERPNext 质量检验单：一件零件的全部特性到齐后建一张，关联到“零件检验”工序的作业卡
const erp = global.get('wqErp');
const m = msg.payload;
if (!m || !m.data || m.mode !== erp.mode) return null;
erp.onMeasurement(m).then((out) => {
  if (out.length) node.status({ fill: 'green', shape: 'dot', text: m.data.part_serial + ' 检验单已建' });
  node.send([out]);
}).catch((e) => {
  node.status({ fill: 'red', shape: 'ring', text: e.message.slice(0, 50) });
  node.error(e.message, msg);
  // 写 ERPNext 失败也发到总线（erp.doc，action=failed），看板、AI 和老师都能看到原因
  node.send([[erp.failed('Quality Inspection', e, { corr: m.corr, mode: m.mode, extra: { work_order: m.data.work_order, part_serial: m.data.part_serial } })]]);
});
return null;
