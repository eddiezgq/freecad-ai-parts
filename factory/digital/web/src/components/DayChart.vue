<template>
  <!-- 按日期的曲线（孪生用）：多条线 + 水平参考线（限值、振动分区），鼠标十字线看当天的数 -->
  <div class="dc">
    <div class="dc-head"><b>{{ title }}</b><span class="muted small">（{{ unit }}）</span>
      <span class="legend small"><span v-for="s in series" :key="s.label"><i :style="{ background: s.color }"></i>{{ s.label }}</span></span>
    </div>
    <svg :viewBox="`0 0 ${W} ${H}`" class="dc-svg" role="img" :aria-label="title" @mousemove="move" @mouseleave="hi = null">
      <rect v-for="b in bands" :key="'b' + b.label" :x="L" :width="W - L - R" :y="sy(Math.min(b.to, yhi))" :height="Math.max(0, sy(Math.max(b.from, ylo)) - sy(Math.min(b.to, yhi)))" :fill="b.color" opacity="0.12" />
      <g class="grid"><line v-for="y in yticks" :key="'y' + y" :x1="L" :x2="W - R" :y1="sy(y)" :y2="sy(y)" /></g>
      <g v-for="r in refs" :key="'r' + r.label">
        <line :x1="L" :x2="W - R" :y1="sy(r.y)" :y2="sy(r.y)" :stroke="r.color" stroke-dasharray="5 4" />
        <text :x="W - R - 4" :y="sy(r.y) - 3" text-anchor="end" class="small" :fill="r.color">{{ r.label }}</text>
      </g>
      <g class="ax small">
        <text v-for="y in yticks" :key="'t' + y" :x="L - 6" :y="sy(y) + 4" text-anchor="end">{{ fmt(y) }}</text>
        <text v-for="i in xticks" :key="'x' + i" :x="sx(i)" :y="H - 4" text-anchor="middle">{{ days[i].slice(5) }}</text>
      </g>
      <polyline v-for="s in series" :key="s.label" :points="pts(s.values)" fill="none" :stroke="s.color" stroke-width="2" stroke-linejoin="round" :stroke-dasharray="s.dash || ''" />
      <g v-if="hi != null">
        <line class="cross" :x1="sx(hi)" :x2="sx(hi)" :y1="T" :y2="H - B" />
        <template v-for="s in series" :key="'c' + s.label"><circle v-if="s.values[hi] != null" :cx="sx(hi)" :cy="sy(s.values[hi])" r="4" :fill="s.color" stroke="#fff" stroke-width="2" /></template>
      </g>
    </svg>
    <div v-if="hi != null" class="tip small" :style="{ left: Math.min(70, hi / Math.max(1, days.length - 1) * 100) + '%' }">
      <div class="muted">{{ days[hi] }}</div>
      <div v-for="s in series" :key="'v' + s.label"><i :style="{ background: s.color }"></i>{{ s.label }}：<b>{{ s.values[hi] == null ? '—' : fmt(s.values[hi]) }}</b></div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';

const props = defineProps({
  title: String, unit: String,
  days: { type: Array, required: true },
  series: { type: Array, required: true },          // [{label, values, color, dash?}]
  refs: { type: Array, default: () => [] },         // [{y, label, color}]
  bands: { type: Array, default: () => [] },        // [{from, to, color, label}]
  min: { type: Number, default: null },
});
const W = 640, H = 180, L = 50, R = 10, T = 10, B = 22;
const hi = ref(null);
const all = computed(() => props.series.flatMap((s) => s.values).filter((v) => v != null).concat(props.refs.map((r) => r.y)));
const ylo = computed(() => (props.min != null ? props.min : Math.min(...all.value, 0)));
const yhi = computed(() => { const m = Math.max(...all.value, ylo.value + 1); return m + (m - ylo.value) * 0.08; });
const sx = (i) => L + (i / Math.max(1, props.days.length - 1)) * (W - L - R);
const sy = (v) => T + (1 - (v - ylo.value) / (yhi.value - ylo.value || 1)) * (H - T - B);
const pts = (vs) => vs.map((v, i) => (v == null ? null : `${sx(i).toFixed(1)},${sy(v).toFixed(1)}`)).filter(Boolean).join(' ');
const yticks = computed(() => {
  const span = yhi.value - ylo.value, step = Math.pow(10, Math.floor(Math.log10(span / 4)));
  const st = [1, 2, 5, 10].map((k) => k * step).find((s) => span / s <= 5) || step * 10;
  const out = []; for (let y = Math.ceil(ylo.value / st) * st; y <= yhi.value; y += st) out.push(+y.toFixed(6)); return out;
});
const xticks = computed(() => { const n = props.days.length, k = Math.max(1, Math.ceil(n / 6)); const out = []; for (let i = 0; i < n; i += k) out.push(i); return out; });
const fmt = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
function move(e) {
  const r = e.currentTarget.getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width * W;
  hi.value = Math.max(0, Math.min(props.days.length - 1, Math.round((x - L) / (W - L - R) * (props.days.length - 1))));
}
</script>

<style scoped>
.dc { position: relative; }
.dc-head { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
.legend { margin-left: auto; display: flex; gap: 10px; }
.legend i, .tip i { display: inline-block; width: 10px; height: 3px; margin-right: 4px; vertical-align: 3px; }
.dc-svg { width: 100%; height: auto; background: var(--surface-2); border-radius: 8px; }
.grid line { stroke: #DDE2DC; }
.ax text { fill: #6B7570; font-size: 11px; }
.cross { stroke: #8A948C; stroke-dasharray: 3 3; }
.tip { position: absolute; top: 28px; background: #fff; border: 1px solid var(--line); border-radius: 6px; padding: 4px 8px; pointer-events: none; }
</style>
