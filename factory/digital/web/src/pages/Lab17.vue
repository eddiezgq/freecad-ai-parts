<!-- 实验 17“安全隐患的识别、评估与停机决策”（第 18 轮 E2-9）：先自己评估、追影响、选方案，提交后才看中枢的建议 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('实验 17 · 安全隐患的识别、评估与停机决策') }}</h1>
      <span class="muted">{{ $t('平台自动评 {a} 分（按平台里的事实），报告 {b} 分由老师在课程里批改', { a: s?.of || 60, b: s?.report_points || 40 }) }}</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab17/guide.docx">{{ $t('指导书') }}</a> · <a href="/api/cae/lab17/report-template.docx">{{ $t('报告模板') }}</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ $td(s.score) }} / {{ $td(s.of) }}</b>
        <span v-if="!s.teacher" class="pill" :class="s.locked ? 'warn' : 'good'">{{ s.locked ? $t('比对模式：提交任务 3 之前，指挥台和 AI 不显示建议') : $t('已提交选择：可以看中枢的建议，和你的对比') }}</span>
        <router-link v-if="s.anomaly_id" class="small" :to="{ path: '/ont', query: { view: 'anomalies', a: s.anomaly_id } }">{{ $t('打开这条隐患的异常') }}</router-link>
        <router-link class="small" to="/ehs">{{ $t('安全环保') }}</router-link>
        <span v-if="!s.teacher && session.user?.role !== 'safety'" class="small warn-t">{{ $t('提示：停机挂牌、验收解锁要用“安全员”角色（右上角切换角色）。') }}</span>
      </div>

      <section v-if="s.teacher" class="card">
        <div class="card-head"><h2>{{ $t('老师：注入') }}</h2><span class="small muted">{{ $t('学生看不到这里') }}</span></div>
        <div class="row">
          <select v-model="inj.unit" :aria-label="$t('设备')"><option v-for="u in UNITS" :key="u" :value="u">{{ u.toUpperCase() }}</option></select>
          <select v-model="inj.issue_kind" :aria-label="$t('隐患种类')"><option v-for="(l, k) in s.options.kinds" :key="k" :value="k">{{ $td(l) }}</option></select>
          <button class="btn danger" @click="inject('major')">{{ $t('注入重大隐患') }}</button>
          <button class="btn" @click="inject('bypass')">{{ $t('模拟违规拆锁') }}</button>
          <span class="small ok">{{ injMsg }}</span>
        </div>
        <p class="small muted">{{ $t('建议 GRD-01 + 防护罩缺失；先在“情景导演”的教师控制台切到“按班次”。“违规拆锁”只在这台设备挂着锁时有效：设备恢复运转而许可没关，规则 E5 会报警。') }}</p>
        <table v-if="s.class?.length" class="tbl small"><thead><tr><th>{{ $t('学生') }}</th><th v-for="t in s.tasks" :key="t.id" class="num">{{ $td(t.title) }}</th><th class="num">{{ $t('合计') }}</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ $td(c.user) }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ $td(c.total) }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>{{ $t('任务 {a}　{b}', { a: i + 1, b: $td(t.title) }) }}</h2><span class="pts">{{ $td(t.score) }} / {{ $td(t.points) }}</span></div>
        <p>{{ $td(t.desc) }}</p>
        <p class="small muted">{{ $t('提示：{a}', { a: $td(t.hint) }) }}</p>
        <form v-if="t.id === 'l17_t1'" class="f" @submit.prevent="submit('l17_t1', a1)">
          <div class="field"><label>{{ $t('隐患') }}</label><select v-model="a1.issue_id" required>
            <option v-for="o in s.options.issues" :key="o.value" :value="o.value">{{ $td(o.label) }}</option></select></div>
          <div class="field"><label>{{ $t('对应的危险源') }}</label><select v-model="a1.hazard_id" required>
            <option v-for="o in s.options.hazards" :key="o.value" :value="o.value">{{ $td(o.label) }}</option></select></div>
          <div class="field"><label>{{ $t('可能性 × 严重度') }}</label>
            <input v-model.number="a1.likelihood" type="number" min="1" max="5" required :aria-label="$t('可能性')"> ×
            <input v-model.number="a1.severity" type="number" min="1" max="5" required :aria-label="$t('严重度')">
            <span class="small">= {{ (a1.likelihood || 0) * (a1.severity || 0) }}</span></div>
          <div class="field"><label>{{ $t('等级') }}</label><span class="cks"><label v-for="l in s.levels" :key="l"><input v-model="a1.level" type="radio" :value="l" required> {{ $td(l) }}</label></span></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l17_t2'" class="f" @submit.prevent="submit('l17_t2', a2)">
          <div class="field"><label>{{ $t('受影响的工单') }}</label><span class="cks">
            <label v-for="w in s.options.work_orders" :key="w"><input v-model="a2.work_orders" type="checkbox" :value="w"> {{ $td(w) }}</label></span></div>
          <div class="field"><label>{{ $t('受影响的订单') }}</label><span class="cks">
            <label v-for="o in s.options.sales_orders" :key="o"><input v-model="a2.sales_orders" type="checkbox" :value="o"> {{ $td(o) }}</label></span></div>
          <div class="field"><label>{{ $t('整改要多少分钟') }}</label><input v-model.number="a2.fix_minutes" type="number" min="0" step="10" required></div>
          <button class="btn primary" :disabled="!s.issue_id">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l17_t3'" class="f" @submit.prevent="submit('l17_t3', a3)">
          <div class="field"><label>{{ $t('选哪个方案') }}</label><span class="cks">
            <label v-for="o in s.options.option_kinds" :key="o.value"><input v-model="a3.option" type="radio" :value="o.value" required> {{ $td(o.label) }}</label></span></div>
          <div class="field"><label>{{ $t('理由与代价') }}</label><textarea v-model="a3.reason" rows="3" required :placeholder="$t('安全、交期、成本……')"></textarea></div>
          <button class="btn primary" :disabled="!s.issue_id">{{ $t('提交选择') }}</button>
        </form>
        <div v-if="t.id === 'l17_t4'" class="small">
          <template v-if="t.evidence?.actions?.length">{{ $t('你的停机挂牌动作：') }}<span v-for="x in t.evidence.actions" :key="x.id"> {{ $t('ACT-{a}（{b}）', { a: String(x.id).padStart(5, '0'), b: ST[x.status] || x.status }) }}</span>
            <span v-if="t.evidence.issue_status"> {{ $t('· 隐患：{a}', { a: { open: $t('待指派'), assigned: $t('整改中'), fixed: $t('待验收'), closed: $t('已关闭') }[t.evidence.issue_status] }) }}</span></template>
          <template v-else>{{ $t('还没有动作。') }}</template> <router-link to="/ont/actions?box=mine">{{ $t('动作收件箱') }}</router-link> · <router-link to="/ehs?tab=permits">{{ $t('作业许可') }}</router-link>
        </div>
        <form v-if="t.id === 'l17_t5'" class="f" @submit.prevent="submit('l17_t5', a5)">
          <div class="field"><label>{{ $t('受影响的订单') }}</label><span class="cks">
            <label v-for="b in s.buckets" :key="b"><input v-model="a5.bucket" type="radio" :value="b" required> {{ $td(b) }}</label></span></div>
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

const UNITS = ['grd-01', 'cnc-l01-a', 'cnc-l01-b', 'ht-01', 'key-01', 'saw-01', 'hob-01', 'press-01'];
const ST = { draft: $t('草稿'), submitted: $t('待批准'), approved: $t('已批准'), rejected: $t('已驳回'), executing: $t('执行中'), done: $t('已完成'), failed: $t('失败') };
const s = ref(null);
const err = ref('');
const fb = reactive({});
const a1 = reactive({ issue_id: null, hazard_id: '', likelihood: 2, severity: 3, level: '' });
const a2 = reactive({ work_orders: [], sales_orders: [], fix_minutes: 0 });
const a3 = reactive({ option: '', reason: '' });
const a5 = reactive({ bucket: '' });
const inj = reactive({ unit: 'grd-01', issue_kind: 'guard' });
const injMsg = ref('');

async function load() {
  try {
    s.value = await get('/lab17');
    if (s.value.issue_id && !a1.issue_id) a1.issue_id = s.value.issue_id;
  } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab17/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { alert(e.message); }
}
async function inject(kind) {
  try { injMsg.value = (await post('/lab17/inject', { ...inj, kind })).text; await load(); } catch (e) { alert(e.message); }
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
.field > label:first-child { width: 150px; font-weight: 500; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 300px; font-size: 13px; }
select, input[type=number] { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
input[type=number] { width: 70px; }
textarea { flex: 1 1 300px; border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.ok { color: var(--good); }
.warn-t { color: var(--warn); }
</style>
