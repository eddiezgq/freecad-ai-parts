<!-- 第 166 轮：计算机厂的整机老化曲线。老化房里每台整机跑满载压力测试，每分钟记 CPU 温度、风扇转速、整机功耗；
     帮学生从“曲线形状”追到原因：满载平台高、升温快、风扇早早到顶是导热硅脂那一层热阻大（点胶量少），按点胶机分开看就知道是哪台。 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('整机老化曲线') }}</h1>
      <span class="muted">{{ $t('老化过的每台整机：CPU 温度、风扇转速、整机功耗随时间；按点胶机分开看，找出问题从哪来') }}</span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div class="cols">
      <section class="card list">
        <div class="card-head"><h2>{{ $t('最近的整机（{a} 台）', { a: $td(shown.length) }) }}</h2></div>
        <div class="small">
          <label>{{ $t('型号') }}
            <select v-model="item"><option value="">{{ $t('全部') }}</option><option v-for="s in items" :key="s" :value="s">{{ $td(s) }}</option></select>
          </label>
          <label> · {{ $t('点胶机') }}
            <select v-model="disp"><option value="">{{ $t('全部') }}</option><option v-for="s in disps" :key="s" :value="s">{{ $td(s) }}</option></select>
          </label>
        </div>
        <div v-if="disps.length > 1" class="small muted">{{ $t('满载温度离上限的平均余量：') }}<span v-for="s in disps" :key="s" class="mono">{{ s }} {{ marginBy(s) }} ℃ · </span></div>
        <div v-if="!list.length" class="small muted">{{ $t('还没有。接一张台式机、笔记本或服务器订单，让车间做到“整机功能测试”。') }}</div>
        <button v-for="w in shown" :key="w.serial" class="brd" :class="{ on: sel === w.serial }" @click="open(w.serial)">
          <span class="mono">{{ $td(w.serial) }}</span>
          <span class="small" :class="w.pass ? 'ok' : 'bad'">{{ w.pass ? $t('合格') : $t('不合格') }}</span>
          <span class="small muted">{{ $t('{a}　点胶 {b}', { a: $td(w.item), b: w.dispenser || '—' }) }}</span>
          <span class="small muted">{{ $t('满载 {a} ℃　平均 {b} W', { a: v(w, 'pc_tmax', 1), b: v(w, 'pc_pavg', 0) }) }}</span>
        </button>
      </section>
      <section v-if="m" class="card main">
        <div class="card-head"><h2>{{ $td(m.serial) }} · <small class="muted">{{ $t('{a}　工单 {b}　点胶机 {c}　老化 {d} 分钟', { a: $td(m.item), b: $td(m.work_order), c: m.dispenser || '—', d: $td(m.minutes) }) }}</small></h2></div>
        <div class="kpis">
          <div :class="{ bad: m.limit && m.tmax > m.limit }"><b>{{ m.tmax.toFixed(1) }} ℃</b><span>{{ $t('CPU 满载温度（上限 {a}）', { a: m.limit || '—' }) }}</span></div>
          <div><b>{{ m.pavg.toFixed(0) }} W</b><span>{{ $t('老化平均功耗') }}</span></div>
          <div><b>{{ m.amb.toFixed(1) }} ℃</b><span>{{ $t('进风温度') }}</span></div>
          <div v-for="(r, k) in m.r_tim" :key="'r' + k"><b>{{ (r + m.r_hs[k]).toFixed(3) }}</b><span>{{ $t('CPU{a} 总热阻 ℃/W（硅脂层 {b}）', { a: m.cpus > 1 ? ' ' + (k + 1) : '', b: r.toFixed(3) }) }}</span></div>
          <div v-for="c in EXTRA" :key="c.code" :class="{ bad: exBad(c.code) }"><b>{{ exv(c.code, c.d) }}</b><span>{{ $td(c.label) }}</span></div>
        </div>
        <h3>{{ $t('CPU 温度（℃）') }}</h3>
        <svg :viewBox="`0 0 ${W} ${H}`" class="chart" role="img" :aria-label="$t('CPU 温度曲线')">
          <rect v-for="(b, i) in loadBands" :key="'b' + i" :x="x(b[0])" :width="x(b[1]) - x(b[0])" :y="PAD" :height="H - 2 * PAD" class="band" />
          <line v-if="m.limit" :x1="x(0)" :x2="x(m.minutes)" :y1="yt(m.limit)" :y2="yt(m.limit)" class="lim" />
          <polyline v-for="(t, k) in m.temp" :key="'t' + k" :points="pts(t, yt)" :class="'ln p' + k" />
          <text v-for="d in ticks" :key="'k' + d" :x="x(d)" :y="H - 2" class="tk" text-anchor="middle">{{ d }}</text>
          <text :x="PAD + 2" :y="12" class="tk">{{ tLo.toFixed(0) }}–{{ tHi.toFixed(0) }} ℃</text>
        </svg>
        <div class="grid2">
          <div>
            <h3>{{ $t('风扇转速（r/min）') }}</h3>
            <svg :viewBox="`0 0 ${W} ${H2}`" class="chart" role="img" :aria-label="$t('风扇转速曲线')">
              <rect v-for="(b, i) in loadBands" :key="'f' + i" :x="x(b[0])" :width="x(b[1]) - x(b[0])" :y="PAD" :height="H2 - 2 * PAD" class="band" />
              <polyline :points="pts(m.fan, (v) => yr(v, fanMax))" class="ln fan" />
              <text :x="PAD + 2" :y="12" class="tk">0–{{ fanMax.toFixed(0) }}</text>
            </svg>
          </div>
          <div>
            <h3>{{ $t('整机功耗（W）') }}</h3>
            <svg :viewBox="`0 0 ${W} ${H2}`" class="chart" role="img" :aria-label="$t('整机功耗曲线')">
              <rect v-for="(b, i) in loadBands" :key="'w' + i" :x="x(b[0])" :width="x(b[1]) - x(b[0])" :y="PAD" :height="H2 - 2 * PAD" class="band" />
              <polyline :points="pts(m.power, (v) => yr(v, pMax))" class="ln pw" />
              <text :x="PAD + 2" :y="12" class="tk">0–{{ pMax.toFixed(0) }}</text>
            </svg>
          </div>
        </div>
        <p class="small">{{ $t('浅色底是满载段（每小时满载 50 分钟、空闲 10 分钟），横轴是老化分钟。看三件事：满载平台有多高、升温有多快、风扇是不是一上来就转到顶——三样都高，热量出不去，先查导热硅脂那一层（点胶量）；风扇转速正常而温度高，不是风扇的问题。') }}</p>
        <p class="small muted">{{ $t('示例模型：功耗、热阻、风扇调速规律都是示例值；曲线每分钟一点，这里抽稀画。') }}</p>
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
const EXTRA = [
  { code: 'pc_noise', label: $t('满载风扇噪声 dB(A)'), d: 1 },
  { code: 'pc_boot', label: $t('开机到就绪 s'), d: 0 },
  { code: 'pc_membw', label: $t('内存带宽 GB/s'), d: 0 },
];
const list = ref([]);
const sel = ref('');
const m = ref(null);
const err = ref('');
const item = ref('');
const disp = ref('');
const route = useRoute();

const items = computed(() => [...new Set(list.value.map((w) => w.item).filter(Boolean))].sort());
const disps = computed(() => [...new Set(list.value.map((w) => w.dispenser).filter(Boolean))].sort());
const shown = computed(() => list.value.filter((w) => (!item.value || w.item === item.value) && (!disp.value || w.dispenser === disp.value)));
const cur = computed(() => list.value.find((w) => w.serial === sel.value));
const v = (w, c, d) => { const q = w.meas[c]; return q ? Number(q.v).toFixed(d) : '—'; };
function marginBy(s) {
  const a = list.value.filter((w) => w.dispenser === s && w.meas.pc_tmax).map((w) => Number(w.meas.pc_tmax.hi) - Number(w.meas.pc_tmax.v));
  return a.length ? (a.reduce((p, q) => p + q, 0) / a.length).toFixed(1) : '—';
}
const exv = (c, d) => { const q = cur.value && cur.value.meas[c]; return q ? Number(q.v).toFixed(d) : '—'; };
const exBad = (c) => { const q = cur.value && cur.value.meas[c]; return !!q && q.result !== 'pass'; };
const x = (min) => PAD + (W - 2 * PAD) * min / (m.value ? m.value.minutes : 1);
const tLo = computed(() => (m.value ? Math.min(...m.value.temp.flat()) - 3 : 0));
const tHi = computed(() => (m.value ? Math.max(...m.value.temp.flat(), m.value.limit || 0) + 3 : 100));
const yt = (t) => H - PAD - (H - 2 * PAD) * (t - tLo.value) / (tHi.value - tLo.value);
const fanMax = computed(() => (m.value ? Math.max(...m.value.fan) * 1.1 : 1));
const pMax = computed(() => (m.value ? Math.max(...m.value.power) * 1.1 : 1));
const yr = (val, mx) => H2 - PAD - (H2 - 2 * PAD) * val / mx;
const ticks = computed(() => { if (!m.value) return []; const st = m.value.minutes > 300 ? 120 : 60; const a = []; for (let d = 0; d <= m.value.minutes; d += st) a.push(d); return a; });
const loadBands = computed(() => {
  if (!m.value) return [];
  const out = []; let s = null;
  m.value.load.forEach((l, i) => {
    const t = m.value.minute[i];
    if (l && s === null) s = t;
    if (!l && s !== null) { out.push([s, t]); s = null; }
  });
  if (s !== null) out.push([s, m.value.minutes]);
  return out;
});
function pts(arr, fy) { return arr.map((e, i) => x(m.value.minute[i]).toFixed(1) + ',' + fy(e).toFixed(1)).join(' '); }
async function open(s) {
  sel.value = s; err.value = '';
  try { m.value = await get('/computer/unit/' + encodeURIComponent(s)); } catch (e) { err.value = e.message; }
}
onMounted(async () => {
  try {
    list.value = (await get('/computer/units')).units;
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
.chart .band { fill: #fff7ed; }
.chart .lim { stroke: #dc2626; stroke-dasharray: 4 3; }
.chart .ln { fill: none; stroke-width: 1.2; }
.chart .p0 { stroke: #dc2626; } .chart .p1 { stroke: #f59e0b; }
.chart .fan { stroke: #1d4ed8; } .chart .pw { stroke: #0f766e; }
.chart .tk { font-size: 10px; fill: #6b7280; }
.ok { color: #15803d; } .bad { color: #b91c1c; }
</style>
