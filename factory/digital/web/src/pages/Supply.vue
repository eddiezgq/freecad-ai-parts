<!-- 采购与来料（第 18 轮 E5）：采购单与在途、到货与来料检验、批次追溯、供应商评分卡。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>采购与来料</h1>
      <span class="muted">请购 → 采购单 → 发货 → 到货 → 来料检验 → 批次入库 → 用到哪些零件 → 供应商评分</span>
      <span class="tabs" data-help="sup-tabs" role="tablist"><button v-for="(l, k) in TABS" :key="k" type="button" role="tab" :class="{ on: tab === k }" @click="go(k)">{{ l }}</button></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="msg" class="ok small">{{ msg }}</div>

    <section v-if="kp" class="kpis" data-help="sup-kpis">
      <div class="card k"><span class="small muted">在途</span><b>{{ kp.in_transit }}</b><span class="small muted">批</span></div>
      <div class="card k"><span class="small muted">到货待检</span><b :class="{ warn: kp.waiting_inspection }">{{ kp.waiting_inspection }}</b></div>
      <div class="card k"><span class="small muted">不合格待处理</span><b :class="{ bad: kp.rejected_open }">{{ kp.rejected_open }}</b></div>
      <div class="card k"><span class="small muted">准时率 / 合格率</span><b>{{ pct(kp.on_time) }} / {{ pct(kp.pass_rate) }}</b><span class="small muted">近 30 天</span></div>
      <div class="card k"><span class="small muted">供应商模拟器</span><b>{{ kp.enabled ? '开' : '关' }}</b>
        <span v-if="teacher" class="row small"><button class="btn sm" @click="setSim(!kp.enabled)">{{ kp.enabled ? '关闭' : '打开' }}</button></span>
        <span v-else class="small muted">{{ kp.enabled ? '供应商会晚、会出不合格' : '准时、不出问题' }}</span></div>
    </section>

    <!-- ① 采购单与在途 -->
    <template v-if="tab === 'lots'">
      <div v-if="rq?.requests.length" class="card">
        <h3>还没下采购单的请购</h3>
        <table class="tbl small"><thead><tr><th>请购单</th><th>物料</th><th class="num">数量</th><th>需要日期</th><th>供应商</th><th></th></tr></thead>
          <tbody><tr v-for="r in rq.requests" :key="r.mr + r.item_code"><td>{{ r.mr }}</td><td>{{ r.item_code }}</td><td class="num">{{ r.qty }}</td><td>{{ r.schedule_date }}</td>
            <td><select v-model="pick[r.mr + r.item_code]" aria-label="供应商"><option v-for="s in r.suppliers" :key="s.name" :value="s.name">
              {{ s.name.split(' ')[0] }}（{{ s.role === 'alt' ? '备选' : '默认' }}，{{ s.lead_days }} 天{{ s.price_index > 1 ? '，贵 ' + Math.round((s.price_index - 1) * 100) + '%' : '' }}）</option></select></td>
            <td><button class="linkbtn" @click="toPo(r)">转采购单</button></td></tr></tbody></table>
        <p class="small muted">转采购单生成“采购单”动作，厂长批准后进 ERPNext。教学模拟器打开时，请购单 3 分钟没人转，采购员（模拟器）按默认供应商下单。</p>
      </div>
      <div v-if="lt" class="card">
        <table class="tbl small"><thead><tr><th>批号</th><th>采购单</th><th>物料</th><th class="num">数量</th><th>供应商</th><th>承诺到货</th><th>状态</th><th></th></tr></thead>
          <tbody><tr v-for="x in lt.lots" :key="x.id"><td>{{ x.lot || '#' + x.id }}</td><td>{{ x.po || '—' }}</td><td>{{ x.item }}</td><td class="num">{{ x.qty }}</td>
            <td>{{ x.supplier.split(' ')[0] }}</td><td>{{ x.promised || '—' }}<span v-if="x.late_days > 0 && x.arrived_at" class="bad"> 晚 {{ x.late_days }} 天</span></td>
            <td :class="TONE[x.status]">{{ x.status_label }}{{ x.concession ? '（让步接收）' : '' }}</td>
            <td><button v-if="lt.can_receive && x.status === 'transit' && !kp?.enabled" class="linkbtn" @click="arrive(x)">登记到货</button></td></tr></tbody></table>
      </div>
    </template>

    <!-- ② 到货与来料检验 -->
    <template v-if="tab === 'inspect' && lt">
      <div class="card" data-help="sup-inspect">
        <table class="tbl small"><thead><tr><th>批号</th><th>物料</th><th class="num">数量</th><th>供应商</th><th>到货</th><th>状态</th><th></th></tr></thead>
          <tbody><tr v-for="x in lt.lots.filter((y) => ['arrived', 'rejected', 'accepted'].includes(y.status)).slice(0, 40)" :key="x.id" :class="{ sel: sm && sm.id === x.id }">
            <td>{{ x.lot }}</td><td>{{ x.item }}</td><td class="num">{{ x.qty }}</td><td>{{ x.supplier.split(' ')[0] }}</td><td>{{ (x.arrived_at || '').slice(5, 16).replace('T', ' ') }}</td>
            <td :class="TONE[x.status]">{{ x.status_label }}</td><td><button class="linkbtn" @click="openSample(x)">{{ x.status === 'arrived' ? '检验' : '看检验' }}</button></td></tr></tbody></table>
      </div>
      <div v-if="sm" class="card">
        <h3>{{ sm.lot }} · {{ sm.item }}：{{ sm.template || '没有检验模板（直接收货）' }}</h3>
        <template v-if="sm.template">
          <p class="small muted">上下限：{{ sm.params.map((p) => p.specification.split(' ')[0] + (p.numeric ? ' ' + p.min + '～' + p.max : '：' + p.value)).join('；') }}</p>
          <table class="tbl small"><thead><tr><th>件</th><th v-for="p in sm.params" :key="p.specification">{{ p.specification.split(' ')[0] }}</th></tr></thead>
            <tbody><tr v-for="(r, i) in sm.rows" :key="i"><td>{{ i + 1 }}</td>
              <td v-for="p in sm.params" :key="p.specification">{{ r[p.specification] }}</td></tr></tbody></table>
          <p class="small muted">自己逐件对照上下限，判定这一批。</p>
        </template>
        <div v-if="sm.status === 'arrived' && lt.can_inspect" class="row">
          <input v-model="note" class="note" placeholder="备注（可不填）" aria-label="备注">
          <button class="btn primary sm" @click="judge(true)">{{ sm.template ? '合格，收货入库' : '收货入库' }}</button>
          <button v-if="sm.template" class="btn danger sm" @click="judge(false)">不合格</button></div>
        <p v-else-if="sm.status === 'arrived'" class="small muted">来料检验由质量或厂长操作（右上角切换角色）。</p>
        <p v-else class="small">结论：<b :class="TONE[sm.status]">{{ STATUS[sm.status] }}</b>，检验人 {{ sm.inspected_by || '—' }}。不合格的批次到厂情中枢看处理方案（退货 / 备选急单 / 让步接收）。</p>
      </div>
    </template>

    <!-- ③ 批次 -->
    <template v-if="tab === 'batches'">
      <div class="card">
        <div class="row"><input v-model="q" placeholder="批号（L……）或零件 / 设备序列号" aria-label="批号或序列号"><button class="btn sm" @click="doTrace">追溯</button></div>
        <template v-if="tr">
          <div v-if="tr.row" class="small">
            <p><b>{{ tr.lot }}</b>：{{ tr.row.item }} × {{ tr.row.qty }}，{{ tr.row.supplier }}，采购单 {{ tr.row.po || '—' }}，{{ tr.row.status_label }}，剩 {{ tr.row.qty_left }}</p>
            <p>用到了 {{ tr.parts.length }} 个零件、{{ tr.work_orders.length }} 张工单：{{ tr.parts.slice(0, 20).join('、') }}{{ tr.parts.length > 20 ? '……' : '' }}</p>
            <p v-if="tr.units.length">装进了现场设备：{{ tr.units.map((u) => u.serial).join('、') }}</p>
            <p v-if="lt?.can_inspect && tr.row.status === 'accepted'"><button class="linkbtn" @click="suspect(tr.row)">判为可疑批次（事后发现问题）</button></p>
          </div>
          <div v-else-if="tr.lots" class="small">
            <p>{{ tr.serial }} 用了这些批次：</p>
            <ul><li v-for="x in tr.lots" :key="x.id">{{ x.lot }}：{{ x.item }}，{{ x.supplier }}（{{ x.status_label }}）</li></ul>
            <p v-if="!tr.lots.length" class="muted">没有记录（情景开始时库里的料记为“期初”）。</p>
          </div>
        </template>
        <p class="small muted">车间每开工一件，按先进先出记下用了哪个批次的料。也可以在下面的表里点批号。</p>
        <table v-if="lt" class="tbl small"><tbody><tr v-for="x in lt.lots.filter((y) => y.lot && ['accepted', 'suspect'].includes(y.status)).slice(0, 30)" :key="x.id">
          <td><button class="linkbtn" @click="q = x.lot; doTrace()">{{ x.lot }}</button></td><td>{{ x.item }}</td><td>{{ x.supplier.split(' ')[0] }}</td>
          <td class="num">剩 {{ x.qty_left }} / {{ x.qty_ok ?? x.qty }}</td><td :class="TONE[x.status]">{{ x.status_label }}</td></tr></tbody></table>
      </div>
    </template>

    <!-- ④ 供应商 -->
    <template v-if="tab === 'suppliers' && sp">
      <div class="card">
        <table class="tbl small"><thead><tr><th>供应商</th><th>物料</th><th>默认 / 备选</th><th class="num">价格指数</th><th class="num">提前期</th>
          <th class="num">准时率</th><th class="num">合格率</th><th class="num">在途</th></tr></thead>
          <tbody><tr v-for="s in sp.suppliers" :key="s.supplier" :class="{ off: !s.active }"><td>{{ s.supplier }}</td><td>{{ s.cat_name }}</td>
            <td>{{ s.role === 'alt' ? (s.active ? '备选' : '备选（未启用）') : '默认' }}</td><td class="num">{{ s.price_index }}</td><td class="num">{{ s.lead_days }} 天</td>
            <td class="num">{{ pct(s.on_time) }} <span class="muted">（{{ pct(s.hist_on_time) }}）</span></td>
            <td class="num">{{ pct(s.pass_rate) }} <span class="muted">（{{ pct(s.hist_pass) }}）</span></td><td class="num">{{ s.in_transit }}</td></tr></tbody></table>
        <p class="small muted">准时率、合格率：近 30 天到货、检验的批次（让步接收不算合格）；括号里是过去一年的历史。每件总拥有成本 = 单价 × 价格指数 + (1 − 合格率) × $4 + (1 − 准时率) × $3。</p>
        <h3>单一来源</h3>
        <ul class="small"><li v-for="x in sp.single_source" :key="x.cat">{{ x.cat_name }}：只有 {{ (x.supplier || '—').split(' ')[0] }}{{ x.has_alt ? '（有可开发的备选）' : '（还没有备选）' }}</li></ul>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post, session } from '../lib/api';

const TABS = { lots: '采购单与在途', inspect: '到货与检验', batches: '批次', suppliers: '供应商' };
const STATUS = { ordered: '已下单', transit: '在途', arrived: '到货待检', accepted: '合格入库', rejected: '不合格', returned: '已退货', suspect: '可疑' };
const TONE = { arrived: 'warn', rejected: 'bad', suspect: 'bad', accepted: 'ok' };
const route = useRoute();
const router = useRouter();
const tab = ref(TABS[route.query.tab] ? route.query.tab : 'lots');
const err = ref('');
const msg = ref('');
const kp = ref(null);
const lt = ref(null);
const rq = ref(null);
const sp = ref(null);
const sm = ref(null);
const tr = ref(null);
const q = ref(route.query.lot || '');
const note = ref('');
const pick = reactive({});
const teacher = computed(() => session.user?.teacher && session.user?.mode === 'teach');
const pct = (v) => (v === null || v === undefined ? '—' : Math.round(v * 100) + '%');

function go(k) { tab.value = k; router.replace({ query: { ...route.query, tab: k } }); load(); }
async function wrap(fn) { err.value = ''; try { await fn(); } catch (e) { err.value = e.message; } }
function load() {
  wrap(async () => { lt.value = await get('/supply/lots'); kp.value = lt.value.kpis; });
  if (tab.value === 'lots') wrap(async () => { rq.value = await get('/supply/requests'); for (const r of rq.value.requests) pick[r.mr + r.item_code] ??= r.suppliers[0]?.name; });
  if (tab.value === 'suppliers') wrap(async () => { sp.value = await get('/supply/suppliers'); });
  if (tab.value === 'batches' && q.value) doTrace();
}
async function toPo(r) {
  await wrap(async () => {
    const res = await post('/ont/actions', { changes: [{ type: 'purchase_order', supplier: pick[r.mr + r.item_code],
      items: [{ item_code: r.item_code, qty: r.qty, material_request: r.mr, material_request_item: r.row }] }] });
    msg.value = '已提交动作 ' + res.ids.map((i) => 'ACT-' + String(i).padStart(5, '0')).join('、') + '，厂长批准后下单';
    load();
  });
}
async function arrive(x) { await wrap(async () => { await post(`/supply/lots/${x.id}/arrive`, {}); load(); }); }
async function openSample(x) {
  await wrap(async () => { const s = await get(`/supply/lots/${x.id}/sample`); sm.value = { ...s, id: x.id, status: x.status, inspected_by: x.inspection?.by }; note.value = ''; });
}
async function judge(ok) {
  await wrap(async () => {
    const r = await post(`/supply/lots/${sm.value.id}/inspect`, { accept: ok, note: note.value });
    msg.value = r.status === 'accepted' ? '已判合格，收货单提交入库（ERPNext）' : '已判不合格：收货单留草稿，ERPNext 有检验单；到厂情中枢看处理方案';
    sm.value = { ...sm.value, status: r.status, inspected_by: session.user?.name };
    load();
  });
}
async function doTrace() {
  await wrap(async () => {
    const v = q.value.trim();
    tr.value = await get('/supply/trace?' + (/^L\d{6}-\d{4}$/.test(v) || v.startsWith('期初') ? 'lot=' : 'serial=') + encodeURIComponent(v));
  });
}
async function suspect(row) {
  const why = prompt('事后发现了什么问题？', '复验不合格');
  if (!why) return;
  await wrap(async () => { await post(`/supply/lots/${row.id}/suspect`, { why }); doTrace(); load(); });
}
async function setSim(on) { await wrap(async () => { await post('/supply/sim', { enabled: on }); load(); }); }
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
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
select, input { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; min-width: 0; }
.note { flex: 1 1 200px; }
.card .tbl { display: block; overflow-x: auto; }
tr.sel td { background: var(--surface-2); }
tr.off td { color: var(--muted); }
.bad { color: var(--bad); }
.warn { color: var(--warn); }
.ok { color: var(--good); }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; padding: 0 4px; }
.btn.sm { height: 28px; padding: 0 10px; }
h3 { font-size: 14px; margin: 8px 0 6px; }
.num { text-align: right; }
</style>
