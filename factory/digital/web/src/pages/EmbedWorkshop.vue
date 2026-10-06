<template>
  <div class="embed">
    <div ref="host" class="host"></div>
    <div class="cap small">
      <b>问渠数字工厂</b>
      <span v-if="mode === 'replay'"> · 回放 {{ clockText }}<template v-if="speed !== 1">（×{{ speed }}）</template></span>
      <span v-else> · 实时<template v-if="!bus.connected">（连接中…）</template></span>
      <span v-if="focusName"> · {{ focusName }}</span>
    </div>
    <div class="legend small">
      <span v-for="s in ['run', 'idle', 'setup', 'down']" :key="s"><i :style="{ background: HEX[s] }"></i>{{ STATE[s].label }}</span>
    </div>
    <div v-if="err" class="err small">{{ err }}</div>
  </div>
</template>

<script setup>
// 可嵌入的只读 3D 车间（第 4 轮 C8）：/embed/workshop?view=overview|device&device=grd-01&mode=live|replay&t0=&speed=&token=
// 实时画面不用登录（总线本来就匿名只读，C5 之后不含姓名）；回放要学习平台申请的嵌入凭证。页面上没有操作按钮。
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { createWorkshop, HEX } from '../lib/workshop3d';
import { bus, connectBus } from '../lib/bus';
import { STATE } from '../lib/fmt';

const route = useRoute();
const host = ref(null);
const err = ref('');
const q = route.query;
const mode = q.mode === 'replay' ? 'replay' : 'live';
const speed = Math.max(0.1, Math.min(600, Number(q.speed) || 1));
const CHUNK_MIN = 10;
let ws, off, timer;
const layout = ref(null);

const rp = reactive({ machines: {}, agvs: {}, rows: [], i: 0, start: 0, wall: 0, loadedTo: 0, loading: false, clock: 0 });
const clockText = computed(() => (rp.clock ? new Date(rp.clock).toLocaleString('zh-CN', { hour12: false }) : '—'));
const focusName = computed(() => (q.view === 'device' && layout.value?.units[q.device] ? `${q.device.toUpperCase()} ${layout.value.units[q.device].name}` : ''));

async function loadChunk() {
  if (rp.loading) return;
  rp.loading = true;
  try {
    const from = new Date(rp.loadedTo).toISOString();
    const r = await fetch(`/api/embed/replay?token=${encodeURIComponent(q.token || '')}&t0=${encodeURIComponent(from)}&minutes=${CHUNK_MIN}`);
    if (r.status === 401) { err.value = '回放凭证无效或已过期（30 分钟内有效），请刷新课件页面。'; return; }
    if (!r.ok) throw new Error(String(r.status));
    const j = await r.json();
    rp.rows = rp.rows.slice(rp.i).concat(j.rows.map((x) => ({ ...x, t: Date.parse(x.ts) })));
    rp.i = 0;
    rp.loadedTo = Date.parse(j.to);
  } catch (e) {
    err.value = '回放数据读取失败：' + e.message;
  } finally {
    rp.loading = false;
  }
}

function tick() {
  rp.clock = rp.start + (performance.now() - rp.wall) * speed;
  let changed = false;
  while (rp.i < rp.rows.length && rp.rows[rp.i].t <= rp.clock) {
    const x = rp.rows[rp.i++];
    if (x.kind === 'machine') rp.machines[x.unit] = x; else rp.agvs[x.unit] = x;
    changed = true;
  }
  if (changed) ws.update(rp.machines, rp.agvs);
  if (!err.value && rp.loadedTo - rp.clock < 2 * 60000) loadChunk();
}

onMounted(async () => {
  try {
    layout.value = await (await fetch('/api/layout')).json();
    ws = createWorkshop(host.value, layout.value);
    if (q.view === 'device' && q.device && !ws.focus(q.device)) err.value = '没有这台设备：' + q.device;
    if (mode === 'replay') {
      const t0 = Date.parse(q.t0 || '');
      if (!q.token) { err.value = '回放需要嵌入凭证（token）。'; return; }
      if (Number.isNaN(t0)) { err.value = '回放需要开始时间 t0（ISO 时间）。'; return; }
      rp.start = t0; rp.loadedTo = t0; rp.wall = performance.now(); rp.clock = t0;
      await loadChunk();
      timer = setInterval(tick, 100);
    } else {
      const cfg = await (await fetch('/api/embed/config')).json();
      connectBus(cfg.mqtt_ws.replace('localhost', location.hostname), 'teach');
      const apply = () => ws.update(bus.machines, bus.agvs);
      off = watch(() => [bus.machines, bus.agvs], apply, { deep: true });
      apply();
    }
  } catch (e) {
    err.value = '3D 车间载入失败：' + e.message;
  }
});
onUnmounted(() => { clearInterval(timer); if (off) off(); if (ws) ws.dispose(); });
</script>

<style scoped>
.embed { position: fixed; inset: 0; background: #EEF0EC; }
.host { position: absolute; inset: 0; }
.cap { position: absolute; left: 12px; top: 10px; background: rgba(255, 255, 255, .92); border-radius: 8px; padding: 6px 10px; }
.legend { position: absolute; left: 12px; bottom: 10px; background: rgba(255, 255, 255, .92); border-radius: 8px; padding: 6px 10px;
  display: flex; gap: 10px; flex-wrap: wrap; }
.legend i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; margin-right: 5px; }
.err { position: absolute; right: 12px; top: 10px; background: #FCE8E6; color: #B42318; border-radius: 8px; padding: 6px 10px; max-width: 60%; }
</style>
