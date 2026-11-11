<!-- 实验 22“经营：订单毛利、应收与现金”（第 18 轮 E7-10）：没达标的指标、订单毛利、比较催款方案（比对模式）、执行、DSO 与现金 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('实验 22 · 经营：订单毛利、应收与现金') }}</h1>
      <span class="muted">{{ $t('平台自动评 {a} 分（按平台里的事实），报告 {b} 分由老师在课程里批改', { a: s?.of || 60, b: s?.report_points || 40 }) }}</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab22/guide.docx">{{ $t('指导书') }}</a> · <a href="/api/cae/lab22/report-template.docx">{{ $t('报告模板') }}</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ $td(s.score) }} / {{ $td(s.of) }}</b>
        <span v-if="!s.teacher" class="pill" :class="s.locked ? 'warn' : 'good'">{{ s.locked ? $t('比对模式：提交任务 3 之前，指挥台和 AI 不显示建议') : $t('已提交选择：可以看中枢的建议，和你的对比') }}</span>
        <span class="small" :class="s.sim ? 'ok' : 'muted'">{{ $t('财务模拟器{a}', { a: s.sim ? $t('已打开') : $t('没打开') }) }}</span>
        <span v-if="s.target" class="small">{{ $t('注入的发票：{a} ${b}，{c}', { a: s.target.customer.split(' ')[0], b: Math.round(s.target.amount).toLocaleString(), c: $td(s.target.status) }) }}</span>
        <router-link v-if="s.anomaly_id" class="small" :to="{ path: '/ont', query: { view: 'anomalies', a: s.anomaly_id } }">{{ $t('打开应收逾期异常') }}</router-link>
        <router-link class="small" to="/finance?tab=objectives">{{ $t('经营目标') }}</router-link>
        <router-link class="small" to="/finance?tab=margins">{{ $t('订单毛利') }}</router-link>
        <router-link class="small" to="/finance?tab=arap">{{ $t('应收应付') }}</router-link>
        <span v-if="!s.teacher && !['sales', 'planner'].includes(session.user?.role)" class="small warn-t">{{ $t('提示：催款用“销售”或“计划员”角色发起（右上角切换角色）。') }}</span>
      </div>

      <section v-if="s.teacher" class="card">
        <div class="card-head"><h2>{{ $t('老师：设置') }}</h2><span class="small muted">{{ $t('学生看不到这里') }}</span></div>
        <div class="row">
          <button class="btn" @click="inject({ enable: !s.sim, only_toggle: true })">{{ $t('{a}财务模拟器', { a: s.sim ? $t('关闭') : $t('打开') }) }}</button>
          <label class="small">{{ $t('任务 2 的订单') }} <input v-model="so" :placeholder="$t('不填用第一张')"></label>
          <button class="btn danger" @click="inject({ enable: true, sales_order: so || undefined })">{{ $t('注入：海港起重一笔发票逾期不付') }}</button>
          <span class="small ok">{{ injMsg }}</span>
        </div>
        <p class="small muted">{{ $t('$13,200 逾期 15 天，不催就不付；催款后客户 3 个账期日（约 6 分钟）内付。') }}</p>
        <table v-if="s.class?.length" class="tbl small"><thead><tr><th>{{ $t('学生') }}</th><th v-for="t in s.tasks" :key="t.id" class="num">{{ $td(t.title) }}</th><th class="num">{{ $t('合计') }}</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ $td(c.user) }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ $td(c.total) }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>{{ $t('任务 {a}　{b}', { a: i + 1, b: $td(t.title) }) }}</h2><span class="pts">{{ $td(t.score) }} / {{ $td(t.points) }}</span></div>
        <p>{{ $td(t.desc) }}</p>
        <p class="small muted">{{ $t('提示：{a}', { a: $td(t.hint) }) }}</p>
        <form v-if="t.id === 'l22_t1'" class="f" @submit.prevent="submit('l22_t1', { codes: a1 })">
          <div class="field"><label>{{ $t('没达标的指标') }}</label><span class="cks">
            <label v-for="o in s.objectives" :key="o.value"><input v-model="a1" type="checkbox" :value="o.value"> {{ $td(o.value) }} {{ $td(o.label) }}</label></span></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l22_t2'" class="f" @submit.prevent="submit('l22_t2', a2)">
          <p class="small">{{ $t('订单：') }}<b>{{ s.sales_order || $t('还没有做完的订单') }}</b></p>
          <div class="field"><label>{{ $t('毛利率（%）') }}</label><input v-model.number="a2.margin_pct" type="number" step="0.1" required></div>
          <div class="field"><label>{{ $t('料以外花得最多的一项') }}</label><select v-model="a2.top" required><option v-for="c in s.costs" :key="c.value" :value="c.value">{{ $td(c.label) }}</option></select></div>
          <button class="btn primary" :disabled="!s.sales_order">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l22_t3'" class="f" @submit.prevent="submit('l22_t3', a3)">
          <div class="field"><label>{{ $t('选哪个方案') }}</label><span class="cks">
            <label v-for="o in s.options" :key="o.value"><input v-model="a3.option" type="radio" :value="o.value" required> {{ $td(o.label) }}</label></span></div>
          <div class="field"><label>{{ $t('理由与代价') }}</label><textarea v-model="a3.reason" rows="3" required :placeholder="$t('几天收到钱、现金哪周最紧、客户关系……')"></textarea></div>
          <button class="btn primary" :disabled="!s.anomaly_id">{{ $t('提交选择') }}</button>
        </form>
        <div v-if="t.id === 'l22_t4'" class="small">
          <template v-if="t.evidence?.actions?.length">{{ $t('你的动作：') }}<span v-for="x in t.evidence.actions" :key="x.id"> {{ $t('ACT-{a}（{b}）', { a: String(x.id).padStart(5, '0'), b: ST[x.status] || x.status }) }}</span>
            <span> {{ $t('· 这笔发票：{a}', { a: INV[t.evidence.invoice] || t.evidence.invoice || '—' }) }}</span></template>
          <template v-else>{{ $t('还没有针对这笔发票的催款或信用冻结动作。') }}</template> <router-link to="/ont/actions?box=mine">{{ $t('动作收件箱') }}</router-link>
        </div>
        <form v-if="t.id === 'l22_t5'" class="f" @submit.prevent="submit('l22_t5', a5)">
          <div class="field"><label>{{ $t('应收周转天数 DSO') }}</label><input v-model.number="a5.dso" type="number" step="0.1" required></div>
          <div class="field"><label>{{ $t('现金最紧的是第几周') }}</label><input v-model.number="a5.low_week" type="number" min="1" max="8" required></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <p v-if="fb[t.id]" class="small fb">{{ $td(fb[t.id]) }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { onMounted, reactive, ref } from 'vue';
import { get, post, session } from '../lib/api';

const ST = { draft: $t('草稿'), submitted: $t('待批准'), approved: $t('已批准'), rejected: $t('已驳回'), executing: $t('执行中'), done: $t('已完成'), failed: $t('失败') };
const s = ref(null);
const err = ref('');
const fb = reactive({});
const INV = { draft: $t('待开票'), open: $t('未付'), paying: $t('付款中'), paid: $t('已付'), failed: $t('开票失败'), held: $t('冻结待放行') };
const a1 = ref([]);
const a2 = reactive({ margin_pct: null, top: '' });
const a3 = reactive({ option: '', reason: '' });
const a5 = reactive({ dso: null, low_week: null });
const so = ref('');
const injMsg = ref('');

async function load() {
  try { s.value = await get('/lab22'); } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab22/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { alert(e.message); }
}
async function inject(body) {
  try { injMsg.value = (await post('/lab22/inject', body)).text; await load(); } catch (e) { alert(e.message); }
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
.field { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.field > label:first-child { width: 260px; font-weight: 500; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 300px; font-size: 13px; }
input[type=number] { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; width: 110px; }
textarea { flex: 1 1 300px; border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.ok { color: var(--good); }
.warn-t { color: var(--warn); }
</style>
