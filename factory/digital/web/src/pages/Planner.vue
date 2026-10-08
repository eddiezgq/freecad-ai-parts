<template>
  <div class="page">
    <TaskBar v-if="teachStatus" :t="teachStatus" />
    <div class="page-title"><h1>订单与计划</h1><span class="muted">计划员工作区 · 接单、算料（MRP）、下达车间</span></div>

    <div class="row">
      <section class="card neworder">
        <div class="card-head"><h2>新建订单</h2><span class="muted small">先算料，看清楚再提交；提交后要你确认才写入 ERPNext</span></div>
        <form class="form" @submit.prevent="calc">
          <div class="field"><label>客户</label>
            <select v-model="f.customer" required><option v-for="c in customers" :key="c" :value="c">{{ short(c) }}</option></select></div>
          <div class="field"><label>产品</label><select v-model="f.item"><option value="WQR-105">WQR-105 二级圆柱齿轮减速器</option></select></div>
          <div class="field"><label>数量（台）</label><input v-model.number="f.qty" type="number" min="1" max="200" required></div>
          <div class="field"><label>交期</label><input v-model="f.delivery_date" type="date" required></div>
          <button class="btn">算料</button>
        </form>
        <div v-if="err" class="err">{{ err }}</div>
        <template v-if="pv">
          <h3>算料结果</h3>
          <table class="t">
            <thead><tr><th>物料</th><th class="num">毛需求</th><th class="num">占用</th><th class="num">库存</th><th class="num">在途</th>
              <th class="num">安全</th><th class="num">净需求</th><th>动作</th></tr></thead>
            <tbody><tr v-for="r in pv.mrp" :key="r.item_code" :class="{ need: r.net > 0 }">
              <td><ObjLink type="Item" :k="r.item_code" mono /> <span class="muted small">{{ r.name.split(' ')[0] }}</span></td>
              <td class="num">{{ n(r.gross) }}</td><td class="num">{{ n(r.committed) }}</td><td class="num">{{ n(r.stock) }}</td>
              <td class="num">{{ n(r.on_order) }}</td><td class="num">{{ n(r.safety) }}</td><td class="num">{{ n(r.net) }}</td><td>{{ r.action }}</td>
            </tr></tbody>
          </table>
          <p class="small">工单：<b v-for="w in pv.work_orders" :key="w.production_item" class="mono">{{ w.production_item }} × {{ w.qty }}（{{ w.planned_start_date }} → {{ w.expected_delivery_date }}）</b>
            · 请购 {{ pv.material_requests.length }} 项<template v-if="pv.std_cost_sh301"> · SH-301 标准成本 ${{ pv.std_cost_sh301.total }}/件</template></p>
          <p v-if="pv.warnings.length" class="warn small">{{ pv.warnings.join('；') }}</p>
          <p class="muted small">{{ pv.basis }}。净需求 = 毛需求 + 其他订单占用 + 安全库存 − 库存 − 在途。</p>
          <button class="btn primary" :disabled="busy" @click="submit">提交（生成待确认的提议）</button>
        </template>
      </section>

      <section class="card side">
        <div class="card-head"><h2>提议</h2><span class="muted small">AI 起草或你提交的，确认后才执行</span></div>
        <div v-if="!props_.length" class="empty">暂无</div>
        <div v-for="p in props_" :key="p.proposal_id" class="prow" @click="pid = p.proposal_id">
          <span class="pill" :class="stTone(p.status)">{{ stText(p.status) }}</span>
          <span class="small">{{ p.title }}</span>
        </div>
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>工单</h2><span class="muted small">下达后按工艺路线逐道派给设备；操作工在车间终端开工</span>
        <button class="btn ghost more" @click="load">刷新</button></div>
      <table class="t">
        <thead><tr><th>工单</th><th>物料</th><th class="num">数量</th><th class="num">完工</th><th>计划</th><th>销售订单</th><th>状态</th><th></th></tr></thead>
        <tbody>
          <tr v-for="w in wos" :key="w.name">
            <td class="mono"><ObjLink type="WorkOrder" :k="w.name" /><span v-if="w.demo" class="pill mute">演示</span></td>
            <td class="mono"><ObjLink type="Item" :k="w.production_item" /></td><td class="num">{{ w.qty }}</td><td class="num">{{ w.produced }}</td>
            <td class="mono small">{{ w.planned_start_date }} → {{ w.expected_delivery_date }}</td>
            <td class="mono small"><ObjLink v-if="w.sales_order" type="SalesOrder" :k="w.sales_order" /></td>
            <td><span class="pill" :class="w.status === 'Completed' ? 'good' : w.released ? 'info' : 'warn'">{{ woStatus(w) }}</span></td>
            <td><button v-if="!w.released && w.status !== 'Completed' && !w.demo" class="btn primary" :disabled="busy" @click="release(w.name)">下达车间</button></td>
          </tr>
        </tbody>
      </table>
      <div v-if="relMsg" class="ok">{{ relMsg }}</div>
    </section>
    <ProposalModal v-if="pid" :pid="pid" @close="pid = null; load()" @done="load" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import { get, post, session } from '../lib/api';
import { short } from '../lib/fmt';
import ProposalModal from '../components/ProposalModal.vue';
import TaskBar from '../components/TaskBar.vue';
import ObjLink from '../components/ObjLink.vue';

const customers = ref([]);
const f = ref({ customer: '', item: 'WQR-105', qty: 10, delivery_date: '2026-10-15' });
const pv = ref(null);
const err = ref(null);
const busy = ref(false);
const pid = ref(null);
const props_ = ref([]);
const wos = ref([]);
const relMsg = ref('');
const teachStatus = ref(null);
const n = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }));
const stText = (s) => ({ pending: '待确认', confirmed: '执行中', executed: '已执行', rejected: '已否决', failed: '失败' }[s]);
const stTone = (s) => ({ pending: 'warn', confirmed: 'info', executed: 'good', rejected: 'mute', failed: 'bad' }[s]);
const woStatus = (w) => (w.status === 'Completed' ? '已完工' : w.started ? '加工中' : w.released ? '已下达' : '未下达');

async function load() {
  const [c, p, w] = await Promise.all([get('/config'), get('/proposals'), get('/work_orders')]);
  customers.value = c.customers;
  if (!f.value.customer) f.value.customer = c.customers[0];
  props_.value = p;
  wos.value = w;
  if (session.user.mode === 'teach') teachStatus.value = await get('/teach');
}
async function calc() {
  err.value = null;
  try { pv.value = await post('/plan/order', f.value); } catch (e) { err.value = e.message; }
}
async function submit() {
  busy.value = true;
  try {
    const r = await post('/proposals', { action: 'create_order_and_plan', ...f.value });
    pid.value = r.proposal_id;
    pv.value = null;
    await load();
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
async function release(name) {
  busy.value = true; relMsg.value = '';
  try {
    const r = await post('/mes/release', { work_order: name });
    relMsg.value = `已下达 ${name}：` + r.dispatched.map((d) => `${d.operation.split(' ')[0]}→${d.unit.toUpperCase()}`).join('，');
    await load();
  } catch (e) { relMsg.value = e.message; } finally { busy.value = false; }
}
onMounted(load);
</script>

<style scoped>
.neworder { flex-grow: 1; min-width: 0; }
.side { width: 340px; flex-shrink: 0; }
.form { display: grid; grid-template-columns: 2fr 2fr 1fr 1.3fr auto; gap: 10px; align-items: end; }
h3 { font-size: 14px; margin: 16px 0 8px; }
tr.need td { background: #FFF8EC; }
.warn { color: var(--warn-ink); }
.prow { display: flex; gap: 8px; align-items: baseline; padding: 8px 0; border-top: 1px solid var(--line-soft); cursor: pointer; }
.prow:hover { background: var(--surface-2); }
.pill.mute { margin-left: 6px; }
@media (max-width: 1100px) { .form { grid-template-columns: 1fr 1fr; } .side { width: auto; } }
</style>
