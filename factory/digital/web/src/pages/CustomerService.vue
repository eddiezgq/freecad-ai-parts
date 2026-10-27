<!-- 客户与服务（第 18 轮 E1）：销售漏斗、投诉、服务派工与排班、回访与满意度。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>客户与服务</h1>
      <span class="muted">线索 → 商机 → 报价 → 合同 → 订单；投诉 → 追溯 → 派工 → 回访。线索、商机、报价、合同、服务工单都在 ERPNext 里有对应单据</span>
      <span class="tabs" data-help="svc-tabs" role="tablist"><button v-for="(l, k) in TABS" :key="k" type="button" role="tab" :class="{ on: tab === k }" @click="go(k)">{{ l }}
        <span v-if="k === 'complaints' && kp?.open_complaints" class="cnt">{{ kp.open_complaints }}</span></button></span></div>
    <div v-if="err" class="err">{{ err }}</div>

    <section v-if="kp" class="kpis" data-help="svc-kpis">
      <div class="card k"><span class="small muted">满意度（近 30 天）</span><b>{{ kp.satisfaction ?? '—' }}<small v-if="kp.satisfaction"> / 5</small></b><span class="small muted">{{ kp.surveys }} 次回访</span></div>
      <div class="card k"><span class="small muted">开着的投诉</span><b>{{ kp.open_complaints }}</b><span class="small muted">平均响应 {{ kp.response_h ?? '—' }} 小时</span></div>
      <div class="card k"><span class="small muted">待上门的服务</span><b>{{ kp.open_jobs }}</b><span class="small muted">一次修复率 {{ kp.first_fix == null ? '—' : Math.round(kp.first_fix * 100) + '%' }}</span></div>
      <div class="card k"><span class="small muted">保修成本（近 30 天）</span><b>${{ Math.round(kp.warranty_cost).toLocaleString() }}</b></div>
      <div class="card k"><span class="small muted">漏斗金额</span><b>${{ Math.round(kp.funnel_amount).toLocaleString() }}</b><span class="small muted">本月成交 ${{ Math.round(kp.won_month).toLocaleString() }}</span></div>
    </section>

    <!-- ⑤ 客户 360（AI 代理的 customer_360 工具用的是同一个接口） -->
    <template v-if="tab === 'c360'">
      <div class="card add">
        <label>客户 <select v-model="cust" @change="load360">
          <option v-for="c in custs" :key="c" :value="c">{{ c }}</option></select></label>
      </div>
      <section v-if="c3" class="card">
        <div class="card-head"><h2>{{ c3.customer }}</h2>
          <span class="small muted">满意度 {{ c3.satisfaction ?? '—' }}（{{ c3.surveys }} 次回访）</span></div>
        <p v-if="c3.contract?.hidden" class="small muted">合同 {{ c3.contract.name }}：条款你没有权限查看。</p>
        <p v-else-if="c3.contract" class="small">合同 <b class="mono">{{ c3.contract.name }}</b>：延期违约金 {{ c3.contract.penalty_per_day ? '$' + c3.contract.penalty_per_day + '/天' : '无' }}，
          投诉响应 {{ c3.contract.response_h ?? 24 }} 小时，保修 {{ c3.contract.warranty_months ?? 12 }} 个月（{{ c3.contract.start }} 起）</p>
        <p v-else class="small muted">没有生效的合同（按默认：响应 24 小时、保修 12 个月）。</p>
        <h3>现场设备</h3>
        <table v-if="c3.units.length" class="tbl small"><thead><tr><th>序列号</th><th>现场</th><th>健康度</th><th>报警</th><th>保修到</th></tr></thead>
          <tbody><tr v-for="x in c3.units" :key="x.serial"><td class="mono"><router-link :to="{ path: '/twin', query: { serial: x.serial } }">{{ x.serial }}</router-link></td>
            <td>{{ x.site }}</td><td><span class="pill" :class="{ red: 'bad', yellow: 'warn', green: 'good' }[x.health]">{{ { red: '红', yellow: '黄', green: '绿' }[x.health] || x.health }}</span></td>
            <td>{{ x.alerts.join('；') || '—' }}</td><td>{{ x.warranty_until || '—' }}{{ x.in_warranty ? '' : '（已过保）' }}</td></tr></tbody></table>
        <p v-else class="small muted">没有现场设备。</p>
        <h3>订单</h3>
        <p class="small"><span v-for="o in c3.orders" :key="o.name" class="mono">{{ o.name }}（{{ o.qty }} 台，交期 {{ o.delivery_date }}）　</span><span v-if="!c3.orders.length" class="muted">没有订单。</span></p>
        <h3>投诉与服务</h3>
        <p class="small"><span v-for="c in c3.complaints" :key="c.key">{{ c.key }} {{ c.subject }}（{{ c.status }}）　</span><span v-if="!c3.complaints.length" class="muted">没有投诉。</span></p>
        <p class="small"><span v-for="j in c3.jobs" :key="j.key">{{ j.key }} {{ j.serial }} {{ j.kind }}（{{ j.status === 'done' ? '已完成' : j.day }}）　</span></p>
      </section>
    </template>

    <!-- ① 销售漏斗 -->
    <template v-if="tab === 'funnel' && pl">
      <div class="card add" v-if="pl.can_edit">
        <b class="small">新线索</b>
        <input v-model="nl.company_name" placeholder="公司名称" aria-label="公司名称">
        <input v-model="nl.note" placeholder="需求（例如：输送线改造，6 台）" aria-label="需求">
        <button class="btn sm primary" @click="newLead">添加</button>
        <span class="small muted">{{ msg }}</span>
      </div>
      <div class="board">
        <div v-for="st in pl.stages.slice(0, 4)" :key="st.key" class="col">
          <div class="ch"><b>{{ st.label }}</b><span class="small muted">{{ st.count }}</span></div>
          <div v-for="c in pl.cards.filter((x) => x.stage === st.key)" :key="c.name" class="card cc">
            <div class="small mono muted">{{ c.name }}</div>
            <b>{{ c.title }}</b>
            <div v-if="c.amount" class="small">${{ Math.round(c.amount).toLocaleString() }}</div>
            <div v-if="c.note" class="small muted">{{ c.note }}</div>
            <div v-if="c.terms" class="small muted">保修 {{ c.terms.warranty_months }} 个月 · 响应 {{ c.terms.response_h }} 小时 · 违约金 ${{ c.terms.penalty_per_day }}/天</div>
            <div v-if="c.date" class="small muted">{{ st.key === 'quotation' ? '有效期到 ' : '' }}{{ c.date }}</div>
            <div v-if="pl.can_edit" class="act">
              <template v-if="st.key === 'lead'"><input v-model.number="qty[c.name]" type="number" min="1" placeholder="台数" class="n" aria-label="台数">
                <button class="linkbtn" @click="toOpp(c)">转成商机</button></template>
              <template v-else-if="st.key === 'opportunity'"><input v-model.number="qty[c.name]" type="number" min="1" placeholder="台数" class="n" aria-label="台数">
                <button class="linkbtn" @click="toQuote(c)">出报价（${{ pl.price.toLocaleString() }}/台）</button></template>
              <template v-else-if="st.key === 'quotation'"><button class="linkbtn" @click="ct = { quotation: c, customer: c.title, penalty_per_day: 0, response_h: 24, warranty_months: 12, amount: c.amount }">签合同…</button></template>
              <template v-else-if="st.key === 'contract'"><input v-model.number="qty[c.name]" type="number" min="1" placeholder="台数" class="n" aria-label="台数">
                <input v-model="due[c.name]" type="date" class="d" aria-label="交期"><button class="linkbtn" @click="toOrder(c)">转订单</button></template>
            </div>
          </div>
        </div>
      </div>
      <div v-if="ct" class="card">
        <h3>签合同：{{ ct.customer }}（报价 {{ ct.quotation.name }}）</h3>
        <div class="grid3">
          <label>客户名称<input v-model="ct.customer"></label>
          <label>保修期（月）<input v-model.number="ct.warranty_months" type="number" min="0"></label>
          <label>投诉响应时限（小时）<input v-model.number="ct.response_h" type="number" min="1"></label>
          <label>延期违约金（$/天）<input v-model.number="ct.penalty_per_day" type="number" min="0"></label>
        </div>
        <p class="small muted">违约金会进入推演：这个客户的订单有延期风险时，指挥台按合同算违约金。</p>
        <button class="btn primary sm" @click="sign">签合同（写入 ERPNext）</button> <button class="btn sm" @click="ct = null">取消</button>
      </div>
      <div class="card">
        <h3>生效中的合同</h3>
        <table class="tbl small"><thead><tr><th>合同</th><th>客户</th><th class="num">保修（月）</th><th class="num">响应（小时）</th><th class="num">违约金 $/天</th><th>期限</th></tr></thead>
          <tbody><tr v-for="c in pl.contracts" :key="c.name"><td class="mono">{{ c.name }}<span v-if="c.demo" class="pill mute">演示</span></td><td>{{ c.customer }}</td>
            <td class="num">{{ c.warranty_months ?? '—' }}</td><td class="num">{{ c.response_h ?? '—' }}</td><td class="num">{{ c.penalty_per_day }}</td><td>{{ c.start }} — {{ c.end }}</td></tr></tbody></table>
      </div>
    </template>

    <!-- ② 投诉 -->
    <template v-if="tab === 'complaints' && cp">
      <div v-if="cp.can_edit" class="card" data-help="svc-complaint">
        <h3>登记投诉</h3>
        <div class="grid3">
          <label>设备序列号（铭牌）<input v-model="nc.serial" list="serials" placeholder="例如 WQR105-H2504-06"></label>
          <datalist id="serials"><option v-for="x in cp.units" :key="x.serial" :value="x.serial">{{ x.customer }}</option></datalist>
          <label>客户（填了序列号可不填）<input v-model="nc.customer"></label>
          <label>严重度<select v-model="nc.severity"><option v-for="(l, k) in cp.severities" :key="k" :value="k">{{ l }}</option></select></label>
          <label class="w2">现象<input v-model="nc.subject" placeholder="例如：异响、油温偏高"></label>
          <label>渠道<select v-model="nc.channel"><option>电话</option><option>邮件</option><option>现场</option><option>微信</option></select></label>
          <label>联系人 / 邮箱<input v-model="nc.contact"></label>
          <label class="w2">详细描述<input v-model="nc.detail"></label>
        </div>
        <button class="btn primary sm" @click="newComplaint">登记（同时在 ERPNext 开投诉单）</button> <span class="small ok">{{ msg }}</span>
      </div>
      <div class="filters small"><label><input v-model="cpOpen" type="checkbox" @change="loadCp"> 只看没关闭的</label></div>
      <p v-if="!cp.complaints.length" class="muted small">没有投诉。</p>
      <div v-for="c in cp.complaints" :key="c.id" class="card item" :class="c.severity">
        <div class="ih"><span class="mono small">{{ c.key }}</span><b>{{ c.subject }}</b><span class="pill" :class="c.status === 'closed' ? 'good' : c.status === 'doing' ? 'info' : 'warn'">{{ c.status_label }}</span>
          <span class="pill" :class="c.severity === 'urgent' ? 'bad' : 'mute'">{{ c.severity_label }}</span></div>
        <div class="small">{{ c.customer }}<template v-if="c.serial"> · 设备 <router-link :to="'/ont/FieldUnit/' + c.serial">{{ c.serial }}</router-link></template>
          · {{ c.channel }} · {{ fmtTs(c.created_at) }} · {{ c.created_by }}<template v-if="c.issue"> · ERPNext {{ c.issue }}</template></div>
        <div v-if="c.serial && !c.traceable" class="small warn-t">这台没有出厂数据，追不到车间</div>
        <div v-if="c.unit" class="small muted">孪生健康度 {{ { red: '红', yellow: '黄', green: '绿' }[c.unit.health] }} · {{ c.unit.in_warranty ? '保修期内（到 ' + c.unit.warranty_until + '）' : '已过保修期' }}</div>
        <div class="act">
          <router-link v-if="c.anomaly_id" :to="{ path: '/ont', query: { view: 'anomalies', a: c.anomaly_id } }" class="btn sm primary">追溯与处理方案</router-link>
          <template v-if="cp.can_edit && c.status !== 'closed'">
            <button v-if="c.status === 'open'" class="btn sm" @click="respond(c, 'doing')">已联系客户</button>
            <button class="btn sm" @click="respond(c, 'closed')">关闭</button></template>
        </div>
      </div>
    </template>

    <!-- ③ 服务 -->
    <template v-if="tab === 'service'">
      <div v-if="sc" class="card">
        <div class="card-head"><h3>工程师排班（现场日 {{ sc.start }} 起 14 天）</h3><span class="small muted">本区域每天最多 2 单；去外区域当天只做 1 单</span></div>
        <div class="sched">
          <table class="tbl small"><thead><tr><th>工程师</th><th v-for="d in sc.engineers[0]?.days || []" :key="d.day" :class="{ off: d.off }">{{ d.day.slice(5) }}</th></tr></thead>
            <tbody><tr v-for="e in sc.engineers" :key="e.id"><td class="nm">{{ e.name }}<span class="muted"> · {{ e.region }}</span></td>
              <td v-for="d in e.days" :key="d.day" :class="{ off: d.off, busy: d.jobs.length }" :title="d.jobs.map((j) => j.serial + ' ' + j.kind).join('\n')">
                {{ d.off ? '休' : d.jobs.length || '' }}</td></tr></tbody></table>
        </div>
      </div>
      <div v-if="jb" class="card">
        <h3>服务工单</h3>
        <table class="tbl small"><thead><tr><th>单号</th><th>设备 · 客户</th><th>内容</th><th>工程师</th><th>上门日</th><th>保修</th><th>ERPNext</th><th>状态</th><th></th></tr></thead>
          <tbody><tr v-for="j in jb.jobs" :key="j.id"><td class="mono">{{ j.key }}</td><td>{{ j.serial }}<br><span class="muted">{{ j.customer }}</span></td><td>{{ j.kind_label }}</td>
            <td>{{ j.engineer_name || '待定' }}</td><td>{{ j.day || '—' }}</td><td>{{ j.warranty ? '保修内' : '收费' }}</td><td class="mono">{{ j.issue || '…' }}</td>
            <td>{{ { planned: '待上门', done: '已完成', cancelled: '已取消' }[j.status] }}<div v-if="j.result" class="muted">{{ j.result }}</div></td>
            <td><button v-if="jb.can_edit && j.status === 'planned'" class="linkbtn" @click="done(j)">完工</button></td></tr></tbody></table>
        <p v-if="!jb.jobs.length" class="muted small">还没有服务工单。投诉或现场报警在厂情中枢里采纳处理方案、批准后，会自动排进日历。</p>
      </div>
      <div v-if="nt?.notices.length" class="card">
        <h3>客户通知</h3>
        <div v-for="n in nt.notices" :key="n.id" class="small notice"><b>{{ n.customer }}</b> · {{ { draft: '草稿', sent: '已发出', recorded: '已记录（未发出）' }[n.status] }} · {{ fmtTs(n.created_at) }}
          <details><summary>内容</summary><pre>{{ n.body }}</pre></details></div>
      </div>
    </template>

    <!-- ④ 回访与满意度 -->
    <template v-if="tab === 'followups' && fu">
      <div class="card">
        <h3>回访（服务完成后 1 天）</h3>
        <table class="tbl small"><thead><tr><th>回访</th><th>客户 · 设备</th><th>服务内容</th><th>应回访日</th><th>满意度</th><th>意见</th></tr></thead>
          <tbody><tr v-for="f in fu.followups" :key="f.id"><td class="mono">{{ f.key }}</td><td>{{ f.customer }}<br><span class="muted">{{ f.serial }}</span></td><td>{{ f.kind }}</td><td>{{ f.due_day }}</td>
            <td><template v-if="f.score != null"><b>{{ f.score }}</b> / 5</template>
              <template v-else-if="fu.can_edit"><select v-model.number="sco[f.id]"><option v-for="s in [5, 4, 3, 2, 1]" :key="s" :value="s">{{ s }}</option></select></template></td>
            <td><template v-if="f.score != null">{{ f.comment }}</template>
              <template v-else-if="fu.can_edit"><input v-model="cmt[f.id]" placeholder="客户的一句话"><button class="linkbtn" @click="score(f)">记下</button></template></td></tr></tbody></table>
        <p v-if="!fu.followups.length" class="muted small">还没有回访。</p>
      </div>
    </template>
    <ProposalModal v-if="pid" :pid="pid" @close="pid = null; loadPl()" />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post } from '../lib/api';
import { fmtTs } from '../lib/ont';
import ProposalModal from '../components/ProposalModal.vue';

const TABS = { funnel: '销售漏斗', complaints: '投诉', service: '服务与排班', followups: '回访与满意度', c360: '客户 360' };
const route = useRoute();
const router = useRouter();
const tab = ref(TABS[route.query.tab] ? route.query.tab : (route.query.customer ? 'c360' : 'complaints'));
const err = ref('');
const msg = ref('');
const kp = ref(null);
const pl = ref(null);
const cp = ref(null);
const sc = ref(null);
const jb = ref(null);
const fu = ref(null);
const nt = ref(null);
const pid = ref(null);
const ct = ref(null);
const cpOpen = ref(true);
const nl = reactive({ company_name: '', note: '' });
const nc = reactive({ serial: '', customer: '', severity: 'normal', subject: '', channel: '电话', contact: '', detail: '' });
const qty = reactive({});
const due = reactive({});
const sco = reactive({});
const cmt = reactive({});

function go(k) { tab.value = k; router.replace({ query: { ...route.query, tab: k } }); load(); }
async function wrap(fn) { err.value = ''; try { await fn(); } catch (e) { err.value = e.message; } }
const loadKp = () => wrap(async () => { kp.value = await get('/service/kpis'); });
const loadPl = () => wrap(async () => { pl.value = await get('/crm/pipeline'); });
const loadCp = () => wrap(async () => { cp.value = await get('/complaints' + (cpOpen.value ? '?status=open' : '')); });
const loadSv = () => wrap(async () => { [sc.value, jb.value, nt.value] = await Promise.all([get('/service/schedule'), get('/service/jobs'), get('/service/notices')]); });
const loadFu = () => wrap(async () => { fu.value = await get('/followups'); });
const cust = ref(route.query.customer || '');
const custs = ref([]);
const c3 = ref(null);
const load360 = () => wrap(async () => { if (cust.value) c3.value = await get('/ont/customer360/' + encodeURIComponent(cust.value)); });
const loadC3 = () => wrap(async () => {
  const [p, u] = await Promise.all([get('/crm/pipeline'), get('/service/units')]);
  custs.value = [...new Set([...p.customers, ...u.units.map((x) => x.customer)])].sort();
  if (!cust.value) cust.value = u.units[0]?.customer || custs.value[0] || '';
  await load360();
});
function load() {
  loadKp();
  ({ funnel: loadPl, complaints: loadCp, service: loadSv, followups: loadFu, c360: loadC3 })[tab.value]();
}
const later = (f) => setTimeout(f, 4000);           // 写进 ERPNext 后，桥接要几秒才把单据读回来
async function newLead() { await wrap(async () => { await post('/crm/leads', { ...nl }); nl.company_name = ''; nl.note = ''; msg.value = '已写入 ERPNext，稍后出现'; later(loadPl); }); }
async function toOpp(c) { await wrap(async () => { await post('/crm/opportunities', { from: 'Lead', party: c.name, qty: qty[c.name] || 1 }); later(loadPl); }); }
async function toQuote(c) {
  await wrap(async () => {
    await post('/crm/quotations', { quotation_to: c.lead ? 'Lead' : 'Customer', party: c.lead || c.title, opportunity: c.name, qty: qty[c.name] || 1 });
    later(loadPl);
  });
}
async function sign() {
  await wrap(async () => {
    await post('/crm/contracts', { customer: ct.value.customer, quotation: ct.value.quotation.name, amount: ct.value.amount, penalty_per_day: ct.value.penalty_per_day,
      response_h: ct.value.response_h, warranty_months: ct.value.warranty_months });
    ct.value = null; later(loadPl);
  });
}
async function toOrder(c) {
  await wrap(async () => {
    if (!due[c.name]) throw new Error('选交期');
    const r = await post(`/crm/contracts/${encodeURIComponent(c.name)}/order`, { qty: qty[c.name] || 1, delivery_date: due[c.name] });
    pid.value = r.proposal_id;
  });
}
async function newComplaint() {
  await wrap(async () => { const r = await post('/complaints', { ...nc }); msg.value = '已登记 ' + r.key + '；厂情中枢下一轮检测（20 秒内）会开异常'; nc.subject = ''; nc.detail = ''; loadCp(); loadKp(); });
}
async function respond(c, status) { await wrap(async () => { await post(`/complaints/${c.id}/respond`, { status }); loadCp(); loadKp(); }); }
async function done(j) { await wrap(async () => { await post(`/service/jobs/${j.id}/done`, { note: '' }); loadSv(); loadKp(); }); }
async function score(f) { await wrap(async () => { await post(`/followups/${f.id}`, { score: sco[f.id] || 5, comment: cmt[f.id] || '' }); loadFu(); loadKp(); }); }
watch(() => route.query.tab, (t) => { if (t && TABS[t] && t !== tab.value) { tab.value = t; load(); } });
onMounted(load);
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.tabs { margin-left: auto; display: flex; gap: 4px; flex-wrap: wrap; }
.tabs button { height: 30px; padding: 0 12px; border: 1px solid var(--line); background: var(--surface); border-radius: 6px; cursor: pointer; }
.tabs button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.cnt { background: var(--bad); color: #fff; border-radius: 8px; font-size: 10px; padding: 0 5px; margin-left: 4px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; margin-bottom: 12px; }
.k { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; }
.k b { font-size: 22px; }
.add { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
input, select { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; min-width: 0; }
.board { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
@media (max-width: 900px) { .board { grid-template-columns: minmax(0, 1fr); } }
.col { background: var(--surface-2); border-radius: 10px; padding: 8px; min-width: 0; }
.ch { display: flex; justify-content: space-between; margin-bottom: 6px; }
.cc { padding: 8px 10px; margin-bottom: 8px; display: flex; flex-direction: column; gap: 2px; }
.act { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 6px; }
.n { width: 70px; }
.d { width: 140px; }
.grid3 { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px 12px; margin: 8px 0; }
.grid3 label { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--muted); }
.grid3 .w2 { grid-column: span 2; }
@media (max-width: 600px) { .grid3 .w2 { grid-column: span 1; } }
.item { margin-bottom: 8px; border-left: 4px solid var(--warn); }
.item.urgent { border-left-color: var(--bad); }
.ih { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.warn-t { color: #8A5A00; }
.filters { margin: 6px 0; }
.sched { overflow-x: auto; }
.sched td, .sched th { text-align: center; min-width: 34px; }
.sched td.nm { text-align: left; white-space: nowrap; }
.sched .off { color: var(--muted); background: var(--surface-2); }
.sched td.busy { background: #E8F1FB; font-weight: 600; }
.notice pre { white-space: pre-wrap; font-size: 12px; }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; padding: 0; }
.btn.sm { height: 28px; padding: 0 10px; }
.ok { color: var(--good); }
h3 { font-size: 14px; margin: 0 0 6px; }
.num { text-align: right; }
</style>
