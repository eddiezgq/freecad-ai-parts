<!-- 实验 33“一张非标订单：从询价到收款”（第 139 轮 139h）：估算 → 报价接单 → 设计与计划 → 车间与质量 → 分期开票 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('实验 33 · 一张非标订单：从询价到收款') }}</h1>
      <span class="muted">{{ $t('平台自动评 {a} 分（按平台里的事实），报告 {b} 分由老师在课程里批改', { a: s?.of || 60, b: s?.report_points || 40 }) }}</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab33/guide.docx">{{ $t('指导书') }}</a> · <a href="/api/cae/lab33/report-template.docx">{{ $t('报告模板') }}</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ $td(s.score) }} / {{ $td(s.of) }}</b>
        <span class="small">{{ $t('作业：') }}<b>{{ s.job_no || $t('还没填（任务 1）') }}</b></span>
        <router-link class="small" :to="s.job_no ? { path: '/eto', query: { job: s.job_no } } : '/eto'">{{ $t('打开按单设计') }}</router-link>
        <span class="small muted">{{ $t('提示：估算、报价用“销售”，设计用“工艺员”，下达车间用“计划员”，检验用“质检员”（右上角切换角色）。') }}</span>
      </div>

      <section v-if="s.teacher && s.class?.length" class="card">
        <div class="card-head"><h2>{{ $t('老师：全班成绩') }}</h2><span class="small muted">{{ $t('学生看不到这里') }}</span></div>
        <table class="tbl small"><thead><tr><th>{{ $t('学生') }}</th><th v-for="t in s.tasks" :key="t.id" class="num">{{ $td(t.title) }}</th><th class="num">{{ $t('合计') }}</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ $td(c.user) }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ $td(c.total) }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>{{ $t('任务 {a}　{b}', { a: i + 1, b: $td(t.title) }) }}</h2><span class="pts">{{ $td(t.score) }} / {{ $td(t.points) }}</span></div>
        <p>{{ $td(t.desc) }}</p>
        <p class="small muted">{{ $t('提示：{a}', { a: $td(t.hint) }) }}</p>
        <form v-if="t.id === 'l33_t1'" class="f" @submit.prevent="submit('l33_t1', a1)">
          <div class="fr"><label>{{ $t('作业号') }}</label><input v-model.trim="a1.job_no" required placeholder="JOB-2026-0001"></div>
          <div class="fr"><label>{{ $t('2 件那一档的报价总额（$）') }}</label><input v-model.number="a1.price" type="number" step="0.01"></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <p v-if="t.id === 'l33_t2'" class="small muted">{{ $t('平台自动检查：作业已接单、销售订单带付款计划。') }}</p>
        <form v-if="t.id === 'l33_t3'" class="f" @submit.prevent="submit('l33_t3', a3)">
          <div class="fr"><label>{{ $t('最早能交货的日期') }}</label><input v-model="a3.earliest" type="date" required></div>
          <button class="btn primary" :disabled="!s.job_no">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l33_t4'" class="f" @submit.prevent="submit('l33_t4', a4)">
          <div class="fr"><label>{{ $t('工序成本：实际 − 估算（$）') }}</label><input v-model.number="a4.diff" type="number" step="0.01" required></div>
          <button class="btn primary" :disabled="!s.job_no">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l33_t5'" class="f" @submit.prevent="submit('l33_t5', a5)">
          <div class="fr"><label>{{ $t('“发货”那一期为什么开不了票') }}</label><span class="cks">
            <label v-for="o in s.reasons" :key="o.value"><input v-model="a5.reason" type="radio" :value="o.value" required> {{ $td(o.label) }}</label></span></div>
          <button class="btn primary" :disabled="!s.job_no">{{ $t('提交') }}</button>
        </form>
        <p v-if="fb[t.id]" class="small fb">{{ $td(fb[t.id]) }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { onMounted, reactive, ref } from 'vue';
import { get, post } from '../lib/api';

const s = ref(null);
const err = ref('');
const fb = reactive({});
const a1 = reactive({ job_no: '', price: null });
const a3 = reactive({ earliest: '' });
const a4 = reactive({ diff: null });
const a5 = reactive({ reason: '' });

async function load() {
  try { s.value = await get('/lab33'); err.value = ''; if (s.value.job_no && !a1.job_no) a1.job_no = s.value.job_no; } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab33/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { err.value = e.message; }
}
onMounted(load);
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.r { margin-left: auto; }
.sum { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
.big { font-size: 24px; }
.task.done { border-left: 4px solid var(--good); }
.pts { margin-left: auto; font-weight: 600; }
.f { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.fr { display: flex; flex-direction: row; gap: 10px; align-items: center; flex-wrap: wrap; }
.fr > label:first-child { width: 260px; font-weight: 500; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 auto; font-size: 13px; }
.f .btn { align-self: flex-start; }
input { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; width: 180px; }
input[type=radio] { width: auto; height: auto; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
</style>
