<template>
  <figure class="bt">
    <div class="ctl">
      <span class="small muted">从下往上做：</span>
      <button v-for="(l, i) in LEVELS" :key="l" class="btn sm" :class="{ primary: step === i }" @click="go(i)">{{ i + 1 }}. {{ l }}</button>
      <button class="btn sm" @click="replay">从头演示</button>
    </div>
    <div class="tree" role="tree" aria-label="协作机器人 WQ-CR5 的多层物料清单（简化）">
      <div v-for="row in ROWS" :key="row.code" role="treeitem" class="node" :style="{ marginLeft: row.depth * 22 + 'px' }"
           :class="[row.kind, { done: doneOf(row), now: nowOf(row) }]">
        <span class="tag">{{ KIND[row.kind] }}</span>
        <b>{{ row.name }}</b>
        <span class="small muted">{{ row.code }}{{ row.qty ? ' × ' + row.qty : '' }}</span>
        <span v-if="nowOf(row)" class="state">正在做</span>
        <span v-else-if="doneOf(row)" class="state ok">已入库</span>
      </div>
    </div>
    <figcaption class="small muted">示例：本厂清单里 WQ-CR5 的物料清单，省略了编码器、驱动板、轴承、螺钉、线缆。外购件、原材料在库里；
      自制件（壳体、空心轴）先做，再装关节模组、臂管和底座，最后整机装配——下一层没入库，上一层的工单开工了也领不到料。</figcaption>
  </figure>
</template>

<script setup>
// 多层物料清单（第 45 轮机器人厂）：成品 → 关节模组 → 壳体、空心轴，按层从下往上下达工单
import { onMounted, onUnmounted, ref } from 'vue';

const KIND = { fg: '成品', sub: '部件', make: '自制件', buy: '外购件', raw: '原材料' };
const LEVELS = ['自制件：壳体、空心轴、臂管、底座', '部件：三种关节模组', '成品：整机装配、标定、跑合'];
const ROWS = [
  { code: 'WQ-CR5', name: '六轴协作机器人', kind: 'fg', depth: 0, level: 2 },
  { code: 'WQJ-L', name: '大关节模组', kind: 'sub', depth: 1, qty: 2, level: 1 },
  { code: 'JH-L', name: '关节壳体（大）', kind: 'make', depth: 2, qty: 1, level: 0 },
  { code: 'JS-L', name: '空心轴（大）', kind: 'make', depth: 2, qty: 1, level: 0 },
  { code: 'HD-CSF-32-100', name: '谐波减速器', kind: 'buy', depth: 2, qty: 1 },
  { code: 'MTR-SV-400', name: '伺服电机（型号待确认）', kind: 'buy', depth: 2, qty: 1 },
  { code: 'WQJ-M', name: '中关节模组', kind: 'sub', depth: 1, qty: 1, level: 1 },
  { code: 'WQJ-S', name: '小关节模组', kind: 'sub', depth: 1, qty: 3, level: 1 },
  { code: 'ARM-UP', name: '大臂', kind: 'make', depth: 1, qty: 1, level: 0 },
  { code: 'ARM-FO', name: '小臂', kind: 'make', depth: 1, qty: 1, level: 0 },
  { code: 'BASE-CR5', name: '底座', kind: 'make', depth: 1, qty: 1, level: 0 },
  { code: 'CTRL-CAB', name: '控制柜（型号待确认）', kind: 'buy', depth: 1, qty: 1 },
];
const step = ref(2);
const finished = ref(3);
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
let timer;

const doneOf = (r) => r.level === undefined || r.level < finished.value;
const nowOf = (r) => r.level !== undefined && r.level === step.value && finished.value <= r.level;

function go(i) {
  clearInterval(timer);
  step.value = i;
  finished.value = i;
}
function replay() {
  clearInterval(timer);
  if (reduced) { step.value = 2; finished.value = 3; return; }
  step.value = 0;
  finished.value = 0;
  timer = setInterval(() => {
    if (finished.value === step.value) { finished.value += 1; return; }
    if (step.value >= 2) { clearInterval(timer); return; }
    step.value += 1;
  }, 1100);
}
onMounted(replay);
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.bt { margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); }
.ctl { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.tree { display: flex; flex-direction: column; gap: 4px; }
.node { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 5px 10px; border-radius: 8px; background: var(--surface-2);
  border-left: 4px solid var(--line); transition: background 0.3s, border-color 0.3s; font-size: 14px; }
.node.done { border-left-color: var(--good); }
.node.now { border-left-color: var(--accent); background: var(--accent-bg); }
.tag { font-size: 11px; font-weight: 700; padding: 1px 7px; border-radius: 999px; background: var(--line); color: var(--ink); }
.node.fg .tag { background: var(--brand); }
.node.buy .tag, .node.raw .tag { background: var(--warn-bg); color: var(--warn-ink); }
.state { margin-left: auto; font-size: 12px; font-weight: 600; color: var(--accent); }
.state.ok { color: var(--good); }
figcaption { margin-top: 8px; }
</style>
