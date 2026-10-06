// 每 60 秒取一次库存（Bin），有变化的发到总线；看板的“关键物料”和算料都用它
const erp = global.get('wqErp');
erp.bins().then((out) => {
  node.status({ fill: 'grey', shape: 'dot', text: new Date().toLocaleTimeString() + ' 库存变化 ' + out.length });
  node.send([out]);
}).catch((e) => { node.status({ fill: 'red', shape: 'ring', text: e.message.slice(0, 50) }); node.error(e.message, msg); });
return null;
