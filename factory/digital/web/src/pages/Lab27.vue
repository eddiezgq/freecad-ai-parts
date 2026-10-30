<!-- 实验 27“两厂之间的一张订单”（第 57 轮，机器人厂）：接 2 台 AGV、WQR-105 采购单送到减速器厂、到货检验、交期、安全库存、复盘 -->
<template>
  <div class="page">
    <div class="page-title"><h1>实验 27 · 两厂之间的一张订单</h1>
      <span class="muted">平台自动评 {{ s?.of || 60 }} 分，报告 {{ s?.report_points || 40 }} 分由老师在课程里批改</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab27/guide.docx">指导书</a> · <a href="/api/cae/lab27/report-template.docx">报告模板</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ s.score }} / {{ s.of }}</b>
        <span v-if="s.order" class="small">你的订单 <b class="mono">{{ s.order.sales_order }}</b>（WQ-AGV300 × {{ s.order.qty }}），请购单
          <b class="mono">{{ s.order.material_request || '—' }}</b></span>
        <span v-else class="small muted">还没有你的 AGV 订单：先做任务 1</span>
        <span v-if="s.lot" class="small">WQR-105 批次 <b class="mono">{{ s.lot.lot || '#' + s.lot.id }}</b>：{{ s.lot.status_label }}{{ s.lot_days !== null ? '，用了 ' + s.lot_days + ' 天' : '' }}</span>
        <router-link class="small" to="/work/planner">订单与计划</router-link>
        <router-link class="small" to="/supply">采购与来料</router-link>
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
        <form v-if="t.id === 'l27_t1'" class="f" @submit.prevent="submit(t.id, a1)">
          <div class="lf"><label>WQR-105 请购（台）</label><input v-model.number="a1.qty" type="number" min="0" max="200" required></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 'l27_t2'" class="f" @submit.prevent="submit(t.id, a2)">
          <div class="lf"><label>工业园订单号</label><input v-model="a2.order" placeholder="如 3" required></div>
          <button class="btn primary">提交</button>
        </form>
        <p v-if="t.id === 'l27_t3'" class="small muted">{{ s.lot ? '这一批现在：' + s.lot.status_label : '采购单送出、到货后在“采购与来料 → 到货与检验”里检验。' }}</p>
        <form v-if="t.id === 'l27_t4'" class="f" @submit.prevent="submit(t.id, a4)">
          <div class="lf"><label>下单到到货（天）</label><input v-model.number="a4.days" type="number" step="0.1" required></div>
          <div class="lf"><label>和承诺的 10 天比</label><span class="cks">
            <label><input v-model="a4.on_time" type="radio" :value="true" required> 不晚（≤ 10 天）</label>
            <label><input v-model="a4.on_time" type="radio" :value="false"> 晚了</label></span></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 'l27_t5'" class="f" @submit.prevent="submit(t.id, a5)">
          <p class="small">你的数据（示例值）：日需求均值 d = <b>{{ s.demand.d }}</b> 台/天，标准差 σ_d = <b>{{ s.demand.sigma_d }}</b> 台/天，
            提前期 L = <b>{{ s.demand.lead_days }}</b> 天，z = {{ s.demand.z }}</p>
          <div class="lf"><label>安全库存 SS（台）</label><input v-model.number="a5.ss" type="number" step="0.01" required></div>
          <div class="lf"><label>订货点 ROP（台）</label><input v-model.number="a5.rop" type="number" step="0.01" required></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 'l27_t6'" class="f" @submit.prevent="submit(t.id, a6)">
          <div class="lf"><label>选一项</label><span class="cks col">
            <label v-for="o in s.t6_choices" :key="o.value"><input v-model="a6.choice" type="radio" :value="o.value" required> {{ o.label }}</label></span></div>
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
const a1 = reactive({ qty: null });
const a2 = reactive({ order: '' });
const a4 = reactive({ days: null, on_time: null });
const a5 = reactive({ ss: null, rop: null });
const a6 = reactive({ choice: '' });

async function load() {
  try { s.value = await get('/lab27'); err.value = ''; } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab27/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { err.value = e.message; }
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
.f .btn { align-self: flex-start; }
input[type=number], input:not([type]) { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; width: 120px; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; }
.num { text-align: right; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
</style>
