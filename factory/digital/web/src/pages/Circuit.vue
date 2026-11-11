<!-- 第 79 轮（电子 E1）：电路分析。关节伺服驱动板 DRV-JOINT 的 6 道例题（原理图、参数、曲线、读数与公式对照、容差、计算书）+ 网表模式。
     例题默认在浏览器里跑 ngspice（WebAssembly，随网页放在我们自己的服务器上），也可以交给服务器 ngspice；网表模式与蒙特卡洛在服务器上跑。 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ t('电路分析') }}</h1>
      <span class="muted">{{ t('关节伺服驱动板 DRV-JOINT 上的电路：改参数、看曲线和读数，每个读数都和手算公式对照（ngspice 求解；参数是示例值）') }}</span></div>
    <div class="tabs">
      <button v-for="e in examples" :key="e.key" class="tab" :class="{ on: mode === 'ex' && key === e.key }" @click="pick(e.key)">{{ e.no }} {{ isEn() ? e.title_en || t(e.title) : e.title }}</button>
      <button class="tab" :class="{ on: mode === 'net' }" @click="mode = 'net'">{{ t('网表模式') }}</button>
    </div>
    <div v-if="err" class="err">{{ err }}</div>

    <template v-if="mode === 'ex' && ex">
      <section class="card">
        <p class="q"><b>{{ t('问题') }}</b> {{ isEn() ? ex.question_en || ex.question : ex.question }}</p>
        <SchematicView :items="SCHEMATICS[key] || []" :params="params" @pick="focusParam" />
        <div v-if="SHEET[key]" class="small"><router-link :to="'/pcb-design?tab=sch&sheet=' + SHEET[key]">{{ t('打开驱动板原理图里的这一页 →') }}</router-link> {{ t('（KiCad 设计用的是同一组数）') }}</div>
        <div class="params">
          <label v-for="p in ex.params" :key="p.key" :class="{ hl: hl === p.key }">{{ t(p.label) }}
            <input :ref="(el) => (inputs[p.key] = el)" v-model.number="params[p.key]" type="number" step="any" :min="p.min" :max="p.max"></label>
        </div>
        <div class="line">
          <span class="small">{{ t('在哪儿算') }}</span>
          <label class="chk"><input v-model="engine" type="radio" value="browser"> {{ t('浏览器（本机，不占服务器）') }}</label>
          <label class="chk"><input v-model="engine" type="radio" value="server"> {{ t('服务器') }}</label>
          <button class="btn primary" :disabled="busy" @click="runEx">{{ busy ? busyText : t('运行|按钮') }}</button>
          <button class="btn" :disabled="busy" @click="reset">{{ t('恢复默认') }}</button>
          <span v-if="took" class="small muted">{{ took }}</span>
        </div>
      </section>

      <section v-if="res" class="card">
        <div class="card-head"><h2>{{ t('读数与公式对照') }}</h2></div>
        <table class="tbl">
          <thead><tr><th>{{ t('读数') }}</th><th class="num">{{ t('仿真') }}</th><th class="num">{{ t('公式') }}</th><th class="num">{{ t('差') }}</th><th class="num">{{ t('允许') }}</th><th></th></tr></thead>
          <tbody><tr v-for="r in res.compare" :key="r.name">
            <td>{{ t(r.label) }}</td><td class="num mono">{{ si(r.sim, r.unit) }}</td><td class="num mono">{{ si(r.formula, r.unit) }}</td>
            <td class="num">{{ r.diff == null ? '—' : (100 * r.diff).toFixed(2) + '%' }}</td><td class="num muted">{{ (100 * r.allow).toFixed(0) }}%</td>
            <td><span :class="r.ok ? 'ok' : 'bad-t'">{{ r.ok ? '✓' : '✗' }}</span></td></tr></tbody>
        </table>
        <p v-if="built.note_formula" class="small muted">{{ t('说明：') }}{{ t(built.note_formula) }}</p>
        <div v-if="built.derived" class="derived small">
          <span v-for="(v, k) in built.derived" :key="k" class="chip"><span class="muted">{{ DERIVED[k] ? t(DERIVED[k]) : k }}</span> <b class="mono">{{ v === true ? t('是') : v === false ? t('否') : v }}</b></span>
        </div>
        <div v-for="(names, an) in built.plots" :key="an">
          <SpiceChart v-if="plots[an]" :ref="(c) => (charts[an] = c)" :title="ANALYSIS[an] ? t(ANALYSIS[an]) : an" :plot="plots[an]" :show="names" :kind="kindOf(an)" />
          <button v-if="plots[an] && kindOf(an) === 'tran'" class="btn sm" @click="toScope(an, names)">{{ t('送到示波器（虚拟仪器）') }}</button>
        </div>
        <div class="line">
          <button v-if="built.mc" class="btn" :disabled="busy" @click="runMc">{{ t('容差分析（蒙特卡洛 200 次，服务器）') }}</button>
          <button class="btn" :disabled="busy" @click="report">{{ t('下载计算书（Word）') }}</button>
        </div>
        <div v-if="mc" class="mc small">
          <div>{{ t('元件按容差（{tol}）随机取值 {n} 次：', { tol: Object.entries(mc.tol).map(([k, v]) => k + ' ±' + (100 * v) + '%').join(', '), n: mc.n }) }}
            <b>{{ READ[mc.meas] ? t(READ[mc.meas]) : mc.meas }}</b> {{ t('均值') }} <b class="mono">{{ si(mc.mean) }}</b>, {{ t('标准差') }} <b class="mono">{{ si(mc.std) }}</b>,
            {{ t('3σ 区间') }} <b class="mono">[{{ si(mc.lo3) }}, {{ si(mc.hi3) }}]</b> {{ t('（名义 {v}）', { v: si(mc.nominal) }) }}</div>
          <svg viewBox="0 0 400 90" class="hist"><rect v-for="(h, i) in mc.hist" :key="i" :x="i * 20 + 1" :y="88 - 84 * h / Math.max(...mc.hist)" width="18" :height="84 * h / Math.max(...mc.hist)" /></svg>
        </div>
        <details class="small"><summary>{{ t('网表（浏览器和服务器用的是同一张）') }}</summary>
          <div v-for="(n, an) in built.netlists" :key="an"><div class="muted">[{{ ANALYSIS[an] ? t(ANALYSIS[an]) : an }}]</div><pre>{{ n }}</pre></div></details>
      </section>
    </template>

    <template v-if="mode === 'net'">
      <section class="card">
        <p class="small muted">{{ t('贴一段 SPICE 网表（第一行是标题；支持 .op .dc .ac .tran .meas 等分析语句和常见器件；不支持读写文件、.control 段）。在服务器上算。') }}</p>
        <textarea v-model="net" rows="12" class="netin mono" spellcheck="false"></textarea>
        <div class="line"><button class="btn" :disabled="busy" @click="checkNet">{{ t('检查') }}</button>
          <button class="btn primary" :disabled="busy" @click="runNet">{{ busy ? t('正在算…') : t('运行|按钮') }}</button>
          <span v-if="netChk" class="small" :class="netChk.errors.length ? 'bad-t' : 'ok'">{{ netChk.errors.length ? netChk.errors.join('; ') : t('没问题，节点：') + netChk.nodes.join(', ') }}</span></div>
      </section>
      <section v-if="netRes" class="card">
        <div v-if="Object.keys(netRes.meas).length" class="derived small"><span v-for="(v, k) in netRes.meas" :key="k" class="chip">{{ k }} <b class="mono">{{ si(v) }}</b></span></div>
        <p v-if="netRes.errors.length" class="small bad-t">{{ netRes.errors.join('; ') }}</p>
        <div v-for="(p, i) in netRes.plots" :key="i">
          <div class="line small"><b>{{ p.plot }}</b>
            <label v-for="n in p.names.slice(1)" :key="n" class="chk"><input v-model="netSel[i]" type="checkbox" :value="n"> {{ n }}</label></div>
          <SpiceChart v-if="(netSel[i] || []).length" :title="p.plot" :plot="p" :show="netSel[i]" :kind="p.plot.startsWith('AC') ? 'ac' : p.plot.startsWith('DC') ? 'dc' : 'tran'" />
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post, session } from '../lib/api';
import { SCHEMATICS } from '../lib/schematics';
import SchematicView from '../components/SchematicView.vue';
import SpiceChart from '../components/SpiceChart.vue';
import { isEn, t, tk } from '../lib/i18n';

const router = useRouter();
const route = useRoute();
// 第 88 轮：例题 ↔ 驱动板 KiCad 原理图的那一页
const SHEET = { sense: 'sense', gate: 'gate', bus: 'power', encoder: 'io' };
const ANALYSIS = { dc: tk('直流扫描'), ac: tk('交流（波特图）'), tran: tk('瞬态'), open: tk('开环（电压阶跃）'), qgd: tk('量 Q_gd') };
const DERIVED = {
  i_peak_A: tk('峰值相电流 A'), i_rated_A: tk('额定相电流 A'), shunt_mV_at_peak: tk('峰值时采样电压 mV'), p_shunt_W_rated: tk('额定电流下采样电阻功耗 W'),
  headroom_V: tk('峰值时离 ADC 下限 V'), i_load_A: tk('负载电流 A'), vplat_internal_V: tk('芯片内平台电压 V'), ig_on_A: tk('平台期栅电流 A'),
  f0_Hz: tk('LC 谐振频率 Hz'), Z0_ohm: tk('特征阻抗 Ω'), Q: tk('品质因数 Q'), ripple_cap_V: tk('电容项纹波 V'), ripple_esr_V: tk('ESR 项纹波 V'),
  f_pulse_Hz: tk('编码器脉冲频率 Hz'), tau_ns: tk('RC 时间常数 ns'), fc_over_fpulse: tk('截止频率 / 脉冲频率'), duty: tk('占空比'), fc_LC_Hz: tk('输出 LC 频率 Hz'),
  r_load_ohm: tk('负载电阻 Ω'), tau_e_ms: tk('电气时间常数 ms'), Kp_V_per_A: tk('Kp V/A'), Ki_V_per_As: tk('Ki V/(A·s)'), u_needed_V: tk('阶跃需要的电压 V'),
  vbus_V: tk('母线电压 V'), saturated: tk('电压饱和'),
};
const examples = ref([]);
const key = ref(String(route.query.ex || 'sense'));
const mode = ref('ex');
const params = reactive({});
const built = ref(null);
const res = ref(null);
const plots = reactive({});
const charts = reactive({});
const inputs = reactive({});
const engine = ref('browser');
const busy = ref(false);
const busyText = ref('');
const took = ref('');
const err = ref('');
const hl = ref('');
const mc = ref(null);
const READ = ref({});
const ex = computed(() => examples.value.find((e) => e.key === key.value));
const net = ref((isEn() ? 'RC low-pass' : 'RC 低通') + '\nV1 in 0 DC 0 AC 1 PULSE(0 1 0 1n 1n 0.5m 1m)\nR1 in out 1k\nC1 out 0 100n\n.tran 2u 3m\n.ac dec 20 10 1meg\n.meas tran trise TRIG v(out) VAL=0.1 RISE=1 TARG v(out) VAL=0.9 RISE=1\n.end\n');   // i18n-ok 网表标题
const netChk = ref(null);
const netRes = ref(null);
const netSel = reactive({});

function si(v, unit = '') {
  if (v == null || !isFinite(v)) return '—';
  const a = Math.abs(v);
  if (unit === '' || unit === 'dB') return (+v.toPrecision(4)).toString() + (unit ? ' ' + unit : '');
  const P = [[1e9, 'G'], [1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'μ'], [1e-9, 'n'], [1e-12, 'p']];
  for (const [k, s] of P) if (a >= k * 0.999) return (+(v / k).toPrecision(4)) + ' ' + s + unit;
  return v.toExponential(3) + ' ' + unit;
}
function kindOf(an) { return an === 'dc' ? 'dc' : an === 'ac' ? 'ac' : 'tran'; }
function clear() { res.value = null; mc.value = null; took.value = ''; for (const k of Object.keys(plots)) delete plots[k]; }
function pick(k) { key.value = k; mode.value = 'ex'; reset(); }
function reset() {
  for (const k of Object.keys(params)) delete params[k];
  Object.assign(params, ex.value?.defaults || {});
  built.value = null;
  clear();
}
function focusParam(k) { hl.value = k; inputs[k]?.focus(); setTimeout(() => { if (hl.value === k) hl.value = ''; }, 1500); }

async function runEx() {
  busy.value = true; err.value = ''; clear();
  const t0 = performance.now();
  try {
    busyText.value = t('准备网表…');
    built.value = await post(`/circuit/examples/${key.value}/build`, { params: { ...params } });
    READ.value = Object.fromEntries(Object.entries(built.value.readings).map(([k, v]) => [k, v.label]));
    if (engine.value === 'server') {
      busyText.value = t('服务器在算…');
      const r = await post(`/circuit/examples/${key.value}/simulate`, { params: built.value.params });
      for (const [an, v] of Object.entries(r.by_analysis)) if (v.plots[0]) plots[an] = v.plots[0];
      res.value = { compare: r.compare, meas: r.meas };
      took.value = t('服务器 ngspice，用时 {s} 秒', { s: ((performance.now() - t0) / 1000).toFixed(1) });
    } else {
      busyText.value = t('载入浏览器里的 ngspice（第一次约 5 MB）…');
      const spice = await import('../lib/spice.js');
      await spice.ready();
      const meas = {};
      for (const [an, n] of Object.entries(built.value.netlists)) {
        busyText.value = t('浏览器在算：{a}…', { a: ANALYSIS[an] ? t(ANALYSIS[an]) : an });
        const r = await spice.run(n);
        if (r.errors.length) throw new Error(r.errors.join('; '));
        Object.assign(meas, r.meas);
        plots[an] = r.plot;
      }
      const c = await post(`/circuit/examples/${key.value}/compare`, { params: built.value.params, meas });
      res.value = { compare: c.compare, meas };
      took.value = t('浏览器 ngspice（WebAssembly），用时 {s} 秒', { s: ((performance.now() - t0) / 1000).toFixed(1) });
    }
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
async function runMc() {
  busy.value = true; err.value = '';
  try { mc.value = await post(`/circuit/examples/${key.value}/montecarlo`, { params: built.value.params, n: 200, seed: 1 }); } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
async function svgPng(el) {
  const xml = new XMLSerializer().serializeToString(el);
  const img = new Image();
  img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(xml);
  await img.decode();
  const c = document.createElement('canvas');
  c.width = 1280; c.height = 480;
  c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL('image/png');
}
async function report() {
  busy.value = true; err.value = '';
  try {
    const images = [];
    for (const [an, c] of Object.entries(charts)) {
      if (c?.svg) images.push({ data: await svgPng(c.svg), caption: (ANALYSIS[an] || an) + '：' + (built.value.plots[an] || []).join('、') });   // i18n-ok 计算书是中文 Word（第三批）
    }
    const r = await fetch(`/api/circuit/examples/${key.value}/report`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'x-wq-token': session.token },
      body: JSON.stringify({ params: built.value.params, meas: res.value.meas, images, mc: mc.value }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || t('计算书生成失败'));
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await r.blob());
    a.download = isEn() ? `circuit-report-${ex.value.key}.docx` : `电路分析计算书-${ex.value.title}.docx`;   // i18n-ok 中文文件名
    document.body.appendChild(a); a.click(); a.remove();
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
// 第 82 轮：瞬态曲线送到虚拟仪器的示波器（带示波器自己的带宽、量化和噪声）
function toScope(an, names) {
  const p = plots[an];
  const tt = p.data[p.names[0]];
  const keep = names.filter((n) => p.data[n]).slice(0, 4);
  try {
    sessionStorage.setItem('wq-scope-import', JSON.stringify({ title: t('例题 {n} {x} · {a}', { n: ex.value.no, x: isEn() ? ex.value.title_en || t(ex.value.title) : ex.value.title, a: ANALYSIS[an] ? t(ANALYSIS[an]) : an }), names: keep, t: tt, series: keep.map((n) => p.data[n]) }));
  } catch (e) { err.value = t('浏览器不让存临时数据（无痕窗口？）'); return; }
  router.push({ path: '/instruments', query: { task: 'import' } });
}
async function checkNet() {
  err.value = '';
  try { netChk.value = await post('/circuit/check', { netlist: net.value }); } catch (e) { err.value = e.message; }
}
async function runNet() {
  busy.value = true; err.value = ''; netRes.value = null;
  try {
    netRes.value = await post('/circuit/run', { netlist: net.value });
    netRes.value.plots.forEach((p, i) => { netSel[i] = p.names.slice(1).filter((n) => n.startsWith('v(')).slice(0, 3); });
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}

onMounted(async () => {
  try {
    const r = await get('/circuit/examples');
    examples.value = r.examples;
    reset();
  } catch (e) { err.value = e.message; }
});
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.page-title h1 { white-space: nowrap; }
.tabs { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 10px; }
.tab { border: 1px solid var(--line); background: var(--surface); border-radius: 16px; padding: 4px 12px; cursor: pointer; font-size: 13px; }
.tab.on { background: var(--brand, #2563eb); color: #fff; border-color: transparent; }
.q { margin: 0 0 8px; }
.params { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 10px 0; }
.params label { display: flex; flex-direction: column; font-size: 12px; gap: 2px; padding: 2px 4px; border-radius: 6px; }
.params label.hl { background: #fff3c4; }
.params input { width: 120px; height: 28px; border: 1px solid var(--line); border-radius: 6px; padding: 0 6px; }
.line { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; margin: 6px 0; }
.chk { font-size: 13px; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; }
.num { text-align: right; }
.ok { color: var(--good, #16a34a); } .bad-t { color: var(--bad, #dc2626); }
.derived { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 8px 0; }
.mc { background: var(--surface-2); border-radius: 6px; padding: 8px; margin: 8px 0; }
.hist { width: 100%; max-width: 420px; height: 90px; } .hist rect { fill: var(--brand, #2563eb); opacity: 0.7; }
pre { font-size: 12px; background: var(--surface-2); padding: 8px; border-radius: 6px; overflow-x: auto; }
.netin { width: 100%; font-size: 13px; border: 1px solid var(--line); border-radius: 6px; padding: 8px; box-sizing: border-box; }
@media (max-width: 600px) { .params input { width: 100px; } }
</style>
