<template>
  <div class="page">
    <div class="page-title">
      <h1><router-link to="/ont" class="back">厂情中枢</router-link> / 规则目录</h1>
      <span class="muted">{{ live }} 条在跑、{{ waiting }} 条待数据<template v-if="data?.last_round"> · 上一轮检测用时 {{ data.last_round.ms }} 毫秒</template>
        · {{ data?.can_edit ? '厂长（教师）可以改阈值和开关，每次改动都有记录' : '阈值和开关由厂长（教师）调整' }}</span>
    </div>
    <div v-if="err" class="err">{{ err }}</div>
    <section v-if="data?.calibration?.length" class="card calib">
      <div class="card-head"><h2>校准提示（来自复盘）</h2><span class="small muted">只提示，不自动改；改标准工时请在工艺规程里改</span></div>
      <ul class="small"><li v-for="(c, i) in data.calibration" :key="i">{{ c.text }}<span class="muted">（{{ c.retros.join('、') }}）</span></li></ul>
    </section>
    <section v-for="g in groups" :key="g.domain" class="card">
      <div class="card-head"><h2>{{ g.label }}</h2></div>
      <table class="t">
        <thead><tr><th>编号</th><th>规则</th><th>严重度</th><th>负责</th><th>阈值</th><th class="num">开过</th><th class="num">开着</th><th>最近</th><th>开关</th><th></th></tr></thead>
        <tbody>
          <template v-for="r in g.rules" :key="r.id">
            <tr :class="{ off: !r.enabled }">
              <td class="mono">{{ r.id }}</td>
              <td><b>{{ r.name }}</b><div class="small muted">{{ r.desc }}</div>
                <div v-if="r.error" class="small bad">出错：{{ r.error }}</div></td>
              <td><span class="sev" :class="r.severity">{{ LV[r.severity] }}</span></td>
              <td class="small">{{ r.role.map((x) => ROLES[x] || x).join('、') }}</td>
              <td class="small">
                <template v-if="r.waiting"><span class="pill mute">待数据</span></template>
                <template v-else>
                  <span v-for="(v, k) in r.params" :key="k" class="param">{{ k }}
                    <input v-if="data.can_edit && !Array.isArray(v)" v-model="edits[r.id][k]" :aria-label="r.id + ' ' + k" class="mono">
                    <b v-else class="mono">{{ Array.isArray(v) ? v.join('、') : v }}</b>
                    <span v-if="v !== r.defaults[k]" class="muted">（默认 {{ r.defaults[k] }}）</span>
                  </span>
                  <span v-if="!Object.keys(r.params).length" class="muted">—</span>
                </template>
              </td>
              <td class="num">{{ r.fired }}</td><td class="num">{{ r.open }}</td>
              <td class="small">{{ r.last_fired ? fmtTs(r.last_fired) : '—' }}</td>
              <td><label v-if="!r.waiting" class="small"><input type="checkbox" :checked="r.enabled" :disabled="!data.can_edit"
                @change="save(r, { enabled: $event.target.checked })"> 启用</label></td>
              <td class="acts">
                <button v-if="data.can_edit && changed(r)" class="btn sm primary" @click="save(r, { params: editable(r) })">保存</button>
                <button v-if="!r.waiting" class="btn sm ghost" :disabled="bt[r.id] === 'busy'" @click="backtest(r)">{{ bt[r.id] === 'busy' ? '检验中…' : '用历史检验' }}</button>
              </td>
            </tr>
            <tr v-if="bt[r.id] && bt[r.id] !== 'busy'" class="btrow">
              <td></td><td colspan="9" class="small">
                过去 7 天每 6 小时按当时的数据跑一次{{ changed(r) ? '（用上面改过的阈值）' : '' }}：共报 <b>{{ bt[r.id].total }}</b> 次。
                <span class="bars"><span v-for="p in bt[r.id].points" :key="p.at" class="bar" :style="{ height: Math.min(24, 3 + p.count * 6) + 'px' }"
                  :class="{ on: p.count }" :title="fmtTs(p.at) + '：' + p.count + ' 次' + (p.items.length ? '（' + p.items.map((x) => x.title).join('；') + '）' : '')"></span></span>
                <div class="muted">{{ bt[r.id].note }}</div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </section>
    <section v-if="data?.changes?.length" class="card">
      <div class="card-head"><h2>改动记录</h2></div>
      <table class="t small"><tbody><tr v-for="(c, i) in data.changes" :key="i">
        <td class="mono">{{ fmtTs(c.ts) }}</td><td>{{ c.who }}</td><td class="mono">{{ c.rule }}</td><td>{{ c.field }}</td>
        <td class="mono">{{ JSON.stringify(c.old) }} → {{ JSON.stringify(c.new) }}</td></tr></tbody></table>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { get, post } from '../lib/api';
import { fmtTs } from '../lib/ont';

const ROLES = { planner: '计划员', engineer: '工艺员', operator: '操作工', quality: '质检员', manager: '厂长', sales: '销售' };
const LV = { info: '提示', warn: '警告', critical: '严重' };
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
