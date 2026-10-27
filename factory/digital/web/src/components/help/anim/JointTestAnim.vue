<template>
  <figure class="jt">
    <div class="ctl">
      <label for="jt-bl">背隙</label>
      <input id="jt-bl" v-model.number="backlash" type="range" min="0.2" max="1.6" step="0.05" aria-describedby="jt-note">
      <b class="mono">{{ backlash.toFixed(2) }}′</b>
      <label for="jt-fr">摩擦</label>
      <input id="jt-fr" v-model.number="friction" type="range" min="0.2" max="2.4" step="0.1">
      <b class="mono">{{ friction.toFixed(1) }} N·m</b>
      <button class="btn sm" @click="replay">从头演示</button>
    </div>
    <svg viewBox="0 0 520 230" role="img" :aria-label="`输入转角与输出转角的回差曲线：背隙 ${backlash.toFixed(2)} 角分`">
      <line x1="40" y1="200" x2="500" y2="200" class="axis" />
      <line x1="40" y1="20" x2="40" y2="200" class="axis" />
      <text x="500" y="218" text-anchor="end" class="lab">输入转角（电机侧，换算到输出）</text>
      <text x="46" y="16" class="lab">输出转角</text>
      <polyline :points="pathPts" class="trace" />
      <circle v-if="dot" :cx="dot[0]" :cy="dot[1]" r="5" class="dot" />
      <g v-if="phase >= 2">
        <line :x1="gapX" :y1="gapY1" :x2="gapX" :y2="gapY2" class="gap" />
        <text :x="gapX + 8" :y="(gapY1 + gapY2) / 2 + 4" class="lab strong">回差 = 背隙 {{ backlash.toFixed(2) }}′</text>
      </g>
    </svg>
    <ol class="steps" aria-label="关节测试三步">
      <li v-for="(s, i) in STEPS" :key="s" :class="{ on: i <= phase }"><span>{{ i + 1 }}</span>{{ s }}</li>
    </ol>
    <p class="verdict" :class="ok ? 'good' : 'bad'">
      {{ ok ? '合格' : '不合格' }}：背隙 {{ backlash.toFixed(2) }}′（上限 {{ LIMIT_BL }}′），空载摩擦力矩 {{ friction.toFixed(1) }} N·m（上限 {{ LIMIT_FR }} N·m）
    </p>
    <figcaption id="jt-note" class="small muted">示例数据（WQJ-L 一类大关节），不是本厂此刻的数。测试台先正转、再反转：反转刚开始时电机在转、输出还没动，
      这段“空程”就是背隙；空载时驱动电流换算出的力矩就是摩擦力矩。两项都进质量页的控制图。</figcaption>
  </figure>
</template>

<script setup>
// 关节测试台（第 45 轮机器人厂）：正转—反转一圈，画输入转角—输出转角曲线，回差就是背隙；拖背隙、摩擦看合不合格
import { computed, onMounted, onUnmounted, ref } from 'vue';

const STEPS = ['正转到位', '反转：先走完空程，输出才跟着动', '量出回差，与上限比'];
const LIMIT_BL = 1.0;
const LIMIT_FR = 2.0;
const backlash = ref(0.6);
const friction = ref(1.2);
const phase = ref(2);
const t = ref(1);
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
let timer;

// 输入从 0 走到 A 再回到 0；输出在反转开始的那段空程（背隙）里不动
const A = 6;                     // 角分，示意
const sx = (v) => 40 + (v / A) * 440;
const sy = (v) => 200 - (v / A) * 170;
const pts = computed(() => {
  const out = [];
  const b = backlash.value;
  for (let i = 0; i <= 60; i += 1) {          // 正转：输出 = 输入 − b/2（齿面贴着一侧）
    const x = (A * i) / 60;
    out.push([x, Math.max(0, x - b / 2)]);
  }
  for (let i = 0; i <= 60; i += 1) {          // 反转：先走 b 的空程输出不动，然后贴另一侧
    const x = A - (A * i) / 60;
    out.push([x, Math.max(0, Math.min(A - b / 2, x + b / 2))]);
  }
  return out;
});
const shown = computed(() => pts.value.slice(0, Math.max(2, Math.round(t.value * pts.value.length))));
const pathPts = computed(() => shown.value.map(([x, y]) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join(' '));
const dot = computed(() => {
  const p = shown.value[shown.value.length - 1];
  return p ? [sx(p[0]), sy(p[1])] : null;
});
const gapX = computed(() => sx(A / 2));
const gapY1 = computed(() => sy(A / 2 - backlash.value / 2));
const gapY2 = computed(() => sy(A / 2 + backlash.value / 2));
const ok = computed(() => backlash.value <= LIMIT_BL && friction.value <= LIMIT_FR);

function replay() {
  clearInterval(timer);
  if (reduced) { t.value = 1; phase.value = 2; return; }
  t.value = 0;
  phase.value = 0;
  timer = setInterval(() => {
    t.value = Math.min(1, t.value + 0.02);
    phase.value = t.value < 0.5 ? 0 : (t.value < 1 ? 1 : 2);
    if (t.value >= 1) clearInterval(timer);
  }, 60);
}
onMounted(replay);
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.jt { margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); }
.ctl { display: flex; align-items: center; gap: 8px 10px; flex-wrap: wrap; margin-bottom: 8px; }
.ctl input[type=range] { flex: 1; min-width: 110px; accent-color: var(--accent); }
svg { width: 100%; height: auto; display: block; }
.axis { stroke: var(--line); stroke-width: 1.5; }
.trace { fill: none; stroke: var(--accent); stroke-width: 2.5; stroke-linejoin: round; }
.dot { fill: var(--brand); }
.gap { stroke: var(--bad); stroke-width: 3; }
.lab { font-size: 12px; fill: var(--muted); }
.lab.strong { fill: var(--ink); font-weight: 600; }
.steps { list-style: none; display: flex; gap: 6px; padding: 0; margin: 8px 0; flex-wrap: wrap; }
.steps li { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); padding: 4px 10px 4px 4px; border-radius: 999px;
  background: var(--surface-2); transition: background 0.3s, color 0.3s; }
.steps li span { width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center; background: var(--line); font-weight: 700; font-size: 11px; }
.steps li.on { background: var(--task-bg); color: var(--ink); }
.steps li.on span { background: var(--brand); }
.verdict { margin: 6px 0; padding: 6px 10px; border-radius: 8px; font-size: 14px; font-weight: 600; }
.verdict.good { background: var(--good-bg); color: var(--good); }
.verdict.bad { background: var(--bad-bg); color: var(--bad); }
</style>
