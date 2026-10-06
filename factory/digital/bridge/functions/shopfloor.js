// 设备事件 → ERPNext 作业卡：每完成一件记一条工时（按工厂时间）；一道工序做完就提交作业卡；
// 最后一道工序做完，按合格数做完工入库（扣原材料、加成品，工单完工数随之更新）
const erp = global.get('wqErp');
const m = msg.payload;
if (!m || !m.data || m.mode !== erp.mode || !m.data.work_order) return null;
let job = null;
if (m.data.event === 'cycle_end') job = erp.onCycleEnd(m);
else if (m.data.event === 'op_complete') job = erp.onOpComplete(m);
if (!job) return null;
job.then((out) => {
  if (out.length) node.status({ fill: 'green', shape: 'dot', text: m.data.work_order + ' ' + m.data.operation.split(' ')[0] + ' ' + m.data.event });
  node.send([out]);
}).catch((e) => {
  node.status({ fill: 'red', shape: 'ring', text: e.message.slice(0, 50) });
  node.error(e.message, msg);
  // 写 ERPNext 失败也发到总线（erp.doc，action=failed），看板、AI 和老师都能看到原因
  node.send([[erp.failed('Job Card', e, { corr: m.corr, mode: m.mode, extra: { work_order: m.data.work_order, operation: m.data.operation, event: m.data.event } })]]);
});
return null;
