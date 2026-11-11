<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('按单设计（ETO）') }}</h1>
      <span class="muted">{{ $t('客户的非标要求 → 作业号 → 逐行估算（AI 起草，价格取主数据）→ 报价提议，确认后写入 ERPNext') }}</span></div>
    <p v-if="cfg && !cfg.configured" class="warnbox">{{ $t('本厂还没有配置按单设计（工厂清单的 eto 一节）：风险预留、加价率、设计费率是“未知”，估算算不出报价。') }}</p>
    <div class="row">
      <div class="col">
      <section class="card side">
        <div class="card-head"><h2>{{ $t('作业') }}</h2>
          <button class="btn ghost small" @click="showNew = !showNew">{{ showNew ? $t('收起') : $t('新询价') }}</button></div>
        <form v-if="showNew" class="newform" @submit.prevent="create">
          <label class="fld"><span>{{ $t('客户') }}</span>
            <input v-model="nj.customer" list="eto-customers" required>
            <datalist id="eto-customers"><option v-for="c in customers" :key="c" :value="c" /></datalist></label>
          <label class="fld"><span>{{ $t('名称') }}</span><input v-model="nj.title" required :placeholder="$t('如：非标减速器（速比 12）')"></label>
          <label class="fld"><span>{{ $t('客户要求') }}</span>
            <textarea v-model="nj.requirement" rows="5" :placeholder="$t('尺寸、性能、材料、标准、图纸要点；参照现有产品就写它的编号')" /></label>
          <div class="two">
            <label class="fld"><span>{{ $t('数量') }}</span><input v-model.number="nj.qty" type="number" min="1" step="1" required></label>
            <label class="fld"><span>{{ $t('交期') }}</span><input v-model="nj.due_date" type="date"></label>
          </div>
          <label class="fld"><span>{{ $t('另报数量（逗号分开，可空）') }}</span><input v-model="nj.breaks" placeholder="5, 10"></label>
          <button class="btn primary" :disabled="busy">{{ $t('建作业') }}</button>
        </form>
        <div v-if="!jobs.length && !showNew" class="empty">{{ $t('还没有作业。点“新询价”录入客户的要求。') }}</div>
        <button v-for="j in jobs" :key="j.job_no" class="job" :class="{ on: sel === j.job_no }" @click="open(j.job_no)">
          <span class="mono">{{ j.job_no }}</span><span class="pill" :class="tone(j.status)">{{ $t(STATUS[j.status] || j.status) }}</span>
          <b>{{ j.title }}</b><span class="muted small">{{ $td(j.customer) }} · {{ $t('{n} 件', { n: j.qty }) }}</span>
        </button>
      </section>

      <section v-if="d" class="card side">
        <div class="card-head"><h2>{{ $t('报价') }}</h2></div>
        <table class="t">
          <thead><tr><th>{{ $t('数量') }}</th><th class="num">{{ $t('成本') }}</th><th class="num">{{ $t('单价') }}</th><th class="num">{{ $t('合计') }}</th></tr></thead>
          <tbody><tr v-for="b in res.breaks" :key="b.qty" :class="{ main: b.qty === d.job.qty }">
            <td>{{ b.qty }}</td><td class="num mono">{{ money(b.cost) }}</td><td class="num mono">{{ money(b.unit_price) }}</td><td class="num mono">{{ money(b.price) }}</td></tr></tbody>
        </table>
        <table v-if="mainB" class="t parts"><tbody>
          <tr v-for="k in CATS" :key="k[0]"><td class="muted">{{ $t(k[1]) }}</td><td class="num mono">{{ money(mainB[k[0]]) }}</td></tr>
          <tr><td class="muted">{{ $t('风险预留 {p}%', { p: res.basis.contingency_pct ?? '?' }) }}</td><td class="num mono">{{ money(mainB.contingency) }}</td></tr>
          <tr><td class="muted">{{ $t('加价 {p}% · 毛利 {m}%', { p: res.basis.markup_pct ?? '?', m: mainB.margin_pct ?? '?' }) }}</td><td></td></tr>
        </tbody></table>
        <p v-if="res.basis.example" class="small muted">{{ $t('演示工厂：费率与比例是示例值。') }}</p>
        <div v-if="d.feasibility" class="feas small" :class="d.feasibility.ok ? 'ok' : 'warnline'">
          {{ $t('粗算最早 {e} 交货（设计 {a} + 采购 {b} + 加工 {c} + 发货 {s} 个工作日）', { e: d.feasibility.earliest, a: d.feasibility.engineering_days,
            b: d.feasibility.purchase_days, c: d.feasibility.manufacturing_days, s: d.feasibility.ship_days }) }}
          <template v-if="d.feasibility.due">{{ d.feasibility.slack_days >= 0 ? $t('，赶得上交期。') : $t('，比交期晚 {n} 个工作日。', { n: -d.feasibility.slack_days }) }}</template>
          <span v-if="d.feasibility.unknown.length">{{ $t('周期不明：{a}', { a: d.feasibility.unknown.join(', ') }) }}</span>
        </div>
        <div v-if="res.errors.length || res.unknown.length" class="issues">
          <div v-for="e in res.errors" :key="e" class="err small">✗ {{ $td(e) }}</div>
          <div v-for="u in res.unknown" :key="u" class="warnline small">{{ $t('未知：{a}', { a: $td(u) }) }}</div>
        </div>
        <button class="btn primary" :disabled="!res.can_quote || dirty || d.frozen || d.job.status === 'quoting' || busy" @click="quote">{{ $t('生成报价提议') }}</button>
        <p class="small muted">{{ quoteHint }}</p>
        <button v-if="d.job.pending_proposal" class="btn ghost" @click="pid = d.job.pending_proposal">{{ $t('打开待确认的报价提议') }}</button>
        <div v-if="d.job.quotation" class="small ok">{{ $t('ERPNext 报价单 {q} · 项目 {p}', { q: d.job.quotation, p: d.job.project }) }}</div>
        <template v-if="d.job.status === 'quoted' && !d.job.sales_order">
          <h3>{{ $t('客户接受报价') }}</h3>
          <label class="fld"><span>{{ $t('交期') }}</span><input v-model="orderDue" type="date"></label>
          <button class="btn primary" :disabled="busy" @click="order">{{ $t('生成接单提议') }}</button>
          <p class="small muted">{{ $t('确认后在 ERPNext 建销售订单：单价按报出去的那一版，挂项目，付款计划按里程碑。') }}</p>
        </template>
        <div v-if="d.job.sales_order" class="small ok">{{ $t('销售订单 {s}', { s: d.job.sales_order }) }}</div>
        <h3>{{ $t('估算版本') }}</h3>
        <div v-for="r in d.revisions" :key="r.rev" class="small">
          <b>{{ $t('第 {r} 版', { r: r.rev }) }}</b> <span class="muted">{{ r.created_by }} · {{ fmtTime(r.created_at) }}</span>
          <span v-if="d.job.quoted_rev && r.rev <= d.job.quoted_rev" class="pill mute">{{ $t('冻结') }}</span></div>
        <div v-if="msg" :class="msgOk ? 'ok' : 'err'" class="small">{{ msg }}</div>
      </section>
      </div>
      <section v-if="d" class="card grow">
        <div class="card-head"><h2>{{ d.job.job_no }} {{ d.job.title }}</h2>
          <span class="muted small">{{ $td(d.job.customer) }} · {{ $t('{n} 件', { n: d.job.qty }) }}<template v-if="d.job.due_date"> · {{ $t('交期 {d}', { d: d.job.due_date }) }}</template></span></div>
        <p v-if="d.job.requirement" class="req">{{ d.job.requirement }}</p>
        <div class="tabs" role="tablist">
          <button role="tab" :aria-selected="tab === 'est'" :class="{ on: tab === 'est' }" @click="tab = 'est'">{{ $t('估算') }}</button>
          <button role="tab" :aria-selected="tab === 'design'" :class="{ on: tab === 'design' }" @click="tab = 'design'">{{ $t('设计（物料清单与工艺）') }}</button>
          <button v-if="d.job.sales_order" role="tab" :aria-selected="tab === 'mat'" :class="{ on: tab === 'mat' }" @click="tab = 'mat'">{{ $t('物料') }}</button>
          <button v-if="d.job.sales_order" role="tab" :aria-selected="tab === 'plan'" :class="{ on: tab === 'plan' }" @click="tab = 'plan'">{{ $t('计划') }}</button>
          <button v-if="d.job.sales_order" role="tab" :aria-selected="tab === 'shop'" :class="{ on: tab === 'shop' }" @click="tab = 'shop'">{{ $t('车间与成本') }}</button>
          <button role="tab" :aria-selected="tab === 'qual'" :class="{ on: tab === 'qual' }" @click="tab = 'qual'">{{ $t('图纸与质量') }}</button>
          <button v-if="d.job.sales_order" role="tab" :aria-selected="tab === 'bill'" :class="{ on: tab === 'bill' }" @click="tab = 'bill'">{{ $t('开票与毛利') }}</button>
        </div>
        <EtoDesign v-if="tab === 'design'" :job="d.job" :ops="ops" :items="allItems" :suppliers="suppliers" @changed="open(sel)" />
        <EtoMaterials v-else-if="tab === 'mat'" :job="d.job" @changed="open(sel)" />
        <EtoPlan v-else-if="tab === 'plan'" :job="d.job" />
        <EtoShop v-else-if="tab === 'shop'" :job="d.job" />
        <EtoQuality v-else-if="tab === 'qual'" :job="d.job" @changed="open(sel)" />
        <EtoBilling v-else-if="tab === 'bill'" :job="d.job" />
        <template v-else>
        <div class="tools">
          <span class="muted small">{{ d.estimate ? $t('第 {r} 版估算', { r: d.estimate.rev }) : $t('还没有估算') }}
            <template v-if="d.frozen"> · {{ $t('已报价，改动会出新版本') }}</template></span>
          <button class="btn ghost" :disabled="!editable || busy" @click="draft">{{ drafting ? $t('正在起草…') : $t('AI 起草') }}</button>
          <button class="btn ghost" :disabled="!editable" @click="add">{{ $t('加一行') }}</button>
          <button class="btn" :disabled="!editable || busy || !dirty" @click="save">{{ $t('保存估算') }}</button>
        </div>
        <p v-if="note" class="notebox small">{{ $td(note) }}</p>
        <div class="tablewrap">
          <table class="t lines">
            <thead><tr><th>{{ $t('类别') }}</th><th>{{ $t('物料 / 工序') }}</th><th>{{ $t('说明') }}</th>
              <th class="num">{{ $t('用量 / 件') }}</th><th class="num">{{ $t('单价') }}</th><th class="num">{{ $t('调整（分）') }}</th>
              <th class="num">{{ $t('单件（分）') }}</th><th class="num">{{ $t('工时（时）') }}</th><th></th></tr></thead>
            <tbody>
              <tr v-for="(ln, i) in lines" :key="i" :class="{ bad: rowErr(i), miss: rowMiss(i) }">
                <td><select v-model="ln.kind" :disabled="!editable" @change="touch"><option v-for="k in KINDS" :key="k" :value="k">{{ $t(KIND_ZH[k]) }}</option></select></td>
                <td>
                  <select v-if="ln.kind === 'operation'" v-model="ln.op" :disabled="!editable" @change="touch">
                    <option v-for="o in ops" :key="o" :value="o">{{ $td(o) }}</option></select>
                  <input v-else-if="ln.kind === 'material' || ln.kind === 'buyout'" v-model="ln.item_code" class="mono code" list="eto-items"
                    :disabled="!editable" :placeholder="$t('编号（新物料空着）')" @input="touch">
                  <span v-else class="muted">—</span>
                </td>
                <td><input v-model="ln.desc" :disabled="!editable" @input="touch">
                  <small v-if="ln.source === 'ai'" class="tag">AI</small></td>
                <td class="num"><input v-if="has(ln, 'qty_per')" v-model.number="ln.qty_per" type="number" step="any" :disabled="!editable" @input="touch"></td>
                <td class="num"><input v-if="has(ln, 'unit_price')" v-model.number="ln.unit_price" type="number" step="any" :disabled="!editable"
                  :placeholder="masterPrice(i)" @input="touch"></td>
                <td class="num"><input v-if="has(ln, 'setup_min')" v-model.number="ln.setup_min" type="number" step="any" :disabled="!editable" @input="touch"></td>
                <td class="num"><input v-if="has(ln, 'run_min')" v-model.number="ln.run_min" type="number" step="any" :disabled="!editable" @input="touch"></td>
                <td class="num"><input v-if="has(ln, 'hours')" v-model.number="ln.hours" type="number" step="any" :disabled="!editable" @input="touch"></td>
                <td><button v-if="editable" class="x" :aria-label="$t('删去这一行')" @click="lines.splice(i, 1); touch()">×</button></td>
              </tr>
              <tr v-if="!lines.length"><td colspan="9" class="empty">{{ $t('没有估算行：点“AI 起草”，或“加一行”手工填。') }}</td></tr>
            </tbody>
          </table>
          <datalist id="eto-items"><option v-for="it in items" :key="it.code" :value="it.code">{{ $td(it.name) }}</option></datalist>
        </div>
        <p class="muted small">{{ $t('单价空着的：有物料编号就取物料主数据的单价（灰字），没有的要填。工序费率取工作站的折旧 + 人工 + 能耗。') }}</p>
        <div v-if="dirty" class="small warnline">{{ $t('有改动还没保存：下面的金额是上次保存的。') }}</div>
        </template>
      </section>
      <section v-else class="card grow empty">{{ $t('选一个作业，或录入新询价。') }}</section>

    </div>
    <ProposalModal v-if="pid" :pid="pid" @close="pid = null; open(sel)" @done="open(sel)" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { api, get, loadConfig, post } from '../lib/api';
import { loc, t as $t, td as $td, tk } from '../lib/i18n';
import ProposalModal from '../components/ProposalModal.vue';
import EtoDesign from '../components/EtoDesign.vue';
import EtoMaterials from '../components/EtoMaterials.vue';
import EtoPlan from '../components/EtoPlan.vue';
import EtoShop from '../components/EtoShop.vue';
import EtoQuality from '../components/EtoQuality.vue';
import EtoBilling from '../components/EtoBilling.vue';

const KINDS = ['material', 'buyout', 'operation', 'outside', 'engineering'];
const KIND_ZH = { material: tk('材料'), buyout: tk('外购件'), operation: tk('工序'), outside: tk('外协'), engineering: tk('设计') };
const STATUS = { estimating: tk('估算中'), quoting: tk('报价待确认'), quoted: tk('已报价'), ordered: tk('已接单'), shipped: tk('已发货') };
const CATS = [['material', tk('材料与外购件')], ['operations', tk('工序')], ['outside', tk('外协')], ['engineering', tk('设计（一次性）')]];
const FIELDS = { material: ['qty_per', 'unit_price'], buyout: ['qty_per', 'unit_price'], operation: ['setup_min', 'run_min'],
  outside: ['unit_price'], engineering: ['hours'] };

const cfg = ref(null);
const jobs = ref([]);
const route = useRoute();
const sel = ref(null);
const d = ref(null);
const lines = ref([]);
const note = ref('');
const source = ref('human');
const dirty = ref(false);
const busy = ref(false);
const drafting = ref(false);
const showNew = ref(false);
const customers = ref([]);
const ops = ref([]);
const items = ref([]);
const allItems = ref([]);
const suppliers = ref({});
const tab = ref('est');
const orderDue = ref('');
const pid = ref(null);
const msg = ref('');
const msgOk = ref(true);
const nj = ref({ customer: '', title: '', requirement: '', qty: 1, due_date: '', breaks: '' });

const res = computed(() => d.value?.result || { breaks: [], errors: [], unknown: [], basis: {} });
const mainB = computed(() => res.value.breaks.find((b) => b.qty === d.value?.job.qty));
const editable = computed(() => d.value && d.value.job.status !== 'quoting');
const quoteHint = computed(() => {
  if (!d.value) return '';
  if (d.value.job.status === 'quoting') return $t('报价提议在等确认：确认后桥接在 ERPNext 建项目（作业号）、物料和报价单。');
  if (d.value.frozen) return $t('这一版已经报过价。要改价先改估算，保存后是新的一版。');
  if (dirty.value) return $t('先保存估算。');
  if (!res.value.can_quote) return $t('有未知或错误项时不能报价：补齐数据，不估。');
  return $t('报价单上报客户要的数量，其余数量阶梯和付款条件写进条款。');
});
const money = (x) => (x === null || x === undefined ? '—' : '$' + Number(x).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const fmtTime = (s) => new Date(s).toLocaleString(loc(), { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const tone = (s) => ({ estimating: 'info', quoting: 'warn', quoted: 'good', ordered: 'good', shipped: 'good' }[s] || 'mute');
const has = (ln, f) => (FIELDS[ln.kind] || []).includes(f);
const rowErr = (i) => !dirty.value && (res.value.lines?.[i]?.errors || []).length > 0;
const rowMiss = (i) => !dirty.value && (res.value.lines?.[i]?.missing || []).length > 0;
const masterPrice = (i) => {
  const r = res.value.lines?.[i];
  return r && r.price_from === '物料主数据' ? String(r.unit_price) : '';   // i18n-ok 枢纽返回的出处标记，不显示
};
function touch() { dirty.value = true; }
function say(text, ok = true) { msg.value = text; msgOk.value = ok; }

async function loadJobs() { jobs.value = await get('/eto/jobs'); }
async function open(jn) {
  if (!jn) return;
  if (sel.value !== jn) tab.value = 'est';
  sel.value = jn; msg.value = '';
  const r = await get('/eto/jobs/' + encodeURIComponent(jn));
  apply(r);
  await loadJobs();
}
function apply(r) {
  d.value = r;
  orderDue.value = r.job.due_date || '';
  lines.value = JSON.parse(JSON.stringify(r.estimate?.lines || []));
  note.value = r.estimate?.note || '';
  source.value = r.estimate?.source || 'human';
  dirty.value = false;
}
async function create() {
  busy.value = true;
  try {
    const br = nj.value.breaks.split(/[,，\s]+/).filter(Boolean).map(Number);   // i18n-ok 中文逗号也认
    const j = await post('/eto/jobs', { ...nj.value, qty_breaks: br, due_date: nj.value.due_date || null });
    showNew.value = false;
    nj.value = { customer: '', title: '', requirement: '', qty: 1, due_date: '', breaks: '' };
    await open(j.job_no);
  } catch (e) { say(e.message, false); } finally { busy.value = false; }
}
async function draft() {
  if (lines.value.length && !window.confirm($t('起草的结果会替换现在的估算行（保存后才生效），继续吗？'))) return;
  drafting.value = true; busy.value = true;
  try {
    const r = await post(`/eto/jobs/${encodeURIComponent(sel.value)}/draft`);
    lines.value = r.lines; note.value = r.note; source.value = r.source; dirty.value = true;
  } catch (e) { say(e.message, false); } finally { drafting.value = false; busy.value = false; }
}
function add() { lines.value.push({ kind: 'operation', op: ops.value[0], desc: '', source: 'human' }); touch(); }
async function save() {
  busy.value = true;
  try {
    const r = await api('PUT', `/eto/jobs/${encodeURIComponent(sel.value)}/estimate`, { lines: lines.value, note: note.value, source: source.value });
    apply(r);
    say($t('已保存第 {r} 版估算。', { r: r.estimate.rev }));
  } catch (e) { say(e.message, false); } finally { busy.value = false; }
}
async function quote() {
  busy.value = true;
  try {
    const r = await post(`/eto/jobs/${encodeURIComponent(sel.value)}/quote`);
    pid.value = r.proposal_id;
    await open(sel.value);
  } catch (e) { say(e.message, false); } finally { busy.value = false; }
}
async function order() {
  busy.value = true;
  try {
    const r = await post(`/eto/jobs/${encodeURIComponent(sel.value)}/order`, { delivery_date: orderDue.value || null });
    pid.value = r.proposal_id;
  } catch (e) { say(e.message, false); } finally { busy.value = false; }
}
onMounted(async () => {
  const [c, conf] = await Promise.all([get('/eto/config'), loadConfig()]);
  cfg.value = c;
  customers.value = conf.customers || [];
  ops.value = c.operations || [];
  items.value = c.items || [];
  allItems.value = c.all_items || [];
  suppliers.value = c.suppliers || {};
  await loadJobs();
  const want = String(route.query.job || '');                 // 实验 33 等页面带 ?job= 直接打开那张作业
  const hit = jobs.value.find((j) => j.job_no === want);
  if (hit || jobs.value.length) await open((hit || jobs.value[0]).job_no);
});
</script>

<style scoped>
.col { width: 310px; flex-shrink: 0; display: flex; flex-direction: column; gap: 16px; }
.side { display: flex; flex-direction: column; gap: 8px; }
.grow { flex-grow: 1; min-width: 0; }
.fld { display: flex; flex-direction: column; gap: 3px; font-size: 13px; }
.fld input, .fld textarea, .fld select { border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; font: inherit; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.newform { display: flex; flex-direction: column; gap: 8px; padding-bottom: 10px; border-bottom: 1px solid var(--line); }
.job { display: grid; grid-template-columns: 1fr auto; gap: 2px 8px; text-align: left; padding: 8px 10px; border: 1px solid var(--line);
  border-radius: 8px; background: #fff; cursor: pointer; font: inherit; }
.job b, .job .small { grid-column: 1 / -1; }
.job.on { border-color: var(--accent); background: var(--accent-bg); }
.req { white-space: pre-wrap; background: #F7F8FA; border-radius: 8px; padding: 8px 10px; font-size: 13px; margin: 0 0 10px; }
.tools { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.tools > span { margin-right: auto; }
.notebox { background: var(--accent-bg); border-radius: 8px; padding: 8px 10px; white-space: pre-wrap; }
.tablewrap { overflow-x: auto; }
.lines td { padding: 3px 4px; vertical-align: top; }
.lines input, .lines select { width: 100%; min-width: 60px; border: 1px solid var(--line); border-radius: 5px; padding: 3px 5px; font: inherit; font-size: 13px; }
.lines td.num input { width: 76px; text-align: right; }
.lines input.code { min-width: 110px; }
.lines tr.bad td { background: #FDECEC; }
.lines tr.miss td { background: #FFF8EC; }
.tag { font-size: 10px; color: var(--accent); margin-left: 4px; }
.x { border: none; background: none; font-size: 16px; cursor: pointer; color: var(--muted, #888); }
tr.main td { font-weight: 600; }
.side .t { font-size: 12px; }
.side .t td, .side .t th { padding: 4px 3px; }
.parts td { padding: 3px 6px; }
.issues { display: flex; flex-direction: column; gap: 3px; max-height: 220px; overflow-y: auto; }
.err { color: var(--bad); } .ok { color: var(--good); } .warnline { color: var(--warn-ink); }
.warnbox { background: var(--warn-bg); color: var(--warn-ink); border-radius: 8px; padding: 10px 12px; }
.empty { color: var(--muted, #888); padding: 16px 0; }
.feas { border-radius: 6px; padding: 6px 8px; background: #F7F8FA; }
.tabs { display: flex; gap: 6px; margin-bottom: 10px; }
.tabs button { padding: 6px 12px; border-radius: 8px; border: 1px solid var(--line); background: #fff; cursor: pointer; font: inherit; }
.tabs button.on { border-color: var(--accent); background: var(--accent-bg); }
.btn.small { height: 26px; font-size: 12px; margin-left: auto; }
.side h3 { font-size: 13px; margin: 10px 0 4px; }
@media (max-width: 1100px) { .row { flex-direction: column; } .col { width: auto; } }
</style>
