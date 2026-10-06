<template>
  <div class="gv">
    <svg :viewBox="`0 0 ${W} ${H}`" width="100%" :height="H" role="img" aria-label="键槽刀路（侧视，X 沿轴线，Z 竖直）">
      <rect :x="sx(slot.x_from - 20)" :y="sz(0)" :width="(slot.x_to - slot.x_from + 40) * k" :height="H - sz(0) - 8" fill="#E6E9E4" />
      <rect :x="sx(slot.x_from)" :y="sz(0)" :width="(slot.x_to - slot.x_from) * k" :height="slot.depth * k" fill="#fff" stroke="#8C96A0" stroke-dasharray="3 2" />
      <polyline v-for="(seg, i) in segs" :key="i" :points="seg.pts" fill="none" :stroke="seg.rapid ? '#9AA3AD' : 'var(--accent)'"
        :stroke-dasharray="seg.rapid ? '4 3' : null" stroke-width="1.6" />
      <circle v-if="tool" :cx="sx(tool[0])" :cy="sz(tool[2])" r="5" fill="var(--warn)" />
    </svg>
    <div class="ctl small">
      <button class="btn ghost" @click="play">{{ playing ? '暂停' : '回放刀路' }}</button>
      <span class="muted">灰虚线：快移；实线：切削。共 {{ pts.length }} 个刀位点</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref } from 'vue';
import { parseGcode } from '../lib/gcode';

const props = defineProps({ code: String, slot: Object });
const W = 520, H = 160;
const pts = computed(() => parseGcode(props.code || ''));
const x0 = computed(() => props.slot.x_from - 25);
const k = computed(() => (W - 20) / (props.slot.x_to - props.slot.x_from + 50));
const sx = (x) => 10 + (x - x0.value) * k.value;
const sz = (z) => 30 - z * k.value;
const segs = computed(() => {
  const out = [];
  for (let i = 1; i < pts.value.length; i++) {
    const a = pts.value[i - 1], b = pts.value[i];
    out.push({ rapid: b[3], pts: `${sx(a[0])},${sz(a[2])} ${sx(b[0])},${sz(b[2])}` });
  }
  return out;
});
const tool = ref(null);
const playing = ref(false);
let raf;
function play() {
  if (playing.value) { playing.value = false; cancelAnimationFrame(raf); return; }
  playing.value = true;
  let i = 0, f = 0;
  const step = () => {
    if (!playing.value) return;
    const a = pts.value[i], b = pts.value[i + 1];
    if (!b) { playing.value = false; return; }
    f += 0.04;
    tool.value = [a[0] + (b[0] - a[0]) * f, 0, a[2] + (b[2] - a[2]) * f];
    if (f >= 1) { f = 0; i += 1; }
    raf = requestAnimationFrame(step);
  };
  step();
}
onUnmounted(() => cancelAnimationFrame(raf));
</script>

<style scoped>
.ctl { display: flex; gap: 10px; align-items: center; margin-top: 6px; }
</style>
