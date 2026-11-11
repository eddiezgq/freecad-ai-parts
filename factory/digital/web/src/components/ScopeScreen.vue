<!-- 第 82 轮：示波器屏幕（10 × 8 格）。traces：scopeAcquire 的结果；vdiv / off：每个通道的伏/格与偏置；tdiv：秒/格 -->
<template>
  <div class="scope">
    <svg viewBox="0 0 500 400" class="scr" @mousemove="hover" @mouseleave="hx = null">
      <rect x="0" y="0" width="500" height="400" class="bg" />
      <g class="grid">
        <line v-for="i in 11" :key="'x' + i" :x1="(i - 1) * 50" :x2="(i - 1) * 50" y1="0" y2="400" :class="{ mid: i === 6 }" />
        <line v-for="i in 9" :key="'y' + i" x1="0" x2="500" :y1="(i - 1) * 50" :y2="(i - 1) * 50" :class="{ mid: i === 5 }" />
      </g>
      <polyline v-for="(tr, k) in traces" :key="k" :points="pts(tr, k)" fill="none" :stroke="COL[k]" stroke-width="1.6" />
      <line class="trig" x1="50" x2="50" y1="0" y2="10" />
      <line v-if="hx != null" class="cur" :x1="hx" :x2="hx" y1="0" y2="400" />
    </svg>
    <div class="info small">
      <span v-for="(tr, k) in traces" :key="'i' + k" :style="{ color: COL[k] }">CH{{ k + 1 }} {{ t(tr.name) }}  {{ si(vdiv[k]) }}{{ t('V/格') }}</span>
      <span>{{ si(tdiv) }}{{ t('s/格') }}</span>
      <span v-if="hx != null && traces.length">t = {{ si(curT) }}s  <b v-for="(tr, k) in traces" :key="'h' + k" :style="{ color: COL[k] }">{{ si(curV(tr)) }}V  </b></span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';
import { t } from '../lib/i18n';

const props = defineProps({ traces: { type: Array, default: () => [] }, vdiv: { type: Array, default: () => [1, 1, 1, 1] },
  off: { type: Array, default: () => [0, 0, 0, 0] }, tdiv: { type: Number, default: 1e-3 } });
const COL = ['#eab308', '#22d3ee', '#f472b6', '#4ade80'];
const hx = ref(null);
function pts(tr, k) {
  const n = tr.v.length; const vd = props.vdiv[k]; const of = props.off[k] || 0;
  const step = Math.max(1, Math.floor(n / 1000));
  const out = [];
  for (let i = 0; i < n; i += step) out.push(`${(i / n * 500).toFixed(1)},${(200 - (tr.v[i] - of) / vd * 50).toFixed(1)}`);
  return out.join(' ');
}
const curI = computed(() => (hx.value == null || !props.traces.length ? 0 : Math.min(props.traces[0].v.length - 1, Math.round(hx.value / 500 * props.traces[0].v.length))));
const curT = computed(() => (props.traces.length ? props.traces[0].t0 + curI.value * props.traces[0].dt : 0));
function curV(tr) { return tr.v[curI.value]; }
function hover(ev) { const r = ev.currentTarget.getBoundingClientRect(); hx.value = (ev.clientX - r.left) / r.width * 500; }
function si(v) {
  if (v == null || !isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a === 0) return '0';
  for (const [k, s] of [[1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'μ'], [1e-9, 'n']]) if (a >= k * 0.999) return (+(v / k).toPrecision(4)) + ' ' + s;
  return v.toExponential(2);
}
</script>

<style scoped>
.scope { max-width: 560px; }
.scr { width: 100%; height: auto; border-radius: 8px; display: block; }
.bg { fill: #0b1220; }
.grid line { stroke: #26324a; stroke-width: 1; } .grid line.mid { stroke: #3b4a66; }
.trig { stroke: #f97316; stroke-width: 3; }
.cur { stroke: #94a3b8; stroke-dasharray: 3 3; }
.info { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 4px; font-family: var(--mono, monospace); }
</style>
