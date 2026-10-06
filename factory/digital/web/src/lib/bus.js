// 浏览器直接订阅统一数据总线（MQTT over WebSocket）：设备状态、AGV 位置实时更新，不用等看板轮询
import { reactive } from 'vue';
import mqtt from 'mqtt';

export const bus = reactive({
  connected: false,
  machines: {},       // 单元 → 最新 machine.status 的 data（附 ts）
  agvs: {},           // 单元 → 最新 logistics.status 的 data
  rate: 0,            // 最近一分钟收到的消息数
  last: [],           // 最近 30 条消息（调试、数据流展示用）
  error: null,
});

let client = null;
let mode = 'teach';
const stamps = [];
const listeners = new Set();

export function onBus(fn) { listeners.add(fn); return () => listeners.delete(fn); }

export function connectBus(url, m) {
  mode = m || 'teach';
  if (client) return;
  client = mqtt.connect(url, { reconnectPeriod: 3000, connectTimeout: 8000, clean: true,
    clientId: 'wq-web-' + Math.random().toString(16).slice(2, 10) });
  client.on('connect', () => {
    bus.connected = true; bus.error = null;
    client.subscribe(['wq/gearbox/+/+/status', 'wq/gearbox/+/+/event', 'wq/gearbox/ai/#',
      'wq/gearbox/quality/qc-01/measurement', 'wq/gearbox/office/erp/#', 'wq/gearbox/design/#',
      'wq/gearbox/+/+/cmd/ack'], { qos: 0 });
  });
  client.on('close', () => { bus.connected = false; });
  client.on('offline', () => { bus.connected = false; if (!bus.error) bus.error = '网络断开或服务器不可达'; });
  client.on('error', (e) => { bus.error = String(e.message || e); });
  client.on('message', (topic, payload) => {
    let m;
    try { m = JSON.parse(payload.toString()); } catch (e) { return; }
    if (!m || m.mode !== mode) return;
    const now = Date.now();
    stamps.push(now);
    while (stamps.length && now - stamps[0] > 60000) stamps.shift();
    bus.rate = stamps.length;
    const unit = topic.split('/')[3];
    if (m.type === 'machine.status') bus.machines[unit] = { ...m.data, ts: m.ts };
    else if (m.type === 'logistics.status') bus.agvs[unit] = { ...m.data, ts: m.ts };
    bus.last.unshift({ topic: topic.replace('wq/gearbox/', ''), type: m.type, ts: m.ts, corr: m.corr, data: m.data });
    if (bus.last.length > 30) bus.last.pop();
    for (const fn of listeners) fn(topic, m);
  });
}

// 第 6 轮 W7②：页面上的“重试”按钮
export function reconnectBus() {
  bus.error = null;
  if (client) client.reconnect();
}

export function busMode() { return mode; }

export function setBusMode(m) {
  mode = m;
  bus.machines = {};
  bus.agvs = {};
}
