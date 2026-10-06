<template>
  <section v-if="t" class="task-bar" aria-label="当前任务">
    <span class="tag">实验 7 · 数字工厂闭环</span>
    <div class="body">
      <b>任务 {{ t.current + 1 }} / {{ t.tasks.length }}：{{ cur.title }}{{ cur.done ? '（已完成）' : '' }}</b>
      <span class="muted small">你的角色：{{ roleName(cur.role) }} · 提示：{{ cur.hint }}</span>
    </div>
    <div class="score">
      <span class="mono big">{{ t.score }} / {{ t.of }}</span>
      <span class="muted small">得分 · 已用 {{ t.elapsed_min }} 分钟</span>
    </div>
    <router-link class="btn ghost" to="/teach">查看任务</router-link>
  </section>
</template>

<script setup>
import { computed } from 'vue';
import { roleName } from '../lib/api';

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
