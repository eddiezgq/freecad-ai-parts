<!-- 实验 20“供应链：来料不合格与供应商选择”（第 18 轮 E5-8）：单一来源、来料检验、比较方案（比对模式）、执行、总拥有成本 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('实验 20 · 供应链：来料不合格与供应商选择') }}</h1>
      <span class="muted">{{ $t('平台自动评 {a} 分（按平台里的事实），报告 {b} 分由老师在课程里批改', { a: s?.of || 60, b: s?.report_points || 40 }) }}</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab20/guide.docx">{{ $t('指导书') }}</a> · <a href="/api/cae/lab20/report-template.docx">{{ $t('报告模板') }}</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ $td(s.score) }} / {{ $td(s.of) }}</b>
        <span v-if="!s.teacher" class="pill" :class="s.locked ? 'warn' : 'good'">{{ s.locked ? $t('比对模式：提交任务 3 之前，指挥台和 AI 不显示建议') : $t('已提交选择：可以看中枢的建议，和你的对比') }}</span>
        <span class="small" :class="s.enabled ? 'ok' : 'muted'">{{ $t('供应商模拟器{a}', { a: s.enabled ? $t('已打开') : $t('没打开') }) }}</span>
        <span v-if="s.target" class="small">{{ $t('这一批：{a} {b}（{c}），{d}', { a: s.target.lot || $t('已下单'), b: $td(s.target.item), c: s.target.supplier.split(' ')[0], d: $td(s.target.status) }) }}</span>
        <router-link v-if="s.anomaly_id" class="small" :to="{ path: '/ont', query: { view: 'anomalies', a: s.anomaly_id } }">{{ $t('打开来料不合格异常') }}</router-link>
        <router-link class="small" to="/supply?tab=inspect">{{ $t('到货与检验') }}</router-link>
        <router-link class="small" to="/supply?tab=suppliers">{{ $t('供应商') }}</router-link>
        <span v-if="!s.teacher && !['quality', 'planner'].includes(session.user?.role)" class="small warn-t">{{ $t('提示：来料检验用“质量”角色；退货、采购单用“计划员”或“质量”（右上角切换角色）。') }}</span>
      </div>

      <section v-if="s.teacher" class="card">
        <div class="card-head"><h2>{{ $t('老师：设置') }}</h2><span class="small muted">{{ $t('学生看不到这里') }}</span></div>
        <div class="row">
          <button class="btn" @click="inject({ enable: !s.enabled, only_toggle: true })">{{ $t('{a}供应商模拟器', { a: s.enabled ? $t('关闭') : $t('打开') }) }}</button>
          <button class="btn danger" @click="inject({ enable: true })">{{ $t('注入一批不合格的轴承（五大湖 BRG-6207 × 40）') }}</button>
          <span class="small ok">{{ injMsg }}</span>
        </div>
        <p class="small muted">{{ $t('约 15 分钟（真实时间）后到货；这一批留给学生检验，质检员模拟器不替他们检。') }}</p>
        <table v-if="s.class?.length" class="tbl small"><thead><tr><th>{{ $t('学生') }}</th><th v-for="t in s.tasks" :key="t.id" class="num">{{ $td(t.title) }}</th><th class="num">{{ $t('合计') }}</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ $td(c.user) }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ $td(c.total) }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>{{ $t('任务 {a}　{b}', { a: i + 1, b: $td(t.title) }) }}</h2><span class="pts">{{ $td(t.score) }} / {{ $td(t.points) }}</span></div>
        <p>{{ $td(t.desc) }}</p>
        <p class="small muted">{{ $t('提示：{a}', { a: $td(t.hint) }) }}</p>
        <form v-if="t.id === 'l20_t1'" class="f" @submit.prevent="submit('l20_t1', { cats: a1 })">
          <div class="field"><label>{{ $t('只有一家供应商的物料类别') }}</label><span class="cks">
            <label v-for="c in s.cats" :key="c.value"><input v-model="a1" type="checkbox" :value="c.value"> {{ $td(c.label) }}</label></span></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l20_t2'" class="f" @submit.prevent="submit('l20_t2', a2)">
          <div class="field"><label>{{ $t('抽样里几处超差') }}</label><input v-model.number="a2.bad_count" type="number" min="0" step="1" required></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l20_t3'" class="f" @submit.prevent="submit('l20_t3', a3)">
          <div class="field"><label>{{ $t('选哪个方案') }}</label><span class="cks">
            <label v-for="o in s.options" :key="o.value"><input v-model="a3.option" type="radio" :value="o.value" required> {{ $td(o.label) }}</label></span></div>
          <div class="field"><label>{{ $t('理由与代价') }}</label><textarea v-model="a3.reason" rows="3" required :placeholder="$t('到料日、交期、花费、质量风险……')"></textarea></div>
          <button class="btn primary" :disabled="!s.target">{{ $t('提交选择') }}</button>
        </form>
        <div v-if="t.id === 'l20_t4'" class="small">
          <template v-if="t.evidence?.actions?.length">{{ $t('你的动作：') }}<span v-for="x in t.evidence.actions" :key="x.id"> {{ $t('ACT-{a}（{b}）', { a: String(x.id).padStart(5, '0'), b: ST[x.status] || x.status }) }}</span>
            <span> {{ $t('· 这一批：{a}', { a: LOT[t.evidence.lot] || t.evidence.lot || '—' }) }}</span></template>
          <template v-else>{{ $t('还没有退货、让步接收或采购单动作。') }}</template> <router-link to="/ont/actions?box=mine">{{ $t('动作收件箱') }}</router-link>
        </div>
        <form v-if="t.id === 'l20_t5'" class="f" @submit.prevent="submit('l20_t5', a5)">
          <div class="field"><label>{{ $t('默认供应商每件总拥有成本（$）') }}</label><input v-model.number="a5.tco_default" type="number" step="0.01" required></div>
          <div class="field"><label>{{ $t('备选供应商每件总拥有成本（$）') }}</label><input v-model.number="a5.tco_alt" type="number" step="0.01" required></div>
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
const LOT = { ordered: $t('已下单'), transit: $t('在途'), arrived: $t('到货待检'), accepted: $t('合格入库'), rejected: $t('不合格'), returned: $t('已退货'), suspect: $t('可疑') };
const s = ref(null);
const err = ref('');
const fb = reactive({});
const a1 = ref([]);
const a2 = reactive({ bad_count: null });
const a3 = reactive({ option: '', reason: '' });
const a5 = reactive({ tco_default: null, tco_alt: null });
const injMsg = ref('');

async function load() {
  try { s.value = await get('/lab20'); } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab20/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { alert(e.message); }
}
async function inject(body) {
  try { injMsg.value = (await post('/lab20/inject', body)).text; await load(); } catch (e) { alert(e.message); }
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
.field > label:first-child { width: 230px; font-weight: 500; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 300px; font-size: 13px; }
input[type=number] { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; width: 110px; }
textarea { flex: 1 1 300px; border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.ok { color: var(--good); }
.warn-t { color: var(--warn); }
</style>
