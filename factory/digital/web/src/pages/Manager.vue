<template>
  <div class="page">
    <TaskBar v-if="teachStatus" :t="teachStatus" />
    <div class="page-title"><h1>经营与成本</h1><span class="muted">厂长工作区 · 设备效率、工单成本、交付；教学模式下也是教师控制台</span></div>

    <section v-if="teach" class="card teacher">
      <div class="card-head"><h2>教师控制台</h2><span class="muted small">只在教学模式出现；指令经总线发给仿真车间（machining/sim/cmd）</span></div>
      <div class="ctl">
        <div class="field"><label>仿真倍速</label>
          <div class="inline"><select v-model.number="speed"><option v-for="s in [1, 5, 20, 60, 120, 300]" :key="s" :value="s">{{ s }}×</option></select>
            <button class="btn" @click="setSpeed">应用</button></div></div>
        <div class="field"><label>制造一次故障</label>
          <div class="inline">
            <select v-model="fault.unit"><option v-for="m in units" :key="m" :value="m">{{ m.toUpperCase() }}</option></select>
            <input v-model.number="fault.minutes" type="number" min="5" max="480" style="width: 80px" aria-label="分钟">
            <input v-model="fault.reason" style="width: 120px" aria-label="原因">
            <button class="btn danger" @click="injectFault">注入</button></div></div>
        <div class="field"><label>车间班次（第 17 轮 C 期）</label>
          <div class="inline">
            <select v-model="shiftMode" aria-label="班次模式"><option value="continuous">24 小时连续</option><option value="shift">按班次（周一至周五 08:00–17:00）</option></select>
            <button class="btn" @click="setShift">应用</button></div>
          <span class="small muted">按班次时可以在厂情中枢推演和批准“加班”</span></div>
        <div class="field"><label>重置实验 7 情景</label>
          <div class="inline">
            <label class="small"><input v-model="resetScores" type="checkbox"> 同时清空学生得分</label>
            <button class="btn danger" @click="reset">重置</button></div></div>
      </div>
      <div v-if="ctlMsg" class="ok small">{{ ctlMsg }}</div>
    </section>

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
        <p class="muted small">{{ cost.note }} 来源：{{ cost.evidence.topic }}，corr = {{ cost.work_order }}，{{ cost.evidence.messages }} 条完工事件。时长为仿真分钟。</p>
      </template>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { get, post, session } from '../lib/api';
import { money, pct, pctSigned } from '../lib/fmt';
import { useOverview } from '../lib/overview';
import TaskBar from '../components/TaskBar.vue';

const { ov } = useOverview(10000);
const teach = computed(() => session.user.mode === 'teach');
const wos = ref([]);
const wo = ref('');
const cost = ref(null);
const costErr = ref('');
const teachStatus = ref(null);
const speed = ref(20);
const fault = ref({ unit: 'grd-01', minutes: 30, reason: '主轴过热' });
const units = ['saw-01', 'cnc-l01-a', 'cnc-l01-b', 'key-01', 'ht-01', 'grd-01', 'qc-01'];
const resetScores = ref(false);
const ctlMsg = ref('');
const mins = (s) => (s === undefined || s === null ? '—' : (s / 60).toFixed(1));

async function loadCost() {
  cost.value = null; costErr.value = '';
  if (!wo.value) return;
  try { cost.value = await get(`/work_orders/${wo.value}/cost`); } catch (e) { costErr.value = e.message; }
}
async function setSpeed() {
  await post('/mes/cmd', { unit: 'sim', command: 'set_speed', speed: speed.value });
  ctlMsg.value = `已把仿真倍速改为 ${speed.value}×`;
}
const shiftMode = ref('continuous');
async function loadShift() { try { shiftMode.value = (await get('/ont/shifts')).calendar.mode; } catch (e) { /* 老版本没有 */ } }
async function setShift() {
  try { const r = await post('/ont/shifts', { mode: shiftMode.value }); ctlMsg.value = '车间班次：' + (r.calendar.mode === 'shift' ? '按班次' : '24 小时连续') + '，已发给仿真车间'; } catch (e) { ctlMsg.value = e.message; }
}
async function injectFault() {
  await post('/mes/cmd', { unit: fault.value.unit, command: 'inject_fault', minutes: fault.value.minutes, reason: fault.value.reason });
  ctlMsg.value = `已让 ${fault.value.unit.toUpperCase()} 停机 ${fault.value.minutes} 分钟（${fault.value.reason}）`;
}
async function reset() {
  if (!confirm('清空教学模式的全部历史，重新载入实验 7 情景？')) return;
  await post('/scenario/reset', { speed: 1, scores: resetScores.value });
  ctlMsg.value = '已重置，情景约 5 秒后载入完成';
}
onMounted(async () => {
  if (teach.value) loadShift();
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
.teacher { border-color: var(--task-line); background: #FFFCF0; }
.ctl { display: flex; gap: 24px; flex-wrap: wrap; }
.inline { display: flex; gap: 6px; align-items: center; }
.inline select, .inline input { height: 34px; border: 1px solid #C8CEC7; border-radius: 6px; padding: 0 8px; }
.card-head select { height: 32px; border: 1px solid var(--line); border-radius: 6px; }
@media (max-width: 1100px) { .side { width: auto; } }
</style>
