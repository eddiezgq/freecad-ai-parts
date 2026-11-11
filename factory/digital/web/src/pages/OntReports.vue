<!-- 厂情日报 / 经营周报（第 17 轮 D 期 D7）：数字全部来自历史库；生产模式按时自动生成，教学模式点“生成” -->
<template>
  <div class="page">
    <div class="page-title noprint"><h1><router-link to="/ont" class="back">{{ $t('厂情中枢') }}</router-link> {{ $t('/ 日报与周报') }}</h1>
      <span class="muted">{{ teach ? $t('教学模式：点“生成”即时生成最近 24 小时（日报）或 7 天（周报）的报告，可作实验材料') : $t('生产模式：每天 07:30 生成前一天的日报，每周一 08:00 生成上周的周报，按订阅推送') }}</span>
      <span class="tabs"><button v-for="(l, k) in KINDS" :key="k" :class="{ on: kind === k }" @click="kind = k; load()">{{ l }}</button></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="canGen" class="gen noprint">
      <button class="btn primary sm" :disabled="busy" @click="gen('daily')">{{ busy ? $t('生成中…') : teach ? $t('生成今天的日报') : $t('补生成日报') }}</button>
      <button class="btn sm" :disabled="busy" @click="gen('weekly')">{{ teach ? $t('生成本周的周报') : $t('补生成周报') }}</button>
    </div>
    <div class="grid">
      <div class="card list noprint">
        <p v-if="!list.length" class="muted small">{{ $t('还没有报告。') }}</p>
        <button v-for="r in list" :key="r.id" class="row" :class="{ on: sel?.id === r.id }" @click="open(r.id)">
          <b>{{ $td(r.title) }}</b><span class="small muted">{{ r.summary.slice(0, 70) }}…</span>
          <span class="small muted">{{ $td(r.created_by) }} · {{ r.engine === 'rules' ? $t('规则文字') : $t('AI 改写') }}</span>
        </button>
      </div>
      <article v-if="sel" class="card rpt">
        <header><h2>{{ $td(sel.title) }}</h2>
          <span class="small muted">{{ fmtTs(sel.period_start) }} — {{ fmtTs(sel.period_end) }} · {{ $td(sel.key) }} · {{ sel.engine === 'rules' ? $t('规则文字') : $t('AI 改写（数字已核对）') }}</span>
          <button class="btn sm noprint r" @click="print">{{ $t('打印') }}</button></header>
        <pre class="txt">{{ $td(sel.text) }}</pre>
        <h3>{{ $t('关键指标') }}</h3>
        <div class="tiles">
          <div v-for="t in tiles" :key="t[0]" class="tile"><span class="small muted">{{ $td(t[0]) }}</span><b>{{ $td(t[1]) }}</b></div>
        </div>
        <h3>{{ $t('异常') }}</h3>
        <table class="tbl small"><thead><tr><th>{{ $t('领域') }}</th><th class="num">{{ $t('新发现') }}</th><th class="num">{{ $t('处理完') }}</th><th class="num">{{ $t('还开着') }}</th></tr></thead>
          <tbody><tr v-for="(v, k) in d.anomalies.by_domain" :key="k"><td>{{ domLabel(k) }}</td><td class="num">{{ $td(v.new) }}</td><td class="num">{{ $td(v.closed) }}</td><td class="num">{{ $td(v.open) }}</td></tr>
            <tr class="sum"><td>{{ $t('合计') }}</td><td class="num">{{ $td(d.anomalies.new) }}</td><td class="num">{{ $td(d.anomalies.closed) }}</td><td class="num">{{ $td(d.anomalies.open) }}</td></tr></tbody></table>
        <h3>{{ $t('{a}要关注', { a: sel.kind === 'daily' ? $t('今天') : $t('本周') }) }}</h3>
        <ol class="small"><li v-for="(f, i) in d.focus" :key="i"><router-link :to="f.url">{{ $td(f.text) }}</router-link></li></ol>
        <template v-if="d.risk_orders.length"><h3>{{ $t('交付风险') }}</h3>
          <table class="tbl small"><thead><tr><th>{{ $t('订单') }}</th><th>{{ $t('客户') }}</th><th>{{ $t('交期') }}</th><th>{{ $t('预计') }}</th><th>{{ $t('情况') }}</th></tr></thead>
            <tbody><tr v-for="o in d.risk_orders" :key="o.name"><td class="mono">{{ $td(o.name) }}</td><td>{{ $td(o.customer) }}</td><td>{{ $td(o.delivery_date) }}</td>
              <td>{{ o.projected || '—' }}</td><td>{{ $td(o.risk) }}</td></tr></tbody></table></template>
        <template v-if="d.service"><h3>{{ $t('客户与服务') }}</h3>
          <p class="small">{{ $t('新投诉 {a} 张、开着 {b} 张 · 完成服务 {c} 单、待上门 {d} 单 ·满意度 {e} · 平均响应 {f} 小时 · 保修成本 ${g}', { a: $td(d.service.new_complaints), b: $td(d.service.open_complaints), c: $td(d.service.jobs_done), d: $td(d.service.open_jobs), e: d.service.satisfaction ?? '—', f: d.service.response_h ?? '—', g: Math.round(d.service.warranty_cost || 0).toLocaleString() }) }}</p></template>
        <template v-if="d.maint"><h3>{{ $t('设备维护') }}</h3>
          <p class="small">{{ $t('故障 {a} 次（停机 {b} 分钟）· 完成保养 {c} 次 · 保养逾期 {d} 台{e} · 开着的维修单 {f} 张 ·平均故障间隔 {g} 小时', { a: $td(d.maint.failures), b: $td(d.maint.failure_down_min), c: $td(d.maint.pms_done), d: $td(d.maint.overdue), e: d.maint.overdue_units?.length ? $t('（') + d.maint.overdue_units.map((u) => u.toUpperCase()).join($t('、')) + $t('）') : '', f: $td(d.maint.open_repairs), g: d.maint.mtbf ?? '—' }) }}</p></template>
        <template v-if="d.ehs"><h3>{{ $t('安全环保') }}</h3>
          <p class="small">{{ $t('新隐患 {a} 条（重大 {b}）· 整改关闭 {c} 条 · 还开着 {d} 条（重大 {e}、逾期 {f}）·挂牌上锁 {g} 台 · 培训 30 天内到期 {h} 项 · 近 30 天未遂 {i} 起', { a: $td(d.ehs.new_issues), b: $td(d.ehs.new_major), c: $td(d.ehs.closed), d: $td(d.ehs.open_issues), e: $td(d.ehs.major_open), f: $td(d.ehs.overdue), g: $td(d.ehs.locked), h: $td(d.ehs.training_due), i: $td(d.ehs.near_miss_30d) }) }}</p></template>
        <h3>{{ $t('动作') }}</h3>
        <p class="small">{{ $t('共 {a} 个', { a: $td(d.actions.total) }) }}<template v-for="(n, s) in d.actions.by_status" :key="s"> · {{ ST[s] || s }} {{ n }}</template></p>
        <ul v-if="d.actions.executed.length" class="small"><li v-for="a in d.actions.executed" :key="a.key">{{ $t('{a} {b}（{c}）', { a: $td(a.key), b: $td(a.title), c: $td(ST[a.status]) }) }}</li></ul>
        <template v-if="d.retros.length"><h3>{{ $t('推演与实际') }}</h3>
          <ul class="small"><li v-for="r in d.retros" :key="r.key">{{ $t('{a} {b}：完工偏差 {c}', { a: $td(r.key), b: $td(r.title), c: r.finish_pct == null ? '—' : (r.finish_pct > 0 ? '+' : '') + r.finish_pct + '%' }) }}</li></ul></template>
        <template v-if="sel.kind === 'weekly'">
          <template v-if="Object.keys(d.trends || {}).length"><h3>{{ $t('趋势（每天一个点）') }}</h3>
            <table class="tbl small"><tbody><tr v-for="(pts, m) in d.trends" :key="m"><td>{{ METRIC[m] || m }}</td>
              <td v-for="p in pts" :key="p[0]" class="num">{{ fmtMetric(m, p[1]) }}</td></tr></tbody></table></template>
          <template v-if="d.recurring?.length"><h3>{{ $t('反复出现的异常') }}</h3>
            <ul class="small"><li v-for="r in d.recurring" :key="r.rule + r.subject">{{ $t('{a}（{b} · {c}，{d} 次）', { a: $td(r.title), b: $td(r.rule), c: $td(r.subject), d: $td(r.n) }) }}</li></ul></template>
          <template v-if="d.cost_top?.length"><h3>{{ $t('成本差异前五') }}</h3>
            <table class="tbl small"><thead><tr><th>{{ $t('工单') }}</th><th class="num">{{ $t('差异') }}</th><th class="num">%</th><th>{{ $t('差得最多的工序') }}</th></tr></thead>
              <tbody><tr v-for="c in d.cost_top" :key="c.work_order"><td class="mono">{{ $td(c.work_order) }}</td><td class="num">${{ $td(c.variance) }}</td>
                <td class="num">{{ c.variance_pct == null ? '—' : c.variance_pct.toFixed(1) }}</td><td>{{ $td(c.worst) }}</td></tr></tbody></table></template>
          <template v-if="d.rule_hits && Object.keys(d.rule_hits).length"><h3>{{ $t('规则命中') }}</h3>
            <p class="small"><span v-for="(n, r) in d.rule_hits" :key="r" class="hit">{{ r }} × {{ n }}</span></p></template>
        </template>
      </article>
    </div>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { get, post } from '../lib/api';
import { fmtTs, loadTypes, ont } from '../lib/ont';

const KINDS = { '': $t('全部'), daily: $t('日报'), weekly: $t('周报') };
const ST = { draft: $t('草稿'), submitted: $t('待批准'), approved: $t('已批准'), rejected: $t('已驳回'), executing: $t('执行中'), done: $t('已完成'), failed: $t('失败') };
const METRIC = { oee: 'OEE', on_time: $t('准时交付率'), fpy: $t('一次合格率'), down_min: $t('停机（分钟）'), cost_var: $t('成本偏差'), risk_orders: $t('风险订单'), short_items: $t('缺料项') };
const route = useRoute();
const kind = ref('');
const list = ref([]);
const sel = ref(null);
const err = ref('');
const busy = ref(false);
const teach = ref(true);
const canGen = ref(false);
const d = computed(() => sel.value?.data || {});
const pct = (v, n = 0) => (v == null ? '—' : (v * 100).toFixed(n) + '%');
const tiles = computed(() => {
  const k = d.value.kpis || {};
  return [['OEE', pct(k.oee)], [$t('准时交付率'), pct(k.on_time)], [$t('本周完工'), `${k.output_week}/${k.plan_week}`], [$t('一次合格率'), pct(k.fpy_week, 1)],
    [$t('在制品'), $t('{a} 件', { a: k.wip })], [$t('成本偏差'), k.cost_var == null ? '—' : (k.cost_var > 0 ? '+' : '') + (k.cost_var * 100).toFixed(1) + '%'],
    [$t('停机设备'), (k.down_machines || []).join($t('、')) || $t('无')]];
});
function fmtMetric(m, v) { return ['oee', 'on_time', 'fpy', 'cost_var'].includes(m) ? pct(v, 1) : Math.round(v); }
function domLabel(k) { return ont.domains[k]?.label || k; }
async function load() {
  try {
    const r = await get('/reports' + (kind.value ? '?kind=' + kind.value : ''));
    list.value = r.reports; teach.value = r.teach; canGen.value = r.can_generate;
    if (!sel.value && list.value.length) open(Number(route.query.id) || list.value[0].id);
  } catch (e) { err.value = e.message; }
}
async function open(id) { try { sel.value = await get('/reports/' + id); } catch (e) { err.value = e.message; } }
async function gen(k) {
  busy.value = true;
  try { sel.value = await post('/reports/generate', { kind: k }); await load(); } catch (e) { alert(e.message); } finally { busy.value = false; }
}
function print() { window.print(); }
onMounted(async () => { try { await loadTypes(); } catch { /* 领域名取不到就显示编号 */ } load(); });
</script>

<style scoped>
.back { color: var(--muted); font-weight: 500; }
.page-title { flex-wrap: wrap; }
.tabs { margin-left: auto; display: flex; gap: 4px; }
.tabs button { height: 30px; padding: 0 12px; border: 1px solid var(--line); background: var(--surface); border-radius: 6px; cursor: pointer; }
.tabs button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.gen { display: flex; gap: 8px; margin-bottom: 10px; }
.grid { display: grid; grid-template-columns: minmax(0, 300px) minmax(0, 1fr); gap: 14px; align-items: start; }
@media (max-width: 900px) { .grid { grid-template-columns: minmax(0, 1fr); } }
.list { padding: 6px; max-height: 78vh; overflow: auto; }
.row { display: flex; flex-direction: column; gap: 2px; text-align: left; width: 100%; border: none; background: none; padding: 8px; border-radius: 6px;
  cursor: pointer; border-bottom: 1px solid var(--line); }
.row.on, .row:hover { background: var(--surface-2); }
.rpt header { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.rpt h2 { font-size: 18px; margin: 0; }
.rpt h3 { font-size: 14px; margin: 16px 0 6px; }
.r { margin-left: auto; }
.txt { white-space: pre-wrap; background: var(--surface-2); border-radius: 8px; padding: 10px 12px; font-size: 13px; line-height: 1.6; font-family: inherit; }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; }
.tile { border: 1px solid var(--line); border-radius: 8px; padding: 8px; display: flex; flex-direction: column; gap: 2px; }
.tile b { font-size: 17px; }
.num { text-align: right; }
tr.sum td { font-weight: 600; }
.hit { display: inline-block; margin-right: 10px; }
.btn.sm { height: 28px; padding: 0 10px; }
@media print {
  .noprint, :global(.rail), :global(.top), :global(.drawer) { display: none !important; }
  .grid { display: block; }
  .rpt { border: none; box-shadow: none; }
}
</style>
