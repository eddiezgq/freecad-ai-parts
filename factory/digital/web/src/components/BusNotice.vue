<template>
  <!-- 第 6 轮 W7②③：车间数据连不上或没有设备时，说清原因、给出下一步，不让页面看起来“没反应” -->
  <div v-if="kind" class="notice" :class="kind === 'connecting' ? 'info' : 'warn'" role="status">
    <template v-if="kind === 'connecting'">正在连接统一数据总线…</template>
    <template v-else-if="kind === 'failed'">
      <span><b>连不上统一数据总线</b>（{{ bus.error || '超时' }}），设备状态不会更新，按钮发出的指令也收不到应答。</span>
      <button class="btn" @click="reconnectBus">重试</button>
    </template>
    <template v-else-if="kind === 'prod-empty'">
      <span><b>生产模式只显示接入的真实设备，目前没有设备接入。</b>要练习操作，请切换到教学模式（仿真车间）。</span>
      <button class="btn primary" @click="toTeach">切换到教学模式</button>
    </template>
    <template v-else-if="kind === 'teach-empty'">
      <span><b>仿真车间没有发来数据。</b>请稍等半分钟；仍然没有，请告诉管理员检查仿真程序。</span>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { session, switchTo } from '../lib/api';
import { bus, reconnectBus, setBusMode } from '../lib/bus';

const waited = ref(false);
let t;
onMounted(() => { t = setTimeout(() => { waited.value = true; }, 10000); });
onUnmounted(() => clearTimeout(t));

const kind = computed(() => {
  if (!bus.connected) return waited.value || bus.error ? 'failed' : 'connecting';
  if (Object.keys(bus.machines).length) return null;
  if (!waited.value) return null;
  return session.user?.mode === 'prod' ? 'prod-empty' : 'teach-empty';
});

async function toTeach() {
  await switchTo({ mode: 'teach' });
  setBusMode('teach');
}
</script>

<style scoped>
.notice { display: flex; gap: 12px; align-items: center; justify-content: space-between; flex-wrap: wrap;
  border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 14px; }
.notice.info { background: var(--accent-bg); }
.notice.warn { background: var(--warn-bg); color: var(--warn-ink); }
</style>
