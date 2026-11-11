<template>
  <div class="shop">
    <p v-if="err" class="muted">{{ err }}</p>
    <template v-else-if="s">
      <h3>{{ $t('工单') }}</h3>
      <p v-if="!s.work_orders.length" class="small muted">{{ $t('还没有工单：先在“物料”页签生成算料提议。') }}</p>
      <table v-else class="t">
        <thead><tr><th>{{ $t('工单') }}</th><th>{{ $t('物料') }}</th><th class="num">{{ $t('完工 / 数量') }}</th><th>{{ $t('状态') }}</th>
          <th>{{ $t('设计版本') }}</th><th></th></tr></thead>
        <tbody><tr v-for="w in s.work_orders" :key="w.name" :class="{ late: w.current_design === false }">
          <td class="mono">{{ w.name }}</td><td class="mono">{{ w.item }}</td><td class="num">{{ w.produced }} / {{ w.qty }}</td>
          <td>{{ $td(w.status) }}<span v-if="w.started" class="muted small"> · {{ $t('已开工') }}</span></td>
          <td>{{ w.current_design === false ? $t('旧版，不能下达') : (w.current_design ? $t('当前版') : '—') }}</td>
          <td class="acts">
            <button class="btn ghost tiny" @click="showTraveler(w.name)">{{ $t('作业单') }}</button>
            <button v-if="!w.started && w.current_design !== false && w.status !== 'Completed'" class="btn tiny" :disabled="busy" @click="release(w.name)">{{ $t('下达车间') }}</button>
          </td></tr></tbody>
      </table>

      <h3>{{ $t('作业成本：估算对实际') }}</h3>
      <table class="t cost">
        <thead><tr><th></th><th class="num">{{ $t('估算（第 {r} 版）', { r: s.cost.estimate?.rev ?? '—' }) }}</th><th class="num">{{ $t('实际（到现在）') }}</th></tr></thead>
        <tbody>
          <tr v-for="k in CATS" :key="k[0]"><td>{{ $t(k[1]) }}</td><td class="num mono">{{ money(s.cost.estimate?.[k[0]]) }}</td>
            <td class="num mono">{{ s.cost.actual[k[0]] === null ? $t('未知') : money(s.cost.actual[k[0]]) }}</td></tr>
          <tr class="sum"><td>{{ $t('合计（不含风险预留）') }}</td>
            <td class="num mono">{{ money(sumEst) }}</td><td class="num mono">{{ s.cost.actual.total === null ? $t('未知') : money(s.cost.actual.total) }}</td></tr>
        </tbody>
      </table>
      <p class="small muted">{{ $t('工序的标准成本（按标准工时）：{a}', { a: money(s.cost.operations_std) }) }}</p>
      <div v-for="u in s.cost.unknown" :key="u" class="warnline small">{{ $t('未知：{a}', { a: $td(u) }) }}</div>
      <p class="small muted">{{ $td(s.cost.basis) }}</p>

      <h3>{{ $t('设计工时') }}</h3>
      <div class="hrs">
        <input v-model.number="h" type="number" min="0.25" step="0.25" :placeholder="$t('小时')">
        <input v-model="note" :placeholder="$t('做了什么')">
        <button class="btn ghost" :disabled="!h || busy" @click="addHours">{{ $t('登记（进 ERPNext 工时表）') }}</button>
      </div>
      <div v-for="x in s.hours" :key="x.id" class="small">{{ x.day }} · {{ x.who }} · {{ $t('{n} 小时', { n: x.hours }) }} · {{ x.note }}</div>
      <div v-if="msg" :class="msgOk ? 'ok' : 'err'" class="small">{{ msg }}</div>
    </template>

    <div v-if="tr" class="modal-mask" @click.self="tr = null">
      <div class="modal traveler" role="dialog" aria-modal="true" :aria-label="$t('作业单')">
        <h2>{{ $t('作业单') }} <span class="mono">{{ tr.work_order }}</span></h2>
        <table class="t"><tbody>
          <tr><td>{{ $t('作业号') }}</td><td class="mono">{{ tr.job_no }}</td><td>{{ $t('客户') }}</td><td>{{ $td(tr.customer) }}</td></tr>
          <tr><td>{{ $t('物料') }}</td><td><span class="mono">{{ tr.item }}</span> {{ $td(tr.item_name) }}</td><td>{{ $t('数量') }}</td><td>{{ tr.qty }}</td></tr>
          <tr><td>{{ $t('设计版本') }}</td><td>{{ $t('第 {r} 版', { r: tr.design_rev }) }} · <span class="mono">{{ (tr.fingerprint || '').slice(0, 12) }}</span></td>
            <td>{{ $t('交期') }}</td><td class="mono">{{ tr.due_date }}</td></tr>
        </tbody></table>
        <h3>{{ $t('工序') }}</h3>
        <table class="t">
          <thead><tr><th>#</th><th>{{ $t('工序') }}</th><th>{{ $t('工作站') }}</th><th class="num">{{ $t('每件分钟') }}</th><th class="num">{{ $t('合计分钟') }}</th><th></th></tr></thead>
          <tbody><tr v-for="o in tr.operations" :key="o.seq"><td>{{ o.seq }}</td><td>{{ $td(o.operation) }}</td><td>{{ $td(o.workstation) }}</td>
            <td class="num">{{ o.std_min }}</td><td class="num">{{ o.total_min }}</td><td>{{ o.inspection ? $t('检验点') : '' }}</td></tr></tbody>
        </table>
        <h3>{{ $t('子件') }}</h3>
        <table class="t">
          <thead><tr><th>{{ $t('物料') }}</th><th>{{ $t('名称') }}</th><th class="num">{{ $t('每件') }}</th><th class="num">{{ $t('合计') }}</th></tr></thead>
          <tbody><tr v-for="c in tr.components" :key="c.item_code"><td class="mono">{{ c.item_code }}</td><td>{{ $td(c.name) }}</td>
            <td class="num">{{ c.per }}</td><td class="num">{{ c.qty }} {{ c.uom }}</td></tr></tbody>
        </table>
        <div class="actions"><button class="btn ghost" @click="print">{{ $t('打印') }}</button><button class="btn" @click="tr = null">{{ $t('关闭') }}</button></div>
      </div>
    </div>
    <ProposalModal v-if="pid" :pid="pid" @close="pid = null; load()" @done="load" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { get, post } from '../lib/api';
import { t as $t, td as $td, tk } from '../lib/i18n';
import ProposalModal from './ProposalModal.vue';

const props = defineProps({ job: Object });
const CATS = [['material', tk('材料')], ['operations', tk('工序')], ['outside', tk('外协')], ['engineering', tk('设计')]];
const s = ref(null);
const err = ref('');
const tr = ref(null);
const pid = ref(null);
const busy = ref(false);
const h = ref(null);
const note = ref('');
const msg = ref('');
const msgOk = ref(true);
const jp = () => encodeURIComponent(props.job.job_no);
const money = (x) => (x === null || x === undefined ? '—' : '$' + Number(x).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const sumEst = computed(() => {
  const e = s.value?.cost?.estimate;
  if (!e) return null;
  const v = CATS.map((k) => e[k[0]]);
  return v.some((x) => x === null || x === undefined) ? null : v.reduce((a, b) => a + b, 0);
});

async function load() {
  err.value = '';
  try { s.value = await get(`/eto/jobs/${jp()}/shop`); } catch (e) { s.value = null; err.value = e.message; }
}
async function showTraveler(wo) {
  try { tr.value = await get(`/eto/jobs/${jp()}/traveler/${encodeURIComponent(wo)}`); } catch (e) { msg.value = e.message; msgOk.value = false; }
}
async function release(wo) {
  busy.value = true; msg.value = '';
  try { pid.value = (await post(`/eto/jobs/${jp()}/release`, { work_order: wo })).proposal_id; } catch (e) { msg.value = e.message; msgOk.value = false; } finally { busy.value = false; }
}
async function addHours() {
  busy.value = true; msg.value = '';
  try {
    await post(`/eto/jobs/${jp()}/hours`, { hours: h.value, note: note.value });
    msg.value = $t('已登记，ERPNext 工时表写好后计入成本。'); msgOk.value = true; h.value = null; note.value = '';
    setTimeout(load, 2500);
  } catch (e) { msg.value = e.message; msgOk.value = false; } finally { busy.value = false; }
}
function print() { window.print(); }
watch(() => props.job.job_no, load);
onMounted(load);
</script>

<style scoped>
h3 { font-size: 14px; margin: 14px 0 6px; }
.t td { padding: 4px 6px; }
tr.late td { background: #FDECEC; }
tr.sum td { font-weight: 600; }
.acts { display: flex; gap: 6px; }
.btn.tiny { height: 24px; font-size: 12px; padding: 0 8px; }
.hrs { display: flex; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }
.hrs input { border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; font: inherit; }
.hrs input[type=number] { width: 90px; }
.traveler { max-width: 860px; }
.actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; }
.err { color: var(--bad); } .ok { color: var(--good); } .warnline { color: var(--warn-ink); }
</style>
