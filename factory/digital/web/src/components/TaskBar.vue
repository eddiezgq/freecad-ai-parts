<template>
  <section v-if="t" class="task-bar" :aria-label="tr('当前任务')">
    <span class="tag">{{ tr('实验 7 · 数字工厂闭环') }}</span>
    <div class="body">
      <b>{{ tr('任务 {i} / {n}：', { i: t.current + 1, n: t.tasks.length }) }}{{ td(cur.title) }}{{ cur.done ? tr('（已完成）') : '' }}</b>
      <span class="muted small">{{ tr('你的角色：{r}', { r: roleName(cur.role) }) }} · {{ tr('提示：') }}{{ td(cur.hint) }}</span>
    </div>
    <div class="score">
      <span class="mono big">{{ t.score }} / {{ t.of }}</span>
      <span class="muted small">{{ tr('得分 · 已用 {m} 分钟', { m: t.elapsed_min }) }}</span>
    </div>
    <router-link class="btn ghost" to="/teach">{{ tr('查看任务') }}</router-link>
  </section>
</template>

<script setup>
import { computed } from 'vue';
import { roleName } from '../lib/api';
import { t as tr, td } from '../lib/i18n';

const props = defineProps({ t: Object });
const cur = computed(() => props.t.tasks[props.t.current]);
</script>

<style scoped>
.tag { font-size: 12px; font-weight: 600; color: var(--task-ink); background: #F2D675; padding: 3px 8px; border-radius: 4px; white-space: nowrap; }
.body { display: flex; flex-direction: column; gap: 2px; flex-grow: 1; }
.body b { font-size: 14px; }
.score { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.big { font-size: 18px; font-weight: 600; }
.btn { display: inline-flex; align-items: center; background: #fff; border-color: #C9A63A; }
@media (max-width: 900px) { .task-bar { flex-wrap: wrap; } }
</style>
