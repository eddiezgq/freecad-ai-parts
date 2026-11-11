<template>
  <div class="plan">
    <p v-if="err" class="muted">{{ err }}</p>
    <template v-else-if="s">
      <div class="head" :class="s.slack_days >= 0 ? 'okbox' : 'badbox'">
        <div><span class="muted small">{{ $t('交期') }}</span><b class="mono">{{ s.due }}</b></div>
        <div><span class="muted small">{{ $t('最早能交') }}</span><b class="mono">{{ s.earliest }}</b></div>
        <div><span class="muted small">{{ $t('松紧') }}</span><b>{{ s.slack_days >= 0 ? $t('富余 {n} 个工作日', { n: s.slack_days }) : $t('晚 {n} 个工作日', { n: -s.slack_days }) }}</b></div>
      </div>
      <p v-if="s.bottleneck" class="err small">{{ $td(s.bottleneck) }}</p>
      <p v-if="s.unknown_lead.length" class="warnline small">{{ $t('交期不明的采购件（按 0 天算）：{a}', { a: s.unknown_lead.join(', ') }) }}</p>
      <h3>{{ $t('自制件（倒排）') }}</h3>
      <table class="t">
        <thead><tr><th>{{ $t('物料') }}</th><th>{{ $t('名称') }}</th><th class="num">{{ $t('数量') }}</th><th class="num">{{ $t('工期（天）') }}</th>
          <th>{{ $t('最晚开工') }}</th><th>{{ $t('最晚完工') }}</th><th>{{ $t('最早完工') }}</th><th></th></tr></thead>
        <tbody><tr v-for="x in s.make" :key="x.item_code" :class="{ late: x.late_days, crit: s.critical.includes(x.item_code) }">
          <td class="mono">{{ x.item_code }}</td><td>{{ $td(x.name) }}</td><td class="num">{{ x.qty }}</td><td class="num">{{ x.days }}</td>
          <td class="mono">{{ x.latest_start }}</td><td class="mono">{{ x.latest_finish }}</td><td class="mono">{{ x.earliest_finish }}</td>
          <td class="small">{{ x.late_days ? $t('已晚 {n} 天', { n: x.late_days }) : (s.critical.includes(x.item_code) ? $t('关键') : '') }}</td></tr></tbody>
      </table>
      <h3>{{ $t('采购件（最晚到货）') }}</h3>
      <table class="t">
        <thead><tr><th>{{ $t('物料') }}</th><th>{{ $t('名称') }}</th><th class="num">{{ $t('数量') }}</th><th class="num">{{ $t('提前期（工作日）') }}</th>
          <th>{{ $t('最晚到货') }}</th><th>{{ $t('最早到货') }}</th></tr></thead>
        <tbody><tr v-for="x in s.buy" :key="x.item_code" :class="{ late: x.late_days, crit: s.critical.includes(x.item_code) }">
          <td class="mono">{{ x.item_code }}</td><td>{{ $td(x.name) }}</td><td class="num">{{ x.qty }}</td><td class="num">{{ x.lead_days ?? '?' }}</td>
          <td class="mono">{{ x.need_by }}</td><td class="mono">{{ x.earliest }}</td></tr></tbody>
      </table>
      <h3>{{ $t('工位负荷（本作业涉及的周）') }}</h3>
      <table class="t">
        <thead><tr><th>{{ $t('工作站') }}</th><th>{{ $t('周') }}</th><th class="num">{{ $t('其他工单（分）') }}</th><th class="num">{{ $t('本作业（分）') }}</th>
          <th class="num">{{ $t('能力（分）') }}</th><th class="num">{{ $t('负荷') }}</th></tr></thead>
        <tbody><tr v-for="r in s.load.rows" :key="r.workstation + r.week" :class="{ late: r.over }">
          <td>{{ $td(r.workstation) }}</td><td class="mono">{{ r.week }}</td><td class="num">{{ r.others_min }}</td><td class="num">{{ r.job_min }}</td>
          <td class="num">{{ r.capacity_min }}</td><td class="num">{{ r.load_pct }}%</td></tr></tbody>
      </table>
      <p class="small muted">{{ $td(s.basis) }}</p>
      <p class="small muted">{{ $td(s.load.basis) }}</p>
    </template>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue';
import { get } from '../lib/api';
import { t as $t, td as $td } from '../lib/i18n';

const props = defineProps({ job: Object });
const s = ref(null);
const err = ref('');
async function load() {
  err.value = '';
  try { s.value = await get(`/eto/jobs/${encodeURIComponent(props.job.job_no)}/schedule`); } catch (e) { s.value = null; err.value = e.message; }
}
watch(() => props.job.job_no, load);
onMounted(load);
</script>

<style scoped>
.head { display: flex; gap: 28px; border-radius: 8px; padding: 10px 14px; margin-bottom: 8px; }
.head > div { display: flex; flex-direction: column; gap: 2px; }
.okbox { background: #EEF7F0; } .badbox { background: #FDECEC; }
h3 { font-size: 14px; margin: 14px 0 6px; }
.t td { padding: 4px 6px; }
.t th, .t td.mono { white-space: nowrap; }
tr.late td { background: #FDECEC; }
tr.crit td:first-child { font-weight: 700; }
.err { color: var(--bad); } .warnline { color: var(--warn-ink); }
</style>
