<template>
  <!-- 拖着玩（第 30 轮 §八 H-11 第 1 种）：课程里做好的虚拟实验，嵌在帮助里当场拖参数 -->
  <figure ref="root" class="hb lab">
    <div v-if="!on" class="cover" :style="{ height: h + 'px' }">
      <b>{{ meta?.title || args.caption || '虚拟实验' }}</b>
      <span class="small muted">{{ meta?.what || '拖参数，曲线当场变' }}</span>
      <button class="btn primary" @click="start">打开实验</button>
    </div>
    <iframe v-else ref="frame" :src="src" :title="meta?.title || '虚拟实验'" :style="{ height: h + 'px' }" loading="lazy" @load="onLoad"></iframe>
    <figcaption class="small muted">
      <span>{{ args.caption || meta?.caption || '' }}</span>
      <a :href="src" target="_blank" rel="noopener">整页打开 ↗</a>
    </figcaption>
  </figure>
</template>

<script setup>
// 实验页是课程《数字工厂实训》网页版里的（textbook/web-editions/dfactory/src/zh/labs/），副本在 web/public/labs/，
// 由 factory/digital/tools/sync_help_labs.py 同步，tests/test_help.py 核对一字不差。同源嵌入，所以能替它点“预置”按钮、定成浅色。
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { LABS } from '../../help/labs';

const props = defineProps({ args: { type: Object, default: () => ({}) } });
const root = ref(null);
const frame = ref(null);
const on = ref(false);
const meta = computed(() => LABS[props.args.id]);
const src = computed(() => `/labs/${props.args.id}.html`);
const h = computed(() => Math.min(1200, Math.max(320, parseInt(props.args.height, 10) || 640)));
let io = null;

function start() { on.value = true; io?.disconnect(); }
// 页面滚到附近才装入（实验页带动画，不一进帮助就全跑起来）
onMounted(() => {
  if (!('IntersectionObserver' in window) || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) start(); }, { rootMargin: '200px 0px' });
  io.observe(root.value);
});
onUnmounted(() => io?.disconnect());

function onLoad() {
  try {
    const d = frame.value.contentDocument;
    d.documentElement.setAttribute('data-theme', 'light');          // 工作台没有深色，帮助里的实验跟着浅色
    // 预置：实验页里有这个预置按钮才点（没有就不管）
    const p = props.args.preset && d.querySelector(`[data-p="${CSS.escape(props.args.preset)}"]`);
    if (p) p.click();
  } catch { /* 不同源（不该发生）：照原样显示 */ }
}
</script>

<style scoped>
.lab { margin: 18px 0; }
iframe, .cover { width: 100%; border: 1px solid var(--line); border-radius: 10px; display: block; background: #eef2f3; }
.cover { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; text-align: center; padding: 16px;
  background: repeating-linear-gradient(135deg, var(--surface) 0 14px, var(--surface-2) 14px 28px); max-height: 360px; }
.cover b { font-size: 17px; }
figcaption { display: flex; justify-content: space-between; gap: 12px; margin-top: 6px; }
@media (max-width: 860px) { iframe { max-height: 80vh; } }
</style>
