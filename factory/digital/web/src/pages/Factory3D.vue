<template>
  <div class="wrap3d">
    <div ref="host" class="host" data-help="3d-scene" @pointerdown="down" @pointerup="up"></div>
    <div v-show="mode === 'plan'" ref="planHost" class="host plan" data-help="3d-plan"></div>
    <!-- 第 171 轮：分车间、参观 -->
    <div v-if="pm" class="zonebar" data-help="3d-zones">
      <span class="seg"><button class="chip" :class="{ on: mode === '3d' }" @click="setMode('3d')">{{ t('三维') }}</button><button class="chip" :class="{ on: mode === 'plan' }" @click="setMode('plan')">{{ t('平面图') }}</button></span>
      <button class="chip" :class="{ on: zone === null }" @click="goZone(null)">{{ t('全厂') }}</button>
      <template v-if="realZones.length">
        <button v-for="z in realZones" :key="z.id" class="chip" :class="{ on: zone === z.id }" @click="goZone(z.id)">{{ zname(z) }}</button>
      </template>
      <button class="chip tourbtn" @click="tour ? endTour() : startTour()">{{ tour ? t('结束参观') : t('开始参观') }}</button>
    </div>
    <div v-if="tour" class="tourcard" data-help="3d-tour">
      <div class="small muted">{{ t('参观 · 第 {k} / {n} 站', { k: tour.i + 1, n: tour.stops.length }) }}</div>
      <h3>{{ stopTitle }}</h3>
      <p v-for="(l, i) in stopLines" :key="i" class="small">{{ l }}</p>
      <div class="tourctl">
        <button class="btn" :disabled="tour.i === 0" @click="step(-1)">{{ t('上一站') }}</button>
        <button class="btn" @click="tour.auto = !tour.auto; tick()">{{ tour.auto ? t('暂停') : t('自动播放') }}</button>
        <button class="btn" :disabled="tour.i >= tour.stops.length - 1" @click="step(1)">{{ t('下一站') }}</button>
      </div>
    </div>
    <div class="legend small" data-help="3d-legend">
      <span v-for="s in ['run', 'idle', 'setup', 'down']" :key="s"><i :style="{ background: HEX[s] }"></i>{{ STATE[s].label }}</span>
      <span class="muted">{{ mode === 'plan' ? t('拖动平移 · 滚轮缩放 · 点车间进去 · 点设备看状态和工艺文件') : t('拖动旋转 · 滚轮缩放 · 点车间进去 · 点设备看状态和工艺文件') }}</span>
    </div>
    <aside v-if="sel" class="panel" data-help="3d-panel">
      <button class="x" :aria-label="t('关闭')" @click="close">×</button>
      <h2>{{ sel.toUpperCase() }} {{ unitName(sel) }}</h2>
      <p v-if="pmu" class="small muted">{{ [zoneOf(sel), pmu.workstation ? t('工作中心') + ' ' + opName(pmu.workstation) : ''].filter(Boolean).join(' · ') }}</p>
      <div class="tabs">
        <button v-for="tb in TABS" :key="tb[0]" :class="{ on: tab === tb[0] }" @click="tab = tb[0]">{{ t(tb[1]) }}</button>
      </div>
      <div v-if="tab !== 'status' && jobs.length > 1" class="jobsel">
        <label class="small">{{ t('零件 · 工序') }}
          <select v-model="jobKey">
            <option v-for="j in jobs" :key="j[0] + '|' + j[1]" :value="j[0] + '|' + j[1]">{{ j[0] }} · {{ opName(j[1]) }}</option>
          </select></label>
      </div>
      <!-- 状态 -->
      <template v-if="tab === 'status'">
        <template v-if="bus.machines[sel]">
          <p><span class="pill" :style="{ color: STATE[m.state].color, background: STATE[m.state].bg }">{{ STATE[m.state].label }}</span>
            <span v-if="m.reason" class="small"> {{ m.locked ? '🔒 ' : '' }}{{ td(m.reason) }}</span></p>
          <p class="small">{{ t('工单') }} <b class="mono">{{ m.work_order || '—' }}</b> · {{ isEn() ? bi(m.operation || '') : (m.operation || '').split(' ')[0] }} · {{ t('{d}/{n} 件', { d: m.qty_done, n: m.qty }) }}</p>
          <p class="small">{{ t('待加工 {n} 件 · 刀具寿命 {p}%', { n: m.queue, p: Math.round((m.tool_life_left ?? 1) * 100) }) }}</p>
          <p v-if="info.tags.length" class="tags"><span v-for="g in info.tags" :key="g.text" class="tag small" :class="g.tone">{{ g.text }}</span></p>
          <p v-if="info.pmH" class="small muted">{{ t('自上次保养运行 {r} 小时 · 保养周期 {p} 小时', { r: info.runH, p: info.pmH }) }}</p>
          <router-link :to="{ path: '/work/operator', query: { unit: sel } }" class="small">{{ t('打开车间终端 →') }}</router-link>
        </template>
        <p v-else-if="bus.agvs && bus.agvs[sel]" class="small">{{ t('物流小车') }} · {{ bus.agvs[sel].load ? t('载货') : t('空车') }}</p>
        <p v-else class="small muted">{{ t('这个单元没有状态消息。') }}</p>
        <p v-if="jobs.length" class="small">{{ t('这台做 {n} 道（零件 · 工序），看“工艺卡”“工序卡”“检验规程”。', { n: jobs.length }) }}</p>
        <!-- 点哪看哪（第 30 轮 §八）：对应的帮助章节 -->
        <p class="helpto small"><span v-if="info.help.domain" class="muted">{{ t('领域：') }}{{ info.help.domain }} · </span>
          <router-link :to="info.help.to">{{ info.help.label }} →</router-link></p>
        <template v-if="sel === 'key-01' || isLathe">
          <hr>
          <h3>{{ sel === 'key-01' ? t('键槽刀路回放') : t('车削刀路回放') }}<span v-if="gcInfo" class="small muted"> {{ gcInfo }}</span></h3>
          <div ref="gcHost" class="gchost"></div>
          <p v-if="!gcode" class="small muted">{{ sel === 'key-01' ? t('还没有 G 代码：工艺员在 FreeCAD 或网页设计台发布后生成。') : t('还没有车削程序：在“数控编程”里给粗车或精车工序编程，挂到工艺规程上审批生效后才有。') }}</p>
          <button v-else class="btn" @click="playGcode">{{ gcPlaying ? t('重新播放') : t('播放刀路') }}</button>
        </template>
      </template>
      <!-- 没有工序的设备（库位、物流、计量室） -->
      <template v-else-if="!job && tab !== 'insp'">
        <p class="small muted">{{ t('这台不在任何工艺路线上（库位、物流或计量室），没有工艺卡、工序卡。') }}</p>
      </template>
      <!-- 工艺卡 -->
      <template v-else-if="tab === 'route'">
        <h3>{{ t('工艺过程卡') }} · {{ job[0] }} {{ itemName(job[0]) }}</h3>
        <table class="kv small"><tbody>
          <tr><th>{{ t('工艺路线') }}</th><td>{{ opName(bom.routing) }}</td></tr>
          <tr><th>{{ t('用于') }}</th><td>{{ (pm.used_in[job[0]] || []).join(LIST()) || t('出厂成品') }}</td></tr>
          <tr><th>{{ t('工序数') }}</th><td>{{ steps.length }}</td></tr>
          <tr><th>{{ t('工时合计') }}</th><td>{{ +steps.reduce((a, s) => a + s[1], 0).toFixed(1) }} min</td></tr>
        </tbody></table>
        <button class="btn small" @click="toggleRoute">{{ routeOn ? t('清掉路线') : t('在 3D 里画路线') }}</button>
        <table class="tbl small"><thead><tr><th>#</th><th>{{ t('工序') }}</th><th>{{ t('设备') }}</th><th>min</th></tr></thead>
          <tbody><tr v-for="(s, i) in steps" :key="i" :class="{ cur: i === job[2] }" @click="gotoStep(i)">
            <td>{{ i + 1 }}</td><td>{{ opName(s[0]) }}</td><td class="mono">{{ (pm.ops[s[0]]?.units || []).slice(0, 3).join(' ') }}{{ (pm.ops[s[0]]?.units || []).length > 3 ? ' …' : '' }}</td><td>{{ s[1] }}</td></tr></tbody></table>
        <p class="small muted">{{ t('点一行跳到那道工序的设备。') }}</p>
        <h3>{{ t('物料清单') }}</h3>
        <table class="tbl small"><tbody><tr v-for="c in bom.components" :key="c[0]"><td class="mono">{{ c[0] }}</td><td>{{ itemName(c[0]) }}</td><td>{{ c[2] }} {{ c[3] }}</td></tr></tbody></table>
        <template v-for="row in [pd?.castrows?.[job[0]], pd?.partrows?.[job[0]]].filter(Boolean)" :key="row.src">
          <h3>{{ t('工艺方案') }}</h3>
          <table class="kv small"><tbody><tr v-for="f in row.fields" :key="f[0]"><th>{{ f[0] }}</th><td class="pre">{{ f[1] }}</td></tr></tbody></table>
          <p class="src small muted">{{ row.src }}<span v-if="isEn()">&nbsp;{{ t('（原文中文）') }}</span></p>
        </template>
        <template v-if="pd?.holes?.[job[0]]?.length"><h3>{{ t('关键孔系') }}</h3><p v-for="l in pd.holes[job[0]]" :key="l" class="small">{{ l.replace(/^- /, '') }}</p></template>
      </template>
      <!-- 工序卡 -->
      <template v-else-if="tab === 'op'">
        <h3>{{ t('工序卡') }} · {{ opName(job[1]) }}</h3>
        <table class="kv small"><tbody>
          <tr><th>{{ t('零件') }}</th><td>{{ job[0] }} {{ itemName(job[0]) }}</td></tr>
          <tr><th>{{ t('第几道') }}</th><td>{{ job[2] + 1 }} / {{ steps.length }}</td></tr>
          <tr><th>{{ t('工作中心') }}</th><td>{{ opName(pm.ops[job[1]]?.workstation || '') }}</td></tr>
          <tr><th>{{ t('能做的设备') }}</th><td><a v-for="u in pm.ops[job[1]]?.units || []" :key="u" href="#" class="mono ulink" @click.prevent="selectUnit(u)">{{ u }}</a></td></tr>
          <tr><th>{{ t('工时') }}</th><td>{{ steps[job[2]]?.[1] }} min</td></tr>
          <tr><th>{{ t('检验工序') }}</th><td>{{ pm.ops[job[1]]?.inspection ? t('是') : t('否') }}</td></tr>
          <tr v-if="job[2] > 0"><th>{{ t('前一道') }}</th><td><a href="#" @click.prevent="gotoStep(job[2] - 1)">{{ opName(steps[job[2] - 1][0]) }}</a></td></tr>
          <tr v-if="job[2] < steps.length - 1"><th>{{ t('后一道') }}</th><td><a href="#" @click.prevent="gotoStep(job[2] + 1)">{{ opName(steps[job[2] + 1][0]) }}</a></td></tr>
        </tbody></table>
        <template v-if="docrow">
          <h3>{{ t('工步与要点') }}</h3>
          <table class="kv small"><tbody><tr v-for="f in docrow.fields" :key="f[0]"><th>{{ f[0] }}</th><td class="pre">{{ f[1] }}</td></tr></tbody></table>
          <p class="src small muted">{{ docrow.src }}<span v-if="isEn()">&nbsp;{{ t('（原文中文）') }}</span></p>
        </template>
        <p v-else class="small muted">{{ t('这道工序的工步、定位夹紧写在工艺规程里。') }} <router-link to="/process">{{ t('工艺规程与 AI 评审 →') }}</router-link></p>
      </template>
      <!-- 检验规程 -->
      <template v-else-if="tab === 'insp'">
        <template v-if="job">
          <h3>{{ t('检验规程') }} · {{ job[0] }} · {{ opName(job[1]) }}</h3>
          <table v-if="chars.length" class="tbl small"><thead><tr><th>{{ t('特性') }}</th><th>{{ t('名义') }}</th><th>{{ t('下限') }}</th><th>{{ t('上限') }}</th><th></th></tr></thead>
            <tbody><tr v-for="c in chars" :key="c.code"><td>{{ td(c.name) }}</td><td>{{ c.nominal }}</td><td>{{ c.lo }}</td><td>{{ c.hi }}</td><td>{{ c.unit }}</td></tr></tbody></table>
          <p v-else class="small muted">{{ pm.ops[job[1]]?.inspection ? t('这道检验工序的特性在质量页的检验模板里。') : t('这道工序没有单独记录的测量特性（由后面的检验工序把关）。') }}</p>
          <template v-if="samp.length">
            <h3>{{ t('计量室抽检') }}</h3>
            <p v-for="(x, i) in samp" :key="i" class="small">{{ t('{u}：每 {e} 件抽 1 件，约 {m} 分钟', { u: x.unit, e: x.every, m: x.minutes }) }} — {{ x.chars.map((c) => td(c.name)).join(SEMI()) }}</p>
          </template>
          <template v-if="fqc.length">
            <h3>{{ t('铸造检验点') }}</h3>
            <table class="kv small"><tbody><tr v-for="r in fqc" :key="r[0]"><th>{{ r[0] }}</th><td class="pre">{{ r.slice(1).join(' · ') }}</td></tr></tbody></table>
          </template>
          <template v-if="metroRows.length">
            <h3>{{ t('计量室首件与抽检') }}</h3>
            <p v-for="(r, i) in metroRows" :key="i" class="small pre">{{ r.row.slice(1).join(' · ') }} · {{ r.unit }}</p>
          </template>
        </template>
        <template v-if="metroTasks.length">
          <h3>{{ t('这台的抽检任务') }}</h3>
          <p v-for="(x, i) in metroTasks" :key="i" class="small">{{ x.key.split('|')[0] }} · {{ opName(x.key.split('|')[1]) }} — {{ t('每 {e} 件抽 1 件', { e: x.every }) }} — {{ x.chars.map((c) => td(c.name)).join(SEMI()) }}</p>
        </template>
        <p v-if="!job && !metroTasks.length" class="small muted">{{ t('这台不在任何工艺路线上（库位、物流或计量室），没有工艺卡、工序卡。') }}</p>
        <template v-if="pd?.general?.length">
          <details><summary class="small">{{ t('通用检验规程（三检、SPC、不合格品、追溯、量具）') }}</summary>
            <p v-for="l in pd.general" :key="l" class="small">{{ l.replace(/^- /, '') }}</p></details>
        </template>
      </template>
    </aside>
    <div v-if="err" class="errbox err">{{ err }}</div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import * as THREE from 'three';
import { createWorkshop, HEX } from '../lib/workshop3d';
import { createPlan } from '../lib/plan2d';
import { get, loadConfig } from '../lib/api';
import { bus } from '../lib/bus';
import { STATE } from '../lib/fmt';
import { parseGcode } from '../lib/gcode';
import { machineInfo } from '../lib/machinfo';
import { bi, isEn, nm, t, td, tk } from '../lib/i18n';
const unitName = (u) => { const x = layout.value?.units[u] || pm.value?.units[u]; return x ? (isEn() ? x.name_en || x.en || x.name : x.name) : ''; };
// 中英合写的名字（工序、物料）：中文界面去掉后面的英文
const LIST = () => (isEn() ? ', ' : '\u3001'), SEMI = () => (isEn() ? '; ' : '\uff1b');   // 列表分隔号
const opName = (s) => (isEn() ? bi(s || '') : String(s || '').replace(/\s+[A-Za-z(][^\u4e00-\u9fff]*$/, ''));

const route = useRoute();
const host = ref(null);
const gcHost = ref(null);
const layout = ref(null);
const sel = ref(null);
const err = ref('');
const gcode = ref('');
const gcPlaying = ref(false);
const m = computed(() => bus.machines[sel.value] || {});
const demo = ref(true);
const risk = ref(null);
const info = computed(() => machineInfo(bus.machines[sel.value], layout.value?.units[sel.value], demo.value, risk.value?.unit === sel.value ? risk.value : null));
// 点哪看哪：演示工厂取设备维护算的保养逾期（设备有保养计划才有；取不到就按 /api/layout 的标准周期）
watch(sel, (u) => {
  risk.value = null;
  if (u && demo.value && layout.value?.units[u]?.pm_h) get('/maint/risk/' + u).then((r) => { if (sel.value === u) risk.value = r; }).catch(() => {});
});
const isLathe = computed(() => (sel.value || '').startsWith('cnc-l01'));
let ws, downAt;
// 第 171b 轮：平面图（白板手绘俯视图）。V() = 当前看的那个视图；高亮、路线、状态两个视图都改
let plan = null;
const MODE_KEY = 'wq-3d-mode';
const mode = ref((() => { try { return localStorage.getItem(MODE_KEY) || '3d'; } catch (e) { return '3d'; } })());
const planHost = ref(null);
const V = () => (mode.value === 'plan' ? plan : ws);
const both = (f) => { if (ws) f(ws); if (plan) f(plan); };
function ensurePlan() {
  if (plan || !planHost.value || !layout.value) return;
  const zs = (pm.value?.zones || []).map((z) => ({ ...z, name_shown: zname(z) }));
  plan = createPlan(planHost.value, layout.value, { zones: zs, unitLabel: unitName,
    onPick: (u) => { sel.value = u; }, onZone: (z) => { if (z !== zone.value) goZone(z); } });
  plan.update(bus.machines, bus.agvs);
  if (sel.value) plan.highlight(sel.value);
}
async function setMode(m) {
  mode.value = m;
  try { localStorage.setItem(MODE_KEY, m); } catch (e) { /* 无痕窗口 */ }
  await nextTick();
  if (m === 'plan') { ensurePlan(); plan?.resize(); } else ws?.resize();
  if (routeOn.value) { routeOn.value = false; both((v) => v.clearRoute()); }
  if (sel.value) V()?.flyUnit(sel.value); else if (zone.value) V()?.flyZone(zone.value); else V()?.overview();
}

// ---------------------------------------------------------------- 第 171 轮：分车间、参观、工艺文件
const TABS = [['status', tk('状态')], ['route', tk('工艺卡')], ['op', tk('工序卡')], ['insp', tk('检验规程')]];
const pm = ref(null);            // /api/plantmap
const zone = ref(null);
const tab = ref('status');
const jobKey = ref('');
const routeOn = ref(false);
const tour = ref(null);
const pd = computed(() => pm.value?.procdocs || null);
const realZones = computed(() => (pm.value?.zones || []).filter((z) => !z.auto));
const zname = (z) => (isEn() ? z.name_en || z.name : z.name);
const zoneOf = (u) => { const z = (pm.value?.zones || []).find((x) => x.id === pm.value?.units[u]?.zone); return z && !z.auto ? zname(z) : ''; };
const pmu = computed(() => pm.value?.units[sel.value] || null);
const jobs = computed(() => pm.value?.jobs[sel.value] || []);
const job = computed(() => jobs.value.find((j) => j[0] + '|' + j[1] === jobKey.value) || jobs.value[0] || null);
const bom = computed(() => (job.value ? pm.value.boms[job.value[0]] : null));
const steps = computed(() => (bom.value ? pm.value.routings[bom.value.routing] || [] : []));
const itemName = (c) => opName(pm.value?.items[c]?.name || '');
const opCode = (op) => String(op || '').split(' ')[0];
const docrow = computed(() => (job.value && pd.value ? pd.value.docrows?.[job.value[0] + '|' + opCode(job.value[1])] : null));
const chars = computed(() => (job.value ? pm.value.meas[job.value[0] + '|' + job.value[1]] || [] : []));
const samp = computed(() => (job.value ? pm.value.sampling[job.value[0] + '|' + job.value[1]] || [] : []));
const fqc = computed(() => (job.value && pd.value?.fqc?.rows ? pd.value.fqc.rows[opCode(job.value[1])] || [] : []));
const metroRows = computed(() => (job.value && pd.value?.metro ? pd.value.metro.rows.filter((r) => r.items.includes(job.value[0])) : []));
const metroTasks = computed(() => Object.entries(pm.value?.sampling || {}).flatMap(([key, xs]) => xs.filter((x) => x.unit === sel.value).map((x) => ({ key, ...x }))));
watch(sel, (u) => {
  jobKey.value = '';
  both((v) => v.highlight(u));
  if (routeOn.value) toggleRoute();
  if (!u) tab.value = 'status';
});
watch(jobs, (js) => {           // 选设备后默认选它的第一道（零件 · 工序）
  if (js.length && !js.some((j) => j[0] + '|' + j[1] === jobKey.value)) jobKey.value = js[0][0] + '|' + js[0][1];
}, { immediate: true });
watch(job, () => { if (routeOn.value) { routeOn.value = false; both((v) => v.clearRoute()); } });
function close() { sel.value = null; }
function selectUnit(u, fly = true) { sel.value = u; if (fly && V()) V().flyUnit(u); }
function gotoStep(i) {
  const s = steps.value[i];
  if (!s) return;
  const it = job.value[0];
  const us = pm.value.ops[s[0]]?.units || [];
  const u = us.includes(sel.value) ? sel.value : us[0];
  if (!u) return;
  const keep = tab.value;
  selectUnit(u);
  nextTick(() => { jobKey.value = it + '|' + s[0]; tab.value = keep; });
}
function toggleRoute() {
  if (!ws) return;
  if (routeOn.value) { both((v) => v.clearRoute()); routeOn.value = false; return; }
  const us = steps.value.map((s) => { const c = pm.value.ops[s[0]]?.units || []; return c.includes(sel.value) ? sel.value : c[0]; }).filter(Boolean);
  both((v) => v.showRoute(us)); routeOn.value = true;
  const L_ = layout.value.units, xs = us.map((u) => L_[u]).filter(Boolean);
  if (xs.length) V().flyRect([Math.min(...xs.map((v) => v.x)) - 4, Math.min(...xs.map((v) => v.y)) - 4, Math.max(...xs.map((v) => v.x)) + 4, Math.max(...xs.map((v) => v.y)) + 4]);
}
function goZone(id) {
  zone.value = id;
  if (!V()) return;
  if (id) V().flyZone(id); else V().overview();
}
// 参观：全厂 → 每个车间（全貌，再每个工作中心停一台，最多 8 台）
function buildStops() {
  const P = pm.value, out = [{ kind: 'plant' }];
  for (const z of P.zones) {
    if (!z.auto) out.push({ kind: 'zone', z });
    const seen = new Set();
    const us = z.units.filter((u) => !P.units[u].agv).slice().sort((a, b) => (layout.value.units[a]?.x ?? 0) - (layout.value.units[b]?.x ?? 0) || (layout.value.units[a]?.y ?? 0) - (layout.value.units[b]?.y ?? 0));
    let n = 0;
    for (const u of us) {
      const key = P.units[u].workstation || u;
      if (seen.has(key) || n >= (z.auto ? 12 : 8)) continue;
      seen.add(key); n += 1;
      out.push({ kind: 'unit', u, z });
    }
  }
  return out;
}
let timer = null;
function startTour() { tour.value = { stops: buildStops(), i: 0, auto: true }; showStop(); tick(); }
function endTour() { tour.value = null; clearTimeout(timer); }
function step(d) { if (!tour.value) return; tour.value.i = Math.max(0, Math.min(tour.value.stops.length - 1, tour.value.i + d)); showStop(); tick(); }
function tick() {
  clearTimeout(timer);
  if (tour.value?.auto && tour.value.i < tour.value.stops.length - 1) timer = setTimeout(() => step(1), 6000);
}
function showStop() {
  const s = tour.value.stops[tour.value.i];
  if (s.kind === 'plant') { sel.value = null; goZone(null); } else if (s.kind === 'zone') { sel.value = null; goZone(s.z.id); zone.value = s.z.id; } else { zone.value = s.z.auto ? null : s.z.id; selectUnit(s.u); tab.value = 'status'; }
}
const stopTitle = computed(() => {
  const s = tour.value?.stops[tour.value.i];
  if (!s) return '';
  if (s.kind === 'plant') return t('全厂');
  if (s.kind === 'zone') return zname(s.z);
  return `${s.u.toUpperCase()} ${unitName(s.u)}`;
});
function opsSummary(us) {
  const set = [];
  for (const u of us) for (const j of pm.value.jobs[u] || []) { const o = opName(j[1]); if (!set.includes(o)) set.push(o); }
  return set;
}
const stopLines = computed(() => {
  const s = tour.value?.stops[tour.value.i], P = pm.value;
  if (!s || !P) return [];
  if (s.kind === 'plant') {
    const n = Object.values(P.units).length;
    return [realZones.value.length ? t('{z} 个车间、{n} 台设备。下面一个车间一个车间走。', { z: realZones.value.length, n }) : t('{n} 台设备。下面每个工作中心停一站。', { n })];
  }
  if (s.kind === 'zone') {
    const ops = opsSummary(s.z.units);
    return [t('{n} 台设备', { n: s.z.units.length }), ops.length ? t('做：{o}', { o: ops.slice(0, 8).join(LIST()) + (ops.length > 8 ? ' …' : '') }) : t('这里不做加工工序（库位、计量室）。')];
  }
  const js = P.jobs[s.u] || [], u = P.units[s.u], st = bus.machines[s.u];
  const lines = [];
  if (u.workstation) lines.push(t('工作中心：{w}', { w: opName(u.workstation) }));
  if (js.length) lines.push(t('做：{j}', { j: js.slice(0, 4).map((j) => `${j[0]} · ${opName(j[1])}`).join(SEMI()) + (js.length > 4 ? t('……共 {n} 道', { n: js.length }) : '') }));
  else lines.push(t('{a}，不在工艺路线上。', { a: t(u.area_zh) }));
  if (st) lines.push(t('现在：{s}', { s: STATE[st.state]?.label || st.state }) + (st.work_order ? ` · ${st.work_order}` : ''));
  return lines;
});
let gc = null;             // 刀路小窗

function applyStatus() { both((v) => v.update(bus.machines, bus.agvs)); }
function down(e) { downAt = [e.clientX, e.clientY]; }
function up(e) {
  if (!ws || !downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
  const u = ws.pick(e);
  if (u) { sel.value = u; return; }
  const z = ws.pickZone && ws.pickZone(e);           // 点到车间地面：进这个车间
  if (z && z !== zone.value) goZone(z);
}

// ---------------------------------------------------------------- 刀路小窗
let design = null;
const gcInfo = ref('');
// 键槽：设计发布带的或数控编程下发的“铣键槽”程序；车削：数控编程随工艺规程下发到 CNC-L01 的最新程序（第 13 轮）
async function loadGcode(unit) {
  gcode.value = ''; gcInfo.value = '';
  let ref_ = unit === 'key-01' ? route.query.gcode : null;
  if (!ref_) {
    design = design || await get('/design/SH-301');
    const g = unit === 'key-01' ? design.gcode.find((x) => (x.operation || '').startsWith('铣键槽'))   // i18n-ok 数据里的工序名
      : design.gcode.filter((x) => (x.machine || '').startsWith('cnc-l01'))
        .sort((a, b) => (b.process_revision || 0) - (a.process_revision || 0) || (a.program || 0) - (b.program || 0))[0];
    ref_ = g?.gcode_ref;
    if (g && g.program) gcInfo.value = `O${String(g.program).padStart(4, '0')} · ${isEn() ? bi(g.operation || '') : (g.operation || '').split(' ')[0]}`;
  }
  if (ref_) gcode.value = await (await fetch(ref_)).text();
}
function initGc() {
  if (!gcHost.value || gc) return;
  if (isLathe.value) { initLathe(); return; }
  const w = gcHost.value.clientWidth, h = 200;
  const s = new THREE.Scene();
  s.background = new THREE.Color('#F6F7F4');
  const cam = new THREE.PerspectiveCamera(40, w / h, 0.1, 2000);
  const r = new THREE.WebGLRenderer({ antialias: true });
  r.setSize(w, h);
  gcHost.value.appendChild(r.domElement);
  s.add(new THREE.HemisphereLight(0xffffff, 0x888888, 2));
  const pts = parseGcode(gcode.value);
  const xs = pts.map((p) => p[0]);
  const xmid = (Math.min(...xs) + Math.max(...xs)) / 2;
  // 轴段（Ø40），轴线沿 X；Z0 为最高母线
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(20, 20, 120, 48), new THREE.MeshLambertMaterial({ color: '#C7CDD1' }));
  shaft.rotation.z = Math.PI / 2; shaft.position.set(xmid, -20, 0);
  s.add(shaft);
  const tool = new THREE.Mesh(new THREE.CylinderGeometry(6, 6, 30, 24), new THREE.MeshLambertMaterial({ color: '#F2B705' }));
  s.add(tool);
  const trail = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: '#0E5E6F' }));
  s.add(trail);
  cam.position.set(xmid - 40, 70, 110);
  cam.lookAt(xmid, -5, 0);
  gc = { s, cam, r, pts, tool, trail, i: 0, f: 0, done: [], render() {
    if (gcPlaying.value) {
      const a = this.pts[this.i], b = this.pts[this.i + 1];
      if (!b) { gcPlaying.value = false; } else {
        this.f += b[3] ? 0.2 : 0.035;
        const p = [a[0] + (b[0] - a[0]) * Math.min(1, this.f), a[2] + (b[2] - a[2]) * Math.min(1, this.f)];
        this.tool.position.set(p[0], p[1] + 15, 0);
        if (!b[3]) { this.done.push(new THREE.Vector3(p[0], p[1], 0)); this.trail.geometry.setFromPoints(this.done); }
        if (this.f >= 1) { this.f = 0; this.i += 1; }
      }
    }
    this.r.render(this.s, this.cam);
  } };
  gc.tool.position.set(pts[0][0], pts[0][2] + 15, 0);
}
function initLathe() {
  // 车床：程序的 X 是直径、Z 沿轴线；场景里 x = Z，y = X/2（只画上半边刀路），毛坯是半透明圆柱
  const w = gcHost.value.clientWidth, h = 200;
  const s = new THREE.Scene();
  s.background = new THREE.Color('#F6F7F4');
  const cam = new THREE.PerspectiveCamera(40, w / h, 0.1, 3000);
  const r = new THREE.WebGLRenderer({ antialias: true });
  r.setSize(w, h);
  gcHost.value.appendChild(r.domElement);
  s.add(new THREE.HemisphereLight(0xffffff, 0x888888, 2));
  const pts = parseGcode(gcode.value).filter((p) => Math.abs(p[0]) < 150 && p[2] < 50);      // 去掉换刀点
  const zs = pts.map((p) => p[2]), rmax = Math.max(...pts.map((p) => p[0] / 2));
  const zmin = Math.min(...zs), zmax = Math.max(...zs), zmid = (zmin + zmax) / 2;
  // 只画后半个毛坯圆柱（剖开看），刀路画在剖面上
  const stock = new THREE.Mesh(new THREE.CylinderGeometry(rmax - 2, rmax - 2, zmax - zmin, 48, 1, false, Math.PI / 2, Math.PI),
    new THREE.MeshLambertMaterial({ color: '#C7CDD1', side: THREE.DoubleSide }));
  stock.rotation.z = Math.PI / 2; stock.position.set(zmid, 0, 0);
  s.add(stock);
  const tool = new THREE.Mesh(new THREE.ConeGeometry(3, 12, 16), new THREE.MeshLambertMaterial({ color: '#F2B705' }));
  tool.rotation.x = Math.PI;                         // 刀尖朝下，正好落在刀位点上
  s.add(tool);
  const trail = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: '#C62828' }));
  s.add(trail);
  cam.position.set(zmid, 40, (zmax - zmin) * 0.9 + 60);
  cam.lookAt(zmid, 5, 0);
  const P = pts.map((p) => [p[2], p[0] / 2, 0, p[3]]);
  gc = { s, cam, r, pts: P, tool, trail, i: 0, f: 0, done: [], render() {
    if (gcPlaying.value) {
      const a = this.pts[this.i], b = this.pts[this.i + 1];
      if (!b) { gcPlaying.value = false; } else {
        const L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
        this.f += (b[3] ? 6 : 1.2) / L;
        const p = [a[0] + (b[0] - a[0]) * Math.min(1, this.f), a[1] + (b[1] - a[1]) * Math.min(1, this.f)];
        this.tool.position.set(p[0], p[1] + 6, 0);
        if (!b[3]) { this.done.push(new THREE.Vector3(p[0], p[1], 0)); this.trail.geometry.setFromPoints(this.done); }
        if (this.f >= 1) { this.f = 0; this.i += 1; }
      }
    }
    this.r.render(this.s, this.cam);
  } };
  if (P.length) gc.tool.position.set(P[0][0], P[0][1] + 6, 0);
}
function playGcode() {
  initGc();
  if (!gc) return;
  gc.i = 0; gc.f = 0; gc.done = [];
  gcPlaying.value = true;
}
watch(sel, async (u) => {
  if (gc) { gc.r.dispose(); gc = null; }
  gcPlaying.value = false;
  if (u === 'key-01' || (u || '').startsWith('cnc-l01')) {
    try { await loadGcode(u); } catch (e) { gcode.value = ''; }
    await nextTick(); if (gcode.value) initGc();
  }
});

let off;
onMounted(async () => {
  loadConfig().then((c) => { demo.value = c?.plant?.demo !== false; }).catch(() => {});
  try {
    layout.value = await get('/layout');
    try { pm.value = await get('/plantmap'); } catch (e) { pm.value = null; }
    const zs = (pm.value?.zones || []).map((z) => ({ ...z, name_shown: zname(z) }));
    ws = createWorkshop(host.value, layout.value, { zones: zs, onFrame: () => { if (gc) gc.render(); } });
    if (mode.value === 'plan') { await nextTick(); ensurePlan(); }
    applyStatus();
    off = watch(() => [bus.machines, bus.agvs], applyStatus, { deep: true });
    if (route.query.gcode) sel.value = 'key-01';
    else if (route.query.unit) sel.value = String(route.query.unit);           // 数控编程页“到 3D 车间回放”带过来
  } catch (e) { err.value = t('3D 车间载入失败：') + e.message; }
});
onUnmounted(() => {
  clearTimeout(timer);
  if (off) off();
  if (ws) ws.dispose();
  if (plan) plan.dispose();
  if (gc) gc.r.dispose();
});
</script>

<style scoped>
.wrap3d { position: relative; height: calc(100vh - 64px); }
.host { position: absolute; inset: 0; }
.legend { position: absolute; left: 16px; bottom: 16px; background: rgba(255, 255, 255, .92); border-radius: 8px; padding: 8px 12px;
  display: flex; gap: 12px; flex-wrap: wrap; }
.legend i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; margin-right: 5px; }
.panel { position: absolute; right: 16px; top: 16px; width: 360px; background: #fff; border-radius: 10px; border: 1px solid var(--line);
  padding: 14px 16px; max-height: calc(100% - 32px); overflow-y: auto; }
.panel h3 { font-size: 14px; margin: 6px 0; }
.tags { display: flex; gap: 6px; flex-wrap: wrap; margin: 6px 0; }
.tag { padding: 1px 8px; border-radius: 999px; background: var(--surface-2); }
.tag.bad { color: var(--bad); background: var(--bad-bg); } .tag.warn { color: var(--warn-ink); background: var(--warn-bg); }
.helpto { margin: 10px 0 0; padding-top: 8px; border-top: 1px solid var(--line); }
.x { position: absolute; right: 10px; top: 6px; border: 0; background: none; font-size: 20px; cursor: pointer; color: var(--muted); }
.gchost { width: 100%; height: 200px; margin-bottom: 8px; border-radius: 8px; overflow: hidden; }
.zonebar { position: absolute; left: 16px; right: 372px; top: 12px; display: flex; gap: 6px; overflow-x: auto; padding-bottom: 4px; }
.chip { flex: 0 0 auto; border: 1px solid var(--line); background: rgba(255, 255, 255, .94); border-radius: 999px; padding: 4px 12px; font: inherit;
  font-size: 13px; cursor: pointer; white-space: nowrap; }
.chip.on { background: var(--accent, #0E5E6F); color: #fff; border-color: transparent; }
.seg { display: inline-flex; flex: 0 0 auto; margin-right: 6px; }
.seg .chip:first-child { border-radius: 999px 0 0 999px; } .seg .chip:last-child { border-radius: 0 999px 999px 0; border-left: 0; }
.plan { z-index: 0; }
.chip.tourbtn { border-color: #C2410C; color: #C2410C; font-weight: 600; }
.tourcard { position: absolute; left: 50%; transform: translateX(-50%); bottom: 56px; width: min(560px, calc(100% - 32px)); background: #fff;
  border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px; box-shadow: 0 4px 18px rgba(0, 0, 0, .12); }
.tourcard h3 { margin: 2px 0 4px; font-size: 16px; }
.tourcard p { margin: 2px 0; }
.tourctl { display: flex; gap: 8px; justify-content: flex-end; margin-top: 6px; }
.tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); margin: 8px 0; }
.tabs button { border: 0; background: none; padding: 6px 10px; font: inherit; font-size: 13px; cursor: pointer; color: var(--muted); border-bottom: 2px solid transparent; }
.tabs button.on { color: inherit; font-weight: 600; border-bottom-color: var(--accent, #0E5E6F); }
.jobsel select { max-width: 100%; margin-left: 6px; }
table.kv, table.tbl { width: 100%; border-collapse: collapse; margin: 6px 0; }
table.kv th { text-align: left; color: var(--muted); font-weight: 500; padding: 3px 8px 3px 0; vertical-align: top; white-space: nowrap; width: 1%; }
table.kv td, table.tbl td, table.tbl th { padding: 3px 4px; vertical-align: top; border-bottom: 1px solid var(--line); text-align: left; }
table.tbl tbody tr { cursor: pointer; }
table.tbl tr.cur td { background: #FFF4D6; font-weight: 600; }
.pre { white-space: pre-line; }
.src { margin-top: 2px; }
.ulink { margin-right: 6px; }
@media (max-width: 760px) {
  .zonebar { right: 16px; }
  .panel { left: 8px; right: 8px; top: auto; bottom: 8px; width: auto; max-height: 55%; }
  .tourcard { top: 52px; bottom: auto; }
}
.errbox { position: absolute; left: 16px; top: 16px; background: #fff; padding: 10px; border-radius: 8px; }
hr { border: 0; border-top: 1px solid var(--line); margin: 12px 0; }
</style>
