<!-- 复盘（第 17 轮 D 期 D8）：推演预测 vs 实际、偏差原因、“如果当时选别的” -->
<template>
  <div class="rp">
    <div class="rp-h"><h3>{{ $t('复盘') }}</h3>
      <span v-if="r" class="small muted">{{ $td(r.key) }} · {{ fmtTs(r.created_at) }}<template v-if="r.partial"> {{ $t('· 受影响的工单还没做完，做完后会自动更新') }}</template></span>
      <button v-if="data?.can_create && (!r || r.partial)" class="linkbtn" :disabled="busy" @click="make">{{ busy ? $t('复盘中…') : $t('现在复盘') }}</button></div>
    <p v-if="err" class="small err">{{ err }}</p>
    <p v-if="data && !r" class="small muted">{{ data.can_create ? $t('采纳的动作已执行；异常解决、受影响的工单做完后会自动复盘。') : $t('这个异常还没有执行完的动作，处理完以后自动复盘。') }}</p>
    <template v-if="r">
      <table class="t small">
        <thead><tr><th>{{ $t('工单') }}</th><th>{{ $t('推演完工') }}</th><th>{{ $t('实际完工') }}</th><th class="num">{{ $t('偏差') }}</th></tr></thead>
        <tbody><tr v-for="w in r.deviation.work_orders" :key="w.work_order"><td class="mono">{{ $td(w.work_order) }}</td><td>{{ fmtTs(w.predicted) || '—' }}</td>
          <td>{{ w.actual ? fmtTs(w.actual) : $t('还没做完（') + w.done + '/' + w.qty + $t('）') }}</td>
          <td class="num">{{ w.pct == null ? '—' : (w.diff_h > 0 ? $t('晚 ') : $t('早 ')) + Math.abs(w.diff_h) + $t(' 小时（') + (w.pct > 0 ? '+' : '') + w.pct + $t('%）') }}</td></tr></tbody>
      </table>
      <table class="t small">
        <thead><tr><th>{{ $t('订单') }}</th><th>{{ $t('推演交付') }}</th><th>{{ $t('实际交付') }}</th></tr></thead>
        <tbody><tr v-for="(s, i) in r.predicted.sales_orders" :key="s.name"><td class="mono">{{ $td(s.name) }}</td><td>{{ soText(s) }}</td><td>{{ soText(r.actual.sales_orders[i]) }}</td></tr></tbody>
      </table>
      <p class="small">{{ $t('多花的钱：推演') }} <b>${{ money(r.predicted.cost_total) }}</b>{{ $t('，实际') }} <b>${{ money(r.actual.cost_total) }}</b>
        <span v-if="r.deviation.cost_diff" :class="r.deviation.cost_diff > 0 ? 'late' : 'ok'">{{ $t('（{a}${b}）', { a: r.deviation.cost_diff > 0 ? '+' : '', b: money(r.deviation.cost_diff) }) }}</span></p>
      <div class="small"><b>{{ $t('偏差的可能原因：') }}</b>
        <span v-if="!r.causes.length" class="muted">{{ $t('没找到明显原因（推演和实际基本一致）。') }}</span>
        <ul v-else><li v-for="(c, i) in r.causes" :key="i">{{ $td(c.text) }}<router-link v-if="c.anomaly_id" :to="{ path: '/ont', query: { view: 'anomalies', a: c.anomaly_id } }"> {{ $t('看') }}</router-link></li></ul></div>
      <div v-if="r.counterfactual.length" class="small"><b>{{ $t('如果当时……') }}</b>{{ $t('（用当时的快照重算各方案）') }}
        <table class="t small"><thead><tr><th>{{ $t('方案') }}</th><th>{{ $t('订单') }}</th><th class="num">{{ $t('多花') }}</th></tr></thead>
          <tbody><tr v-for="o in r.counterfactual" :key="o.key" :class="{ chosen: o.chosen }"><td>{{ $td(o.key) }} {{ $td(o.label) }}<span v-if="o.chosen" class="pill info">{{ $t('采纳了') }}</span>
            <span v-if="o.recommended" class="pill good">{{ $t('当时建议') }}</span></td>
            <td>{{ o.sales_orders.map(soText).join($t('；')) }}</td><td class="num">${{ money(o.cost_total) }}</td></tr></tbody></table></div>
      <router-link v-if="r.scenario_id" class="small" :to="{ path: '/ont/sim', query: { scenario: r.scenario_id } }">{{ $t('在推演工作台打开当时的推演') }}</router-link>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, ref, watch } from 'vue';
import { get, post } from '../lib/api';
import { fmtTs } from '../lib/ont';

const props = defineProps({ anomalyId: Number });
const data = ref(null);
const err = ref('');
const busy = ref(false);
const r = computed(() => data.value?.retro);
const money = (v) => Math.round(v || 0).toLocaleString();
function soText(s) {
  if (!s || s.late_days == null) return '—';
  return $t('{a}，{b}', { a: s.projected, b: s.late_days > 0 ? $t('晚 ') + s.late_days + $t(' 天') : $t('按时') });
}
async function load() { err.value = ''; try { data.value = await get(`/ont/anomalies/${props.anomalyId}/retro`); } catch (e) { err.value = e.message; } }
async function make() { busy.value = true; try { data.value = await post(`/ont/anomalies/${props.anomalyId}/retro`); } catch (e) { err.value = e.message; } finally { busy.value = false; } }
watch(() => props.anomalyId, load, { immediate: true });
</script>

<style scoped>
.rp-h { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; margin-top: 14px; }
.rp-h h3 { font-size: 14px; margin: 0; }
.rp-h .linkbtn { margin-left: auto; }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; }
.t { width: 100%; margin: 6px 0; }
.num { text-align: right; }
tr.chosen td { background: var(--surface-2); }
.late { color: var(--bad); }
.ok { color: var(--good); }
.err { color: var(--bad); }
ul { margin: 4px 0; padding-left: 18px; }
</style>
