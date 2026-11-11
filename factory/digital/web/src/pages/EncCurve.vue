<!-- 第 125 轮（电子 E12）：传感器厂的编码器误差曲线。终检时把编码器和基准编码器同轴连起来转一圈，记下每个角度的误差；
     帮学生从“曲线形状”追到原因：每圈一个起伏是偏心（一次谐波），某处尖峰、幅值掉坑是码盘脏，幅值整体低、细分误差大是读头间隙。 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('编码器误差曲线') }}</h1>
      <span class="muted">{{ $t('终检过的每台编码器：整圈误差、谐波分解、信号幅值和细分误差；按粘接对心机分开看，找出误差从哪来') }}</span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div class="cols">
      <section class="card list">
        <div class="card-head"><h2>{{ $t('最近的编码器（{a} 台）', { a: $td(shown.length) }) }}</h2></div>
        <div class="small">
          <label>{{ $t('粘接对心机') }}
            <select v-model="station"><option value="">{{ $t('全部') }}</option><option v-for="s in stations" :key="s" :value="s">{{ $td(s) }}</option></select>
          </label>
          <span v-if="stations.length > 1" class="muted"> · {{ $t('一次谐波均值：') }}<span v-for="s in stations" :key="s" class="mono">{{ s }} {{ meanH1(s) }}″ · </span></span>
        </div>
        <div v-if="!list.length" class="small muted">{{ $t('还没有。接一张 WQ-ENC17 订单，让车间做到“编码器终检”。') }}</div>
        <button v-for="w in shown" :key="w.serial" class="brd" :class="{ on: sel === w.serial }" @click="open(w.serial)">
          <span class="mono">{{ $td(w.serial) }}</span>
          <span class="small" :class="w.pass ? 'ok' : 'bad'">{{ w.pass ? $t('合格') : $t('不合格') }}</span>
          <span class="small muted">{{ $t('{a}　精度 {b}″　一次 {c}″', { a: $td(w.station), b: v(w, 'enc_acc'), c: v(w, 'enc_h1') }) }}</span>
          <span class="small muted">{{ $t('幅值 {a} %（最低 {b} %）', { a: v(w, 'enc_amp'), b: v(w, 'enc_amp_min') }) }}</span>
        </button>
      </section>
      <section v-if="m" class="card main">
        <div class="card-head"><h2>{{ $td(m.serial) }} · <small class="muted">{{ $t('工单 {a}　粘接对心机 {b}　偏心 {c} µm', { a: $td(m.work_order), b: $td(m.station), c: $td(m.ecc_um) }) }}</small></h2></div>
        <div class="kpis">
          <div :class="{ bad: m.acc > m.acc_hi }"><b>{{ m.acc.toFixed(1) }}″</b><span>{{ $t('精度（峰峰值，上限 {a}″）', { a: $td(m.acc_hi) }) }}</span></div>
          <div :class="{ bad: m.h1 > 30 }"><b>{{ m.h1.toFixed(1) }}″</b><span>{{ $t('一次谐波（偏心，上限 30″）') }}</span></div>
          <div :class="{ bad: m.interp > 20 }"><b>{{ m.interp.toFixed(1) }}″</b><span>{{ $t('细分误差（上限 20″）') }}</span></div>
          <div :class="{ bad: m.amp < 80 || m.amp_min < 70 }"><b>{{ m.amp.toFixed(0) }} %</b><span>{{ $t('信号幅值（最低 {a} %）', { a: m.amp_min.toFixed(0) }) }}</span></div>
        </div>
        <h3>{{ $t('整圈误差（被测 − 基准，角秒）') }}</h3>
        <svg :viewBox="`0 0 ${W} ${H}`" class="chart" role="img" :aria-label="$t('整圈误差曲线')">
          <line v-for="d in [0, 90, 180, 270, 360]" :key="'g' + d" :x1="x(d)" :x2="x(d)" :y1="PAD" :y2="H - PAD" class="grid" />
          <line :x1="x(0)" :x2="x(360)" :y1="ye(0)" :y2="ye(0)" class="axis" />
          <polyline :points="pts(m.err, ye)" class="ln" />
          <polyline v-if="showH1" :points="h1pts" class="ln h1" />
          <text v-for="d in [0, 90, 180, 270, 360]" :key="'t' + d" :x="x(d)" :y="H - 4" class="tk" text-anchor="middle">{{ d }}°</text>
          <text :x="PAD + 2" :y="PAD + 8" class="tk">+{{ eMax.toFixed(0) }}″</text>
          <text :x="PAD + 2" :y="H - PAD - 2" class="tk">−{{ eMax.toFixed(0) }}″</text>
        </svg>
        <label class="small"><input v-model="showH1" type="checkbox" /> {{ $t('叠上一次谐波（偏心那一部分）') }}</label>
        <div class="grid2">
          <div>
            <h3>{{ $t('谐波分解（每圈几个起伏）') }}</h3>
            <div class="sbars">
              <div v-for="(a, k) in m.harmonics" :key="k" class="sbar" :title="(k + 1) + $t(' 次：') + a + '″'">
                <div class="sb" :class="{ hot: k === 0 && a > 30 }" :style="{ height: (80 * a / hMax) + '%' }" />
                <div class="small">{{ k + 1 }}</div>
              </div>
            </div>
            <p class="small">{{ $t('1 次 = 每圈一个起伏 = 码盘偏心（e ÷ 码道半径 {a} mm，1 µm ≈ 16″）；2 次 = 倾斜、轴承椭圆；更高次 = 码盘刻划误差。', { a: $td(m.r_mm) }) }}</p>
          </div>
          <div>
            <h3>{{ $t('信号幅值随角度（%，额定 100）') }}</h3>
            <svg :viewBox="`0 0 ${W} ${H2}`" class="chart" role="img" :aria-label="$t('信号幅值曲线')">
              <line :x1="x(0)" :x2="x(360)" :y1="ya(80)" :y2="ya(80)" class="lim" />
              <polyline :points="pts(m.amp_curve, ya)" class="ln amp" />
              <text :x="x(360) - 2" :y="ya(80) - 3" class="tk" text-anchor="end">{{ $t('下限 80 %') }}</text>
              <text v-for="d in [0, 180, 360]" :key="'a' + d" :x="x(d)" :y="H2 - 4" class="tk" text-anchor="middle">{{ d }}°</text>
            </svg>
            <p class="small">{{ $t('幅值由读头间隙决定：间隙大幅值整体低；码盘某处有污点，那个角度掉一个坑，误差曲线同一角度出一个尖峰。') }}</p>
          </div>
          <div>
            <h3>{{ $t('细分误差（放大两个信号周期）') }}</h3>
            <svg :viewBox="`0 0 ${W} ${H2}`" class="chart" role="img" :aria-label="$t('细分误差曲线')">
              <line :x1="x(0)" :x2="x(360)" :y1="H2 / 2" :y2="H2 / 2" class="axis" />
              <polyline :points="ipts" class="ln ip" />
            </svg>
            <p class="small">{{ $t('码盘 {a} 线，一个信号周期 360° ÷ {b} ≈ 633″。读头的正弦、余弦信号幅值不等、有偏置时，每个周期里起伏一两次；幅值越低，这个误差越大。它周期太短，整圈曲线上看不出来，要单独看。', { a: $td(m.lines), b: $td(m.lines) }) }}</p>
          </div>
        </div>
        <p class="small muted">{{ $t('示例模型：码道半径、线数、误差量级、规格限都是示例值；曲线由 4096 个点算出，这里抽稀到 720 点画。') }}</p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { get } from '../lib/api';

const W = 640; const H = 220; const H2 = 140; const PAD = 14;
const list = ref([]);
const sel = ref('');
const m = ref(null);
const err = ref('');
const station = ref('');
const showH1 = ref(true);
const route = useRoute();

const stations = computed(() => [...new Set(list.value.map((w) => w.station).filter(Boolean))].sort());
const shown = computed(() => list.value.filter((w) => !station.value || w.station === station.value));
const v = (w, c) => { const x = w.meas[c]; return x ? Number(x.v).toFixed(0) : '—'; };
function meanH1(s) {
  const a = list.value.filter((w) => w.station === s && w.meas.enc_h1).map((w) => Number(w.meas.enc_h1.v));
  return a.length ? (a.reduce((p, q) => p + q, 0) / a.length).toFixed(1) : '—';
}
const x = (d) => PAD + (W - 2 * PAD) * d / 360;
const eMax = computed(() => Math.max(20, ...(m.value ? m.value.err.map(Math.abs) : [0])) * 1.1);
const ye = (e) => H / 2 - (H / 2 - PAD) * e / eMax.value;
const ya = (a) => H2 - 18 - (H2 - 30) * Math.max(0, a) / 130;
const hMax = computed(() => Math.max(5, ...(m.value ? m.value.harmonics : [0])));
function pts(arr, fy) { return arr.map((e, i) => x(m.value.deg[i]).toFixed(1) + ',' + fy(e).toFixed(1)).join(' '); }
const h1pts = computed(() => {
  if (!m.value) return '';
  // 用整圈曲线最小二乘拟合出一次谐波（相位从数据算，幅值与谐波分解一致）
  const d = m.value.deg; const e = m.value.err; let a = 0; let b = 0;
  d.forEach((q, i) => { const t = q * Math.PI / 180; a += e[i] * Math.cos(t); b += e[i] * Math.sin(t); });
  a *= 2 / d.length; b *= 2 / d.length;
  return d.map((q) => { const t = q * Math.PI / 180; return x(q).toFixed(1) + ',' + ye(a * Math.cos(t) + b * Math.sin(t)).toFixed(1); }).join(' ');
});
const ipts = computed(() => {
  if (!m.value) return '';
  const c = m.value.interp_curve; const mx = Math.max(10, ...c.map(Math.abs)) * 1.15;
  return c.map((q, j) => x(360 * j / (c.length - 1)).toFixed(1) + ',' + (H2 / 2 - (H2 / 2 - 8) * q / mx).toFixed(1)).join(' ');
});
async function open(s) {
  sel.value = s; err.value = '';
  try { m.value = await get('/sensor/encoder/' + encodeURIComponent(s)); } catch (e) { err.value = e.message; }
}
onMounted(async () => {
  try {
    list.value = (await get('/sensor/encoders')).encoders;
    const want = route.query.serial || (list.value[0] && list.value[0].serial);
    if (want) open(want);
  } catch (e) { err.value = e.message; }
});
</script>

<style scoped>
.cols { display: grid; grid-template-columns: minmax(220px, 300px) 1fr; gap: 12px; }
@media (max-width: 800px) { .cols { grid-template-columns: 1fr; } }
.cols > * { min-width: 0; }
.brd { display: grid; grid-template-columns: 1fr auto; gap: 2px 8px; width: 100%; text-align: left; border: 1px solid #e3e6ee; background: #fff; border-radius: 8px; padding: 6px 8px; margin: 4px 0; cursor: pointer; }
.brd > span:nth-child(n+3) { grid-column: 1 / -1; }
.brd.on { border-color: #1d4ed8; background: #eff6ff; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin: 6px 0 10px; }
.kpis div { border: 1px solid #e3e6ee; border-radius: 8px; padding: 6px 8px; display: flex; flex-direction: column; }
.kpis b { font-size: 1.2em; } .kpis span { font-size: 12px; color: #6b7280; }
.kpis .bad { border-color: #fca5a5; background: #fef2f2; } .kpis .bad b { color: #b91c1c; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }
.chart { width: 100%; height: auto; display: block; background: #fafbfd; border: 1px solid #eef0f5; border-radius: 6px; }
.chart .grid { stroke: #eef0f5; } .chart .axis { stroke: #cbd5e1; } .chart .lim { stroke: #f59e0b; stroke-dasharray: 4 3; }
.chart .ln { fill: none; stroke: #1d4ed8; stroke-width: 1.2; } .chart .ln.h1 { stroke: #dc2626; stroke-width: 1.5; stroke-dasharray: 5 3; }
.chart .ln.amp { stroke: #0f766e; } .chart .ln.ip { stroke: #7c3aed; }
.chart .tk { font-size: 10px; fill: #6b7280; }
.sbars { display: flex; gap: 3px; align-items: stretch; height: 130px; margin: 6px 0 4px; }
.sbar { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; }
.sb { width: 75%; background: #60a5fa; border-radius: 3px 3px 0 0; min-height: 2px; } .sb.hot { background: #dc2626; }
.ok { color: #15803d; } .bad { color: #b91c1c; }
</style>
