// 厂情中枢 · 工厂本体（第 17 轮 A 期）：接口、领域配色、对象摘要缓存
import { reactive } from 'vue';
import { get, post } from './api';

// 15 个领域 + 中枢自身的颜色（关系图节点、全貌地图色条）
export const DOMAIN_COLOR = {
  strategy: '#5B4B8A', customer: '#B5487A', sales: '#C7652E', product: '#2F6FB3', supply: '#7A6A2E',
  planning: '#3E7C8C', production: '#0E5E6F', quality: '#1F7A4D', warehouse: '#8C6D3E', service: '#A23B3B',
  maintenance: '#5E6B78', ehs: '#C98A12', people: '#6F5D99', energy: '#4E8C4A', finance: '#36506B', core: '#17212B',
};
export const MATURITY_STYLE = {
  have: { label: '已有数据', cls: 'm-have' },
  erp: { label: 'ERPNext 可启用', cls: 'm-erp' },
  capture: { label: '待采集', cls: 'm-capture' },
  sim: { label: '教学模拟', cls: 'm-sim' },
  next: { label: '后续各期生成', cls: 'm-next' },
};

export const ont = reactive({ types: null, byName: {}, domains: {}, level: 1 });

export async function loadTypes(force = false) {
  if (ont.types && !force) return ont.types;
  const r = await get('/ont/types');
  ont.types = r.domains;
  ont.level = r.level;
  ont.byName = {};
  ont.domains = {};
  for (const d of r.domains) {
    ont.domains[d.domain] = d;
    for (const t of d.types) ont.byName[t.name] = { ...t, domain: d.domain, domain_label: d.label };
  }
  return ont.types;
}

export const enc = (k) => String(k).split('/').map(encodeURIComponent).join('/');
export const objPath = (type, key) => `/ont/${type}/${enc(key)}`;
export const search = (q, type = '') => get(`/ont/search?q=${encodeURIComponent(q)}${type ? '&type=' + type : ''}`);
export const getObj = (type, key) => get(`/ont/obj/${type}/${enc(key)}`);
export const getGraph = (type, key, depth = 1) => get(`/ont/obj/${type}/${enc(key)}/graph?depth=${depth}`);
export const getTimeline = (type, key) => get(`/ont/obj/${type}/${enc(key)}/timeline`);
export const query = (body) => post('/ont/query', body);
export const lineage = (seq) => get(`/ont/lineage/${seq}`);

// 对象卡片的摘要：同一页多处引用同一个对象只请求一次，1 分钟内复用
const cache = new Map();
export function summary(type, key) {
  const k = type + '|' + key;
  const c = cache.get(k);
  if (c && Date.now() - c.t < 60000) return c.p;
  const p = getObj(type, key).catch((e) => ({ error: e.message || String(e) }));
  cache.set(k, { t: Date.now(), p });
  return p;
}

export function fmtVal(v, unit) {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? '是' : '否';
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === 'object' ? JSON.stringify(x) : x)).join('；') : '—';
  if (typeof v === 'object') return JSON.stringify(v);
  if (typeof v === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(v)) return fmtTs(v);
  if (typeof v === 'number') return (Number.isInteger(v) ? v : +v.toFixed(4)) + (unit ? ' ' + unit : '');
  return String(v) + (unit ? ' ' + unit : '');
}

export function fmtTs(s) {
  if (!s) return '';
  const d = new Date(s);
  if (isNaN(d)) return s;
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

// 状态类属性 → 状态色
export function stateTone(props) {
  const v = String(props?.status ?? props?.state ?? props?.result ?? props?.health ?? '').toLowerCase();
  if (!v) return '';
  if (/fail|fault|down|bad|overdue|open|危险|故障|不合格|逾期|alarm|停/.test(v)) return 'bad';
  if (/warn|setup|idle|draft|pending|注意|调整|待/.test(v)) return 'warn';
  if (/pass|run|ok|good|complete|closed|done|正常|合格|完成|已/.test(v)) return 'good';
  return 'info';
}

export function toCsv(rows) {
  const esc = (x) => { const s = x === null || x === undefined ? '' : typeof x === 'object' ? JSON.stringify(x) : String(x); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  return '\ufeff' + rows.map((r) => r.map(esc).join(',')).join('\n');
}

export function download(name, text, type = 'text/csv;charset=utf-8') {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
