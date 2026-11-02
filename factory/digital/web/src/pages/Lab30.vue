<!-- 实验 30“一台轮式人形从订单到交付”（第 74 轮，机器人厂）：接单、按层下达、两种整机抢 CAL-1、联调判定、交付开票、成本 -->
<template>
  <div class="page">
    <div class="page-title"><h1>实验 30 · 一台轮式人形从订单到交付</h1>
      <span class="muted">平台自动评 {{ s?.of || 60 }} 分（按平台里的事实），报告 {{ s?.report_points || 40 }} 分由老师在课程里批改</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab30/guide.docx">指导书</a> · <a href="/api/cae/lab30/report-template.docx">报告模板</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ s.score }} / {{ s.of }}</b>
        <span v-if="s.order" class="small">你的订单 <b class="mono">{{ s.order.sales_order }}</b>，{{ Object.keys(s.order.work_orders).length }} 张工单</span>
        <span v-else class="small muted">还没有你的 WQ-H1 订单：先做任务 1</span>
        <span v-if="s.other_order" class="small">同周的协作臂订单 <b class="mono">{{ s.other_order }}</b></span>
        <router-link class="small" to="/work/planner">订单与计划</router-link>
        <router-link class="small" to="/work/quality">质量</router-link>
        <router-link class="small" to="/cost">生产成本</router-link>
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
        <form v-if="t.id === 'l30_t1'" class="f" @submit.prevent="submit(t.id, a1)">
          <div class="lf"><label>要下几张工单</label><input v-model.number="a1.work_orders" type="number" min="1" max="50" required></div>
          <div class="lf"><label>一台用几个关节模组</label><input v-model.number="a1.joints" type="number" min="1" max="40" required></div>
          <div class="lf"><label>底盘 WQ-AGV300 从哪来</label><span class="cks">
            <label v-for="o in s.t1_sources" :key="o.value"><input v-model="a1.chassis" type="radio" :value="o.value" required> {{ o.label }}</label></span></div>
          <button class="btn primary">提交</button>
        </form>
        <div v-if="t.id === 'l30_t2'" class="small">
          <table v-if="s.layers.length" class="tbl"><thead><tr><th>物料</th><th>工单</th><th>下达</th><th>用到的下一层</th><th>核对</th></tr></thead>
            <tbody><tr v-for="l in s.layers" :key="l.work_order">
              <td class="mono">{{ l.item }}</td><td class="mono">{{ l.work_order }}</td><td>{{ l.released ? timeOf(l.released) : '还没下达' }}</td>
              <td>{{ l.children.join('、') || '—' }}</td>
              <td><span v-if="!l.released" class="muted">—</span><span v-else-if="l.released_before_children_done.length" class="bad-t">
                {{ l.released_before_children_done.join('、') }} 还没做完就下达了</span><span v-else class="ok">✓</span></td></tr></tbody></table>
          <p v-else class="muted">先完成任务 1。</p>
        </div>
        <form v-if="t.id === 'l30_t3'" class="f" @submit.prevent="submit(t.id, a3)">
          <div class="lf"><label>两种整机抢的工位</label><input v-model="a3.unit" placeholder="设备编号，如 RA-1" required></div>
          <div class="lf"><label>这一周可行的对策</label><span class="cks">
            <label v-for="o in s.t3_options" :key="o.value"><input v-model="a3.choices" type="checkbox" :value="o.value"> {{ o.label }}</label></span></div>
          <p class="small muted">去看：<router-link to="/work/planner">订单与计划</router-link>的产能、<router-link to="/people">人员与排班</router-link>的技能矩阵。</p>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 'l30_t4'" class="f" @submit.prevent="submit(t.id, a4)">
          <div class="lf"><label>人形</label><select v-model="a4.serial" required>
            <option v-for="j in s.units" :key="j.serial" :value="j.serial">{{ j.serial }}（{{ j.item }}）</option></select></div>
          <div v-if="unit" class="lf"><label>测量值</label><span class="small">
            <span v-for="(c, k) in unit.chars" :key="k" class="chip">{{ c.name }} <b class="mono">{{ c.value }}</b> {{ c.unit }}（公差 {{ c.lo }}–{{ c.hi }}）</span></span></div>
          <div class="lf"><label>判定</label><span class="cks">
            <label><input v-model="a4.verdict" type="radio" value="pass" required> 合格</label>
            <label><input v-model="a4.verdict" type="radio" value="fail"> 不合格</label></span></div>
          <div v-if="a4.verdict === 'fail' && unit" class="lf"><label>超了哪一项</label><select v-model="a4.char">
            <option v-for="(c, k) in unit.chars" :key="k" :value="k">{{ c.name }}</option></select></div>
          <p v-if="!s.units.length" class="small muted">你这张单的人形还没测（人形联调做完才有）。</p>
          <button class="btn primary" :disabled="!s.units.length">提交</button>
        </form>
        <p v-if="t.id === 'l30_t6' && s.std" class="small">整台 WQ-H1 的标准成本（含底盘）（逐层累加）：材料 <b class="mono">${{ s.std.material.toLocaleString() }}</b>，
          各层工序 <b class="mono">${{ s.std.operations.toLocaleString() }}</b>，合计 <b class="mono">${{ s.std.total.toLocaleString() }}</b>。
          实际成本 = 材料 + 你这张单各工单的实际工时成本（“生产成本”页逐张看）。</p>
        <form v-if="t.id === 'l30_t6'" class="f" @submit.prevent="submit(t.id, a6)">
          <div class="lf"><label>实际比标准高（%）</label><input v-model.number="a6.variance_pct" type="number" step="0.1" required></div>
          <div class="lf"><label>差得最多的工单（物料编号）</label><input v-model="a6.worst" placeholder="如 WQJ-S" required></div>
          <button class="btn primary">提交</button>
        </form>
        <p v-if="fb[t.id]" class="small fb">{{ fb[t.id] }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { get, post } from '../lib/api';
import { timeOf } from '../lib/fmt';

const s = ref(null);
const err = ref('');
const fb = reactive({});
const a1 = reactive({ work_orders: null, joints: null, chassis: '' });
const a3 = reactive({ unit: '', choices: [] });
const a4 = reactive({ serial: '', verdict: '', char: '' });
const a6 = reactive({ variance_pct: null, worst: '' });
const unit = computed(() => s.value?.units?.find((j) => j.serial === a4.serial) || null);

async function load() {
  try { s.value = await get('/lab30'); err.value = ''; } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab30/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { alert(e.message); }
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
.f .btn { align-self: flex-start; }
select, input[type=number], input:not([type]) { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
input[type=number] { width: 100px; }
.chip { display: inline-block; margin: 0 10px 4px 0; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; }
.num { text-align: right; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.ok { color: var(--good); }
.bad-t { color: var(--bad); }
</style>
