// 设计发布 → ERPNext；工艺规程生效 → 新版 BOM 工序（第 13 轮）。FreeCAD 发布 → ERPNext：物料版本号加一；BOM 用量变了就建新版 BOM；STEP、图纸、G 代码作为附件挂到物料上
const erp = global.get('wqErp');
const m = msg.payload;
if (!m || !m.data || m.mode !== erp.mode) return null;
if (!['design.release', 'design.gcode', 'process.release'].includes(m.type)) return null;   // 待审、退回等消息不写 ERPNext
const job = m.type === 'design.release' ? erp.onRelease(m) : m.type === 'process.release' ? erp.onProcess(m) : erp.onGcode(m);
job.then((out) => {
  node.status({ fill: 'green', shape: 'dot', text: m.data.item + (m.type === 'process.release' ? ' 工艺 rev ' : ' rev ') + m.data.revision });
  node.send([out]);
}).catch((e) => {
  node.status({ fill: 'red', shape: 'ring', text: e.message.slice(0, 50) });
  node.error(e.message, msg);
  // 写 ERPNext 失败也发到总线（erp.doc，action=failed），看板、AI 和老师都能看到原因
  node.send([[erp.failed('Item', e, { corr: m.corr, mode: m.mode, extra: { name: m.data.item, revision: m.data.revision } })]]);
});
return null;
