// 每 30 秒看一次 ERPNext 里有没有新改的订单、工单、请购单、采购单（例如学生直接在 ERPNext 里操作），有就发到总线
const erp = global.get('wqErp');
erp.poll().then((out) => {
  node.status({ fill: 'grey', shape: 'dot', text: new Date().toLocaleTimeString() + ' 变化 ' + out.length });
  node.send([out]);
}).catch((e) => { node.status({ fill: 'red', shape: 'ring', text: e.message.slice(0, 50) }); node.error(e.message, msg); });
return null;
