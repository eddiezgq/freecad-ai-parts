<template>
  <figure class="ad">
    <ol class="lane">
      <li v-for="(s, i) in STEPS" :key="s.who" :class="{ on: i === cur, past: i < cur, stop: rejected && i > 1 }">
        <span class="who small">{{ s.who }}</span>
        <b>{{ rejected && i === 2 ? '你点了“拒绝”' : s.what }}</b>
        <span class="small muted">{{ rejected && i === 2 ? '提议作废，什么都不写' : s.note }}</span>
      </li>
    </ol>
    <div class="ctl">
      <button class="btn sm" @click="play(false)">看“确认”这条路</button>
      <button class="btn sm" @click="play(true)">看“拒绝”这条路</button>
    </div>
    <figcaption class="small muted">AI 工厂助手和厂情中枢都只<b>起草</b>：订单、请购、加班、动作都先成为一条“提议”，写清楚要做什么、依据是什么。只有人点了确认，桥接才把它写进 ERPNext；拒绝就什么也不发生。</figcaption>
  </figure>
</template>

<script setup>
// AI 只起草、由人确认（ADR-0065）：一条提议从起草到写入 ERPNext 的路，以及拒绝的那条路。
import { onMounted, onUnmounted, ref } from 'vue';

const STEPS = [
  { who: '你', what: '“帮我下一张 20 台的订单”', note: '在 AI 工厂助手里说一句话' },
  { who: 'AI 工厂助手', what: '起草一条提议', note: '算好料、列出要建的单据和依据' },
  { who: '你（或有权限的人）', what: '看清楚后点“确认执行”', note: '这是唯一能让它生效的一步' },
  { who: '桥接', what: '按提议写入 ERPNext', note: '销售订单、工单、请购单' },
  { who: 'ERPNext', what: '单据建好，状态回到工作台', note: '提议显示“已执行”，附单据号' },
];
const cur = ref(0);
const rejected = ref(false);
let timer;
function play(rej) {
  clearInterval(timer);
  rejected.value = rej;
  const end = rej ? 2 : STEPS.length - 1;
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { cur.value = end; return; }
  cur.value = 0;
  timer = setInterval(() => { if (cur.value >= end) clearInterval(timer); else cur.value += 1; }, 1200);
}
onMounted(() => play(false));
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.ad { margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); }
.lane { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; font-size: 13px; }
@media (max-width: 640px) { .lane { grid-template-columns: 1fr; } }
.lane li { display: flex; flex-direction: column; gap: 4px; padding: 10px; border-radius: 8px; background: var(--surface-2); border-top: 4px solid var(--line);
  opacity: 0.45; transition: all 0.35s; }
.lane li.past { opacity: 0.8; border-top-color: var(--accent); }
.lane li.on { opacity: 1; border-top-color: var(--brand); background: var(--task-bg); }
.lane li:nth-child(3).on { box-shadow: 0 0 0 2px var(--brand); }
.lane li.stop { opacity: 0.2; }
.who { color: var(--muted); }
.ctl { display: flex; gap: 8px; margin: 10px 0 4px; }
figcaption { line-height: 1.7; }
@media (prefers-reduced-motion: reduce) { .lane li { transition: none; } }
</style>
