<!-- 实验 26“一台协作机器人的运动学标定”（第 55 轮，机器人厂）：正运动学、位姿选法与条件数、辨识、验证、位姿少了会怎样、复盘 -->
<template>
  <div class="page">
    <div class="page-title"><h1>实验 26 · 一台协作机器人的运动学标定</h1>
      <span class="muted">平台自动评 {{ s?.of || 60 }} 分，报告 {{ s?.report_points || 40 }} 分由老师在课程里批改</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab26/guide.docx">指导书</a> · <a href="/api/cae/lab26/report-template.docx">报告模板</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ s.score }} / {{ s.of }}</b>
        <span class="small">你的机器人
          <select v-model="serial" aria-label="机器人" @change="pick"><option v-for="r in s.robots" :key="r" :value="r">{{ r }}</option></select></span>
        <span v-if="!s.robots.length" class="small muted">还没有标定过的 WQ-CR5：先接一台（实验 24），做到整机标定</span>
        <router-link class="small" :to="'/calib' + (s.serial ? '?serial=' + s.serial : '')">整机标定页</router-link>
        <button class="btn sm" @click="load">刷新</button>
      </div>

      <section v-if="s.teacher && s.class?.length" class="card">
        <div class="card-head"><h2>老师：全班成绩</h2></div>
        <table class="tbl small"><thead><tr><th>学生</th><th v-for="(t, i) in s.tasks" :key="t.id" class="num">任务 {{ i + 1 }}</th><th class="num">合计</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ c.user }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ c.total }}</b></td></tr></tbody></table>
      </section>

      <section class="card small">
        <div class="card-head"><h2>名义 DH 参数（示例值）</h2><span class="muted">T = Rz(θ)·Tz(d)·Tx(a)·Rx(α)；工具点在法兰坐标系 ({{ s.nominal.tool_mm.join(', ') }}) mm</span></div>
        <table class="tbl"><thead><tr><th>关节</th><th class="num">a（mm）</th><th class="num">α（°）</th><th class="num">d（mm）</th></tr></thead>
          <tbody><tr v-for="r in s.nominal.dh" :key="r.joint"><td>{{ r.joint }}</td><td class="num">{{ r.a_mm }}</td><td class="num">{{ r.alpha_deg }}</td><td class="num">{{ r.d_mm }}</td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>任务 {{ i + 1 }}　{{ t.title }}</h2><span class="pts">{{ t.score }} / {{ t.points }}</span></div>
        <p>{{ t.desc }}</p>
        <p class="small muted">提示：{{ t.hint }}</p>
        <form v-if="t.id === 'l26_t1'" class="f" @submit.prevent="submit(t.id, a1)">
          <p v-if="s.fk_q_deg" class="small">关节角 q（°）：<b class="mono">{{ s.fk_q_deg.join('，') }}</b></p>
          <div class="lf"><label>x、y、z（mm）</label><span class="xyz">
            <input v-model.number="a1.x" type="number" step="0.01" required aria-label="x"><input v-model.number="a1.y" type="number" step="0.01" required aria-label="y">
            <input v-model.number="a1.z" type="number" step="0.01" required aria-label="z"></span></div>
          <button class="btn primary" :disabled="!s.serial">提交</button>
        </form>
        <form v-if="t.id === 'l26_t2'" class="f" @submit.prevent="submit(t.id, a2)">
          <div class="lf"><label>条件数大的是</label><span class="cks">
            <label><input v-model="a2.larger" type="radio" value="full" required> 铺满工作空间</label>
            <label><input v-model="a2.larger" type="radio" value="cluster"> 集中在常用姿态附近</label></span></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 'l26_t3'" class="f" @submit.prevent="submit(t.id, a3)">
          <div class="lf"><label>零位偏得最多的两个</label><span class="cks">
            <label v-for="j in s.joints" :key="j"><input v-model="a3.joints" type="checkbox" :value="j"> {{ j }}</label></span></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 'l26_t4'" class="f" @submit.prevent="submit(t.id, a4)">
          <div class="lf"><label>标定后平均误差（mm）</label><input v-model.number="a4.after_mm" type="number" step="0.001" required></div>
          <div class="lf"><label>判定</label><span class="cks">
            <label><input v-model="a4.pass" type="radio" :value="true" required> 合格</label><label><input v-model="a4.pass" type="radio" :value="false"> 不合格</label></span></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 'l26_t5' || t.id === 'l26_t6'" class="f" @submit.prevent="submit(t.id, t.id === 'l26_t5' ? a5 : a6)">
          <div class="lf"><label>选一项</label><span class="cks col">
            <label v-for="o in (t.id === 'l26_t5' ? s.t5_choices : s.t6_choices)" :key="o.value">
              <input v-if="t.id === 'l26_t5'" v-model="a5.choice" type="radio" :value="o.value" required>
              <input v-else v-model="a6.choice" type="radio" :value="o.value" required> {{ o.label }}</label></span></div>
          <button class="btn primary">提交</button>
        </form>
        <p v-if="fb[t.id]" class="small fb">{{ fb[t.id] }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { get, post } from '../lib/api';

const s = ref(null);
const err = ref('');
const fb = reactive({});
const serial = ref('');
const a1 = reactive({ x: null, y: null, z: null });
const a2 = reactive({ larger: '' });
const a3 = reactive({ joints: [] });
const a4 = reactive({ after_mm: null, pass: null });
const a5 = reactive({ choice: '' });
const a6 = reactive({ choice: '' });

async function load() {
  try { s.value = await get('/lab26'); serial.value = s.value.serial || ''; err.value = ''; } catch (e) { err.value = e.message; }
}
async function pick() {
  try { await post('/lab26/pick', { serial: serial.value }); await load(); } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab26/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { err.value = e.message; }
}
onMounted(load);
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.r { margin-left: auto; }
.sum { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
.big { font-size: 24px; }
.task.done { border-left: 4px solid var(--good); }
.pts { margin-left: auto; font-weight: 600; }
.f { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.lf { display: flex; flex-direction: row; gap: 10px; align-items: flex-start; flex-wrap: wrap; }
.lf > label:first-child { width: 170px; font-weight: 500; padding-top: 4px; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 auto; min-width: 240px; font-size: 13px; }
.cks.col { flex-direction: column; }
.xyz { display: flex; gap: 6px; flex-wrap: wrap; }
.f .btn { align-self: flex-start; }
select, input[type=number] { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
input[type=number] { width: 110px; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; }
.num { text-align: right; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
</style>
