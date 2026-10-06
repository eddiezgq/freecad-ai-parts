<template>
  <svg :viewBox="`0 0 ${W} ${H}`" width="100%" :height="H" role="img" :aria-label="label">
    <line :x1="L" :y1="y(chart.upper)" :x2="W - 8" :y2="y(chart.upper)" stroke="var(--bad)" stroke-dasharray="4 3" />
    <line :x1="L" :y1="y(chart.center)" :x2="W - 8" :y2="y(chart.center)" stroke="#8C96A0" />
    <line :x1="L" :y1="y(chart.lower)" :x2="W - 8" :y2="y(chart.lower)" stroke="var(--bad)" stroke-dasharray="4 3" />
    <text x="0" :y="y(chart.upper) + 4" class="lab">{{ tick(chart.upper) }}</text>
    <text x="0" :y="y(chart.center) + 4" class="lab">{{ tick(chart.center) }}</text>
    <text x="0" :y="y(chart.lower) + 4" class="lab">{{ tick(chart.lower) }}</text>
    <polyline :points="line" fill="none" stroke="var(--accent)" stroke-width="2" />
    <circle v-for="(p, i) in pts" :key="p.id" :cx="x(i)" :cy="y(p.value)" :r="i === pts.length - 1 ? 4 : 2.5"
      :fill="p.result === 'fail' ? 'var(--bad)' : i === pts.length - 1 ? 'var(--warn)' : 'var(--accent)'">
      <title>{{ p.serial }}：{{ p.value }} mm {{ p.result === 'fail' ? '超差' : '' }}</title>
    </circle>
  </svg>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({ chart: Object, height: { type: Number, default: 132 } });
const W = 360;
const L = 40;
const H = props.height;
const pts = computed(() => props.chart?.points || []);
const span = computed(() => {
  const c = props.chart;
  const vals = pts.value.map((p) => p.value).concat([c.lower, c.upper]);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.08 || 0.001;
  return [lo - pad, hi + pad];
});
const y = (v) => 8 + (1 - (v - span.value[0]) / (span.value[1] - span.value[0])) * (H - 16);
const x = (i) => L + 6 + (i * (W - L - 18)) / Math.max(1, pts.value.length - 1);
const line = computed(() => pts.value.map((p, i) => `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' '));
const tick = (v) => '.' + String(Math.round((v % 1) * 1000)).padStart(3, '0');
const label = computed(() => `控制图：最近 ${pts.value.length} 件，上限 ${props.chart.upper}，下限 ${props.chart.lower}`);
</script>

<style scoped>
.lab { font-family: var(--mono); font-size: 10px; fill: var(--muted); }
</style>
