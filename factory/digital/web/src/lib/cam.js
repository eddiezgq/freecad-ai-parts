// 数控编程（第 13 轮）：回放用的刀位插值、浏览器里的去除材料（车削半径网格、铣削高度图），与服务器 cam_sim.py 同一规则
import { session } from './api';

// path：[[0 快移 / 1 切削, x, y, z, 行号, 累计时间 s, 刀号], …]
export function segAt(path, t) {
  let lo = 0, hi = path.length - 1;
  if (t <= 0) return 0;
  if (t >= path[hi][5]) return hi;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (path[m][5] < t) lo = m; else hi = m; }
  return hi;
}

export function toolAt(path, t) {
  const i = segAt(path, t);
  if (i === 0) return { i, p: path[0] };
  const a = path[i - 1], b = path[i];
  const dt = b[5] - a[5];
  const f = dt > 1e-9 ? Math.min(1, Math.max(0, (t - a[5]) / dt)) : 1;
  return { i, f, p: [b[0], a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f, b[4], t, b[6]] };
}

// ---------------------------------------------------------------- 车削
function dAt(profile, z) {
  let best = null;
  for (let k = 0; k + 1 < profile.length; k++) {
    const [z0, d0] = profile[k], [z1, d1] = profile[k + 1];
    if (Math.min(z0, z1) - 1e-9 <= z && z <= Math.max(z0, z1) + 1e-9) {
      const d = Math.abs(z1 - z0) < 1e-12 ? Math.max(d0, d1) : d0 + (d1 - d0) * (z - z0) / (z1 - z0);
      best = best === null ? d : Math.max(best, d);
    }
  }
  if (best !== null) return best;
  const lo = profile.reduce((a, b) => (b[0] < a[0] ? b : a)), hi = profile.reduce((a, b) => (b[0] > a[0] ? b : a));
  return z < lo[0] ? lo[1] : hi[1];
}

export class LatheSim {
  // stock：{d, z_right, z_left} 或 {profile, z_right, z_left}
  constructor(stock, h = 0.05) {
    this.z0 = stock.z_left; this.h = h;
    this.n = Math.max(2, Math.round((stock.z_right - stock.z_left) / h));
    this.zc = Float64Array.from({ length: this.n }, (_, i) => this.z0 + (i + 0.5) * h);
    this.init = new Float64Array(this.n);
    const zmax = stock.profile ? Math.max(...stock.profile.map((p) => p[0])) : Infinity;
    for (let i = 0; i < this.n; i++) {
      const z = this.zc[i];
      this.init[i] = stock.profile ? (z <= zmax + 1e-9 ? dAt(stock.profile, z) / 2 : 0) : stock.d / 2;
    }
    this.reset();
  }
  reset() { this.r = Float64Array.from(this.init); this.done = 0; }
  // 刀尖从 a 到 b（x 直径）：外圆车刀去掉刀尖右上方的材料
  cut(a, b) {
    const L = Math.hypot((b[1] - a[1]) / 2, b[3] - a[3]);
    const m = Math.max(1, Math.ceil(L / (this.h / 2)));
    const best = new Float64Array(this.n).fill(Infinity);
    for (let k = 0; k <= m; k++) {
      const f = k / m, z = a[3] + (b[3] - a[3]) * f, r = (a[1] + (b[1] - a[1]) * f) / 2;
      let i = Math.ceil((z - this.z0) / this.h - 0.5);
      if (i >= this.n) continue;
      if (i < 0) i = 0;
      if (r < best[i]) best[i] = r;
    }
    let run = Infinity;
    for (let i = 0; i < this.n; i++) { if (best[i] < run) run = best[i]; if (run < this.r[i]) this.r[i] = run; }
  }
  // 推进到第 idx 段（含）
  advance(path, idx) {
    if (idx < this.done) this.reset();
    for (let i = Math.max(1, this.done + 1); i <= idx; i++) this.cut(path[i - 1], path[i]);
    this.done = Math.max(this.done, idx);
  }
}

// ---------------------------------------------------------------- 铣削
export class MillSim {
  // grid：{x0, y0, h, nx, ny}（服务器仿真的网格），stock：{box, top} 或 {cyl_r, box}；tools：{刀号: {d}}
  constructor(grid, stock, tools) {
    Object.assign(this, grid);
    this.tools = tools;
    this.init = new Float32Array(this.nx * this.ny);
    const [x0, y0, x1, y1] = stock.box;
    for (let i = 0; i < this.nx; i++) {
      const x = this.x0 + i * this.h;
      for (let j = 0; j < this.ny; j++) {
        const y = this.y0 + j * this.h;
        let v = NaN;
        if (x >= x0 && x <= x1 && y >= y0 && y <= y1) {
          if (stock.cyl_r) v = Math.abs(y) < stock.cyl_r ? Math.sqrt(stock.cyl_r ** 2 - y * y) - stock.cyl_r : NaN;
          else v = stock.top ?? 0;
        }
        this.init[i * this.ny + j] = v;
      }
    }
    this.reset();
  }
  reset() { this.H = Float32Array.from(this.init); this.done = 0; }
  stamp(x, y, z, R) {
    const k = Math.ceil(R / this.h) + 1, ix = Math.floor((x - this.x0) / this.h), iy = Math.floor((y - this.y0) / this.h);
    for (let i = Math.max(0, ix - k); i < Math.min(this.nx, ix + k + 1); i++) {
      const dx = this.x0 + i * this.h - x;
      for (let j = Math.max(0, iy - k); j < Math.min(this.ny, iy + k + 1); j++) {
        const dy = this.y0 + j * this.h - y;
        if (dx * dx + dy * dy <= R * R) { const q = i * this.ny + j; if (this.H[q] > z) this.H[q] = z; }
      }
    }
  }
  cut(a, b) {
    const t = this.tools[b[6]] || this.tools[String(b[6])];
    if (!t) return;
    const R = t.d / 2, L = Math.hypot(b[1] - a[1], b[2] - a[2], b[3] - a[3]);
    const m = Math.max(1, Math.ceil(L / (this.h / 2)));
    for (let k = 0; k <= m; k++) {
      const f = k / m;
      this.stamp(a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, a[3] + (b[3] - a[3]) * f, R);
    }
  }
  advance(path, idx) {
    if (idx < this.done) this.reset();
    for (let i = Math.max(1, this.done + 1); i <= idx; i++) this.cut(path[i - 1], path[i]);
    this.done = Math.max(this.done, idx);
  }
}

export async function fetchHeight(jid, k) {
  const r = await fetch(`/api/cam/jobs/${jid}/h${k}.bin`, { headers: { 'x-wq-token': session.token } });
  if (!r.ok) throw new Error('高度图取不到');
  return new Float32Array(await r.arrayBuffer());
}

export async function fetchNc(jid, k) {
  const r = await fetch(`/api/cam/jobs/${jid}/${k}.nc`, { headers: { 'x-wq-token': session.token } });
  if (!r.ok) throw new Error('程序取不到');
  return r.text();
}

export const fmtMin = (s) => (s >= 60 ? `${Math.floor(s / 60)} 分 ${Math.round(s % 60)} 秒` : `${s.toFixed(1)} 秒`);
