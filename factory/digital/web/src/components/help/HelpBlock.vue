<template>
  <!-- 带我去做 -->
  <div v-if="kind === 'goto'" class="hb goto">
    <div class="g-txt">
      <b>{{ args.label || def?.title || '带我去做' }}</b>
      <span class="small muted">{{ def ? `打开“${pageName}”，分 ${def.steps.length} 步指给你看` : '' }}</span>
    </div>
    <button v-if="loggedIn" class="btn primary" :disabled="!def" @click="go">带我去做</button>
    <router-link v-else class="btn" :to="{ path: '/login', query: { next: $route.fullPath } }">登录后可以跟着做</router-link>
  </div>

  <!-- 动画 -->
  <div v-else-if="kind === 'anim'" class="hb anim">
    <component :is="ANIMS[args.name]" v-if="ANIMS[args.name]" :args="args" :caption="args.caption" />
  </div>

  <!-- 视频 -->
  <figure v-else-if="kind === 'video'" class="hb video">
    <video v-if="hasVideo" :src="`/help-media/${args.name}.webm`" controls preload="metadata" playsinline></video>
    <div v-else class="novid">
      <p><b>{{ args.caption || '操作视频' }}</b></p>
      <p class="small">这段视频还没装到这台服务器上。可以用本章的“带我去做”在系统里实际走一遍。</p>
    </div>
    <figcaption v-if="hasVideo && args.caption" class="small muted">{{ args.caption }}（无配音，看字幕）</figcaption>
  </figure>

  <!-- 本厂此刻的数据 -->
  <div v-else-if="kind === 'live'" class="hb live">
    <p class="lv-h small"><span class="dot"></span>{{ cfg?.plant?.name || '本厂' }} · 此刻</p>
    <template v-if="args.kind === 'plant'">
      <dl class="facts">
        <div><dt>工厂</dt><dd>{{ cfg?.plant?.name }}</dd></div>
        <div><dt>公司</dt><dd>{{ cfg?.plant?.company }}</dd></div>
        <div><dt>币种</dt><dd>{{ cfg?.plant?.currency }}</dd></div>
        <div><dt>班次</dt><dd>{{ cfg?.plant?.shift }}</dd></div>
        <div v-if="layout"><dt>车间</dt><dd>{{ layout.floor[0] }} × {{ layout.floor[1] }} 米，{{ Object.keys(layout.units).length }} 台设备</dd></div>
      </dl>
    </template>
    <p v-else-if="!loggedIn" class="small muted">登录后这里显示本厂此刻的{{ args.kind === 'kpi' ? '指标' : '设备状态' }}。</p>
    <template v-else-if="args.kind === 'machines'">
      <div v-if="machineList.length" class="mgrid">
        <div v-for="m in machineList" :key="m.unit" class="m" :title="m.reason || ''">
          <i :style="{ background: HEX[m.state] || HEX.idle }"></i>
          <span class="mono">{{ m.unit }}</span>
          <span class="small muted">{{ STATE[m.state]?.label || '空闲' }}</span>
        </div>
      </div>
      <p v-else class="small muted">还没收到设备状态（总线{{ bus.connected ? '已连接，设备还没发消息' : '连接中' }}）。</p>
    </template>
    <template v-else-if="args.kind === 'kpi'">
      <div v-if="kpis.length" class="kgrid">
        <div v-for="k in kpis" :key="k.key" class="k" :class="k.tone">
          <span class="small muted">{{ k.label }}</span>
          <b>{{ fmtKpi(k) }}</b>
          <span class="small muted">{{ k.note }}</span>
        </div>
      </div>
      <p v-else class="small muted">指标还在计算。</p>
    </template>
  </div>

  <!-- 问 AI -->
  <div v-else-if="kind === 'ask'" class="hb ask">
    <span class="small muted">还不清楚？</span>
    <button class="btn" :disabled="!loggedIn" :title="loggedIn ? '' : '登录后可以问 AI 工厂助手'" @click="ask(args.q)">问 AI：{{ args.q }}</button>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ANIMS } from './anim';
import { get, loadConfig, session } from '../../lib/api';
import { bus } from '../../lib/bus';
import { ask } from '../../lib/ai';
import { HEX } from '../../lib/workshop3d';
import { STATE } from '../../lib/fmt';
import { startTour, tourDef } from '../../lib/tour';
import { pageTitle } from '../../help/pages';

const props = defineProps({ kind: String, args: { type: Object, default: () => ({}) }, media: { type: Array, default: () => [] } });
const router = useRouter();
const loggedIn = computed(() => !!session.token);
const def = computed(() => (props.kind === 'goto' ? tourDef(props.args.tour) : null));
const pageName = computed(() => (def.value ? pageTitle(def.value.path) : ''));
const hasVideo = computed(() => props.media.includes(props.args.name + '.webm'));
const cfg = ref(null);
const layout = ref(null);
const kpis = ref([]);
const machineList = computed(() => Object.entries(bus.machines).map(([unit, m]) => ({ unit, ...m })).sort((a, b) => a.unit.localeCompare(b.unit)));

function go() { startTour(router, props.args.tour); }
function fmtKpi(k) {
  if (k.value == null) return '—';
  if (k.fmt === 'pct0') return Math.round(k.value * 100) + '%';
  if (k.fmt === 'pct1') return (k.value * 100).toFixed(1) + '%';
  return k.value + (k.unit ? ' ' + k.unit : '');
}
onMounted(async () => {
  if (props.kind !== 'live') return;
  try { cfg.value = await loadConfig(); } catch { /* 没连上就不显示 */ }
  if (props.args.kind === 'plant') { try { layout.value = await get('/layout'); } catch { /* 同上 */ } }
  if (props.args.kind === 'kpi' && loggedIn.value) { try { kpis.value = (await get('/overview')).kpis || []; } catch { /* 同上 */ } }
});
</script>

<style scoped>
.hb { margin: 18px 0; }
.goto { display: flex; align-items: center; gap: 16px; padding: 14px 16px; border-radius: 10px; background: var(--task-bg);
  border-left: 4px solid var(--brand); }
.g-txt { display: flex; flex-direction: column; gap: 2px; flex: 1; }
.video video { width: 100%; border-radius: 10px; background: #17212B; display: block; }
.novid { border-radius: 10px; background: var(--surface-2); color: var(--ink); padding: 12px 16px 12px 52px; position: relative; border: 1px dashed var(--line); }
.novid::before { content: ''; position: absolute; left: 18px; top: 50%; transform: translateY(-50%); border-left: 16px solid var(--idle);
  border-top: 10px solid transparent; border-bottom: 10px solid transparent; }
.novid .small { color: var(--muted); }
.novid p { margin: 4px 0; }
figcaption { margin-top: 6px; }
.live { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; background: var(--surface); }
.lv-h { margin: 0 0 10px; color: var(--muted); display: flex; align-items: center; gap: 8px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--good); animation: pulse 2s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) { .dot { animation: none; } }
.mgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 6px; }
.m { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border-radius: 6px; background: var(--surface-2); }
.m i { width: 10px; height: 10px; border-radius: 50%; flex: none; }
.kgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px; }
.k { display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; border-radius: 8px; background: var(--surface-2); }
.k b { font-size: 22px; }
.k.good b { color: var(--good); } .k.bad b { color: var(--bad); } .k.warn b { color: var(--warn-ink); }
.facts { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; margin: 0; }
.facts div { display: flex; flex-direction: column; } .facts dt { color: var(--muted); font-size: 12px; } .facts dd { margin: 0; font-weight: 600; }
.ask { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
</style>
