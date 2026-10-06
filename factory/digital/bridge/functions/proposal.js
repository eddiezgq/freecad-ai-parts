// 只处理“人已确认”的提议（附录 A.4 第 2 条）；写入 ERPNext 后把每张单据作为 erp.doc 发回总线，corr = 提议编号
const erp = global.get('wqErp');
const m = msg.payload;
if (!m || !m.data || m.mode !== erp.mode || m.data.status !== 'confirmed') return null;
node.status({ fill: 'blue', shape: 'dot', text: '执行 ' + m.data.proposal_id });
erp.execProposal(m).then((out) => {
  const bad = out.some((o) => o.payload.data.action === 'failed');
  node.status({ fill: bad ? 'red' : 'green', shape: 'dot', text: m.data.proposal_id + (bad ? ' 失败' : ' 已写入 ' + out.length + ' 张') });
  node.send([out]);
}).catch((e) => { node.status({ fill: 'red', shape: 'ring', text: e.message.slice(0, 50) }); node.error(e.message, msg); });
return null;
