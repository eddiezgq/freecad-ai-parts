<template>
  <div class="page">
    <TaskBar v-if="teachStatus" :t="teachStatus" />
    <div class="page-title"><h1>车间终端</h1><span class="muted">操作工工作区 · 选你的工位，开工、暂停、复位；数据实时来自统一数据总线</span></div>
    <BusNotice />
    <div class="tabs" data-help="op-units" role="tablist">
      <button v-for="m in machines" :key="m.unit" role="tab" :aria-selected="unit === m.unit" :class="{ on: unit === m.unit }"
        @click="pick(m.unit)">
        <i :style="{ background: STATE[m.state].color }"></i>{{ m.code }}
      </button>
    </div>
    <div v-if="cur" class="row">
      <section class="card grow">
        <div class="head">
          <div><h2 class="big">{{ cur.code }} {{ cur.name }}</h2>
            <span class="muted small">主题 wq/gearbox/{{ area }}/{{ unit }}/status</span></div>
          <span class="state" :style="{ color: STATE[cur.state].color, background: STATE[cur.state].bg }">{{ STATE[cur.state].label }}</span>
        </div>
        <div v-if="['down', 'fault'].includes(cur.state)" class="downbox">
          <b>{{ cur.locked ? '🔒 ' : '' }}{{ cur.reason || '停机' }}</b>：已停 {{ Math.round((cur.down_for_s || 0) / 60) }} 分钟，预计还要 {{ Math.round((cur.down_until_s || 0) / 60) }} 分钟（工厂时间），排队 {{ cur.queue }} 件。
          <button class="btn danger" @click="cmd('reset')">处理完毕，复位</button>
        </div>
        <div class="now" data-help="op-now">
          <div><span class="muted small">当前工单</span><b class="mono"><ObjLink v-if="cur.work_order" type="WorkOrder" :k="cur.work_order" /><template v-else>—</template></b></div>
          <div><span class="muted small">工序</span><b>{{ cur.operation ? cur.operation.split(' ')[0] : '—' }}</b></div>
          <div><span class="muted small">零件</span><b class="mono"><ObjLink v-if="cur.part_serial && !/件在炉/.test(cur.part_serial)" type="PartSerial" :k="cur.part_serial" /><template v-else>{{ cur.part_serial || '—' }}</template></b></div>
          <div><span class="muted small">完成</span><b class="mono">{{ cur.qty_done || 0 }} / {{ cur.qty || 0 }}</b></div>
          <div><span class="muted small">主轴</span><b class="mono">{{ cur.spindle_rpm || 0 }} r/min</b></div>
          <div><span class="muted small">待加工</span><b class="mono">{{ cur.queue || 0 }} 件</b></div>
        </div>
        <div class="progress"><span class="muted small">本件进度</span>
          <div class="bar big"><div :style="{ width: Math.round((cur.progress || 0) * 100) + '%', background: STATE[cur.state].color }"></div></div></div>
        <div class="progress"><span class="muted small">刀具（砂轮）剩余寿命 {{ Math.round((cur.tool_life_left ?? 1) * 100) }}%</span>
          <div class="bar"><div :style="{ width: Math.round((cur.tool_life_left ?? 1) * 100) + '%', background: (cur.tool_life_left ?? 1) < 0.15 ? 'var(--bad)' : 'var(--good)' }"></div></div></div>

        <h3 data-help="op-jobs">派到本工位的工序</h3>
        <div v-if="!(cur.dispatched || []).length" class="empty">这台设备还没有派工，所以没有“开工”按钮。先到
          <router-link to="/work/planner">订单与计划</router-link> 下达工单（或请计划员下达），这里就会出现要做的工序。</div>
        <div v-for="j in cur.dispatched || []" :key="j.work_order + j.operation" class="job">
          <div class="jinfo"><b class="mono"><ObjLink type="WorkOrder" :k="j.work_order" /></b> {{ j.operation }}<span class="muted small"> · {{ j.done }} / {{ j.qty }} 件</span></div>
          <span class="pill" :class="j.started ? 'good' : 'warn'">{{ j.started ? '已开工' : '待开工' }}</span>
          <button v-if="!j.started" class="btn primary big" @click="cmd('start', j)">开工</button>
          <button v-else class="btn ghost big" @click="cmd('pause', j)">暂停</button>
        </div>
        <div v-if="msg" :class="msgOk ? 'ok' : 'err'">{{ msg }}</div>
      </section>
      <section class="card side">
        <div class="card-head"><h2>最近事件</h2><span class="muted small">event · cmd/ack</span></div>
        <div v-for="e in events" :key="e.id" class="ev small">
          <span class="mono muted">{{ timeOf(e.ts).slice(-5) }}</span>
          <span>{{ evText(e) }}</span>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post, session } from '../lib/api';
import { onBus } from '../lib/bus';
import { useOverview } from '../lib/overview';
import { STATE, timeOf } from '../lib/fmt';
import TaskBar from '../components/TaskBar.vue';
import ObjLink from '../components/ObjLink.vue';
import BusNotice from '../components/BusNotice.vue';

const route = useRoute();
const router = useRouter();
const { machines } = useOverview(3000);
const unit = ref(route.query.unit || 'saw-01');
const events = ref([]);
const msg = ref('');
const msgOk = ref(true);
const teachStatus = ref(null);
const cur = computed(() => machines.value.find((m) => m.unit === unit.value));
// 没指定工位时，先打开有派工或正在运行的设备（第 6 轮 W7）
let autoPicked = !!route.query.unit;
watch(machines, (ms) => {
  if (autoPicked || !ms.length) return;
  autoPicked = true;
  const busy = ms.find((m) => (m.dispatched || []).length) || ms.find((m) => m.state === 'run');
  if (busy && busy.unit !== unit.value) { unit.value = busy.unit; loadEvents(); }
});
const area = computed(() => (unit.value === 'qc-01' ? 'quality' : 'machining'));
function pick(u) { unit.value = u; router.replace({ query: { unit: u } }); loadEvents(); }
async function loadEvents() {
  const h = await get(`/machine/${unit.value}`);
  events.value = h.events.slice(0, 25);
}
function evText(e) {
  const d = e.data;
  const op = (d.operation || '').split(' ')[0];
  return { cycle_start: `开始 ${d.part_serial} ${op}`, cycle_end: `完成 ${d.part_serial} ${op}，用时 ${Math.round(d.cycle_time_s / 60 * 10) / 10} 分钟`,
    op_complete: `工序完工 ${d.work_order} ${op}：合格 ${d.qty_good}/${d.qty}`, tool_change: d.message,
    alarm: '报警：' + d.message, fault: '故障：' + d.message, recover: '恢复：' + d.message }[d.event] || d.event;
}
async function cmd(command, j) {
  msg.value = '';
  try {
    await post('/mes/cmd', { unit: unit.value, command, work_order: j?.work_order, operation: j?.operation });
    msgOk.value = true;
    msg.value = { start: '开工指令已发出', pause: '暂停指令已发出：当前件做完后暂停', reset: '复位指令已发出' }[command];
  } catch (e) { msgOk.value = false; msg.value = e.message; }
}
let off;
onMounted(async () => {
  loadEvents();
  off = onBus((topic, m) => {
    if (topic.split('/')[3] !== unit.value) return;
    if (m.type === 'machine.ack') { msgOk.value = m.data.accepted; msg.value = '设备应答：' + m.data.reason; }
    if (m.type === 'machine.event') events.value = [{ id: m.id, ts: m.ts, data: m.data }, ...events.value].slice(0, 25);
  });
  if (session.user.mode === 'teach') teachStatus.value = await get('/teach');
});
onUnmounted(() => off && off());
</script>

<style scoped>
.tabs { display: flex; gap: 6px; flex-wrap: wrap; }
.tabs button { height: 36px; padding: 0 12px; border-radius: 8px; border: 1px solid var(--line); background: #fff; cursor: pointer;
  font-family: var(--mono); display: flex; align-items: center; gap: 6px; }
.tabs button.on { border-color: var(--accent); background: var(--accent-bg); font-weight: 600; }
.tabs i { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.grow { flex-grow: 1; min-width: 0; }
.side { width: 360px; flex-shrink: 0; max-height: 640px; overflow-y: auto; }
.head { display: flex; justify-content: space-between; align-items: flex-start; }
.big { font-size: 20px; }
.state { font-size: 18px; font-weight: 700; padding: 6px 16px; border-radius: 8px; }
.downbox { margin-top: 12px; background: var(--bad-bg); color: var(--bad); border-radius: 8px; padding: 12px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.now { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin: 16px 0; }
.now div { display: flex; flex-direction: column; gap: 3px; }
.now b { font-size: 16px; }
.progress { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
.bar.big { height: 12px; border-radius: 6px; }
h3 { font-size: 14px; margin: 16px 0 8px; }
.job { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-top: 1px solid var(--line-soft); }
.jinfo { flex-grow: 1; }
.ev { display: flex; gap: 8px; padding: 5px 0; border-top: 1px solid var(--line-soft); }
@media (max-width: 1100px) { .now { grid-template-columns: repeat(3, 1fr); } .side { width: auto; } }
</style>
