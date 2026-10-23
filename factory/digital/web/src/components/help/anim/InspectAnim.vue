<template>
  <figure class="ins">
    <div class="ctl">
      <label class="small"><input v-model="cheap" type="checkbox" @change="restart"> 改从便宜的供应商进货</label>
      <span class="small muted">到货 {{ arrived }} 批 · 合格入库 {{ ok }} · 不合格隔离 {{ ng }}</span>
    </div>
    <svg viewBox="0 0 760 210" role="img" :aria-label="`来料检验演示：到货 ${arrived} 批，合格 ${ok}，不合格 ${ng}`">
      <line x1="20" y1="70" x2="470" y2="70" class="belt" />
      <text x="70" y="26" class="lb">供应商{{ cheap ? '（便宜）' : '' }}</text>
      <rect x="250" y="34" width="120" height="72" rx="8" class="station" />
      <text x="310" y="26" class="lb">来料检验 · 抽 5 件</text>
      <!-- 抽样的 5 件：量值对上下限 -->
      <g class="meas">
        <rect x="226" y="120" width="168" height="80" rx="6" />
        <text x="232" y="138" class="lim-t">上限</text><text x="232" y="194" class="lim-t">下限</text>
        <line x1="262" y1="142" x2="388" y2="142" class="lim" /><line x1="262" y1="178" x2="388" y2="178" class="lim" />
        <template v-if="cur">
          <circle v-for="(v, k) in cur.sample.slice(0, shown)" :key="k" :cx="282 + k * 23" :cy="160 - v * 18" r="5" :class="Math.abs(v) > 1 ? 'out' : 'in'" />
        </template>
      </g>
      <!-- 在路上的批 -->
      <g v-for="b in moving" :key="b.id" :transform="`translate(${b.x},${b.y})`">
        <rect x="-18" y="-14" width="36" height="28" rx="4" :class="['box', b.state]" />
        <text y="5" class="bid">{{ b.id }}</text>
      </g>
      <!-- 去处 -->
      <rect x="560" y="18" width="180" height="70" rx="8" class="good" /><text x="650" y="48" class="dst">合格 → 入库</text>
      <text x="650" y="72" class="cnt">{{ ok }} 批</text>
      <rect x="560" y="116" width="180" height="70" rx="8" class="bad" /><text x="650" y="146" class="dst">不合格 → 隔离</text>
      <text x="650" y="170" class="cnt">{{ ng }} 批 · 装配等料</text>
    </svg>
    <figcaption class="small muted">示例。每次到货是一个批次，抽 5 件量尺寸，对照上下限（两条线）：全在线内判合格入库，有一件出线就判不合格隔离，等退货、换供应商或让步接收。
      勾上“便宜的供应商”看：单价低，但不合格的批多了，装配要等料——这就是要算<b>总拥有成本</b>的原因。</figcaption>
  </figure>
</template>

<script setup>
// 来料一批批流过抽样检验（第 30 轮 §八 8-2，采购与来料）：合格的去入库，不合格的去隔离。
import { computed, onMounted, onUnmounted, ref } from 'vue';

const cheap = ref(false);
const batches = ref([]);
const shown = ref(0);
const ok = computed(() => batches.value.filter((b) => b.state === 'pass' && b.x >= 600).length);
const ng = computed(() => batches.value.filter((b) => b.state === 'fail' && b.x >= 600).length);
const arrived = computed(() => batches.value.filter((b) => b.x >= 250).length);
const cur = computed(() => batches.value.find((b) => b.state === 'check'));
const moving = computed(() => batches.value.filter((b) => b.x < 640));
let raf, last, n, seed, holdUntil;
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

function rnd() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }
function sample(badRate) {
  const bad = rnd() < badRate;
  return Array.from({ length: 5 }, (_, k) => (bad && k === 2 + Math.floor(rnd() * 3) ? 1.25 + rnd() * 0.3 : (rnd() - 0.5) * 1.5) * (rnd() < 0.5 ? -1 : 1));
}
function addBatch() {
  n += 1;
  batches.value.push({ id: (cheap.value ? 'C' : 'B') + String(n).padStart(2, '0'), x: -20, y: 70, state: 'new', sample: sample(cheap.value ? 0.45 : 0.1) });
}
function tick(dt, ts) {
  for (const b of batches.value) {
    if (b.state === 'new') { b.x += dt * 140; if (b.x >= 310 && !cur.value) { b.x = 310; b.state = 'check'; shown.value = 0; holdUntil = ts + 1600; } else if (b.x >= 220 && cur.value) b.x = Math.min(b.x, 220); }
    else if (b.state === 'check') { shown.value = Math.min(5, Math.floor((1600 - (holdUntil - ts)) / 280) + 1); if (ts >= holdUntil) b.state = b.sample.some((v) => Math.abs(v) > 1) ? 'fail' : 'pass'; }
    else { b.x += dt * 160; b.y += (b.state === 'pass' ? 54 - b.y : 150 - b.y) * Math.min(1, dt * 4); }
  }
  // 后面的批不能叠在一起
  const q = batches.value.filter((b) => b.state === 'new').sort((a, b) => b.x - a.x);
  for (let i = 1; i < q.length; i++) q[i].x = Math.min(q[i].x, q[i - 1].x - 44);
}
function frame(ts) {
  raf = requestAnimationFrame(frame);
  const dt = Math.min(0.1, last ? (ts - last) / 1000 : 0);
  last = ts;
  if (batches.value.filter((b) => b.x < 250).length < 2 && n < 12) addBatch();
  tick(dt, ts);
  if (n >= 12 && batches.value.every((b) => b.x >= 640)) restart();
}
function restart() {
  batches.value = []; n = 0; seed = cheap.value ? 7 : 11; shown.value = 0;
  if (reduced) { for (let i = 0; i < 12; i++) { addBatch(); const b = batches.value[i]; b.state = b.sample.some((v) => Math.abs(v) > 1) ? 'fail' : 'pass'; b.x = 700; } }
}
onMounted(() => { restart(); if (!reduced) raf = requestAnimationFrame(frame); });
onUnmounted(() => cancelAnimationFrame(raf));
</script>

<style scoped>
.ins { margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); }
.ctl { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 6px; }
svg { width: 100%; height: auto; display: block; }
.belt { stroke: var(--line); stroke-width: 8; stroke-linecap: round; }
.station { fill: var(--surface-2); stroke: var(--accent); stroke-width: 2; }
.meas rect { fill: var(--surface-2); stroke: var(--line); }
.lim-t { font-size: 11px; fill: var(--muted); }
.lim { stroke: var(--bad); stroke-width: 1.5; stroke-dasharray: 4 3; }
circle.in { fill: var(--good); }
circle.out { fill: var(--bad); }
.box { fill: var(--surface-2); stroke: var(--idle); stroke-width: 2; }
.box.check { stroke: var(--accent); }
.box.pass { fill: var(--good-bg); stroke: var(--good); }
.box.fail { fill: var(--bad-bg); stroke: var(--bad); }
.bid { text-anchor: middle; font-size: 11px; fill: var(--ink); }
.lb { text-anchor: middle; font-size: 14px; fill: var(--muted); }
.good { fill: var(--good-bg); stroke: var(--good); stroke-width: 2; }
.bad { fill: var(--bad-bg); stroke: var(--bad); stroke-width: 2; }
.dst { text-anchor: middle; font-size: 15px; font-weight: 600; fill: var(--ink); }
.cnt { text-anchor: middle; font-size: 13px; fill: var(--muted); }
figcaption { margin-top: 6px; line-height: 1.7; }
</style>
