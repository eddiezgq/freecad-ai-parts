<!-- 实验 29“一台机器人的售后追溯”（第 68 轮，机器人厂）：现场报警 → 出厂档案 → 减速器批次 → 判原因 → 召回范围 → 派工 → 算账 -->
<template>
  <div class="page">
    <div class="page-title"><h1>实验 29 · 一台机器人的售后追溯</h1>
      <span class="muted">平台自动评 {{ s?.of || 60 }} 分，报告 {{ s?.report_points || 40 }} 分由老师在课程里批改</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab29/guide.docx">指导书</a> · <a href="/api/cae/lab29/report-template.docx">报告模板</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ s.score }} / {{ s.of }}</b>
        <span class="small">你的场景：客户 <b>{{ s.case.customer.split(' ')[0] }}</b>，机器人序列号以 <b class="mono">{{ s.case.prefix }}</b> 开头（3 台）</span>
        <router-link class="small" to="/rservice">客户与服务（现场的机器人）</router-link>
        <router-link class="small" to="/ont">厂情中枢</router-link>
        <button class="btn sm" @click="load">刷新</button>
      </div>

      <section v-if="s.teacher && s.class?.length" class="card">
        <div class="card-head"><h2>老师：全班成绩</h2></div>
        <table class="tbl small"><thead><tr><th>学生</th><th v-for="(t, i) in s.tasks" :key="t.id" class="num">任务 {{ i + 1 }}</th><th class="num">合计</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ c.user }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ c.total }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>任务 {{ i + 1 }}　{{ t.title }}</h2><span class="pts">{{ t.score }} / {{ t.points }}</span></div>
        <p>{{ t.desc }}</p>
        <p class="small muted">提示：{{ t.hint }}</p>
        <form v-if="t.id === 'l29_t1'" class="f" @submit.prevent="submit(t.id, a1)">
          <div class="lf"><label>机器人序列号</label><input v-model="a1.serial" class="w" required></div>
          <div class="lf"><label>关节</label><select v-model="a1.joint" required><option v-for="j in JOINTS" :key="j" :value="j">{{ j }}</option></select></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 'l29_t2'" class="f" @submit.prevent="submit(t.id, a2)">
          <div class="lf"><label>谐波减速器批号</label><input v-model="a2.lot" class="w" required></div>
          <div class="lf"><label>出厂背隙（′）</label><input v-model.number="a2.backlash0" type="number" step="0.01" required></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 'l29_t3'" class="f" @submit.prevent="submit(t.id, a3)">
          <div class="lf"><label>选一项</label><span class="cks col">
            <label v-for="o in s.t3_choices" :key="o.value"><input v-model="a3.choice" type="radio" :value="o.value" required> {{ o.label }}</label></span></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 'l29_t4'" class="f" @submit.prevent="submit(t.id, a4)">
          <div class="lf"><label>同批的机器人（逗号分开）</label><input v-model="a4.serials" class="w2" required></div>
          <button class="btn primary">提交</button>
        </form>
        <p v-if="t.id === 'l29_t5'" class="small muted">在“客户与服务 → 现场的机器人”里点报警的那台、选服务方案派工；工程师做完（或点“做完”）后这一步自动打勾。</p>
        <form v-if="t.id === 'l29_t6'" class="f" @submit.prevent="submit(t.id, a6)">
          <div class="lf"><label>A 全部预防性更换（$）</label><input v-model.number="a6.A" type="number" step="1" required></div>
          <div class="lf"><label>B 等报警了再换（$）</label><input v-model.number="a6.B" type="number" step="1" required></div>
          <span class="small muted">B 的每次停线损失 ${{ s.loss_per_complaint.toLocaleString() }}（示例值）</span>
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

const JOINTS = ['J1', 'J2', 'J3', 'J4', 'J5', 'J6'];
const s = ref(null);
const err = ref('');
const fb = reactive({});
const a1 = reactive({ serial: '', joint: '' });
const a2 = reactive({ lot: '', backlash0: null });
const a3 = reactive({ choice: '' });
const a4 = reactive({ serials: '' });
const a6 = reactive({ A: null, B: null });

async function load() {
  try { s.value = await get('/lab29'); err.value = ''; } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab29/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { err.value = e.message; }
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
.lf > label:first-child { width: 190px; font-weight: 500; padding-top: 4px; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 auto; min-width: 240px; font-size: 13px; }
.cks.col { flex-direction: column; }
.f .btn { align-self: flex-start; }
input, select { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; width: 140px; }
input.w { width: 220px; }
input.w2 { width: min(420px, 100%); }
input[type=radio] { height: auto; width: auto; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; }
.num { text-align: right; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
</style>
