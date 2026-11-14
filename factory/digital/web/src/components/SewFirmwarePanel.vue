<!-- 第 159 轮 159f：平缝机控制器 CTRL-LS 的示例固件——磁场定向控制 + 缝纫状态机，在 Renode 里接第 138 轮 G2 一转负载缝一段。
     整条链示意、四个场景（转速、主轴转角、力矩、电磁铁时序、逐项判据与 159c 对照）、参数表、源码逐文件、下载。
     产物在 factory/designs/ctrl-ls/fw/out（sim_sew.json、fw.json、ctrl-ls-fw.zip）。写法照 FirmwarePanel.vue / MotorPanel.vue。 -->
<template>
  <div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="sim && fw">
      <div class="chain">
        <div class="box">{{ t('脚踏板') }}<small>{{ t('霍尔电压') }}</small></div><span class="arr">→</span>
        <div class="box mcu">{{ t('STM32G431 固件') }}<small>{{ t('缝纫状态机 + 磁场定向控制 16 kHz') }}</small></div><span class="arr">→</span>
        <div class="box">{{ t('功率模块') }}<small>STGIPS14K60T</small></div><span class="arr">→</span>
        <div class="box mot">{{ t('主轴电机 + 机头') }}<small>{{ t('第 138 轮 G2 一转负载') }}</small></div>
        <span class="arr">⇢ {{ t('编码器、Z 相回固件') }}</span>
        <div class="box">{{ t('四个电磁铁') }}<small>{{ t('剪线、拨线、倒缝、抬压脚') }}</small></div>
      </div>
      <p class="small">{{ t('编译出来的真固件（{f} 字节 Flash、{r} 字节 RAM）在 Renode（开源单片机仿真器）里跑；功率模块、电机和机头是仿真对象，负载用第 138 轮 G2 的一转负载表（和 159c 的伺服复算同一张）。', { f: fw.firmware.flash, r: fw.firmware.ram }) }}
        {{ t('每 1 ms 读一次电机真值和固件内存里的遥测区；电磁铁每次吸合、释放都记下时刻和主轴转角。') }}</p>
      <p class="small muted">⚠ {{ td(sim.disclaimer) }}</p>

      <h3>{{ t('场景（{p} / {n} 通过）', { p: sim.scenarios.filter((s) => s.passed).length, n: sim.scenarios.length }) }}</h3>
      <div class="line">
        <button v-for="s in sim.scenarios" :key="s.id" class="chip" :class="{ on: sc && sc.id === s.id }" @click="pick(s.id)">
          {{ s.passed ? '✓' : '✗' }} {{ td(s.name) }}</button>
      </div>
      <div v-if="sc" class="card2">
        <p class="small">{{ td(sc.desc) }}</p>
        <p class="small muted">{{ t('横轴从踩下脚踏算起（秒）；开机对零、找 Z 相在这之前。') }}</p>
        <div class="charts">
          <div>
            <div class="small"><b>{{ t('转速 r/min') }}</b> <span class="k ref">— {{ t('固件给定') }}</span> <span class="k tru">— {{ t('真值') }}</span></div>
            <svg :viewBox="'0 0 ' + W + ' ' + H" class="ch">
              <g v-for="g in grid(rpmY)" :key="'r' + g.v"><line :x1="PL" :x2="W - 4" :y1="g.y" :y2="g.y" class="gl" /><text :x="PL - 4" :y="g.y + 3" class="ax" text-anchor="end">{{ g.v }}</text></g>
              <polyline :points="pts(sc.series.rpm_ref, rpmY)" class="pl ref" />
              <polyline :points="pts(sc.series.rpm, rpmY)" class="pl tru" />
              <text :x="W - 4" :y="H - 4" class="ax" text-anchor="end">{{ t('时间 {s} s', { s: tmax.toFixed(2) }) }}</text>
            </svg>
          </div>
          <div>
            <div class="small"><b>{{ t('力矩 N·m') }}</b> <span class="k tru">— {{ t('电机') }}</span> <span class="k lod">— {{ t('负载（G2 一转负载）') }}</span></div>
            <svg :viewBox="'0 0 ' + W + ' ' + H" class="ch">
              <g v-for="g in grid(tqY)" :key="'q' + g.v"><line :x1="PL" :x2="W - 4" :y1="g.y" :y2="g.y" class="gl" /><text :x="PL - 4" :y="g.y + 3" class="ax" text-anchor="end">{{ g.v }}</text></g>
              <polyline :points="pts(sc.series.tl, tqY)" class="pl lod" />
              <polyline :points="pts(sc.series.tm, tqY)" class="pl tru" />
            </svg>
          </div>
          <div>
            <div class="small"><b>{{ t('主轴转角 °（0° = 针杆最高点）') }}</b></div>
            <svg :viewBox="'0 0 ' + W + ' ' + H" class="ch">
              <g v-for="g in [0, 70, 180, 200, 330, 360]" :key="'a' + g"><line :x1="PL" :x2="W - 4" :y1="y(g, angY)" :y2="y(g, angY)" class="gl" /><text :x="PL - 4" :y="y(g, angY) + 3" class="ax" text-anchor="end">{{ g }}</text></g>
              <polyline v-for="(p, i) in segs(sc.series.ang, angY)" :key="'g' + i" :points="p" class="pl ang" />
            </svg>
          </div>
          <div>
            <div class="small"><b>{{ t('电磁铁与缝纫状态') }}</b></div>
            <svg :viewBox="'0 0 ' + W + ' ' + H" class="ch">
              <g v-for="(n, k) in SOL" :key="'s' + k">
                <text :x="PL - 4" :y="lane(k) + 9" class="ax" text-anchor="end">{{ t(n) }}</text>
                <rect v-for="(b, i) in bars(k)" :key="i" :x="b[0]" :y="lane(k)" :width="Math.max(1, b[1] - b[0])" height="12" :class="'sb s' + k" />
              </g>
              <g v-for="(b, i) in stateBands" :key="'st' + i">
                <rect :x="b.x0" :y="H - PB - 22" :width="Math.max(1, b.x1 - b.x0)" height="14" :class="'band b' + (i % 2)" />
                <text v-if="b.x1 - b.x0 > 34" :x="(b.x0 + b.x1) / 2" :y="H - PB - 12" class="ax" text-anchor="middle">{{ td(b.name) }}</text>
              </g>
            </svg>
          </div>
        </div>
        <table class="tbl">
          <thead><tr><th>{{ t('判据') }}</th><th>{{ t('结果') }}</th><th>{{ t('读数') }}</th><th>{{ t('159c 对照') }}</th></tr></thead>
          <tbody><tr v-for="(c, i) in sc.checks" :key="i"><td class="small">{{ td(c.name) }}</td>
            <td :class="['nw', c.ok ? 'ok' : 'bad']">{{ c.ok ? t('✓ 通过') : t('✗ 不通过') }}</td><td class="small mono">{{ td(c.detail) }}</td>
            <td class="small">{{ td(c.vs) }}</td></tr></tbody>
        </table>
        <details class="small"><summary>{{ t('电磁铁动作记录（{n} 次）', { n: sc.solenoids.length }) }}</summary>
          <table class="tbl"><tbody><tr v-for="(x, i) in sc.solenoids" :key="i">
            <td class="mono">{{ (x.t - sim.t0).toFixed(4) }} s</td><td>{{ td(x.name) }}</td><td>{{ x.on ? t('吸合') : t('释放') }}</td>
            <td class="mono">{{ x.ang.toFixed(1) }}°</td></tr></tbody></table>
        </details>
      </div>

      <h3>{{ t('参数与出处') }}</h3>
      <table class="tbl"><tbody><tr v-for="(p, i) in sim.params" :key="i"><td class="small">{{ td(p.name) }}</td>
        <td class="small mono">{{ td(p.value) }} {{ p.unit }}</td><td class="small muted">{{ td(p.source) }}</td></tr></tbody></table>

      <h3>{{ t('源码') }}</h3>
      <div class="line">
        <button v-for="f in fw.files" :key="f.path" class="chip" :class="{ on: file && file.path === f.path }" @click="file = f">{{ f.path }}</button>
      </div>
      <p v-if="file" class="small muted">{{ td(file.note) }} {{ t('（{n} 行）', { n: file.lines }) }}</p>
      <pre v-if="file" class="code"><span v-for="(l, i) in file.text.split('\n')" :key="i"><i>{{ i + 1 }}</i>{{ l }}
</span></pre>
      <p><a class="btn" :href="base + fw.zip" download>{{ t('下载固件包（源码 + fw.elf + Renode 平台与模型 + 场景脚本与结果）') }}</a></p>
      <p class="small muted">{{ t('自己跑：装 arm-none-eabi-gcc 和 Renode 1.15，') }}<span class="mono">make</span>{{ t(' 后 ') }}<span class="mono">python3 run_sew.py --renode &lt;Renode dir&gt;/renode</span>
        {{ t('（见包里的 README）。') }}</p>
    </template>
    <p v-else-if="!err" class="muted">{{ t('读取中…') }}</p>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { t, td, tk } from '../lib/i18n';

const base = '/api/designs/ctrl-ls/fw/';
const SOL = [tk('剪线'), tk('拨线'), tk('倒缝'), tk('抬压脚')];
const sim = ref(null);
const fw = ref(null);
const sc = ref(null);
const file = ref(null);
const err = ref('');
const W = 420; const H = 170; const PL = 46; const PT = 8; const PB = 18;

function pick(id) { sc.value = sim.value.scenarios.find((s) => s.id === id); }
const t0 = computed(() => sim.value?.t0 || 0);
const tmax = computed(() => (sc.value ? sc.value.series.t[sc.value.series.t.length - 1] - t0.value : 1));
const tmin = computed(() => (sc.value ? sc.value.series.t[0] - t0.value : 0));
function x(tt) { return PL + (W - PL - 4) * (tt - t0.value - tmin.value) / (tmax.value - tmin.value); }
function range(arrs) {
  const v = arrs.flat().filter((z) => z !== null && z !== undefined);
  let lo = Math.min(0, ...v); let hi = Math.max(0, ...v);
  if (hi - lo < 1) hi = lo + 1;
  const pad = (hi - lo) * 0.08;
  return [lo - pad, hi + pad];
}
const rpmY = computed(() => range([sc.value.series.rpm, sc.value.series.rpm_ref]));
const tqY = computed(() => range([sc.value.series.tm, sc.value.series.tl]));
const angY = [-10, 370];
function y(v, r) { return PT + (H - PT - PB) * (1 - (v - r[0]) / (r[1] - r[0])); }
function pts(arr, r) {
  const tt = sc.value.series.t; const rr = r.value || r;
  return arr.map((v, i) => x(tt[i]).toFixed(1) + ',' + y(v, rr).toFixed(1)).join(' ');
}
// 转角过 360° → 0° 时断开，分段画（不画那条竖线）
function segs(arr, r) {
  const tt = sc.value.series.t; const out = []; let seg = [];
  arr.forEach((v, i) => {
    if (i && Math.abs(v - arr[i - 1]) > 180) { out.push(seg.join(' ')); seg = []; }
    seg.push(x(tt[i]).toFixed(1) + ',' + y(v, r).toFixed(1));
  });
  out.push(seg.join(' '));
  return out;
}
function grid(r) {
  const [lo, hi] = r.value || r;
  const raw = (hi - lo) / 4; const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((k) => k * mag).find((s) => s >= raw);
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push({ v: +v.toFixed(6), y: y(v, [lo, hi]) });
  return out;
}
function lane(k) { return PT + 4 + k * 22; }
function bars(k) {
  const s = sc.value.series; const out = []; let x0 = null;
  s.sol.forEach((b, i) => {
    const on = (b >> k) & 1;
    if (on && x0 === null) x0 = x(s.t[i]);
    if (!on && x0 !== null) { out.push([x0, x(s.t[i])]); x0 = null; }
  });
  if (x0 !== null) out.push([x0, x(s.t[s.t.length - 1])]);
  return out;
}
const stateBands = computed(() => {
  const s = sc.value.series; const out = [];
  s.state.forEach((v, i) => {
    if (!out.length || out[out.length - 1].v !== v) out.push({ v, name: sim.value.states[v], x0: x(s.t[i]), x1: x(s.t[i]) });
    else out[out.length - 1].x1 = x(s.t[i]);
  });
  return out;
});
onMounted(async () => {
  try {
    const [a, b] = await Promise.all([fetch(base + 'sim_sew.json'), fetch(base + 'fw.json')]);
    if (!a.ok || !b.ok) throw new Error(t('读不到固件产物（{a} / {b}）', { a: a.status, b: b.status }));
    sim.value = await a.json(); fw.value = await b.json();
    pick('cycle'); file.value = fw.value.files.find((f) => f.path === 'src/sew.c') || fw.value.files[0];
  } catch (e) { err.value = e.message || String(e); }
});
</script>

<style scoped>
.chain { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 8px 0; }
.box { border: 1px solid #cfd6e4; border-radius: 8px; padding: 6px 10px; background: #f8fafc; font-size: 13px; font-weight: 600; }
.box small { display: block; font-weight: 400; color: #64748b; font-size: 11px; }
.box.mcu { background: #eff6ff; border-color: #93c5fd; } .box.mot { background: #fef3c7; border-color: #fcd34d; }
.arr { color: #64748b; font-size: 12px; }
.line { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.chip { border: 1px solid var(--line, #ccd); background: #fff; border-radius: 14px; padding: 3px 10px; cursor: pointer; font-size: 13px; }
.chip.on { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
.card2 { border: 1px solid #e3e6ee; border-radius: 8px; padding: 8px 10px; margin: 6px 0; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 10px; }
.ch { width: 100%; height: auto; background: #fff; border: 1px solid #eef0f5; border-radius: 6px; }
.gl { stroke: #eef0f5; stroke-width: 1; } .ax { font-size: 9px; fill: #64748b; }
.pl { fill: none; stroke-width: 1.4; } .pl.ref { stroke: #94a3b8; stroke-width: 3; } .pl.tru { stroke: #1d4ed8; } .pl.lod { stroke: #d97706; stroke-width: 1; }
.pl.ang { stroke: #16a34a; stroke-width: 1; }
.k { margin-right: 8px; } .k.ref { color: #94a3b8; } .k.tru { color: #1d4ed8; } .k.lod { color: #d97706; }
.sb.s0 { fill: #dc2626; } .sb.s1 { fill: #7c3aed; } .sb.s2 { fill: #0891b2; } .sb.s3 { fill: #16a34a; }
.band.b0 { fill: #eef2ff; } .band.b1 { fill: #f1f5f9; }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 6px; }
.tbl th, .tbl td { border-bottom: 1px solid #eef0f5; padding: 4px 6px; text-align: left; vertical-align: top; }
.ok { color: #15803d; } .bad { color: #b91c1c; } .nw { white-space: nowrap; }
.code { max-height: 60vh; overflow: auto; background: #0f172a; color: #e2e8f0; font-size: 12px; line-height: 1.45; padding: 8px; border-radius: 8px; }
.code i { display: inline-block; width: 3em; color: #64748b; font-style: normal; user-select: none; }
</style>
