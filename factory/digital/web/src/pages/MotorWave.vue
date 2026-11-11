<!-- 第 131 轮：电机厂的电机终检波形。终检台（测功台）拖动电机转一圈录三相反电势，不通电慢转一圈录齿槽转矩；
     帮学生从“波形和谐波”追到原因：齿槽转矩每圈 12、24 次变大是磁钢贴歪，反电势整体低是充磁不足，某一相低是绕组问题。 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('电机终检波形') }}</h1>
      <span class="muted">{{ $t('终检过的每台电机：三相反电势波形与谐波、齿槽转矩曲线与谐波、定子测试；按绕线机分开看，找出问题从哪来') }}</span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div class="cols">
      <section class="card list">
        <div class="card-head"><h2>{{ $t('最近的电机（{a} 台）', { a: $td(shown.length) }) }}</h2></div>
        <div class="small">
          <label>{{ $t('型号') }}
            <select v-model="item"><option value="">{{ $t('全部') }}</option><option v-for="s in items" :key="s" :value="s">{{ $td(s) }}</option></select>
          </label>
          <label> · {{ $t('绕线机') }}
            <select v-model="winder"><option value="">{{ $t('全部') }}</option><option v-for="s in winders" :key="s" :value="s">{{ $td(s) }}</option></select>
          </label>
        </div>
        <div v-if="winders.length > 1" class="small muted">{{ $t('三相电阻不平衡均值：') }}<span v-for="s in winders" :key="s" class="mono">{{ s }} {{ meanBy(s) }} % · </span></div>
        <div v-if="!list.length" class="small muted">{{ $t('还没有。接一张伺服电机订单，让车间做到“电机终检”。') }}</div>
        <button v-for="w in shown" :key="w.serial" class="brd" :class="{ on: sel === w.serial }" @click="open(w.serial)">
          <span class="mono">{{ $td(w.serial) }}</span>
          <span class="small" :class="w.pass ? 'ok' : 'bad'">{{ w.pass ? $t('合格') : $t('不合格') }}</span>
          <span class="small muted">{{ $t('{a}　绕线 {b}', { a: $td(w.item), b: w.winder || '—' }) }}</span>
          <span class="small muted">{{ $t('反电势 {a} %　齿槽 {b} %　THD {c} %', { a: v(w, 'mt_ke', 1), b: v(w, 'mt_cog', 2), c: v(w, 'mt_thd', 1) }) }}</span>
        </button>
      </section>
      <section v-if="m" class="card main">
        <div class="card-head"><h2>{{ $td(m.serial) }} · <small class="muted">{{ $t('{a}　工单 {b}　绕线机 {c}　{d} 极 {e} 槽', { a: $td(m.item), b: $td(m.work_order), c: m.winder || '—', d: $td(m.poles), e: $td(m.slots) }) }}</small></h2></div>
        <div class="kpis">
          <div :class="{ bad: m.ke < 95 || m.ke > 105 }"><b>{{ m.ke.toFixed(1) }} %</b><span>{{ $t('反电势常数（95–105）') }}</span></div>
          <div :class="{ bad: m.unbal > 2 }"><b>{{ m.unbal.toFixed(2) }} %</b><span>{{ $t('三相不平衡（上限 2）') }}</span></div>
          <div :class="{ bad: m.thd > 5 }"><b>{{ m.thd.toFixed(1) }} %</b><span>{{ $t('谐波畸变 THD（上限 5）') }}</span></div>
          <div :class="{ bad: m.cog > 2.5 }"><b>{{ m.cog.toFixed(2) }} %</b><span>{{ $t('齿槽转矩峰峰值（上限 2.5）') }}</span></div>
          <div v-for="c in STATOR" :key="c.code" :class="{ bad: stBad(c.code) }"><b>{{ stv(c.code) }}</b><span>{{ $td(c.label) }}</span></div>
        </div>
        <h3>{{ $t('三相反电势（拖动转一圈，相对额定）') }}</h3>
        <svg :viewBox="`0 0 ${W} ${H}`" class="chart" role="img" :aria-label="$t('三相反电势波形')">
          <line v-for="d in [0, 90, 180, 270, 360]" :key="'g' + d" :x1="x(d)" :x2="x(d)" :y1="PAD" :y2="H - PAD" class="grid" />
          <line :x1="x(0)" :x2="x(360)" :y1="ye(0)" :y2="ye(0)" class="axis" />
          <polyline v-for="(e, k) in m.emf" :key="'e' + k" :points="pts(e, ye)" :class="'ln p' + k" />
          <text v-for="d in [0, 90, 180, 270, 360]" :key="'t' + d" :x="x(d)" :y="H - 4" class="tk" text-anchor="middle">{{ d }}°</text>
        </svg>
        <p class="small"><span class="lg p0">{{ $t('A 相') }}</span> · <span class="lg p1">{{ $t('B 相') }}</span> · <span class="lg p2">{{ $t('C 相') }}</span> · {{ $t('转一圈走 {a} 个电周期。某一相整体矮，是那相绕组有问题；三相一起矮，是磁钢没充饱。', { a: m.poles / 2 }) }}</p>
        <div class="grid2">
          <div>
            <h3>{{ $t('线反电势的谐波（每圈几次，基波 = 100）') }}</h3>
            <div class="sbars">
              <div v-for="(a, k) in harmShown" :key="k" class="sbar" :title="$t('每圈 ') + (k + 1) + $t(' 次：') + a + ' %'">
                <div class="sb" :class="{ fund: k + 1 === m.poles / 2, hot: k + 1 !== m.poles / 2 && a > 1.5 }" :style="{ height: (80 * Math.min(a, 12) / 12) + '%' }" />
                <div v-if="(k + 1) % 5 === 0" class="small">{{ k + 1 }}</div>
              </div>
            </div>
            <p class="small">{{ $t('基波在每圈 {a} 次（蓝高柱，截到 12 % 显示）；5、7 倍是设计本身的波形。夹在中间的 4、6、9、11 次是“次谐波”——10 块磁钢强弱、位置不一，每块经过线圈时不一样，磁钢贴歪时它们变高（红）。', { a: m.poles / 2 }) }}</p>
          </div>
          <div>
            <h3>{{ $t('齿槽转矩（不通电慢转一圈，% 额定转矩）') }}</h3>
            <svg :viewBox="`0 0 ${W} ${H2}`" class="chart" role="img" :aria-label="$t('齿槽转矩曲线')">
              <line :x1="x(0)" :x2="x(360)" :y1="H2 / 2" :y2="H2 / 2" class="axis" />
              <polyline :points="pts(m.cog_curve, yc)" class="ln cog" />
              <text v-for="d in [0, 180, 360]" :key="'c' + d" :x="x(d)" :y="H2 - 4" class="tk" text-anchor="middle">{{ d }}°</text>
              <text :x="PAD + 2" :y="12" class="tk">±{{ cMax.toFixed(1) }} %</text>
            </svg>
            <div class="cbars">
              <div v-for="(a, k) in m.cog_harm" :key="k" class="cb">
                <span class="small mono">{{ $t('{a} 次', { a: (k + 1) * m.slots }) }}</span>
                <span class="bar"><i :class="{ hot: k < 2 && a > 0.4, base: k === 4 }" :style="{ width: Math.min(100, 100 * a / cogMax) + '%' }" /></span>
                <span class="small mono">{{ a.toFixed(2) }}</span>
              </div>
            </div>
            <p class="small">{{ $t('{a} 极 {b} 槽，设计本身的齿槽转矩是每圈 60 次（灰）；每圈 12、24 次本来互相抵消，磁钢贴歪时抵消不掉（红），峰峰值变大，关节低速转动时会“一顿一顿”。', { a: $td(m.poles), b: $td(m.slots) }) }}</p>
          </div>
        </div>
        <h3>{{ $t('10 块磁钢（强度、位置误差）') }}</h3>
        <div class="mags">
          <div v-for="(a, k) in m.mag_a" :key="k" class="mag" :class="{ hot: Math.abs(m.mag_d[k]) > 1 }">
            <b>{{ k + 1 }}</b><span>{{ (a * 100).toFixed(1) }} %</span><span>{{ m.mag_d[k] > 0 ? '+' : '' }}{{ m.mag_d[k].toFixed(2) }}°</span>
          </div>
        </div>
        <p class="small muted">{{ $t('示例模型：极槽数、波形谐波、规格限都是示例值；曲线由一圈 1440 个点算出，这里抽稀到 720 点画。') }}</p>
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
const STATOR = [
  { code: 'st_r_unbal', label: $t('三相电阻不平衡 %（上限 1.5）'), d: 2 },
  { code: 'st_leak', label: $t('耐压漏电流 mA（上限 1.0）'), d: 2 },
  { code: 'mt_i0', label: $t('空载电流 A'), d: 2 },
];
const list = ref([]);
const sel = ref('');
const m = ref(null);
const err = ref('');
const item = ref('');
const winder = ref('');
const route = useRoute();

const items = computed(() => [...new Set(list.value.map((w) => w.item).filter(Boolean))].sort());
const winders = computed(() => [...new Set(list.value.map((w) => w.winder).filter(Boolean))].sort());
const shown = computed(() => list.value.filter((w) => (!item.value || w.item === item.value) && (!winder.value || w.winder === winder.value)));
const cur = computed(() => list.value.find((w) => w.serial === sel.value));
const v = (w, c, d) => { const q = w.meas[c]; return q ? Number(q.v).toFixed(d) : '—'; };
function meanBy(s) {
  const a = list.value.filter((w) => w.winder === s && w.meas.st_r_unbal).map((w) => Number(w.meas.st_r_unbal.v));
  return a.length ? (a.reduce((p, q) => p + q, 0) / a.length).toFixed(2) : '—';
}
const stv = (c) => { const q = cur.value && cur.value.meas[c]; return q ? Number(q.v).toFixed(2) : '—'; };
const stBad = (c) => { const q = cur.value && cur.value.meas[c]; return !!q && q.result !== 'pass'; };
const x = (d) => PAD + (W - 2 * PAD) * d / 360;
const ye = (e) => H / 2 - (H / 2 - PAD) * e / 125;
const cMax = computed(() => Math.max(1.5, ...(m.value ? m.value.cog_curve.map(Math.abs) : [0])) * 1.1);
const yc = (c) => H2 / 2 - (H2 / 2 - 14) * c / cMax.value;
const harmShown = computed(() => (m.value ? m.value.line_harm.slice(0, 40) : []));
const cogMax = computed(() => Math.max(0.5, ...(m.value ? m.value.cog_harm : [0])));
function pts(arr, fy) { return arr.map((e, i) => x(m.value.deg[i]).toFixed(1) + ',' + fy(e).toFixed(1)).join(' '); }
async function open(s) {
  sel.value = s; err.value = '';
  try { m.value = await get('/motor/motor/' + encodeURIComponent(s)); } catch (e) { err.value = e.message; }
}
onMounted(async () => {
  try {
    list.value = (await get('/motor/motors')).motors;
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
.chart .grid { stroke: #eef0f5; } .chart .axis { stroke: #cbd5e1; }
.chart .ln { fill: none; stroke-width: 1.2; }
.chart .p0, .lg.p0 { stroke: #1d4ed8; color: #1d4ed8; } .chart .p1, .lg.p1 { stroke: #dc2626; color: #dc2626; } .chart .p2, .lg.p2 { stroke: #0f766e; color: #0f766e; }
.chart .cog { stroke: #7c3aed; }
.chart .tk { font-size: 10px; fill: #6b7280; }
.lg { font-weight: 600; }
.sbars { display: flex; gap: 1px; align-items: stretch; height: 130px; margin: 6px 0 4px; }
.sbar { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; min-width: 0; }
.sb { width: 80%; background: #93c5fd; border-radius: 2px 2px 0 0; min-height: 1px; } .sb.fund { background: #1d4ed8; } .sb.hot { background: #dc2626; }
.cbars { margin: 6px 0; }
.cb { display: grid; grid-template-columns: 52px 1fr 44px; gap: 6px; align-items: center; margin: 2px 0; }
.cb .bar { background: #f1f5f9; border-radius: 3px; height: 10px; overflow: hidden; }
.cb .bar i { display: block; height: 100%; background: #a78bfa; } .cb .bar i.hot { background: #dc2626; } .cb .bar i.base { background: #9ca3af; }
.mags { display: grid; grid-template-columns: repeat(auto-fit, minmax(64px, 1fr)); gap: 6px; margin: 6px 0; }
.mag { border: 1px solid #e3e6ee; border-radius: 6px; padding: 4px; display: flex; flex-direction: column; align-items: center; font-size: 12px; }
.mag.hot { border-color: #fca5a5; background: #fef2f2; }
.ok { color: #15803d; } .bad { color: #b91c1c; }
</style>
