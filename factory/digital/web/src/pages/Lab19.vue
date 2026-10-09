<!-- 实验 19“排班与技能：缺人时的决策”（第 18 轮 E4-10）：找单点依赖、手算缺人影响、比较方案（比对模式）、执行调班、技能培训计划 -->
<template>
  <div class="page">
    <div class="page-title"><h1>实验 19 · 排班与技能：缺人时的决策</h1>
      <span class="muted">平台自动评 {{ s?.of || 60 }} 分（按平台里的事实），报告 {{ s?.report_points || 40 }} 分由老师在课程里批改</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab19/guide.docx">指导书</a> · <a href="/api/cae/lab19/report-template.docx">报告模板</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ s.score }} / {{ s.of }}</b>
        <span v-if="!s.teacher" class="pill" :class="s.locked ? 'warn' : 'good'">{{ s.locked ? '比对模式：提交任务 3 之前，指挥台和 AI 不显示建议' : '已提交选择：可以看中枢的建议，和你的对比' }}</span>
        <span class="small" :class="s.enabled ? 'ok' : 'muted'">车间“要有人”{{ s.enabled ? '已打开' : '没打开' }}</span>
        <span v-if="s.gap" class="small">缺口：{{ s.gap.day }} {{ s.gap.shift === 'day' ? '早班' : '晚班' }} {{ s.gap.unit.toUpperCase() }}（{{ s.gap.name }} 请假）</span>
        <router-link v-if="s.anomaly_id" class="small" :to="{ path: '/ont', query: { view: 'anomalies', a: s.anomaly_id } }">打开排班缺口异常</router-link>
        <router-link v-if="s.h1_anomaly_id" class="small" :to="{ path: '/ont', query: { view: 'anomalies', a: s.h1_anomaly_id } }">单点依赖异常</router-link>
        <router-link class="small" to="/people?tab=skills">人员</router-link>
        <span v-if="!s.teacher && !['lead', 'planner'].includes(session.user?.role)" class="small warn-t">提示：调班、技能培训要用“班组长”或“计划员”角色发起（右上角切换角色）。</span>
      </div>

      <section v-if="s.teacher" class="card">
        <div class="card-head"><h2>老师：设置</h2><span class="small muted">学生看不到这里</span></div>
        <div class="row">
          <button class="btn" @click="inject({ enable: !s.enabled })">{{ s.enabled ? '关闭' : '打开' }}车间“要有人”</button>
          让 <select v-model="emp" aria-label="谁请假"><option v-for="p in s.people" :key="p.value" :value="p.value">{{ p.label }}</option></select>
          下一个班请假 <button class="btn danger" @click="inject({ enable: true, emp_id: emp })">设置</button><span class="small ok">{{ injMsg }}</span>
        </div>
        <p class="small muted">建议：王强（P01，外圆磨床早班；磨床是瓶颈）。</p>
        <table v-if="s.class?.length" class="tbl small"><thead><tr><th>学生</th><th v-for="t in s.tasks" :key="t.id" class="num">{{ t.title }}</th><th class="num">合计</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ c.user }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ c.total }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>任务 {{ i + 1 }}　{{ t.title }}</h2><span class="pts">{{ t.score }} / {{ t.points }}</span></div>
        <p>{{ t.desc }}</p>
        <p class="small muted">提示：{{ t.hint }}</p>
        <form v-if="t.id === 'l19_t1'" class="f" @submit.prevent="submit('l19_t1', { units: a1 })">
          <div class="field"><label>只有一个人会开的设备</label><span class="cks">
            <label v-for="u in s.units" :key="u.value"><input v-model="a1" type="checkbox" :value="u.value"> {{ u.label }}</label></span></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 'l19_t2'" class="f" @submit.prevent="submit('l19_t2', a2)">
          <div class="field"><label>这一班停多少小时</label><input v-model.number="a2.hours" type="number" step="0.5" required></div>
          <div class="field"><label>少做多少件</label><input v-model.number="a2.parts" type="number" step="1" required></div>
          <button class="btn primary" :disabled="!s.gap">提交</button>
        </form>
        <form v-if="t.id === 'l19_t3'" class="f" @submit.prevent="submit('l19_t3', a3)">
          <div class="field"><label>选哪个方案</label><span class="cks">
            <label v-for="o in s.options" :key="o.value"><input v-model="a3.option" type="radio" :value="o.value" required> {{ o.label }}</label></span></div>
          <div class="field"><label>理由与代价</label><textarea v-model="a3.reason" rows="3" required placeholder="交期、花费、对别的班的影响、加班上限……"></textarea></div>
          <button class="btn primary" :disabled="!s.gap">提交选择</button>
        </form>
        <div v-if="t.id === 'l19_t4'" class="small">
          <template v-if="t.evidence?.actions?.length">你的动作：<span v-for="x in t.evidence.actions" :key="x.id"> ACT-{{ String(x.id).padStart(5, '0') }}（{{ ST[x.status] || x.status }}）</span>
            <span> · 这一班人员等级：{{ ['没人', '学徒', '熟练'][t.evidence.level] ?? '—' }}</span></template>
          <template v-else>还没有调班或加班动作。</template> <router-link to="/ont/actions?box=mine">动作收件箱</router-link> · <router-link to="/people?tab=roster">排班</router-link>
        </div>
        <div v-if="t.id === 'l19_t5'" class="small">
          <template v-if="t.evidence?.actions?.length">技能培训：<span v-for="x in t.evidence.actions" :key="x.id"> {{ x.unit.toUpperCase() }}（{{ ST[x.status] || x.status }}）</span>
            · 覆盖 {{ t.evidence.covered.length }} / {{ t.evidence.single_points.length }} 台单点依赖设备</template>
          <template v-else>还没有技能培训动作。</template>
        </div>
        <p v-if="fb[t.id]" class="small fb">{{ fb[t.id] }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { get, post, session } from '../lib/api';

const ST = { draft: '草稿', submitted: '待批准', approved: '已批准', rejected: '已驳回', executing: '执行中', done: '已完成', failed: '失败' };
const s = ref(null);
const err = ref('');
const fb = reactive({});
const a1 = ref([]);
const a2 = reactive({ hours: null, parts: null });
const a3 = reactive({ option: '', reason: '' });
const emp = ref('P01');
const injMsg = ref('');

async function load() {
  try { s.value = await get('/lab19'); } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab19/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { alert(e.message); }
}
async function inject(body) {
  try { injMsg.value = (await post('/lab19/inject', body)).text; await load(); } catch (e) { alert(e.message); }
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
.field { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.field > label:first-child { width: 200px; font-weight: 500; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 300px; font-size: 13px; }
select, input[type=number] { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
input[type=number] { width: 110px; }
textarea { flex: 1 1 300px; border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.ok { color: var(--good); }
.warn-t { color: var(--warn); }
</style>
