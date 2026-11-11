<template>
  <div class="page">
    <div class="page-title">
      <h1><router-link to="/ont" class="back">{{ $t('厂情中枢') }}</router-link> {{ $t('/ 规则目录') }}</h1>
      <span class="muted">{{ $t('{a} 条在跑、{b} 条待数据', { a: live, b: waiting }) }}<template v-if="data?.last_round"> {{ $t('· 上一轮检测用时 {a} 毫秒', { a: $td(data.last_round.ms) }) }}</template>
        · {{ data?.can_edit ? $t('厂长（教师）可以改阈值和开关，每次改动都有记录') : $t('阈值和开关由厂长（教师）调整') }}</span>
    </div>
    <div v-if="err" class="err">{{ err }}</div>
    <section v-if="data?.calibration?.length" class="card calib">
      <div class="card-head"><h2>{{ $t('校准提示（来自复盘）') }}</h2><span class="small muted">{{ $t('只提示，不自动改；改标准工时请在工艺规程里改') }}</span></div>
      <ul class="small"><li v-for="(c, i) in data.calibration" :key="i">{{ $td(c.text) }}<span class="muted">{{ $t('（{a}）', { a: c.retros.join($t('、')) }) }}</span></li></ul>
    </section>
    <section v-for="g in groups" :key="g.domain" class="card">
      <div class="card-head"><h2>{{ $td(g.label) }}</h2></div>
      <table class="t">
        <thead><tr><th>{{ $t('编号') }}</th><th>{{ $t('规则') }}</th><th>{{ $t('严重度') }}</th><th>{{ $t('负责') }}</th><th>{{ $t('阈值') }}</th><th class="num">{{ $t('开过') }}</th><th class="num">{{ $t('开着') }}</th><th>{{ $t('最近') }}</th><th>{{ $t('开关') }}</th><th></th></tr></thead>
        <tbody>
          <template v-for="r in g.rules" :key="r.id">
            <tr :class="{ off: !r.enabled }">
              <td class="mono">{{ $td(r.id) }}</td>
              <td><b>{{ $td(r.name) }}</b><div class="small muted">{{ $td(r.desc) }}</div>
                <div v-if="r.error" class="small bad">{{ $t('出错：{a}', { a: $td(r.error) }) }}</div></td>
              <td><span class="sev" :class="r.severity">{{ $td(LV[r.severity]) }}</span></td>
              <td class="small">{{ r.role.map((x) => ROLES[x] || x).join($t('、')) }}</td>
              <td class="small">
                <template v-if="r.waiting"><span class="pill mute">{{ $t('待数据') }}</span></template>
                <template v-else>
                  <span v-for="(v, k) in r.params" :key="k" class="param">{{ k }}
                    <input v-if="data.can_edit && !Array.isArray(v)" v-model="edits[r.id][k]" :aria-label="r.id + ' ' + k" class="mono">
                    <b v-else class="mono">{{ Array.isArray(v) ? v.join($t('、')) : v }}</b>
                    <span v-if="v !== r.defaults[k]" class="muted">{{ $t('（默认 {a}）', { a: $td(r.defaults[k]) }) }}</span>
                  </span>
                  <span v-if="!Object.keys(r.params).length" class="muted">—</span>
                </template>
              </td>
              <td class="num">{{ $td(r.fired) }}</td><td class="num">{{ $td(r.open) }}</td>
              <td class="small">{{ r.last_fired ? fmtTs(r.last_fired) : '—' }}</td>
              <td><label v-if="!r.waiting" class="small"><input type="checkbox" :checked="r.enabled" :disabled="!data.can_edit"
                @change="save(r, { enabled: $event.target.checked })"> {{ $t('启用') }}</label></td>
              <td class="acts">
                <button v-if="data.can_edit && changed(r)" class="btn sm primary" @click="save(r, { params: editable(r) })">{{ $t('保存') }}</button>
                <button v-if="!r.waiting" class="btn sm ghost" :disabled="bt[r.id] === 'busy'" @click="backtest(r)">{{ bt[r.id] === 'busy' ? $t('检验中…') : $t('用历史检验') }}</button>
              </td>
            </tr>
            <tr v-if="bt[r.id] && bt[r.id] !== 'busy'" class="btrow">
              <td></td><td colspan="9" class="small">
                {{ $t('过去 7 天每 6 小时按当时的数据跑一次{a}：共报', { a: changed(r) ? $t('（用上面改过的阈值）') : '' }) }} <b>{{ $td(bt[r.id].total) }}</b> {{ $t('次。') }}
                <span class="bars"><span v-for="p in bt[r.id].points" :key="p.at" class="bar" :style="{ height: Math.min(24, 3 + p.count * 6) + 'px' }"
                  :class="{ on: p.count }" :title="fmtTs(p.at) + $t('：') + p.count + $t(' 次') + (p.items.length ? $t('（') + p.items.map((x) => x.title).join($t('；')) + $t('）') : '')"></span></span>
                <div class="muted">{{ $td(bt[r.id].note) }}</div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </section>
    <section v-if="data?.changes?.length" class="card">
      <div class="card-head"><h2>{{ $t('改动记录') }}</h2></div>
      <table class="t small"><tbody><tr v-for="(c, i) in data.changes" :key="i">
        <td class="mono">{{ fmtTs(c.ts) }}</td><td>{{ $td(c.who) }}</td><td class="mono">{{ $td(c.rule) }}</td><td>{{ $td(c.field) }}</td>
        <td class="mono">{{ JSON.stringify(c.old) }} → {{ JSON.stringify(c.new) }}</td></tr></tbody></table>
    </section>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, reactive, ref } from 'vue';
import { get, post } from '../lib/api';
import { fmtTs } from '../lib/ont';

const ROLES = { planner: $t('计划员'), engineer: $t('工艺员'), operator: $t('操作工'), quality: $t('质检员'), manager: $t('厂长'), sales: $t('销售') };
const LV = { info: $t('提示'), warn: $t('警告'), critical: $t('严重') };
const data = ref(null);
const err = ref('');
const edits = reactive({});
const bt = reactive({});
const live = computed(() => (data.value?.rules || []).filter((r) => !r.waiting).length);
const waiting = computed(() => (data.value?.rules || []).filter((r) => r.waiting).length);
const groups = computed(() => {
  const g = {};
  for (const r of data.value?.rules || []) (g[r.domain] ||= { domain: r.domain, label: r.domain_label, rules: [] }).rules.push(r);
  return Object.values(g).sort((a, b) => a.rules.every((r) => r.waiting) - b.rules.every((r) => r.waiting));
});
function changed(r) { return Object.entries(r.params).some(([k, v]) => !Array.isArray(v) && String(edits[r.id]?.[k]) !== String(v)); }
function editable(r) { return Object.fromEntries(Object.entries(edits[r.id] || {}).filter(([, v]) => !Array.isArray(v))); }
function fill(d) {
  data.value = d;
  for (const r of d.rules) edits[r.id] = { ...r.params };
}
async function load() { try { fill(await get('/ont/rules')); } catch (e) { err.value = e.message; } }
async function save(r, body) {
  try { fill(await post('/ont/rules/' + r.id, body)); } catch (e) { alert(e.message); load(); }
}
async function backtest(r) {
  bt[r.id] = 'busy';
  try { bt[r.id] = await post(`/ont/rules/${r.id}/backtest`, { days: 7, step_h: 6, params: changed(r) ? editable(r) : undefined }); } catch (e) { bt[r.id] = null; alert(e.message); }
}
onMounted(load);
</script>

<style scoped>
.calib { border-left: 4px solid var(--warn); }
.back { color: var(--muted); font-weight: 500; }
tr.off { opacity: .55; }
.sev { font-size: 11px; font-weight: 600; border-radius: 4px; padding: 1px 6px; color: #fff; }
.sev.critical { background: var(--bad); }
.sev.warn { background: var(--warn); }
.sev.info { background: var(--accent); }
.param { display: inline-flex; gap: 3px; align-items: center; margin-right: 8px; white-space: nowrap; }
.param input { width: 64px; height: 26px; border: 1px solid #C8CEC7; border-radius: 4px; padding: 0 4px; }
.acts { white-space: nowrap; }
.btn.sm { height: 28px; padding: 0 8px; }
.bad { color: var(--bad); }
.btrow td { background: var(--surface-2); }
.bars { display: inline-flex; gap: 2px; align-items: flex-end; height: 26px; margin-left: 8px; vertical-align: middle; }
.bar { width: 6px; background: var(--line); border-radius: 1px; }
.bar.on { background: var(--warn); }
</style>
