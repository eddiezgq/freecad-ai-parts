<template>
  <div v-if="tour.id" class="tour" role="dialog" aria-live="polite" :aria-label="'带我去做：' + tour.title">
    <!-- 这一节完成（第 30 轮 §八：带“做完检测”的引导，每一步都真做了） -->
    <div v-if="tour.finished" class="bubble fin" style="left: 50%; top: 30%; transform: translateX(-50%)">
      <p class="t small">{{ tour.title }}</p>
      <p class="big">这一节完成 ✓</p>
      <ol class="ticks small"><li v-for="(s, k) in tour.steps" :key="k" :class="{ ok: tour.ok[k] }">{{ shortStep(s.text) }}</li></ol>
      <div class="acts"><button class="btn primary" @click="stopTour">好的</button>
        <router-link class="link small" to="/help" @click="stopTour">回帮助</router-link></div>
    </div>
    <template v-else>
    <div v-if="box" class="spot" :class="{ ok: tour.ok[tour.i] }" :style="spotStyle"></div>
    <div class="bubble" :style="bubbleStyle">
      <p class="t small">{{ tour.title }} · 第 {{ tour.i + 1 }} / {{ tour.steps.length }} 步
        <span v-if="anyDone" class="dots" aria-hidden="true"><i v-for="(s, k) in tour.steps" :key="k" :class="{ ok: tour.ok[k], cur: k === tour.i }"></i></span></p>
      <p class="body">{{ step.text }}</p>
      <p v-if="step.done && tour.ok[tour.i]" class="okline">✓ 做到了</p>
      <p v-else-if="step.done" class="small wait">请在页面上做这一步，做完会自动打勾。</p>
      <p v-if="!box" class="small muted">{{ missing }}</p>
      <div class="acts">
        <button class="btn" :disabled="tour.i === 0" @click="prevStep">上一步</button>
        <button class="btn primary" @click="nextStep">{{ tour.i < tour.steps.length - 1 ? '下一步' : '完成' }}</button>
        <button class="link small" @click="stopTour">退出引导</button>
      </div>
    </div>
    </template>
  </div>
</template>

<script setup>
// 引导层：给当前步骤的页面元素（data-help 标记）开一个“聚光灯”，旁边放说明。元素晚加载时会等一会儿再找。
import { computed, onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { get } from '../lib/api';
import { tour, nextStep, prevStep, stopTour, markDone, met, pick } from '../lib/tour';

const box = ref(null);
const missing = ref('');
const step = computed(() => tour.steps[tour.i] || {});
// 完成页的步骤清单：每步取第一句（到“：”或“。”为止），太长截断
const shortStep = (t) => { const x = String(t).split(/[：。（]/)[0]; return x.length > 24 ? x.slice(0, 23) + '…' : x; };
const anyDone = computed(() => tour.steps.some((s) => s.done));
const route = useRoute();
let timer = null;

// 做完检测：每 1.5 秒看一次地址或页面元素；接口每 3 秒取一次。gen：换了步骤，上一步还没回来的检测作废
let poll = null;
let gen = 0;
async function apiValue(d) {
  try { return pick(await get(d.api), d.path); } catch { return undefined; }
}
async function watchDone() {
  clearInterval(poll); poll = null;
  const g = ++gen;
  const i = tour.i;
  const d = step.value.done;
  if (!tour.id || !d || tour.ok[i]) return;
  const base = d.api && (d.grew || d.changed) ? await apiValue(d) : undefined;
  if (g !== gen) return;
  let n = 0;
  let busy = false;
  const check = async () => {
    if (g !== gen || !tour.id || tour.i !== i || tour.ok[i]) { if (g === gen) { clearInterval(poll); poll = null; } return; }
    n += 1;
    if (d.api && n % 2) return;
    if (busy) return;
    busy = true;
    const value = d.api ? await apiValue(d) : undefined;
    busy = false;
    if (g === gen && met(d, { route, doc: document, value, base })) { clearInterval(poll); poll = null; markDone(i); }
  };
  poll = setInterval(check, 1500);
  if (!d.api) check();
}
watch(() => [tour.id, tour.i], () => watchDone());

function locate(tries = 0) {
  clearTimeout(timer);
  const el = step.value.help && document.querySelector(`[data-help="${step.value.help}"]`);
  if (el) {
    el.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    timer = setTimeout(() => { const r = el.getBoundingClientRect(); box.value = { x: r.left, y: r.top, w: r.width, h: r.height }; }, 250);
    missing.value = '';
  } else if (tries < 20) {
    box.value = null;
    timer = setTimeout(() => locate(tries + 1), 250);
  } else {
    box.value = null;
    missing.value = '这一步要找的地方现在不在页面上（可能要先换角色或先做上一步）。';
  }
}

watch(() => [tour.id, tour.i], () => { if (tour.id) locate(); }, { immediate: true });
const onResize = () => tour.id && locate();
window.addEventListener('resize', onResize);
onUnmounted(() => { window.removeEventListener('resize', onResize); clearTimeout(timer); clearInterval(poll); });

const PAD = 6;
const spotStyle = computed(() => box.value && ({
  left: box.value.x - PAD + 'px', top: box.value.y - PAD + 'px', width: box.value.w + PAD * 2 + 'px', height: box.value.h + PAD * 2 + 'px',
}));
const bubbleStyle = computed(() => {
  if (!box.value) return { left: '50%', top: '30%', transform: 'translateX(-50%)' };
  const below = box.value.y + box.value.h + 16;
  const top = below + 180 < window.innerHeight ? below : Math.max(12, box.value.y - 196);
  const left = Math.min(Math.max(12, box.value.x), window.innerWidth - 352);
  return { left: left + 'px', top: top + 'px' };
});
</script>

<style scoped>
.tour { position: fixed; inset: 0; z-index: 900; pointer-events: none; }
.spot { position: fixed; border-radius: 8px; box-shadow: 0 0 0 9999px rgba(23, 33, 43, 0.55); outline: 2px solid var(--brand);
  transition: all 0.25s ease; }
.bubble { position: fixed; width: 340px; background: var(--surface); border-radius: 10px; padding: 14px 16px; pointer-events: auto;
  box-shadow: 0 12px 32px rgba(23, 33, 43, 0.28); border-top: 4px solid var(--brand); }
.t { margin: 0 0 6px; color: var(--muted); }
.body { margin: 0 0 12px; line-height: 1.6; }
.acts { display: flex; gap: 8px; align-items: center; }
.link { background: none; border: 0; color: var(--muted); cursor: pointer; margin-left: auto; }
.spot.ok { outline-color: var(--good); }
.dots { display: inline-flex; gap: 3px; margin-left: 6px; vertical-align: middle; }
.dots i { width: 7px; height: 7px; border-radius: 50%; background: var(--line); }
.dots i.cur { background: var(--brand); }
.dots i.ok { background: var(--good); }
.okline { margin: -4px 0 10px; color: var(--good); font-weight: 600; }
.wait { margin: -4px 0 10px; color: var(--muted); }
.fin { border-top-color: var(--good); text-align: left; }
.big { font-size: 22px; font-weight: 700; color: var(--good); margin: 4px 0 8px; }
.ticks { margin: 0 0 12px; padding-left: 18px; color: var(--muted); }
.ticks li.ok::marker { color: var(--good); }
@media (prefers-reduced-motion: reduce) { .spot { transition: none; } }
</style>
