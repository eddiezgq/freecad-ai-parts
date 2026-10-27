<!-- 实验 18“设备维护策略：保养时机的决策”（第 18 轮 E3-9）：手算概率、比较方案（比对模式）、执行保养、对比、估 MTBF -->
<template>
  <div class="page">
    <div class="page-title"><h1>实验 18 · 设备维护策略：保养时机的决策</h1>
      <span class="muted">平台自动评 {{ s?.of || 60 }} 分（按平台里的事实），报告 {{ s?.report_points || 40 }} 分由老师在课程里批改</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab18/guide.docx">指导书</a> · <a href="/api/cae/lab18/report-template.docx">报告模板</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ s.score }} / {{ s.of }}</b>
        <span v-if="!s.teacher" class="pill" :class="s.locked ? 'warn' : 'good'">{{ s.locked ? '比对模式：提交任务 2 之前，指挥台和 AI 不显示建议' : '已提交选择：可以看中枢的建议，和你的对比' }}</span>
        <router-link v-if="s.anomaly_id" class="small" :to="{ path: '/ont', query: { view: 'anomalies', a: s.anomaly_id } }">打开这台设备的异常</router-link>
        <router-link class="small" to="/maint">设备维护</router-link>
        <span class="small muted">车间可靠性系数 {{ s.factor }}</span>
        <span v-if="!s.teacher && session.user?.role !== 'maintenance'" class="small warn-t">提示：保养工单要用“维修工”角色发起（右上角切换角色）。</span>
      </div>

      <section v-if="s.teacher" class="card">
        <div class="card-head"><h2>老师：设置</h2><span class="small muted">学生看不到这里</span></div>
        <div class="row">
          可靠性 <select v-model.number="inj.factor"><option :value="0">关（不会坏）</option><option :value="1">正常</option><option :value="5">加速 ×5</option></select>
          把 <select v-model="inj.unit"><option v-for="u in s.units" :key="u.value" :value="u.value">{{ u.label }}</option></select>
          的运行小时拨到 <input v-model.number="inj.hours" type="number" min="0" step="10" aria-label="运行小时"> 小时
          <button class="btn danger" @click="inject">设置</button><span class="small ok">{{ injMsg }}</span>
        </div>
        <p class="small muted">建议：加速 ×5，GRD-01 拨到 600–700 小时（保养周期 500）。运行小时填 0 表示只改可靠性。</p>
        <table v-if="s.class?.length" class="tbl small"><thead><tr><th>学生</th><th v-for="t in s.tasks" :key="t.id" class="num">{{ t.title }}</th><th class="num">合计</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ c.user }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ c.total }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>任务 {{ i + 1 }}　{{ t.title }}</h2><span class="pts">{{ t.score }} / {{ t.points }}</span></div>
        <p>{{ t.desc }}</p>
        <p class="small muted">提示：{{ t.hint }}</p>
        <form v-if="t.id === 'l18_t1'" class="f" @submit.prevent="submit('l18_t1', a1)">
          <div class="field"><label>设备</label><select v-model="a1.unit" required><option v-for="u in s.units" :key="u.value" :value="u.value">{{ u.label }}</option></select></div>
          <div class="field"><label>自上次保养运行（小时）</label><input v-model.number="a1.run_h" type="number" step="0.1" required></div>
          <div class="field"><label>未来 80 运行小时坏掉的概率（%）</label><input v-model.number="a1.p_fail" type="number" step="0.01" required></div>
          <div class="field"><label>预期损失（$）</label><input v-model.number="a1.loss" type="number" step="1" required></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 'l18_t2'" class="f" @submit.prevent="submit('l18_t2', a2)">
          <div class="field"><label>选哪个方案</label><span class="cks">
            <label v-for="o in s.options" :key="o.value"><input v-model="a2.option" type="radio" :value="o.value" required> {{ o.label }}</label></span></div>
          <div class="field"><label>理由与代价</label><textarea v-model="a2.reason" rows="3" required placeholder="概率、预期损失、保养花费、交期……"></textarea></div>
          <button class="btn primary" :disabled="!s.unit">提交选择</button>
        </form>
        <div v-if="t.id === 'l18_t3'" class="small">
          <template v-if="t.evidence?.actions?.length">你的保养工单：<span v-for="x in t.evidence.actions" :key="x.id"> ACT-{{ String(x.id).padStart(5, '0') }}（{{ ST[x.status] || x.status }}）</span>
            <span v-if="t.evidence.pm"> · 保养单：{{ { doing: '保养中', fixed: '待验收', closed: '已完成' }[t.evidence.pm] || t.evidence.pm }}</span></template>
          <template v-else>还没有保养工单。</template> <router-link to="/ont/actions?box=mine">动作收件箱</router-link> · <router-link to="/maint?tab=pm">保养</router-link>
        </div>
        <form v-if="t.id === 'l18_t4'" class="f" @submit.prevent="submit('l18_t4', a4)">
          <div class="field"><label>我保养的设备，保养后坏了几次</label><input v-model.number="a4.mine" type="number" min="0" required></div>
          <div class="field"><label>逾期最多的另一台，同期坏了几次</label><input v-model.number="a4.other" type="number" min="0" required></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 'l18_t5'" class="f" @submit.prevent="submit('l18_t5', a5)">
          <div class="field"><label>全厂近 30 天 MTBF（运行小时）</label><input v-model.number="a5.mtbf" type="number" step="0.1" required></div>
          <button class="btn primary">提交</button>
        </form>
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
const a1 = reactive({ unit: 'grd-01', run_h: null, p_fail: null, loss: null });
const a2 = reactive({ option: '', reason: '' });
const a4 = reactive({ mine: null, other: null });
const a5 = reactive({ mtbf: null });
const inj = reactive({ factor: 5, unit: 'grd-01', hours: 650 });
const injMsg = ref('');

async function load() {
  try { s.value = await get('/lab18'); if (s.value.unit) a1.unit = s.value.unit; } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab18/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { alert(e.message); }
}
async function inject() {
  try { injMsg.value = (await post('/lab18/inject', { ...inj })).text; await load(); } catch (e) { alert(e.message); }
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
.field > label:first-child { width: 230px; font-weight: 500; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 300px; font-size: 13px; }
select, input[type=number] { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
input[type=number] { width: 110px; }
textarea { flex: 1 1 300px; border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.ok { color: var(--good); }
.warn-t { color: var(--warn); }
</style>
