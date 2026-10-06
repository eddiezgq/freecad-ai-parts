<!-- 推演甘特图（第 17 轮 C 期）：设备 × 时间，按工单着色；停机斜线、下班灰底、加班橙底 -->
<template>
  <div class="gc">
    <div class="range small">看
      <button v-for="h in [24, 72, 0]" :key="h" :class="{ on: hours === h }" @click="hours = h">{{ h ? (h / 24) + ' 天' : '全部' }}</button></div>
    <div v-if="!rows.length" class="muted small">这段时间没有加工安排。</div>
    <svg v-else :viewBox="`0 0 ${W} ${H}`" :height="H" class="svg" role="img" :aria-label="'甘特图：' + rows.length + ' 台设备'">
      <defs>
        <pattern id="gc-down" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="6" height="6" fill="#FCE8E6" /><line x1="0" y1="0" x2="0" y2="6" stroke="#B42318" stroke-width="2" />
        </pattern>
      </defs>
      <!-- 下班、加班底色 -->
      <rect v-for="(b, i) in bands" :key="'b' + i" :x="x(b.s)" y="18" :width="Math.max(0, x(b.e) - x(b.s))" :height="H - 18"
        :fill="b.ot ? '#FBF1DC' : '#EEF0EC'" />
      <!-- 时间刻度 -->
      <g v-for="(t, i) in ticks" :key="'t' + i">
        <line :x1="x(t.t)" y1="16" :x2="x(t.t)" :y2="H" stroke="#DDE1DC" />
        <text :x="x(t.t) + 3" y="12" font-size="10" fill="#5D6873">{{ t.label }}</text>
      </g>
      <g v-for="(r, i) in rows" :key="r">
        <text x="4" :y="24 + i * ROW + ROW / 2 + 4" font-size="11" fill="#17212B" font-family="IBM Plex Mono, monospace">{{ r.toUpperCase() }}</text>
        <line :x1="LEFT" :y1="20 + (i + 1) * ROW" :x2="W" :y2="20 + (i + 1) * ROW" stroke="#EEF0EC" />
      </g>
      <rect v-for="(d, i) in downs" :key="'d' + i" :x="x(d.s)" :y="22 + rowOf(d.unit) * ROW" :width="Math.max(2, x(d.e) - x(d.s))"
        :height="ROW - 6" fill="url(#gc-down)"><title>{{ d.unit.toUpperCase() }} 停机：{{ d.reason }}</title></rect>
      <rect v-for="(g, i) in segs" :key="'g' + i" :x="x(g.s)" :y="24 + rowOf(g.unit) * ROW" :width="Math.max(1.5, x(g.e) - x(g.s) - 0.5)"
        :height="ROW - 10" :fill="color(g.wo)" rx="1.5"><title>{{ g.wo }} · {{ g.op }} · {{ g.part }}
{{ fmt(g.s) }} – {{ fmt(g.e) }}</title></rect>
      <line v-if="nowX" :x1="nowX" y1="16" :x2="nowX" :y2="H" stroke="#0E5E6F" stroke-dasharray="3 3" />
    </svg>
    <div class="legend small">
      <span v-for="w in wos" :key="w"><i :style="{ background: color(w) }"></i>{{ w }}</span>
      <span><i class="down"></i>停机</span><span><i class="off"></i>下班</span><span><i class="ot"></i>加班</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';

const props = defineProps({ result: Object, width: { type: Number, default: 900 } });
const W = computed(() => props.width).value;
const LEFT = 78;
const ROW = 22;
const PALETTE = ['#0E5E6F', '#C7652E', '#5B4B8A', '#1F7A4D', '#B5487A', '#7A6A2E', '#2F6FB3', '#A23B3B'];

const hours = ref(24);
const tEnd = computed(() => (hours.value ? Date.parse(props.result?.start || 0) + hours.value * 3600e3 : Infinity));
const segs = computed(() => (props.result?.gantt || []).map((g) => ({ ...g, s: Date.parse(g.start), e: Date.parse(g.end) }))
  .filter((g) => g.s < tEnd.value).map((g) => ({ ...g, e: Math.min(g.e, tEnd.value) })));
const downs = computed(() => (props.result?.downtime || []).map((d) => ({ ...d, s: Date.parse(d.start), e: Date.parse(d.end) }))
  .filter((d) => d.s < tEnd.value).map((d) => ({ ...d, e: Math.min(d.e, tEnd.value) })));
const rows = computed(() => [...new Set(segs.value.map((g) => g.unit).concat(downs.value.map((d) => d.unit)))].sort());
const wos = computed(() => [...new Set(segs.value.map((g) => g.wo))]);
const t0 = computed(() => Date.parse(props.result?.start || 0));
const t1 = computed(() => (hours.value ? tEnd.value : Math.max(t0.value + 3600e3, ...segs.value.map((g) => g.e), ...downs.value.map((d) => d.e))));
const H = computed(() => 24 + Math.max(1, rows.value.length) * ROW + 4);
function x(t) { return LEFT + ((t - t0.value) / (t1.value - t0.value)) * (W - LEFT - 6); }
function rowOf(u) { return rows.value.indexOf(u); }
function color(w) { const i = wos.value.indexOf(w); return PALETTE[(i < 0 ? 0 : i) % PALETTE.length]; }
const tz = computed(() => props.result?.calendar?.tz || 'America/New_York');
function fmt(t) { return new Date(t).toLocaleString('zh-CN', { timeZone: tz.value, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }); }
const nowX = computed(() => x(t0.value));
const ticks = computed(() => {
  const span = t1.value - t0.value;
  const step = span > 4 * 86400e3 ? 86400e3 : span > 36 * 3600e3 ? 6 * 3600e3 : span > 8 * 3600e3 ? 2 * 3600e3 : 3600e3;
  const out = [];
  for (let t = Math.ceil(t0.value / step) * step; t < t1.value; t += step) out.push({ t, label: fmt(t).slice(step >= 86400e3 ? 0 : 6) });
  return out;
});
// 下班（灰）与加班（橙）：按日历在工厂时区算每天的窗口
const bands = computed(() => {
  const cal = props.result?.calendar;
  if (!cal || cal.mode !== 'shift') return [];
  const out = [];
  const hm = (s) => { const [h, m] = s.split(':').map(Number); return h * 60 + m; };
  const day0 = new Date(t0.value);
  for (let i = -1; i <= 15; i += 1) {
    const d = new Date(day0.getTime() + i * 86400e3);
    const ymd = d.toLocaleDateString('en-CA', { timeZone: cal.tz });
    const wd = new Date(ymd + 'T12:00:00Z').getUTCDay();
    const work = (cal.workdays || [0, 1, 2, 3, 4]).includes((wd + 6) % 7);
    // 当天 00:00 的工厂时区时刻：用时区偏移近似
    const midnight = Date.parse(ymd + 'T00:00:00Z') - tzOffset(cal.tz, ymd);
    const ot = Math.max(cal.overtime?.[ymd + '|*'] || 0, 0);
    const s = midnight + hm(cal.start) * 60e3;
    const e = midnight + hm(cal.end) * 60e3;
    if (work) {
      out.push({ s: midnight, e: s });
      if (ot) out.push({ s: e, e: e + ot * 60e3, ot: true });
      out.push({ s: e + ot * 60e3, e: midnight + 86400e3 });
    } else {
      out.push({ s: midnight, e: midnight + 86400e3 });
    }
  }
  return out.filter((b) => b.e > t0.value && b.s < t1.value).map((b) => ({ ...b, s: Math.max(b.s, t0.value), e: Math.min(b.e, t1.value) }));
});
function tzOffset(tzName, ymd) {
  const d = new Date(ymd + 'T12:00:00Z');
  const loc = new Date(d.toLocaleString('en-US', { timeZone: tzName }));
  const utc = new Date(d.toLocaleString('en-US', { timeZone: 'UTC' }));
  return loc - utc;
}
</script>

<style scoped>
.gc { overflow-x: auto; max-width: 100%; }
.range { display: flex; gap: 4px; align-items: center; margin-bottom: 4px; color: var(--muted); }
.range button { border: 1px solid var(--line); background: var(--surface); border-radius: 4px; padding: 1px 8px; cursor: pointer; font-size: 12px; }
.range button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.svg { width: 100%; min-width: 640px; display: block; }
.legend { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 4px; color: var(--muted); }
.legend i { display: inline-block; width: 12px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: -1px; }
.legend i.down { background: repeating-linear-gradient(45deg, #FCE8E6, #FCE8E6 3px, #B42318 3px, #B42318 4px); }
.legend i.off { background: #EEF0EC; border: 1px solid #DDE1DC; }
.legend i.ot { background: #FBF1DC; border: 1px solid #EDD58A; }
</style>
