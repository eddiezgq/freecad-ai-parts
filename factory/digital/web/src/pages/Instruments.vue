<!-- 第 82 轮（电子 E2）：虚拟仪器。左边选测量任务（被测对象与接线已摆好），右边是仪器；仪器和传感器都在浏览器里算（lib/instruments.js），
     服务器只给这位学生的随机种子、核对结果、出实验记录。“从电路分析送来”的波形也在这里用示波器看。 -->
<template>
  <div class="page">
    <div class="page-title"><h1>虚拟仪器</h1>
      <span class="muted">示波器、万用表、信号源、电源、逻辑分析仪、数据记录仪 + 6 种传感器：照实验桌的样子测量，算出结果交平台核对（参数是示例值，每人的数不同）</span></div>
    <div class="tabs">
      <button v-for="(t, i) in tasks" :key="t.key" class="tab" :class="{ on: task === t.key }" @click="go(t.key)">{{ i + 1 }} {{ t.title }}</button>
      <button v-if="imported" class="tab" :class="{ on: task === 'import' }" @click="go('import')">从电路分析送来的波形</button>
    </div>
    <div v-if="err" class="err">{{ err }}</div>

    <!-- ① 力矩传感器标定 -->
    <section v-if="task === 'torque'" class="card">
      <p class="small">{{ P.torque.note }}。按顺序加砝码（0→50→0 N·m），每一步用万用表读放大器输出，点“记录”。</p>
      <div class="bench">
        <div class="dut">
          <div class="lab">砝码（力矩）</div>
          <div class="steps"><button v-for="(T, i) in P.torque.points_nm" :key="i" class="stp" :class="{ on: tq.step === i }" @click="tq.step = i">
            {{ T }}<small>{{ i > 5 ? '↓' : i > 0 ? '↑' : '' }}</small></button></div>
          <div class="small muted">现在：{{ tqT }} N·m（{{ tq.step > 5 ? '卸载' : '加载' }}）　供桥电源 {{ P.torque.vex.toFixed(3) }} V　放大器增益 {{ P.torque.gain }}</div>
        </div>
        <DmmPanel :r="dmm" v-model:range="dmmRange" :hist="dmmHist" />
      </div>
      <div class="line"><button class="btn" @click="rec([tq.step + 1, tqT, tq.step > 5 ? '卸载' : '加载', fmtV(dmmMean)])">记录这一步（取最近 10 次读数的平均）</button>
        <button class="btn" @click="fitTorque">对加载段做最小二乘</button><span v-if="fitRes" class="small mono">{{ fitRes }}</span></div>
    </section>

    <!-- ② 编码器 -->
    <section v-if="task === 'encoder'" class="card">
      <p class="small">{{ P.encoder.note }}。电机以某个转速转（不告诉你多快、往哪转），A、B、Z 接示波器 CH1–CH3 和逻辑分析仪。</p>
      <p class="small">板上用专用芯片做这件事：<router-link to="/chip-design?tab=bench">编码器接口芯片 WQ-ENCIF——接上编码器，看它怎么滤毛刺、计数、用 SPI 交给 MCU →</router-link></p>
      <div class="bench">
        <div><ScopeScreen :traces="sc.traces" :vdiv="sc.vdiv" :off="sc.off" :tdiv="sc.tdiv" />
          <div class="line small">时基 <select v-model.number="sc.tdiv" @change="acquire"><option v-for="t in TDIVS" :key="t" :value="t">{{ si(t) }}s/格</option></select>
            <button class="btn sm" @click="acquire">单次触发</button>
            <span class="mono">CH1 频率 {{ si(scM?.freq) }}Hz，峰峰值 {{ si(scM?.vpp) }}V</span></div></div>
        <div class="la">
          <div class="lab">逻辑分析仪（阈值 2.5 V，四倍频解码）</div>
          <div class="line small">采集时长 <select v-model.number="la.span"><option v-for="s in [0.001, 0.01, 0.1, 0.5, 1]" :key="s" :value="s">{{ si(s) }}s</option></select>
            <button class="btn sm" @click="capture">采集</button></div>
          <div v-if="la.res" class="small mono">计数 {{ la.res.count }}（正向沿 {{ la.res.up }}，反向沿 {{ la.res.down }}）
            <div v-for="(z, i) in la.res.zs.slice(0, 6)" :key="i">Z{{ i + 1 }}：t = {{ si(z.t) }}s，此时计数 {{ z.count }}</div>
            <div v-if="!la.res.zs.length" class="muted">这段时间里没有 Z 脉冲，采集时间加长</div></div>
          <svg v-if="la.res" viewBox="0 0 400 90" class="latr"><polyline v-for="(k, j) in [1, 2, 3]" :key="j" :points="laPts(k, j)" fill="none" stroke="#2563eb" />
            <text x="2" y="20" class="tl">A</text><text x="2" y="50" class="tl">B</text><text x="2" y="80" class="tl">Z</text></svg>
        </div>
      </div>
    </section>

    <!-- ③ IMU -->
    <section v-if="task === 'imu'" class="card">
      <p class="small">{{ P.imu.note }}。数据记录仪记陀螺 Z 轴静置 2 小时（仿真瞬间完成），看平均值（零偏）和 Allan 偏差曲线：短 τ 段斜率 −1/2 读角度随机游走（ARW = σ(τ)·√τ，°/s·√s × 60 = °/√h），曲线最低点 ÷ 0.664 是零偏不稳定性。</p>
      <div class="line"><button class="btn primary" :disabled="busy" @click="runImu">{{ busy ? '记录中…' : '记录 2 小时' }}</button>
        <span v-if="imu.st" class="small mono">{{ imu.n.toLocaleString() }} 个点：平均 {{ imu.st.mean.toFixed(5) }} °/s，标准差 {{ imu.st.sd.toFixed(4) }} °/s</span></div>
      <svg v-if="imu.ad" viewBox="0 0 560 300" class="ll" @mousemove="llHover" @mouseleave="imu.h = null">
        <rect x="0" y="0" width="560" height="300" fill="#fff" />
        <g class="grid"><line v-for="x in llX" :key="'x' + x" :x1="lx(x)" :x2="lx(x)" y1="10" y2="270" /><line v-for="y in llY" :key="'y' + y" x1="60" x2="550" :y1="ly(y)" :y2="ly(y)" /></g>
        <g class="axt"><text v-for="x in llX" :key="'tx' + x" :x="lx(x)" y="288" text-anchor="middle">{{ si(x) }}</text>
          <text v-for="y in llY" :key="'ty' + y" x="56" :y="ly(y) + 4" text-anchor="end">{{ si(y) }}</text>
          <text x="550" y="300" text-anchor="end">τ（s）</text><text x="62" y="10">Allan 偏差 σ(τ)（°/s）</text></g>
        <polyline :points="imu.ad.map((p) => lx(p.tau) + ',' + ly(p.adev)).join(' ')" fill="none" stroke="#2563eb" stroke-width="2" />
        <circle v-for="(p, i) in imu.ad" :key="'c' + i" :cx="lx(p.tau)" :cy="ly(p.adev)" r="3" :fill="imu.h === i ? '#dc2626' : '#2563eb'" />
      </svg>
      <div v-if="imu.h != null" class="small mono">τ = {{ si(imu.ad[imu.h].tau) }}s，σ = {{ imu.ad[imu.h].adev.toExponential(3) }} °/s</div>
      <button v-if="imu.ad" class="btn sm" @click="rows.imu = imu.ad.map((p) => [si(p.tau), p.adev.toExponential(4)])">把 Allan 表放进记录</button>
    </section>

    <!-- ④ 霍尔电流传感器 -->
    <section v-if="task === 'hall'" class="card">
      <p class="small">{{ P.hall.note }}。直流：可编程电流源给电流、万用表读输出；交流：信号源给 1 A 幅值的正弦电流，示波器看输出幅值随频率的变化。</p>
      <div class="bench">
        <div class="dut"><div class="lab">直流电流源</div>
          <div class="line">电流 <input v-model.number="hl.I" type="number" step="1" min="-20" max="20" class="num"> A</div>
          <DmmPanel :r="dmm" v-model:range="dmmRange" :hist="dmmHist" />
          <button class="btn sm" @click="rec(['直流', hl.I, fmtV(dmmMean)])">记录（电流、输出平均）</button>
          <button class="btn sm" @click="fitHall">对直流点做最小二乘</button><div v-if="fitRes" class="small mono">{{ fitRes }}</div></div>
        <div><div class="lab">信号源 → 示波器</div>
          <div class="line small">频率 <input v-model.number="hl.f" type="number" min="10" max="10000000" class="num"> Hz　幅值 1 A
            伏/格 <select v-model.number="sc.vdiv[0]" @change="acquire"><option v-for="v in VDIVS" :key="v" :value="v">{{ si(v) }}V</option></select>
            <button class="btn sm" @click="acquire">单次触发</button></div>
          <ScopeScreen :traces="sc.traces" :vdiv="sc.vdiv" :off="sc.off" :tdiv="sc.tdiv" />
          <div class="small mono">CH1 峰峰值 {{ si(scM?.vpp) }}V，交流有效值 {{ si(scM?.acrms) }}V → 幅值 = 有效值 × √2 = {{ si(scM ? scM.acrms * Math.SQRT2 : null) }}V，频率 {{ si(scM?.freq) }}Hz</div>
          <div class="small muted">用有效值算幅值比用峰峰值准：峰峰值会被噪声撑大，信号小的时候尤其明显。</div>
          <button class="btn sm" @click="rec(['交流', hl.f, fmtV(scM ? scM.acrms * Math.SQRT2 : null)])">记录（频率、幅值）</button></div>
      </div>
    </section>

    <!-- ⑤ NTC -->
    <section v-if="task === 'ntc'" class="card">
      <p class="small">{{ P.ntc.note }}。把 NTC 放进恒温槽，换几个温度，万用表读 NTC 两端电压；R = Rfix·V/(Vs − V)，再拟合 ln R 与 1/T 的直线：斜率 = B，截距 = ln R25。</p>
      <div class="bench">
        <div class="dut"><div class="lab">恒温槽</div>
          <div class="steps"><button v-for="t in P.ntc.temps_c" :key="t" class="stp" :class="{ on: nt.t === t }" @click="nt.t = t">{{ t }} ℃</button></div>
          <div class="small muted">分压电源 {{ P.ntc.vs }} V，Rfix = {{ P.ntc.rfix }} Ω</div></div>
        <DmmPanel :r="dmm" v-model:range="dmmRange" :hist="dmmHist" />
      </div>
      <div class="line"><button class="btn" @click="recNtc">记录（温度、电压、算出的电阻）</button>
        <button class="btn" @click="fitNtc">拟合 ln R ～ (1/T − 1/298.15)</button><span v-if="fitRes" class="small mono">{{ fitRes }}</span></div>
    </section>

    <!-- ⑥ 激光测距 -->
    <section v-if="task === 'tof'" class="card">
      <p class="small">{{ P.tof.note }}。靶板放在几个距离，每处连续测 N 次看标准差；再看“每 16 次取平均”后的标准差（重复 100 组）。</p>
      <div class="line">距离 <span class="steps"><button v-for="d in P.tof.dists_m" :key="d" class="stp" :class="{ on: tf.d === d }" @click="tf.d = d">{{ d }} m</button></span>
        N <input v-model.number="tf.n" type="number" min="10" max="5000" class="num">
        <button class="btn" @click="tofSample">测 N 次</button><button class="btn" @click="tofAvg">16 次平均 × 100 组</button></div>
      <div v-if="tf.last" class="small mono">{{ tf.last }}</div>
    </section>

    <!-- 从电路分析送来 -->
    <section v-if="task === 'import' && imported" class="card">
      <p class="small">“{{ imported.title }}”的瞬态曲线，接到示波器上看：仿真给的是理想值，示波器有带宽、8 位量化和本底噪声。</p>
      <div class="line small">时基 <select v-model.number="sc.tdiv" @change="acquire"><option v-for="t in TDIVS" :key="t" :value="t">{{ si(t) }}s/格</option></select>
        <span v-for="(n, k) in imported.names" :key="n">CH{{ k + 1 }} {{ n }} 伏/格 <select v-model.number="sc.vdiv[k]" @change="acquire"><option v-for="v in VDIVS" :key="v" :value="v">{{ si(v) }}V</option></select>
          偏置 <input v-model.number="sc.off[k]" type="number" step="any" class="num" @change="acquire"></span>
        <button class="btn sm" @click="acquire">单次触发</button></div>
      <ScopeScreen :traces="sc.traces" :vdiv="sc.vdiv" :off="sc.off" :tdiv="sc.tdiv" />
      <div class="small mono">CH1 峰峰值 {{ si(scM?.vpp) }}V，平均 {{ si(scM?.mean) }}V，频率 {{ si(scM?.freq) }}Hz</div>
    </section>

    <!-- 记录、结果、核对 -->
    <section v-if="TASKS.includes(task)" class="card">
      <div class="card-head"><h2>记录</h2><span class="r small"><button class="btn sm" @click="csv">导出 CSV</button> <button class="btn sm" @click="rows[task] = []">清空</button></span></div>
      <table v-if="(rows[task] || []).length" class="tbl small"><thead><tr><th v-for="c in COLS[task]" :key="c">{{ c }}</th><th></th></tr></thead>
        <tbody><tr v-for="(r, i) in rows[task]" :key="i"><td v-for="(x, j) in r" :key="j" class="mono">{{ x }}</td><td><a href="#" @click.prevent="rows[task].splice(i, 1)">删</a></td></tr></tbody></table>
      <p v-else class="small muted">还没有记录。</p>
      <div class="card-head"><h2>结果</h2></div>
      <div class="ans">
        <label v-for="k in ANS[task]" :key="k">{{ labels[k]?.label || k }}<span v-if="labels[k]?.unit" class="muted">（{{ labels[k].unit }}）</span>
          <select v-if="k === 'dir'" v-model="ans[task][k]"><option value="">—</option><option value="cw">正转（A 超前 B）</option><option value="ccw">反转（B 超前 A）</option></select>
          <input v-else v-model="ans[task][k]" type="number" step="any">
          <span v-if="chk[task]" :class="chkRow(k)?.ok ? 'ok' : 'bad-t'">{{ chkRow(k)?.ok ? '✓' : '✗' }} <small class="muted">{{ chkRow(k)?.allow }}</small></span></label>
      </div>
      <div class="line"><button class="btn primary" :disabled="busy" @click="check">交平台核对</button>
        <button class="btn" :disabled="busy" @click="record">下载实验记录（Word）</button>
        <span v-if="chk[task]" class="small" :class="chk[task].all_ok ? 'ok' : 'bad-t'">{{ chk[task].all_ok ? '全部正确' : '有不对的，看看哪一步' }}</span></div>
    </section>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { post, session } from '../lib/api';
import * as I from '../lib/instruments';
import ScopeScreen from '../components/ScopeScreen.vue';

const P = I.PARAMS;
const TASKS = I.TASKS;
const ANS = { torque: ['s_mv_v', 'zero_mv', 'nl_pct', 'hys_pct'], encoder: ['dir', 'rpm', 'cpr', 'z_ms'], imu: ['bias', 'arw', 'bi'],
  hall: ['s_mv_a', 'vz', 'fb'], ntc: ['b', 'r25'], tof: ['sd1', 'sd5', 'sd5avg'] };
const COLS = { torque: ['步', '力矩 N·m', '方向', '输出 V'], encoder: ['项目', '值'], imu: ['τ s', 'σ °/s'],
  hall: ['类型', '电流 A / 频率 Hz', '输出 V / 幅值 V'], ntc: ['温度 ℃', '电压 V', '电阻 Ω'], tof: ['距离 m', '次数', '平均 mm', '标准差 mm'] };
const TDIVS = [1e-7, 2e-7, 5e-7, 1e-6, 2e-6, 5e-6, 1e-5, 2e-5, 5e-5, 1e-4, 2e-4, 5e-4, 1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 5e-2, 0.1];
const VDIVS = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10];

// 万用表面板（小组件）：显示值、量程、精度等级与不确定度（B 类 = 精度/√3，A 类 = 最近 10 次读数的标准差/√10）
const DmmPanel = defineComponent({
  props: { r: Object, range: [Number, String], hist: Array },
  emits: ['update:range'],
  setup(p, { emit }) {
    return () => {
      const r = p.r || {};
      const n = p.hist.length;
      const m = n ? p.hist.reduce((a, b) => a + b, 0) / n : null;
      const sdv = n > 1 ? Math.sqrt(p.hist.reduce((a, b) => a + (b - m) ** 2, 0) / (n - 1)) : 0;
      const ua = n > 1 ? sdv / Math.sqrt(n) : 0;
      const uc = Math.sqrt(ua * ua + (r.u_b || 0) ** 2);
      const dig = r.res ? Math.max(0, -Math.floor(Math.log10(r.res) + 1e-9)) : 4;
      return h('div', { class: 'dmm' }, [
        h('div', { class: 'lab' }, '数字万用表 · 直流电压'),
        h('div', { class: 'disp mono' }, r.over ? 'OL' : r.value == null ? '—' : r.value.toFixed(dig) + ' V'),
        h('div', { class: 'small' }, ['量程 ', h('select', { value: p.range, onChange: (e) => emit('update:range', e.target.value === 'auto' ? 'auto' : +e.target.value) },
          [h('option', { value: 'auto' }, '自动'), ...P.dmm.ranges_v.map((x) => h('option', { value: x }, x + ' V'))]),
        `　分辨率 ${r.res ? r.res.toExponential(0) : '—'} V`]),
        h('div', { class: 'small muted' }, `精度 ±(${P.dmm.dcv_pct}% 读数 + ${P.dmm.dcv_dig} 字) = ±${r.acc ? r.acc.toExponential(2) : '—'} V；B 类 u = ${r.u_b ? r.u_b.toExponential(2) : '—'} V`),
        h('div', { class: 'small muted' }, n ? `最近 ${n} 次平均 ${m.toFixed(dig + 1)} V，A 类 u = ${ua.toExponential(2)} V，合成 u = ${uc.toExponential(2)} V` : ''),
      ]);
    };
  },
});

const route = useRoute();
const router = useRouter();
const tasks = ref(TASKS.map((k) => ({ key: k, title: k })));
const labels = ref({});
const seed = ref(null);
const task = ref(route.query.task || 'torque');
const err = ref('');
const busy = ref(false);
const rows = reactive(Object.fromEntries(TASKS.map((k) => [k, []])));
const ans = reactive(Object.fromEntries(TASKS.map((k) => [k, Object.fromEntries(ANS[k].map((a) => [a, '']))])));
const chk = reactive({});
const fitRes = ref('');
const imported = ref(null);
const v = computed(() => (seed.value == null || !TASKS.includes(task.value) ? null : I.variant(task.value, seed.value)));
let g = I.gaussFrom(I.mulberry32(Date.now() >>> 0));

// ---------------------------------------------------------------- 万用表（每 0.4 秒读一次）
const dmm = ref(null);
const dmmRange = ref('auto');
const dmmHist = ref([]);
const dmmMean = computed(() => (dmmHist.value.length ? dmmHist.value.reduce((a, b) => a + b, 0) / dmmHist.value.length : null));
const tq = reactive({ step: 0 });
const tqT = computed(() => P.torque.points_nm[tq.step]);
const hl = reactive({ I: 0, f: 1000 });
const nt = reactive({ t: 25 });
const ntBath = reactive({});
function trueVolt() {
  if (!v.value) return null;
  if (task.value === 'torque') return (I.torqueOut(v.value, tqT.value, tq.step > 5) + P.torque.noise_mv * g()) / 1000;
  if (task.value === 'hall') return I.hallDc(v.value, hl.I) + P.hall.noise_mv / 1000 * g();
  if (task.value === 'ntc') {
    if (ntBath[nt.t] == null) ntBath[nt.t] = nt.t + P.ntc.bath_sd_k * g();
    return I.ntcVolt(v.value, ntBath[nt.t]).V;
  }
  return null;
}
function readDmm() {
  const V = trueVolt();
  if (V == null) { dmm.value = null; return; }
  const r = I.dmmRead(V, g, dmmRange.value === 'auto' ? null : dmmRange.value);
  dmm.value = r;
  if (r.value != null) dmmHist.value = [...dmmHist.value, r.value].slice(-10);
}
watch([() => tq.step, () => hl.I, () => nt.t, dmmRange, task], () => { dmmHist.value = []; fitRes.value = ''; });
let timer = null;

// ---------------------------------------------------------------- 示波器
const sc = reactive({ traces: [], vdiv: [5, 5, 5, 1], off: [-12, -2, 8, 0], tdiv: 1e-5 });
const scM = computed(() => (sc.traces[0] ? I.scopeMeasure(sc.traces[0]) : null));
function channels() {
  if (task.value === 'encoder' && v.value) {
    const s = I.encoderSignals(v.value);
    return [{ name: 'A', fn: s.A }, { name: 'B', fn: s.B }, { name: 'Z', fn: s.Z }];
  }
  if (task.value === 'hall' && v.value) {
    const a = I.hallAc(v.value, hl.f, 1);
    return [{ name: '输出', fn: (t) => v.value.vz + a.amp * Math.sin(2 * Math.PI * hl.f * t + a.phase) + P.hall.noise_mv / 1000 * g() }];
  }
  if (task.value === 'import' && imported.value) {
    const t = imported.value.t;
    return imported.value.names.map((n, k) => {
      const y = imported.value.series[k];
      return { name: n, fn: (x) => {
        if (x <= t[0]) return y[0];
        if (x >= t[t.length - 1]) return y[y.length - 1];
        let lo = 0; let hi = t.length - 1;
        while (hi - lo > 1) { const m = (lo + hi) >> 1; if (t[m] <= x) lo = m; else hi = m; }
        return y[lo] + (y[hi] - y[lo]) * (x - t[lo]) / (t[hi] - t[lo] || 1);
      } };
    });
  }
  return [];
}
function acquire() {
  const chs = channels();
  if (!chs.length) return;
  let lvl = null;
  if (task.value === 'encoder') lvl = 2.5;
  if (task.value === 'hall') lvl = v.value.vz;
  if (task.value === 'import') { const s = imported.value.series[0]; lvl = (Math.max(...s) + Math.min(...s)) / 2; }
  sc.traces = I.scopeAcquire(chs, { tdiv: sc.tdiv, vdiv: sc.vdiv, off: sc.off, trigLevel: lvl }, g);
}
function setupScope() {
  if (task.value === 'encoder') { Object.assign(sc, { vdiv: [5, 5, 5, 1], off: [-12, -2, 8, 0], tdiv: 2e-5 }); }
  if (task.value === 'hall' && v.value) { Object.assign(sc, { vdiv: [0.01, 1, 1, 1], off: [v.value.vz, 0, 0, 0], tdiv: 2e-4 }); }
  if (task.value === 'import' && imported.value) {
    const t = imported.value.t; const span = t[t.length - 1] - t[0];
    sc.tdiv = TDIVS.find((x) => x * 10 >= span * 0.9) || TDIVS[TDIVS.length - 1];
    sc.vdiv = imported.value.series.map((s) => { const r = Math.max(...s) - Math.min(...s); return VDIVS.find((x) => x * 8 >= r * 1.2) || 10; });
    sc.off = imported.value.series.map((s) => +((Math.max(...s) + Math.min(...s)) / 2).toPrecision(3));
  }
  acquire();
}
watch(() => hl.f, () => { if (task.value === 'hall') { sc.tdiv = TDIVS.find((x) => x * 10 >= 3 / hl.f) || 0.1; acquire(); } });

// ---------------------------------------------------------------- 逻辑分析仪
const la = reactive({ span: 0.1, res: null });
function capture() {
  if (!v.value) return;
  const s = I.encoderSignals(v.value);
  la.res = I.decodeQuadrature(s, 0, la.span, Math.max(2e6, s.fA * 32));
}
function laPts(k, j) {
  const tr = la.res.trace.slice(0, 400);
  if (!tr.length) return '';
  const t0 = tr[0][0]; const t1 = tr[tr.length - 1][0] || 1;
  return tr.map((r) => `${(20 + (r[0] - t0) / (t1 - t0 || 1) * 375).toFixed(1)},${(28 + j * 30 - r[k] * 18).toFixed(1)}`).join(' ');
}

// ---------------------------------------------------------------- IMU
const imu = reactive({ ad: null, st: null, n: 0, h: null });
async function runImu() {
  busy.value = true;
  await new Promise((r) => setTimeout(r, 30));
  const s = I.imuSeries(v.value, seed.value);
  imu.n = s.data.length;
  imu.st = I.stats(Array.from(s.data.subarray(0, 200000)));
  let sum = 0; for (const x of s.data) sum += x;
  imu.st.mean = sum / s.data.length;
  imu.ad = I.allan(s.data, s.fs, 0.1);
  busy.value = false;
}
const llR = computed(() => {
  if (!imu.ad) return null;
  const ts = imu.ad.map((p) => p.tau); const ys = imu.ad.map((p) => p.adev);
  return { x0: Math.log10(Math.min(...ts)), x1: Math.log10(Math.max(...ts)), y0: Math.floor(Math.log10(Math.min(...ys))), y1: Math.ceil(Math.log10(Math.max(...ys))) };
});
function lx(t) { const r = llR.value; return 60 + (Math.log10(t) - r.x0) / (r.x1 - r.x0) * 490; }
function ly(y) { const r = llR.value; return 270 - (Math.log10(y) - r.y0) / (r.y1 - r.y0) * 260; }
const llX = computed(() => { if (!llR.value) return []; const o = []; for (let e = Math.ceil(llR.value.x0); e <= llR.value.x1; e++) o.push(10 ** e); return o; });
const llY = computed(() => { if (!llR.value) return []; const o = []; for (let e = llR.value.y0; e <= llR.value.y1; e++) o.push(10 ** e); return o; });
function llHover(ev) {
  const r = ev.currentTarget.getBoundingClientRect(); const px = (ev.clientX - r.left) / r.width * 560;
  let b = 0; let bd = Infinity; imu.ad.forEach((p, i) => { const d = Math.abs(lx(p.tau) - px); if (d < bd) { bd = d; b = i; } });
  imu.h = b;
}

// ---------------------------------------------------------------- 激光测距
const tf = reactive({ d: 1, n: 200, last: '' });
function tofSample() {
  const a = []; for (let i = 0; i < tf.n; i++) a.push(tf.d * 1000 + I.tofSigma(v.value, tf.d) * g());
  const s = I.stats(a);
  tf.last = `${tf.d} m，${s.n} 次：平均 ${s.mean.toFixed(2)} mm，标准差 ${s.sd.toFixed(3)} mm`;
  rec([tf.d, s.n, s.mean.toFixed(2), s.sd.toFixed(3)]);
}
function tofAvg() {
  const ms = [];
  for (let k = 0; k < 100; k++) { let s = 0; for (let i = 0; i < P.tof.n_avg; i++) s += tf.d * 1000 + I.tofSigma(v.value, tf.d) * g(); ms.push(s / P.tof.n_avg); }
  const s = I.stats(ms);
  tf.last = `${tf.d} m，每 ${P.tof.n_avg} 次平均 × 100 组：平均 ${s.mean.toFixed(2)} mm，标准差 ${s.sd.toFixed(3)} mm`;
  rec([tf.d, `${P.tof.n_avg} 次平均 ×100`, s.mean.toFixed(2), s.sd.toFixed(3)]);
}

// ---------------------------------------------------------------- 记录与拟合
function fmtV(x) { return x == null ? '—' : (+x).toPrecision(6); }
function rec(r) { rows[task.value].push(r); }
function recNtc() {
  const V = dmmMean.value;
  if (V == null) return;
  rec([nt.t, fmtV(V), (P.ntc.rfix * V / (P.ntc.vs - V)).toFixed(1)]);
}
function fitTorque() {
  const pts = rows.torque.filter((r) => r[2] === '加载').map((r) => [+r[1], +r[3] * 1000]);
  if (pts.length < 3) { fitRes.value = '加载段至少记录 3 步'; return; }
  const f = I.linfit(pts.map((p) => p[0]), pts.map((p) => p[1]));
  fitRes.value = `斜率 ${f.k.toFixed(4)} mV/(N·m)，截距 ${f.b.toFixed(3)} mV（满量程输出 ${(f.k * P.torque.fs_nm).toFixed(2)} mV）`;
}
function fitHall() {
  const pts = rows.hall.filter((r) => r[0] === '直流').map((r) => [+r[1], +r[2]]);
  if (pts.length < 3) { fitRes.value = '直流至少记录 3 个点'; return; }
  const f = I.linfit(pts.map((p) => p[0]), pts.map((p) => p[1]));
  fitRes.value = `斜率 ${(1000 * f.k).toFixed(3)} mV/A，截距 ${f.b.toFixed(4)} V`;
}
function fitNtc() {
  const pts = rows.ntc.map((r) => [1 / (+r[0] + 273.15) - 1 / 298.15, Math.log(+r[2])]);
  if (pts.length < 3) { fitRes.value = '至少记录 3 个温度'; return; }
  const f = I.linfit(pts.map((p) => p[0]), pts.map((p) => p[1]));
  fitRes.value = `斜率（B）${f.k.toFixed(1)} K，截距 ${f.b.toFixed(5)} → R25 = ${Math.exp(f.b).toFixed(1)} Ω`;
}
function csv() {
  const L = [COLS[task.value].join(',')].concat(rows[task.value].map((r) => r.join(',')));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['﻿' + L.join('\n')], { type: 'text/csv' }));
  a.download = `虚拟仪器-${task.value}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
}
function chkRow(k) { return chk[task.value]?.rows.find((r) => r.key === k); }
async function check() {
  busy.value = true; err.value = '';
  try { chk[task.value] = await post('/instruments/check', { task: task.value, answers: { ...ans[task.value] } }); } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
async function record() {
  busy.value = true; err.value = '';
  try {
    const r = await fetch('/api/instruments/record', { method: 'POST', headers: { 'Content-Type': 'application/json', 'x-wq-token': session.token },
      body: JSON.stringify({ task: task.value, answers: { ...ans[task.value] }, rows: rows[task.value], columns: COLS[task.value] }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || '实验记录生成失败');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await r.blob());
    a.download = `虚拟仪器实验记录-${task.value}.docx`;
    document.body.appendChild(a); a.click(); a.remove();
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}

function go(k) { router.replace({ query: { task: k } }); }
watch(() => route.query.task, (k) => { task.value = k || 'torque'; fitRes.value = ''; setupScope(); });
function si(x) {
  if (x == null || !isFinite(x)) return '—';
  const a = Math.abs(x);
  if (a === 0) return '0';
  for (const [k, s] of [[1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'μ'], [1e-9, 'n']]) if (a >= k * 0.999) return (+(x / k).toPrecision(4)) + ' ' + s;
  return x.toExponential(2);
}

onMounted(async () => {
  try {
    const raw = sessionStorage.getItem('wq-scope-import');
    if (raw) imported.value = JSON.parse(raw);
  } catch (e) { /* 无痕窗口 */ }
  try {
    const r = await post('/instruments/params', {});
    seed.value = r.seed; tasks.value = r.tasks; labels.value = r.labels;
    g = I.gaussFrom(I.mulberry32((r.seed ^ (Date.now() & 0xffff)) >>> 0));
  } catch (e) { err.value = e.message; }
  setupScope();
  timer = setInterval(readDmm, 400);
});
onBeforeUnmount(() => clearInterval(timer));
</script>

<style scoped>
.page-title { flex-wrap: wrap; } .page-title h1 { white-space: nowrap; }
.tabs { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 10px; }
.tab { border: 1px solid var(--line); background: var(--surface); border-radius: 16px; padding: 4px 12px; cursor: pointer; font-size: 13px; }
.tab.on { background: var(--brand, #2563eb); color: #fff; border-color: transparent; }
.bench { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; margin: 8px 0; }
.bench > * { flex: 1 1 300px; min-width: 0; }
.dut, .la, :deep(.dmm) { background: var(--surface-2); border-radius: 8px; padding: 10px; }
.lab, :deep(.dmm .lab) { font-weight: 600; font-size: 13px; margin-bottom: 4px; }
:deep(.dmm .disp) { font-size: 30px; background: #10241a; color: #7CFC9A; border-radius: 6px; padding: 6px 10px; margin: 4px 0; text-align: right; }
.steps { display: inline-flex; flex-wrap: wrap; gap: 4px; margin: 4px 0; }
.stp { border: 1px solid var(--line); background: var(--surface); border-radius: 6px; padding: 3px 8px; cursor: pointer; font-size: 13px; }
.stp.on { background: var(--brand, #2563eb); color: #fff; }
.stp small { margin-left: 2px; }
.line { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: center; margin: 6px 0; }
.num { width: 90px; height: 28px; border: 1px solid var(--line); border-radius: 6px; padding: 0 6px; }
.latr { width: 100%; max-width: 420px; background: #fff; border: 1px solid var(--line); border-radius: 6px; margin-top: 6px; }
.tl { font-size: 11px; fill: #6b7280; }
.ll { width: 100%; max-width: 620px; border: 1px solid var(--line); border-radius: 6px; }
.ll .grid line { stroke: #eef0f3; } .axt text { font-size: 11px; fill: #6b7280; }
.tbl { width: 100%; border-collapse: collapse; } .tbl th, .tbl td { padding: 3px 6px; border-bottom: 1px solid var(--line); text-align: left; }
.ans { display: flex; flex-wrap: wrap; gap: 10px 18px; }
.ans label { display: flex; flex-direction: column; font-size: 12px; gap: 2px; }
.ans input, .ans select { width: 150px; height: 28px; border: 1px solid var(--line); border-radius: 6px; padding: 0 6px; }
.ok { color: var(--good, #16a34a); } .bad-t { color: var(--bad, #dc2626); }
.r { margin-left: auto; }
</style>
