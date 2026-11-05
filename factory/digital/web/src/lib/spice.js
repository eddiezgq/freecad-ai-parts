// 第 79 轮（电子 E1）：浏览器里的 ngspice（WebAssembly 版 eecircuit-engine，固定 1.8.0，随网页打包、从我们自己的服务器加载）。
// run(netlist) → { meas, plot, errors }：meas 从 ngspice 打印的 .meas 结果读（与服务器 cae/circuit.py 的 parse_meas 同一规则），
// plot 与服务器的格式相同：{ names, complex, data: {名: [..]} }（复数为 [实部, 虚部]）。
let sim = null;
let starting = null;

async function engine() {
  if (sim) return sim;
  if (!starting) {
    starting = (async () => {
      const { Simulation } = await import('eecircuit-engine');
      const s = new Simulation();
      await s.start();
      sim = s;
      return s;
    })();
  }
  return starting;
}

const NUM = /^\s*([a-z_][a-z0-9_]*)\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)/i;
const AT = /\bat\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)/i;
const MEAS = /^\s*\.meas(?:ure)?\s+\w+\s+(\w+)/i;

export function measNames(netlist) {
  const out = new Set();
  for (const ln of netlist.split('\n')) { const m = ln.match(MEAS); if (m) out.add(m[1].toLowerCase()); }
  return out;
}

export function parseMeas(text, names) {
  const out = {};
  for (const ln of (text || '').split('\n')) {
    const m = ln.match(NUM);
    if (m && (!names || names.has(m[1].toLowerCase()))) {
      out[m[1].toLowerCase()] = parseFloat(m[2]);
      const a = ln.match(AT);
      if (a) out[m[1].toLowerCase() + '_at'] = parseFloat(a[1]);
    }
  }
  return out;
}

export async function ready() { await engine(); return true; }

export async function run(netlist, maxPoints = 4000) {
  const s = await engine();
  // 引擎按字符数写文件，多字节字符（中文注释等）会把网表末尾截掉、仿真卡住：送进去前换成 ASCII
  const ascii = netlist.replace(/[^\x00-\x7f]/g, '?');
  s.setNetList(ascii.endsWith('\n') ? ascii : ascii + '\n');
  const r = await s.runSim();
  const info = s.getInfo() || '';
  const errors = (s.getError() || []).map((x) => x.trim()).filter((x) => x && /error|failed/i.test(x));
  const cplx = r.dataType === 'complex';
  const n = r.numPoints || 0;
  const step = Math.max(1, Math.ceil(n / maxPoints));
  const data = {};
  const names = [];
  for (const d of r.data || []) {
    const nm = d.name.toLowerCase();
    names.push(nm);
    const v = [];
    for (let i = 0; i < d.values.length; i += step) {
      const x = d.values[i];
      v.push(cplx ? [x.real, x.img] : x);
    }
    data[nm] = v;
  }
  return { meas: parseMeas(info, measNames(netlist)), plot: { names, complex: cplx, data }, errors: errors.slice(0, 20) };
}
