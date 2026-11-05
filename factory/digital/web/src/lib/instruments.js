// 第 82 轮（电子 E2）：虚拟仪器的模型——传感器（物理模型）+ 仪器（带宽、量化、噪声、精度等级）。
// 参数只有一份：sensors.json（服务器 cae/instruments.py 读同一份）。随机数用 mulberry32，固定种子：同一个学生每次数据相同，不同学生不同。
// 学生的参数 variant(task, seed) 与服务器的 Python 实现逐位一致（测试核对）。
import P from './sensors.json' with { type: 'json' };

export const PARAMS = P;

// ---------------------------------------------------------------- 随机数
export function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export function gaussFrom(r) {
  let spare = null;
  return function () {
    if (spare !== null) { const s = spare; spare = null; return s; }
    let u = 0; let v = 0;
    while (u <= 1e-12) u = r();
    v = r();
    const m = Math.sqrt(-2 * Math.log(u));
    spare = m * Math.sin(2 * Math.PI * v);
    return m * Math.cos(2 * Math.PI * v);
  };
}
export const TASKS = ['torque', 'encoder', 'imu', 'hall', 'ntc', 'tof'];
export function taskSeed(seed, task) {
  const no = TASKS.indexOf(task) + 1;
  return (seed ^ Math.imul(no, 0x9E3779B1)) >>> 0;
}

// ---------------------------------------------------------------- 每个学生的参数（名义值附近散布）
export function variant(task, seed) {
  const r = mulberry32(taskSeed(seed, task));
  const c = () => 2 * r() - 1;               // [-1, 1)
  const u = () => r();
  if (task === 'torque') {
    const t = P.torque;
    return { s_mv_v: t.s_mv_v * (1 + t.var.s_mv_v * c()), nl_fs: t.nl_fs * (1 + t.var.nl_fs * c()), hys_fs: t.hys_fs * (1 + t.var.hys_fs * c()),
      zero_mv: t.zero_mv + t.var.zero_mv * c() };
  }
  if (task === 'encoder') {
    const e = P.encoder;
    return { rpm: Math.round(e.rpm_min + (e.rpm_max - e.rpm_min) * u()), dir: u() < 0.5 ? 1 : -1 };
  }
  if (task === 'imu') {
    const m = P.imu;
    return { arw: m.arw_min + (m.arw_max - m.arw_min) * u(), bi: m.bi_min + (m.bi_max - m.bi_min) * u(), bias: m.bias_min + (m.bias_max - m.bias_min) * u() };
  }
  if (task === 'hall') {
    const h = P.hall;
    return { s_mv_a: h.s_mv_a * (1 + h.var.s_mv_a * c()), vz: h.vz + h.var.vz_mv / 1000 * c(), fb: h.fb_min + (h.fb_max - h.fb_min) * u() };
  }
  if (task === 'ntc') {
    const n = P.ntc;
    return { b: n.b * (1 + n.var.b * c()), r25: n.r25 * (1 + n.var.r25 * c()) };
  }
  if (task === 'tof') {
    const f = P.tof;
    return { sigma0_mm: f.sigma0_mm * (1 + f.var * c()), k_mm_m2: f.k_mm_m2 * (1 + f.var * c()) };
  }
  throw new Error('没有这个任务 ' + task);
}

// ---------------------------------------------------------------- 传感器
// ① 力矩传感器：桥路比 y = x + 4·nl·x(1−x)（卸载再加 4·hys·x(1−x)），放大器输出 mV = G·S·Vex·y + 零点
export function torqueOut(v, T, down = false, vex = P.torque.vex) {
  const t = P.torque;
  const x = T / t.fs_nm;
  const y = x + 4 * v.nl_fs * x * (1 - x) + (down ? 4 * v.hys_fs * x * (1 - x) : 0);
  return t.gain * v.s_mv_v * vex * y + v.zero_mv;      // mV
}

// ② 编码器：A、B 正交方波（A 超前 B 为正转），每转一个 Z（宽一个刻线的 1/4）
export function encoderSignals(v) {
  const e = P.encoder;
  const w = v.dir * 2 * Math.PI * v.rpm / 60;           // 机械角速度 rad/s
  const sq = (th) => (Math.sin(th) >= 0 ? e.vh : 0);
  const frac = (x) => x - Math.floor(x);
  return {
    A: (t) => sq(w * e.lines * t),
    B: (t) => sq(w * e.lines * t - Math.PI / 2),
    Z: (t) => (frac(w * t / (2 * Math.PI)) < 1 / (4 * e.lines) ? e.vh : 0),
    fA: e.lines * v.rpm / 60, period: 60 / v.rpm,
  };
}

// ③ IMU 陀螺：白噪声（ARW）+ 零偏不稳定性（几个一阶马尔可夫过程叠加近似 1/f）+ 常值零偏
export const BI_TAUS = [3, 10, 30, 100, 300];
export const BI_GAIN = 0.78;                                // 标定常数：使 Allan 曲线最低点 ≈ 0.664·BI（测试核对）
export function imuSeries(v, seed, hours = P.imu.hours) {
  const fs = P.imu.fs_hz;
  const n = Math.round(hours * 3600 * fs);
  const g = gaussFrom(mulberry32(taskSeed(seed, 'imu') ^ 0x5bd1e995));
  const out = new Float64Array(n);
  const sw = (v.arw / 60) * Math.sqrt(fs);                 // °/s，每个样本
  const bi = v.bi / 3600 * BI_GAIN;                         // °/s
  const st = BI_TAUS.map(() => 0);
  const a = BI_TAUS.map((tau) => Math.exp(-1 / (fs * tau)));
  const q = a.map((ai) => bi * Math.sqrt(1 - ai * ai));
  for (let i = 0; i < n; i++) {
    let b = 0;
    for (let k = 0; k < st.length; k++) { st[k] = a[k] * st[k] + q[k] * g(); b += st[k]; }
    out[i] = v.bias + b + sw * g();
  }
  return { fs, data: out };
}
// 重叠 Allan 偏差：τ = m/fs，m = 1, 2, 4, …（用累积和，O(N)）
export function allan(data, fs, maxFrac = 0.1) {
  const n = data.length;
  const th = new Float64Array(n + 1);
  for (let i = 0; i < n; i++) th[i + 1] = th[i] + data[i] / fs;
  const out = [];
  for (let m = 1; m <= n * maxFrac; m *= 2) {
    const tau = m / fs;
    let s = 0; let k = 0;
    for (let i = 0; i + 2 * m <= n; i++) { const d = th[i + 2 * m] - 2 * th[i + m] + th[i]; s += d * d; k++; }
    out.push({ tau, adev: Math.sqrt(s / (2 * tau * tau * k)) });
  }
  return out;
}

// ④ 霍尔电流传感器：直流 Vo = Vz + S·I；交流幅值 S·I/√(1 + (f/fb)²)，相位 −atan(f/fb)
export function hallDc(v, I) { return v.vz + v.s_mv_a / 1000 * I; }
export function hallAc(v, f, amp) {
  const k = 1 / Math.sqrt(1 + (f / v.fb) ** 2);
  return { amp: v.s_mv_a / 1000 * amp * k, phase: -Math.atan(f / v.fb) };
}

// ⑤ NTC：R(T) = R25·exp(B(1/T − 1/298.15))，分压 V = Vs·R/(R + Rfix)，自热 ΔT = P/δ（迭代）
export function ntcVolt(v, tc, vs = P.ntc.vs) {
  const n = P.ntc;
  let T = tc + 273.15; let V = 0; let R = 0;
  for (let i = 0; i < 8; i++) {
    R = v.r25 * Math.exp(v.b * (1 / T - 1 / 298.15));
    V = vs * R / (R + n.rfix);
    T = tc + 273.15 + (V * V / R) / (n.delta_mw_k / 1000);
  }
  return { V, R, T_self: T - 273.15 - tc };
}

// ⑥ 激光测距：σ(d) = σ0 + k·d²
export function tofSigma(v, d) { return v.sigma0_mm + v.k_mm_m2 * d * d; }

// ---------------------------------------------------------------- 仪器
// 万用表（直流电压）：自动量程、分辨率 = 量程 / 计数、读数抖动、精度等级 ±(读数% + 字)
export function dmmRange(V) { return P.dmm.ranges_v.find((r) => Math.abs(V) < r) || P.dmm.ranges_v[P.dmm.ranges_v.length - 1]; }
export function dmmRead(V, gauss, range = null) {
  const d = P.dmm;
  const rg = range || dmmRange(V);
  const res = rg / d.counts;
  const over = Math.abs(V) >= rg;
  const raw = V + d.noise_dig * res * gauss();
  const shown = Math.round(raw / res) * res;
  const acc = Math.abs(shown) * d.dcv_pct / 100 + d.dcv_dig * res;
  return { value: over ? null : shown, range: rg, res, acc, u_b: acc / Math.sqrt(3), over };
}

// 示波器：一屏 points 点；一阶带宽；本底噪声；8 位量化（±4 格以外削顶）；触发在左起 1 格处（上升沿过电平）
export function scopeAcquire(chs, set, gauss) {
  const S = P.scope;
  const n = S.points;
  const span = set.tdiv * S.divs_x;
  const dt = span / n;
  const trig = chs[set.trigCh || 0];
  let t0 = 0;
  if (trig && set.trigLevel != null) {                       // 在前一屏里找上升沿
    const m = 4000; const st = span / m * 2;
    let prev = trig.fn(-span * 2);
    for (let i = 1; i <= m; i++) {
      const t = -span * 2 + i * st;
      const y = trig.fn(t);
      if (prev < set.trigLevel && y >= set.trigLevel) { t0 = t; }
      prev = y;
    }
  }
  const tStart = t0 - set.tdiv;
  const alpha = 1 - Math.exp(-2 * Math.PI * S.bw_hz * dt);
  return chs.map((c, k) => {
    const vdiv = set.vdiv[k]; const off = set.off?.[k] || 0;
    const q = S.divs_y * vdiv / 2 ** S.bits;
    let y = c.fn(tStart - dt * 20);
    for (let i = 0; i < 20; i++) y += (c.fn(tStart - dt * (19 - i)) - y) * alpha;
    const out = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      y += (c.fn(tStart + i * dt) - y) * alpha;
      let v = y + S.noise_div * vdiv * gauss();
      const lim = S.divs_y / 2 * vdiv;
      v = Math.max(-lim + off, Math.min(lim + off, v));
      out[i] = Math.round((v - off) / q) * q + off;
    }
    return { name: c.name, color: c.color, t0: tStart, dt, v: out };
  });
}
export function scopeMeasure(ch) {
  const v = ch.v; const n = v.length;
  let mn = Infinity; let mx = -Infinity; let s = 0; let s2 = 0;
  for (const x of v) { mn = Math.min(mn, x); mx = Math.max(mx, x); s += x; s2 += x * x; }
  const mean = s / n;
  const mid = (mx + mn) / 2;
  const ups = [];
  for (let i = 1; i < n; i++) if (v[i - 1] < mid && v[i] >= mid) ups.push(i);
  const freq = ups.length >= 2 ? (ups.length - 1) / ((ups[ups.length - 1] - ups[0]) * ch.dt) : null;
  let acs = 0;
  for (const x of v) acs += (x - mean) ** 2;
  return { vpp: mx - mn, vmax: mx, vmin: mn, mean, rms: Math.sqrt(s2 / n), acrms: Math.sqrt(acs / n), freq };
}

// 逻辑分析仪：按阈值采样 A/B/Z，四倍频解码（计数、方向、Z 出现的位置）
export function decodeQuadrature(sig, t0, span, fs = 2e6) {
  const n = Math.round(span * fs);
  const th = P.encoder.vh / 2;
  let a0 = sig.A(t0) > th; let b0 = sig.B(t0) > th; let z0 = sig.Z(t0) > th;
  let count = 0; let up = 0; let down = 0;
  const zs = []; const trace = [];
  const step = Math.max(1, Math.floor(n / 1500));
  for (let i = 1; i <= n; i++) {
    const t = t0 + i / fs;
    const a = sig.A(t) > th; const b = sig.B(t) > th; const z = sig.Z(t) > th;
    if (a !== a0 || b !== b0) {
      const dirStep = (a ? 1 : 0) ^ (b0 ? 1 : 0) ? 1 : -1;   // 此刻 A 异或前一时刻 B：A 超前 B（正转）→ +1
      count += dirStep;
      if (dirStep > 0) up++; else down++;
    }
    if (z && !z0) zs.push({ t, count });
    if (i % step === 0) trace.push([t, a ? 1 : 0, b ? 1 : 0, z ? 1 : 0]);
    a0 = a; b0 = b; z0 = z;
  }
  return { count, up, down, zs, trace, fs };
}

// 最小二乘直线
export function linfit(xs, ys) {
  const n = xs.length;
  const mx = xs.reduce((a, b) => a + b, 0) / n; const my = ys.reduce((a, b) => a + b, 0) / n;
  let sxy = 0; let sxx = 0;
  for (let i = 0; i < n; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) ** 2; }
  const k = sxy / sxx;
  return { k, b: my - k * mx };
}
export function stats(arr) {
  const n = arr.length;
  const m = arr.reduce((a, b) => a + b, 0) / n;
  const sd = Math.sqrt(arr.reduce((a, b) => a + (b - m) ** 2, 0) / Math.max(1, n - 1));
  let mn = Infinity; let mx = -Infinity;
  for (const x of arr) { if (x < mn) mn = x; if (x > mx) mx = x; }       // 不用 Math.min(...arr)：几十万个点会爆栈
  return { n, mean: m, sd, min: mn, max: mx };
}
