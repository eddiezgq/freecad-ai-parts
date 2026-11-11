<!-- 简单折线图（第 102 轮）：t 为横轴（秒），series 为 [{ name, data, cls }]，不同 cls 不同颜色；可选 zero 把 0 包进纵轴范围。 -->
<template>
  <div>
    <div class="small"><b>{{ tr(title) }}</b>
      <span v-for="s in series" :key="s.name" class="k" :class="s.cls">— {{ tr(s.name) }}</span></div>
    <svg :viewBox="'0 0 ' + W + ' ' + H" class="ch">
      <g v-for="g in grid" :key="g.v"><line :x1="PL" :x2="W - 4" :y1="g.y" :y2="g.y" class="gl" />
        <text :x="PL - 4" :y="g.y + 3" class="ax" text-anchor="end">{{ g.v }}</text></g>
      <polyline v-for="s in series" :key="'p' + s.name" :points="pts(s.data)" class="pl" :class="s.cls" />
      <text :x="PL" :y="H - 4" class="ax">{{ t0 }} s</text>
      <text :x="W - 4" :y="H - 4" class="ax" text-anchor="end">{{ t1 }} s</text>
    </svg>
  </div>
</template>

<script setup>
import { t as tr } from '../lib/i18n';
import { computed } from 'vue';

const props = defineProps({ title: String, t: Array, series: Array, zero: { type: Boolean, default: false } });
const W = 420; const H = 170; const PL = 50; const PT = 8; const PB = 18;
const t0 = computed(() => props.t[0]);
const t1 = computed(() => props.t[props.t.length - 1]);
const rng = computed(() => {
  const v = props.series.flatMap((s) => s.data).filter((x) => x !== null && x !== undefined);
  let lo = Math.min(...v); let hi = Math.max(...v);
  if (props.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.08;
  return [lo - pad, hi + pad];
});
function y(v) { const [lo, hi] = rng.value; return PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo)); }
function x(t) { return PL + (W - PL - 4) * (t - t0.value) / ((t1.value - t0.value) || 1); }
function pts(d) { return d.map((v, i) => (v === null ? null : x(props.t[i]).toFixed(1) + ',' + y(v).toFixed(1))).filter((p) => p).join(' '); }
const grid = computed(() => {
  const [lo, hi] = rng.value;
  const raw = (hi - lo) / 4; const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((k) => k * mag).find((s) => s >= raw);
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push({ v: +v.toPrecision(6), y: y(v) });
  return out;
});
</script>

<style scoped>
.ch { width: 100%; height: auto; background: #fff; border: 1px solid #eef0f5; border-radius: 6px; }
.gl { stroke: #eef0f5; stroke-width: 1; } .ax { font-size: 9px; fill: #64748b; }
.pl { fill: none; stroke-width: 1.6; }
.pl.truth { stroke: #94a3b8; stroke-width: 3.5; } .pl.fwk { stroke: #1d4ed8; } .pl.ref { stroke: #f59e0b; stroke-dasharray: 4 3; }
.pl.c2 { stroke: #16a34a; } .pl.c3 { stroke: #dc2626; }
.k { margin-left: 8px; } .k.truth { color: #94a3b8; } .k.fwk { color: #1d4ed8; } .k.ref { color: #f59e0b; } .k.c2 { color: #16a34a; } .k.c3 { color: #dc2626; }
</style>
