<template>
  <div class="page">
    <div class="page-title"><h1>参数配置器</h1>
      <span class="muted">按客户要求填参数 → 自动校核、出三维、图纸和报价 → 生成订单提议（确认后写入 ERPNext）</span></div>
    <div class="tabs" role="tablist">
      <button v-for="t in tpls" :key="t.id" role="tab" :aria-selected="tid === t.id" :class="{ on: tid === t.id }" @click="pickT(t.id)">
        <b>{{ t.id }}</b> {{ t.name }}</button>
    </div>
    <div v-if="tpl" class="row">
      <section class="card side">
        <div class="card-head"><h2>参数</h2><button class="btn ghost small" @click="reset">恢复默认</button></div>
        <p class="small muted">{{ tpl.summary }}</p>
        <div v-for="(ps, g) in groups" :key="g" class="grp">
          <h3>{{ g }}</h3>
          <label v-for="p in ps" :key="p.key" class="fld">
            <span>{{ p.zh }}<small v-if="p.unit" class="muted"> {{ p.unit }}</small></span>
            <select v-if="p.choices" v-model="vals[p.key]"><option v-for="c in p.choices" :key="c.value" :value="c.value">{{ c.label }}</option></select>
            <input v-else v-model.number="vals[p.key]" type="number" :min="p.min" :max="p.max" :step="p.step">
            <small v-if="p.hint" class="muted">{{ p.hint }}</small>
          </label>
        </div>
      </section>

      <section class="card grow">
        <div class="card-head"><h2>结果</h2><span class="muted small">{{ busy ? '正在计算…' : '' }}</span></div>
        <div v-if="res" class="checks">
          <div v-for="e in res.errors" :key="e" class="err">✗ {{ e }}</div>
          <div v-for="w in res.warnings" :key="w" class="warnline">！{{ w }}</div>
          <div v-if="res.ok" class="okline">✓ 校核通过</div>
        </div>
        <table v-if="res" class="t figs"><tbody>
          <tr v-for="f in res.figures" :key="f[0]"><td class="muted">{{ f[0] }}</td><td class="mono">{{ f[1] }}</td></tr>
          <tr v-for="p in res.parts || []" :key="p.ref"><td class="muted">{{ p.zh }}</td>
            <td><router-link :to="{ path: '/library', query: { ref: p.ref } }" class="mono">{{ p.ref }}</router-link></td></tr>
        </tbody></table>
        <div class="viewer">
          <ModelViewer v-if="model" :url="model.glb" />
          <div v-else class="empty">{{ modelMsg }}</div>
        </div>
        <div v-if="model" class="drawing"><img :src="model.drawing" alt="图纸"></div>
      </section>

      <section class="card side">
        <div class="card-head"><h2>报价</h2></div>
        <template v-if="res?.quote">
          <label class="fld"><span>数量</span><input v-model.number="qty" type="number" min="1" step="1"></label>
          <table class="t"><tbody>
            <tr v-for="l in res.quote.lines" :key="l.desc"><td class="small">{{ l.desc }}</td><td class="num mono">{{ money(l.amount) }}</td></tr>
            <tr v-if="res.quote.unit_cost"><td class="small muted">单件成本 · 毛利 {{ Math.round(res.quote.margin * 100) }}%</td><td class="num mono">{{ money(res.quote.unit_cost) }}</td></tr>
            <tr><td><b>单价</b></td><td class="num mono"><b>{{ money(res.quote.unit_price) }}</b></td></tr>
            <tr><td><b>合计 × {{ res.quote.qty }}</b></td><td class="num mono"><b>{{ money(res.quote.total) }}</b></td></tr>
          </tbody></table>
          <h3>生成订单提议</h3>
          <label class="fld"><span>客户</span><select v-model="customer"><option v-for="c in customers" :key="c" :value="c">{{ c }}</option></select></label>
          <label class="fld"><span>交期</span><input v-model="due" type="date"></label>
          <button class="btn primary" :disabled="!res.ok || ordering" @click="order">{{ ordering ? '正在生成…' : '生成订单提议' }}</button>
          <div v-if="orderMsg" :class="orderOk ? 'ok' : 'err'" class="small">{{ orderMsg }}
            <router-link v-if="orderOk" to="/work/planner">到“订单与计划”确认 →</router-link></div>
          <p class="small muted">提议确认后，桥接在 ERPNext 里建销售订单（单价按本报价）、算料、请购、工单草稿。</p>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { get, post, loadConfig } from '../lib/api';
import ModelViewer from '../components/ModelViewer.vue';

const tpls = ref([]);
const tid = ref('WQR-105');
const vals = ref({});
const qty = ref(1);
const res = ref(null);
const model = ref(null);
const modelMsg = ref('正在生成三维…');
const busy = ref(false);
const customers = ref([]);
const customer = ref('');
const due = ref(new Date(Date.now() + 21 * 864e5).toISOString().slice(0, 10));
const ordering = ref(false);
const orderMsg = ref('');
const orderOk = ref(true);
const tpl = computed(() => tpls.value.find((t) => t.id === tid.value));
const groups = computed(() => (tpl.value?.params || []).reduce((g, p) => ((g[p.group] = g[p.group] || []).push(p), g), {}));
const money = (x) => '$' + Number(x || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function reset() { vals.value = Object.fromEntries(tpl.value.params.map((p) => [p.key, p.default])); }
function pickT(id) { tid.value = id; reset(); }
let t1, t2, seq = 0;
async function evaluate() {
  busy.value = true;
  try { res.value = await post(`/configurator/${tid.value}/evaluate`, { values: vals.value, qty: qty.value }); } finally { busy.value = false; }
}
async function buildModel() {
  const my = ++seq;
  modelMsg.value = '正在生成三维和图纸…';
  try {
    const m = await post(`/configurator/${tid.value}/model`, { values: vals.value });
    if (my === seq) model.value = m;
  } catch (e) { if (my === seq) { model.value = null; modelMsg.value = e.message; } }
}
watch([vals, qty], () => {
  clearTimeout(t1); clearTimeout(t2);
  t1 = setTimeout(evaluate, 250);
  t2 = setTimeout(buildModel, 900);
}, { deep: true });
async function order() {
  ordering.value = true; orderMsg.value = '';
  try {
    const r = await post(`/configurator/${tid.value}/order`, { values: vals.value, qty: qty.value, customer: customer.value, delivery_date: due.value });
    orderOk.value = true; orderMsg.value = `已生成提议 ${r.proposal_id}。`;
  } catch (e) { orderOk.value = false; orderMsg.value = e.message; } finally { ordering.value = false; }
}
onMounted(async () => {
  const [t, c] = await Promise.all([get('/configurator'), loadConfig()]);
  tpls.value = t;
  customers.value = c.customers || [];
  customer.value = customers.value[0] || '';
  reset();
});
</script>

<style scoped>
.tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.tabs button { padding: 8px 14px; border-radius: 8px; border: 1px solid var(--line); background: #fff; cursor: pointer; }
.tabs button.on { border-color: var(--accent); background: var(--accent-bg); }
.side { width: 300px; flex-shrink: 0; display: flex; flex-direction: column; gap: 8px; }
.grow { flex-grow: 1; min-width: 0; }
.grp h3, .side h3 { font-size: 13px; margin: 10px 0 4px; }
.fld { display: flex; flex-direction: column; gap: 3px; font-size: 13px; margin-bottom: 6px; }
.fld input, .fld select { border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; font: inherit; }
.checks { display: flex; flex-direction: column; gap: 4px; margin-bottom: 8px; font-size: 13px; }
.err { color: var(--bad); } .ok, .okline { color: var(--good); } .warnline { color: var(--warn-ink); }
.figs td { padding: 4px 8px; }
.viewer { margin-top: 10px; }
.drawing { margin-top: 10px; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.drawing img { width: 100%; display: block; }
.btn.small { height: 26px; font-size: 12px; margin-left: auto; }
@media (max-width: 1200px) { .side { width: auto; } }
</style>
