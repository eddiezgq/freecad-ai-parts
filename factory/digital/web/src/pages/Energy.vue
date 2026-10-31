<!-- 能源与环境（第 18 轮 E6）：总览（峰平谷曲线、每台设备分档电量）、计量点曲线、单耗与空转、碳与环境。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>能源与环境</h1>
      <span class="muted">设备状态 → 功率 → 计量读数（每 15 分钟）→ 单件能耗 → 电费（峰平谷）→ 碳排放</span>
      <span class="tabs" role="tablist"><button v-for="(l, k) in TABS" :key="k" type="button" role="tab" :class="{ on: tab === k }" @click="go(k)">{{ l }}</button></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="msg" class="ok small">{{ msg }}</div>

    <section v-if="ov" class="kpis" data-help="energy-kpis">
      <div class="card k"><span class="small muted">用电（{{ ov.day.slice(5) }}）</span><b>{{ num(ov.kwh) }}</b><span class="small muted">度 · {{ ov.hours }} 小时的数据</span></div>
      <div class="card k"><span class="small muted">电费</span><b>${{ money(ov.cost) }}</b><span class="small muted">峰 {{ num(ov.by_bucket.peak) }} / 平 {{ num(ov.by_bucket.flat) }} / 谷 {{ num(ov.by_bucket.valley) }} 度</span></div>
      <div class="card k"><span class="small muted">峰时占比</span><b :class="{ warn: ov.peak_share > 0.3 }">{{ pct(ov.peak_share) }}</b><span class="small muted">目标 30% 以下</span></div>
      <div class="card k"><span class="small muted">空转电量</span><b :class="{ warn: ov.idle_share > 0.2 }">{{ num(ov.idle_kwh) }}</b><span class="small muted">度（{{ pct(ov.idle_share) }}）</span></div>
      <div class="card k"><span class="small muted">碳排放</span><b>{{ num(ov.co2_kg) }}</b><span class="small muted">kg CO2（× {{ ov.factor }}）</span></div>
      <div class="card k"><span class="small muted">需量 / 合同（本月）</span><b :class="{ bad: ov.demand_ratio > 1, warn: ov.demand_ratio > 0.9 }">{{ num(ov.demand_kw) }} / {{ num(ov.contract_kw) }}</b><span class="small muted">kW（{{ pct(ov.demand_ratio) }}）</span></div>
    </section>
    <p v-if="ov && !ov.hours" class="card small muted">{{ ov.measuring ? '还没有计量读数：教学模式由仿真车间每 15 分钟（工厂时间）发一个，车间跑起来就有。' : '这个模式没有打开计量（生产模式要接电表网关或导入读数）。' }}</p>

    <!-- ① 总览 -->
    <template v-if="tab === 'overview' && ov">
      <div class="card" data-help="energy-curve">
        <div class="ch"><h3>车间总表（{{ ov.day }}，15 分钟平均功率 kW）</h3>
          <span class="small"><i class="sw peak"></i>峰 ${{ ov.price.peak }} <i class="sw flat"></i>平 ${{ ov.price.flat }} <i class="sw valley"></i>谷 ${{ ov.price.valley }} /度</span>
          <span class="row small"><button class="linkbtn" @click="shift(-1)">前一天</button><button class="linkbtn" @click="shift(1)">后一天</button></span></div>
        <svg v-if="ov.series.length" class="curve" viewBox="0 0 960 180" preserveAspectRatio="none" role="img" aria-label="总表功率曲线">
          <line v-if="ov.contract_kw" x1="0" x2="960" :y1="y(ov.contract_kw)" :y2="y(ov.contract_kw)" class="cl" />
          <rect v-for="(p, i) in ov.series" :key="i" :x="x(p.ts)" :width="9" :y="y(p.kw)" :height="170 - y(p.kw)" :class="p.bucket" />
        </svg>
        <p class="small muted">虚线：合同需量 {{ ov.contract_kw }} kW。横轴 0–24 点。</p>
      </div>
      <div class="card" data-help="energy-units">
        <h3>每台设备的电量（度）</h3>
        <div v-for="u in ov.units" :key="u.unit" class="bar-row">
          <span class="bn">{{ u.unit.toUpperCase() }} <span class="muted">{{ u.name }}</span></span>
          <span class="bar"><span v-for="s in ORDER" :key="s" :class="'st-' + s" :style="{ width: w(u.by_state[s]) }" :title="(ov.state_names[s] || s) + ' ' + (u.by_state[s] || 0) + ' 度'"></span></span>
          <span class="bv small">{{ num(u.kwh) }}<span v-if="u.by_state.idle && u.unit !== 'ht-01'" class="muted">（空转 {{ pct(u.idle_share) }}）</span></span>
        </div>
        <p class="small"><span v-for="s in ORDER" :key="s" class="lg"><i :class="'sw st-' + s"></i>{{ ov.state_names[s] }}</span>
          <span class="muted">· 热处理炉空闲 = 保温</span></p>
      </div>
      <div class="card">
        <h3>节能设定（车间正在用）</h3>
        <p class="small">空闲自动待机：<template v-if="Object.keys(ov.settings.standby).length">{{ Object.entries(ov.settings.standby).map(([u, m]) => u.toUpperCase() + ' ' + m + ' 分钟').join('、') }}</template><span v-else class="muted">没有</span>
          · 错峰：<template v-if="ov.settings.tou.length">{{ ov.settings.tou.map((u) => u.toUpperCase()).join('、') }} 峰时不开新炉</template><span v-else class="muted">没有</span>
          <template v-if="ov.settings.quiet.length"> · 隔声罩：{{ ov.settings.quiet.map((u) => u.toUpperCase()).join('、') }}</template></p>
        <p class="small muted">改设定走厂情中枢的方案（“空转能耗高”“峰时用电占比高”异常的右栏），厂长批准后下发车间。</p>
      </div>
      <div v-if="ov.teacher" class="card">
        <h3>老师：能源模拟器 <span class="small" :class="ov.sim ? 'ok' : 'muted'">{{ ov.sim ? '开（会出问题）' : '关' }}</span></h3>
        <div class="row small">
          <button class="btn sm" @click="sim({ sim: !ov.sim })">{{ ov.sim ? '关闭' : '打开' }}</button>
          <select v-model="inj.kind" aria-label="问题"><option v-for="(l, k) in FAULTS" v-show="k !== 'ht_peak' || ov.units.some((x) => x.unit === 'ht-01')" :key="k" :value="k">{{ l }}</option></select>
          <select v-if="['forgot', 'degrade'].includes(inj.kind)" v-model="inj.unit" aria-label="设备"><option v-for="u in ov.units.filter((x) => x.unit !== 'ht-01')" :key="u.unit" :value="u.unit">{{ u.unit.toUpperCase() }}</option></select>
          <button class="btn sm danger" @click="sim({ inject: { ...inj } })">注入</button>
        </div>
        <ul v-if="ov.faults.length" class="small"><li v-for="f in ov.faults" :key="f.key">{{ f.name }}{{ f.unit ? '（' + f.unit.toUpperCase() + '）' : '' }} · {{ f.by }} · {{ f.at?.slice(11, 16) }}
          <button class="linkbtn" @click="sim({ clear: f.key })">清除</button></li></ul>
        <p class="small muted">计量一直开（只记数，不改车间）；模拟器打开时大约每 30 分钟可能出一个问题：下班忘关、漏气、劣化、油雾收集器故障。重载实验 7 情景后关闭。</p>
      </div>
    </template>

    <!-- ② 计量点 -->
    <template v-if="tab === 'meters'">
      <div class="card">
        <div class="row"><select v-model="meter" aria-label="计量点" @change="loadSeries"><option v-for="m in meters" :key="m.code" :value="m.code">{{ m.code }} {{ m.label }}（{{ m.unit }}）</option></select>
          <select v-model.number="hours" aria-label="时长" @change="loadSeries"><option :value="24">24 小时</option><option :value="72">3 天</option><option :value="168">7 天</option></select></div>
        <svg v-if="ser.length" class="curve" viewBox="0 0 960 180" preserveAspectRatio="none" role="img" aria-label="计量点曲线">
          <rect v-for="(p, i) in ser" :key="i" :x="i * 960 / ser.length" :width="Math.max(1, 960 / ser.length - 1)" :y="ys(p.value)" :height="170 - ys(p.value)" :class="p.bucket || 'flat'" />
        </svg>
        <p v-else class="small muted">这段时间没有读数。</p>
        <p v-if="ser.length" class="small muted">每格 15 分钟的{{ meter.startsWith('ENV') ? '平均值' : '用量' }}；合计 {{ num(ser.reduce((a, p) => a + p.value, 0)) }}{{ meters.find((m) => m.code === meter)?.unit }}{{ meter.startsWith('ENV') ? '（累加没有意义）' : '' }}</p>
      </div>
      <div class="card"><table class="tbl small"><thead><tr><th>编号</th><th>名称</th><th>介质</th><th>单位</th><th>设备</th><th class="num">运行 / 空转 / 待机 kW</th></tr></thead>
        <tbody><tr v-for="m in meters" :key="m.code"><td>{{ m.code }}</td><td>{{ m.label }}</td><td>{{ m.medium }}</td><td>{{ m.unit }}</td><td>{{ m.machine || '—' }}</td>
          <td class="num">{{ m.power?.join(' / ') || '—' }}</td></tr></tbody></table></div>
    </template>

    <!-- ③ 单耗 -->
    <template v-if="tab === 'unit' && un">
      <div class="card">
        <h3>单件运行电量（度 / 件）</h3>
        <table class="tbl small"><thead><tr><th>设备</th><th>物料</th><th class="num">最近几件</th><th class="num">每件</th><th class="num">基线</th><th>基线来自</th><th class="num">变化</th></tr></thead>
          <tbody><tr v-for="x in un.rows" :key="x.unit + x.item"><td>{{ x.unit.toUpperCase() }}</td><td>{{ x.item }}</td><td class="num">{{ x.recent_parts }}</td><td class="num">{{ x.recent ?? '—' }}</td>
            <td class="num">{{ x.base ?? '—' }}</td><td>{{ x.base_from === 'history' ? '近 7 天' : '标准值 × 1.08' }}</td>
            <td class="num" :class="{ bad: x.change > 0.25 }">{{ x.change === null ? '—' : (x.change > 0 ? '+' : '') + pct(x.change) }}</td></tr></tbody></table>
        <p class="small muted">标准值 = 运行功率 × 这台设备上这道工序的标准工时。高 25% 以上厂情中枢报“单耗突增”：多半是主轴轴承、刀具 / 砂轮在劣化。</p>
      </div>
      <div class="card">
        <h3>近 12 小时空转</h3>
        <table class="tbl small"><thead><tr><th>设备</th><th class="num">电量</th><th class="num">空转电量</th><th class="num">空转小时</th><th class="num">占比</th></tr></thead>
          <tbody><tr v-for="x in [...un.idle].sort((a, b) => b.idle_kwh - a.idle_kwh)" :key="x.unit"><td>{{ x.unit.toUpperCase() }} <span class="muted">{{ x.name }}</span></td>
            <td class="num">{{ x.kwh }}</td><td class="num">{{ x.idle_kwh }}</td><td class="num">{{ x.idle_h }}</td><td class="num" :class="{ warn: x.idle_share > 0.3 }">{{ pct(x.idle_share) }}</td></tr></tbody></table>
      </div>
      <div class="card small">
        <h3>公用</h3>
        <p>空压机近 {{ un.air.hours }} 小时平均 {{ un.air.actual_kw }} kW，按开着的用气设备应 {{ un.air.expected_kw }} kW，<b :class="{ bad: un.air.excess_kw > 3 }">多出 {{ un.air.excess_kw }} kW</b>{{ un.air.excess_kw > 3 ? '（可能漏气）' : '' }}。</p>
        <p>近 24 小时峰时电量 {{ num(un.peak.peak_kwh) }} 度，占 {{ pct(un.peak.share) }}；其中热处理炉 {{ num(un.peak.ht_peak_kwh) }} 度。</p>
      </div>
    </template>

    <!-- ④ 碳与环境 -->
    <template v-if="tab === 'carbon' && cb">
      <div class="card">
        <h3>{{ cb.month }} 碳核算（{{ cb.scope }}）</h3>
        <p class="small">用电 <b>{{ num(cb.kwh) }}</b> 度（{{ cb.hours }} 小时的数据）× 排放因子 {{ cb.factor }} kg/度 = <b>{{ cb.t_co2e }}</b> 吨 CO2e；
          自来水 {{ cb.water_m3 }} m³，压缩空气 {{ num(cb.air_m3) }} m³。</p>
        <table class="tbl small"><thead><tr><th>设备</th><th class="num">电量</th><th class="num">碳（kg）</th><th class="num">件数</th><th class="num">每件（全口径，度）</th></tr></thead>
          <tbody><tr v-for="x in cb.units" :key="x.unit"><td>{{ x.unit.toUpperCase() }} <span class="muted">{{ x.name }}</span></td><td class="num">{{ num(x.kwh) }}</td><td class="num">{{ num(x.co2_kg) }}</td>
            <td class="num">{{ x.parts }}</td><td class="num">{{ x.kwh_per_part ?? '—' }}</td></tr></tbody></table>
        <h3>每件产品的碳足迹（全口径：各工序设备的电量 ÷ 件数，加上空压机、照明按件分摊）</h3>
        <ul class="small"><li v-for="p in cb.products" :key="p.item">{{ p.item }}：每件约 {{ p.kwh }} 度、<b>{{ p.co2_kg }} kg CO2e</b>（{{ p.ops }} 道工序）
          <span v-if="p.missing.length" class="muted">；{{ p.missing.map((u) => u.toUpperCase()).join('、') }} 这个月还没做过件，没算进去</span></li></ul>
        <p class="small muted">开工率低时每件分摊的保温、空转很多，全口径会比“运行功率 × 工时”大得多。</p>
      </div>
      <div v-if="env" class="card">
        <h3>车间环境（近 24 小时，15 分钟平均）</h3>
        <div v-for="(v, k) in env.now" :key="k" class="envr">
          <span class="bn">{{ v.label }}</span>
          <svg class="mini" viewBox="0 0 480 60" preserveAspectRatio="none" role="img" :aria-label="v.label">
            <line x1="0" x2="480" :y1="ye(v.limit, k)" :y2="ye(v.limit, k)" class="cl" />
            <polyline :points="(env.series[k] || []).map((p, i, a) => (i * 480 / Math.max(1, a.length - 1)).toFixed(1) + ',' + ye(p.value, k).toFixed(1)).join(' ')" class="pl" />
          </svg>
          <span class="small" :class="{ bad: v.over }">{{ v.value ?? '—' }} {{ v.unit }}（限值 {{ v.limit }}）</span>
        </div>
        <p class="small muted">油雾按开着的湿式加工设备数，噪声按运行设备声级叠加。超限厂情中枢报“车间环境指标超限”，整改走安全环保的整改工单。</p>
      </div>
      <div class="card">
        <h3>参数</h3>
        <div class="row small">
          <label>峰 $<input v-model.number="pm.price.peak" type="number" step="0.01" :disabled="!pm.can_edit"></label>
          <label>平 $<input v-model.number="pm.price.flat" type="number" step="0.01" :disabled="!pm.can_edit"></label>
          <label>谷 $<input v-model.number="pm.price.valley" type="number" step="0.01" :disabled="!pm.can_edit"></label>
          <label>排放因子 <input v-model.number="pm.co2_factor" type="number" step="0.0001" :disabled="!pm.can_edit"> kg/度</label>
          <label>合同需量 <input v-model.number="pm.contract_kw" type="number" step="1" :disabled="!pm.can_edit"> kW</label>
          <label>油雾限值 <input v-model.number="pm.mist_limit" type="number" step="0.1" :disabled="!pm.can_edit"></label>
          <label>噪声限值 <input v-model.number="pm.noise_limit" type="number" step="1" :disabled="!pm.can_edit"></label>
          <button v-if="pm.can_edit" class="btn sm" @click="saveParams">保存</button>
        </div>
        <p class="small muted">峰 8–11、18–21 点；谷 23–7 点；其余平。排放因子默认用全国电网平均值，可按所在地区改。只有厂长能改。</p>
      </div>
    </template>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post } from '../lib/api';

const TABS = { overview: '总览', meters: '计量点', unit: '单耗', carbon: '碳与环境' };
const ORDER = ['run', 'setup', 'idle', 'standby', 'down', 'off'];
const FAULTS = { forgot: '下班忘关', degrade: '设备劣化（单耗上升）', leak: '压缩空气泄漏', ht_peak: '峰时开炉', mist: '油雾收集器故障' };
const route = useRoute();
const router = useRouter();
const tab = ref(TABS[route.query.tab] ? route.query.tab : 'overview');
const err = ref('');
const msg = ref('');
const ov = ref(null);
const un = ref(null);
const cb = ref(null);
const env = ref(null);
const meters = ref([]);
const meter = ref('E-TOTAL');
const hours = ref(24);
const ser = ref([]);
const day = ref('');
const pm = reactive({ price: { peak: 0, flat: 0, valley: 0 }, co2_factor: 0, contract_kw: 0, mist_limit: 0, noise_limit: 0, can_edit: false });
const inj = reactive({ kind: 'forgot', unit: '' });
const num = (v) => (v === null || v === undefined ? '—' : Math.round(v).toLocaleString());
const money = (v) => (v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (v) => (v === null || v === undefined ? '—' : Math.round(v * 100) + '%');

const maxKw = () => Math.max(ov.value?.contract_kw || 0, ...((ov.value?.series || []).map((p) => p.kw || 0)), 1) * 1.1;
const y = (kw) => 170 - 165 * (kw || 0) / maxKw();
function x(ts) {          // 读数时间带工厂时区（如 2026-10-07T08:15:00-04:00），直接取钟点
  const h = Number(ts.slice(11, 13)) + Number(ts.slice(14, 16)) / 60;
  return Math.max(0, Math.min(950, isNaN(h) ? 0 : h * 40));
}
const maxS = () => Math.max(...ser.value.map((p) => p.value), 0.001) * 1.1;
const ys = (v) => 170 - 165 * (v || 0) / maxS();
const ye = (v, k) => { const top = k === 'noise' ? 100 : 10; const bot = k === 'noise' ? 50 : 0; return 58 - 56 * Math.max(0, Math.min(1, ((v || 0) - bot) / (top - bot))); };
function w(v) { const m = Math.max(...(ov.value?.units || []).map((u) => u.kwh), 1); return ((v || 0) / m * 100).toFixed(2) + '%'; }

function go(k) { tab.value = k; router.replace({ query: { ...route.query, tab: k } }); load(); }
async function wrap(fn) { err.value = ''; try { await fn(); } catch (e) { err.value = e.message; } }
function load() {
  wrap(async () => {
    ov.value = await get('/energy/overview' + (day.value ? '?day=' + day.value : ''));
    if (!inj.unit) inj.unit = (ov.value.units.find((x) => x.unit === 'hmc-01') || ov.value.units[0] || {}).unit || '';
  });
  if (tab.value === 'meters') wrap(async () => { meters.value = (await get('/energy/meters')).meters; loadSeries(); });
  if (tab.value === 'unit') wrap(async () => { un.value = await get('/energy/unit'); });
  if (tab.value === 'carbon') {
    wrap(async () => { cb.value = await get('/energy/carbon'); });
    wrap(async () => { env.value = await get('/energy/env'); });
    wrap(async () => { Object.assign(pm, await get('/energy/params')); });
  }
}
function shift(n) {
  const d = new Date((ov.value?.day || new Date().toISOString().slice(0, 10)) + 'T12:00:00');
  d.setDate(d.getDate() + n);
  day.value = d.toISOString().slice(0, 10);
  load();
}
async function loadSeries() { await wrap(async () => { ser.value = (await get(`/energy/meters/${meter.value}/series?hours=${hours.value}`)).series; }); }
async function saveParams() {
  await wrap(async () => {
    await post('/energy/params', { price: pm.price, co2_factor: pm.co2_factor, contract_kw: pm.contract_kw, mist_limit: pm.mist_limit, noise_limit: pm.noise_limit });
    msg.value = '参数已保存'; load();
  });
}
async function sim(body) { await wrap(async () => { const r = await post('/energy/sim', body); msg.value = r.text || ('模拟器' + (r.sim ? '已打开' : '已关闭')); load(); }); }
load();
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.tabs { margin-left: auto; display: flex; gap: 4px; flex-wrap: wrap; }
.tabs button { height: 30px; padding: 0 12px; border: 1px solid var(--line); background: var(--surface); border-radius: 6px; cursor: pointer; }
.tabs button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; margin-bottom: 12px; }
.k { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; }
.k b { font-size: 22px; }
.ch { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.ch .row { margin-left: auto; }
.curve { width: 100%; height: 180px; display: block; background: var(--surface-2); border-radius: 6px; }
.curve .peak, .sw.peak { fill: #E0605A; background: #E0605A; }
.curve .flat, .sw.flat { fill: #E8B04A; background: #E8B04A; }
.curve .valley, .sw.valley { fill: #5B9BD5; background: #5B9BD5; }
.cl { stroke: var(--bad); stroke-dasharray: 6 4; stroke-width: 1.5; }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin: 0 3px 0 8px; vertical-align: middle; }
.bar-row { display: grid; grid-template-columns: 170px 1fr 120px; gap: 8px; align-items: center; margin: 3px 0; }
.bn { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar { display: flex; height: 14px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }
.bar span { display: block; height: 100%; }
.st-run { background: #3C8D5A; }
.st-setup { background: #8BBF9C; }
.st-idle { background: #9A9A9A; }
.st-standby { background: #C9D7E8; }
.st-down { background: #D0655F; }
.st-off { background: transparent; }
.sw.st-off { border: 1px solid var(--line); }
.lg { margin-right: 4px; }
.bv { text-align: right; }
.envr { display: grid; grid-template-columns: 90px 1fr 190px; gap: 8px; align-items: center; margin: 6px 0; }
.mini { width: 100%; height: 60px; background: var(--surface-2); border-radius: 4px; }
.pl { fill: none; stroke: var(--accent); stroke-width: 1.5; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
select, input { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; min-width: 0; }
input[type=number] { width: 80px; }
.card .tbl { display: block; overflow-x: auto; }
.bad { color: var(--bad); }
.warn { color: var(--warn); }
.ok { color: var(--good); }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; padding: 0 4px; }
.btn.sm { height: 28px; padding: 0 10px; }
h3 { font-size: 14px; margin: 8px 0 6px; }
.num { text-align: right; }
@media (max-width: 600px) {
  .bar-row { grid-template-columns: 90px 1fr 70px; }
  .envr { grid-template-columns: 1fr; }
}
</style>
