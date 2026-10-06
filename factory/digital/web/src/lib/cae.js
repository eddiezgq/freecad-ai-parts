// 仿真与分析（第 11 轮）：结果文件解析、色标、约束载荷的种类
import { session, ApiError } from './api';

export async function fetchSurface(jobId) {
  const r = await fetch(`/api/cae/jobs/${encodeURIComponent(jobId)}/surface.bin`, { headers: { 'x-wq-token': session.token } });
  if (!r.ok) throw new ApiError(r.status, '结果读取失败');
  const buf = await r.arrayBuffer();
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== 'WQS1') throw new Error('结果文件格式不对');
  const nv = dv.getUint32(4, true), nt = dv.getUint32(8, true);
  let o = 12;
  const take = (T, n) => { const a = new T(buf.slice(o, o + 4 * n)); o += 4 * n; return a; };
  const positions = take(Float32Array, nv * 3);
  const vm = take(Float32Array, nv);
  const u = take(Float32Array, nv * 3);
  const triangles = take(Uint32Array, nt * 3);
  const faceOf = take(Uint32Array, nt);
  const temp = buf.byteLength >= o + 4 * nv ? take(Float32Array, nv) : null;     // 第 14 轮：热分析的节点温度
  const umag = new Float32Array(nv);
  for (let i = 0; i < nv; i++) umag[i] = Math.hypot(u[3 * i], u[3 * i + 1], u[3 * i + 2]);
  return { positions, vm, u, umag, triangles, faceOf, nv, nt, temp };
}

// Turbo 色标（Google，2019）的多项式近似：蓝 → 青 → 绿 → 黄 → 红
export function turbo(t) {
  const x = Math.min(1, Math.max(0, t));
  const r = 0.13572138 + x * (4.6153926 + x * (-42.66032258 + x * (132.13108234 + x * (-152.94239396 + x * 59.28637943))));
  const g = 0.09140261 + x * (2.19418839 + x * (4.84296658 + x * (-14.18503333 + x * (4.27729857 + x * 2.82956604))));
  const b = 0.1066733 + x * (12.64194608 + x * (-60.58204836 + x * (110.36276771 + x * (-89.90310912 + x * 27.34824973))));
  return [Math.min(1, Math.max(0, r)), Math.min(1, Math.max(0, g)), Math.min(1, Math.max(0, b))];
}
export const turboCss = (n = 10) => `linear-gradient(to top, ${Array.from({ length: n + 1 }, (_, i) => {
  const [r, g, b] = turbo(i / n); return `rgb(${(r * 255) | 0},${(g * 255) | 0},${(b * 255) | 0}) ${(i / n * 100).toFixed(0)}%`;
}).join(',')})`;

// 约束与载荷的种类（网页上的名字 → 计算服务的设置）
export const KINDS = {
  fixed: { label: '固定', hint: '这个面完全不能动（焊死、夹紧）', color: '#5B6670', support: true },
  bearing: { label: '轴承支承', hint: '圆柱面：只限制径向（轴可以转）；勾“止推”再限制轴向', color: '#2F6FDE', support: true, cyl: true },
  coupling: { label: '限制转动', hint: '圆柱面：联轴器、键连接的那一端，只限制绕轴转动', color: '#7C4DDB', support: true, cyl: true },
  force: { label: '力', hint: '总力（N），均匀分布在所选面上', color: '#D64541' },
  pressure: { label: '压力', hint: '垂直压在面上（MPa = N/mm²）', color: '#E08A00' },
  torque: { label: '扭矩', hint: '绕轴线的扭矩（N·m），按到轴线的距离分布', color: '#1F8A5B' },
};

export function toLoad(row, axes) {
  const ax = (id) => {
    const a = axes.find((x) => x.key === id) || axes[0];
    return a ? { origin: a.origin, dir: a.dir } : null;
  };
  switch (row.kind) {
    case 'fixed': return { type: 'fixed', faces: row.faces };
    case 'bearing': return { type: 'cyl_support', faces: row.faces, axis: ax(row.axis), dofs: row.thrust ? ['radial', 'axial'] : ['radial'], ...(row.ring ? { band_mm: 1 } : {}) };
    case 'coupling': return { type: 'cyl_support', faces: row.faces, axis: ax(row.axis), dofs: ['tangential'] };
    case 'force': return { type: 'force', faces: row.faces, vector_n: [+row.fx || 0, +row.fy || 0, +row.fz || 0] };
    case 'pressure': return { type: 'pressure', faces: row.faces, value_mpa: +row.value || 0 };
    case 'torque': return { type: 'torque', faces: row.faces, axis: ax(row.axis), value_nmm: (+row.value || 0) * 1000 };
    default: return null;
  }
}

// 零件上的轴线：圆柱面按面积从大到小，同一条轴线只留一个
export function axesOf(faces) {
  const out = [];
  const cyl = faces.filter((f) => f.kind === 'cylinder' && f.axis && f.axis_origin).sort((a, b) => b.area_mm2 - a.area_mm2);
  for (const f of cyl) {
    const d = f.axis, o = f.axis_origin;
    const dot = o[0] * d[0] + o[1] * d[1] + o[2] * d[2];
    const p = [o[0] - dot * d[0], o[1] - dot * d[1], o[2] - dot * d[2]];        // 轴线上离原点最近的点
    const same = out.find((a) => Math.abs(Math.abs(a.dir[0] * d[0] + a.dir[1] * d[1] + a.dir[2] * d[2]) - 1) < 1e-3
      && Math.hypot(a.p[0] - p[0], a.p[1] - p[1], a.p[2] - p[2]) < 0.2);
    if (same) { same.faces.push(f.id); continue; }
    out.push({ key: 'a' + f.id, dir: d, origin: o, p, faces: [f.id],
      label: `${out.length ? '' : '主轴 · '}经过面 ${f.id}（Ø${(f.radius_mm * 2).toFixed(1)}）的轴线` });
  }
  return out;
}

export const KIND_NAME = { plane: '平面', cylinder: '圆柱面', cone: '圆锥面', sphere: '球面', torus: '圆环面', other: '曲面' };
export const faceText = (f) => f ? `面 ${f.id} · ${KIND_NAME[f.kind] || f.kind}${f.radius_mm ? ' Ø' + (f.radius_mm * 2).toFixed(1) : ''} · ${f.area_mm2.toFixed(1)} mm²` : '';

// 热分析（第 14 轮）：热载荷的种类
export const TH_KINDS = {
  temperature: { label: '固定温度', hint: '这个面的温度已知（例如贴着热源、冷却水套）', color: '#C0392B' },
  convection: { label: '对流散热', hint: '表面向周围空气 / 液体散热：散热系数 h 和环境温度', color: '#2E86C1' },
  heat_flux: { label: '面发热', hint: '这个面上总共进来多少瓦热量（例如芯片贴合面、摩擦面）', color: '#E67E22' },
  heat_body: { label: '整体发热', hint: '整个零件体积内均匀发热（例如线圈、整体损耗），不用选面', color: '#8E44AD', nofaces: true },
};

export function toThermal(row) {
  switch (row.kind) {
    case 'temperature': return { type: 'temperature', faces: row.faces, value_c: +row.value || 0 };
    case 'convection': return { type: 'convection', faces: row.rest ? 'rest' : row.faces, h_w_m2k: +row.h || 0, t_inf_c: +row.tinf || 0 };
    case 'heat_flux': return { type: 'heat_flux', faces: row.faces, power_w: +row.value || 0 };
    case 'heat_body': return { type: 'heat_body', power_w: +row.value || 0 };
    default: return null;
  }
}
