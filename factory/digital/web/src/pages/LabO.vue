<!-- 通用“从订单到交付”实验页（第 149 轮，照实验 34）：/labo/39 电路板厂、/labo/40 芯片封测厂；内容来自 hub/labo.py 的配置 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('实验 {a} · {b}', { a: no, b: $td(s?.title || '') }) }}</h1>
      <span class="muted">{{ $t('平台自动评 {a} 分（按平台里的事实），报告 {b} 分由老师在课程里批改', { a: s?.of || 60, b: s?.report_points || 40 }) }}</span>
      <span class="r small" data-help="lab-links"><a :href="'/api/cae/lab' + no + '/guide.docx'">{{ $t('指导书') }}</a> · <a :href="'/api/cae/lab' + no + '/report-template.docx'">{{ $t('报告模板') }}</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ $td(s.score) }} / {{ $td(s.of) }}</b>
        <span v-if="s.order" class="small">{{ $t('你的订单') }} <b class="mono">{{ $td(s.order.sales_order) }}</b>{{ $t('，{a} 张工单', { a: Object.keys(s.order.work_orders).length }) }}</span>
        <span v-else class="small muted">{{ $t('还没有你的 {a} 订单：先做任务 1', { a: s.product }) }}</span>
        <router-link class="small" to="/work/planner">{{ $t('订单与计划') }}</router-link>
        <router-link class="small" to="/work/quality">{{ $t('质量') }}</router-link>
        <router-link class="small" to="/cost">{{ $t('生产成本') }}</router-link>
        <button class="btn sm" @click="load">{{ $t('刷新') }}</button>
      </div>

      <section v-if="s.teacher && s.class?.length" class="card">
        <div class="card-head"><h2>{{ $t('老师：全班成绩') }}</h2></div>
        <table class="tbl small"><thead><tr><th>{{ $t('学生') }}</th><th v-for="(t, i) in s.tasks" :key="t.id" class="num">{{ $t('任务 {a}', { a: i + 1 }) }}</th><th class="num">{{ $t('合计') }}</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ $td(c.user) }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ $td(c.total) }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>{{ $t('任务 {a}　{b}', { a: i + 1, b: $td(t.title) }) }}</h2><span class="pts">{{ $td(t.score) }} / {{ $td(t.points) }}</span></div>
        <p>{{ $td(t.desc) }}</p>
        <p class="small muted">{{ $t('提示：{a}', { a: $td(t.hint) }) }}</p>
        <form v-if="t.id === pre + 't1'" class="f" @submit.prevent="submit(t.id, a1)">
          <div class="lf"><label>{{ $t('要下几张工单') }}</label><input v-model.number="a1.work_orders" type="number" min="1" max="50" required></div>
          <div class="lf"><label>{{ $t('要领多少 {a}', { a: s.count_item }) }}</label><input v-model.number="a1.count" type="number" min="0" step="any" required></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === pre + 't2' && s.route" class="f" @submit.prevent="submit(t.id, a2)">
          <table class="tbl small"><thead><tr><th>{{ $t('工序') }}</th><th>{{ $t('单件工时（分钟）') }}</th><th>{{ $t('设备') }}</th><th>{{ $t('一次装几件') }}</th></tr></thead>
            <tbody><tr v-for="o in s.routing" :key="o.operation"><td>{{ $td(o.operation) }}</td><td class="mono">{{ $td(o.minutes) }}</td>
              <td class="mono">{{ o.units.join($t('、')) }}</td><td class="mono">{{ $td(o.batch) }}</td></tr></tbody></table>
          <div class="lf"><label>{{ $t('单件占时最长的工序') }}</label><input v-model="a2.longest" :placeholder="$t('写工序名称')" required></div>
          <div class="lf"><label>{{ $t('真正卡产能的工序') }}</label><input v-model="a2.bottleneck" :placeholder="$t('写工序名称')" required></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <div v-if="t.id === pre + 't2' && !s.route" class="small">
          <table v-if="s.layers.length" class="tbl"><thead><tr><th>{{ $t('物料') }}</th><th>{{ $t('工单') }}</th><th>{{ $t('下达') }}</th><th>{{ $t('用到的下一层') }}</th><th>{{ $t('核对') }}</th></tr></thead>
            <tbody><tr v-for="l in s.layers" :key="l.work_order">
              <td class="mono">{{ $td(l.item) }}</td><td class="mono">{{ $td(l.work_order) }}</td><td>{{ l.released ? timeOf(l.released) : $t('还没下达') }}</td>
              <td>{{ l.children.join($t('、')) || '—' }}</td>
              <td><span v-if="!l.released" class="muted">—</span><span v-else-if="l.released_before_children_done.length" class="bad-t">
                {{ $t('{a} 还没做完就下达了', { a: l.released_before_children_done.join($t('、')) }) }}</span><span v-else class="ok">✓</span></td></tr></tbody></table>
          <p v-else class="muted">{{ $t('先完成任务 1。') }}</p>
        </div>
        <form v-if="t.id === pre + 't3'" class="f" @submit.prevent="submit(t.id, a3)">
          <div class="lf"><label>{{ $t('选一件') }}</label><select v-model="a3.serial" required>
            <option v-for="j in s.machines" :key="j.serial" :value="j.serial">{{ $t('{a}（{b}）', { a: $td(j.serial), b: $td(j.item) }) }}</option></select></div>
          <div v-if="machine" class="lf"><label>{{ $t('测量值') }}</label><span class="small">
            <span v-for="(c, k) in machine.chars" :key="k" class="chip">{{ $td(c.name) }} <b class="mono">{{ $td(c.value) }}</b> {{ $t('{a}（公差 {b}–{c}）', { a: $td(c.unit), b: $td(c.lo), c: $td(c.hi) }) }}</span></span></div>
          <div class="lf"><label>{{ $t('判定') }}</label><span class="cks">
            <label><input v-model="a3.verdict" type="radio" value="pass" required> {{ $t('合格') }}</label>
            <label><input v-model="a3.verdict" type="radio" value="fail"> {{ $t('不合格') }}</label></span></div>
          <div v-if="a3.verdict === 'fail' && machine" class="lf"><label>{{ $t('超了哪一项') }}</label><select v-model="a3.char">
            <option v-for="(c, k) in machine.chars" :key="k" :value="k">{{ $td(c.name) }}</option></select></div>
          <p v-if="!s.machines.length" class="small muted">{{ $t('你这张单的成品还没测完（成品工单做到出厂检验后才有）。') }}</p>
          <button class="btn primary" :disabled="!s.machines.length">{{ $t('提交') }}</button>
        </form>
        <p v-if="t.id === pre + 't5' && s.std" class="small">{{ $t('一个单位 {a} 的标准成本（逐层累加）：材料', { a: s.product }) }} <b class="mono">${{ s.std.material.toLocaleString() }}</b>{{ $t('，各层工序') }} <b class="mono">${{ s.std.operations.toLocaleString() }}</b>{{ $t('，合计') }} <b class="mono">${{ s.std.total.toLocaleString() }}</b>{{ $t('。实际成本 = 材料 + 你这张单各工单的实际工时成本（“生产成本”页逐张看）。') }}</p>
        <form v-if="t.id === pre + 't5'" class="f" @submit.prevent="submit(t.id, a5)">
          <div class="lf"><label>{{ $t('实际比标准高（%）') }}</label><input v-model.number="a5.variance_pct" type="number" step="0.1" required></div>
          <div class="lf"><label>{{ $t('差得最多的工单（物料编号）') }}</label><input v-model="a5.worst" :placeholder="$t('物料编号')" required></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === pre + 't6'" class="f" @submit.prevent="submit(t.id, a6)">
          <div class="lf"><label>{{ $t('多了哪些环节') }}</label><span class="cks">
            <label v-for="o in s.t6_options" :key="o.value"><input v-model="a6.choices" type="checkbox" :value="o.value"> {{ $td(o.label) }}</label></span></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <p v-if="fb[t.id]" class="small fb">{{ $td(fb[t.id]) }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { get, post } from '../lib/api';
import { timeOf } from '../lib/fmt';

const route = useRoute();
const no = computed(() => Number(route.params.no));
const pre = computed(() => 'l' + no.value + '_');
const s = ref(null);
const err = ref('');
const fb = reactive({});
const a1 = reactive({ work_orders: null, count: null });
const a2 = reactive({ longest: '', bottleneck: '' });
const a3 = reactive({ serial: '', verdict: '', char: '' });
const a5 = reactive({ variance_pct: null, worst: '' });
const a6 = reactive({ choices: [] });
const machine = computed(() => s.value?.machines?.find((j) => j.serial === a3.serial) || null);

async function load() {
  try { s.value = await get('/labo/' + no.value); err.value = ''; } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/labo/' + no.value + '/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { alert(e.message); }
}
onMounted(load);
watch(no, () => { s.value = null; load(); });
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.r { margin-left: auto; }
.sum { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
.big { font-size: 24px; }
.task.done { border-left: 4px solid var(--good); }
.pts { margin-left: auto; font-weight: 600; }
.f { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.lf { display: flex; flex-direction: row; gap: 10px; align-items: flex-start; flex-wrap: wrap; }
.lf > label:first-child { width: 170px; font-weight: 500; padding-top: 4px; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 auto; min-width: 240px; font-size: 13px; }
.f .btn { align-self: flex-start; }
select, input[type=number], input:not([type]) { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
input[type=number] { width: 100px; }
.chip { display: inline-block; margin: 0 10px 4px 0; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; }
.num { text-align: right; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.ok { color: var(--good); }
.bad-t { color: var(--bad); }
</style>
