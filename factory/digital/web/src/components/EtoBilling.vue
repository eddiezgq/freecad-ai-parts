<template>
  <div class="bill">
    <p v-if="err" class="muted">{{ err }}</p>
    <template v-else-if="b">
      <h3>{{ $t('分期开票') }}</h3>
      <p v-if="!b.milestones.length" class="small muted">{{ $t('还没有付款计划：接单后按里程碑分期。') }}</p>
      <table v-else class="t">
        <thead><tr><th>{{ $t('期次') }}</th><th class="num">{{ $t('比例') }}</th><th class="num">{{ $t('金额') }}</th><th>{{ $t('里程碑') }}</th>
          <th>{{ $t('计划日期') }}</th><th>{{ $t('状态') }}</th><th></th></tr></thead>
        <tbody><tr v-for="m in b.milestones" :key="m.key" :class="{ wait: m.state === 'waiting' }">
          <td>{{ $td(m.description) }}</td><td class="num">{{ m.invoice_portion }}%</td><td class="num mono">{{ money(m.payment_amount) }}</td>
          <td>{{ $t(ON[m.on] || m.on) }}<span v-if="m.reached" class="ok small"> · {{ $t('已到') }}</span></td>
          <td class="mono">{{ m.due_date }}</td>
          <td>{{ $t(STATE[m.state]) }}<span v-if="m.invoice" class="mono small"> {{ m.invoice }}</span></td>
          <td><button v-if="m.state === 'due'" class="btn tiny" :disabled="busy" @click="invoice(m.key)">{{ $t('起草发票') }}</button></td>
        </tr></tbody>
      </table>
      <p class="small muted">{{ $t('里程碑到了才能开那一期；每期只开一次。发票由人确认后写进 ERPNext。作业的订单不走“做完整单开票”。') }}</p>

      <h3>{{ $t('客户验收') }}</h3>
      <p v-if="b.accepted" class="small">{{ $t('{d} 验收，登记人 {w}', { d: b.accepted.day, w: b.accepted.who }) }}<span v-if="b.accepted.note"> · {{ b.accepted.note }}</span></p>
      <p v-else-if="!b.delivery_note" class="small muted">{{ $t('发货后才能登记验收。') }}</p>
      <div v-else class="acc">
        <input v-model="day" type="date" :aria-label="$t('验收日期')">
        <input v-model="note" :placeholder="$t('验收说明（可空）')">
        <button class="btn ghost" :disabled="busy" @click="accept">{{ $t('登记验收') }}</button>
      </div>

      <h3>{{ $t('收付与毛利') }}</h3>
      <table class="t money">
        <tbody>
          <tr><td>{{ $t('订单金额') }}</td><td class="num mono">{{ money(b.money.order_amount) }}</td></tr>
          <tr><td>{{ $t('已开票') }}</td><td class="num mono">{{ money(b.money.invoiced) }}</td></tr>
          <tr><td>{{ $t('已收款') }}</td><td class="num mono">{{ money(b.money.received) }}</td></tr>
          <tr><td>{{ $t('应收未收') }}</td><td class="num mono">{{ money(b.money.receivable) }}</td></tr>
          <tr><td>{{ $t('还没开票') }}</td><td class="num mono">{{ money(b.money.not_invoiced) }}</td></tr>
          <tr><td>{{ $t('实际成本（到现在）') }}</td><td class="num mono">{{ b.money.actual_cost === null ? $t('未知') : money(b.money.actual_cost) }}</td></tr>
          <tr class="sum"><td>{{ $t('毛利') }}</td>
            <td class="num mono">{{ b.money.margin === null ? $t('未知') : $t('{a}（{p}%）', { a: money(b.money.margin), p: b.money.margin_pct }) }}</td></tr>
        </tbody>
      </table>
      <p class="small muted">{{ $t('毛利 = 订单金额 − 实际成本；实际成本里哪一项未知（见“车间与成本”），毛利就是未知。') }}</p>
      <div v-if="msg" :class="msgOk ? 'ok' : 'err'" class="small">{{ msg }}</div>
    </template>
    <ProposalModal v-if="pid" :pid="pid" @close="pid = null; load()" @done="load" />
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue';
import { get, post } from '../lib/api';
import { t as $t, td as $td, tk } from '../lib/i18n';
import ProposalModal from './ProposalModal.vue';

const props = defineProps({ job: Object });
const ON = { order: tk('订单确认'), design: tk('设计发布'), ship: tk('发货'), accept: tk('客户验收') };
const STATE = { waiting: tk('里程碑没到'), due: tk('可以开票'), drafted: tk('发票在等确认'), invoiced: tk('已开票') };
const b = ref(null);
const err = ref('');
const pid = ref(null);
const busy = ref(false);
const day = ref(new Date().toISOString().slice(0, 10));
const note = ref('');
const msg = ref('');
const msgOk = ref(true);
const jp = () => encodeURIComponent(props.job.job_no);
const money = (x) => (x === null || x === undefined ? '—' : '$' + Number(x).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

async function load() {
  err.value = '';
  try { b.value = await get(`/eto/jobs/${jp()}/billing`); } catch (e) { b.value = null; err.value = e.message; }
}
async function invoice(key) {
  busy.value = true; msg.value = '';
  try { pid.value = (await post(`/eto/jobs/${jp()}/invoice`, { key })).proposal_id; } catch (e) { msg.value = e.message; msgOk.value = false; } finally { busy.value = false; }
}
async function accept() {
  busy.value = true; msg.value = '';
  try { b.value = await post(`/eto/jobs/${jp()}/accept`, { day: day.value, note: note.value }); msg.value = $t('已登记验收。'); msgOk.value = true; } catch (e) { msg.value = e.message; msgOk.value = false; } finally { busy.value = false; }
}
watch(() => props.job.job_no, load);
onMounted(load);
</script>

<style scoped>
h3 { font-size: 14px; margin: 14px 0 6px; }
.t td { padding: 4px 6px; }
tr.wait td { color: var(--muted); }
tr.sum td { font-weight: 600; }
.money { max-width: 420px; }
.btn.tiny { height: 24px; font-size: 12px; padding: 0 8px; }
.acc { display: flex; gap: 8px; flex-wrap: wrap; }
.acc input { border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; font: inherit; }
.err { color: var(--bad); } .ok { color: var(--good); }
</style>
