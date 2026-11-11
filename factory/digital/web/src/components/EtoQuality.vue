<template>
  <div class="qual">
    <p v-if="err" class="muted">{{ err }}</p>
    <template v-else-if="q">
      <h3>{{ $t('客户图纸') }}</h3>
      <div class="files">
        <a v-for="f in q.files" :key="f.id" :href="'/api/files/' + f.sha256" target="_blank" rel="noopener" class="file">
          {{ f.name }} <span class="muted small">{{ kb(f.size) }}{{ f.has_text ? '' : ' · ' + $t('没有文字（AI 读不到）') }}</span></a>
        <label class="btn ghost tiny up">{{ $t('上传图纸') }}<input type="file" accept=".pdf,image/*" @change="upload"></label>
      </div>
      <p class="small muted">{{ $t('PDF 图纸的文字给 AI 起草估算和检验项时读；扫描件读不到文字，请把关键尺寸写进客户要求。') }}</p>

      <h3>{{ $t('检验计划') }}
        <span v-if="q.approved" class="pill good">{{ $t('第 {r} 版已批准（{w}）', { r: q.approved.rev, w: q.approved.approved_by }) }}</span></h3>
      <div class="tools">
        <span class="muted small">{{ q.plan ? $t('第 {r} 版 · {s}', { r: q.plan.rev, s: $t(PST[q.plan.status]) }) : $t('还没有检验计划') }}</span>
        <button class="btn ghost" :disabled="busy" @click="draft">{{ $t('AI 起草') }}</button>
        <button class="btn ghost" @click="addChar">{{ $t('加一项') }}</button>
        <button class="btn" :disabled="busy || !dirty" @click="savePlan">{{ $t('保存计划') }}</button>
        <button class="btn primary" :disabled="busy || dirty || !q.plan || q.plan.status === 'approved' || q.errors.length" @click="approve">{{ $t('批准') }}</button>
      </div>
      <p v-if="note" class="notebox small">{{ $td(note) }}</p>
      <div class="tablewrap">
        <table class="t chars">
          <thead><tr><th>{{ $t('编号') }}</th><th>{{ $t('名称') }}</th><th>{{ $t('件') }}</th><th>{{ $t('检验') }}</th><th class="num">{{ $t('名义') }}</th>
            <th class="num">{{ $t('下限') }}</th><th class="num">{{ $t('上限') }}</th><th>{{ $t('单位') }}</th><th>{{ $t('方法') }}</th><th></th></tr></thead>
          <tbody><tr v-for="(c, i) in chars" :key="i">
            <td><input v-model="c.code" class="mono code" @input="dirty = true"></td>
            <td><input v-model="c.name" @input="dirty = true"><small v-if="c.source === 'ai'" class="tag">{{ $t('AI 读出，要核对') }}</small></td>
            <td><select v-model="c.item" @change="dirty = true"><option v-for="it in q.items" :key="it" :value="it">{{ it }}</option></select></td>
            <td><select v-model="c.kind" @change="dirty = true"><option v-for="k in KINDS" :key="k" :value="k">{{ $t(KIND_ZH[k]) }}</option></select></td>
            <td class="num"><input v-model.number="c.nominal" type="number" step="any" @input="dirty = true"></td>
            <td class="num"><input v-model.number="c.lo" type="number" step="any" @input="dirty = true"></td>
            <td class="num"><input v-model.number="c.hi" type="number" step="any" @input="dirty = true"></td>
            <td><input v-model="c.unit" class="short" @input="dirty = true"></td>
            <td><input v-model="c.method" @input="dirty = true"></td>
            <td><button class="x" :aria-label="$t('删去这一行')" @click="chars.splice(i, 1); dirty = true">×</button></td>
          </tr></tbody>
        </table>
      </div>
      <div v-for="e in q.errors" :key="e" class="err small">✗ {{ $td(e) }}</div>

      <template v-if="q.approved && q.work_orders.length">
        <h3>{{ $t('首件与终检') }}</h3>
        <div class="insp">
          <label class="fld"><span>{{ $t('检验') }}</span><select v-model="f.kind"><option value="fai">{{ $t('首件') }}</option><option value="final">{{ $t('终检') }}</option></select></label>
          <label class="fld"><span>{{ $t('工单') }}</span><select v-model="f.work_order">
            <option v-for="w in formWos" :key="w.name" :value="w.name">{{ w.name }} · {{ w.item }}</option></select></label>
          <label class="fld"><span>{{ $t('件号') }}</span><input v-model.number="f.piece" type="number" min="1" :disabled="f.kind === 'fai'"></label>
        </div>
        <div v-for="c in formChars" :key="c.code" class="reading">
          <span>{{ c.name }} <span class="muted small">{{ c.lo }} ~ {{ c.hi }} {{ c.unit }}</span></span>
          <input v-model.number="f.readings[c.code]" type="number" step="any">
        </div>
        <button class="btn" :disabled="busy || !formChars.length" @click="inspect">{{ $t('保存检验记录') }}</button>
        <p class="small muted">{{ $t('保存后不能改；记错了只能作废并写原因，再记一条。不合格自动开不合格品单。') }}</p>
        <table v-if="q.records.length" class="t">
          <thead><tr><th>#</th><th>{{ $t('检验') }}</th><th>{{ $t('工单') }}</th><th class="num">{{ $t('件号') }}</th><th>{{ $t('结果') }}</th>
            <th>{{ $t('检验员') }}</th><th>{{ $t('不合格品单') }}</th><th></th></tr></thead>
          <tbody><tr v-for="r in q.records" :key="r.id" :class="{ voided: r.voided_at, late: r.result === 'fail' && !r.voided_at }">
            <td>{{ r.id }}</td><td>{{ $t(KIND_ZH[r.kind]) }}</td><td class="mono">{{ r.work_order }}</td><td class="num">{{ r.piece }}</td>
            <td>{{ $t(RES[r.result]) }}<span v-if="r.voided_at" class="small muted"> · {{ $t('已作废：{a}', { a: r.void_reason }) }}</span></td>
            <td>{{ r.inspector }}</td><td class="mono">{{ r.ncr_id || '' }}<span v-if="r.ncr_status" class="small muted"> {{ $t(NCR[r.ncr_status] || r.ncr_status) }}</span></td>
            <td><button v-if="!r.voided_at" class="btn ghost tiny" @click="voidRec(r)">{{ $t('作废') }}</button></td></tr></tbody>
        </table>
      </template>

      <h3>{{ $t('发货') }}</h3>
      <p v-if="q.delivery_note" class="ok small">{{ $t('已发货：ERPNext 发货单 {d}', { d: q.delivery_note }) }}</p>
      <template v-else>
        <div v-for="b in q.ship_block" :key="b" class="warnline small">{{ $t('还不能发：{a}', { a: $td(b) }) }}</div>
        <button class="btn primary" :disabled="busy || q.ship_block.length" @click="ship">{{ $t('生成发货提议') }}</button>
      </template>
      <button class="btn ghost" :disabled="!q.records.some((r) => r.kind === 'final' && !r.voided_at)" @click="showCert">{{ $t('合格证') }}</button>
      <div v-if="msg" :class="msgOk ? 'ok' : 'err'" class="small">{{ msg }}</div>
    </template>

    <div v-if="cert" class="modal-mask" @click.self="cert = null">
      <div class="modal" role="dialog" aria-modal="true" :aria-label="$t('合格证')">
        <h2>{{ $t('产品合格证') }}</h2>
        <table class="t"><tbody>
          <tr><td>{{ $t('作业号') }}</td><td class="mono">{{ cert.job_no }}</td><td>{{ $t('客户') }}</td><td>{{ $td(cert.customer) }}</td></tr>
          <tr><td>{{ $t('名称') }}</td><td>{{ cert.title }}</td><td>{{ $t('销售订单') }}</td><td class="mono">{{ cert.sales_order }}</td></tr>
          <tr><td>{{ $t('设计版本') }}</td><td>{{ $t('第 {r} 版', { r: cert.design_rev }) }} · <span class="mono">{{ (cert.fingerprint || '').slice(0, 12) }}</span></td>
            <td>{{ $t('检验计划') }}</td><td>{{ $t('第 {r} 版（{w} 批准）', { r: cert.plan_rev, w: cert.plan_approved_by }) }}</td></tr>
        </tbody></table>
        <div v-for="p in cert.pieces" :key="p.work_order + p.piece" class="piece">
          <b>{{ $t('第 {n} 件', { n: p.piece }) }}</b> <span class="muted small">{{ p.work_order }} · {{ p.inspector }}</span>
          <span v-if="p.concession" class="pill warn">{{ $t('让步接收（{n}）', { n: p.ncr_id }) }}</span>
          <div class="small">{{ p.readings.map((r) => r.name + ' ' + r.value + ' ' + r.unit).join('; ') }}</div>
        </div>
        <p class="small muted">{{ $t('终检合格 {a} / {b} 件；签发时间 {t}', { a: cert.pieces.length, b: cert.qty, t: cert.issued_at }) }}</p>
        <div class="actions"><button class="btn ghost" @click="print">{{ $t('打印') }}</button><button class="btn" @click="cert = null">{{ $t('关闭') }}</button></div>
      </div>
    </div>
    <ProposalModal v-if="pid" :pid="pid" @close="pid = null; load()" @done="load(); $emit('changed')" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { api, get, post, session } from '../lib/api';
import { t as $t, td as $td, tk } from '../lib/i18n';
import ProposalModal from './ProposalModal.vue';

const props = defineProps({ job: Object });
defineEmits(['changed']);
const KINDS = ['fai', 'final', 'both'];
const KIND_ZH = { fai: tk('首件'), final: tk('终检'), both: tk('首件和终检') };
const RES = { pass: tk('合格'), fail: tk('不合格'), unknown: tk('未知') };
const PST = { approved: tk('已批准'), draft: tk('草稿') };
const NCR = { open: tk('待处置'), rework: tk('返修'), scrap: tk('报废'), use_as_is: tk('让步接收') };
const q = ref(null);
const err = ref('');
const chars = ref([]);
const note = ref('');
const dirty = ref(false);
const busy = ref(false);
const pid = ref(null);
const cert = ref(null);
const msg = ref('');
const msgOk = ref(true);
const f = ref({ kind: 'fai', work_order: '', piece: 1, readings: {} });
const jp = () => encodeURIComponent(props.job.job_no);
const kb = (n) => (n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.ceil(n / 1024) + ' KB');
const formWos = computed(() => (q.value?.work_orders || []).filter((w) => (f.value.kind === 'final' ? w.item === props.job.job_no : w.own)));
const formChars = computed(() => {
  const w = (q.value?.work_orders || []).find((x) => x.name === f.value.work_order);
  return w ? (q.value.approved?.chars || []).filter((c) => c.item === w.item && [f.value.kind, 'both'].includes(c.kind)) : [];
});
function say(t, ok = true) { msg.value = t; msgOk.value = ok; }
function addChar() { chars.value.push({ code: '', name: '', item: props.job.job_no, kind: 'final', unit: 'mm' }); dirty.value = true; }

async function load() {
  err.value = '';
  try {
    q.value = await get(`/eto/jobs/${jp()}/quality`);
    chars.value = JSON.parse(JSON.stringify(q.value.plan?.chars || []));
    dirty.value = false;
    if (!formWos.value.some((w) => w.name === f.value.work_order)) f.value.work_order = formWos.value[0]?.name || '';
  } catch (e) { q.value = null; err.value = e.message; }
}
async function upload(ev) {
  const file = ev.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  busy.value = true;
  try {
    const r = await fetch(`/api/eto/jobs/${jp()}/files`, { method: 'POST', body: fd, headers: session.token ? { 'x-wq-token': session.token } : {} });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || r.status);
    say($t('已上传 {n}（读出 {c} 个字）', { n: d.name, c: d.text_chars }));
    await load();
  } catch (e) { say(e.message, false); } finally { busy.value = false; ev.target.value = ''; }
}
async function draft() {
  if (chars.value.length && !window.confirm($t('起草的结果会替换现在的检验项（保存后才生效），继续吗？'))) return;
  busy.value = true;
  try { const d = await post(`/eto/jobs/${jp()}/quality/plan/draft`); chars.value = d.chars; note.value = d.note; dirty.value = true; } catch (e) { say(e.message, false); } finally { busy.value = false; }
}
async function savePlan() {
  busy.value = true;
  try { q.value = await api('PUT', `/eto/jobs/${jp()}/quality/plan`, { chars: chars.value }); chars.value = JSON.parse(JSON.stringify(q.value.plan.chars)); dirty.value = false; say($t('已保存。')); } catch (e) { say(e.message, false); } finally { busy.value = false; }
}
async function approve() {
  busy.value = true;
  try { q.value = await post(`/eto/jobs/${jp()}/quality/plan/approve`); say($t('已批准。')); } catch (e) { say(e.message, false); } finally { busy.value = false; }
}
async function inspect() {
  busy.value = true;
  try {
    const r = await post(`/eto/jobs/${jp()}/quality/inspect`, { ...f.value, piece: f.value.kind === 'fai' ? 1 : f.value.piece });
    say($t('已记：{r}{n}', { r: $t(RES[r.result]), n: r.ncr_id ? $t('，开了不合格品单 {n}', { n: r.ncr_id }) : '' }), r.result === 'pass');
    f.value.readings = {};
    await load();
  } catch (e) { say(e.message, false); } finally { busy.value = false; }
}
async function voidRec(r) {
  const reason = window.prompt($t('作废原因：'), '');
  if (!reason) return;
  try { await post(`/eto/jobs/${jp()}/quality/inspect/${r.id}/void`, { reason }); await load(); } catch (e) { say(e.message, false); }
}
async function ship() {
  busy.value = true;
  try { pid.value = (await post(`/eto/jobs/${jp()}/ship`)).proposal_id; } catch (e) { say(e.message, false); } finally { busy.value = false; }
}
async function showCert() { try { cert.value = await get(`/eto/jobs/${jp()}/certificate`); } catch (e) { say(e.message, false); } }
function print() { window.print(); }
watch(() => f.value.kind, () => { f.value.work_order = formWos.value[0]?.name || ''; f.value.readings = {}; });
watch(() => props.job.job_no, load);
onMounted(load);
</script>

<style scoped>
h3 { font-size: 14px; margin: 16px 0 6px; display: flex; gap: 8px; align-items: center; }
.files { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.file { border: 1px solid var(--line); border-radius: 6px; padding: 4px 8px; font-size: 13px; }
.up { position: relative; overflow: hidden; display: inline-flex; align-items: center; }
.up input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.tools { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; }
.tools > span { margin-right: auto; }
.tablewrap { overflow-x: auto; }
.chars td { padding: 3px 4px; }
.chars input, .chars select, .insp input, .insp select, .reading input { border: 1px solid var(--line); border-radius: 5px; padding: 3px 5px; font: inherit; font-size: 13px; }
.chars td.num input { width: 80px; text-align: right; }
.chars input.code { width: 90px; } .chars input.short { width: 50px; }
.tag { font-size: 10px; color: var(--warn-ink); margin-left: 4px; }
.insp { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
.fld { display: flex; flex-direction: column; gap: 3px; font-size: 13px; }
.reading { display: flex; gap: 10px; align-items: center; justify-content: space-between; max-width: 520px; font-size: 13px; margin: 3px 0; }
.reading input { width: 110px; text-align: right; }
.t td { padding: 4px 6px; }
tr.voided td { color: var(--muted, #999); text-decoration: line-through; }
tr.late td { background: #FDECEC; }
.btn.tiny { height: 24px; font-size: 12px; padding: 0 8px; }
.x { border: none; background: none; font-size: 16px; cursor: pointer; color: var(--muted, #888); }
.notebox { background: var(--accent-bg); border-radius: 8px; padding: 8px 10px; }
.piece { border-top: 1px solid var(--line); padding: 6px 0; }
.actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; }
.err { color: var(--bad); } .ok { color: var(--good); } .warnline { color: var(--warn-ink); }
</style>
