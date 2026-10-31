<!-- 设备维护（第 18 轮 E3）：设备台账与失效风险、保养计划、扫码点检、维修与备件。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>设备维护</h1>
      <span class="muted">台账 → 保养 → 点检 → 故障 → 维修 → 备件；保养、维修都挂牌上锁，做完由另一个人验收解锁</span>
      <span class="tabs" data-help="maint-tabs" role="tablist"><button v-for="(l, k) in TABS" :key="k" type="button" role="tab" :class="{ on: tab === k }" @click="go(k)">{{ l }}</button></span></div>
    <div v-if="err" class="err">{{ err }}</div>

    <section v-if="kp" class="kpis" data-help="maint-kpis">
      <div class="card k"><span class="small muted">保养逾期的设备</span><b :class="{ bad: kp.overdue }">{{ kp.overdue }}</b>
        <span class="small muted">{{ kp.overdue_units.map((u) => u.toUpperCase()).join('、') || '—' }}</span></div>
      <div class="card k"><span class="small muted">开着的维修单</span><b>{{ kp.open_repairs }}</b></div>
      <div class="card k"><span class="small muted">近 7 天故障停机</span><b>{{ Math.round(kp.failure_down_7d) }}</b><span class="small muted">分钟</span></div>
      <div class="card k"><span class="small muted">平均故障间隔</span><b>{{ kp.mtbf ?? '—' }}</b><span class="small muted">运行小时（近 30 天）</span></div>
      <div class="card k"><span class="small muted">点检异常待处理</span><b>{{ kp.open_inspections }}</b></div>
    </section>

    <!-- ① 台账 -->
    <template v-if="tab === 'assets' && as">
      <div v-if="session.user?.teacher && session.user?.mode === 'teach'" class="card row small" data-help="maint-reliability">
        <b>老师：车间可靠性</b>
        <button v-for="f in [0, 1, 5]" :key="f" class="btn sm" :class="{ primary: kp?.factor === f }" @click="setFactor(f)">{{ { 0: '关（不会坏）', 1: '正常', 5: '加速 ×5' }[f] }}</button>
        <span class="muted">情景重载后回到“关”。加速时老化快 5 倍，课堂上看得见。</span>
      </div>
      <div class="card" data-help="maint-assets">
        <table class="tbl small"><thead><tr><th>设备</th><th>资产号</th><th class="num">原值</th><th class="num">自上次保养</th><th class="num">周期</th><th>保养</th>
          <th class="num">未来 {{ as.horizon_h }} 运行小时坏的概率</th><th class="num">预期损失</th><th class="num">近 30 天故障</th><th></th></tr></thead>
          <tbody><tr v-for="a in as.assets" :key="a.unit" :class="{ sel: sel === a.unit }">
            <td><b>{{ a.unit.toUpperCase() }}</b> {{ a.name }} <span v-if="a.locked">🔒</span></td><td class="mono">{{ a.asset || '（建档中）' }}</td>
            <td class="num">${{ (a.value || 0).toLocaleString() }}</td><td class="num">{{ a.run_h }} h</td><td class="num">{{ a.pm_h }} h</td>
            <td><span v-if="a.overdue_h" class="pill bad">逾期 {{ a.overdue_h }} h</span><span v-else-if="a.due_in_h < 50" class="pill warn">{{ a.due_in_h }} h 后到期</span>
              <span v-else class="muted">{{ a.due_in_h }} h 后</span></td>
            <td class="num" :class="{ bad: a.p_fail >= 0.2 }">{{ (a.p_fail * 100).toFixed(1) }}%</td><td class="num">${{ Math.round(a.expected_loss_usd) }}</td>
            <td class="num">{{ a.failures_30d }}</td><td><button class="linkbtn" @click="open(a.unit)">详情</button></td></tr></tbody></table>
      </div>
      <section v-if="dt" class="card">
        <div class="card-head"><h2>{{ dt.unit.toUpperCase() }} {{ dt.name }}</h2><span class="small muted">保养：{{ dt.pm_text }}（停 {{ dt.pm_minutes }} 分钟）</span></div>
        <div class="two">
          <div>
            <svg :viewBox="`0 0 ${W} ${Hh}`" class="curve" role="img" aria-label="累计故障概率曲线">
              <line :x1="30" :y1="Hh - 20" :x2="W - 6" :y2="Hh - 20" class="ax" /><line :x1="30" :y1="6" :x2="30" :y2="Hh - 20" class="ax" />
              <polyline :points="pts" class="ln" />
              <line :x1="xh(dt.risk.pm_h)" :x2="xh(dt.risk.pm_h)" :y1="6" :y2="Hh - 20" class="pm" />
              <line :x1="xh(dt.risk.run_h)" :x2="xh(dt.risk.run_h)" :y1="6" :y2="Hh - 20" class="now" />
              <text :x="xh(dt.risk.pm_h) + 3" y="16" class="t">保养周期</text><text :x="xh(dt.risk.run_h) + 3" y="30" class="t now-t">现在</text>
              <text x="2" y="12" class="t">100%</text><text x="8" :y="Hh - 22" class="t">0</text>
              <text :x="W - 60" :y="Hh - 6" class="t">运行小时</text>
            </svg>
            <p class="small muted">F(t) = 1 − exp(−(t/η)^β)，β = {{ dt.risk.beta }}，η = {{ dt.risk.eta_h }} 小时（可靠性系数 {{ dt.risk.factor }}）</p>
          </div>
          <div class="small">
            <p>自上次保养已运行 <b>{{ dt.risk.run_h }}</b> 小时，周期 {{ dt.risk.pm_h }} 小时{{ dt.risk.overdue_h ? '，逾期 ' + dt.risk.overdue_h + ' 小时' : '' }}。</p>
            <p>未来 {{ dt.risk.horizon_h }} 运行小时坏掉的概率 <b>{{ (dt.risk.p_fail * 100).toFixed(1) }}%</b>；保养后同样时间 {{ (dt.risk.p_after_pm * 100).toFixed(1) }}%。</p>
            <p>坏一次：修理 ${{ dt.risk.repair_usd }} + 停机 {{ dt.risk.mttr_min }} 分钟损失 ${{ dt.risk.lost_usd }}；预期损失 <b>${{ Math.round(dt.risk.expected_loss_usd) }}</b>。一次保养约 ${{ dt.risk.pm_usd }}。</p>
            <p>故障模式：{{ dt.modes.map((m) => m[1] + (m[2] ? '（' + m[2] + '）' : '')).join('、') }}</p>
            <p>平均故障间隔：{{ dt.mtbf ?? '—' }} 运行小时 · ERPNext 资产 {{ dt.asset?.name || '—' }} · 维护计划 {{ dt.maintenance?.name || '—' }}</p>
            <p><a :href="`/api/maint/qr/${dt.unit}.svg`" target="_blank">打印点检二维码</a></p>
            <p v-if="as.can_manage" class="row">调整保养周期为 <input v-model.number="ivh" type="number" min="50" max="5000" step="50" aria-label="保养周期"> 运行小时
              <button class="btn" @click="interval">提交（厂长批准）</button><span class="ok">{{ ivMsg }}</span></p>
          </div>
        </div>
        <h3>最近的故障</h3>
        <table v-if="dt.failures.length" class="tbl small"><thead><tr><th>时间</th><th>故障</th><th class="num">运行小时</th><th class="num">停机（分钟）</th><th>维修单</th></tr></thead>
          <tbody><tr v-for="f in dt.failures" :key="f.id"><td>{{ fmtTs(f.at) }}</td><td>{{ f.name }}</td><td class="num">{{ f.run_h ?? '—' }}</td><td class="num">{{ f.down_min }}</td>
            <td>{{ f.repair_id ? 'MR-' + String(f.repair_id).padStart(5, '0') : '—' }}</td></tr></tbody></table>
        <p v-else class="small muted">没有故障记录。</p>
      </section>
    </template>

    <!-- ② 保养 -->
    <template v-if="tab === 'pm' && rp">
      <p class="small muted">保养在厂情中枢里排：保养逾期（M2）、故障风险高（M4）的异常右栏有“现在保养 / 下班后保养 / 不做”三个方案，采纳后生成保养工单，到时间自动挂牌上锁。</p>
      <table class="tbl small card" data-help="maint-pm"><thead><tr><th>保养单</th><th>设备</th><th>状态</th><th class="num">时长</th><th class="num">保养时运行小时</th><th>做的人 / 验收</th><th></th></tr></thead>
        <tbody><tr v-for="p in rp.pms" :key="p.id"><td class="mono">{{ p.key }}</td><td>{{ p.unit.toUpperCase() }}</td>
          <td><span class="pill" :class="{ closed: 'good', fixed: 'info', doing: 'warn' }[p.status] || 'mute'">{{ p.status_label }}</span></td>
          <td class="num">{{ p.minutes }} 分钟{{ p.delay_minutes ? '（' + p.delay_minutes + ' 分钟后）' : '' }}</td><td class="num">{{ p.run_h ?? '—' }}</td>
          <td>{{ p.fixed_by || '—' }} / {{ p.verified_by || '—' }}</td>
          <td><button v-if="rp.can_manage && p.status === 'doing'" class="linkbtn" @click="pmDone(p)">保养完成</button>
            <button v-if="rp.can_verify && p.status === 'fixed'" class="linkbtn" @click="pmVerify(p)">验收解锁</button></td></tr></tbody></table>
      <p v-if="!rp.pms.length" class="small muted">还没有保养单。</p>
    </template>

    <!-- ③ 点检 -->
    <template v-if="tab === 'inspect'">
      <div class="card" data-help="maint-inspect">
        <h3>点检</h3>
        <div class="row"><label>设备 <select v-model="iu" @change="loadCl"><option v-for="u in UNITS" :key="u" :value="u">{{ u.toUpperCase() }}</option></select></label>
          <span class="small muted">扫设备上的二维码会直接打开这台设备的点检表</span></div>
        <div v-if="cl" class="checks">
          <label v-for="(it, i) in cl.items" :key="it" class="chk" :class="{ badrow: !res[i].ok }">
            <span>{{ it }}</span>
            <span class="seg"><button type="button" :class="{ on: res[i].ok }" @click="res[i].ok = true">正常</button>
              <button type="button" :class="{ on: !res[i].ok, bad: !res[i].ok }" @click="res[i].ok = false">异常</button></span>
            <input v-if="!res[i].ok" v-model="res[i].note" placeholder="说明" class="note">
          </label>
        </div>
        <button class="btn primary sm" :disabled="!cl" @click="submitInspect">提交点检</button> <span class="small ok">{{ msg }}</span>
      </div>
      <div v-if="ins" class="card"><h3>最近的点检</h3>
        <table class="tbl small"><thead><tr><th>编号</th><th>设备</th><th>时间</th><th>点检人</th><th>结果</th><th></th></tr></thead>
          <tbody><tr v-for="x in ins.inspections" :key="x.id"><td class="mono">{{ x.key }}</td><td>{{ x.unit.toUpperCase() }}</td><td>{{ fmtTs(x.at) }}</td><td>{{ x.by_name }}</td>
            <td><span v-if="!x.abnormal.length" class="muted">正常</span><span v-else class="bad">异常：{{ x.abnormal.map((a) => a.item).join('、') }}</span>
              <span v-if="x.status === 'handled'" class="pill info">已开维修单</span><span v-if="x.status === 'watch'" class="pill mute">观察</span></td>
            <td><template v-if="ins.can_manage && x.status === 'open'"><button class="linkbtn" @click="toRepair(x)">开维修单</button><button class="linkbtn" @click="watchIt(x)">先观察</button></template></td></tr></tbody></table></div>
    </template>

    <!-- ④ 维修与备件 -->
    <template v-if="tab === 'repairs' && rp">
      <div class="card"><h3>备件</h3>
        <span v-for="s in rp.spares" :key="s.item_code" class="pill" :class="s.stock < s.min ? 'bad' : 'mute'">{{ s.item_code }}：{{ s.stock }}（最低 {{ s.min }}）</span></div>
      <table class="tbl small card"><thead><tr><th>维修单</th><th>设备</th><th>内容</th><th>备件</th><th>状态</th><th>ERPNext</th><th>维修 / 验收</th><th></th></tr></thead>
        <tbody><tr v-for="r in rp.repairs" :key="r.id"><td class="mono">{{ r.key }}</td><td>{{ r.unit.toUpperCase() }}</td><td>{{ r.title }}</td>
          <td>{{ (r.parts || []).map((p) => p.item_code + ' × ' + p.qty).join('、') || '—' }}</td>
          <td><span class="pill" :class="{ closed: 'good', fixed: 'info', waiting_parts: 'bad', doing: 'warn' }[r.status] || 'mute'">{{ r.status_label }}</span></td>
          <td class="mono">{{ r.erp_repair || '—' }}</td><td>{{ r.fixed_by || '—' }} / {{ r.verified_by || '—' }}</td>
          <td><button v-if="rp.can_manage && ['doing', 'waiting_parts'].includes(r.status)" class="linkbtn" @click="repDone(r)">维修完成</button>
            <button v-if="rp.can_verify && r.status === 'fixed'" class="linkbtn" @click="repVerify(r)">验收解锁</button></td></tr></tbody></table>
      <p v-if="!rp.repairs.length" class="small muted">没有维修单。</p>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post, session } from '../lib/api';
import { fmtTs } from '../lib/ont';

const TABS = { assets: '设备台账', pm: '保养', inspect: '点检', repairs: '维修与备件' };
const UNITS = ref([]);            // 第 59 轮：设备清单取自台账（随工厂变）
const route = useRoute();
const router = useRouter();
const tab = ref(TABS[route.query.tab] ? route.query.tab : 'assets');
const err = ref('');
const msg = ref('');
const kp = ref(null);
const as = ref(null);
const dt = ref(null);
const sel = ref('');
const rp = ref(null);
const ins = ref(null);
const cl = ref(null);
const iu = ref(route.query.unit || '');
const res = reactive([]);
const W = 360;
const Hh = 170;

function go(k) { tab.value = k; router.replace({ query: { ...route.query, tab: k } }); load(); }
async function wrap(fn) { err.value = ''; try { await fn(); } catch (e) { err.value = e.message; } }
const loadAs = () => wrap(async () => { as.value = await get('/maint/assets'); kp.value = as.value.kpis; });
const loadRp = () => wrap(async () => { rp.value = await get('/maint/repairs'); });
const loadIns = () => wrap(async () => { ins.value = await get('/maint/inspections'); });
const loadCl = () => wrap(async () => {
  if (!UNITS.value.length) UNITS.value = (await get('/maint/assets')).assets.map((a) => a.unit);
  if (!iu.value) iu.value = UNITS.value.includes('grd-01') ? 'grd-01' : UNITS.value[0];
  cl.value = await get('/maint/checklist/' + iu.value); res.splice(0, res.length, ...cl.value.items.map(() => ({ ok: true, note: '' }))); });
function load() {
  wrap(async () => { kp.value = await get('/maint/kpis'); });
  ({ assets: loadAs, pm: loadRp, inspect: () => { loadCl(); loadIns(); }, repairs: loadRp })[tab.value]();
}
async function open(u) { sel.value = u; ivMsg.value = ''; await wrap(async () => { dt.value = await get('/maint/assets/' + u); ivh.value = dt.value.risk.pm_h; }); }
const ivh = ref(null);
const ivMsg = ref('');
async function interval() {
  await wrap(async () => {
    const r = await post('/ont/actions', { changes: [{ type: 'interval_change', unit: dt.value.unit, interval_h: ivh.value }] });
    ivMsg.value = '已提交动作 ' + r.ids.map((i) => 'ACT-' + String(i).padStart(5, '0')).join('、') + '，批准后生效';
  });
}
const maxH = computed(() => (dt.value ? Math.max(...dt.value.risk.curve.map((p) => p.h), dt.value.risk.run_h * 1.1) : 1));
const xh = (h) => 30 + (h / maxH.value) * (W - 40);
const yF = (f) => (Hh - 20) - f * (Hh - 30);
const pts = computed(() => (dt.value ? dt.value.risk.curve.map((p) => `${xh(p.h)},${yF(p.F)}`).join(' ') : ''));
async function setFactor(f) { await wrap(async () => { await post('/maint/reliability', { factor: f }); loadAs(); }); }
async function submitInspect() {
  await wrap(async () => {
    const r = await post('/maint/inspections', { unit: iu.value, results: cl.value.items.map((it, i) => ({ item: it, ok: res[i].ok, note: res[i].note })) });
    msg.value = r.abnormal.length ? `${r.key} 有 ${r.abnormal.length} 项异常，厂情中枢会提醒处理` : `${r.key} 全部正常`;
    loadCl(); loadIns();
  });
}
async function toRepair(x) { await wrap(async () => { await post('/maint/repairs', { unit: x.unit, title: '点检异常：' + x.abnormal.map((a) => a.item).join('、'), inspection_id: x.id }); loadIns(); }); }
async function watchIt(x) { await wrap(async () => { await post(`/maint/inspections/${x.id}/watch`); loadIns(); }); }
async function pmDone(p) { await wrap(async () => { await post(`/maint/pms/${p.id}/done`, {}); loadRp(); }); }
async function pmVerify(p) { await wrap(async () => { await post(`/maint/pms/${p.id}/verify`); loadRp(); }); }
async function repDone(r) { await wrap(async () => { await post(`/maint/repairs/${r.id}/done`, {}); loadRp(); }); }
async function repVerify(r) { await wrap(async () => { await post(`/maint/repairs/${r.id}/verify`); loadRp(); }); }
watch(() => route.query.tab, (t) => { if (t && TABS[t] && t !== tab.value) { tab.value = t; load(); } });
onMounted(load);
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
.card.tbl, .tbl.card { display: block; overflow-x: auto; }
.card .tbl { display: block; overflow-x: auto; }
tr.sel td { background: var(--surface-2); }
.two { display: grid; grid-template-columns: minmax(0, 380px) minmax(0, 1fr); gap: 16px; }
@media (max-width: 700px) { .two { grid-template-columns: minmax(0, 1fr); } }
.curve { width: 100%; height: auto; }
.curve .ax { stroke: var(--line); }
.curve .ln { fill: none; stroke: var(--accent); stroke-width: 2; }
.curve .pm { stroke: var(--warn); stroke-dasharray: 4 3; }
.curve .now { stroke: var(--bad); }
.curve .t { font-size: 10px; fill: var(--muted); }
.curve .now-t { fill: var(--bad); }
.checks { display: flex; flex-direction: column; gap: 6px; margin: 8px 0; }
.chk { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 6px 8px; border: 1px solid var(--line); border-radius: 8px; }
.chk > span:first-child { flex: 1 1 200px; }
.chk.badrow { border-color: var(--bad); }
.seg button { height: 30px; padding: 0 12px; border: 1px solid var(--line); background: var(--surface); cursor: pointer; }
.seg button:first-child { border-radius: 6px 0 0 6px; }
.seg button:last-child { border-radius: 0 6px 6px 0; }
.seg button.on { background: var(--good); color: #fff; border-color: var(--good); }
.seg button.on.bad { background: var(--bad); border-color: var(--bad); }
.note { flex: 1 1 200px; }
.bad { color: var(--bad); }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; padding: 0 4px; }
.btn.sm { height: 28px; padding: 0 10px; }
.ok { color: var(--good); }
h3 { font-size: 14px; margin: 8px 0 6px; }
.num { text-align: right; }
.pill { margin-right: 6px; }
</style>
