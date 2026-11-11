<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('统一数据总线') }}</h1><span class="muted">{{ $t('所有软件、设备和 AI 只和总线打交道；这里是总线上正在流过的消息（本页只显示当前模式）') }}</span></div>
    <div class="row">
      <section class="card grow">
        <div class="card-head"><h2>{{ $t('实时消息') }}</h2><span class="muted small">{{ $t('{a} · 最近一分钟 {b} 条', { a: bus.connected ? $t('已连接') : $t('未连接'), b: $td(bus.rate) }) }}</span>
          <label class="more small"><input v-model="paused" type="checkbox"> {{ $t('暂停') }}</label></div>
        <table class="t">
          <thead><tr><th>{{ $t('时间') }}</th><th>{{ $t('主题') }}</th><th>{{ $t('类型') }}</th><th>{{ $t('关联号') }}</th><th>{{ $t('内容') }}</th></tr></thead>
          <tbody><tr v-for="(m, i) in shown" :key="i">
            <td class="mono small">{{ new Date(m.ts).toLocaleTimeString('zh-CN', { hour12: false }) }}</td>
            <td class="mono small">{{ $td(m.topic) }}</td><td class="mono small">{{ $td(m.type) }}</td><td class="mono small">{{ m.corr || '' }}</td>
            <td class="small data">{{ brief(m.data) }}</td>
          </tr></tbody>
        </table>
      </section>
      <section class="card side">
        <div class="card-head"><h2>{{ $t('主题怎么读') }}</h2></div>
        <p class="small mono">{{ $t('wq / 工厂 / 区域 / 单元 / 类别') }}</p>
        <ul class="small">
          <li><span class="mono">machining/grd-01/status</span>{{ $t('：磨床当前状态（保留消息，新打开的页面立即拿到）') }}</li>
          <li><span class="mono">machining/grd-01/event</span>{{ $t('：开工、完工、报警、换刀') }}</li>
          <li><span class="mono">machining/grd-01/cmd</span>{{ $t('：发给设备的指令；设备在') }} <span class="mono">cmd/ack</span> {{ $t('应答') }}</li>
          <li><span class="mono">quality/qc-01/measurement</span>{{ $t('：三坐标测量值') }}</li>
          <li><span class="mono">office/erp/work_order</span>{{ $t('：ERPNext 的单据（由 Node-RED 桥接发出）') }}</li>
          <li><span class="mono">design/sh-301/release</span>{{ $t('：FreeCAD 发布的新版本') }}</li>
          <li><span class="mono">ai/alert · ai/briefing · ai/proposal</span>{{ $t('：AI 的提醒、简报和待确认的提议') }}</li>
        </ul>
        <p class="small muted">{{ $t('每条消息都有统一信封：v（规范版本）、id、ts（UTC）、type、source、mode（教学 / 生产）、corr（关联号，通常是工单号）、data。全部消息同时存入历史库，看板、报表和 AI 都从历史库取数。规范见《实施细则 第 1 轮》附录 A。') }}</p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { ref, watch } from 'vue';
import { bus } from '../lib/bus';

const paused = ref(false);
const shown = ref([...bus.last]);
watch(() => bus.last[0], () => { if (!paused.value) shown.value = [...bus.last]; });
function brief(d) {
  const s = JSON.stringify(d);
  return s.length > 160 ? s.slice(0, 160) + '…' : s;
}
</script>

<style scoped>
.grow { flex-grow: 1; min-width: 0; }
.side { width: 380px; flex-shrink: 0; }
.data { word-break: break-all; color: var(--muted); }
ul { padding-left: 18px; line-height: 1.8; }
@media (max-width: 1100px) { .side { width: auto; } }
</style>
