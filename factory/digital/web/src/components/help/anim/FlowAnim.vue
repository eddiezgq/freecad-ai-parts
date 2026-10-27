<template>
  <figure class="flow" :class="{ dark }">
    <svg viewBox="0 0 1000 150" role="img" :aria-label="'全流程：' + STAGES.map((s) => s.name).join('、')">
      <line x1="40" y1="62" x2="960" y2="62" class="rail" />
      <line x1="40" y1="62" x2="960" y2="62" class="belt" :class="{ still: reduced }" />
      <g v-for="(s, i) in STAGES" :key="s.name" class="st" :class="{ on: i === cur, can: clickable }" tabindex="0" role="button"
        :aria-label="s.name + '：' + s.doc" @click="pick(i)" @keydown.enter="pick(i)">
        <circle :cx="x(i)" cy="62" r="17" />
        <text :x="x(i)" y="67" class="n">{{ i + 1 }}</text>
        <text :x="x(i)" y="112" class="nm">{{ s.name }}</text>
        <text :x="x(i)" y="132" class="sub">{{ s.role }}</text>
      </g>
      <g class="tok" :style="{ transform: `translate(${tokX}px, 0)` }">
        <rect x="-62" y="10" width="124" height="28" rx="6" />
        <text x="0" y="29">{{ STAGES[cur].doc }}</text>
      </g>
    </svg>
    <figcaption v-if="caption" class="small">{{ caption }}</figcaption>
  </figure>
</template>

<script setup>
// 全流程动画（ADR-0065）：一张单据沿着“设计 → ERP → MRP → MES → 车间 → 质量 → 厂情中枢”走，到哪一站换成那一站的单据。
// 点站点跳到对应章节；减少动态效果时不自动走。
import { onMounted, onUnmounted, ref } from 'vue';

const props = defineProps({ dark: Boolean, clickable: Boolean, caption: String });
const emit = defineEmits(['pick']);
const STAGES = [
  { name: '设计', role: '工程师 · 设计台', doc: '设计 第 1 版' },
  { name: 'ERP', role: '物料与 BOM', doc: '物料 · BOM' },
  { name: 'MRP', role: '计划员', doc: '订单 → 工单' },
  { name: 'MES', role: '派工', doc: '派工单' },
  { name: '车间', role: '操作工 · 设备', doc: '加工中 3/10' },
  { name: '质量', role: '质检员', doc: '检验记录' },
  { name: '厂情中枢', role: '厂长 · AI', doc: '日报 · 异常' },
];
const x = (i) => 70 + i * (860 / (STAGES.length - 1));
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const cur = ref(0);
const tokX = ref(x(0));
let raf, t0;

function frame(t) {
  raf = requestAnimationFrame(frame);
  if (!t0) t0 = t;
  const per = 2200;                       // 每站 2.2 秒：走 0.9 秒，停 1.3 秒
  const k = ((t - t0) / per) % STAGES.length;
  const i = Math.floor(k);
  const f = Math.min(1, (k - i) / 0.4);
  const ease = f < 0.5 ? 2 * f * f : 1 - (-2 * f + 2) ** 2 / 2;
  const nxt = (i + 1) % STAGES.length;
  if (f >= 1 || nxt === 0) { cur.value = i; tokX.value = x(i); return; }
  cur.value = ease > 0.5 ? nxt : i;
  tokX.value = x(i) + (x(nxt) - x(i)) * ease;
}
function pick(i) { cur.value = i; tokX.value = x(i); if (props.clickable) emit('pick', i); }
onMounted(() => { if (!reduced) raf = requestAnimationFrame(frame); });
onUnmounted(() => cancelAnimationFrame(raf));
</script>

<style scoped>
.flow { margin: 0; }
svg { width: 100%; height: auto; display: block; }
.rail { stroke: var(--line); stroke-width: 10; stroke-linecap: round; }
.belt { stroke: var(--idle); stroke-width: 2; stroke-dasharray: 2 14; animation: belt 0.9s linear infinite; }
.belt.still { animation: none; }
@keyframes belt { to { stroke-dashoffset: -16; } }
.st circle { fill: var(--surface); stroke: var(--idle); stroke-width: 2; transition: fill 0.3s, stroke 0.3s; }
.st .n { text-anchor: middle; font-size: 14px; font-weight: 600; fill: var(--muted); }
.st .nm { text-anchor: middle; font-size: 17px; font-weight: 600; fill: var(--ink); }
.st .sub { text-anchor: middle; font-size: 12px; fill: var(--muted); }
.st.on circle { fill: var(--brand); stroke: var(--brand); }
.st.on .n { fill: var(--ink); }
.st.can { cursor: pointer; }
.st:focus-visible circle { stroke: var(--accent); stroke-width: 4; }
.tok rect { fill: var(--ink); }
.tok text { text-anchor: middle; font-size: 13px; fill: #fff; font-weight: 600; }
.dark .rail { stroke: #34485A; }
.dark .belt { stroke: #8795A1; }
.dark .st circle { fill: #22303C; stroke: #8795A1; }
.dark .st .nm { fill: #F4F6F3; }
.dark .st .sub, .dark .st .n { fill: #A9B5BF; }
.dark .st.on circle { fill: var(--brand); stroke: var(--brand); }
.dark .st.on .n { fill: #17212B; }
.dark .tok rect { fill: var(--brand); }
.dark .tok text { fill: #17212B; }
figcaption { color: var(--muted); margin-top: 4px; }
</style>
