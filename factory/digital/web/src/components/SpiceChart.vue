<!-- 第 79 轮：电路分析的曲线。kind：tran（横轴时间）、dc（横轴扫描量）、ac（横轴频率，对数；纵轴 dB，另画相位）。十字线读数。 -->
<template>
  <div class="sc">
    <div class="sc-head"><b>{{ title }}</b>
      <span class="legend small"><span v-for="l in lines" :key="l.name"><i :style="{ background: l.color }"></i>{{ l.name }}</span></span></div>
    <svg ref="svg" :viewBox="`0 0 ${W} ${H}`" class="sc-svg" @mousemove="hover" @mouseleave="hi = null">
      <rect :x="0" :y="0" :width="W" :height="H" fill="#fff" />
      <g class="grid"><line v-for="y in yt" :key="'y' + y" :x1="L" :x2="W - R" :y1="sy(y)" :y2="sy(y)" />
        <line v-for="x in xt" :key="'x' + x" :y1="T" :y2="H - B" :x1="sx(x)" :x2="sx(x)" /></g>
      <g class="ax">
        <text v-for="y in yt" :key="'ty' + y" :x="L - 6" :y="sy(y) + 4" text-anchor="end">{{ si(y) }}</text>
        <text v-for="x in xt" :key="'tx' + x" :x="sx(x)" :y="H - B + 16" text-anchor="middle">{{ si(x) }}</text>
        <text :x="W - R" :y="H - 4" text-anchor="end">{{ xlabel }}</text>
        <text :x="L" :y="T - 6">{{ ylabel }}</text>
      </g>
      <polyline v-for="l in lines" :key="l.name" :points="l.pts" fill="none" :stroke="l.color" stroke-width="1.8" stroke-linejoin="round" />
      <g v-if="hi != null"><line class="cross" :x1="sx(xs[hi])" :x2="sx(xs[hi])" :y1="T" :y2="H - B" />
        <circle v-for="l in lines" :key="'c' + l.name" :cx="sx(xs[hi])" :cy="sy(l.v[hi])" r="3.5" :fill="l.color" /></g>
    </svg>
    <div v-if="hi != null" class="tip small">{{ xlabel }} = {{ si(xs[hi]) }}　<span v-for="l in lines" :key="'v' + l.name"><i :style="{ background: l.color }"></i>{{ l.name }} = <b>{{ si(l.v[hi]) }}</b>　</span></div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';

const props = defineProps({
  title: String,
  plot: { type: Object, required: true },        // { names, complex, data }
  show: { type: Array, required: true },         // 要画的量，如 ['v(out)']
  kind: { type: String, default: 'tran' },       // tran / dc / ac
  phase: { type: Boolean, default: false },      // ac：画相位而不是 dB
});
const W = 640; const H = 240; const L = 60; const R = 16; const T = 20; const B = 34;
const COLORS = ['#2563eb', '#dc2626', '#16a34a', '#9333ea', '#ea580c'];
const svg = ref(null);
const hi = ref(null);

const xname = computed(() => props.plot.names[0]);
const isLog = computed(() => props.kind === 'ac');
const xs = computed(() => {
  const v = props.plot.data[xname.value] || [];
  return props.plot.complex ? v.map((c) => c[0]) : v;
});
const xlabel = computed(() => (props.kind === 'ac' ? '频率 Hz' : props.kind === 'dc' ? '扫描 ' + xname.value : '时间 s'));
const ylabel = computed(() => (props.kind === 'ac' ? (props.phase ? '相位 °' : '幅值 dB') : props.show.some((n) => n.startsWith('i(')) && props.show.every((n) => n.startsWith('i(')) ? 'A' : 'V / A'));
function yval(c) {
  if (!props.plot.complex) return c;
  const [re, im] = c;
  return props.phase ? Math.atan2(im, re) * 180 / Math.PI : 20 * Math.log10(Math.hypot(re, im) || 1e-30);
}
const series = computed(() => props.show.filter((n) => props.plot.data[n]).map((n, k) => ({ name: n, color: COLORS[k % COLORS.length], v: props.plot.data[n].map(yval) })));
const xr = computed(() => {
  const v = xs.value.filter((x) => !isLog.value || x > 0);
  return [Math.min(...v), Math.max(...v)];
});
const yr = computed(() => {
  let lo = Infinity; let hi2 = -Infinity;
  for (const s of series.value) for (const y of s.v) { if (isFinite(y)) { lo = Math.min(lo, y); hi2 = Math.max(hi2, y); } }
  if (!isFinite(lo)) return [0, 1];
  if (hi2 - lo < 1e-12) { const d = Math.abs(lo) * 0.05 || 1; return [lo - d, hi2 + d]; }
  const pad = (hi2 - lo) * 0.06;
  return [lo - pad, hi2 + pad];
});
function fx(x) { return isLog.value ? Math.log10(x) : x; }
function sx(x) { const [a, b] = xr.value.map(fx); return L + (fx(x) - a) / (b - a || 1) * (W - L - R); }
function sy(y) { const [a, b] = yr.value; return H - B - (y - a) / (b - a || 1) * (H - T - B); }
function ticks(a, b, n = 5) {
  const st = Math.pow(10, Math.floor(Math.log10((b - a) / n || 1)));
  const m = [1, 2, 5, 10].find((k) => (b - a) / (k * st) <= n) * st;
  const out = [];
  for (let v = Math.ceil(a / m) * m; v <= b + 1e-12 * Math.abs(b); v += m) out.push(+v.toPrecision(12));
  return out;
}
const yt = computed(() => ticks(...yr.value));
const xt = computed(() => {
  if (!isLog.value) return ticks(...xr.value);
  const out = [];
  for (let e = Math.ceil(Math.log10(xr.value[0])); e <= Math.log10(xr.value[1]); e++) out.push(Math.pow(10, e));
  return out;
});
const lines = computed(() => series.value.map((s) => ({ ...s, pts: s.v.map((y, i) => `${sx(xs.value[i]).toFixed(1)},${sy(y).toFixed(1)}`).join(' ') })));
function si(v) {
  if (v == null || !isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a === 0) return '0';
  const P = [[1e9, 'G'], [1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'μ'], [1e-9, 'n'], [1e-12, 'p']];
  for (const [k, s] of P) if (a >= k * 0.999) return (+(v / k).toPrecision(4)) + s;
  return v.toExponential(2);
}
function hover(ev) {
  const r = svg.value.getBoundingClientRect();
  const px = (ev.clientX - r.left) / r.width * W;
  let best = 0; let bd = Infinity;
  xs.value.forEach((x, i) => { const d = Math.abs(sx(x) - px); if (d < bd) { bd = d; best = i; } });
  hi.value = best;
}
defineExpose({ svg });
</script>

<style scoped>
.sc { position: relative; margin: 6px 0 12px; max-width: 760px; }
.sc-head { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }
.legend i, .tip i { display: inline-block; width: 10px; height: 3px; margin: 0 4px 3px 8px; vertical-align: middle; }
.sc-svg { width: 100%; height: auto; border: 1px solid var(--line, #e5e7eb); border-radius: 6px; }
.grid line { stroke: #eef0f3; }
.ax text { font-size: 11px; fill: #6b7280; }
.cross { stroke: #9ca3af; stroke-dasharray: 3 3; }
.tip { color: var(--muted, #555); }
</style>
