<template>
  <div class="mat">
    <template v-if="plan">
      <div class="tools">
        <span class="muted small">{{ $t('按设计第 {r} 版算料', { r: plan.job.design_rev }) }}</span>
        <button class="btn ghost" :disabled="busy" @click="load">{{ $t('重新算') }}</button>
        <button class="btn primary" :disabled="busy || (!plan.work_orders.length && !plan.material_requests.length)" @click="propose">{{ $t('生成算料提议') }}</button>
      </div>
      <p class="small muted">{{ $td(plan.basis) }}</p>
      <div class="tablewrap">
        <table class="t">
          <thead><tr><th>{{ $t('层') }}</th><th>{{ $t('物料') }}</th><th>{{ $t('名称') }}</th><th class="num">{{ $t('毛需求') }}</th>
            <th class="num">{{ $t('自由库存') }}</th><th class="num">{{ $t('本作业已有') }}</th><th class="num">{{ $t('净需求') }}</th><th>{{ $t('动作') }}</th></tr></thead>
          <tbody><tr v-for="r in plan.mrp" :key="r.item_code" :class="{ need: r.net > 0 }">
            <td class="num">{{ r.level }}</td><td class="mono">{{ r.item_code }}<span v-if="r.own" class="tag">{{ $t('专用') }}</span></td>
            <td>{{ $td(r.name) }}</td><td class="num">{{ n(r.gross) }}</td><td class="num">{{ r.own ? '—' : n(r.free_stock) }}</td>
            <td class="num">{{ n(r.pegged) }}</td><td class="num">{{ n(r.net) }}</td><td>{{ $td(r.action) }}</td></tr></tbody>
        </table>
      </div>
      <div v-if="plan.warnings.length" class="warnbox small"><div v-for="w in plan.warnings" :key="w">{{ $td(w) }}</div></div>
    </template>
    <div v-else-if="err" class="small">
      <p class="muted">{{ err }}</p>
    </div>

    <template v-if="early.design_status !== 'released'">
    <h3>{{ $t('长周期件提前采购') }}</h3>
    <p class="small muted">{{ $t('设计发布前，提前期 ≥ {d} 天的外购件、原材料可以先请购（挂作业号，单独确认）。', { d: early.threshold || 15 }) }}</p>
    <div v-if="!early.items?.length" class="small muted">{{ $t('当前设计里没有长周期件。') }}</div>
    <label v-for="it in early.items" :key="it.item_code" class="pick">
      <input v-model="picked" type="checkbox" :value="it.item_code">
      <span class="mono">{{ it.item_code }}</span> {{ $td(it.name) }} <span class="muted">{{ $t('提前期 {d} 天', { d: it.lead }) }}</span>
    </label>
    <button v-if="early.items?.length" class="btn ghost" :disabled="!picked.length || busy" @click="earlyBuy">{{ $t('生成提前采购提议') }}</button>
    </template>
    <div v-if="msg" :class="msgOk ? 'ok' : 'err'" class="small">{{ msg }}</div>
    <ProposalModal v-if="pid" :pid="pid" @close="pid = null; load()" @done="load(); $emit('changed')" />
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue';
import { get, post } from '../lib/api';
import { t as $t, td as $td } from '../lib/i18n';
import ProposalModal from './ProposalModal.vue';

const props = defineProps({ job: Object });
defineEmits(['changed']);
const plan = ref(null);
const err = ref('');
const early = ref({ items: [] });
const picked = ref([]);
const busy = ref(false);
const pid = ref(null);
const msg = ref('');
const msgOk = ref(true);
const n = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 }));
const jp = () => encodeURIComponent(props.job.job_no);

async function load() {
  busy.value = true; err.value = '';
  try { plan.value = await get(`/eto/jobs/${jp()}/materials`); } catch (e) { plan.value = null; err.value = e.message; }
  try { early.value = await get(`/eto/jobs/${jp()}/early-buy`); } catch (e) { early.value = { items: [] }; }
  busy.value = false;
}
async function propose() {
  busy.value = true; msg.value = '';
  try { pid.value = (await post(`/eto/jobs/${jp()}/materials`)).proposal_id; } catch (e) { msg.value = e.message; msgOk.value = false; } finally { busy.value = false; }
}
async function earlyBuy() {
  busy.value = true; msg.value = '';
  try { pid.value = (await post(`/eto/jobs/${jp()}/early-buy`, { items: picked.value })).proposal_id; picked.value = []; } catch (e) { msg.value = e.message; msgOk.value = false; } finally { busy.value = false; }
}
watch(() => props.job.job_no, load);
onMounted(load);
</script>

<style scoped>
.tools { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; }
.tools > span { margin-right: auto; }
.tablewrap { overflow-x: auto; }
.t td { padding: 4px 6px; }
tr.need td { background: #FFF8EC; }
.tag { font-size: 10px; color: var(--accent); margin-left: 4px; }
h3 { font-size: 14px; margin: 16px 0 6px; }
.pick { display: flex; gap: 8px; align-items: center; font-size: 13px; margin: 3px 0; }
.warnbox { background: var(--warn-bg); color: var(--warn-ink); border-radius: 8px; padding: 8px 10px; margin-top: 8px; }
.err { color: var(--bad); } .ok { color: var(--good); }
</style>
