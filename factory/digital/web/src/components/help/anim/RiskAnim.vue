<template>
  <figure class="rk">
    <div class="wrap">
      <svg viewBox="0 0 300 300" role="img" :aria-label="`风险矩阵：${STEPS[at].t}，可能性 ${pos.l}、严重度 ${pos.s}`">
        <g v-for="l in 5" :key="'l' + l">
          <rect v-for="s in 5" :key="s" :x="40 + (s - 1) * 50" :y="10 + (5 - l) * 50" width="48" height="48" rx="4" :class="zone(l, s)" />
        </g>
        <text x="165" y="285" class="ax">严重度 →</text>
        <text x="16" y="135" class="ax" transform="rotate(-90 16 135)">可能性 →</text>
        <circle :cx="65 + (pos.s - 1) * 50" :cy="35 + (5 - pos.l) * 50" r="14" class="dot" />
        <text :x="65 + (pos.s - 1) * 50" :y="40 + (5 - pos.l) * 50" class="dt">!</text>
      </svg>
      <ol class="steps">
        <li v-for="(s, i) in STEPS" :key="i" :class="{ now: i === at, past: i < at }">
          <button type="button" @click="go(i)"><b>{{ s.t }}</b><span class="small">{{ s.say }}</span></button>
        </li>
      </ol>
    </div>
    <figcaption class="small muted">示例：磨床防护门联锁被短接。风险 = 可能性 × 严重度，落在红区是<b>重大隐患</b>，要先停机挂牌上锁再整改；
      加防护、修好联锁让可能性降下来，验收由另一个人做，验收时解锁。点右边任一步看点子落在哪。</figcaption>
  </figure>
</template>

<script setup>
// 风险矩阵 + 挂牌上锁（第 30 轮 §八 8-2，安全环保）：隐患点子落在红区 → 停机、上锁、整改、验收解锁，点子落回绿区。
import { computed, onMounted, onUnmounted, ref } from 'vue';

const STEPS = [
  { t: '发现隐患', say: '联锁被短接，开着门也能转', l: 4, s: 5 },
  { t: '评估：重大', say: '红区，1 天内整改，先停机', l: 4, s: 5 },
  { t: '停机、断电', say: '按停止，断开电源', l: 2, s: 5 },
  { t: '挂牌上锁', say: '锁上电源，挂上自己的牌', l: 1, s: 5 },
  { t: '整改', say: '修好联锁，加护栏', l: 1, s: 5 },
  { t: '验收解锁', say: '另一个人验收、解锁，恢复生产', l: 1, s: 3 },
];
const at = ref(0);
const pos = computed(() => STEPS[at.value]);
function zone(l, s) { const r = l * s; return r >= 15 ? 'z-red' : r >= 8 ? 'z-amb' : 'z-grn'; }
let timer;
function go(i) { at.value = i; clearInterval(timer); }
onMounted(() => {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { at.value = STEPS.length - 1; return; }
  timer = setInterval(() => { at.value = (at.value + 1) % STEPS.length; }, 2200);
});
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.rk { margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); }
.wrap { display: grid; grid-template-columns: minmax(180px, 300px) 1fr; gap: 16px; align-items: center; }
@media (max-width: 560px) { .wrap { grid-template-columns: 1fr; } }
svg { width: 100%; height: auto; display: block; }
.z-red { fill: var(--bad-bg); stroke: var(--bad); }
.z-amb { fill: var(--warn-bg); stroke: var(--warn); }
.z-grn { fill: var(--good-bg); stroke: var(--good); }
.ax { font-size: 13px; fill: var(--muted); text-anchor: middle; }
.dot { fill: var(--ink); transition: cx 0.6s, cy 0.6s; }
.dt { fill: var(--surface); font-size: 16px; font-weight: 700; text-anchor: middle; transition: x 0.6s, y 0.6s; }
.steps { list-style: none; padding: 0; margin: 0; display: grid; gap: 4px; }
.steps button { width: 100%; text-align: left; display: flex; gap: 10px; align-items: baseline; padding: 6px 10px; border-radius: 6px; cursor: pointer;
  background: var(--surface-2); border: 1px solid var(--line); color: var(--muted); font-size: 14px; }
.steps .past button { color: var(--ink); }
.steps .now button { border-color: var(--accent); background: var(--accent-bg); color: var(--ink); }
.steps button:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
figcaption { margin-top: 8px; line-height: 1.7; }
@media (prefers-reduced-motion: reduce) { .dot, .dt { transition: none; } }
</style>
