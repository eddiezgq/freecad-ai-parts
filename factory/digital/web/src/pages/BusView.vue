<template>
  <div class="page">
    <div class="page-title"><h1>统一数据总线</h1><span class="muted">所有软件、设备和 AI 只和总线打交道；这里是总线上正在流过的消息（本页只显示当前模式）</span></div>
    <div class="row">
      <section class="card grow">
        <div class="card-head"><h2>实时消息</h2><span class="muted small">{{ bus.connected ? '已连接' : '未连接' }} · 最近一分钟 {{ bus.rate }} 条</span>
          <label class="more small"><input v-model="paused" type="checkbox"> 暂停</label></div>
        <table class="t">
          <thead><tr><th>时间</th><th>主题</th><th>类型</th><th>关联号</th><th>内容</th></tr></thead>
          <tbody><tr v-for="(m, i) in shown" :key="i">
            <td class="mono small">{{ new Date(m.ts).toLocaleTimeString('zh-CN', { hour12: false }) }}</td>
            <td class="mono small">{{ m.topic }}</td><td class="mono small">{{ m.type }}</td><td class="mono small">{{ m.corr || '' }}</td>
            <td class="small data">{{ brief(m.data) }}</td>
          </tr></tbody>
        </table>
      </section>
      <section class="card side">
        <div class="card-head"><h2>主题怎么读</h2></div>
        <p class="small mono">wq / 工厂 / 区域 / 单元 / 类别</p>
        <ul class="small">
          <li><span class="mono">machining/grd-01/status</span>：磨床当前状态（保留消息，新打开的页面立即拿到）</li>
          <li><span class="mono">machining/grd-01/event</span>：开工、完工、报警、换刀</li>
          <li><span class="mono">machining/grd-01/cmd</span>：发给设备的指令；设备在 <span class="mono">cmd/ack</span> 应答</li>
          <li><span class="mono">quality/qc-01/measurement</span>：三坐标测量值</li>
          <li><span class="mono">office/erp/work_order</span>：ERPNext 的单据（由 Node-RED 桥接发出）</li>
          <li><span class="mono">design/sh-301/release</span>：FreeCAD 发布的新版本</li>
          <li><span class="mono">ai/alert · ai/briefing · ai/proposal</span>：AI 的提醒、简报和待确认的提议</li>
        </ul>
        <p class="small muted">每条消息都有统一信封：v（规范版本）、id、ts（UTC）、type、source、mode（教学 / 生产）、corr（关联号，通常是工单号）、data。
          全部消息同时存入历史库，看板、报表和 AI 都从历史库取数。规范见《实施细则 第 1 轮》附录 A。</p>
      </section>
    </div>
  </div>
</template>

<script setup>
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
