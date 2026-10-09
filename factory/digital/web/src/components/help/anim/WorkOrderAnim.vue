<template>
  <figure class="wo">
    <div class="ctl">
      <label class="small"><input v-model="twin" type="checkbox" @change="restart"> 粗车加一台车床</label>
      <button class="btn sm" @click="restart">重新开始</button>
      <span class="small muted">工单 10 件 · 工厂时间 {{ Math.round(t) }} 分钟 · 完工 {{ done }} / 10</span>
    </div>
    <svg viewBox="0 0 760 196" role="img" :aria-label="`工单流转演示：完工 ${done} 件，粗车前排队最多 ${maxQ} 件`">
      <line x1="20" y1="104" x2="740" y2="104" class="belt" />
      <g v-for="(s, i) in st" :key="s.name">
        <g v-for="(p, k) in s.queue.slice(0, 8)" :key="'q' + p" class="qpart">
          <circle :cx="sx(i) - 64 + (k % 4) * 12" :cy="96 - Math.floor(k / 4) * 12 + 8" r="5" />
        </g>
        <text v-if="s.queue.length > 8" :x="sx(i) - 46" y="70" class="more">+{{ s.queue.length - 8 }}</text>
        <rect v-for="(m, j) in s.slots" :key="j" :x="sx(i) - 24" :y="74 + j * 0 - (s.slots.length > 1 ? 22 - j * 44 : 0)" width="64" height="40" rx="6"
          class="mach" :class="{ busy: m.part !== null, bott: s.name === '粗车' }" />
        <template v-for="(m, j) in s.slots" :key="'p' + j">
          <circle v-if="m.part !== null" :cx="sx(i) + 8" :cy="94 - (s.slots.length > 1 ? 22 - j * 44 : 0)" r="7" class="part" />
          <rect v-if="m.part !== null" :x="sx(i) - 18" :y="108 - (s.slots.length > 1 ? 22 - j * 44 : 0)" :width="52 * (1 - m.left / s.cycle)" height="3" class="prog" />
        </template>
        <text :x="sx(i) + 8" y="166" class="nm">{{ s.name }}</text>
        <text :x="sx(i) + 8" y="188" class="sub">{{ s.cycle }} 分/件{{ s.slots.length > 1 ? ' × 2 台' : '' }}</text>
      </g>
      <g class="bin">
        <rect x="676" y="70" width="70" height="56" rx="8" />
        <text x="711" y="98" class="bn">{{ done }}</text>
        <text x="711" y="118" class="sub">完工</text>
      </g>
    </svg>
    <figcaption class="small muted">示例：四道工序、每件依次流过。粗车最慢，零件在它前面排队，它就是<b>瓶颈</b>；给粗车加一台，排队消失，整批完工时间缩短（{{ twin ? '现在是两台' : '勾上“粗车加一台车床”试试' }}）。</figcaption>
  </figure>
</template>

<script setup>
// 工单在设备间流转（ADR-0065）：一张 10 件的工单依次走四道工序，看排队、瓶颈；可以给瓶颈加一台设备对比。
import { computed, onMounted, onUnmounted, ref } from 'vue';

const STEPS = [{ name: '下料', cycle: 2 }, { name: '粗车', cycle: 6 }, { name: '精车', cycle: 4 }, { name: '检验', cycle: 2 }];
const twin = ref(false);
const st = ref([]);
const t = ref(0);
const done = ref(0);
const maxQ = ref(0);
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const sx = (i) => 92 + i * 150;
let raf, last;

function reset() {
  st.value = STEPS.map((s, i) => ({ ...s, queue: i === 0 ? [...Array(10).keys()] : [],
    slots: Array.from({ length: s.name === '粗车' && twin.value ? 2 : 1 }, () => ({ part: null, left: 0 })) }));
  t.value = 0; done.value = 0; maxQ.value = 0;
}
function step(dt) {
  const S = st.value;
  for (let i = S.length - 1; i >= 0; i--) {
    for (const m of S[i].slots) {
      if (m.part !== null) {
        m.left -= dt;
        if (m.left <= 0) { if (i + 1 < S.length) S[i + 1].queue.push(m.part); else done.value += 1; m.part = null; }
      }
      if (m.part === null && S[i].queue.length) { m.part = S[i].queue.shift(); m.left = S[i].cycle; }
    }
  }
  maxQ.value = Math.max(maxQ.value, S[1].queue.length);
  t.value += dt;
}
const finished = computed(() => done.value >= 10);
function frame(ts) {
  raf = requestAnimationFrame(frame);
  if (!last) last = ts;
  const dt = Math.min(0.2, (ts - last) / 1000) * 4;     // 1 秒真实时间 = 4 分钟工厂时间
  last = ts;
  if (!finished.value) step(dt); else if (t.value > 0 && ts - (frame.doneAt || (frame.doneAt = ts)) > 2500) { frame.doneAt = 0; reset(); }
}
function restart() {
  reset();
  if (reduced) { while (!finished.value && t.value < 500) step(0.1); }
}
onMounted(() => { restart(); if (!reduced) raf = requestAnimationFrame(frame); });
onUnmounted(() => cancelAnimationFrame(raf));
</script>

<style scoped>
.wo { margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); }
.ctl { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 6px; }
svg { width: 100%; height: auto; display: block; }
.belt { stroke: var(--line); stroke-width: 8; stroke-linecap: round; }
.mach { fill: var(--surface-2); stroke: var(--idle); stroke-width: 2; }
.mach.busy { fill: var(--good-bg); stroke: var(--good); }
.mach.bott { stroke-dasharray: 5 3; }
.part { fill: var(--ink); }
.prog { fill: var(--good); }
.qpart circle { fill: var(--warn); }
.more { font-size: 12px; fill: var(--warn-ink); }
.nm { text-anchor: middle; font-size: 18px; font-weight: 600; fill: var(--ink); }
.sub { text-anchor: middle; font-size: 14px; fill: var(--muted); }
.bin rect { fill: var(--accent-bg); stroke: var(--accent); stroke-width: 2; }
.bn { text-anchor: middle; font-size: 22px; font-weight: 700; fill: var(--accent); }
figcaption { margin-top: 6px; line-height: 1.7; }
</style>
