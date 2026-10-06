<template>
  <div class="mill">
    <div class="wrap">
      <canvas ref="cv" :width="W" :height="Hh" @mousemove="hover" @mouseleave="tip = ''" />
      <div v-if="tip" class="tip small mono">{{ tip }}</div>
    </div>
    <div class="legend small">
      <span class="bar" /> 上表面 → 最深 {{ zmin.toFixed(2) }} mm（颜色越深越低）
      <span class="k feed" />切削 <span class="k rapid" />快移 <span class="k cur" />刀具
      <span class="muted">· 俯视图，X 向右、Y 向上；鼠标停在图上看高度</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, shallowRef, watch } from 'vue';
import { MillSim, toolAt } from '../lib/cam';

const props = defineProps({
  prog: { type: Object, required: true }, stock: { type: Object, required: true },
  time: { type: Number, default: 0 }, final: { type: Object, default: null },     // final：服务器算的最终高度图 Float32Array
});
const cv = ref(null);
const tip = ref('');
const sim = shallowRef(null);
const g = computed(() => props.prog.sim);
const scale = computed(() => Math.max(1, Math.floor(820 / g.value.nx)));
const W = computed(() => g.value.nx * scale.value);
const Hh = computed(() => g.value.ny * scale.value);
const top = computed(() => props.stock.top ?? 0);
const zmin = computed(() => {
  let m = 0;
  const H = props.final || sim.value?.H;
  if (H) for (let q = 0; q < H.length; q++) if (H[q] < m && H[q] > -1e5) m = H[q];
  return m;
});

watch(() => [props.prog, props.stock], () => { sim.value = new MillSim(g.value, props.stock, props.prog.tools || {}); }, { immediate: true });
const cur = computed(() => toolAt(props.prog.path, props.time));

function color(z) {
  if (Number.isNaN(z) || z < -1e5) return [251, 252, 251];
  const f = Math.min(1, Math.max(0, (top.value - z) / Math.max(1e-6, top.value - zmin.value)));
  return [Math.round(226 - 170 * f), Math.round(230 - 150 * f), Math.round(222 - 60 * f)];
}
function draw() {
  const c = cv.value; if (!c || !sim.value) return;
  const ctx = c.getContext('2d');
  const { nx, ny } = g.value; const k = scale.value;
  const end = cur.value.i >= props.prog.path.length - 1 && props.final;
  if (!end) sim.value.advance(props.prog.path, Math.max(0, cur.value.i - 1));
  const H = end ? props.final : sim.value.H;
  const img = ctx.createImageData(nx * k, ny * k);
  for (let i = 0; i < nx; i++) {
    for (let j = 0; j < ny; j++) {
      const [r, gg, b] = color(H[i * ny + j]);
      for (let a = 0; a < k; a++) for (let bb = 0; bb < k; bb++) {
        const px = ((ny - 1 - j) * k + bb) * nx * k + i * k + a;
        img.data[4 * px] = r; img.data[4 * px + 1] = gg; img.data[4 * px + 2] = b; img.data[4 * px + 3] = 255;
      }
    }
  }
  ctx.putImageData(img, 0, 0);
  const X = (x) => ((x - g.value.x0) / g.value.h + 0.5) * k, Y = (y) => (ny - 0.5 - (y - g.value.y0) / g.value.h) * k;
  const p = props.prog.path; const ci = cur.value.i;
  ctx.lineWidth = 1;
  for (const kind of [1, 0]) {
    ctx.beginPath();
    ctx.setLineDash(kind ? [] : [5, 4]);
    ctx.strokeStyle = kind ? 'rgba(27,94,32,0.85)' : 'rgba(224,123,0,0.75)';
    for (let i = 1; i < Math.min(ci, p.length); i++) {
      if (p[i][0] !== kind) continue;
      ctx.moveTo(X(p[i - 1][1]), Y(p[i - 1][2])); ctx.lineTo(X(p[i][1]), Y(p[i][2]));
    }
    ctx.stroke();
  }
  ctx.setLineDash([]);
  const t = cur.value.p;
  if (t) {
    const tl = (props.prog.tools || {})[t[6]] || (props.prog.tools || {})[String(t[6])];
    ctx.beginPath(); ctx.strokeStyle = '#C62828'; ctx.lineWidth = 2;
    ctx.arc(X(t[1]), Y(t[2]), ((tl?.d || 6) / 2 / g.value.h) * k, 0, 2 * Math.PI); ctx.stroke();
  }
}
let raf = 0;
watch([cur, () => props.final, sim], () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(draw); });
onMounted(draw);

function hover(ev) {
  const c = cv.value; const rect = c.getBoundingClientRect();
  const px = (ev.clientX - rect.left) * (c.width / rect.width) / scale.value, py = (ev.clientY - rect.top) * (c.height / rect.height) / scale.value;
  const i = Math.floor(px), j = g.value.ny - 1 - Math.floor(py);
  if (i < 0 || j < 0 || i >= g.value.nx || j >= g.value.ny) { tip.value = ''; return; }
  const H = (cur.value.i >= props.prog.path.length - 1 && props.final) ? props.final : sim.value.H;
  const z = H[i * g.value.ny + j];
  tip.value = `X${(g.value.x0 + i * g.value.h).toFixed(2)} Y${(g.value.y0 + j * g.value.h).toFixed(2)}  ` + (Number.isNaN(z) || z < -1e5 ? '（没有材料）' : `高度 Z${z.toFixed(3)}`);
}
</script>

<style scoped>
.mill { display: flex; flex-direction: column; gap: 4px; }
.wrap { position: relative; }
canvas { width: 100%; max-height: 460px; object-fit: contain; border: 1px solid var(--line); border-radius: 8px; background: #FBFCFB; image-rendering: pixelated; }
.tip { position: absolute; left: 8px; top: 8px; background: rgba(255,255,255,0.9); border: 1px solid var(--line); border-radius: 6px; padding: 2px 6px; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; }
.bar { display: inline-block; width: 60px; height: 8px; border-radius: 2px; background: linear-gradient(90deg, rgb(226,230,222), rgb(56,80,162)); }
.k { display: inline-block; width: 14px; height: 2px; margin-right: 3px; vertical-align: middle; }
.k.feed { background: #1B5E20; }
.k.rapid { background: repeating-linear-gradient(90deg, #E07B00 0 4px, transparent 4px 7px); }
.k.cur { width: 8px; height: 8px; border: 2px solid #C62828; border-radius: 50%; }
</style>
