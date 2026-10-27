<!-- 教师控制台（第 19 轮 J-5 从“经营与成本”页搬到“情景导演”）：仿真倍速、制造故障、车间班次、重置实验 7 情景 -->
<template>
    <section class="card teacher">
      <div class="card-head"><h2>教师控制台</h2><span class="muted small">只给老师；指令经总线发给仿真车间（machining/sim/cmd）</span></div>
      <div class="ctl">
        <div class="field"><label>仿真倍速</label>
          <div class="inline"><select v-model.number="speed"><option v-for="s in [1, 5, 20, 60, 120, 300]" :key="s" :value="s">{{ s }}×</option></select>
            <button class="btn" @click="setSpeed">应用</button></div></div>
        <div class="field"><label>注入一次故障</label>
          <div class="inline">
            <select v-model="fault.unit"><option v-for="m in units" :key="m" :value="m">{{ m.toUpperCase() }}</option></select>
            <input v-model.number="fault.minutes" type="number" min="5" max="480" style="width: 80px" aria-label="分钟">
            <input v-model="fault.reason" style="width: 120px" aria-label="原因">
            <button class="btn danger" @click="injectFault">注入</button></div></div>
        <div class="field"><label>车间班次（第 17 轮 C 期）</label>
          <div class="inline">
            <select v-model="shiftMode" aria-label="班次模式"><option value="continuous">24 小时连续</option><option value="shift">按班次（周一至周五 08:00–17:00）</option></select>
            <button class="btn" @click="setShift">应用</button></div>
          <span class="small muted">按班次时可以在厂情中枢推演和批准“加班”</span></div>
        <div class="field"><label>重置实验 7 情景</label>
          <div class="inline">
            <label class="small"><input v-model="resetScores" type="checkbox"> 同时清空学生得分</label>
            <button class="btn danger" @click="reset">重置</button></div></div>
      </div>
      <div v-if="ctlMsg" class="ok small">{{ ctlMsg }}</div>
    </section>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import { get, post } from '../lib/api';

const speed = ref(20);
const fault = ref({ unit: 'grd-01', minutes: 30, reason: '主轴过热' });
const units = ['saw-01', 'cnc-l01-a', 'cnc-l01-b', 'key-01', 'ht-01', 'grd-01', 'qc-01'];
const resetScores = ref(false);
const ctlMsg = ref('');
const shiftMode = ref('continuous');

async function setSpeed() {
  await post('/mes/cmd', { unit: 'sim', command: 'set_speed', speed: speed.value });
  ctlMsg.value = `已把仿真倍速改为 ${speed.value}×`;
}
async function loadShift() { try { shiftMode.value = (await get('/ont/shifts')).calendar.mode; } catch (e) { /* 老版本没有 */ } }
async function setShift() {
  try { const r = await post('/ont/shifts', { mode: shiftMode.value }); ctlMsg.value = '车间班次：' + (r.calendar.mode === 'shift' ? '按班次' : '24 小时连续') + '，已发给仿真车间'; } catch (e) { ctlMsg.value = e.message; }
}
async function injectFault() {
  await post('/mes/cmd', { unit: fault.value.unit, command: 'inject_fault', minutes: fault.value.minutes, reason: fault.value.reason });
  ctlMsg.value = `已让 ${fault.value.unit.toUpperCase()} 停机 ${fault.value.minutes} 分钟（${fault.value.reason}）`;
}
async function reset() {
  if (!confirm('清空教学模式的全部历史，重新载入实验 7 情景？')) return;
  await post('/scenario/reset', { speed: 1, scores: resetScores.value });
  ctlMsg.value = '已重置，情景约 5 秒后载入完成';
}
onMounted(loadShift);
</script>

<style scoped>
.teacher { border-color: var(--task-line); background: #FFFCF0; }
.ctl { display: flex; gap: 24px; flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 4px; }
.inline { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.inline select, .inline input { height: 34px; border: 1px solid #C8CEC7; border-radius: 6px; padding: 0 8px; }
</style>
