<!-- 第 79 轮：例题原理图（示意）。元件旁显示当前取值；点带参数的元件 → 发出 pick(参数键) -->
<template>
  <svg :viewBox="'0 0 640 250'" class="sch" role="img" aria-label="原理图">
    <g v-for="(e, i) in items" :key="i" :class="{ pick: e.p }" @click="e.p && emit('pick', e.p)">
      <template v-if="e.t === 'W'"><polyline :points="e.pts.map((q) => q.join(',')).join(' ')" class="w" /></template>
      <circle v-else-if="e.t === 'DOT'" :cx="e.at[0]" :cy="e.at[1]" r="3" class="dot" />
      <text v-else-if="e.t === 'TXT'" :x="e.at[0]" :y="e.at[1]" class="txt">{{ e.s }}</text>
      <text v-else-if="e.t === 'NODE'" :x="e.at[0]" :y="e.at[1]" class="node">{{ e.s }}</text>
      <g v-else-if="e.t === 'GND'" :transform="`translate(${e.at[0]},${e.at[1]})`" class="w">
        <line x1="-10" y1="0" x2="10" y2="0" /><line x1="-6" y1="4" x2="6" y2="4" /><line x1="-2" y1="8" x2="2" y2="8" /></g>
      <g v-else-if="e.t === 'OP'" :transform="`translate(${e.at[0]},${e.at[1]})`">
        <polygon points="0,0 60,30 0,60" class="body" /><text x="5" y="19" class="pm">−</text><text x="5" y="50" class="pm">+</text>
        <text x="10" y="76" class="lab">运放 GBW {{ val('gbw_mhz', 'MHz') }}</text></g>
      <g v-else-if="e.t === 'CMP'" :transform="`translate(${e.at[0]},${e.at[1]})`">
        <polygon points="0,0 60,30 0,60" class="body" /><text x="8" y="36" class="pm">⎍</text>
        <line x1="-40" y1="30" x2="0" y2="30" class="w" /><text x="4" y="-6" class="lab">比较器</text></g>
      <g v-else-if="e.t === 'NMOS'" :transform="`translate(${e.at[0]},${e.at[1]})`">
        <g class="w"><line x1="-25" y1="0" x2="8" y2="0" /><line x1="8" y1="-18" x2="8" y2="18" />
        <line x1="14" y1="-22" x2="14" y2="22" /><line x1="14" y1="-20" x2="20" y2="-20" /><line x1="14" y1="20" x2="20" y2="20" />
        <line x1="20" y1="-30" x2="20" y2="-20" /><line x1="20" y1="20" x2="20" y2="30" /></g>
        <text x="28" y="4" class="lab">M1（功率 MOSFET）</text></g>
      <g v-else-if="e.t === 'PI'" :transform="`translate(${e.at[0]},${e.at[1]})`">
        <rect :width="e.w" :height="e.h" rx="6" class="body" /><text :x="e.w / 2" :y="e.h / 2 + 5" text-anchor="middle" class="big">{{ e.text }}</text>
        <text :x="0" :y="-6" class="lab">{{ val(e.p, e.unit) }}</text></g>
      <g v-else><g :transform="two(e)">
        <line x1="0" y1="0" :x2="(len(e) - 40) / 2" y2="0" class="w" />
        <line :x1="(len(e) + 40) / 2" y1="0" :x2="len(e)" y2="0" class="w" />
        <g :transform="`translate(${(len(e) - 40) / 2},0)`">
          <rect v-if="e.t === 'R'" x="0" y="-7" width="40" height="14" class="body" />
          <g v-else-if="e.t === 'C'" class="w"><line x1="0" y1="0" x2="16" y2="0" /><line x1="16" y1="-12" x2="16" y2="12" /><line x1="24" y1="-12" x2="24" y2="12" /><line x1="24" y1="0" x2="40" y2="0" /></g>
          <path v-else-if="e.t === 'L'" d="M0,0 a5,5 0 0 1 10,0 a5,5 0 0 1 10,0 a5,5 0 0 1 10,0 a5,5 0 0 1 10,0" class="w" />
          <g v-else-if="e.t === 'V'"><circle cx="20" cy="0" r="16" class="body" /><text x="11" y="5" class="pm">+</text><text x="25" y="5" class="pm">−</text></g>
          <g v-else-if="e.t === 'I'"><circle cx="20" cy="0" r="16" class="body" /><line x1="10" y1="0" x2="30" y2="0" class="w" /><polyline points="24,-5 30,0 24,5" class="w" /></g>
          <g v-else-if="e.t === 'D'" class="w"><polygon points="8,-10 8,10 30,0" class="body" /><line x1="30" y1="-10" x2="30" y2="10" /></g>
          <g v-else-if="e.t === 'SW'" class="w"><circle cx="4" cy="0" r="2.5" /><line x1="6" y1="-1" x2="34" y2="-12" /><circle cx="36" cy="0" r="2.5" /></g>
        </g>
      </g>
        <text :x="lx(e)" :y="ly(e)" :text-anchor="vertical(e) || e.lo ? 'start' : 'middle'" class="lab">{{ e.name }} {{ e.p ? val(e.p, e.unit) : e.v || '' }}</text>
      </g>
    </g>
  </svg>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({ items: { type: Array, required: true }, params: { type: Object, default: () => ({}) } });
const emit = defineEmits(['pick']);
const items = computed(() => props.items);

function len(e) { return Math.hypot(e.b[0] - e.a[0], e.b[1] - e.a[1]); }
function ang(e) { return Math.atan2(e.b[1] - e.a[1], e.b[0] - e.a[0]) * 180 / Math.PI; }
function two(e) { return `translate(${e.a[0]},${e.a[1]}) rotate(${ang(e)})`; }
function vertical(e) { return Math.abs(Math.abs(ang(e)) - 90) < 1; }
// 标签放在屏幕坐标里：横着的元件写在上方，竖着的写在右侧
// e.lo = [dx, dy]：标签相对元件中点的位置（左对齐），挤的地方单独摆
function lx(e) { return (e.a[0] + e.b[0]) / 2 + (e.lo ? e.lo[0] : vertical(e) ? 22 : 0); }
function ly(e) { return (e.a[1] + e.b[1]) / 2 + (e.lo ? e.lo[1] : vertical(e) ? 4 : -14); }
function num(v) {
  if (v == null || v === '') return '';
  const a = Math.abs(v);
  return a >= 1000 ? Math.round(v).toLocaleString() : a >= 10 ? (+v.toFixed(1)).toString() : (+v.toPrecision(3)).toString();
}
function val(k, unit) { return k && props.params[k] != null ? num(props.params[k]) + ' ' + (unit || '') : ''; }
</script>

<style scoped>
.sch { width: 100%; max-width: 640px; height: auto; background: var(--surface-2, #f7f8fa); border-radius: 8px; }
.w { stroke: var(--text, #222); stroke-width: 1.8; fill: none; }
.body { stroke: var(--text, #222); stroke-width: 1.8; fill: var(--surface, #fff); }
.dot { fill: var(--text, #222); }
.lab { font-size: 12px; fill: var(--text, #222); }
.txt { font-size: 12px; fill: var(--muted, #666); }
.node { font-size: 11px; fill: var(--brand, #2563eb); font-family: var(--mono, monospace); }
.pm { font-size: 13px; fill: var(--text, #222); }
.big { font-size: 18px; font-weight: 600; fill: var(--text, #222); }
.pick { cursor: pointer; }
.pick:hover .body, .pick:hover .w { stroke: var(--brand, #2563eb); }
.pick .lab { fill: var(--brand, #2563eb); font-weight: 600; }
</style>
