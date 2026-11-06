<!-- 第 100 轮（电子 E7）：驱动板 B 版示例固件——MCU 经 SPI1 读编码器接口芯片 WQ-ENCIF，在 Renode 里跑。
     整条链示意、六个场景（设定 vs 固件读到的转速和位置、逐项判据）、源码逐文件、下载。产物在 factory/designs/drv-joint-b/fw/out。 -->
<template>
  <div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="sim && fw">
      <div class="chain">
        <div class="box">虚拟电机<small>转速曲线 → 编码器 A/B/Z</small></div><span class="arr">→</span>
        <div class="box chip">WQ-ENCIF<small>计数、Z 锁存、报错</small></div><span class="arr">⇄ SPI1 4 MHz ⇄</span>
        <div class="box mcu">STM32G431 固件<small>1 kHz 读数、算转速</small></div><span class="arr">→</span>
        <div class="box">遥测区<small>调试器经 SWD 看</small></div>
      </div>
      <p class="small">编译出来的真固件（{{ fw.firmware.flash }} 字节 Flash、{{ fw.firmware.ram }} 字节 RAM）在 <b>Renode {{ sim.renode }}</b>（开源单片机仿真器）里跑；
        芯片是按第 92 轮规格写的寄存器级模型（芯片 RTL 已在 <router-link to="/chip-design?tab=sim">芯片设计</router-link> 里与参考模型逐拍比对过）。
        每 10 ms 读一次固件内存里的遥测区，与虚拟电机的真值比。编码器 2500 线 ×4 = {{ sim.cpr }} 计数/转。</p>
      <p class="small muted">⚠ {{ sim.disclaimer }}</p>

      <h3>场景（{{ sim.scenarios.filter((s) => s.passed).length }} / {{ sim.scenarios.length }} 通过）</h3>
      <div class="line">
        <button v-for="s in sim.scenarios" :key="s.id" class="chip" :class="{ on: sc && sc.id === s.id }" @click="pick(s.id)">
          {{ s.passed ? '✓' : '✗' }} {{ s.name }}</button>
      </div>
      <div v-if="sc" class="card2">
        <p class="small">{{ sc.desc }}</p>
        <div class="charts">
          <div>
            <div class="small"><b>转速 rpm</b>　<span class="k truth">— 设定（真值）</span>　<span class="k fwk">— 固件读到</span></div>
            <svg :viewBox="'0 0 ' + W + ' ' + H" class="ch">
              <g v-for="g in grid(rpmY)" :key="'r' + g.v"><line :x1="PL" :x2="W - 4" :y1="g.y" :y2="g.y" class="gl" /><text :x="PL - 4" :y="g.y + 3" class="ax" text-anchor="end">{{ g.v }}</text></g>
              <polyline :points="pts(sc.series.truth_rpm, rpmY)" class="pl truth" />
              <polyline :points="pts(sc.series.rpm, rpmY)" class="pl fwk" />
              <text :x="W - 4" :y="H - 4" class="ax" text-anchor="end">时间 {{ tmax }} s</text>
            </svg>
          </div>
          <div>
            <div class="small"><b>位置（计数）</b>　<span class="k truth">— 真值</span>　<span class="k fwk">— 固件读到</span>
              <span v-if="sc.id === 'index'" class="k absk">— 绝对角度（相对 Z）</span></div>
            <svg :viewBox="'0 0 ' + W + ' ' + H" class="ch">
              <g v-for="g in grid(cntY)" :key="'c' + g.v"><line :x1="PL" :x2="W - 4" :y1="g.y" :y2="g.y" class="gl" /><text :x="PL - 4" :y="g.y + 3" class="ax" text-anchor="end">{{ g.v }}</text></g>
              <polyline :points="pts(sc.series.truth_cnt, cntY)" class="pl truth" />
              <polyline :points="pts(sc.series.cnt, cntY)" class="pl fwk" />
              <polyline v-if="sc.id === 'index'" :points="pts(sc.series.abs_cnt.map((v) => (v < 0 ? null : v)), cntY)" class="pl absk" />
            </svg>
          </div>
        </div>
        <table class="tbl">
          <thead><tr><th>判据</th><th>结果</th><th>读数</th></tr></thead>
          <tbody><tr v-for="(c, i) in sc.checks" :key="i"><td class="small">{{ c.name }}</td>
            <td :class="c.ok ? 'ok' : 'bad'">{{ c.ok ? '✓ 通过' : '✗ 不通过' }}</td><td class="small mono">{{ c.detail }}</td></tr></tbody>
        </table>
        <details class="small"><summary>结束时的遥测区（固件内存 {{ sim.tlm_addr }}）</summary>
          <table class="tbl"><tbody><tr v-for="(v, k) in sc.final" :key="k"><td class="mono">{{ k }}</td><td class="mono">{{ show(k, v) }}</td></tr></tbody></table>
        </details>
      </div>

      <h3>源码</h3>
      <div class="line">
        <button v-for="f in fw.files" :key="f.path" class="chip" :class="{ on: file && file.path === f.path }" @click="file = f">{{ f.path }}</button>
      </div>
      <p v-if="file" class="small muted">{{ file.note }}（{{ file.lines }} 行）</p>
      <pre v-if="file" class="code"><span v-for="(l, i) in file.text.split('\n')" :key="i"><i>{{ i + 1 }}</i>{{ l }}
</span></pre>
      <p><a class="btn" :href="base + fw.zip" download>下载固件包（源码 + fw.elf + Renode 平台与芯片模型 + 场景脚本）</a></p>
      <p class="small muted">自己跑：装 arm-none-eabi-gcc 和 Renode 1.15，<span class="mono">make</span> 后 <span class="mono">python3 run.py --renode &lt;Renode 目录&gt;/renode</span>（见包里的 README）。
        本轮只做编码器这一路；电机控制（PWM、电流环）和 CAN 以后再做。</p>
    </template>
    <p v-else-if="!err" class="muted">读取中…</p>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';

const base = '/api/designs/drv-joint-b/fw/';
const sim = ref(null);
const fw = ref(null);
const sc = ref(null);
const file = ref(null);
const err = ref('');
const W = 420; const H = 170; const PL = 46; const PT = 8; const PB = 18;

function pick(id) { sc.value = sim.value.scenarios.find((s) => s.id === id); }
const tmax = computed(() => (sc.value ? sc.value.series.t[sc.value.series.t.length - 1] : 1));
function range(arrs) {
  const v = arrs.flat().filter((x) => x !== null && x !== undefined);
  let lo = Math.min(0, ...v); let hi = Math.max(0, ...v);
  if (hi - lo < 1) hi = lo + 1;
  const pad = (hi - lo) * 0.08;
  return [lo - pad, hi + pad];
}
const rpmY = computed(() => range([sc.value.series.truth_rpm, sc.value.series.rpm]));
const cntY = computed(() => range([sc.value.series.truth_cnt, sc.value.series.cnt]));
function y(v, r) { return PT + (H - PT - PB) * (1 - (v - r[0]) / (r[1] - r[0])); }
function pts(arr, r) {
  const t = sc.value.series.t;
  return arr.map((v, i) => (v === null ? null : (PL + (W - PL - 4) * t[i] / tmax.value).toFixed(1) + ',' + y(v, r.value || r).toFixed(1)))
    .filter((p) => p).join(' ');
}
function grid(r) {
  const [lo, hi] = r.value || r;
  const raw = (hi - lo) / 4; const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((k) => k * mag).find((s) => s >= raw);
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push({ v: +v.toFixed(6), y: y(v, [lo, hi]) });
  return out;
}
function show(k, v) {
  if (k === 'id' || k === 'ctrl' || k === 'status') return '0x' + (v >>> 0).toString(16).toUpperCase();
  if (k === 'state') return ['启动', '运行', '芯片缺失'][v] || v;
  if (k === 'rpm_x10') return (v / 10).toFixed(1) + ' rpm';
  return v;
}
onMounted(async () => {
  try {
    const [a, b] = await Promise.all([fetch(base + 'sim.json'), fetch(base + 'fw.json')]);
    if (!a.ok || !b.ok) throw new Error('读不到固件产物（' + a.status + ' / ' + b.status + '）');
    sim.value = await a.json(); fw.value = await b.json();
    pick('fwd'); file.value = fw.value.files[0];
  } catch (e) { err.value = e.message || String(e); }
});
</script>

<style scoped>
.chain { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 8px 0; }
.box { border: 1px solid #cfd6e4; border-radius: 8px; padding: 6px 10px; background: #f8fafc; font-size: 13px; font-weight: 600; }
.box small { display: block; font-weight: 400; color: #64748b; font-size: 11px; }
.box.chip { background: #ecfdf5; border-color: #86efac; } .box.mcu { background: #eff6ff; border-color: #93c5fd; }
.arr { color: #64748b; font-size: 12px; }
.line { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.chip { border: 1px solid var(--line, #ccd); background: #fff; border-radius: 14px; padding: 3px 10px; cursor: pointer; font-size: 13px; }
.chip.on { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
.card2 { border: 1px solid #e3e6ee; border-radius: 8px; padding: 8px 10px; margin: 6px 0; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; }
.ch { width: 100%; height: auto; background: #fff; border: 1px solid #eef0f5; border-radius: 6px; }
.gl { stroke: #eef0f5; stroke-width: 1; } .ax { font-size: 9px; fill: #64748b; }
.pl { fill: none; stroke-width: 1.6; } .pl.truth { stroke: #94a3b8; stroke-width: 3.5; } .pl.fwk { stroke: #1d4ed8; } .pl.absk { stroke: #16a34a; }
.k { margin-right: 8px; } .k.truth { color: #94a3b8; } .k.fwk { color: #1d4ed8; } .k.absk { color: #16a34a; }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 6px; }
.tbl th, .tbl td { border-bottom: 1px solid #eef0f5; padding: 4px 6px; text-align: left; vertical-align: top; }
.ok { color: #15803d; } .bad { color: #b91c1c; }
.code { max-height: 60vh; overflow: auto; background: #0f172a; color: #e2e8f0; font-size: 12px; line-height: 1.45; padding: 8px; border-radius: 8px; }
.code i { display: inline-block; width: 3em; color: #64748b; font-style: normal; user-select: none; }
</style>
