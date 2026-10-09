<template>
  <div class="page">
    <div class="page-title"><h1><router-link to="/ont" class="back">厂情中枢</router-link> / 推演工作台</h1>
      <span class="muted">给工厂拍一张快照，换上不同的处理，用仿真车间同一套引擎快进，看订单什么时候完成、多花多少钱</span></div>
    <div v-if="err" class="err">{{ err }}</div>

    <div class="layout">
      <section class="card left">
        <div class="card-head"><h2>改动</h2></div>
        <p class="small muted">快照：<template v-if="snap">#{{ snap.id }} · {{ fmtTs(snap.factory_now) }} · {{ snap.exact ? '精确' : '近似（从总线状态重建）' }}</template>
          <template v-else>未拍</template>
          <button class="linkbtn" :disabled="busy" @click="newSnap">拍新快照</button></p>
        <p v-if="isPast" class="small pastn">复盘推演：这是过去的快照，可以试“如果当时那样做会怎样”，但不能变成动作。</p>
        <p class="small muted">车间：{{ shift.mode === 'shift' ? '按班次（' + shift.start + '–' + shift.end + '）' : '24 小时连续' }}</p>
        <ol class="changes">
          <li v-for="(c, i) in changes" :key="i">
            <span class="pill info">{{ TYPE_LABEL[c.type] }}</span> <span class="small">{{ describe(c) }}</span>
            <button class="linkbtn" @click="changes.splice(i, 1); run()">删除</button>
          </li>
        </ol>
        <p v-if="!changes.length" class="small muted">没有改动 = “不处理”。</p>
        <details class="add" :open="adding">
          <summary @click.prevent="adding = !adding">+ 加一个改动</summary>
          <div class="field"><label>种类</label>
            <select v-model="form.type"><option v-for="(l, k) in TYPES" :key="k" :value="k">{{ l }}</option></select></div>
          <template v-if="form.type === 'reassign'">
            <div class="field"><label>工单 · 工序（在哪台设备）</label>
              <select v-model="form.job"><option v-for="j in jobs" :key="j.k" :value="j">{{ j.wo }} · {{ j.op.split(' ')[0] }}（{{ j.unit.toUpperCase() }}）</option></select></div>
            <div class="field"><label>改到</label><select v-model="form.to_unit"><option v-for="u in alts" :key="u" :value="u">{{ u.toUpperCase() }}</option></select></div>
          </template>
          <template v-if="form.type === 'reorder' || form.type === 'outsource'">
            <div class="field"><label>工单 · 工序（在哪台设备）</label>
              <select v-model="form.job"><option v-for="j in jobs" :key="j.k" :value="j">{{ j.wo }} · {{ j.op.split(' ')[0] }}（{{ j.unit.toUpperCase() }}）</option></select></div>
            <template v-if="form.type === 'outsource'">
              <div class="field"><label>件数</label><input v-model.number="form.qty" type="number" min="1"></div>
              <div class="field"><label>外协周期（天）</label><input v-model.number="form.days" type="number" min="0.5" step="0.5"></div>
            </template>
          </template>
          <template v-if="form.type === 'overtime'">
            <div class="field"><label>日期</label><input v-model="form.day" type="date"></div>
            <div class="field"><label>设备（空 = 全厂）</label><select v-model="form.unit"><option value="*">全厂</option>
              <option v-for="u in units" :key="u" :value="u">{{ u.toUpperCase() }}</option></select></div>
            <div class="field"><label>分钟（最多 240）</label><input v-model.number="form.minutes" type="number" min="30" max="240" step="30"></div>
            <p v-if="shift.mode !== 'shift'" class="small err">车间是 24 小时连续运转，加班没有意义；老师可以在“情景导演”的教师控制台切到按班次。</p>
          </template>
          <template v-if="form.type === 'expedite'">
            <div class="field"><label>停机的设备</label><select v-model="form.unit"><option v-for="u in downUnits" :key="u" :value="u">{{ u.toUpperCase() }}</option></select></div>
            <div class="field"><label>剩余停机缩短到</label><select v-model.number="form.factor"><option :value="0.75">75%</option><option :value="0.5">50%</option><option :value="0.25">25%</option></select></div>
          </template>
          <template v-if="form.type === 'urgent_purchase'">
            <div class="field"><label>物料</label><input v-model="form.item" placeholder="如 BRG-6207"></div>
            <div class="field"><label>数量</label><input v-model.number="form.qty" type="number" min="1"></div>
            <div class="field"><label>到货日</label><input v-model="form.arrive" type="date"></div>
          </template>
          <template v-if="form.type === 'split_delivery'">
            <div class="field"><label>销售订单</label><select v-model="form.sales_order"><option v-for="s in sos" :key="s.name" :value="s.name">{{ s.name }}（{{ s.qty }} 台，交期 {{ s.delivery_date }}）</option></select></div>
            <div class="field"><label>首批台数</label><input v-model.number="form.first_qty" type="number" min="1"></div>
            <div class="field"><label>首批交期</label><input v-model="form.first_date" type="date"></div>
          </template>
          <template v-if="form.type === 'insert_order'">
            <div class="field"><label>工单号</label><input v-model="form.work_order" placeholder="如 插单-1"></div>
            <div class="field"><label>件数（SH-301）</label><input v-model.number="form.qty" type="number" min="1"></div>
            <div class="field"><label>下达日</label><input v-model="form.at" type="date"></div>
          </template>
          <button class="btn primary sm" @click="addChange">加入并推演</button>
        </details>
        <div class="acts">
          <button class="btn sm" :disabled="busy" @click="run">{{ busy ? '推演中…' : '推演' }}</button>
          <input v-model="title" placeholder="场景名" aria-label="场景名">
          <button class="btn sm ghost" :disabled="!title || busy" @click="save">保存场景</button>
        </div>
        <button v-if="canInitiate && !isPast && changes.some((c) => !['insert_order', 'breakdown'].includes(c.type))" class="btn primary sm wide" :disabled="busy" @click="toActions">把这些改动提交为动作</button>
        <p v-if="msg" class="small ok">{{ msg }} <router-link to="/ont/actions">去动作收件箱</router-link></p>
      </section>

      <section class="card mid">
        <div class="card-head"><h2>甘特图</h2>
          <span class="seg"><button :class="{ on: showBase }" @click="showBase = true">不处理</button><button :class="{ on: !showBase }" @click="showBase = false">本方案</button></span></div>
        <GanttChart v-if="(showBase ? base : cur)" :result="showBase ? base : cur" :width="980" />
        <div class="card-head" style="margin-top:14px"><h2>订单</h2><span class="small muted">看板首页的交期是粗估（瓶颈节拍 × 剩余件数），这里是逐件推演</span></div>
        <table class="t small">
          <thead><tr><th>订单</th><th>交期</th><th>不处理</th><th>本方案</th><th v-for="s in compared" :key="s.id">{{ s.title }}</th></tr></thead>
          <tbody><tr v-for="so in orderRows" :key="so.name">
            <td class="mono">{{ so.name }}</td><td>{{ so.delivery_date }}</td>
            <td v-for="(r, i) in [base, cur, ...compared.map((x) => x.result)]" :key="i" v-html="soCell(r, so.name)"></td>
          </tr>
          <tr><td>多花的钱</td><td></td><td v-for="(r, i) in [base, cur, ...compared.map((x) => x.result)]" :key="'c' + i" class="num">${{ Math.round(r?.cost_total || 0).toLocaleString() }}</td></tr>
          <tr><td>加班</td><td></td><td v-for="(r, i) in [base, cur, ...compared.map((x) => x.result)]" :key="'o' + i" class="num">{{ otText(r) }}</td></tr></tbody>
        </table>
        <ul v-if="cur?.costs?.length" class="small costs"><li v-for="(c, i) in cur.costs" :key="i">{{ c.what }}：${{ c.usd.toLocaleString() }}</li></ul>
        <ul v-if="cur?.checks?.length" class="small"><li v-for="(c, i) in cur.checks" :key="i" :class="c.ok ? 'ok' : 'err'">{{ c.text }}</li></ul>
      </section>

      <section class="card right">
        <div class="card-head"><h2>场景</h2><span class="small muted">勾选最多 4 个并排比较</span></div>
        <p v-if="!scenarios.length" class="small muted">还没有保存的场景。</p>
        <label v-for="s in scenarios" :key="s.id" class="sc small"><input v-model="cmp" type="checkbox" :value="s.id" :disabled="cmp.length >= 4 && !cmp.includes(s.id)" @change="loadCompared">
          <b>{{ s.title }}</b> <span class="muted">SC-{{ String(s.id).padStart(5, '0') }} · {{ s.created_by }} · ${{ Math.round(s.cost || 0) }}</span>
          <button class="linkbtn" @click.prevent="open(s.id)">载入</button></label>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { get, post, session } from '../lib/api';
import { fmtTs } from '../lib/ont';
import GanttChart from '../components/GanttChart.vue';

const TYPES = { reassign: '改派', reorder: '调序', insert_order: '插单', overtime: '加班', expedite: '维修加急', urgent_purchase: '紧急采购', outsource: '外协', split_delivery: '分批交货' };
const TYPE_LABEL = { ...TYPES, breakdown: '假设停机' };
const route = useRoute();
const err = ref('');
const msg = ref('');
const busy = ref(false);
const snap = ref(null);
const changes = ref([]);
const base = ref(null);
const cur = ref(null);
const showBase = ref(false);
const title = ref('');
const scenarios = ref([]);
const cmp = ref([]);
const compared = ref([]);
const shift = ref({ mode: 'continuous' });
const adding = ref(false);
const canInitiate = computed(() => session.user?.teacher === true || ['planner', 'manager'].includes(session.user?.role));
const form = ref({ type: 'expedite', qty: 3, days: 1, minutes: 120, unit: '*', factor: 0.5 });

const jobs = computed(() => {
  const out = [];
  const st = snap.value?.state;
  if (!st) return out;
  for (const [u, m] of Object.entries(st.machines)) for (const [wo, i] of m.jobs) out.push({ k: u + wo + i, unit: u, wo, op: st.wos[wo].ops[i][0] });
  return out;
});
const alts = computed(() => (form.value.job ? ((snap.value?.state?.op_units || {})[form.value.job.op] || []).filter((u) => u !== form.value.job.unit) : []));
const units = computed(() => Object.keys(snap.value?.state?.machines || {}));
const downUnits = computed(() => Object.entries(snap.value?.state?.machines || {}).filter(([, m]) => ['down', 'fault'].includes(m.state)).map(([u]) => u));
const sos = computed(() => base.value?.sales_orders || []);
const orderRows = computed(() => sos.value.filter((s) => s.work_orders?.length));

// 过去的快照（2 小时以前拍的）：只能复盘推演，不能提交为动作（服务端也会拒绝）
const isPast = computed(() => !!snap.value?.ts && Date.now() - new Date(snap.value.ts).getTime() > 2 * 3600 * 1000);
function describe(c) {
  if (c.type === 'reassign') return `${c.work_order} ${c.operation.split(' ')[0]}：${c.from_unit.toUpperCase()} → ${c.to_unit.toUpperCase()}`;
  if (c.type === 'reorder') return `${c.work_order} 在 ${c.unit.toUpperCase()} 上排到最前`;
  if (c.type === 'overtime') return `${c.day} ${c.unit === '*' ? '全厂' : c.unit.toUpperCase()} ${c.minutes} 分钟`;
  if (c.type === 'expedite') return `${c.unit.toUpperCase()} 剩余停机缩短到 ${Math.round(c.factor * 100)}%`;
  if (c.type === 'urgent_purchase') return `${c.item} × ${c.qty}，${c.arrive} 到货`;
  if (c.type === 'outsource') return `${c.work_order} ${c.operation.split(' ')[0]} ${c.qty} 件，${c.days} 天`;
  if (c.type === 'split_delivery') return `${c.sales_order} 先交 ${c.first_qty} 台（${c.first_date}）`;
  if (c.type === 'insert_order') return `${c.work_order} SH-301 × ${c.qty}，${c.at} 下达`;
  if (c.type === 'breakdown') return `假设 ${c.unit.toUpperCase()} 再停 ${Math.round(c.minutes)} 分钟（只推演）`;
  if (c.type === 'lockout') return `${c.unit.toUpperCase()} ${c.delay_minutes ? c.delay_minutes + ' 分钟后' : '立即'}停机挂牌整改 ${Math.round(c.minutes)} 分钟`;
  return JSON.stringify(c);
}
function otText(r) { return r?.overtime_min ? `${r.overtime_min} 分钟 × ${r.overtime_units} 台` : '0'; }
function soCell(r, name) {
  const s = (r?.sales_orders || []).find((x) => x.name === name);
  if (!s) return '—';
  if (s.late_days === null) return `<span class="muted">${s.note || '做不完'}</span>`;
  return `${s.projected} <b style="color:${s.late_days > 0 ? 'var(--bad)' : 'var(--good)'}">${s.late_days > 0 ? '晚 ' + s.late_days + ' 天' : '按时'}</b>`;
}
function addChange() {
  const f = form.value;
  let c = { type: f.type };
  if (f.type === 'reassign') { if (!f.job || !f.to_unit) return alert('选工序和设备'); c = { ...c, work_order: f.job.wo, operation: f.job.op, from_unit: f.job.unit, to_unit: f.to_unit }; }
  if (f.type === 'reorder') { if (!f.job) return alert('选工序'); c = { ...c, unit: f.job.unit, work_order: f.job.wo, operation: f.job.op }; }
  if (f.type === 'outsource') { if (!f.job) return alert('选工序'); c = { ...c, unit: f.job.unit, work_order: f.job.wo, operation: f.job.op, qty: f.qty, days: f.days }; }
  if (f.type === 'overtime') c = { ...c, day: f.day, unit: f.unit || '*', minutes: f.minutes };
  if (f.type === 'expedite') c = { ...c, unit: f.unit, factor: f.factor };
  if (f.type === 'urgent_purchase') c = { ...c, item: f.item, qty: f.qty, arrive: f.arrive };
  if (f.type === 'split_delivery') c = { ...c, sales_order: f.sales_order, first_qty: f.first_qty, first_date: f.first_date };
  if (f.type === 'insert_order') c = { ...c, work_order: f.work_order || '插单-1', item: 'SH-301', qty: f.qty, at: f.at };
  changes.value.push(c);
  adding.value = false;
  run();
}
async function newSnap() {
  busy.value = true;
  try {
    const s = await post('/ont/snapshot');
    await loadSnap(s.id);
    await run(true);
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
async function loadSnap(id) {
  const list = await get('/ont/snapshots?hours=720');
  const one = list.snapshots.find((x) => x.id === id);
  snap.value = { id, factory_now: one?.factory_now, exact: one?.exact, ts: one?.ts, state: null };
  // 快照内容（派工、停机）从“不处理”的推演里带回：服务端在推演结果里不返回整个快照，这里单独取
  const st = await post('/ont/simulate', { snapshot_id: id, changes: [] });
  base.value = st;
  snap.value.state = st.snapshot_state || null;
}
async function run(rebase = false) {
  if (!snap.value) return newSnap();
  busy.value = true; err.value = '';
  try {
    if (rebase || !base.value) base.value = await post('/ont/simulate', { snapshot_id: snap.value.id, changes: [] });
    cur.value = await post('/ont/simulate', { snapshot_id: snap.value.id, changes: changes.value });
    snap.value.state = cur.value.snapshot_state || snap.value.state;
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
async function save() {
  try {
    await post('/ont/scenarios', { title: title.value, snapshot_id: snap.value.id, changes: changes.value, anomaly_id: route.query.a ? Number(route.query.a) : undefined });
    title.value = '';
    loadScenarios();
  } catch (e) { alert(e.message); }
}
async function loadScenarios() { scenarios.value = (await get('/ont/scenarios')).scenarios; }
async function loadCompared() { compared.value = await Promise.all(cmp.value.map((id) => get('/ont/scenarios/' + id))); }
async function open(id) {
  const s = await get('/ont/scenarios/' + id);
  changes.value = s.changes;
  if (s.snapshot_id) { await loadSnap(s.snapshot_id); }
  await run();
}
async function toActions() {
  try {
    const r = await post('/ont/actions', { changes: changes.value, snapshot_id: snap.value.id, anomaly_id: route.query.a ? Number(route.query.a) : undefined });
    msg.value = `已提交 ${r.ids.length} 个动作，等待批准。`;
  } catch (e) { alert(e.message); }
}
watch(() => form.value.type, () => { form.value.job = null; form.value.to_unit = null; });

onMounted(async () => {
  try {
    const sh = await get('/ont/shifts');
    shift.value = sh.calendar;
    form.value.day = new Date().toISOString().slice(0, 10);
    form.value.arrive = form.value.day;
    form.value.first_date = form.value.day;
    form.value.at = form.value.day;
    loadScenarios();
    if (route.query.scenario) {
      await open(Number(route.query.scenario));
    } else if (route.query.snap && !route.query.a) {
      await loadSnap(Number(route.query.snap));
      await run();
    } else if (route.query.a) {
      const o = await get(`/ont/anomalies/${route.query.a}/options` + (route.query.snap ? '?snapshot_id=' + route.query.snap : ''));
      const opt = o.options.find((x) => x.key === route.query.opt);
      if (opt) changes.value = [...opt.changes];
      await loadSnap(o.snapshot_id);
      await run();
    } else {
      await newSnap();
    }
  } catch (e) { err.value = e.message; }
});
</script>

<style scoped>
.back { color: var(--muted); font-weight: 500; }
.pastn { background: #FFF4CC; border-radius: 6px; padding: 6px 8px; color: #6B4500; }
.layout { display: grid; grid-template-columns: 300px minmax(0, 1fr) 260px; gap: 14px; align-items: start; }
.layout > * { min-width: 0; }
.mid table { display: block; overflow-x: auto; }
.changes { padding-left: 18px; margin: 6px 0; }
.changes li { margin-bottom: 4px; }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; }
.add { border: 1px dashed var(--line); border-radius: 8px; padding: 6px 8px; margin: 8px 0; }
.add summary { cursor: pointer; color: var(--accent); font-size: 13px; }
.add .field { margin-top: 6px; }
.add input, .add select { height: 30px; }
.acts { display: flex; gap: 6px; align-items: center; margin-top: 8px; }
.acts input { flex: 1; height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 6px; min-width: 0; }
.btn.sm { height: 30px; padding: 0 10px; }
.btn.wide { width: 100%; margin-top: 8px; }
.seg { margin-left: auto; display: inline-flex; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
.seg button { border: none; background: var(--surface); padding: 4px 10px; cursor: pointer; font-size: 12px; }
.seg button.on { background: var(--accent); color: #fff; }
.costs { margin: 6px 0; padding-left: 18px; }
.sc { display: block; padding: 6px 0; border-bottom: 1px solid var(--line-soft); }
.ok { color: var(--good); }
.err { color: var(--bad); }
@media (max-width: 1200px) { .layout { grid-template-columns: 280px minmax(0, 1fr); } .right { grid-column: 1 / -1; } }
@media (max-width: 800px) { .layout { grid-template-columns: 1fr; } }
</style>
