<!-- 厂情日报 / 经营周报（第 17 轮 D 期 D7）：数字全部来自历史库；生产模式按时自动生成，教学模式点“生成” -->
<template>
  <div class="page">
    <div class="page-title noprint"><h1><router-link to="/ont" class="back">厂情中枢</router-link> / 日报与周报</h1>
      <span class="muted">{{ teach ? '教学模式：点“生成”即时生成最近 24 小时（日报）或 7 天（周报）的报告，可作实验材料' : '生产模式：每天 07:30 生成前一天的日报，每周一 08:00 生成上周的周报，按订阅推送' }}</span>
      <span class="tabs"><button v-for="(l, k) in KINDS" :key="k" :class="{ on: kind === k }" @click="kind = k; load()">{{ l }}</button></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="canGen" class="gen noprint">
      <button class="btn primary sm" :disabled="busy" @click="gen('daily')">{{ busy ? '生成中…' : teach ? '生成今天的日报' : '补生成日报' }}</button>
      <button class="btn sm" :disabled="busy" @click="gen('weekly')">{{ teach ? '生成本周的周报' : '补生成周报' }}</button>
    </div>
    <div class="grid">
      <div class="card list noprint">
        <p v-if="!list.length" class="muted small">还没有报告。</p>
        <button v-for="r in list" :key="r.id" class="row" :class="{ on: sel?.id === r.id }" @click="open(r.id)">
          <b>{{ r.title }}</b><span class="small muted">{{ r.summary.slice(0, 70) }}…</span>
          <span class="small muted">{{ r.created_by }} · {{ r.engine === 'rules' ? '规则文字' : 'AI 改写' }}</span>
        </button>
      </div>
      <article v-if="sel" class="card rpt">
        <header><h2>{{ sel.title }}</h2>
          <span class="small muted">{{ fmtTs(sel.period_start) }} — {{ fmtTs(sel.period_end) }} · {{ sel.key }} · {{ sel.engine === 'rules' ? '规则文字' : 'AI 改写（数字已核对）' }}</span>
          <button class="btn sm noprint r" @click="print">打印</button></header>
        <pre class="txt">{{ sel.text }}</pre>
        <h3>关键指标</h3>
        <div class="tiles">
          <div v-for="t in tiles" :key="t[0]" class="tile"><span class="small muted">{{ t[0] }}</span><b>{{ t[1] }}</b></div>
        </div>
        <h3>异常</h3>
        <table class="tbl small"><thead><tr><th>领域</th><th class="num">新发现</th><th class="num">处理完</th><th class="num">还开着</th></tr></thead>
          <tbody><tr v-for="(v, k) in d.anomalies.by_domain" :key="k"><td>{{ domLabel(k) }}</td><td class="num">{{ v.new }}</td><td class="num">{{ v.closed }}</td><td class="num">{{ v.open }}</td></tr>
            <tr class="sum"><td>合计</td><td class="num">{{ d.anomalies.new }}</td><td class="num">{{ d.anomalies.closed }}</td><td class="num">{{ d.anomalies.open }}</td></tr></tbody></table>
        <h3>{{ sel.kind === 'daily' ? '今天' : '本周' }}要关注</h3>
        <ol class="small"><li v-for="(f, i) in d.focus" :key="i"><router-link :to="f.url">{{ f.text }}</router-link></li></ol>
        <template v-if="d.risk_orders.length"><h3>交付风险</h3>
          <table class="tbl small"><thead><tr><th>订单</th><th>客户</th><th>交期</th><th>预计</th><th>情况</th></tr></thead>
            <tbody><tr v-for="o in d.risk_orders" :key="o.name"><td class="mono">{{ o.name }}</td><td>{{ o.customer }}</td><td>{{ o.delivery_date }}</td>
              <td>{{ o.projected || '—' }}</td><td>{{ o.risk }}</td></tr></tbody></table></template>
        <h3>动作</h3>
        <p class="small">共 {{ d.actions.total }} 个<template v-for="(n, s) in d.actions.by_status" :key="s"> · {{ ST[s] || s }} {{ n }}</template></p>
        <ul v-if="d.actions.executed.length" class="small"><li v-for="a in d.actions.executed" :key="a.key">{{ a.key }} {{ a.title }}（{{ ST[a.status] }}）</li></ul>
        <template v-if="d.retros.length"><h3>推演与实际</h3>
          <ul class="small"><li v-for="r in d.retros" :key="r.key">{{ r.key }} {{ r.title }}：完工偏差 {{ r.finish_pct == null ? '—' : (r.finish_pct > 0 ? '+' : '') + r.finish_pct + '%' }}</li></ul></template>
        <template v-if="sel.kind === 'weekly'">
          <template v-if="Object.keys(d.trends || {}).length"><h3>趋势（每天一个点）</h3>
            <table class="tbl small"><tbody><tr v-for="(pts, m) in d.trends" :key="m"><td>{{ METRIC[m] || m }}</td>
              <td v-for="p in pts" :key="p[0]" class="num">{{ fmtMetric(m, p[1]) }}</td></tr></tbody></table></template>
          <template v-if="d.recurring?.length"><h3>反复出现的异常</h3>
            <ul class="small"><li v-for="r in d.recurring" :key="r.rule + r.subject">{{ r.title }}（{{ r.rule }} · {{ r.subject }}，{{ r.n }} 次）</li></ul></template>
          <template v-if="d.cost_top?.length"><h3>成本差异前五</h3>
            <table class="tbl small"><thead><tr><th>工单</th><th class="num">差异</th><th class="num">%</th><th>差得最多的工序</th></tr></thead>
              <tbody><tr v-for="c in d.cost_top" :key="c.work_order"><td class="mono">{{ c.work_order }}</td><td class="num">${{ c.variance }}</td>
                <td class="num">{{ c.variance_pct == null ? '—' : c.variance_pct.toFixed(1) }}</td><td>{{ c.worst }}</td></tr></tbody></table></template>
          <template v-if="d.rule_hits && Object.keys(d.rule_hits).length"><h3>规则命中</h3>
            <p class="small"><span v-for="(n, r) in d.rule_hits" :key="r" class="hit">{{ r }} × {{ n }}</span></p></template>
        </template>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { get, post } from '../lib/api';
import { fmtTs, loadTypes, ont } from '../lib/ont';

const KINDS = { '': '全部', daily: '日报', weekly: '周报' };
const ST = { draft: '草稿', submitted: '待批准', approved: '已批准', rejected: '已驳回', executing: '执行中', done: '已完成', failed: '失败' };
const METRIC = { oee: 'OEE', on_time: '准时交付率', fpy: '一次合格率', down_min: '停机（分钟）', cost_var: '成本偏差', risk_orders: '风险订单', short_items: '缺料项' };
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
  return [['OEE', pct(k.oee)], ['准时交付率', pct(k.on_time)], ['本周完工', `${k.output_week}/${k.plan_week}`], ['一次合格率', pct(k.fpy_week, 1)],
    ['在制品', `${k.wip} 件`], ['成本偏差', k.cost_var == null ? '—' : (k.cost_var > 0 ? '+' : '') + (k.cost_var * 100).toFixed(1) + '%'],
    ['停机设备', (k.down_machines || []).join('、') || '无']];
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
