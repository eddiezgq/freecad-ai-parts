<template>
  <figure class="rc">
    <div class="ctl">
      <span class="small">方案：</span>
      <button v-for="o in OPTS" :key="o.k" class="btn sm" :class="{ primary: plan === o.k }" :aria-pressed="plan === o.k" @click="choose(o.k)">{{ o.k }} {{ o.t }}</button>
      <button class="btn sm" @click="restart">重新追一遍</button>
    </div>
    <svg viewBox="0 0 760 250" role="img" :aria-label="`追溯演示：从投诉的设备追到同一片砂轮磨的 ${UNITS.length} 根轴，方案 ${plan} 上门 ${visited} 台`">
      <!-- 追溯链 -->
      <g v-for="(n, i) in CHAIN" :key="n" :class="['node', { lit: step > i }]">
        <rect :x="18 + i * 122" y="14" width="110" height="40" rx="8" />
        <text :x="73 + i * 122" y="39">{{ n }}</text>
        <line v-if="i < CHAIN.length - 1" :x1="128 + i * 122" y1="34" :x2="140 + i * 122" y2="34" class="edge" />
      </g>
      <!-- 同一片砂轮磨的轴 → 装进的设备 → 客户 -->
      <g v-for="(u, i) in UNITS" :key="u.sn" :class="['unit', { shown: step > CHAIN.length, risk: u.risk, bad: u.bad, go: goes(u) }]"
        :style="{ transitionDelay: (i * 0.08) + 's' }">
        <line :x1="624" y1="54" :x2="ux(i) + 30" y2="100" class="fan" />
        <rect :x="ux(i)" y="100" width="60" height="42" rx="6" />
        <text :x="ux(i) + 30" y="118" class="sn">{{ u.sn }}</text>
        <text :x="ux(i) + 30" y="134" class="hp">{{ u.bad ? '投诉' : u.risk ? '高风险' : '健康' }}</text>
        <text :x="ux(i) + 30" y="162" class="cu">{{ u.cust }}</text>
        <text v-if="goes(u)" :x="ux(i) + 30" y="186" class="van">🔧 上门</text>
      </g>
      <text x="380" y="226" class="sum">{{ summary }}</text>
    </svg>
    <figcaption class="small muted">示例。投诉的设备有序列号，就能一路追到出厂数据：它的输出轴是哪一片砂轮磨的，同一片砂轮还磨了哪些轴、装进了哪些客户的设备——这就是<b>排查范围</b>。
      再选方案：A 只修投诉的那台；B 加上范围里的高风险设备；C 范围里全部上门。</figcaption>
  </figure>
</template>

<script setup>
// 投诉追溯与召回范围（第 30 轮 §八 8-2，客户与服务）：追溯链一环环亮，同批的设备摊开，选 A/B/C 看上门哪几台。
import { computed, onMounted, onUnmounted, ref } from 'vue';

const CHAIN = ['投诉的设备', '出厂总成', '输出轴', '磨它的砂轮', '同一片砂轮'];
const UNITS = [
  { sn: 'U-0312', cust: '港口客户', bad: true },
  { sn: 'U-0315', cust: '港口客户', risk: true },
  { sn: 'U-0318', cust: '汽配厂' },
  { sn: 'U-0321', cust: '汽配厂', risk: true },
  { sn: 'U-0324', cust: '机器人厂' },
  { sn: 'U-0327', cust: '机器人厂' },
  { sn: 'U-0330', cust: '物流公司', risk: true },
  { sn: 'U-0333', cust: '物流公司' },
  { sn: 'U-0336', cust: '机器人厂' },
];
const OPTS = [{ k: 'A', t: '只修投诉的' }, { k: 'B', t: '修 + 高风险点检' }, { k: 'C', t: '整批排查' }];
const step = ref(0);
const plan = ref('B');
const ux = (i) => 18 + i * 82;
const goes = (u) => step.value > CHAIN.length && (u.bad || (plan.value !== 'A' && (u.risk || plan.value === 'C')));
const visited = computed(() => UNITS.filter(goes).length);
const summary = computed(() => {
  if (step.value <= CHAIN.length) return '沿着出厂数据往回追……';
  const custs = new Set(UNITS.filter(goes).map((u) => u.cust)).size;
  const missed = UNITS.filter((u) => u.risk && !goes(u)).length;
  return `方案 ${plan.value}：上门 ${visited.value} 台，涉及 ${custs} 个客户` + (missed ? `，漏掉 ${missed} 台高风险设备` : '，不漏高风险设备');
});
let timer;
function restart() {
  clearInterval(timer);
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { step.value = CHAIN.length + 1; return; }
  step.value = 0;
  timer = setInterval(() => { if (step.value <= CHAIN.length) step.value += 1; else clearInterval(timer); }, 900);
}
function choose(k) { plan.value = k; if (step.value <= CHAIN.length) step.value = CHAIN.length + 1; }
onMounted(restart);
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.rc { margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); }
.ctl { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
svg { width: 100%; height: auto; display: block; }
.node rect { fill: var(--surface-2); stroke: var(--line); stroke-width: 2; transition: all 0.4s; }
.node text { text-anchor: middle; font-size: 15px; fill: var(--muted); transition: fill 0.4s; }
.node.lit rect { fill: var(--warn-bg); stroke: var(--warn); }
.node.lit text { fill: var(--ink); font-weight: 600; }
.node:first-child.lit rect { fill: var(--bad-bg); stroke: var(--bad); }
.edge { stroke: var(--line); stroke-width: 3; }
.unit { opacity: 0; transition: opacity 0.5s; }
.unit.shown { opacity: 1; }
.unit rect { fill: var(--good-bg); stroke: var(--good); stroke-width: 2; }
.unit.risk rect { fill: var(--warn-bg); stroke: var(--warn); }
.unit.bad rect { fill: var(--bad-bg); stroke: var(--bad); }
.unit.go rect { stroke-width: 4; }
.fan { stroke: var(--line); stroke-width: 1.5; stroke-dasharray: 3 3; }
.sn { text-anchor: middle; font-size: 13px; font-weight: 600; fill: var(--ink); }
.hp { text-anchor: middle; font-size: 12px; fill: var(--muted); }
.cu { text-anchor: middle; font-size: 12px; fill: var(--muted); }
.van { text-anchor: middle; font-size: 13px; fill: var(--accent); font-weight: 600; }
.sum { text-anchor: middle; font-size: 16px; fill: var(--ink); font-weight: 600; }
figcaption { margin-top: 6px; line-height: 1.7; }
@media (prefers-reduced-motion: reduce) { .node rect, .node text, .unit { transition: none; } }
</style>
