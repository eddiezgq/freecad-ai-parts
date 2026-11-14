<!-- 第 167 轮：软件公司的发布流水线与服务监控。两页合一，上面切换：
     发布流水线——每个版本：在哪台构建服务器编译与单元测试、多少用例失败、硬件在环的中断延迟分布或长稳压测的内存曲线；按构建服务器 / 测试台分开看；
     服务监控——每份订阅开通后 24 小时的延迟与错误率曲线；按宿主机 / 可用区分开看。帮学生从“只在一台机器上出问题”追到原因。 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('发布流水线与服务监控') }}</h1>
      <span class="muted">{{ $t('每个版本的测试、中断延迟、内存曲线；每份订阅 24 小时的延迟与错误率——按机器分开看，找出问题从哪来') }}</span></div>
    <div class="tabs">
      <button :class="{ on: tab === 'build' }" @click="tab = 'build'">{{ $t('发布流水线') }}</button>
      <button :class="{ on: tab === 'svc' }" @click="tab = 'svc'">{{ $t('服务监控') }}</button>
    </div>
    <div v-if="err" class="err">{{ err }}</div>

    <div v-if="tab === 'build'" class="cols">
      <section class="card list">
        <div class="card-head"><h2>{{ $t('最近的版本（{a} 个）', { a: $td(bShown.length) }) }}</h2></div>
        <div class="small">
          <label>{{ $t('产品') }}
            <select v-model="bItem"><option value="">{{ $t('全部') }}</option><option v-for="s in bItems" :key="s" :value="s">{{ $td(s) }}</option></select>
          </label>
          <label> · {{ $t('构建服务器') }}
            <select v-model="runner"><option value="">{{ $t('全部') }}</option><option v-for="s in runners" :key="s" :value="s">{{ s }}</option></select>
          </label>
        </div>
        <div v-if="runners.length > 1" class="small muted">{{ $t('测试通过率（按构建服务器）：') }}<span v-for="s in runners" :key="s" class="mono">{{ s }} {{ avgBy(builds, 'runner', s, 'sw_pass', 3) }} % · </span></div>
        <div v-if="benches.length > 1" class="small muted">{{ $t('中断延迟离上限的余量（按测试台）：') }}<span v-for="s in benches" :key="s" class="mono">{{ s }} {{ marginBy(s) }} μs · </span></div>
        <div v-if="!builds.length" class="small muted">{{ $t('还没有。接一张版本订单（实时 OS、OS、云平台……），让流水线走到“发布门禁”。') }}</div>
        <button v-for="w in bShown" :key="w.serial" class="brd" :class="{ on: bSel === w.serial }" @click="openBuild(w.serial)">
          <span class="mono">{{ $td(w.serial) }}</span>
          <span class="small" :class="w.pass ? 'ok' : 'bad'">{{ w.pass ? $t('合格') : $t('不合格') }}</span>
          <span class="small muted">{{ $t('{a}　构建 {b}{c}', { a: $td(w.item), b: w.runner || '—', c: w.bench ? '　' + $t('测试台 {a}', { a: w.bench }) : '' }) }}</span>
          <span class="small muted">{{ $t('通过率 {a} %', { a: mv(w, 'sw_pass', 3) }) }}{{ w.meas.rtos_irq ? $t('　中断 {a} μs', { a: mv(w, 'rtos_irq', 2) }) : '' }}{{ w.meas.os_leak ? $t('　内存 {a} MB/h', { a: mv(w, 'os_leak', 2) }) : '' }}</span>
        </button>
      </section>
      <section v-if="b" class="card main">
        <div class="card-head"><h2>{{ $td(b.serial) }} · <small class="muted">{{ $t('{a}　工单 {b}　构建服务器 {c}', { a: $td(b.item), b: $td(b.work_order), c: b.runner || '—' }) }}{{ b.bench ? $t('　测试台 {a}', { a: b.bench }) : '' }}</small></h2></div>
        <div class="stages">
          <span v-for="(s, i) in b.stages" :key="s" class="stage" :class="stageCls(i)">{{ $td(s) }}</span>
        </div>
        <div class="kpis">
          <div :class="{ bad: b.pass < b.pass_lo }"><b>{{ b.pass.toFixed(3) }} %</b><span>{{ $t('测试通过率（门禁 ≥ {a}）', { a: b.pass_lo }) }}</span></div>
          <div><b>{{ $td(b.tests) }}</b><span>{{ $t('用例数') }}</span></div>
          <div :class="{ bad: b.fails > 0 }"><b>{{ b.fails }}</b><span>{{ $t('失败用例（其中和时间有关的 {a}）', { a: b.fail_flaky }) }}</span></div>
          <div v-if="b.irq_max" :class="{ bad: irqBad }"><b>{{ b.irq_max.toFixed(2) }} μs</b><span>{{ $t('最坏中断延迟（2 万次）') }}</span></div>
          <div v-if="b.irq_max"><b>{{ b.irq_p999.toFixed(2) }} μs</b><span>{{ $t('99.9 % 分位') }}</span></div>
          <div v-if="b.leak !== undefined" :class="{ bad: b.leak > 5 }"><b>{{ b.leak.toFixed(2) }} MB/h</b><span>{{ $t('内存增长速率（回收后底线）') }}</span></div>
        </div>
        <template v-if="b.hist">
          <h3>{{ $t('中断延迟分布（2 万次，每格 0.25 μs）') }}</h3>
          <svg :viewBox="`0 0 ${W} ${H}`" class="chart" role="img" :aria-label="$t('中断延迟分布')">
            <rect v-for="(n, i) in b.hist" :key="'h' + i" :x="hx(i)" :width="(W - 2 * PAD) / b.hist.length - 1" :y="hy(n)" :height="H - PAD - hy(n)" class="bar" />
            <text v-for="i in [0, 10, 20, 30, 40]" :key="'e' + i" :x="hx(i)" :y="H - 2" class="tk" text-anchor="middle">{{ b.hist_edges[i] }}</text>
            <text :x="PAD + 2" :y="12" class="tk">{{ $t('次数（对数）') }}</text>
          </svg>
          <p class="small">{{ $t('一个版本换台测试台就正常，问题在测试台；所有测试台一起变慢，才是内核的问题。') }}</p>
        </template>
        <template v-if="b.soak_mb">
          <h3>{{ $t('长稳压测内存（MB），点是每次垃圾回收后的底线') }}</h3>
          <svg :viewBox="`0 0 ${W} ${H}`" class="chart" role="img" :aria-label="$t('长稳压测内存曲线')">
            <polyline :points="b.soak_h.map((t, i) => sx(t).toFixed(1) + ',' + sy(b.soak_mb[i]).toFixed(1)).join(' ')" class="ln mem" />
            <circle v-for="(t, i) in b.floor_h" :key="'f' + i" :cx="sx(t)" :cy="sy(b.floor_mb[i])" r="2.5" class="dot" />
            <text v-for="t in hourTicks" :key="'t' + t" :x="sx(t)" :y="H - 2" class="tk" text-anchor="middle">{{ t }} h</text>
            <text :x="PAD + 2" :y="12" class="tk">{{ mLo.toFixed(0) }}–{{ mHi.toFixed(0) }} MB</text>
          </svg>
          <p class="small">{{ $t('锯齿是垃圾回收：涨上去、回收、落回底线。底线不动是正常；底线一直往上走就是泄漏——找第一个变坏的版本，回滚那次提交。加内存、定时重启只是拖延。') }}</p>
        </template>
        <p class="small muted">{{ $t('示例模型：用例数、偶发失败、延迟分布、内存曲线都是示例值。') }}</p>
      </section>
    </div>

    <div v-else class="cols">
      <section class="card list">
        <div class="card-head"><h2>{{ $t('最近的订阅（{a} 份）', { a: $td(sShown.length) }) }}</h2></div>
        <div class="small">
          <label>{{ $t('宿主机') }}
            <select v-model="host"><option value="">{{ $t('全部') }}</option><option v-for="s in hosts" :key="s" :value="s">{{ s }}</option></select>
          </label>
        </div>
        <div v-if="hosts.length > 1" class="small muted">{{ $t('延迟 p99（按宿主机）：') }}<span v-for="s in hosts" :key="s" class="mono">{{ s }} {{ avgBy(svcs, 'host', s, 'cl_p99', 1) }} ms · </span></div>
        <div v-if="hosts.length > 1" class="small muted">{{ $t('错误率（按可用区）：') }}<span v-for="z in zones" :key="z" class="mono">{{ $td(zoneName(z)) }} {{ zoneErr(z) }} % · </span></div>
        <div v-if="!svcs.length" class="small muted">{{ $t('还没有。接一张云平台或数字工厂的订阅订单，开通后验收一天。') }}</div>
        <button v-for="w in sShown" :key="w.serial" class="brd" :class="{ on: sSel === w.serial }" @click="openSvc(w.serial)">
          <span class="mono">{{ $td(w.serial) }}</span>
          <span class="small" :class="w.pass ? 'ok' : 'bad'">{{ w.pass ? $t('合格') : $t('不合格') }}</span>
          <span class="small muted">{{ $t('{a}　宿主机 {b}', { a: $td(w.item), b: w.host || '—' }) }}</span>
          <span class="small muted">{{ $t('延迟 {a} ms　错误 {b} %', { a: mv(w, 'cl_p99', 1), b: mv(w, 'cl_err', 3) }) }}</span>
        </button>
      </section>
      <section v-if="s" class="card main">
        <div class="card-head"><h2>{{ $td(s.serial) }} · <small class="muted">{{ $t('{a}　工单 {b}　宿主机 {c}', { a: $td(s.item), b: $td(s.work_order), c: s.host || '—' }) }}</small></h2></div>
        <div class="kpis">
          <div :class="{ bad: s.limit && s.p99 > s.limit }"><b>{{ s.p99.toFixed(1) }} ms</b><span>{{ $t('延迟 p99（24 小时平均，上限 {a}）', { a: s.limit || '—' }) }}</span></div>
          <div :class="{ bad: s.err_avg > 0.1 }"><b>{{ s.err_avg.toFixed(3) }} %</b><span>{{ $t('错误率（上限 0.1）') }}</span></div>
          <div :class="{ bad: s.avail < 99.9 }"><b>{{ s.avail.toFixed(2) }} %</b><span>{{ $t('可用性（按分钟）') }}</span></div>
        </div>
        <h3>{{ $t('延迟 p99（ms，每 5 分钟最高）') }}</h3>
        <svg :viewBox="`0 0 ${W} ${H}`" class="chart" role="img" :aria-label="$t('延迟曲线')">
          <line v-if="s.limit" :x1="PAD" :x2="W - PAD" :y1="ly(s.limit)" :y2="ly(s.limit)" class="lim" />
          <polyline :points="s.minute.map((t, i) => tx(t).toFixed(1) + ',' + ly(s.lat[i]).toFixed(1)).join(' ')" class="ln lat" />
          <text v-for="h in [0, 6, 12, 18, 24]" :key="'h' + h" :x="tx(h * 60)" :y="H - 2" class="tk" text-anchor="middle">{{ h }}:00</text>
          <text :x="PAD + 2" :y="12" class="tk">0–{{ latMax.toFixed(0) }} ms</text>
        </svg>
        <h3>{{ $t('错误率（%，每 5 分钟最高）') }}</h3>
        <svg :viewBox="`0 0 ${W} ${H2}`" class="chart" role="img" :aria-label="$t('错误率曲线')">
          <line :x1="PAD" :x2="W - PAD" :y1="ey(0.1)" :y2="ey(0.1)" class="lim" />
          <polyline :points="s.minute.map((t, i) => tx(t).toFixed(1) + ',' + ey(s.err[i]).toFixed(1)).join(' ')" class="ln er" />
          <text :x="PAD + 2" :y="12" class="tk">0–{{ errMax.toFixed(2) }} %</text>
        </svg>
        <p class="small">{{ $t('延迟一阵一阵地冲高、只在一台宿主机上——查同机的其他租户（吵闹的邻居）；一个可用区的两台宿主机错误率一起升高——查最近推到这个区的配置变更。加机器解决不了这两种。') }}</p>
        <p class="small muted">{{ $t('示例模型：延迟、错误率、日周期都是示例值；曲线每分钟一点，这里每 5 分钟取最高画。') }}</p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { get } from '../lib/api';

const W = 640; const H = 200; const H2 = 130; const PAD = 14;
const route = useRoute();
const tab = ref(route.query.tab === 'svc' ? 'svc' : 'build');
const err = ref('');
const builds = ref([]); const svcs = ref([]);
const bSel = ref(''); const sSel = ref('');
const b = ref(null); const s = ref(null);
const bItem = ref(''); const runner = ref(''); const host = ref('');

const uniq = (a) => [...new Set(a.filter(Boolean))].sort();
const bItems = computed(() => uniq(builds.value.map((w) => w.item)));
const runners = computed(() => uniq(builds.value.map((w) => w.runner)));
const benches = computed(() => uniq(builds.value.map((w) => w.bench)));
const hosts = computed(() => uniq(svcs.value.map((w) => w.host)));
const zones = computed(() => uniq(svcs.value.map((w) => (w.host || '').slice(0, 4))));
const bShown = computed(() => builds.value.filter((w) => (!bItem.value || w.item === bItem.value) && (!runner.value || w.runner === runner.value)));
const sShown = computed(() => svcs.value.filter((w) => !host.value || w.host === host.value));
const mv = (w, c, d) => { const q = w.meas[c]; return q ? Number(q.v).toFixed(d) : '—'; };
function avgBy(arr, f, key, c, d) {
  const a = arr.filter((w) => w[f] === key && w.meas[c]).map((w) => Number(w.meas[c].v));
  return a.length ? (a.reduce((p, q) => p + q, 0) / a.length).toFixed(d) : '—';
}
function marginBy(k) {
  const a = builds.value.filter((w) => w.bench === k && w.meas.rtos_irq).map((w) => Number(w.meas.rtos_irq.hi) - Number(w.meas.rtos_irq.v));
  return a.length ? (a.reduce((p, q) => p + q, 0) / a.length).toFixed(1) : '—';
}
const zoneName = (z) => ({ 'cl-a': $t('A 区'), 'cl-b': $t('B 区') }[z] || z);
function zoneErr(z) {
  const a = svcs.value.filter((w) => (w.host || '').startsWith(z) && w.meas.cl_err).map((w) => Number(w.meas.cl_err.v));
  return a.length ? (a.reduce((p, q) => p + q, 0) / a.length).toFixed(3) : '—';
}
const curB = computed(() => builds.value.find((w) => w.serial === bSel.value));
const irqBad = computed(() => { const q = curB.value && curB.value.meas.rtos_irq; return !!q && q.result !== 'pass'; });
function stageCls(i) {
  if (!b.value) return '';
  if (i === 1 && b.value.fails > 0) return b.value.pass < b.value.pass_lo ? 'bad' : 'warn';
  if (i === 5 && curB.value && !curB.value.pass) return 'bad';
  return 'ok';
}
// 直方图
const hMax = computed(() => (b.value && b.value.hist ? Math.max(...b.value.hist.map((n) => Math.log10(n + 1))) : 1));
const hx = (i) => PAD + (W - 2 * PAD) * i / 40;
const hy = (n) => H - PAD - (H - 2 * PAD) * Math.log10(n + 1) / hMax.value;
// 内存曲线
const mLo = computed(() => (b.value && b.value.soak_mb ? Math.min(...b.value.soak_mb) - 10 : 0));
const mHi = computed(() => (b.value && b.value.soak_mb ? Math.max(...b.value.soak_mb) + 10 : 1));
const sHours = computed(() => (b.value && b.value.soak_h ? b.value.soak_h[b.value.soak_h.length - 1] : 1));
const sx = (t) => PAD + (W - 2 * PAD) * t / sHours.value;
const sy = (v) => H - PAD - (H - 2 * PAD) * (v - mLo.value) / (mHi.value - mLo.value);
const hourTicks = computed(() => { const a = []; const st = sHours.value > 6 ? 2 : 1; for (let t = 0; t <= sHours.value; t += st) a.push(t); return a; });
// 服务曲线
const tx = (m) => PAD + (W - 2 * PAD) * m / 1440;
const latMax = computed(() => (s.value ? Math.max(...s.value.lat, s.value.limit || 0) * 1.1 : 1));
const ly = (v) => H - PAD - (H - 2 * PAD) * v / latMax.value;
const errMax = computed(() => (s.value ? Math.max(...s.value.err, 0.12) * 1.1 : 1));
const ey = (v) => H2 - PAD - (H2 - 2 * PAD) * v / errMax.value;

async function openBuild(x) {
  bSel.value = x; err.value = '';
  try { b.value = await get('/software/build/' + encodeURIComponent(x)); } catch (e) { err.value = e.message; }
}
async function openSvc(x) {
  sSel.value = x; err.value = '';
  try { s.value = await get('/software/service/' + encodeURIComponent(x)); } catch (e) { err.value = e.message; }
}
async function load() {
  try {
    builds.value = (await get('/software/builds')).builds;
    svcs.value = (await get('/software/services')).services;
    const wb = (tab.value === 'build' && route.query.serial) || (builds.value[0] && builds.value[0].serial);
    if (wb) openBuild(wb);
    const ws = (tab.value === 'svc' && route.query.serial) || (svcs.value[0] && svcs.value[0].serial);
    if (ws) openSvc(ws);
  } catch (e) { err.value = e.message; }
}
watch(tab, () => { err.value = ''; });
onMounted(load);
</script>

<style scoped>
.tabs { display: flex; gap: 6px; margin: 0 0 10px; }
.tabs button { border: 1px solid #e3e6ee; background: #fff; border-radius: 8px; padding: 5px 12px; cursor: pointer; }
.tabs button.on { border-color: #1d4ed8; background: #eff6ff; color: #1d4ed8; }
.cols { display: grid; grid-template-columns: minmax(220px, 300px) 1fr; gap: 12px; }
@media (max-width: 800px) { .cols { grid-template-columns: 1fr; } }
.cols > * { min-width: 0; }
.brd { display: grid; grid-template-columns: 1fr auto; gap: 2px 8px; width: 100%; text-align: left; border: 1px solid #e3e6ee; background: #fff; border-radius: 8px; padding: 6px 8px; margin: 4px 0; cursor: pointer; }
.brd > span:nth-child(n+3) { grid-column: 1 / -1; }
.brd.on { border-color: #1d4ed8; background: #eff6ff; }
.stages { display: flex; flex-wrap: wrap; gap: 4px; margin: 4px 0 8px; }
.stage { font-size: 12px; padding: 3px 8px; border-radius: 12px; border: 1px solid #e3e6ee; }
.stage.ok { background: #f0fdf4; border-color: #bbf7d0; color: #15803d; }
.stage.warn { background: #fffbeb; border-color: #fde68a; color: #b45309; }
.stage.bad { background: #fef2f2; border-color: #fca5a5; color: #b91c1c; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin: 6px 0 10px; }
.kpis div { border: 1px solid #e3e6ee; border-radius: 8px; padding: 6px 8px; display: flex; flex-direction: column; }
.kpis b { font-size: 1.2em; } .kpis span { font-size: 12px; color: #6b7280; }
.kpis .bad { border-color: #fca5a5; background: #fef2f2; } .kpis .bad b { color: #b91c1c; }
.chart { width: 100%; height: auto; display: block; background: #fafbfd; border: 1px solid #eef0f5; border-radius: 6px; }
.chart .bar { fill: #93c5fd; }
.chart .lim { stroke: #dc2626; stroke-dasharray: 4 3; }
.chart .ln { fill: none; stroke-width: 1.2; }
.chart .mem { stroke: #0f766e; } .chart .dot { fill: #b91c1c; }
.chart .lat { stroke: #1d4ed8; } .chart .er { stroke: #dc2626; }
.chart .tk { font-size: 10px; fill: #6b7280; }
.ok { color: #15803d; } .bad { color: #b91c1c; }
</style>
