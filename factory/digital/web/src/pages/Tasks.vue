<template>
  <div class="page">
    <div class="page-title"><h1>我的任务</h1>
      <span class="muted">老师在课程里下达的工程任务单：按任务单交交付物，AI 评审员先提意见，老师批准后进车间加工、检验，最后按评分量规给分。</span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <section class="card">
      <div v-if="!rows.length" class="empty">还没有下达的任务单。老师在学习平台课程的“任务单”里下达后，这里就会出现。</div>
      <table v-else class="t">
        <thead><tr><th>编号</th><th>任务</th><th>课程</th><th>交期</th><th>{{ teacher ? '提交情况' : '我的进度' }}</th></tr></thead>
        <tbody><tr v-for="t in rows" :key="t.id">
          <td class="mono">{{ t.code }}</td>
          <td><router-link :to="'/tasks/' + t.id">{{ t.title?.[0] }}</router-link>
            <div class="small muted">{{ t.role?.[0] }} · {{ t.hours }} 学时 · {{ (t.stations || []).join(' ') }}</div></td>
          <td class="small">{{ t.course_name || '—' }}</td>
          <td class="small">{{ t.due ? timeOf(t.due) : '—' }}</td>
          <td v-if="teacher" class="small">
            <span v-for="(n, k) in t.counts || {}" :key="k" class="pill" :class="TONE[k]">{{ STATUS[k] }} {{ n }}</span>
            <span v-if="!Object.keys(t.counts || {}).length" class="muted">还没有人开始</span></td>
          <td v-else><span class="pill" :class="TONE[t.mine?.status || 'draft']">{{ t.mine ? t.mine.status_zh : '未开始' }}</span>
            <span v-if="t.mine?.total != null" class="small"> {{ t.mine.total }} 分</span></td>
        </tr></tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { get, session } from '../lib/api';
import { timeOf } from '../lib/fmt';
import { STATUS, TONE } from '../lib/tasks';

const rows = ref([]);
const err = ref('');
const teacher = computed(() => !!session.user?.teacher);
onMounted(async () => { try { rows.value = await get('/tasks'); } catch (e) { err.value = e.message; } });
</script>

<style scoped>
.pill { margin-right: 4px; }
</style>
