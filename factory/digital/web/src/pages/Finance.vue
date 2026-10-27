<!-- 经营与财务（第 18 轮 E7）：经营目标（指标树）、订单毛利、应收应付与现金流、预算；生产与成本（第 19 轮并进来）。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>经营与财务</h1>
      <span class="muted">订单 → 开票 → 收款 · 采购 → 收货 → 发票 → 付款 · 每张订单的毛利 · 经营目标与预算</span>
      <span class="tabs" data-help="fin-tabs" role="tablist"><button v-for="(l, k) in TABS" :key="k" type="button" role="tab" :class="{ on: tab === k }" @click="go(k)">{{ l }}</button></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="msg" class="ok small">{{ msg }}</div>

    <section v-if="kp" class="kpis" data-help="fin-kpis">
      <div class="card k"><span class="small muted">毛利率（做完的订单）</span><b :class="tone(kp.gross_margin, 0.25)">{{ pct1(kp.gross_margin) }}</b><span class="small muted">目标 25%</span></div>
      <div class="card k"><span class="small muted">应收 / 逾期</span><b>${{ num(kp.ar_total) }}</b><span class="small" :class="{ bad: kp.ar_overdue > 0 }">逾期 ${{ num(kp.ar_overdue) }}</span></div>
      <div class="card k"><span class="small muted">应收周转天数</span><b :class="{ warn: kp.dso > 45 }">{{ kp.dso ?? '—' }}</b><span class="small muted">账期日</span></div>
      <div class="card k"><span class="small muted">现金</span><b>${{ num(kp.cash) }}</b></div>
      <div class="card k"><span class="small muted">预算已用（本月）</span><b :class="{ warn: kp.budget_used > kp.progress * 1.1 }">{{ pct(kp.budget_used) }}</b><span class="small muted">月度进度 {{ pct(kp.progress) }}</span></div>
    </section>

    <!-- ① 经营目标 -->
    <template v-if="tab === 'objectives' && ob">
      <div class="card" data-help="fin-objectives">
        <h3>指标树（目标 → 指标 → 领域）</h3>
        <div class="tree">
          <div class="root">本年经营目标 <span class="small muted">达标 {{ ob.objectives.filter((o) => o.tone === 'good').length }} / {{ ob.objectives.length }}</span></div>
          <div v-for="o in ob.objectives" :key="o.code" class="node" :class="o.tone">
            <div class="nh"><b>{{ o.code }} {{ o.name }}</b><span class="dom small">{{ DOMAINS[o.domain] || o.domain }}</span></div>
            <div class="nv"><span class="big">{{ fmt(o, o.value) }}</span><span class="small muted"> 目标 {{ o.direction === 'ge' ? '≥' : '≤' }} {{ fmt(o, o.target) }}</span>
              <span class="pill" :class="o.tone">{{ TONE[o.tone] }}</span></div>
            <svg v-if="o.history.length > 1" class="spark" viewBox="0 0 100 24" preserveAspectRatio="none" :aria-label="o.name + ' 近 7 天'">
              <polyline :points="spark(o)" class="sl" /></svg>
            <div class="small muted">近 {{ o.history.length }} 天红 {{ o.red_days }} 天</div>
            <div v-if="ob.can_edit" class="row small"><input v-model.number="tg[o.code]" type="number" step="any" :aria-label="o.name + ' 目标'"><button class="linkbtn" @click="setTarget(o)">改目标</button></div>
          </div>
        </div>
        <p class="small muted">指标的数直接取各领域态势卡记下的数（每天一条），和指挥台一个口径。红 = 偏离超过 5%（“≤”的指标超过 10%）。</p>
      </div>
    </template>

    <!-- ② 订单毛利 -->
    <template v-if="tab === 'margins' && mg">
      <div class="card">
        <h3>做完的订单（工单全部完工）</h3>
        <table class="tbl small"><thead><tr><th>订单</th><th>客户</th><th class="num">台数</th><th class="num">收入</th><th class="num">成本</th><th class="num">毛利</th><th class="num">毛利率</th><th class="num">按标准</th><th></th></tr></thead>
          <tbody><tr v-for="m in mg.margins" :key="m.sales_order" :class="{ sel: sel?.sales_order === m.sales_order }">
            <td>{{ m.sales_order }}<span v-if="m.pseudo" class="muted">（估）</span></td><td>{{ (m.customer || '—').split(' ')[0] }}</td><td class="num">{{ m.qty }}</td>
            <td class="num">${{ num(m.revenue) }}</td><td class="num">${{ num(m.cost) }}</td><td class="num">${{ num(m.margin) }}</td>
            <td class="num" :class="tone(m.margin_pct, mg.target)">{{ pct1(m.margin_pct) }}</td><td class="num muted">{{ pct1(m.std_margin_pct) }}</td>
            <td><button class="linkbtn" @click="sel = m">分解</button></td></tr></tbody></table>
        <p v-if="!mg.margins.length" class="small muted">还没有做完的订单。</p>
        <p class="small muted">（估）：订单本身不在 ERPNext 快照里（情景里早先的订单），按它的工单件数和标准售价估。</p>
      </div>
      <div v-if="sel" class="card">
        <h3>{{ sel.sales_order }} 的毛利分解</h3>
        <div v-for="x in sel.lines" :key="x.key" class="bar-row">
          <span class="bn">{{ x.label }}</span>
          <span class="bar"><span :style="{ width: (x.usd / sel.revenue * 100).toFixed(2) + '%' }"></span></span>
          <span class="bv small">${{ num(x.usd) }}</span>
          <span class="bh small muted">{{ x.how }}<template v-if="x.actions?.length">：{{ x.actions.map((a) => a.title + ' $' + num(a.usd)).join('；') }}</template></span>
        </div>
        <p class="small">收入 ${{ num(sel.revenue) }} − 成本 ${{ num(sel.cost) }} = <b>${{ num(sel.margin) }}</b>（{{ pct1(sel.margin_pct) }}；按标准 {{ pct1(sel.std_margin_pct) }}）</p>
      </div>
    </template>

    <!-- ③ 应收应付 -->
    <template v-if="tab === 'arap' && ar">
      <div class="card">
        <h3>应收账龄</h3>
        <div class="aging"><div v-for="(l, k) in ar.buckets" :key="k" class="ag" :class="k"><span class="small muted">{{ l }}</span><b>${{ num(ar.aging[k]) }}</b></div></div>
        <table class="tbl small"><thead><tr><th>发票</th><th>客户</th><th>订单</th><th class="num">未付</th><th>到期</th><th class="num">逾期（天）</th><th>状态</th><th>催款</th></tr></thead>
          <tbody><tr v-for="x in ar.invoices" :key="x.id"><td>{{ x.doc || '期初 #' + x.id }}</td><td>{{ x.party.split(' ')[0] }}</td><td>{{ x.ref }}</td>
            <td class="num">${{ num(x.outstanding) }}</td><td>{{ x.due_at.slice(5, 16).replace('T', ' ') }}</td>
            <td class="num" :class="{ bad: x.overdue_days > 30, warn: x.overdue_days > 0 }">{{ x.overdue_days > 0 ? x.overdue_days : '—' }}</td>
            <td>{{ x.status_label }}</td><td>{{ x.dunned_n ? x.dunned_n + ' 次' : '' }}</td></tr></tbody></table>
        <p class="small muted">账期日：{{ ar.day_s === 86400 ? '1 天' : '教学模式 1 天 = 真实 ' + ar.day_s / 60 + ' 分钟' }}；付款条件 30 天。应收周转天数 {{ ar.dso ?? '—' }} 天。催款、信用冻结走厂情中枢“应收逾期”“信用超限”异常的右栏。</p>
      </div>
      <div class="card">
        <h3>客户信用</h3>
        <table class="tbl small"><thead><tr><th>客户</th><th class="num">额度</th><th class="num">应收</th><th class="num">在做没开票</th><th class="num">占用</th><th class="num">逾期</th><th>冻结</th></tr></thead>
          <tbody><tr v-for="c in ar.credit" :key="c.customer"><td>{{ c.customer.split(' ')[0] }}</td><td class="num">${{ num(c.limit) }}</td><td class="num">${{ num(c.balance) }}</td>
            <td class="num">${{ num(c.open_orders) }}</td><td class="num" :class="{ bad: c.used > 1 }">{{ pct(c.used) }}</td><td class="num">${{ num(c.overdue) }}</td>
            <td :class="{ bad: c.hold }">{{ c.hold ? '冻结中' : '' }}</td></tr></tbody></table>
      </div>
      <div v-if="cf" class="card">
        <h3>现金流预测（未来 8 周，账期周）</h3>
        <svg class="cash" viewBox="0 0 800 160" preserveAspectRatio="none" role="img" aria-label="现金流预测">
          <line x1="0" x2="800" :y1="yc(0)" :y2="yc(0)" class="zero" />
          <rect v-for="(w, i) in cf.weeks" :key="i" :x="i * 100 + 20" width="60" :y="Math.min(yc(w.balance), yc(0))" :height="Math.abs(yc(w.balance) - yc(0))" :class="w.balance < 0 ? 'neg' : 'pos'" />
        </svg>
        <table class="tbl small"><thead><tr><th>周</th><th class="num">收款</th><th class="num">支出</th><th class="num">周末现金</th></tr></thead>
          <tbody><tr v-for="w in cf.weeks" :key="w.week" :class="{ sel: w.week === cf.low.week }"><td>第 {{ w.week }} 周</td><td class="num">${{ num(w.in) }}</td><td class="num">${{ num(w.out) }}</td>
            <td class="num" :class="{ bad: w.balance < 0 }">${{ num(w.balance) }}</td></tr></tbody></table>
        <p class="small muted">现在现金 ${{ num(cf.cash) }}；收款按到期日 + 这个客户平时晚几天（催过的按 3 天内），支出 = 应付到期 + 每周固定开支 ${{ num(cf.weekly_expense) }}。</p>
      </div>
      <div v-if="apd" class="card">
        <h3>应付（供应商发票）</h3>
        <table class="tbl small"><thead><tr><th>发票</th><th>供应商</th><th>收货单</th><th class="num">未付</th><th>付款日</th><th>状态</th></tr></thead>
          <tbody><tr v-for="x in apd.invoices" :key="x.id"><td>{{ x.doc || '#' + x.id }}</td><td>{{ x.party.split(' ')[0] }}</td><td>{{ x.ref }}</td>
            <td class="num">${{ num(x.outstanding) }}</td><td>{{ x.pay_at.slice(5, 16).replace('T', ' ') }}</td><td>{{ x.status_label }}</td></tr></tbody></table>
        <p v-if="!apd.invoices.length" class="small muted">没有未付的供应商发票。</p>
      </div>
      <div v-if="ar.teacher" class="card">
        <h3>老师：财务模拟器 <span class="small" :class="ar.sim ? 'ok' : 'muted'">{{ ar.sim ? '开（客户按习惯晚付）' : '关（按时付）' }}</span></h3>
        <div class="row small"><button class="btn sm" @click="sim({ sim: !ar.sim })">{{ ar.sim ? '关闭' : '打开' }}</button>
          <select v-model="inj.customer" aria-label="客户"><option v-for="c in ar.credit" :key="c.customer" :value="c.customer">{{ c.customer.split(' ')[0] }}</option></select>
          <label>逾期 <input v-model.number="inj.days" type="number" min="1" max="90"> 天</label>
          <button class="btn sm danger" @click="sim({ inject: { ...inj } })">注入一笔不付的发票</button></div>
      </div>
    </template>

    <!-- ④ 预算 -->
    <ProductionCost v-if="tab === 'production'" data-help="fin-production" />

    <template v-if="tab === 'budget' && bd">
      <div class="card">
        <h3>{{ bd.month }} 预算（月度进度 {{ pct(bd.progress) }}）</h3>
        <div v-for="x in bd.rows" :key="x.center" class="bar-row b4">
          <span class="bn">{{ x.name }}</span>
          <span class="bar"><span :class="{ over: x.ratio > 1.1 }" :style="{ width: Math.min(100, x.actual / (x.budget || 1) * 100).toFixed(2) + '%' }"></span>
            <i class="mark" :style="{ left: (bd.progress * 100).toFixed(2) + '%' }"></i></span>
          <span class="bv small">${{ num(x.actual) }} / ${{ num(x.budget) }}</span>
          <span class="small" :class="{ bad: x.ratio > 1.1 }">{{ x.over > 0 ? '超 $' + num(x.over) : '' }}</span>
          <span v-if="bd.can_edit" class="row small"><input v-model.number="bg[x.center]" type="number" step="100" :aria-label="x.name + ' 预算'"><button class="linkbtn" @click="setBudget(x)">改</button></span>
        </div>
        <p class="small muted">竖线是月度进度：实际超过“预算 × 进度 × 1.1”厂情中枢报“预算超支”。实际的来源：工时（车间实测）、采购发票、电费（能源计量）、维修和服务动作的费用、不合格件；管理费用按进度计。</p>
      </div>
    </template>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post } from '../lib/api';
import ProductionCost from '../components/ProductionCost.vue';

const TABS = { objectives: '经营目标', margins: '订单毛利', arap: '应收应付', budget: '预算', production: '生产与成本' };   // 生产与成本：原“经营与成本”页（第 19 轮 J-8）
const TONE = { good: '达标', warn: '接近', bad: '偏离', mute: '没有数' };
const DOMAINS = { sales: '订单与交付', finance: '财务', quality: '质量', production: '生产', energy: '能源', ehs: '安全环保' };
const route = useRoute();
const router = useRouter();
const tab = ref(TABS[route.query.tab] ? route.query.tab : 'objectives');
const err = ref('');
const msg = ref('');
const kp = ref(null);
const ob = ref(null);
const mg = ref(null);
const sel = ref(null);
const ar = ref(null);
const apd = ref(null);
const cf = ref(null);
const bd = ref(null);
const tg = reactive({});
const bg = reactive({});
const inj = reactive({ customer: '', days: 15 });
const num = (v) => (v === null || v === undefined ? '—' : Math.round(v).toLocaleString());
const pct = (v) => (v === null || v === undefined ? '—' : Math.round(v * 100) + '%');
const pct1 = (v) => (v === null || v === undefined ? '—' : (v * 100).toFixed(1) + '%');
const tone = (v, t) => (v === null || v === undefined ? '' : (v >= t ? 'ok' : (v >= t - 0.05 ? 'warn' : 'bad')));
const fmt = (o, v) => (v === null || v === undefined ? '—' : (o.unit === 'pct' ? Math.round(v * 1000) / 10 + '%' : Math.round(v * 10) / 10));
function spark(o) {
  const vs = o.history.map((h) => h[1]); const lo = Math.min(...vs, o.target); const hi = Math.max(...vs, o.target); const r = hi - lo || 1;
  return vs.map((v, i) => (i * 100 / (vs.length - 1)).toFixed(1) + ',' + (22 - 20 * (v - lo) / r).toFixed(1)).join(' ');
}
function yc(v) { const m = Math.max(1, ...cf.value.weeks.map((w) => Math.abs(w.balance))); return 80 - 75 * v / m; }

function go(k) { tab.value = k; router.replace({ query: { ...route.query, tab: k } }); load(); }
async function wrap(fn) { err.value = ''; try { await fn(); } catch (e) { err.value = e.message; } }
function load() {
  wrap(async () => { kp.value = await get('/finance/kpis'); });
  if (tab.value === 'objectives') wrap(async () => { ob.value = await get('/finance/objectives'); for (const o of ob.value.objectives) tg[o.code] ??= o.target; });
  if (tab.value === 'margins') wrap(async () => { mg.value = await get('/finance/margins'); if (mg.value.margins.length && !sel.value) sel.value = mg.value.margins[0]; });
  if (tab.value === 'arap') {
    wrap(async () => { ar.value = await get('/finance/ar'); inj.customer ||= ar.value.credit[ar.value.credit.length - 1]?.customer || ''; });
    wrap(async () => { cf.value = await get('/finance/cashflow'); });
    wrap(async () => { apd.value = await get('/finance/ap'); });
  }
  if (tab.value === 'budget') wrap(async () => { bd.value = await get('/finance/budget'); for (const x of bd.value.rows) bg[x.center] ??= x.budget; });
}
async function setTarget(o) { await wrap(async () => { await post('/finance/objectives', { code: o.code, target: tg[o.code] }); msg.value = o.name + ' 目标已改'; load(); }); }
async function setBudget(x) { await wrap(async () => { await post('/finance/budget', { center: x.center, amount: bg[x.center] }); msg.value = x.name + ' 预算已改'; load(); }); }
async function sim(body) { await wrap(async () => { const r = await post('/finance/sim', body); msg.value = r.text || ('模拟器' + (r.sim ? '已打开' : '已关闭')); load(); }); }
load();
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.tabs { margin-left: auto; display: flex; gap: 4px; flex-wrap: wrap; }
.tabs button { height: 30px; padding: 0 12px; border: 1px solid var(--line); background: var(--surface); border-radius: 6px; cursor: pointer; }
.tabs button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; margin-bottom: 12px; }
.k { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; }
.k b { font-size: 22px; }
.tree { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
.root { grid-column: 1 / -1; font-weight: 600; border-bottom: 2px solid var(--line); padding-bottom: 4px; }
.node { border: 1px solid var(--line); border-left: 4px solid var(--line); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 4px; }
.node.good { border-left-color: var(--good); }
.node.warn { border-left-color: var(--warn); }
.node.bad { border-left-color: var(--bad); }
.nh { display: flex; gap: 6px; align-items: baseline; justify-content: space-between; }
.dom { background: var(--surface-2); border-radius: 4px; padding: 0 6px; }
.big { font-size: 20px; font-weight: 600; }
.pill { margin-left: 6px; font-size: 11px; padding: 0 6px; border-radius: 8px; background: var(--surface-2); }
.pill.good { color: var(--good); }
.pill.warn { color: var(--warn); }
.pill.bad { color: var(--bad); }
.spark { width: 100%; height: 24px; }
.sl { fill: none; stroke: var(--accent); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.bar-row { display: grid; grid-template-columns: 150px 1fr 110px; gap: 8px; align-items: center; margin: 4px 0; }
.bar-row .bh { grid-column: 2 / -1; margin-top: -2px; }
.bar-row.b4 { grid-template-columns: 120px 1fr 150px 90px auto; }
.bn { font-size: 12px; }
.bar { position: relative; display: flex; height: 14px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }
.bar span { display: block; height: 100%; background: var(--accent); }
.bar span.over { background: var(--bad); }
.mark { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--text, #222); }
.bv { text-align: right; }
.aging { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 8px; }
.ag { display: flex; flex-direction: column; border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; }
.ag.d30 b { color: var(--warn); }
.ag.d60 b, .ag.d60p b { color: var(--bad); }
.cash { width: 100%; height: 160px; background: var(--surface-2); border-radius: 6px; }
.cash .pos { fill: var(--accent); }
.cash .neg { fill: var(--bad); }
.cash .zero { stroke: var(--line); stroke-width: 1; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
select, input { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; min-width: 0; }
input[type=number] { width: 90px; }
.card .tbl { display: block; overflow-x: auto; }
tr.sel td { background: var(--surface-2); }
.bad { color: var(--bad); }
.warn { color: var(--warn); }
.ok { color: var(--good); }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; padding: 0 4px; }
.btn.sm { height: 28px; padding: 0 10px; }
h3 { font-size: 14px; margin: 8px 0 6px; }
.num { text-align: right; }
@media (max-width: 600px) {
  .bar-row, .bar-row.b4 { grid-template-columns: 100px 1fr; }
  .bar-row .bv, .bar-row .bh { grid-column: 1 / -1; text-align: left; }
  .aging { grid-template-columns: repeat(2, 1fr); }
}
</style>
