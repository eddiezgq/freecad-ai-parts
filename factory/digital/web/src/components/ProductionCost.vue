<!-- 生产与成本（原“经营与成本”页，第 19 轮 J-8 并进“经营与财务”）：设备综合效率、本月交付、工单成本分解；实验 7 任务 6 在这里做 -->
<template>
  <div class="pc">
    <TaskBar v-if="teachStatus" :t="teachStatus" />

    <div class="row">
      <section class="card grow">
        <div class="card-head"><h2>设备综合效率（今日）</h2><span class="muted small">OEE = 时间开动率 × 性能开动率 × 合格品率 · 来自 machine_state_log 与完工事件</span></div>
        <table class="t">
          <thead><tr><th>设备</th><th class="num">OEE</th><th class="num">开动率</th><th class="num">性能</th><th class="num">合格率</th>
            <th class="num">运行</th><th class="num">调整</th><th class="num">停机</th></tr></thead>
          <tbody><tr v-for="(v, u) in ov?.oee.machines || {}" :key="u">
            <td class="mono">{{ u.toUpperCase() }}</td><td class="num"><b>{{ pct(v.oee) }}</b></td><td class="num">{{ pct(v.availability) }}</td>
            <td class="num">{{ pct(v.performance) }}</td><td class="num">{{ pct(v.quality) }}</td>
            <td class="num">{{ mins(v.run_s) }}</td><td class="num">{{ mins(v.setup_s) }}</td><td class="num">{{ mins(v.down_s) }}</td>
          </tr></tbody>
        </table>
        <p class="muted small">时长为真实时间（仿真倍速下会比工时短）；比率不受倍速影响。全厂 OEE {{ pct(ov?.oee.value) }}，按负荷时间加权。</p>
      </section>
      <section class="card side">
        <div class="card-head"><h2>本月交付</h2></div>
        <p>准时交付率 <b class="mono big">{{ pct(ov?.on_time.value) }}</b>（已交付 {{ ov?.on_time.delivered || 0 }} 单）</p>
        <p class="small">本周加工成本：标准 <b class="mono">{{ money(ov?.cost.std) }}</b>，实际 <b class="mono">{{ money(ov?.cost.actual) }}</b>
          （{{ pctSigned(ov?.cost.value) }}），其中调整与换刀 <b class="mono">{{ money(ov?.cost.setup) }}</b>。</p>
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>工单成本分解</h2>
        <select v-model="wo" @change="loadCost"><option v-for="w in wos" :key="w" :value="w">{{ w }}</option></select>
        <span class="muted small">标准只含单件工时；实际另含调整与换刀 · 工时 × 工位小时费率</span></div>
      <div v-if="costErr" class="empty">{{ costErr }}</div>
      <template v-if="cost">
        <p>{{ cost.work_order }} 已完工 {{ cost.parts_finished }} 件：加工标准成本 <b class="mono">{{ money(cost.std_cost) }}</b>，实际
          <b class="mono">{{ money(cost.actual_cost) }}</b>，差异 <b class="mono" :style="{ color: cost.variance > 0 ? 'var(--bad)' : 'var(--good)' }">{{ money(cost.variance) }}（{{ cost.variance_pct > 0 ? '+' : '' }}{{ cost.variance_pct }}%）</b>。
          材料按标准每件 {{ money(cost.material_std_per_unit) }}。</p>
        <table class="t">
          <thead><tr><th>工序</th><th>设备</th><th class="num">件数</th><th class="num">标准工时</th><th class="num">实际加工</th><th class="num">调整+换刀</th>
            <th class="num">费率/时</th><th class="num">标准成本</th><th class="num">实际成本</th><th class="num">差异</th></tr></thead>
          <tbody><tr v-for="l in cost.lines" :key="l.op_index">
            <td>{{ l.operation.split(' ')[0] }}</td><td class="mono">{{ l.unit.toUpperCase() }}</td><td class="num">{{ l.parts }}</td>
            <td class="num">{{ mins(l.std_s) }}</td><td class="num">{{ mins(l.cycle_s) }}</td><td class="num">{{ mins(l.setup_s + l.tool_change_s) }}</td>
            <td class="num">${{ l.rate_h }}</td><td class="num">{{ money(l.std_cost) }}</td><td class="num">{{ money(l.actual_cost) }}</td>
            <td class="num" :style="{ color: l.variance > 0 ? 'var(--bad)' : 'var(--good)' }">{{ money(l.variance) }}</td>
          </tr></tbody>
        </table>
        <p class="muted small">{{ cost.note }} 来源：{{ cost.evidence.topic }}，corr = {{ cost.work_order }}，{{ cost.evidence.messages }} 条完工事件。时长为工厂分钟。</p>
      </template>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { get, session } from '../lib/api';
import { money, pct, pctSigned } from '../lib/fmt';
import { useOverview } from '../lib/overview';
import TaskBar from './TaskBar.vue';

const { ov } = useOverview(10000);
const teach = computed(() => session.user.mode === 'teach');
const wos = ref([]);
const wo = ref('');
const cost = ref(null);
const costErr = ref('');
const teachStatus = ref(null);
const mins = (s) => (s === undefined || s === null ? '—' : (s / 60).toFixed(1));

async function loadCost() {
  cost.value = null; costErr.value = '';
  if (!wo.value) return;
  try { cost.value = await get(`/work_orders/${wo.value}/cost`); } catch (e) { costErr.value = e.message; }
}
onMounted(async () => {
  const list = await get('/work_orders');
  wos.value = list.filter((w) => w.started).map((w) => w.name);
  wo.value = wos.value[0] || '';
  loadCost();
  if (teach.value) teachStatus.value = await get('/teach');
});
</script>

<style scoped>
.grow { flex-grow: 1; min-width: 0; }
.side { width: 340px; flex-shrink: 0; }
.big { font-size: 22px; }
.card-head select { height: 32px; border: 1px solid var(--line); border-radius: 6px; }
.t { width: 100%; }
@media (max-width: 1100px) { .side { width: auto; } }
@media (max-width: 700px) { .row { flex-direction: column; } .t { display: block; overflow-x: auto; } }
</style>
