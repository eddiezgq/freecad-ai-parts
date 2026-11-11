<template>
  <div v-if="p && p.rows.length" class="chg">
    <h3>{{ $t('处理设计变更（第 {a} 版 → 第 {b} 版）', { a: p.from_rev, b: p.rev }) }}</h3>
    <p class="small muted">{{ $t('改了的件：{c}。下面是挂在作业上、还没完的单据和建议；逐条选好后提交，人确认后在 ERPNext 执行。没处理完不能再算料、再发布。', { c: p.changed_items.join(', ') || '—' }) }}</p>
    <table class="t">
      <thead><tr><th>{{ $t('单据') }}</th><th>{{ $t('物料') }}</th><th>{{ $t('建议与原因') }}</th><th>{{ $t('处理') }}</th><th class="num nw">{{ $t('变更损失') }}</th></tr></thead>
      <tbody>
        <tr v-for="r in p.rows" :key="r.doctype + r.name" :class="{ dim: !r.needs }">
          <td><span class="muted small">{{ $t(DT[r.doctype] || r.doctype) }}</span><br><span class="mono nw">{{ r.name }}</span></td>
          <td class="mono small">{{ r.item }}
            <div v-for="l in r.lines || []" :key="l.item_code" class="small muted">{{ $t('{c}：{q} → {n}（已到 {r}）', { c: l.item_code, q: l.qty, n: l.new_qty, r: l.received }) }}</div></td>
          <td class="small">{{ $td(r.reason) }}</td>
          <td>
            <span v-if="r.decided" class="pill good">{{ $t('已处理：{a}', { a: $t(ZH[r.decided.action]) }) }}</span>
            <span v-else-if="!r.needs" class="muted small">{{ $t('不受影响') }}</span>
            <select v-else v-model="pick[r.doctype + '/' + r.name]" :aria-label="$t('处理方式')">
              <option v-for="o in r.options" :key="o" :value="o">{{ $t(ZH[o]) }}{{ o === r.suggest ? $t('（建议）') : '' }}</option>
            </select>
          </td>
          <td class="num mono">{{ lossOf(r) }}</td>
        </tr>
      </tbody>
    </table>
    <div class="tools">
      <span class="small muted">{{ p.open ? $t('还有 {n} 条没处理', { n: p.open }) : $t('这次变更都处理完了，可以再算料') }}</span>
      <button v-if="p.open" class="btn primary" :disabled="busy || !!p.pending_proposal" @click="submit">{{ p.pending_proposal ? $t('提议在等确认') : $t('提交处理') }}</button>
    </div>
    <div v-if="msg" class="err small">{{ msg }}</div>
    <ProposalModal v-if="pid" :pid="pid" @close="pid = null; load()" @done="load(); $emit('changed')" />
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue';
import { get, post } from '../lib/api';
import { t as $t, td as $td, tk } from '../lib/i18n';
import ProposalModal from './ProposalModal.vue';

const props = defineProps({ job: Object });
defineEmits(['changed']);
const ZH = { keep: tk('照用'), renew: tk('换新版'), cancel: tk('取消'), stop: tk('停止'), qty: tk('改量'), close: tk('关闭') };
const DT = { 'Work Order': tk('工单'), 'Material Request': tk('请购单'), 'Purchase Order': tk('采购单') };
const p = ref(null);
const pick = ref({});
const busy = ref(false);
const pid = ref(null);
const msg = ref('');

function lossOf(r) {
  const a = r.decided ? r.decided.action : (pick.value[r.doctype + '/' + r.name] || r.suggest);
  const v = r.decided ? r.decided.loss : r.loss?.[a];
  if (v === null || v === undefined) return a === 'keep' ? '' : $t('未知');
  return v ? '$' + Number(v).toFixed(2) : '';
}
async function load() {
  try {
    p.value = await get(`/eto/jobs/${encodeURIComponent(props.job.job_no)}/change`);
    const m = {};
    for (const r of p.value.rows) if (r.needs && !r.decided) m[r.doctype + '/' + r.name] = r.suggest;
    pick.value = m;
  } catch (e) { msg.value = e.message; }
}
async function submit() {
  busy.value = true;
  msg.value = '';
  try { pid.value = (await post(`/eto/jobs/${encodeURIComponent(props.job.job_no)}/change`, { choices: pick.value })).proposal_id; }
  catch (e) { msg.value = e.message; } finally { busy.value = false; }
}
watch(() => props.job.job_no, load);
onMounted(load);
defineExpose({ load });
</script>

<style scoped>
.chg { border: 1px solid var(--warn-ink); border-radius: 8px; padding: 8px 12px; margin: 12px 0; }
h3 { font-size: 14px; margin: 2px 0 6px; }
.tools { display: flex; gap: 8px; align-items: center; justify-content: flex-end; margin-top: 8px; }
.tools > span { margin-right: auto; }
.dim { opacity: .6; }
.nw { white-space: nowrap; }
select { border: 1px solid var(--line); border-radius: 5px; padding: 3px 5px; font: inherit; font-size: 13px; }
.err { color: var(--bad); }
</style>
