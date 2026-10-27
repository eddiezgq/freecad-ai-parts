<template>
  <figure class="spc">
    <div class="ctl">
      <button class="btn sm" @click="restart">重新开始</button>
      <span class="small muted">已测 {{ pts.length }} 件{{ alarm ? ` · ${alarm}` : '' }}</span>
    </div>
    <svg viewBox="0 0 760 210" role="img" :aria-label="`控制图演示：已测 ${pts.length} 件，${alarm || '受控'}`">
      <line x1="40" :y1="Y(USL)" x2="706" :y2="Y(USL)" class="spec" /><text x="712" :y="Y(USL) + 4" class="lb">上限</text>
      <line x1="40" :y1="Y(LSL)" x2="706" :y2="Y(LSL)" class="spec" /><text x="712" :y="Y(LSL) + 4" class="lb">下限</text>
      <line x1="40" :y1="Y(UCL)" x2="706" :y2="Y(UCL)" class="ctl-l" /><text x="712" :y="Y(UCL) + 4" class="lb">UCL</text>
      <line x1="40" :y1="Y(LCL)" x2="706" :y2="Y(LCL)" class="ctl-l" /><text x="712" :y="Y(LCL) + 4" class="lb">LCL</text>
      <line x1="40" :y1="Y(0)" x2="706" :y2="Y(0)" class="mid" />
      <polyline :points="pts.map((v, i) => `${X(i)},${Y(v)}`).join(' ')" class="ln" />
      <circle v-for="(v, i) in pts" :key="i" :cx="X(i)" :cy="Y(v)" r="5" :class="cls(i)" />
      <rect v-if="hit" :x="X(hit.from) - 9" :y="Y(UCL) - 4" :width="X(hit.at) - X(hit.from) + 18" :height="Y(0) - Y(UCL) + 8" rx="6" class="box" />
    </svg>
    <figcaption class="small muted">示例：磨床磨的轴承位直径，每件测一次。点子在中线附近上下跳是正常的；砂轮慢慢磨钝，点子<b>一路偏向一边</b>——
      还没出上限、零件还合格，判异规则（和平台“质量”页同一套西电规则 1–4）已经报警，这时修整砂轮最便宜。不管它，后面就出不合格品了。</figcaption>
  </figure>
</template>

<script setup>
// 控制图：砂轮磨钝 → 判异报警（西电规则）→ 再不管就超差（第 30 轮 §八 8-2，质量）。
import { computed, onMounted, onUnmounted, ref } from 'vue';

const USL = 3.4, LSL = -3.4, UCL = 2.4, LCL = -2.4;
// 前 12 件正常波动；之后砂轮磨钝，一件比一件大；第 19 件触发判异（还在上限以内）；再往后超差
const DATA = [0.4, -0.7, 0.9, -0.2, -1.1, 0.6, 0.1, -0.5, 1.2, -0.9, 0.3, -0.4,
  -0.1, 0.3, 0.7, 1.0, 1.4, 1.7, 2.0, 2.3, 2.6, 2.9, 3.2, 3.5, 3.8, 4.0, 4.2, 4.4, 4.5, 4.6];
const N = DATA.length;
const SIG = UCL / 3;
const pts = ref([]);
const next = (i) => DATA[i];
const X = (i) => 50 + i * 22;
const Y = (v) => 115 - v * 22;
// 西电规则 1–4（与 hub/spc.py 同一套）：第一次触发在哪一点、哪条、从哪一点起
const TEXT = { 1: '1 点出 3σ', 2: '连续 3 点中 2 点在 2σ 外同侧', 3: '连续 5 点中 4 点在 1σ 外同侧', 4: '连续 8 点在中心线同侧' };
function rules(p, i) {
  const side = (a, b, k) => { const w = p.slice(Math.max(0, i - a + 1), i + 1); return w.length === a && (w.filter((v) => v > k * SIG).length >= b || w.filter((v) => v < -k * SIG).length >= b); };
  if (Math.abs(p[i]) > 3 * SIG) return { rule: 1, from: i };
  if (side(3, 2, 2)) return { rule: 2, from: i - 2 };
  if (side(5, 4, 1)) return { rule: 3, from: i - 4 };
  if (side(8, 8, 0)) return { rule: 4, from: i - 7 };
  return null;
}
const hit = computed(() => {
  for (let i = 0; i < pts.value.length; i++) { const r = rules(pts.value, i); if (r) return { ...r, at: i }; }
  return null;
});
const firstOut = computed(() => pts.value.findIndex((v) => v > USL));
const alarm = computed(() => (firstOut.value >= 0 ? '超出上限：出不合格品了' : hit.value ? `判异：${TEXT[hit.value.rule]}——报警，去修整砂轮` : ''));
function cls(i) { const v = pts.value[i]; return v > USL || v < LSL ? 'ng' : hit.value && i >= hit.value.from ? 'warn' : 'ok'; }
let timer;
function restart() {
  clearInterval(timer); pts.value = [];
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { for (let i = 0; i < N; i++) pts.value.push(next(i)); return; }
  timer = setInterval(() => {
    if (pts.value.length < N) pts.value.push(next(pts.value.length));
    else { clearInterval(timer); setTimeout(restart, 3000); }
  }, 450);
}
onMounted(restart);
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.spc { margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); }
.ctl { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 6px; }
svg { width: 100%; height: auto; display: block; }
.spec { stroke: var(--bad); stroke-width: 2; }
.ctl-l { stroke: var(--warn); stroke-width: 1.5; stroke-dasharray: 6 4; }
.mid { stroke: var(--line); stroke-width: 1; }
.lb { font-size: 11px; fill: var(--muted); }
.ln { fill: none; stroke: var(--muted); stroke-width: 1.5; }
circle.ok { fill: var(--accent); }
circle.warn { fill: var(--warn); }
circle.ng { fill: var(--bad); }
.box { fill: none; stroke: var(--warn); stroke-width: 2; stroke-dasharray: 4 3; }
figcaption { margin-top: 6px; line-height: 1.7; }
</style>
