<template>
  <figure class="sh">
    <div class="ctl">
      <button v-for="(s, i) in STEPS" :key="i" class="btn sm" :class="{ primary: at === i }" :aria-pressed="at === i" @click="go(i)">{{ i + 1 }} {{ s.t }}</button>
    </div>
    <table class="roster" aria-live="polite">
      <thead><tr><th></th><th v-for="m in MACH" :key="m">{{ m }}</th></tr></thead>
      <tbody>
        <tr v-for="(row, r) in cells" :key="r">
          <th>{{ SHIFTS[r] }}</th>
          <td v-for="(c, k) in row" :key="k" :class="c.cls">
            <span>{{ c.who || '没人能开' }}</span><small v-if="c.note">{{ c.note }}</small>
          </td>
        </tr>
      </tbody>
    </table>
    <p class="say small"><b>{{ STEPS[at].t }}</b>：{{ STEPS[at].say }}</p>
    <figcaption class="small muted">示例。排班表的每一格是谁开这台设备：红是没人能开，黄是学徒带着开。磨床是瓶颈，它那一格空了整条线都慢。
      调人能补上，但他原来的格子会空出来——推演会把这一格一起算进去；加班顶班不动别的格子，要付加班费。</figcaption>
  </figure>
</template>

<script setup>
// 排班缺口与调班（第 30 轮 §八 8-2，人员与排班）：请假 → 缺人变红 → 调人（另一格变红）→ 加班顶上。
import { computed, onMounted, onUnmounted, ref } from 'vue';

const MACH = ['锯床', '车床 1', '车床 2', '磨床 ⚑', '热处理'];
const SHIFTS = ['早班', '晚班'];
const BASE = [['周强', '李娜', '陈刚', '王磊', '赵敏'], ['孙浩', '刘洋', '吴静', '郑涛', '钱峰']];
const STEPS = [
  { t: '照常', say: '每台设备每一班都有能开它的人。' },
  { t: '王磊请假', say: '磨床早班的熟练工请假，磨床这一班没人能开；它是瓶颈，订单要晚。' },
  { t: '调陈刚顶岗', say: '车床 2 的陈刚也会开磨床，调过去；可车床 2 早班又空了。' },
  { t: '改成加班顶班', say: '晚班的郑涛早来加班顶磨床，陈刚回车床 2；没有空格，多付加班费。' },
];
const at = ref(0);
const cells = computed(() => BASE.map((row, r) => row.map((who, k) => {
  if (r === 0 && k === 3 && at.value >= 1) {
    if (at.value === 1) return { who: '', cls: 'red', note: '王磊请假' };
    if (at.value === 2) return { who: '陈刚', cls: 'moved', note: '调来顶岗' };
    return { who: '郑涛', cls: 'ot', note: '加班顶班' };
  }
  if (r === 0 && k === 2 && at.value === 2) return { who: '', cls: 'red', note: '陈刚调走了' };
  return { who, cls: '' };
})));
let timer;
function go(i) { at.value = i; clearInterval(timer); }
onMounted(() => {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { at.value = 3; return; }
  timer = setInterval(() => { at.value = (at.value + 1) % STEPS.length; }, 2600);
});
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.sh { margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); }
.ctl { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.roster { width: 100%; border-collapse: separate; border-spacing: 4px; table-layout: fixed; }
.roster th { font-size: 13px; font-weight: 600; color: var(--muted); text-align: center; }
.roster td { background: var(--good-bg); border: 2px solid var(--good); border-radius: 6px; text-align: center; padding: 8px 2px; font-size: 14px; transition: all 0.4s; }
.roster td small { display: block; font-size: 11px; color: var(--muted); }
.roster td.red { background: var(--bad-bg); border-color: var(--bad); color: var(--bad); font-weight: 600; }
.roster td.moved { background: var(--accent-bg); border-color: var(--accent); }
.roster td.ot { background: var(--warn-bg); border-color: var(--warn); }
.say { margin: 10px 0 0; min-height: 2.6em; }
figcaption { margin-top: 6px; line-height: 1.7; }
@media (max-width: 560px) { .roster td { font-size: 12px; padding: 6px 0; } }
@media (prefers-reduced-motion: reduce) { .roster td { transition: none; } }
</style>
