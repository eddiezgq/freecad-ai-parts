// 问渠数字工厂 · 统一数据总线（附录 A）在 Node-RED 里的小工具：拼主题、打信封。
'use strict';
const crypto = require('crypto');

const ROOT = 'wq/gearbox';
const SPEC_VERSION = 1;

function topic(...parts) {
  return [ROOT, ...parts.filter((p) => p !== null && p !== undefined && p !== '')].join('/');
}

function erpTopic(doctype) {
  return topic('office', 'erp', doctype.toLowerCase().replace(/ /g, '_'));
}

function nowIso() {
  return new Date().toISOString();
}

// 信封：{v, id, ts, type, source, mode, corr, data}
function make(type, source, data, { mode = process.env.WQ_MODE || 'teach', corr = null, ts = null } = {}) {
  return { v: SPEC_VERSION, id: crypto.randomUUID(), ts: ts || nowIso(), type, source, mode, corr, data };
}

// 收到的消息做最基本的检查（完整校验在 Python 的 wqbus 里，历史库会记下不合格的消息）
function check(msg) {
  const need = ['v', 'id', 'ts', 'type', 'source', 'mode', 'data'];
  for (const k of need) if (msg == null || msg[k] === undefined) throw new Error('消息缺少字段 ' + k);
  if (msg.v > SPEC_VERSION) throw new Error('消息版本 v' + msg.v + ' 比桥接支持的新');
  return msg;
}

module.exports = { ROOT, SPEC_VERSION, topic, erpTopic, make, check, nowIso };
