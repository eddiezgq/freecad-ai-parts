// 测试用（tests/test_instruments.py）：stdin 读 {seeds: [...], tasks: [...]}，用网页同一个模块（src/lib/instruments.js）
// 给出每个种子的学生参数，并像学生一样“做实验”得到结果（带仪器噪声），stdout 写 JSON
import * as I from '../src/lib/instruments.js';
let buf = '';
for await (const c of process.stdin) buf += c;
const req = JSON.parse(buf);
const P = I.PARAMS;
const out = {};
for (const seed of req.seeds) {
  const o = { variant: {}, result: {} };
  for (const t of I.TASKS) o.variant[t] = I.variant(t, seed);
  const g = I.gaussFrom(I.mulberry32(seed ^ 0x1234567));
  const want = req.tasks || I.TASKS;
  if (want.includes('torque')) {
    const v = o.variant.torque;
    const ups = [0, 10, 20, 30, 40, 50];
    const rd = (T, down) => { let s = 0; for (let i = 0; i < 10; i++) s += I.dmmRead(I.torqueOut(v, T, down) / 1000, g).value; return 1000 * s / 10; };
    const yu = ups.map((T) => rd(T, false)); const yd = ups.map((T) => (T === 50 ? yu[5] : rd(T, true)));
    const f = I.linfit(ups, yu); const fso = f.k * P.torque.fs_nm;
    o.result.torque = { s_mv_v: f.k * P.torque.fs_nm / (P.torque.gain * P.torque.vex), zero_mv: f.b,
      nl_pct: Math.max(...ups.map((T, i) => Math.abs(yu[i] - (f.k * T + f.b)))) / fso * 100,
      hys_pct: Math.max(...ups.map((T, i) => Math.abs(yd[i] - yu[i]))) / fso * 100 };
  }
  if (want.includes('encoder')) {
    const v = o.variant.encoder; const s = I.encoderSignals(v);
    const tdiv = 2 / s.fA / 10 * 5;                           // 一屏 10 个 A 周期
    const ch = I.scopeAcquire([{ name: 'A', fn: s.A }], { tdiv, vdiv: [1], trigLevel: 2.5 }, g)[0];
    const fA = I.scopeMeasure(ch).freq;
    const dq = I.decodeQuadrature(s, 0, s.period * 2.2, Math.max(2e6, s.fA * 40));
    const zs = dq.zs;
    o.result.encoder = { dir: dq.count > 0 ? 'cw' : 'ccw', rpm: fA * 60 / P.encoder.lines,
      cpr: zs.length >= 2 ? Math.abs(zs[1].count - zs[0].count) : null, z_ms: zs.length >= 2 ? (zs[1].t - zs[0].t) * 1000 : null };
  }
  if (want.includes('imu')) {
    const v = o.variant.imu; const s = I.imuSeries(v, seed);
    const ad = I.allan(s.data, s.fs, 0.1);
    const at1 = ad.find((x) => Math.abs(x.tau - 1.28) < 1e-9) || ad[7];
    // τ = 1 s 处：在 log-log 上按 −1/2 斜率把最近的点换算到 1 s
    // ARW：在 −1/2 斜率段（短 τ，白噪声为主）读 σ(τ)·√τ，换成 °/√h
    const seg = ad.filter((x) => x.tau >= 0.04 && x.tau <= 0.33).map((x) => x.adev * Math.sqrt(x.tau) * 60).sort((p, q) => p - q);
    const arw = seg[Math.floor(seg.length / 2)];
    const mn = Math.min(...ad.map((x) => x.adev));
    let sum = 0; for (const x of s.data) sum += x;
    o.result.imu = { bias: sum / s.data.length, arw, bi: mn / 0.664 * 3600, curve: ad, at1: at1 && at1.adev };
  }
  if (want.includes('hall')) {
    const v = o.variant.hall;
    const Is = [-15, -10, -5, 0, 5, 10, 15];
    const vs = Is.map((I0) => { let s = 0; for (let i = 0; i < 10; i++) s += I.dmmRead(I.hallDc(v, I0) + P.hall.noise_mv / 1000 * g(), g).value; return s / 10; });
    const f = I.linfit(Is, vs);
    const amp = (fr) => {
      const a = I.hallAc(v, fr, 1);
      const fn = (t) => v.vz + a.amp * Math.sin(2 * Math.PI * fr * t + a.phase);
      const ch = I.scopeAcquire([{ name: 'out', fn }], { tdiv: 2 / fr / 10 * 5 / 2, vdiv: [0.01], off: [v.vz], trigLevel: v.vz }, g)[0];
      return I.scopeMeasure(ch).acrms * Math.SQRT2;          // 用交流有效值 × √2 当幅值（峰峰值会被噪声撑大）
    };
    const a0 = amp(1000);
    let lo = 1e3; let hi = 1e6;
    for (let k = 0; k < 30; k++) { const m = Math.sqrt(lo * hi); if (amp(m) > a0 / Math.SQRT2) lo = m; else hi = m; }
    o.result.hall = { s_mv_a: f.k * 1000, vz: f.b, fb: Math.sqrt(lo * hi) };
  }
  if (want.includes('ntc')) {
    const v = o.variant.ntc; const n = P.ntc;
    const xs = []; const ys = [];
    for (const tc of n.temps_c) {
      const tb = tc + n.bath_sd_k * g();
      let s = 0; for (let i = 0; i < 5; i++) s += I.dmmRead(I.ntcVolt(v, tb).V, g).value; const V = s / 5;
      const R = n.rfix * V / (n.vs - V);
      xs.push(1 / (tc + 273.15) - 1 / 298.15); ys.push(Math.log(R));
    }
    const f = I.linfit(xs, ys);
    o.result.ntc = { b: f.k, r25: Math.exp(f.b) };
  }
  if (want.includes('tof')) {
    const v = o.variant.tof; const N = 400;
    const sd = (d) => { const a = []; for (let i = 0; i < N; i++) a.push(d * 1000 + I.tofSigma(v, d) * g()); return I.stats(a).sd; };
    const means = []; for (let k = 0; k < 200; k++) { const a = []; for (let i = 0; i < P.tof.n_avg; i++) a.push(5000 + I.tofSigma(v, 5) * g()); means.push(I.stats(a).mean); }
    o.result.tof = { sd1: sd(1), sd5: sd(5), sd5avg: I.stats(means).sd };
  }
  out[seed] = o;
}
process.stdout.write(JSON.stringify(out));
