// 第 92 轮（电子 E5）：编码器接口芯片 WQ-ENCIF 的行为模型（逐拍），与 factory/designs/wq-encif/model/encif.py 同一套规则
// （测试 tests/test_chip_design.py 用同一组激励逐拍核对）。示例设计，未流片。
// 激励字：位 0 A、1 B、2 Z、3 SCLK、4 CS_N、5 MOSI、6 RST_N
export const ID = 0x454e4331;
export const BIT = { A: 1, B: 2, Z: 4, SCK: 8, CS: 16, MO: 32, RST: 64 };
const M32 = 0x100000000;
const u32 = (x) => ((x % M32) + M32) % M32;

export class Encif {
  constructor() { this.reset(); }

  reset() {
    this.sync = { a: [0, 0], b: [0, 0], z: [0, 0], k: [0, 0], c: [1, 1], m: [0, 0] };
    this.f = { a: 0, b: 0, z: 0 };
    this.fc = { a: 0, b: 0, z: 0 };
    this.p = { a: 0, b: 0, z: 0 };
    this.en = 1; this.inv = 0; this.zclr = 0; this.flen = 3;
    this.dir = 1; this.err = 0; this.ivld = 0;
    this.cnt = 0; this.idx = 0;
    this.bits = 0; this.cmd = 0; this.sh = 0;
    this.boot = 0; this.armed = 0;
  }

  reg(a) {
    if (a === 0) return ID;
    if (a === 1) return this.en | (this.inv << 1) | (this.zclr << 2) | (this.flen << 4);
    if (a === 2) return this.dir | (this.err << 1) | (this.ivld << 2) | (this.f.a << 3) | (this.f.b << 4) | (this.f.z << 5);
    if (a === 3) return this.cnt;
    if (a === 4) return this.idx;
    return 0;
  }

  miso() {
    const sel = !this.sync.c[1];
    return sel && this.bits >= 8 && !(this.cmd >> 7) && Math.floor(this.sh / 0x80000000) & 1 ? 1 : 0;
  }

  // 一个时钟上升沿
  step(w) {
    if (!(w & BIT.RST)) { this.reset(); return this.miso(); }
    const old = {};
    for (const k in this.sync) old[k] = this.sync[k].slice();
    const sckR = !old.k[1] && old.k[0];
    const sckF = old.k[1] && !old.k[0];
    const sel = !old.c[1];
    const mo = old.m[1];
    const f0 = { ...this.f };
    const p0 = { ...this.p };
    const cnt0 = this.cnt;
    const flen0 = this.flen;
    for (const k of ['a', 'b', 'z']) {
      if (old[k][1] !== f0[k]) {
        if (this.fc[k] >= flen0) { this.f[k] = old[k][1]; this.fc[k] = 0; } else this.fc[k] += 1;
      } else this.fc[k] = 0;
    }
    const armed0 = this.armed;
    const da = armed0 && (f0.a ^ p0.a); const db = armed0 && (f0.b ^ p0.b);
    const stp = (da ? 1 : 0) ^ (db ? 1 : 0);
    const same = f0.a ^ f0.b;
    const fwd = ((stp && ((da && same) || (db && !same))) ? 1 : 0) ^ this.inv;
    const zrise = armed0 && f0.z && !p0.z;
    const cmd0 = this.cmd; const bits0 = this.bits; const sh0 = this.sh;
    const wrDone = sel && sckR && bits0 === 39 && (cmd0 >> 7);
    const wdata = u32(sh0 * 2 + mo);
    if (!sel) { this.bits = 0; this.cmd = 0; this.sh = 0; } else {
      if (sckR && bits0 < 40) {
        this.bits = bits0 + 1;
        if (bits0 < 8) {
          const cn = ((cmd0 << 1) | mo) & 0xff;
          this.cmd = cn;
          if (bits0 === 7) this.sh = cn >> 7 ? 0 : this.reg(cn & 0x7f);
        } else if (cmd0 >> 7) this.sh = wdata;
      }
      if (sckF && !(cmd0 >> 7) && bits0 > 8 && bits0 < 40) this.sh = u32(sh0 * 2);
    }
    const en0 = this.en;
    this.p = f0;
    if (this.boot !== 3) this.boot += 1;
    else if (!armed0 && ['a', 'b', 'z'].every((k) => f0[k] === old[k][1])) this.armed = 1;
    if (en0 && stp) { this.cnt = u32(cnt0 + (fwd ? 1 : -1)); this.dir = fwd ? 1 : 0; }
    if (en0 && da && db) this.err = 1;
    if (zrise) { this.idx = cnt0; this.ivld = 1; if (this.zclr && en0) this.cnt = 0; }
    if (wrDone) {
      const a = cmd0 & 0x7f;
      if (a === 1) { this.en = wdata & 1; this.inv = (wdata >> 1) & 1; this.zclr = (wdata >> 2) & 1; this.flen = (wdata >> 4) & 0xf; }
      else if (a === 2) { if ((wdata >> 1) & 1) this.err = 0; if ((wdata >> 2) & 1) this.ivld = 0; }
      else if (a === 3) this.cnt = wdata;
    }
    const ins = { a: w & BIT.A, b: w & BIT.B, z: w & BIT.Z, k: w & BIT.SCK, c: w & BIT.CS, m: w & BIT.MO };
    for (const k in ins) this.sync[k] = [ins[k] ? 1 : 0, old[k][0]];
    return this.miso();
  }
}

export const signed = (x) => (x >= 0x80000000 ? x - M32 : x);

// 逐拍跑一串激励，返回每拍 [cnt, idx, status, miso]
export function run(words) {
  const m = new Encif();
  return words.map((w) => { const mi = m.step(w); return [m.cnt, m.idx, m.reg(2), mi]; });
}

// 网页的“接上编码器”：电机按转速转，A/B 上随机打毛刺，芯片按滤波长度 N 解码；结束前用 SPI 读一次 COUNT。
// 时钟 50 MHz（20 ns 一拍）；SCLK = 5 MHz（半周期 5 拍）。返回逐拍的信号（给逻辑分析仪画）和 SPI 读回的值。
export function bench({ rpm = 3000, dir = 1, lines = 1000, flen = 3, glitchPerUs = 0.02, glitchMax = 3, cycles = 12000, seed = 7, zclr = 0 } = {}) {
  let s = seed >>> 0;
  const rnd = () => { s = (s + 0x6d2b79f5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const dt = 20e-9;
  const edgesPerS = (4 * lines * rpm) / 60;
  const words = []; const marks = [];
  const add = (a, b, z, sck, cs, mo, rst = 1) => words.push((a ? 1 : 0) | (b ? 2 : 0) | (z ? 4 : 0) | (sck ? 8 : 0) | (cs ? 16 : 0) | (mo ? 32 : 0) | (rst ? 64 : 0));
  const gl = { a: 0, b: 0 };
  const phase0 = 0.5;
  const enc = (i) => {
    const ph = phase0 + dir * edgesPerS * i * dt;                // 以“边沿”为单位的相位
    const q = ((Math.floor(ph) % 4) + 4) % 4;
    const ab = [[0, 0], [1, 0], [1, 1], [0, 1]][q];
    const z = ((Math.floor(ph) % (4 * lines)) + 4 * lines) % (4 * lines) === 0 ? 1 : 0;
    return [ab[0], ab[1], z];
  };
  const cur = () => enc(words.length);
  const spi = (cmd, data) => {
    const bitsOut = [];
    for (let i = 0; i < 8; i++) bitsOut.push((cmd >> (7 - i)) & 1);
    for (let i = 0; i < 32; i++) bitsOut.push(Math.floor(data / 2 ** (31 - i)) & 1);
    for (let k = 0; k < 5; k++) { const e = cur(); add(e[0], e[1], e[2], 0, 0, 0); }
    const start = words.length;
    for (const b of bitsOut) {
      for (let k = 0; k < 5; k++) { const e = cur(); add(e[0], e[1], e[2], 0, 0, b); }
      for (let k = 0; k < 5; k++) { const e = cur(); add(e[0], e[1], e[2], 1, 0, b); }
    }
    for (let k = 0; k < 5; k++) { const e = cur(); add(e[0], e[1], e[2], 0, 0, 0); }
    for (let k = 0; k < 10; k++) { const e = cur(); add(e[0], e[1], e[2], 0, 1, 0); }
    return start;
  };
  // 复位 → 写 CTRL（滤波长度 N）→ 转动（编码器一直在转）→ 结束前读 COUNT
  for (let i = 0; i < 4; i++) { const e = cur(); add(e[0], e[1], e[2], 0, 1, 0, 0); }
  for (let i = 0; i < 4; i++) { const e = cur(); add(e[0], e[1], e[2], 0, 1, 0); }
  const ctrl = 0x01 | (zclr ? 4 : 0) | ((flen & 15) << 4);
  marks.push({ at: words.length, label: '写 CTRL：滤波 N=' + flen });   // i18n-ok 页面不显示这个说明（纯模型文件，Node 测试也用）
  spi(0x81, ctrl);
  const until = cycles - 600;
  while (words.length < until) {
    const i = words.length;
    const [a, b, z] = enc(i);
    if (!gl.a && !gl.b && rnd() < glitchPerUs * dt * 1e6) {
      const w = 1 + Math.floor(rnd() * glitchMax);
      if (rnd() < 0.5) gl.a = w; else gl.b = w;
      marks.push({ at: i, label: '毛刺 ' + w * 20 + ' ns', glitch: true, width: w });   // i18n-ok 页面不显示这个说明（纯模型文件，Node 测试也用）
    }
    add(gl.a ? 1 - a : a, gl.b ? 1 - b : b, z, 0, 1, 0);
    if (gl.a) gl.a--; if (gl.b) gl.b--;
  }
  const readAt = spi(0x03, 0);
  marks.push({ at: readAt, label: 'SPI 读 COUNT' });   // i18n-ok 页面不显示这个说明（纯模型文件，Node 测试也用）
  while (words.length < cycles) { const e = enc(words.length); add(e[0], e[1], e[2], 0, 1, 0); }
  // 逐拍跑模型，记下信号
  const m = new Encif();
  const tr = { A: [], B: [], Z: [], fA: [], fB: [], cnt: [], SCLK: [], CS_N: [], MOSI: [], MISO: [] };
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    const mi = m.step(w);
    tr.A.push(w & 1); tr.B.push((w >> 1) & 1); tr.Z.push((w >> 2) & 1); tr.SCLK.push((w >> 3) & 1); tr.CS_N.push((w >> 4) & 1); tr.MOSI.push((w >> 5) & 1);
    tr.fA.push(m.f.a); tr.fB.push(m.f.b); tr.cnt.push(signed(m.cnt)); tr.MISO.push(mi);
  }
  let steps = 0;
  for (let i = 1; i < tr.cnt.length; i++) steps += Math.abs(tr.cnt[i] - tr.cnt[i - 1]);   // 计数变动的次数（毛刺会造成一来一回）
  let v = 0;
  for (let i = 0; i < 32; i++) v = v * 2 + tr.MISO[readAt + (8 + i) * 10 + 5 - 1];   // 主机在第 9+i 个上升沿采样
  const glitches = marks.filter((x) => x.glitch);
  return { tr, marks, readValue: signed(v), finalCount: signed(m.cnt), steps, err: m.err, glitches: glitches.length,
    passed: glitches.filter((g) => g.width >= flen + 1).length, edgesPerS, cycles: words.length, readAt };
}
