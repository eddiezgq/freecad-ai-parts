<template>
  <!-- 时间曲线（一个单位一张图）：十字线 + 数值提示；点图上把动画跳到那一刻 -->
  <div class="tc">
    <div class="tc-head">
      <b>{{ title }}</b><span class="muted small">（{{ unit }}；横轴：时间 s）</span>
      <span v-if="lines.length > 1" class="legend small">
        <span v-for="l in lines" :key="l.name"><i :style="{ background: l.color }"></i>{{ l.label }}</span>
      </span>
    </div>
    <svg ref="svg" :viewBox="`0 0 ${W} ${H}`" class="tc-svg" role="img" :aria-label="title" @mousemove="hover" @mouseleave="hx = null" @click="seek">
      <g class="grid">
        <line v-for="y in yticks" :key="'y' + y" :x1="L" :x2="W - R" :y1="sy(y)" :y2="sy(y)" />
      </g>
      <line v-if="ylo < 0 && yhi > 0" class="zero" :x1="L" :x2="W - R" :y1="sy(0)" :y2="sy(0)" />
      <g class="ax small">
        <text v-for="y in yticks" :key="'t' + y" :x="L - 6" :y="sy(y) + 4" text-anchor="end">{{ fmt(y) }}</text>
        <text v-for="x in xticks" :key="'x' + x" :x="sx(x)" :y="H - 4" text-anchor="middle">{{ fmt(x) }}</text>
      </g>
      <polyline v-for="l in lines" :key="l.name" :points="l.pts" fill="none" :stroke="l.color" stroke-width="2" stroke-linejoin="round" />
      <line v-if="cursor != null" class="cursor" :x1="sx(cursor)" :x2="sx(cursor)" :y1="T" :y2="H - B" />
      <g v-if="hx != null">
        <line class="cross" :x1="sx(t[hi])" :x2="sx(t[hi])" :y1="T" :y2="H - B" />
        <circle v-for="l in lines" :key="'c' + l.name" :cx="sx(t[hi])" :cy="sy(l.v[hi])" r="4" :fill="l.color" stroke="#fff" stroke-width="2" />
      </g>
    </svg>
    <div v-if="hx != null" class="tip small" :style="{ left: Math.min(tipX, 70) + '%' }">
      <div class="muted">t = {{ t[hi].toFixed(3) }} s</div>
      <div v-for="l in lines" :key="'v' + l.name"><i :style="{ background: l.color }"></i>{{ l.label }}：<b>{{ fmt(l.v[hi]) }}</b> {{ unit }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';

const props = defineProps({
  title: String, unit: String,
  t: { type: Object, required: true },             // Float32Array
  series: { type: Array, required: true },         // [{name, label, values(已换算), color}]
  cursor: { type: Number, default: null },
});
const emit = defineEmits(['seek']);
const W = 640, H = 190, L = 56, R = 12, T = 10, B = 22;
const svg = ref(null);
const hx = ref(null);
const t0 = computed(() => props.t[0] || 0), t1 = computed(() => props.t[props.t.length - 1] || 1);
const range = computed(() => {
  let lo = Infinity, hi = -Infinity;
  for (const s of props.series) for (const v of s.values) { if (v < lo) lo = v; if (v > hi) hi = v; }
  if (!isFinite(lo)) return [0, 1];
  if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.06;
  return [lo - pad, hi + pad];
});
const ylo = computed(() => range.value[0]), yhi = computed(() => range.value[1]);
const sx = (x) => L + (x - t0.value) / (t1.value - t0.value || 1) * (W - L - R);
const sy = (y) => T + (yhi.value - y) / (yhi.value - ylo.value) * (H - T - B);
function nice(lo, hi, n) {
  const step0 = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(step0)), f = step0 / mag;
  const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag;
  const out = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-12; v += step) out.push(+v.toPrecision(12));
  return out;
}
const yticks = computed(() => nice(ylo.value, yhi.value, 4));
const xticks = computed(() => nice(t0.value, t1.value, 6));
const fmt = (v) => { const a = Math.abs(v); return a >= 1000 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : a >= 0.01 || a === 0 ? v.toFixed(2) : v.toExponential(1); };
const lines = computed(() => {
  const n = props.t.length, step = Math.max(1, Math.floor(n / 1200));     // 点太多时抽稀
  return props.series.map((s) => {
    let pts = '';
    for (let i = 0; i < n; i += step) pts += `${sx(props.t[i]).toFixed(1)},${sy(s.values[i]).toFixed(1)} `;
    return { ...s, pts, v: s.values };
  });
});
const hi = computed(() => {
  if (hx.value == null) return 0;
  const tt = t0.value + (hx.value - L) / (W - L - R) * (t1.value - t0.value);
  let lo = 0, up = props.t.length - 1;
  while (up - lo > 1) { const m = (lo + up) >> 1; if (props.t[m] < tt) lo = m; else up = m; }
  return Math.abs(props.t[lo] - tt) < Math.abs(props.t[up] - tt) ? lo : up;
});
const tipX = computed(() => ((hx.value || 0) / W) * 100);
function svgX(ev) { const r = svg.value.getBoundingClientRect(); return ((ev.clientX - r.left) / r.width) * W; }
function hover(ev) { const x = svgX(ev); hx.value = x >= L && x <= W - R ? x : null; }
function seek(ev) { const x = svgX(ev); if (x >= L) emit('seek', t0.value + (x - L) / (W - L - R) * (t1.value - t0.value)); }
</script>

<style scoped>
.tc { position: relative; }
.tc-head { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
.legend { margin-left: auto; display: flex; gap: 10px; flex-wrap: wrap; color: var(--muted); }
.legend i, .tip i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: -1px; }
.tc-svg { width: 100%; height: auto; cursor: crosshair; display: block; }
.grid line { stroke: #e3e6e2; stroke-width: 1; }
.zero { stroke: #9aa3ad; stroke-width: 1; }
.ax text { fill: var(--muted); font-size: 11px; }
.cursor { stroke: var(--ink); stroke-width: 1; stroke-dasharray: 3 3; }
.cross { stroke: #9aa3ad; stroke-width: 1; }
.tip { position: absolute; top: 26px; background: #fff; border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px;
  pointer-events: none; box-shadow: 0 2px 8px rgba(0,0,0,.08); white-space: nowrap; transform: translateX(12px); }
</style>
