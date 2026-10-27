<!-- 实验 25“关节背隙异常的追因与 8D”（第 47 轮，机器人厂）：控制图判异 → 按工位、批次分层 → 8D → 数据验证 -->
<template>
  <div class="page">
    <div class="page-title"><h1>实验 25 · 关节背隙异常的追因与 8D</h1>
      <span class="muted">平台自动评 {{ s?.of || 60 }} 分（按平台里的事实），报告 {{ s?.report_points || 40 }} 分由老师在课程里批改</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab25/guide.docx">指导书</a> · <a href="/api/cae/lab25/report-template.docx">报告模板</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ s.score }} / {{ s.of }}</b>
        <span class="pill" :class="s.injected ? 'warn' : ''">{{ s.injected ? '老师已注入问题：从数据里找原因' : '等老师注入问题' }}</span>
        <router-link class="small" to="/work/quality">质量（控制图）</router-link>
        <router-link class="small" to="/quality/8d">质量异常单（8D）</router-link>
        <button class="btn sm" @click="load">刷新</button>
      </div>

      <section v-if="s.teacher" class="card">
        <div class="card-head"><h2>老师：注入隐藏问题</h2><span class="small muted">学生看不到这里</span></div>
        <div class="row">
          <select v-model="kind" aria-label="问题"><option value="random">随机三选一（学生不知道是哪种）</option>
            <option v-for="k in s.inject_kinds" :key="k.value" :value="k.value">{{ k.label }}</option></select>
          <button class="btn danger" @click="inject">注入</button><span class="small ok">{{ injMsg }}</span>
        </div>
        <p v-if="s.problem" class="small">当前：{{ s.problem.name }}（{{ timeOf(s.problem.injected_at) }} 注入{{ s.problem.cleared_at ? '，已被措施消除' : '' }}）</p>
        <p class="small muted">注入后让车间接着做关节：在“订单与计划”接几张 WQJ-L / M / S 的单（每张 8–10 台），按层下达。学生的 8D 措施要您在“质量异常单”里批准，批准后才下发车间。</p>
        <table v-if="s.class?.length" class="tbl small"><thead><tr><th>学生</th><th v-for="(t, i) in s.tasks" :key="t.id" class="num">任务 {{ i + 1 }}</th><th class="num">合计</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ c.user }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ c.total }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>任务 {{ i + 1 }}　{{ t.title }}</h2><span class="pts">{{ t.score }} / {{ t.points }}</span></div>
        <p>{{ t.desc }}</p>
        <p class="small muted">提示：{{ t.hint }}</p>
        <form v-if="t.id === 'l25_t1'" class="f" @submit.prevent="submit(t.id, a1)">
          <div class="lf"><label>出问题的特性</label><select v-model="a1.characteristic" required>
            <option v-for="c in s.characteristics" :key="c.value" :value="c.value">{{ c.label }}</option></select></div>
          <div class="lf"><label>触发的判异规则</label><span class="cks">
            <label v-for="r in s.rules" :key="r"><input v-model="a1.rule" type="radio" :value="r" required> 规则 {{ r }}</label></span></div>
          <button class="btn primary" :disabled="!s.injected">提交</button>
        </form>
        <template v-if="t.id === 'l25_t2'">
          <div class="lf f"><label>看哪个特性分层</label><select v-model="sel" @change="loadStrata">
            <option v-for="c in s.characteristics" :key="c.value" :value="c.value">{{ c.label }}</option></select></div>
          <div v-if="strata" class="strata">
            <div v-for="(g, by) in { station: strata.station, lot: strata.lot }" :key="by">
              <b class="small">按{{ by === 'station' ? '装配工位' : '谐波减速器批次' }}</b>
              <table class="tbl small"><thead><tr><th>{{ by === 'station' ? '工位' : '批次' }}</th><th class="num">台数</th><th class="num">均值</th><th class="num">超差</th></tr></thead>
                <tbody><tr v-for="(x, k) in g" :key="k"><td class="mono">{{ k }}</td><td class="num">{{ x.n }}</td><td class="num">{{ x.mean }}</td>
                  <td class="num" :class="{ 'bad-t': x.fails }">{{ x.fails }}</td></tr></tbody></table>
              <p v-if="!Object.keys(g).length" class="small muted">还没有数据。</p>
            </div>
          </div>
          <form class="f" @submit.prevent="submit(t.id, a2)">
            <div class="lf"><label>问题出在</label><span class="cks">
              <label v-for="l in s.layers" :key="l.value"><input v-model="a2.by" type="radio" :value="l.value" required> {{ l.label }}</label></span></div>
            <div v-if="a2.by && a2.by !== 'sequence'" class="lf"><label>哪一个（工位或批号）</label><input v-model="a2.group" placeholder="如 ja-1 或 HD-L-002" required></div>
            <button class="btn primary" :disabled="!s.injected">提交</button>
          </form>
        </template>
        <div v-if="['l25_t3', 'l25_t4', 'l25_t5'].includes(t.id)" class="small">
          <template v-if="t.evidence?.q8d">你的 8D：<router-link :to="'/quality/8d/' + t.evidence.q8d">{{ t.evidence.q8d }}</router-link>
            <span v-if="t.id === 'l25_t4' && t.evidence.effective === false">（措施对了，等车间再做 10 台后在 8D 页点“验证”）</span></template>
          <template v-else-if="t.evidence?.note">{{ t.evidence.note }}</template>
          <template v-else>平台自动检查你的 8D 单。</template>
        </div>
        <p v-if="fb[t.id]" class="small fb">{{ fb[t.id] }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { get, post } from '../lib/api';
import { timeOf } from '../lib/fmt';

const s = ref(null);
const err = ref('');
const fb = reactive({});
const a1 = reactive({ characteristic: '', rule: null });
const a2 = reactive({ by: '', group: '' });
const kind = ref('random');
const injMsg = ref('');
const sel = ref('');
const strata = ref(null);

async function load() {
  try {
    s.value = await get('/lab25'); err.value = '';
    if (!sel.value && s.value.characteristics.length) { sel.value = s.value.characteristics[0].value; loadStrata(); }
  } catch (e) { err.value = e.message; }
}
async function loadStrata() {
  try { strata.value = await get('/lab25/strata?sel=' + encodeURIComponent(sel.value)); } catch { strata.value = null; }
}
async function submit(tid, body) {
  try { const r = await post('/lab25/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { alert(e.message); }
}
async function inject() {
  try { injMsg.value = (await post('/lab25/inject', { kind: kind.value })).text; await load(); } catch (e) { alert(e.message); }
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
select, input:not([type]) { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.strata { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; margin: 8px 0; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; }
.num { text-align: right; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.ok { color: var(--good); }
.bad-t { color: var(--bad); }
</style>
