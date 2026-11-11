<!-- 客户与服务——现场的机器人（第 64 轮，机器人厂）：已装机台账、远程监测（背隙、温度、电流、碰撞）、出厂档案追到减速器批次、投诉与服务工单、回访。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('客户与服务 · 现场的机器人') }}</h1>
      <span class="muted">{{ $t('发到客户现场的机器人每个现场日回传一条运行摘要（教学模式 1 分钟 = 1 个现场日；数据是示例值）') }}</span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="msg" class="ok-msg small">{{ msg }}</div>

    <section v-if="kp" class="kpis" data-help="rs-kpis">
      <div class="card k"><span class="small muted">{{ $t('在现场') }}</span><b>{{ $td(kp.in_field) }}</b><span class="small muted">{{ $t('出厂待发 {a}', { a: $td(kp.built) }) }}</span></div>
      <div class="card k"><span class="small muted">{{ $t('报警') }}</span><b :class="{ 'bad-t': kp.red }">{{ $t('红 {a} · 黄 {b}', { a: $td(kp.red), b: $td(kp.yellow) }) }}</b></div>
      <div class="card k"><span class="small muted">{{ $t('投诉') }}</span><b>{{ $td(kp.open_complaints) }}</b><span class="small muted">{{ $t('共 {a}，未关闭 {b}', { a: $td(kp.complaints), b: $td(kp.open_complaints) }) }}</span></div>
      <div class="card k"><span class="small muted">{{ $t('服务工单（未完成）') }}</span><b>{{ $td(kp.open_jobs) }}</b></div>
      <div class="card k"><span class="small muted">{{ $t('满意度') }}</span><b>{{ kp.satisfaction ?? '—' }}</b><span class="small muted">{{ $t('现场日 {a}', { a: $td(kp.field_day) }) }}</span></div>
    </section>

    <div class="row">
      <span class="tabs" data-help="rs-tabs" role="tablist"><button v-for="(l, k) in TABS" :key="k" type="button" role="tab" :class="{ on: tab === k }" @click="tab = k; load()">{{ l }}</button></span>
      <button class="btn ghost sm" @click="load">{{ $t('刷新') }}</button>
      <span v-if="fl?.teacher" class="small">{{ $t('老师：') }}<button class="btn ghost sm" @click="advance(30)">{{ $t('现场时钟往前 30 天') }}</button></span>
    </div>

    <template v-if="tab === 'fleet' && fl">
      <section class="card" data-help="rs-fleet">
        <div class="scroll"><table class="tbl small">
          <thead><tr><th>{{ $t('序列号') }}</th><th>{{ $t('客户') }}</th><th>{{ $t('状态') }}</th><th class="num">{{ $t('运行小时') }}</th><th>{{ $t('最差的关节') }}</th><th>{{ $t('健康') }}</th><th>{{ $t('原因') }}</th></tr></thead>
          <tbody><tr v-for="r in fl.robots" :key="r.serial" :class="{ sel: r.serial === sel }" @click="open(r.serial)">
            <td class="mono">{{ $td(r.serial) }}</td><td>{{ short(r.customer) }}</td><td>{{ r.status === 'field' ? $t('在现场') : $t('出厂待发') }}</td>
            <td class="num">{{ r.run_h.toLocaleString() }}</td>
            <td>{{ r.worst ? r.worst.joint + ' ' + r.worst.backlash.toFixed(2) + '′ / ' + r.worst.limit + '′' : '—' }}</td>
            <td><span class="dot" :class="r.health"></span>{{ $td(HL[r.health]) }}</td>
            <td class="small">{{ r.why.map((w) => $td(w.text)).join($t('；')) || '—' }}</td></tr></tbody></table></div>
      </section>

      <section v-if="dt" class="card" data-help="rs-detail">
        <div class="card-head"><h2 class="mono">{{ $td(dt.serial) }}</h2><span class="muted small">{{ $t('{a}{b} · 运行 {c} h', { a: $td(dt.customer), b: dt.site ? ' · ' + dt.site.what : '', c: dt.run_h.toLocaleString() }) }}</span></div>
        <p v-if="dt.why.length" class="small"><b>{{ $t('报警：') }}</b>{{ dt.why.map((w) => w.text).join($t('；')) }}</p>
        <h3>{{ $t('背隙趋势（arcmin，近 120 个现场日；虚线 = 上限）') }}</h3>
        <svg v-if="dt.series.length" :viewBox="'0 0 ' + W + ' ' + Hh" class="chart" role="img" :aria-label="$t('背隙趋势')">
          <g v-for="(j, i) in dt.as_built.joints" :key="j.joint">
            <polyline :points="line(i)" fill="none" :stroke="COLORS[i]" stroke-width="1.6" />
            <text :x="W - 34" :y="yOf(last(i)) + 4" :fill="COLORS[i]" font-size="11">{{ $td(j.joint) }}</text>
          </g>
          <line v-for="lim in [1.0, 1.2]" :key="lim" x1="30" :x2="W - 40" :y1="yOf(lim)" :y2="yOf(lim)" stroke="currentColor" stroke-dasharray="4 4" opacity=".5" />
          <text x="2" :y="yOf(1.2) + 4" font-size="10" fill="currentColor">1.2</text><text x="2" :y="yOf(1.0) + 4" font-size="10" fill="currentColor">1.0</text>
          <text x="2" :y="yOf(0.6) + 4" font-size="10" fill="currentColor">0.6</text>
        </svg>
        <h3>{{ $t('出厂档案（关节 → 谐波减速器批次）') }}</h3>
        <div class="scroll"><table class="tbl small">
          <thead><tr><th>{{ $t('关节') }}</th><th>{{ $t('模组') }}</th><th>{{ $t('关节序列号') }}</th><th>{{ $t('减速器批次') }}</th><th class="num">{{ $t('出厂背隙') }}</th><th class="num">{{ $t('现在') }}</th><th class="num">{{ $t('温度峰值') }}</th><th class="num">{{ $t('电流') }}</th><th>{{ $t('同批还装在') }}</th></tr></thead>
          <tbody><tr v-for="(j, i) in dt.as_built.joints" :key="j.joint">
            <td>{{ $td(j.joint) }}</td><td>{{ $td(j.item) }}</td><td class="mono">{{ $td(j.serial) }}</td>
            <td class="mono" :class="{ 'bad-t': j.bad }">{{ j.lot || '—' }}{{ j.replaced ? $t('（换过，原批 ') + (j.replaced.lot || '—') + $t('）') : '' }}</td>
            <td class="num">{{ j.backlash0.toFixed(2) }}′</td><td class="num">{{ cur(i)?.backlash?.toFixed(2) ?? '—' }}′</td>
            <td class="num">{{ cur(i)?.temp_max ?? '—' }} ℃</td><td class="num">{{ cur(i)?.i_rms ?? '—' }} A</td>
            <td class="small">{{ sameLot(j) }}</td></tr></tbody></table></div>
        <p class="small muted">{{ $t('标定后绝对定位误差 {a} mm；工单 {b}；销售订单 {c}；{d}', { a: dt.as_built.cr_abs ?? '—', b: dt.wo || '—', c: dt.sales_order || '—', d: $td(dt.as_built.source) }) }}</p>
        <div class="row">
          <label>{{ $t('服务方案') }} <select v-model="nj.kind" :aria-label="$t('服务方案')"><option v-for="(l, k) in fl.kinds" :key="k" :value="k">{{ $td(l) }}</option></select></label>
          <label v-if="nj.kind === 'swap'">{{ $t('关节') }} <select v-model="nj.joint" :aria-label="$t('关节')"><option v-for="j in dt.as_built.joints" :key="j.joint" :value="j.joint">{{ $td(j.joint) }}</option></select></label>
          <button class="btn primary sm" @click="plan">{{ $t('派工') }}</button>
        </div>
        <table v-if="dt.jobs.length" class="tbl small"><thead><tr><th>{{ $t('工单') }}</th><th>{{ $t('方案') }}</th><th>{{ $t('工程师') }}</th><th>{{ $t('日子') }}</th><th>{{ $t('状态') }}</th><th class="num">{{ $t('费用') }}</th></tr></thead>
          <tbody><tr v-for="j in dt.jobs" :key="j.id"><td class="mono">{{ $td(j.key) }}</td><td>{{ $td(j.kind_label) }}{{ j.joint ? ' ' + j.joint : '' }}</td><td>{{ $td(j.engineer) }}</td>
            <td>{{ j.done_day || j.plan_day }}</td><td>{{ $td(j.status_label) }}</td><td class="num">${{ j.cost_usd.toLocaleString() }}</td></tr></tbody></table>
      </section>
    </template>

    <template v-if="tab === 'cases' && cs">
      <section class="card" data-help="rs-new">
        <div class="card-head"><h2>{{ $t('登记一条投诉') }}</h2><span class="muted small">{{ $t('同时在 ERPNext 开一张问题单（Issue）') }}</span></div>
        <div class="row">
          <label>{{ $t('机器人') }} <select v-model="nc.serial" :aria-label="$t('机器人')"><option value="">—</option><option v-for="r in fl?.robots || []" :key="r.serial" :value="r.serial">{{ $td(r.serial) }}</option></select></label>
          <label>{{ $t('现象') }} <input v-model="nc.subject" :placeholder="$t('如：J2 有异响，抓取位置偏了')" class="wide"></label>
          <button class="btn primary sm" @click="complain">{{ $t('登记') }}</button>
        </div>
      </section>
      <section class="card">
        <div class="card-head"><h2>{{ $t('投诉') }}</h2></div>
        <p v-if="!cs.complaints.length" class="empty">{{ $t('还没有投诉。') }}</p>
        <div v-else class="scroll"><table class="tbl small">
          <thead><tr><th>{{ $t('编号') }}</th><th>{{ $t('机器人') }}</th><th>{{ $t('客户') }}</th><th>{{ $t('现象') }}</th><th>ERPNext</th><th>{{ $t('状态') }}</th><th>{{ $t('满意度') }}</th><th></th></tr></thead>
          <tbody><tr v-for="c in cs.complaints" :key="c.id"><td class="mono">{{ $td(c.key) }}</td><td class="mono">{{ c.serial || '—' }}</td><td>{{ short(c.customer) }}</td>
            <td>{{ $td(c.subject) }}</td><td class="mono">{{ c.issue || '…' }}</td><td>{{ $td(c.status_label) }}</td><td>{{ c.score ?? '—' }}</td>
            <td><button v-if="c.serial && !c.job_id" class="btn ghost sm" @click="tab = 'fleet'; open(c.serial, c.id)">{{ $t('派工') }}</button>
              <span v-if="c.status === 'closed' && c.score === null" class="cks">
                <button v-for="s in [5, 4, 3, 2, 1]" :key="s" class="btn ghost sm" @click="rate(c.id, s)">{{ s }}</button></span></td></tr></tbody></table></div>
      </section>
      <section class="card">
        <div class="card-head"><h2>{{ $t('服务工单') }}</h2></div>
        <p v-if="!cs.jobs.length" class="empty">{{ $t('还没有。') }}</p>
        <div v-else class="scroll"><table class="tbl small">
          <thead><tr><th>{{ $t('工单') }}</th><th>{{ $t('机器人') }}</th><th>{{ $t('方案') }}</th><th>{{ $t('工程师') }}</th><th>{{ $t('日子') }}</th><th>{{ $t('状态') }}</th><th class="num">{{ $t('费用') }}</th><th></th></tr></thead>
          <tbody><tr v-for="j in cs.jobs" :key="j.id"><td class="mono">{{ $td(j.key) }}</td><td class="mono">{{ $td(j.serial) }}</td><td>{{ $td(j.kind_label) }}{{ j.joint ? ' ' + j.joint : '' }}</td>
            <td>{{ $td(j.engineer) }}</td><td>{{ j.done_day || j.plan_day }}</td><td>{{ $td(j.status_label) }}</td><td class="num">${{ j.cost_usd.toLocaleString() }}</td>
            <td><button v-if="j.status !== 'done'" class="btn ghost sm" @click="done(j.id)">{{ $t('做完') }}</button></td></tr></tbody></table></div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { bi, isEn, t as $t } from '../lib/i18n';
import { onMounted, reactive, ref } from 'vue';
import { get, post } from '../lib/api';

const TABS = { fleet: $t('现场的机器人'), cases: $t('投诉与工单') };
const HL = { green: $t('正常'), yellow: $t('注意'), red: $t('报警') };
const COLORS = ['#2f6fdf', '#d9480f', '#2b8a3e', '#7048e8', '#c2255c', '#0b7285'];
const W = 640;
const Hh = 200;
const tab = ref('fleet');
const err = ref('');
const msg = ref('');
const fl = ref(null);
const kp = ref(null);
const dt = ref(null);
const cs = ref(null);
const sel = ref('');
const cid = ref(null);
const nj = reactive({ kind: 'swap', joint: 'J1' });
const nc = reactive({ serial: '', subject: '' });
const short = (c) => (isEn() ? bi(c || '—') : (c || '—').split(' ')[0]);   // 英文取英文名（第 130 轮第三批）

async function wrap(fn) { try { err.value = ''; await fn(); } catch (e) { err.value = e.message; } }
const load = () => wrap(async () => {
  fl.value = await get('/rfield/fleet'); kp.value = fl.value.kpis;
  if (tab.value === 'cases') cs.value = await get('/rfield/complaints');
  if (sel.value) dt.value = await get('/rfield/robots/' + encodeURIComponent(sel.value));
});
const open = (s, complaint = null) => wrap(async () => {
  sel.value = s; cid.value = complaint;
  dt.value = await get('/rfield/robots/' + encodeURIComponent(s));
  const w = dt.value.why.find((x) => x.kind === 'backlash') || dt.value.why[0];
  if (w) { nj.kind = w.kind === 'backlash' ? 'swap' : (w.kind === 'temp' ? 'lube' : 'recalib'); if (w.joint) nj.joint = w.joint; }
});
const plan = () => wrap(async () => {
  const r = await post('/rfield/jobs', { serial: sel.value, kind: nj.kind, joint: nj.kind === 'swap' ? nj.joint : null, complaint_id: cid.value });
  msg.value = $t('已派工 RS-') + String(r.id).padStart(5, '0'); cid.value = null; await load();
});
const complain = () => wrap(async () => { const r = await post('/rfield/complaints', { ...nc }); msg.value = $t('已登记 RC-') + String(r.id).padStart(5, '0'); nc.subject = ''; await load(); });
const done = (id) => wrap(async () => { await post('/rfield/jobs/' + id + '/done', {}); msg.value = $t('工单已完成'); await load(); });
const rate = (id, s) => wrap(async () => { await post('/rfield/complaints/' + id + '/score', { score: s }); await load(); });
const advance = (d) => wrap(async () => { await post('/rfield/advance', { days: d }); msg.value = $t('现场时钟往前走了 ') + d + $t(' 天'); await load(); });

const cur = (i) => dt.value?.series.at(-1)?.joints[i];
const last = (i) => cur(i)?.backlash ?? 0.6;
const yOf = (v) => Hh - 16 - (Math.min(1.4, Math.max(0.4, v)) - 0.4) / 1.0 * (Hh - 30);
function line(i) {
  const s = dt.value.series;
  const n = Math.max(1, s.length - 1);
  return s.map((d, k) => `${30 + k / n * (W - 80)},${yOf(d.joints[i].backlash)}`).join(' ');
}
function sameLot(j) {
  const x = (dt.value.same_lot || []).find((y) => y.joint === j.joint);
  return x && x.others ? $t('另外 ') + x.others + $t(' 台') : '—';
}
onMounted(load);
</script>

<style scoped>
.kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; margin-bottom: 12px; }
.k { display: flex; flex-direction: column; gap: 2px; }
.k b { font-size: 20px; }
.row { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; margin: 8px 0; }
.tabs button { border: 1px solid var(--line); background: var(--surface); padding: 4px 10px; border-radius: 6px; margin-right: 4px; }
.tabs button.on { background: var(--accent, #2f6fdf); color: #fff; }
.scroll { overflow-x: auto; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; }
.tbl tr.sel { background: var(--surface-2); }
.tbl tbody tr { cursor: pointer; }
.num { text-align: right; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 4px; background: var(--good, #2b8a3e); }
.dot.yellow { background: #f08c00; }
.dot.red { background: #e03131; }
.chart { width: 100%; max-width: 720px; height: auto; }
.wide { min-width: 260px; height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
.bad-t { color: #e03131; }
.ok-msg { color: var(--good, #2b8a3e); }
.cks { display: inline-flex; gap: 2px; }
</style>
