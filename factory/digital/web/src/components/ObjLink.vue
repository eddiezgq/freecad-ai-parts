<!-- 对象卡片链接（第 17 轮 A 期 A10③）：单号、序列号、设备号点进对象 360 页；鼠标停留显示摘要 -->
<template>
  <span class="ol" @mouseenter="enter" @mouseleave="leave" @focusin="enter" @focusout="leave">
    <router-link :to="objPath(type, k)" class="ol-a" :class="{ mono }"><slot>{{ k }}</slot></router-link>
    <span v-if="show" class="ol-card" role="tooltip">
      <template v-if="!s"><span class="muted small">读取中…</span></template>
      <template v-else-if="s.error"><span class="muted small">{{ s.error }}</span></template>
      <template v-else>
        <span class="ol-h"><span class="pill info">{{ s.label }}</span> <b>{{ s.display }}</b>
          <span v-if="tone" class="pill" :class="tone">{{ state }}</span></span>
        <span v-for="a in top" :key="a.name" class="ol-r small"><span class="muted">{{ a.label }}</span> <span class="mono">{{ fmtVal(a.value, a.unit) }}</span></span>
        <span v-if="links" class="ol-r small muted">{{ links }}</span>
        <span class="ol-r small muted">最近更新 {{ fmtTs(s.updated_at) }} · 点击查看全部</span>
      </template>
    </span>
  </span>
</template>

<script setup>
import { computed, ref } from 'vue';
import { objPath, summary, fmtVal, fmtTs, stateTone } from '../lib/ont';

const props = defineProps({ type: { type: String, required: true }, k: { type: [String, Number], required: true }, mono: { type: Boolean, default: false } });
const show = ref(false);
const s = ref(null);
let t;

async function enter() {
  clearTimeout(t);
  t = setTimeout(async () => {
    show.value = true;
    s.value = await summary(props.type, String(props.k));
  }, 300);
}
function leave() { clearTimeout(t); t = setTimeout(() => { show.value = false; }, 150); }

const pmap = computed(() => Object.fromEntries((s.value?.attrs || []).map((a) => [a.name, a.value])));
const tone = computed(() => stateTone(pmap.value));
const state = computed(() => pmap.value.status ?? pmap.value.state ?? pmap.value.result ?? pmap.value.health);
const top = computed(() => (s.value?.attrs || []).filter((a) => a.value !== null && a.value !== undefined && typeof a.value !== 'object'
  && !['status', 'state', 'result', 'health', 'name', 'title'].includes(a.name)).slice(0, 5));
const links = computed(() => (s.value?.links || []).slice(0, 4).map((g) => `${g.label} ${g.items.length}${g.more ? '+' : ''} 个${g.type_label}`).join(' · '));
</script>

<style scoped>
.ol { position: relative; display: inline-block; }
.ol-a { border-bottom: 1px dotted var(--accent); }
.ol-a:hover { text-decoration: none; }
.ol-card { position: absolute; z-index: 50; left: 0; top: 100%; margin-top: 4px; width: 280px; background: var(--surface); border: 1px solid var(--line);
  border-radius: 8px; box-shadow: 0 6px 20px rgba(23, 33, 43, .15); padding: 10px 12px; display: flex; flex-direction: column; gap: 4px;
  font-weight: 400; color: var(--ink); white-space: normal; text-align: left; }
.ol-h { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.ol-r { display: flex; justify-content: space-between; gap: 8px; }
.ol-r .mono { text-align: right; word-break: break-all; }
</style>
