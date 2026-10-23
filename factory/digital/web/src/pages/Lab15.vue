<!-- 实验 15“车间异常的追因、推演与决策”（第 17 轮 D 期 D9）：先自己追因、自己拟方案，提交后才看中枢的建议 -->
<template>
  <div class="page">
    <div class="page-title"><h1>实验 15 · 车间异常的追因、推演与决策</h1>
      <span class="muted">平台自动评 {{ s?.of || 60 }} 分（按平台里的事实），报告 {{ s?.report_points || 40 }} 分由老师在课程里批改</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab15/guide.docx">指导书</a> · <a href="/api/cae/lab15/report-template.docx">报告模板</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ s.score }} / {{ s.of }}</b>
        <span v-if="!s.teacher" class="pill" :class="s.locked ? 'warn' : 'good'">{{ s.locked ? '比对模式：提交任务 3 之前，指挥台和 AI 不显示建议' : '已提交选择：可以看中枢的建议，和你的对比' }}</span>
        <router-link v-if="s.anomaly_id" class="small" :to="{ path: '/ont', query: { view: 'anomalies', a: s.anomaly_id } }">打开你选的异常</router-link>
      </div>

      <section v-if="s.teacher" class="card">
        <div class="card-head"><h2>老师：注入问题</h2><span class="small muted">学生看不到这里；三种可以组合</span></div>
        <div class="row">
          <select v-model="inj.kind"><option v-for="(l, k) in s.inject_kinds" :key="k" :value="k">{{ l }}</option></select>
          <template v-if="inj.kind === 'down'">
            <select v-model="inj.unit"><option v-for="u in UNITS" :key="u" :value="u">{{ u.toUpperCase() }}</option></select>
            <input v-model.number="inj.minutes" type="number" min="10" step="10" aria-label="停机分钟"> 分钟
          </template>
          <template v-if="inj.kind === 'shortage'">
            <select v-model="inj.item"><option v-for="c in ITEMS" :key="c" :value="c">{{ c }}</option></select>
            库存降到 <input v-model.number="inj.qty" type="number" min="0" aria-label="库存">
          </template>
          <button class="btn danger" @click="inject">注入</button><span class="small ok">{{ injMsg }}</span>
        </div>
        <p class="small muted">建议：停机选 GRD-01、1200–2400 分钟，并在“情景导演”的教师控制台切到“按班次”。注入后看指挥台右栏：“不处理”会晚、维修加急能按时，方案差别才明显；否则把停机加长再注入一次。</p>
        <table v-if="s.class?.length" class="tbl small"><thead><tr><th>学生</th><th v-for="t in s.tasks" :key="t.id" class="num">{{ t.title }}</th><th class="num">合计</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ c.user }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ c.total }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>任务 {{ i + 1 }}　{{ t.title }}</h2><span class="pts">{{ t.score }} / {{ t.points }}</span></div>
        <p>{{ t.desc }}</p>
        <p class="small muted">提示：{{ t.hint }}</p>
        <form v-if="t.id === 'l15_t1'" class="f" @submit.prevent="submit('l15_t1', a1)">
          <div class="field"><label>异常</label><select v-model="a1.anomaly_id" required>
            <option v-for="o in s.options.anomalies" :key="o.value" :value="o.value">{{ o.label }}</option></select></div>
          <div class="field"><label>受影响的工单</label><span class="cks">
            <label v-for="w in s.options.work_orders" :key="w"><input v-model="a1.work_orders" type="checkbox" :value="w"> {{ w }}</label></span></div>
          <div class="field"><label>受影响的订单</label><span class="cks">
            <label v-for="o in s.options.sales_orders" :key="o"><input v-model="a1.sales_orders" type="checkbox" :value="o"> {{ o }}</label></span></div>
          <div class="field"><label>不处理的话，订单晚几天</label><input v-model.number="a1.late_days" type="number" min="0" max="30" required></div>
          <button class="btn primary">提交因果链</button>
        </form>
        <div v-if="t.id === 'l15_t2'" class="small">
          已保存 {{ t.evidence?.scenarios?.length || 0 }} 个场景，其中不同的方案 {{ t.evidence?.distinct || 0 }} 个。
          <router-link v-if="s.anomaly_id" :to="{ path: '/ont/sim', query: { a: s.anomaly_id } }">去推演工作台</router-link>
          <span v-else class="muted">先完成任务 1（选定异常）。</span>
        </div>
        <form v-if="t.id === 'l15_t3'" class="f" @submit.prevent="submit('l15_t3', a3)">
          <div class="field"><label>选哪个场景</label><select v-model="a3.scenario_id" required>
            <option v-for="o in s.options.scenarios" :key="o.value" :value="o.value">{{ o.label }}</option></select></div>
          <div class="field"><label>理由与代价</label><textarea v-model="a3.reason" rows="3" required placeholder="交期、成本、风险……"></textarea></div>
          <button class="btn primary" :disabled="!s.options.scenarios.length">提交选择</button>
        </form>
        <div v-if="t.id === 'l15_t4'" class="small">
          <template v-if="t.evidence?.actions?.length">你的动作：<span v-for="x in t.evidence.actions" :key="x.id"> ACT-{{ String(x.id).padStart(5, '0') }}（{{ ST[x.status] || x.status }}）</span></template>
          <template v-else>还没有动作。</template> <router-link to="/ont/actions?box=mine">动作收件箱</router-link>
        </div>
        <form v-if="t.id === 'l15_t5'" class="f" @submit.prevent="submit('l15_t5', a5)">
          <div class="field"><label>推演与实际</label><span class="cks">
            <label v-for="b in s.buckets" :key="b"><input v-model="a5.bucket" type="radio" :value="b" required> {{ b }}</label></span></div>
          <button class="btn primary">提交复盘结论</button>
        </form>
        <p v-if="fb[t.id]" class="small fb">{{ fb[t.id] }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { get, post } from '../lib/api';

const UNITS = ['grd-01', 'cnc-l01-a', 'cnc-l01-b', 'key-01', 'saw-01', 'ht-01'];
const ITEMS = ['RM-45-D50', 'BRG-6207', 'BRG-6206', 'BRG-6205'];
const ST = { draft: '草稿', submitted: '待批准', approved: '已批准', rejected: '已驳回', executing: '执行中', done: '已完成', failed: '失败' };
const s = ref(null);
const err = ref('');
const fb = reactive({});
const a1 = reactive({ anomaly_id: null, work_orders: [], sales_orders: [], late_days: 0 });
const a3 = reactive({ scenario_id: null, reason: '' });
const a5 = reactive({ bucket: '' });
const inj = reactive({ kind: 'down', unit: 'grd-01', minutes: 2400, item: 'RM-45-D50', qty: 5 });
const injMsg = ref('');

async function load() {
  try {
    s.value = await get('/lab15');
    if (s.value.anomaly_id && !a1.anomaly_id) a1.anomaly_id = s.value.anomaly_id;
  } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab15/' + tid, { ...body }); fb[tid] = r.feedback; await load(); } catch (e) { alert(e.message); }
}
async function inject() {
  try { injMsg.value = (await post('/lab15/inject', { ...inj })).text; } catch (e) { alert(e.message); }
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
.field { display: flex; gap: 10px; align-items: flex-start; flex-wrap: wrap; }
.field > label:first-child { width: 150px; font-weight: 500; padding-top: 4px; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 300px; font-size: 13px; }
select, input[type=number] { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
textarea { flex: 1 1 300px; border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
input[type=number] { width: 90px; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.ok { color: var(--good); }
</style>
