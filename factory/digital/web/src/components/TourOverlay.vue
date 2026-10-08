<template>
  <div v-if="tour.id" class="tour" role="dialog" aria-live="polite" :aria-label="'带我去做：' + tour.title">
    <div v-if="box" class="spot" :style="spotStyle"></div>
    <div class="bubble" :style="bubbleStyle">
      <p class="t small">{{ tour.title }} · 第 {{ tour.i + 1 }} / {{ tour.steps.length }} 步</p>
      <p class="body">{{ step.text }}</p>
      <p v-if="!box" class="small muted">{{ missing }}</p>
      <div class="acts">
        <button class="btn" :disabled="tour.i === 0" @click="prevStep">上一步</button>
        <button class="btn primary" @click="nextStep">{{ tour.i < tour.steps.length - 1 ? '下一步' : '完成' }}</button>
        <button class="link small" @click="stopTour">退出引导</button>
      </div>
    </div>
  </div>
</template>

<script setup>
// 引导层：给当前步骤的页面元素（data-help 标记）开一个“聚光灯”，旁边放说明。元素晚加载时会等一会儿再找。
import { computed, onUnmounted, ref, watch } from 'vue';
import { tour, nextStep, prevStep, stopTour } from '../lib/tour';

const box = ref(null);
const missing = ref('');
const step = computed(() => tour.steps[tour.i] || {});
let timer = null;

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
onUnmounted(() => { window.removeEventListener('resize', onResize); clearTimeout(timer); });

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
@media (prefers-reduced-motion: reduce) { .spot { transition: none; } }
</style>
