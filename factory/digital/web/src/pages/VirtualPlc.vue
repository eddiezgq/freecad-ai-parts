<template>
  <div class="page">
    <div class="page-title"><h1 class="nowrap">虚拟 PLC</h1>
      <span class="muted">学生写的 PLC 程序在这里控制车间里的设备跑一个班次：程序经工程任务单批准后自动下载，老师也可以上传程序试跑。产量、合格率、节拍、报警和停机都记下来，供学生复盘。</span></div>

    <div v-if="err" class="err">{{ err }}</div>
    <div class="units">
      <section v-for="u in data?.units || []" :key="u.unit" class="card unit">
        <div class="card-head"><h2>{{ u.name }}</h2><span class="mono small muted">{{ u.unit.toUpperCase() }}</span>
          <span v-if="u.current" class="pill" :class="TONE[u.current.status]">{{ STATUS[u.current.status] }}</span>
          <span v-if="u.current?.status === 'running'" class="pill" :class="STATE_TONE[u.current.live.state]">{{ STATE[u.current.live.state] || '—' }}</span></div>
        <template v-if="u.current">
          <div class="small muted">{{ u.current.title || u.current.id }} · {{ ORIGIN[u.current.origin] }} · 班次 {{ u.current.hours }} 小时</div>
          <div class="bar"><div :style="{ width: pct(progress(u.current)), background: u.current.status === 'failed' ? 'var(--bad)' : 'var(--good)' }"></div></div>
          <div class="nums">
            <div><span class="small muted">产量</span><b>{{ count(u.current).n }}</b></div>
            <div><span class="small muted">合格</span><b>{{ count(u.current).good }}</b></div>
            <div><span class="small muted">不合格</span><b :class="{ bad: count(u.current).nok }">{{ count(u.current).nok }}</b></div>
            <div><span class="small muted">合格率</span><b>{{ count(u.current).n ? pct(count(u.current).good / count(u.current).n, 1) : '—' }}</b></div>
            <div><span class="small muted">{{ u.current.summary ? '平均节拍' : '最近节拍' }}</span><b>{{ cyc(u.current) }}</b></div>
            <div><span class="small muted">报警</span><b :class="{ bad: u.current.alarms.length }">{{ u.current.alarms.length }}</b></div>
          </div>
          <div v-if="u.current.error" class="err small">{{ u.current.error }}</div>
        </template>
        <div v-else class="empty">还没有跑过程序。</div>
        <div v-if="data.teacher" class="trial">
          <template v-if="trial.unit !== u.unit"><button class="btn small-btn" type="button" @click="openTrial(u)">试跑一个班次</button></template>
          <template v-else>
            <label class="small"><input v-model="trial.src" type="radio" value="example"> 参考程序（{{ u.example }}）</label>
            <label class="small"><input v-model="trial.src" type="radio" value="file"> 上传程序（.st 或 PLCopen XML）
              <input v-if="trial.src === 'file'" type="file" accept=".st,.xml,.txt" @change="(e) => (trial.file = e.target.files[0])"></label>
            <label class="small">班次 <select v-model.number="trial.hours"><option :value="8">8 小时</option><option :value="1">1 小时</option><option :value="0.5">半小时</option></select></label>
            <div class="line"><button class="btn primary small-btn" type="button" :disabled="busy || (trial.src === 'file' && !trial.file)" @click="start">下载并运行</button>
              <button class="btn ghost small-btn" type="button" @click="trial.unit = ''">取消</button></div>
            <div class="small muted">同一台设备上正在跑的班次会被停下，换成这个程序。车间按 {{ speedNote }} 回放，8 小时的班次约 {{ Math.round(8 * 60 / (data.speed || 20)) }} 分钟跑完。</div>
          </template>
        </div>
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>班次记录</h2><span class="small muted">点一行看详情</span></div>
      <div v-if="!data?.runs?.length" class="empty">还没有班次。</div>
      <table v-else class="t">
        <thead><tr><th>班次</th><th>设备</th><th>程序</th><th>来源</th><th>状态</th><th class="num">产量</th><th class="num">合格率</th><th class="num">平均节拍</th><th class="num">报警</th><th class="num">停机</th><th>OpenPLC</th><th>开始</th></tr></thead>
        <tbody><tr v-for="r in data.runs" :key="r.id" class="click" :class="{ on: sel?.id === r.id }" @click="open(r.id)">
          <td class="mono">{{ r.id }}</td><td>{{ unitName(r.unit) }}</td><td class="small">{{ r.title }}</td><td class="small">{{ ORIGIN[r.origin] }}</td>
          <td><span class="pill" :class="TONE[r.status]">{{ STATUS[r.status] }}</span></td>
          <td class="num">{{ count(r).n }}</td><td class="num">{{ count(r).n ? pct(count(r).good / count(r).n, 1) : '—' }}</td>
          <td class="num">{{ cyc(r) }}</td><td class="num">{{ r.alarms.length }}</td>
          <td class="num">{{ r.summary ? r.summary.downtime_min + ' 分' : '—' }}</td>
          <td><span class="pill" :class="compatTone(r)">{{ compatText(r) }}</span></td><td class="small">{{ timeOf(r.started_at || r.created_at) }}</td></tr></tbody>
      </table>
    </section>

    <section v-if="sel" class="card">
      <div class="card-head"><h2 class="mono">{{ sel.id }}</h2><span>{{ unitName(sel.unit) }} · {{ sel.title }}</span>
        <span class="pill" :class="TONE[sel.status]">{{ STATUS[sel.status] }}</span><button class="btn ghost small-btn more" type="button" @click="sel = null">关闭</button></div>
      <div v-if="sel.summary" class="two">
        <table class="t small"><tbody>
          <tr><td>班次时长</td><td class="num">{{ sel.summary.hours }} 小时</td></tr>
          <tr><td>产量 / 合格 / 不合格</td><td class="num">{{ sel.summary.parts }} / {{ sel.summary.good }} / {{ sel.summary.nok }}</td></tr>
          <tr><td>合格率</td><td class="num">{{ sel.summary.yield == null ? '—' : pct(sel.summary.yield, 1) }}</td></tr>
          <tr><td>平均节拍（中位数）</td><td class="num">{{ sel.summary.cycle_mean_s ?? '—' }} s（{{ sel.summary.cycle_median_s ?? '—' }} s）</td></tr>
          <tr><td>报警次数</td><td class="num">{{ sel.summary.alarms }}</td></tr>
          <tr><td>停机时间</td><td class="num">{{ sel.summary.downtime_min }} 分钟</td></tr>
          <tr><td>停线（程序不动作超过 10 分钟）</td><td class="num" :class="{ bad: sel.summary.stalls }">{{ sel.summary.stalls }} 次</td></tr>
          <tr><td>危险动作</td><td class="num" :class="{ bad: sel.summary.hazards }">{{ sel.summary.hazards }} 次</td></tr>
          <tr><td>扫描次数</td><td class="num">{{ sel.summary.scans?.toLocaleString() }}</td></tr>
          <tr v-if="sel.summary.plc_error"><td>PLC 停机</td><td class="bad">{{ sel.summary.plc_error }}</td></tr>
        </tbody></table>
        <div>
          <h3>本班发生的设备故障（维修工修好的时间）</h3>
          <ul class="small"><li v-for="(b, i) in sel.summary.breakdowns" :key="i">{{ FAULT[b.fault] || b.fault }}：第 {{ b.at_min }} 分钟起，{{ b.repair_min }} 分钟后修好</li>
            <li v-if="!sel.summary.breakdowns?.length" class="muted">没有</li></ul>
          <p class="small muted">好的程序在设备出故障时报警、停在安全状态，修好后复位就能接着生产；不处理故障的程序会一直等下去（停线）。</p>
        </div>
      </div>
      <h3>OpenPLC 兼容性检查</h3>
      <p class="small muted">同一个程序交给开源软 PLC——OpenPLC 运行时（MatIEC 编译器）编译，并按真实时间控制同一台虚拟设备 90 秒：编译得过、设备照样能生产，说明程序是标准的 IEC 61131-3，换到真的 PLC 上也能用。</p>
      <div v-if="!sel.compat" class="empty">{{ ['queued', 'running'].includes(sel.status) ? '正在检查（约 2–3 分钟）…' : '这个班次没有做兼容性检查。' }}</div>
      <template v-else>
        <p><span class="pill" :class="compatTone(sel)">{{ compatText(sel) }}</span>
          <span v-if="sel.compat.summary" class="small">　90 秒内生产 {{ sel.compat.summary.parts }} 件（合格 {{ sel.compat.summary.good }}），报警 {{ (sel.compat.alarms || []).length }} 次{{ (sel.compat.alarms || []).length ? "（" + sel.compat.alarms.join("、") + "；开机头几十毫秒远程 I/O 还没读进来，急停输入为 0，程序会先进急停状态，复位后正常）" : "" }}，危险动作 {{ sel.compat.summary.hazards }} 次；Modbus 轮询 {{ sel.compat.polls }} 次</span></p>
        <pre v-if="!sel.compat.ok" class="prog">{{ sel.compat.log }}</pre>
        <details v-if="sel.compat.program"><summary class="small">交给 OpenPLC 的程序（编译错误的行号按这个算）</summary><pre class="prog">{{ sel.compat.program }}</pre></details>
      </template>
      <h3>报警</h3>
      <div v-if="!sel.alarms.length" class="empty">没有报警。</div>
      <table v-else class="t small"><thead><tr><th>班次内时刻</th><th>代码</th><th>内容</th></tr></thead>
        <tbody><tr v-for="(a, i) in sel.alarms" :key="i"><td class="mono">{{ hms(a.t_s) }}</td><td class="mono">{{ a.code }}</td><td>{{ a.message }}</td></tr></tbody></table>
      <div v-if="sel.review?.length" class="small"><h3>程序检查</h3>
        <ul><li v-for="(r, i) in sel.review.filter((x) => x.level !== 'info')" :key="i" :class="r.level === 'error' ? 'bad' : ''">{{ r.line ? '第 ' + r.line + ' 行：' : '' }}{{ r.msg[0] }}</li></ul></div>
      <details v-if="sel.program"><summary class="small">程序（ST）</summary><pre class="prog">{{ sel.program }}</pre></details>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { get } from '../lib/api';
import { timeOf } from '../lib/fmt';
import { upload } from '../lib/tasks';

const STATUS = { queued: '排队', running: '运行中', done: '班次完成', failed: '失败', cancelled: '已停止' };
const TONE = { queued: 'mute', running: 'info', done: 'good', failed: 'bad', cancelled: 'mute' };
const STATE = { run: '运行', idle: '等待', fault: '故障', down: '设备停机' };
const STATE_TONE = { run: 'good', idle: 'mute', fault: 'bad', down: 'warn' };
const ORIGIN = { manual: '老师试跑', task: '任务单批准' };
const FAULT = { clampWire: '夹紧到位传感器断线', upStuck: '压头上位开关粘连', y2stuck: '推杆 2 卡住', colorDirty: '颜色传感器脏', tight: '过盈太大', loose: '过盈太小' };
const data = ref(null);
const sel = ref(null);
const err = ref('');
const busy = ref(false);
const trial = reactive({ unit: '', src: 'example', file: null, hours: 8 });
const speedNote = computed(() => `${data.value?.speed || 20} 倍速`);
let timer;

const pct = (x, d = 0) => (x == null ? '—' : (x * 100).toFixed(d) + '%');
const progress = (r) => (r.status === 'done' ? 1 : r.live?.progress || 0);
const count = (r) => (r.summary ? { n: r.summary.parts, good: r.summary.good, nok: r.summary.nok } : { n: r.live?.n || 0, good: r.live?.good_n || 0, nok: r.live?.nok_n || 0 });
const cyc = (r) => { const v = r.summary ? r.summary.cycle_mean_s : r.live?.cycle_s; return v == null ? '—' : v + ' s'; };
const compatText = (r) => { const c = r.compat; if (!c) return ['queued', 'running'].includes(r.status) ? '检查中' : '—';
  return c.ok ? '通过' : { compile: '编译不过', prepare: '程序不合要求', run: '运行出错' }[c.stage] || '没做成'; };
const compatTone = (r) => (!r.compat ? 'mute' : r.compat.ok ? 'good' : r.compat.stage === 'error' ? 'warn' : 'bad');
const unitName = (u) => (data.value?.units || []).find((x) => x.unit === u)?.name || u;
const hms = (s) => { if (s == null) return '—'; const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = Math.floor(s % 60); return `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}`; };

async function load() {
  try { data.value = await get('/plc'); err.value = ''; } catch (e) { err.value = e.message; }
  if (sel.value && ['queued', 'running'].includes(sel.value.status)) open(sel.value.id);
}
async function open(id) {
  try { sel.value = await get('/plc/runs/' + id); } catch (e) { err.value = e.message; }
}
function openTrial(u) { Object.assign(trial, { unit: u.unit, src: 'example', file: null, hours: 8 }); }
async function start() {
  busy.value = true;
  try {
    const f = { unit: trial.unit, hours: trial.hours };
    if (trial.src === 'example') f.example = '1'; else f.file = trial.file;
    const r = await upload('/plc/runs', f);
    trial.unit = '';
    await load();
    open(r.id);
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
onMounted(() => { load(); timer = setInterval(load, 5000); });
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.units { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 16px; }
.unit { display: flex; flex-direction: column; gap: 8px; }
.nums { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; }
.nums div { display: flex; flex-direction: column; }
.nums b { font-size: 18px; }
.bad { color: var(--bad); }
.trial { display: flex; flex-direction: column; gap: 6px; border-top: 1px solid var(--line); padding-top: 8px; }
.line { display: flex; gap: 8px; }
.small-btn { height: 28px; font-size: 12px; }
.click { cursor: pointer; }
.click:hover, .click.on { background: var(--surface-2); }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.prog { font-family: var(--mono); font-size: 12px; background: var(--surface-2); padding: 10px; border-radius: 6px; max-height: 420px; overflow: auto; white-space: pre; }
h3 { font-size: 14px; margin: 12px 0 6px; }
.nowrap { white-space: nowrap; }
@media (max-width: 800px) { .two { grid-template-columns: 1fr; } .nums { grid-template-columns: repeat(3, 1fr); } }
</style>
