<template>
  <div class="page">
    <div class="page-title"><h1 class="nowrap">{{ $t('虚拟 PLC') }}</h1>
      <span class="muted">{{ $t('学生写的 PLC 程序在这里控制车间里的设备跑一个班次：程序经工程任务单批准后自动下载，老师也可以上传程序试跑。产量、合格率、节拍、报警和停机都记下来，供学生复盘。') }}</span></div>

    <div v-if="err" class="err">{{ err }}</div>
    <div class="units">
      <section v-for="u in data?.units || []" :key="u.unit" class="card unit">
        <div class="card-head"><h2>{{ $td(u.name) }}</h2><span class="mono small muted">{{ u.unit.toUpperCase() }}</span>
          <span v-if="u.current" class="pill" :class="TONE[u.current.status]">{{ $td(STATUS[u.current.status]) }}</span>
          <span v-if="u.current?.status === 'running'" class="pill" :class="STATE_TONE[u.current.live.state]">{{ STATE[u.current.live.state] || '—' }}</span></div>
        <template v-if="u.current">
          <div class="small muted">{{ $t('{a} · {b} · 班次 {c} 小时', { a: u.current.title || u.current.id, b: ORIGIN[u.current.origin], c: u.current.hours }) }}</div>
          <div class="bar"><div :style="{ width: pct(progress(u.current)), background: u.current.status === 'failed' ? 'var(--bad)' : 'var(--good)' }"></div></div>
          <div class="nums">
            <div><span class="small muted">{{ $t('产量') }}</span><b>{{ count(u.current).n }}</b></div>
            <div><span class="small muted">{{ $t('合格') }}</span><b>{{ count(u.current).good }}</b></div>
            <div><span class="small muted">{{ $t('不合格') }}</span><b :class="{ bad: count(u.current).nok }">{{ count(u.current).nok }}</b></div>
            <div><span class="small muted">{{ $t('合格率') }}</span><b>{{ count(u.current).n ? pct(count(u.current).good / count(u.current).n, 1) : '—' }}</b></div>
            <div><span class="small muted">{{ u.current.summary ? $t('平均节拍') : $t('最近节拍') }}</span><b>{{ cyc(u.current) }}</b></div>
            <div><span class="small muted">{{ $t('报警') }}</span><b :class="{ bad: u.current.alarms.length }">{{ $td(u.current.alarms.length) }}</b></div>
          </div>
          <div v-if="u.current.error" class="err small">{{ $td(u.current.error) }}</div>
        </template>
        <div v-else class="empty">{{ $t('还没有跑过程序。') }}</div>
        <div v-if="data.teacher" class="trial">
          <template v-if="trial.unit !== u.unit"><button class="btn small-btn" type="button" @click="openTrial(u)">{{ $t('试跑一个班次') }}</button></template>
          <template v-else>
            <label class="small"><input v-model="trial.src" type="radio" value="example"> {{ $t('参考程序（{a}）', { a: u.example }) }}</label>
            <label class="small"><input v-model="trial.src" type="radio" value="file"> {{ $t('上传程序（.st 或 PLCopen XML）') }}
              <input v-if="trial.src === 'file'" type="file" accept=".st,.xml,.txt" @change="(e) => (trial.file = e.target.files[0])"></label>
            <label class="small">{{ $t('班次') }} <select v-model.number="trial.hours"><option :value="8">{{ $t('8 小时') }}</option><option :value="1">{{ $t('1 小时') }}</option><option :value="0.5">{{ $t('半小时') }}</option></select></label>
            <div class="line"><button class="btn primary small-btn" type="button" :disabled="busy || (trial.src === 'file' && !trial.file)" @click="start">{{ $t('下载并运行') }}</button>
              <button class="btn ghost small-btn" type="button" @click="trial.unit = ''">{{ $t('取消') }}</button></div>
            <div class="small muted">{{ $t('同一台设备上正在跑的班次会被停下，换成这个程序。车间按 {a} 回放，8 小时的班次约 {b} 分钟跑完。', { a: speedNote, b: Math.round(8 * 60 / (data.speed || 20)) }) }}</div>
          </template>
        </div>
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>{{ $t('班次记录') }}</h2><span class="small muted">{{ $t('点一行看详情') }}</span></div>
      <div v-if="!data?.runs?.length" class="empty">{{ $t('还没有班次。') }}</div>
      <table v-else class="t">
        <thead><tr><th>{{ $t('班次') }}</th><th>{{ $t('设备') }}</th><th>{{ $t('程序') }}</th><th>{{ $t('来源') }}</th><th>{{ $t('状态') }}</th><th class="num">{{ $t('产量') }}</th><th class="num">{{ $t('合格率') }}</th><th class="num">{{ $t('平均节拍') }}</th><th class="num">{{ $t('报警') }}</th><th class="num">{{ $t('停机') }}</th><th>OpenPLC</th><th>{{ $t('开始') }}</th></tr></thead>
        <tbody><tr v-for="r in data.runs" :key="r.id" class="click" :class="{ on: sel?.id === r.id }" @click="open(r.id)">
          <td class="mono">{{ $td(r.id) }}</td><td>{{ unitName(r.unit) }}</td><td class="small">{{ $td(r.title) }}</td><td class="small">{{ $td(ORIGIN[r.origin]) }}</td>
          <td><span class="pill" :class="TONE[r.status]">{{ $td(STATUS[r.status]) }}</span></td>
          <td class="num">{{ count(r).n }}</td><td class="num">{{ count(r).n ? pct(count(r).good / count(r).n, 1) : '—' }}</td>
          <td class="num">{{ cyc(r) }}</td><td class="num">{{ $td(r.alarms.length) }}</td>
          <td class="num">{{ r.summary ? r.summary.downtime_min + $t(' 分') : '—' }}</td>
          <td><span class="pill" :class="compatTone(r)">{{ compatText(r) }}</span></td><td class="small">{{ timeOf(r.started_at || r.created_at) }}</td></tr></tbody>
      </table>
    </section>

    <section v-if="sel" class="card">
      <div class="card-head"><h2 class="mono">{{ $td(sel.id) }}</h2><span>{{ unitName(sel.unit) }} · {{ $td(sel.title) }}</span>
        <span class="pill" :class="TONE[sel.status]">{{ $td(STATUS[sel.status]) }}</span><button class="btn ghost small-btn more" type="button" @click="sel = null">{{ $t('关闭') }}</button></div>
      <div v-if="sel.summary" class="two">
        <table class="t small"><tbody>
          <tr><td>{{ $t('班次时长') }}</td><td class="num">{{ $t('{a} 小时', { a: sel.summary.hours }) }}</td></tr>
          <tr><td>{{ $t('产量 / 合格 / 不合格') }}</td><td class="num">{{ $td(sel.summary.parts) }} / {{ $td(sel.summary.good) }} / {{ $td(sel.summary.nok) }}</td></tr>
          <tr><td>{{ $t('合格率') }}</td><td class="num">{{ sel.summary.yield == null ? '—' : pct(sel.summary.yield, 1) }}</td></tr>
          <tr><td>{{ $t('平均节拍（中位数）') }}</td><td class="num">{{ $t('{a} s（{b} s）', { a: sel.summary.cycle_mean_s ?? '—', b: sel.summary.cycle_median_s ?? '—' }) }}</td></tr>
          <tr><td>{{ $t('报警次数') }}</td><td class="num">{{ $td(sel.summary.alarms) }}</td></tr>
          <tr><td>{{ $t('停机时间') }}</td><td class="num">{{ $t('{a} 分钟', { a: sel.summary.downtime_min }) }}</td></tr>
          <tr><td>{{ $t('停线（程序不动作超过 10 分钟）') }}</td><td class="num" :class="{ bad: sel.summary.stalls }">{{ $t('{a} 次', { a: sel.summary.stalls }) }}</td></tr>
          <tr><td>{{ $t('危险动作') }}</td><td class="num" :class="{ bad: sel.summary.hazards }">{{ $t('{a} 次', { a: sel.summary.hazards }) }}</td></tr>
          <tr><td>{{ $t('扫描次数') }}</td><td class="num">{{ sel.summary.scans?.toLocaleString() }}</td></tr>
          <tr v-if="sel.summary.plc_error"><td>{{ $t('PLC 停机') }}</td><td class="bad">{{ $td(sel.summary.plc_error) }}</td></tr>
        </tbody></table>
        <div>
          <h3>{{ $t('本班发生的设备故障（维修工修好的时间）') }}</h3>
          <ul class="small"><li v-for="(b, i) in sel.summary.breakdowns" :key="i">{{ $t('{a}：第 {b} 分钟起，{c} 分钟后修好', { a: FAULT[b.fault] || b.fault, b: b.at_min, c: b.repair_min }) }}</li>
            <li v-if="!sel.summary.breakdowns?.length" class="muted">{{ $t('没有') }}</li></ul>
          <p class="small muted">{{ $t('好的程序在设备出故障时报警、停在安全状态，修好后复位就能接着生产；不处理故障的程序会一直等下去（停线）。') }}</p>
        </div>
      </div>
      <h3>{{ $t('OpenPLC 兼容性检查') }}</h3>
      <p class="small muted">{{ $t('同一个程序交给开源软 PLC——OpenPLC 运行时（MatIEC 编译器）编译，并按真实时间控制同一台虚拟设备 90 秒：编译得过、设备照样能生产，说明程序是标准的 IEC 61131-3，换到真的 PLC 上也能用。') }}</p>
      <div v-if="!sel.compat" class="empty">{{ ['queued', 'running'].includes(sel.status) ? $t('正在检查（约 2–3 分钟）…') : $t('这个班次没有做兼容性检查。') }}</div>
      <template v-else>
        <p><span class="pill" :class="compatTone(sel)">{{ compatText(sel) }}</span>
          <span v-if="sel.compat.summary" class="small"> · {{ $t('90 秒内生产 {a} 件（合格 {b}），报警 {c} 次{d}，危险动作 {e} 次；Modbus 轮询 {f} 次', { a: sel.compat.summary.parts, b: sel.compat.summary.good, c: (sel.compat.alarms || []).length, d: (sel.compat.alarms || []).length ? $t('（{a}；开机头几十毫秒远程 I/O 还没读进来，急停输入为 0，程序会先进急停状态，复位后正常）', { a: sel.compat.alarms.map((x) => $td(x)).join($t('、')) }) : '', e: sel.compat.summary.hazards, f: sel.compat.polls }) }}</span></p>
        <pre v-if="!sel.compat.ok" class="prog">{{ $td(sel.compat.log) }}</pre>
        <details v-if="sel.compat.program"><summary class="small">{{ $t('交给 OpenPLC 的程序（编译错误的行号按这个算）') }}</summary><pre class="prog">{{ $td(sel.compat.program) }}</pre></details>
      </template>
      <h3>{{ $t('报警') }}</h3>
      <div v-if="!sel.alarms.length" class="empty">{{ $t('没有报警。') }}</div>
      <table v-else class="t small"><thead><tr><th>{{ $t('班次内时刻') }}</th><th>{{ $t('代码') }}</th><th>{{ $t('内容') }}</th></tr></thead>
        <tbody><tr v-for="(a, i) in sel.alarms" :key="i"><td class="mono">{{ hms(a.t_s) }}</td><td class="mono">{{ $td(a.code) }}</td><td>{{ $td(a.message) }}</td></tr></tbody></table>
      <div v-if="sel.review?.length" class="small"><h3>{{ $t('程序检查') }}</h3>
        <ul><li v-for="(r, i) in sel.review.filter((x) => x.level !== 'info')" :key="i" :class="r.level === 'error' ? 'bad' : ''">{{ r.line ? $t('第 ') + r.line + $t(' 行：') : '' }}{{ $td(r.msg[0]) }}</li></ul></div>
      <details v-if="sel.program"><summary class="small">{{ $t('程序（ST）') }}</summary><pre class="prog">{{ $td(sel.program) }}</pre></details>
    </section>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { get } from '../lib/api';
import { timeOf } from '../lib/fmt';
import { upload } from '../lib/tasks';

const STATUS = { queued: $t('排队'), running: $t('运行中'), done: $t('班次完成'), failed: $t('失败'), cancelled: $t('已停止') };
const TONE = { queued: 'mute', running: 'info', done: 'good', failed: 'bad', cancelled: 'mute' };
const STATE = { run: $t('运行'), idle: $t('等待'), fault: $t('故障'), down: $t('设备停机') };
const STATE_TONE = { run: 'good', idle: 'mute', fault: 'bad', down: 'warn' };
const ORIGIN = { manual: $t('老师试跑'), task: $t('任务单批准') };
const FAULT = { clampWire: $t('夹紧到位传感器断线'), upStuck: $t('压头上位开关粘连'), y2stuck: $t('推杆 2 卡住'), colorDirty: $t('颜色传感器脏'), tight: $t('过盈太大'), loose: $t('过盈太小') };
const data = ref(null);
const sel = ref(null);
const err = ref('');
const busy = ref(false);
const trial = reactive({ unit: '', src: 'example', file: null, hours: 8 });
const speedNote = computed(() => $t('{a} 倍速', { a: data.value?.speed || 20 }));
let timer;

const pct = (x, d = 0) => (x == null ? '—' : (x * 100).toFixed(d) + '%');
const progress = (r) => (r.status === 'done' ? 1 : r.live?.progress || 0);
const count = (r) => (r.summary ? { n: r.summary.parts, good: r.summary.good, nok: r.summary.nok } : { n: r.live?.n || 0, good: r.live?.good_n || 0, nok: r.live?.nok_n || 0 });
const cyc = (r) => { const v = r.summary ? r.summary.cycle_mean_s : r.live?.cycle_s; return v == null ? '—' : v + ' s'; };
const compatText = (r) => { const c = r.compat; if (!c) return ['queued', 'running'].includes(r.status) ? $t('检查中') : '—';
  return c.ok ? $t('通过') : { compile: $t('编译不过'), prepare: $t('程序不合要求'), run: $t('运行出错') }[c.stage] || $t('没做成'); };
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
