// 运动与动力分析（第 12 轮）：结果文件解析、通道名称与单位、CSV
import { session, ApiError } from './api';

async function bin(path) {
  const r = await fetch(path, { headers: { 'x-wq-token': session.token } });
  if (!r.ok) throw new ApiError(r.status, '结果读取失败');
  return r.arrayBuffer();
}

function head(buf, magic) {
  const dv = new DataView(buf);
  const m = String.fromCharCode(...new Uint8Array(buf, 0, 4));
  if (m !== magic) throw new Error('结果文件格式不对');
  const hl = dv.getUint32(4, true);
  return { h: JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 8, hl))), off: 8 + hl };
}

export async function fetchSeries(jobId) {
  const buf = await bin(`/api/mbd/jobs/${encodeURIComponent(jobId)}/series.bin`);
  const { h, off } = head(buf, 'WQC1');
  const all = new Float32Array(buf.slice(off));
  const k = h.names.length, out = {};
  h.names.forEach((n, i) => { const a = new Float32Array(h.n); for (let r = 0; r < h.n; r++) a[r] = all[r * k + i]; out[n] = a; });
  return out;
}

export async function fetchAnim(jobId) {
  const buf = await bin(`/api/mbd/jobs/${encodeURIComponent(jobId)}/anim.bin`);
  const { h, off } = head(buf, 'WQA1');
  const f = h.frames, nb = h.bodies.length;
  const arr = new Float32Array(buf.slice(off));
  return { bodies: h.bodies, frames: f, t: arr.subarray(0, f), pos: arr.subarray(f, f + f * nb * 3), quat: arr.subarray(f + f * nb * 3) };
}

// 固定顺序的类别色（dataviz 参考调色板，浅色界面）
export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300'];

const DEG = 180 / Math.PI;
// 通道 → {组, 标签, 单位, 换算}；jtypes: {关节名: hinge|slide}
export function describe(name, jtypes, labels = {}) {
  const [kind, a, b] = name.split('.');
  const lab = (x) => (labels[x] ? `${labels[x]}（${x}）` : x);
  const hinge = jtypes[a] === 'hinge';
  switch (kind) {
    case 'q': return { group: 'q', label: lab(a), unit: hinge ? '°' : 'mm', k: hinge ? DEG : 1000 };
    case 'qd': return { group: 'qd', label: lab(a), unit: hinge ? '°/s' : 'mm/s', k: hinge ? DEG : 1000 };
    case 'qdd': return { group: 'qdd', label: lab(a), unit: hinge ? '°/s²' : 'm/s²', k: hinge ? DEG : 1 };
    case 'drive': return { group: 'drive', label: lab(a), unit: hinge ? 'N·m' : 'N', k: 1 };
    case 'power': return { group: 'power', label: lab(a), unit: 'W', k: 1 };
    case 'rf': return { group: b === 'abs' ? 'rf' : 'rfxyz', label: lab(a) + (b === 'abs' ? '' : ' ' + b.toUpperCase()), unit: 'N', k: 1 };
    case 'rm': return { group: b === 'abs' ? 'rm' : 'rmxyz', label: lab(a) + (b === 'abs' ? '' : ' ' + b.toUpperCase()), unit: 'N·m', k: 1 };
    case 'pt': return { group: 'pt', label: `${a} ${b.toUpperCase()}`, unit: 'mm', k: 1000 };
    default: return { group: 'other', label: name, unit: '', k: 1 };
  }
}
export const GROUPS = {
  drive: '驱动力矩 / 力', power: '驱动功率', q: '位置（转角 / 位移）', qd: '速度', qdd: '加速度',
  rf: '关节反力（合力）', rm: '关节反力矩（合力矩）', pt: '点的坐标',
};

export function toCSV(series, names) {
  const n = series.t.length;
  const lines = [['t', ...names].join(',')];
  for (let i = 0; i < n; i++) lines.push([series.t[i], ...names.map((c) => series[c][i])].map((v) => +v.toPrecision(7)).join(','));
  return '﻿' + lines.join('\n');
}
