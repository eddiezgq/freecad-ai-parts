<template>
  <figure class="en">
    <div class="ctl">
      <label class="small"><input v-model="standby" type="checkbox"> 机加设备空闲 10 分钟自动待机</label>
      <label class="small"><input v-model="shift" type="checkbox"> 热处理错峰（峰后再开炉）</label>
    </div>
    <svg viewBox="0 0 760 230" role="img" :aria-label="`一天的用电：${tot.kwh} kWh，电费 $${tot.cost}，峰时占 ${tot.peakPct}%，空转 ${tot.idle} kWh`">
      <rect v-for="(b, h) in BANDS" :key="'b' + h" :x="x(h)" y="10" :width="W" height="170" :class="'bg-' + b" />
      <g v-for="(v, h) in hours" :key="h" :class="{ fut: h > now }">
        <rect :x="x(h) + 2" :y="y(v.run)" :width="W - 4" :height="180 - y(v.run)" class="run" />
        <rect :x="x(h) + 2" :y="y(v.run + v.ht)" :width="W - 4" :height="y(v.run) - y(v.run + v.ht)" class="ht" />
        <rect :x="x(h) + 2" :y="y(v.run + v.ht + v.idle)" :width="W - 4" :height="y(v.run + v.ht) - y(v.run + v.ht + v.idle)" class="idle" />
      </g>
      <line :x1="x(now) + W" y1="10" :x2="x(now) + W" y2="180" class="cur" />
      <text v-for="h in [0, 8, 11, 18, 21, 23]" :key="'t' + h" :x="x(h)" y="198" class="tk">{{ h }}:00</text>
      <g class="lg">
        <rect x="40" y="210" width="12" height="12" class="run" /><text x="58" y="221">在干活</text>
        <rect x="120" y="210" width="12" height="12" class="ht" /><text x="138" y="221">热处理炉</text>
        <rect x="216" y="210" width="12" height="12" class="idle" /><text x="234" y="221">空转（开着没活）</text>
        <rect x="370" y="210" width="12" height="12" class="bg-peak sw" /><text x="388" y="221">峰 $0.15</text>
        <rect x="462" y="210" width="12" height="12" class="bg-flat sw" /><text x="480" y="221">平 $0.10</text>
        <rect x="554" y="210" width="12" height="12" class="bg-valley sw" /><text x="572" y="221">谷 $0.05 / kWh</text>
      </g>
    </svg>
    <dl class="nums">
      <div><dt>电量</dt><dd>{{ tot.kwh }} kWh</dd></div>
      <div><dt>电费</dt><dd>${{ tot.cost }}</dd></div>
      <div><dt>峰时占比</dt><dd>{{ tot.peakPct }}%</dd></div>
      <div><dt>空转</dt><dd>{{ tot.idle }} kWh</dd></div>
      <div><dt>碳排放</dt><dd>{{ tot.co2 }} kg</dd></div>
    </dl>
    <figcaption class="small muted">示例：一个车间一天的用电，电价和排放因子用本厂的缺省参数。灰色是机床开着没活；
      勾上“自动待机”灰色变少，<b>电、钱、碳一起省</b>；勾上“错峰”，橙色的炉子挪出峰时段，<b>只省钱</b>，电量和碳不变。</figcaption>
  </figure>
</template>

<script setup>
// 一天的用电曲线：空转与错峰（第 30 轮 §八 8-2，能源与环境）。电价、峰谷时段、排放因子取 hub/energy.py、sim/energy.py 的缺省值。
import { computed, onMounted, onUnmounted, ref } from 'vue';

const PRICE = { peak: 0.15, flat: 0.10, valley: 0.05 };
const CO2 = 0.5306;
const PEAK = [[8, 11], [18, 21]];
const VALLEY = [[23, 24], [0, 7]];
const band = (h) => (PEAK.some(([a, b]) => a <= h && h < b) ? 'peak' : VALLEY.some(([a, b]) => a <= h && h < b) ? 'valley' : 'flat');
const BANDS = Array.from({ length: 24 }, (_, h) => band(h));
const W = 28;
const x = (h) => 40 + h * W;
const y = (kw) => 180 - kw * 1.2;

const standby = ref(false);
const shift = ref(false);
const now = ref(23);
const hours = computed(() => Array.from({ length: 24 }, (_, h) => {
  const work = h >= 8 && h < 23;                              // 两班：8:00–23:00
  const run = work ? (h === 12 || h === 17 ? 55 : 80) : 0;     // 午饭、交班时活少
  const idle0 = work ? (h === 12 || h === 17 ? 40 : 18) : (h < 7 ? 12 : 6);   // 夜里有台忘关
  const idle = standby.value ? Math.round(idle0 * 0.3) : idle0;
  const htOn = shift.value ? (h >= 11 && h < 14) : (h >= 8 && h < 11);
  return { run, idle, ht: htOn ? 40 : 6 };                     // 炉子不开时保温
}));
const tot = computed(() => {
  let kwh = 0, cost = 0, pk = 0, idle = 0;
  hours.value.forEach((v, h) => { const e = v.run + v.idle + v.ht; kwh += e; cost += e * PRICE[BANDS[h]]; if (BANDS[h] === 'peak') pk += e; idle += v.idle; });
  return { kwh: Math.round(kwh), cost: cost.toFixed(2), peakPct: Math.round((pk / kwh) * 100), idle: Math.round(idle), co2: Math.round(kwh * CO2) };
});
let timer;
onMounted(() => {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  now.value = -1;
  timer = setInterval(() => { now.value = now.value >= 26 ? -1 : now.value + 1; }, 260);
});
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.en { margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); }
.ctl { display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 6px; }
svg { width: 100%; height: auto; display: block; }
.bg-peak { fill: var(--bad-bg); }
.bg-flat { fill: var(--warn-bg); opacity: 0.5; }
.bg-valley { fill: var(--accent-bg); }
.sw { stroke: var(--line); }
.run { fill: var(--accent); }
.ht { fill: var(--warn); }
.idle { fill: var(--idle); }
.fut rect { opacity: 0.22; }
rect { transition: y 0.4s, height 0.4s, opacity 0.2s; }
.cur { stroke: var(--ink); stroke-width: 1.5; stroke-dasharray: 3 3; }
.tk { font-size: 12px; fill: var(--muted); text-anchor: middle; }
.lg text { font-size: 12px; fill: var(--muted); }
.nums { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin: 8px 0 0; }
.nums div { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.nums dt { font-size: 12px; color: var(--muted); }
.nums dd { margin: 0; font-weight: 700; font-size: 16px; }
@media (max-width: 560px) { .nums { grid-template-columns: repeat(3, 1fr); } }
figcaption { margin-top: 8px; line-height: 1.7; }
@media (prefers-reduced-motion: reduce) { rect { transition: none; } }
</style>
