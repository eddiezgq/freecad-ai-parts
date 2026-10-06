<template>
  <div class="lathe">
    <svg ref="svg" :viewBox="vb" preserveAspectRatio="xMidYMid meet" @mousemove="hover" @mouseleave="tip = null">
      <line :x1="zL" :x2="zR" y1="0" y2="0" class="axis" />
      <line x1="0" x2="0" :y1="-rmax" :y2="rmax" class="z0" />
      <text x="0.6" :y="-rmax + 3" class="lbl" :font-size="fs">Z0</text>
      <path :d="stockPath" class="stock" />
      <path :d="matPath" class="mat" />
      <polyline :points="targetPts" class="target" />
      <polyline :points="targetPtsLow" class="target low" />
      <path :d="pathDone.rapid" class="rapid" />
      <path :d="pathDone.feed" class="feed" />
      <path :d="pathTodo" class="todo" />
      <g v-if="tool" :transform="`translate(${tool[3]},${-tool[1] / 2})`">
        <polygon :points="`0,0 ${3 * s},${-1.2 * s} ${3 * s},${-5 * s} ${1.2 * s},${-5 * s}`" class="tool" />
      </g>
      <g v-if="tip"><circle :cx="tip.z" :cy="-tip.r" :r="0.8 * s" class="dot" />
        <text :x="tip.z + 1.5 * s" :y="-tip.r - 1.5 * s" :font-size="fs" class="lbl">Z{{ tip.z.toFixed(2) }} Ø{{ (2 * tip.r).toFixed(3) }}{{ tip.t !== null ? '（目标 Ø' + (2 * tip.t).toFixed(3) + '）' : '' }}</text></g>
    </svg>
    <div class="legend small"><span class="k stock" />毛坯 <span class="k mat" />剩下的材料 <span class="k target" />目标（本工序尺寸）
      <span class="k feed" />切削 <span class="k rapid" />快移 <span class="muted">· 只画上半边刀路；鼠标停在轮廓上看直径</span></div>
  </div>
</template>

<script setup>
import { computed, ref, shallowRef, watch } from 'vue';
import { LatheSim, toolAt } from '../lib/cam';

const props = defineProps({ prog: { type: Object, required: true }, time: { type: Number, default: 0 } });
const svg = ref(null);
const tip = ref(null);
const sim = shallowRef(null);
const ver = ref(0);

const st = computed(() => props.prog.stock);
const zL = computed(() => st.value.z_left - 3);
const zR = computed(() => Math.max(st.value.z_right, 0) + 8);
const rmax = computed(() => (st.value.d || 50) / 2 + 6);
const vb = computed(() => `${zL.value} ${-rmax.value} ${zR.value - zL.value} ${2 * rmax.value}`);
const s = computed(() => (zR.value - zL.value) / 200);
const fs = computed(() => 3.2 * s.value);

watch(() => props.prog, (p) => { sim.value = new LatheSim(p.stock, 0.05); ver.value++; }, { immediate: true });
const cur = computed(() => toolAt(props.prog.path, props.time));
const tool = computed(() => cur.value.p);
watch([cur, sim], ([c]) => { if (sim.value) { sim.value.advance(props.prog.path, Math.max(0, c.i - 1)); ver.value++; } }, { immediate: true });

function outline(zs, rs, step) {
  let up = '', lo = '';
  for (let i = 0; i < zs.length; i += step) { up += `${i ? 'L' : 'M'}${zs[i].toFixed(3)},${(-rs[i]).toFixed(3)}`; }
  for (let i = zs.length - 1; i >= 0; i -= step) { lo += `L${zs[i].toFixed(3)},${rs[i].toFixed(3)}`; }
  return up + lo + 'Z';
}
const stockPath = computed(() => { const x = sim.value; return x ? outline(x.zc, x.init, Math.max(1, Math.floor(x.n / 1200))) : ''; });
const matPath = computed(() => {
  ver.value; // eslint-disable-line no-unused-expressions
  const x = sim.value; if (!x) return '';
  // 当前刀位那一段也画进去（段内插值）
  return outline(x.zc, x.r, Math.max(1, Math.floor(x.n / 1200)));
});
const targetPts = computed(() => props.prog.sim.target.map(([z, d]) => `${z},${-d / 2}`).join(' '));
const targetPtsLow = computed(() => props.prog.sim.target.map(([z, d]) => `${z},${d / 2}`).join(' '));
function segs(from, to, kind) {
  const p = props.prog.path; let d = '';
  for (let i = Math.max(1, from); i <= to && i < p.length; i++) {
    if (kind !== undefined && p[i][0] !== kind) continue;
    d += `M${p[i - 1][3]},${-p[i - 1][1] / 2}L${p[i][3]},${-p[i][1] / 2}`;
  }
  return d;
}
const pathDone = computed(() => {
  const c = cur.value; const p = props.prog.path;
  let feed = segs(1, c.i - 1, 1), rapid = segs(1, c.i - 1, 0);
  if (c.i > 0 && c.p) {
    const a = p[c.i - 1]; const piece = `M${a[3]},${-a[1] / 2}L${c.p[3]},${-c.p[1] / 2}`;
    if (p[c.i][0] === 1) feed += piece; else rapid += piece;
  }
  return { feed, rapid };
});
const pathTodo = computed(() => segs(cur.value.i + 1, props.prog.path.length - 1));

function hover(ev) {
  const el = svg.value; if (!el || !sim.value) return;
  const pt = el.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
  const q = pt.matrixTransform(el.getScreenCTM().inverse());
  const x = sim.value; const i = Math.round((q.x - x.z0) / x.h - 0.5);
  if (i < 0 || i >= x.n) { tip.value = null; return; }
  const tg = props.prog.sim.target; const z = x.zc[i];
  const zs = tg.map((t) => t[0]);
  let t = null;
  if (z <= Math.max(...zs) && z >= Math.min(...zs)) {
    for (let k = 0; k + 1 < tg.length; k++) {
      const [z0, d0] = tg[k], [z1, d1] = tg[k + 1];
      if (Math.min(z0, z1) <= z && z <= Math.max(z0, z1) && Math.abs(z1 - z0) > 1e-9) { t = (d0 + (d1 - d0) * (z - z0) / (z1 - z0)) / 2; break; }
    }
  }
  tip.value = { z, r: x.r[i], t };
}
</script>

<style scoped>
.lathe { display: flex; flex-direction: column; gap: 4px; }
svg { width: 100%; height: 330px; background: #FBFCFB; border: 1px solid var(--line); border-radius: 8px; }
.axis { stroke: #9AA39A; stroke-width: 0.25; stroke-dasharray: 4 1 1 1; }
.z0 { stroke: #C9A227; stroke-width: 0.2; stroke-dasharray: 1 1; }
.stock { fill: #ECEEEA; stroke: #C5CBC3; stroke-width: 0.15; }
.mat { fill: #B9C4CF; stroke: #6D7F92; stroke-width: 0.15; }
.target { fill: none; stroke: #1F6FD1; stroke-width: 0.35; }
.target.low { stroke-dasharray: 1 0.6; stroke-width: 0.2; }
.feed { stroke: #1B5E20; stroke-width: 0.3; fill: none; }
.rapid { stroke: #E07B00; stroke-width: 0.25; stroke-dasharray: 1.2 0.8; fill: none; }
.todo { stroke: #8B958B; stroke-width: 0.12; stroke-dasharray: 0.6 0.6; fill: none; opacity: 0.6; }
.tool { fill: #C62828; opacity: 0.9; }
.dot { fill: #C62828; }
.lbl { fill: #333; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; }
.k { display: inline-block; width: 14px; height: 8px; border-radius: 2px; margin-right: 3px; vertical-align: middle; }
.k.stock { background: #ECEEEA; border: 1px solid #C5CBC3; }
.k.mat { background: #B9C4CF; }
.k.target { background: #1F6FD1; height: 2px; }
.k.feed { background: #1B5E20; height: 2px; }
.k.rapid { background: repeating-linear-gradient(90deg, #E07B00 0 4px, transparent 4px 7px); height: 2px; }
</style>
