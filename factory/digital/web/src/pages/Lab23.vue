<!-- 实验 23“两周情景：一张急单的全厂决策”（第 19 轮 J-7）：组队分角色、每一幕的小组决定（比对模式）、发起动作、复盘。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>实验 23 · 两周情景：一张急单的全厂决策</h1>
      <span class="muted">两周课程设计，4–6 人一组；平台自动评 {{ s?.of || 60 }} 分，报告 {{ s?.report_points || 40 }} 分由老师在课程里批改</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab23/guide.docx">指导书</a> · <a href="/api/cae/lab23/report-template.docx">报告模板</a> · <router-link to="/help/teach/director">帮助</router-link></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ s.score }} / {{ s.of }}</b>
        <span v-if="s.team" class="small">小组 <b>{{ s.team }}</b>：{{ s.members.map((m) => m.user + '（' + m.roles.join('、') + '）').join('；') }}</span>
        <span v-if="!s.teacher && s.team" class="pill" :class="s.locked ? 'warn' : 'good'">{{ s.locked ? '比对模式：本组还有幕没交决定，这些异常在指挥台上不显示建议' : '各幕都交了决定：指挥台显示中枢的建议' }}</span>
        <span v-if="s.run" class="small">情景：已演 {{ s.run.beat_no }} / 8 幕<template v-if="s.order?.qty">，车间 {{ s.order.parts }} / {{ s.order.qty }} 根</template></span>
        <span v-else class="small muted">老师还没开始两周情景</span>
        <router-link v-if="s.teacher" class="small" to="/director">情景导演</router-link>
      </div>

      <section v-if="s.teacher && s.class?.length" class="card">
        <div class="card-head"><h2>老师：全班</h2><span class="small muted">学生看不到这里</span></div>
        <table class="tbl small"><thead><tr><th>小组</th><th>学生</th><th v-for="t in s.tasks" :key="t.id" class="num">{{ t.title }}</th><th class="num">合计</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ c.team || '—' }}</td><td>{{ c.user }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ c.total }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>任务 {{ i + 1 }}　{{ t.title }}</h2><span class="pts">{{ t.score }} / {{ t.points }}</span></div>
        <p>{{ t.desc }}</p>
        <p class="small muted">提示：{{ t.hint }}</p>

        <form v-if="t.id === 'l23_t1'" class="f" @submit.prevent="register">
          <div class="field"><label>小组名</label><input v-model="reg.team" required maxlength="30" placeholder="例如：第 3 组"></div>
          <div class="field"><label>我的角色</label><select v-model="reg.role" required><option v-for="r in s.roles" :key="r.key" :value="r.key">{{ r.name }}</option></select></div>
          <button class="btn primary">登记</button>
          <span v-if="s.my_roles.length" class="small">已登记：{{ s.my_roles.map((k) => s.roles.find((r) => r.key === k)?.name || k).join('、') }}（兼角色就再登记一次）</span>
        </form>

        <div v-if="t.id === 'l23_t2'" class="beats">
          <div v-for="b in s.beats.filter((x) => x.decide)" :key="b.n" class="beat" :class="{ decided: b.decision }">
            <div class="bh"><b>第 {{ b.n }} 幕 · {{ b.title }}</b><span class="small muted">{{ b.domain_name }} · 该{{ b.roles.map((r) => r.name).join('或') }}处理</span>
              <span class="small r">{{ b.decision ? '✓ 已交：' + b.decision.label : (b.anomaly ? '待决定' : '还没演') }}</span></div>
            <template v-if="b.anomaly">
              <p class="small">{{ b.story }}</p>
              <p class="small"><router-link :to="{ path: '/ont', query: { view: 'anomalies', a: b.anomaly.id } }">{{ b.anomaly.rule }} {{ b.anomaly.title }}</router-link></p>
              <p v-if="b.decision" class="small fb">{{ b.decision.by }}：{{ b.decision.reason }}<template v-if="b.decision.recommended">（中枢推荐：{{ b.decision.recommended === b.decision.option ? '和你们一样' : '另一个方案，到指挥台看理由' }}）</template></p>
              <template v-else-if="canDecide(b)">
                <button v-if="!opts[b.n]" class="btn" type="button" @click="loadOpts(b)">看方案（推演，要几秒）</button>
                <form v-else class="f" @submit.prevent="decide(b)">
                  <table class="tbl small"><thead><tr><th></th><th>方案</th><th class="num">多花（$）</th><th>说明</th></tr></thead>
                    <tbody><tr v-for="o in opts[b.n].options" :key="o.kind">
                      <td><input v-model="dec[b.n].option" type="radio" :value="o.kind" required :aria-label="o.label"></td><td>{{ o.label }}</td>
                      <td class="num">{{ o.result?.cost_total != null ? Math.round(o.result.cost_total).toLocaleString() : '—' }}</td><td>{{ o.note || '' }}</td></tr></tbody></table>
                  <div class="field"><label>理由与代价</label><textarea v-model="dec[b.n].reason" rows="2" required placeholder="多花多少、交期变不变、风险在哪"></textarea></div>
                  <button class="btn primary">代表小组提交第 {{ b.n }} 幕的决定</button>
                </form>
              </template>
              <p v-else class="small muted">这一幕由组里的{{ b.roles.map((r) => r.name).join('或') }}提交（右上角切到这个角色、并在任务 1 登记过）。</p>
            </template>
          </div>
        </div>

        <div v-if="t.id === 'l23_t3'" class="small">
          <template v-if="t.evidence?.beats?.length">
            <span v-for="x in t.evidence.beats" :key="x.beat">第 {{ x.beat }} 幕：{{ x.actions.map((a) => 'ACT-' + String(a.id).padStart(5, '0') + '（' + (ST[a.status] || a.status) + '）').join('、') }}；</span>
          </template>
          <template v-else>本组还没有挂在情景异常上的动作。</template> <router-link to="/ont/actions?box=mine">动作收件箱</router-link>
        </div>

        <form v-if="t.id === 'l23_t4'" class="f" @submit.prevent="submit('l23_t4', a4)">
          <div class="field"><label>这张订单的毛利率（%）</label><input v-model.number="a4.margin_pct" type="number" step="0.1" required></div>
          <div class="field"><label>记到订单上的钱最多的是第几幕</label><input v-model.number="a4.top_beat" type="number" min="1" max="8" required></div>
          <div class="field"><label>动作费用合计（$）</label><input v-model.number="a4.actions_usd" type="number" step="1" required></div>
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
const reg = reactive({ team: '', role: '' });
const opts = reactive({});
const dec = reactive({});
const a4 = reactive({ margin_pct: null, top_beat: null, actions_usd: null });

function canDecide(b) {
  return !s.value.teacher && b.roles.some((r) => s.value.my_roles.includes(r.key)) && b.roles.some((r) => r.key === session.user?.role);
}
async function load() {
  try { s.value = await get('/lab23'); if (s.value.team && !reg.team) reg.team = s.value.team; } catch (e) { err.value = e.message; }
}
async function register() {
  try { fb.l23_t1 = (await post('/lab23/register', { ...reg })).feedback; await load(); } catch (e) { alert(e.message); }
}
async function loadOpts(b) {
  try { opts[b.n] = await get('/ont/anomalies/' + b.anomaly.id + '/options'); dec[b.n] = { option: '', reason: '' }; } catch (e) { alert(e.message); }
}
async function decide(b) {
  try { s.value = await post('/lab23/decide/' + b.n, { ...dec[b.n] }); fb.l23_t2 = '已交第 ' + b.n + ' 幕的决定。到指挥台在这个方案下“采纳，生成动作”。'; await load(); } catch (e) { alert(e.message); }
}
async function submit(tid, body) {
  try { const r = await post('/lab23/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { alert(e.message); }
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
.f > .btn { align-self: flex-start; }
.field { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; flex-direction: row; }
.field > label:first-child { width: 220px; font-weight: 500; }
input[type=number], .field input, .field select { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
textarea { flex: 1 1 300px; border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; }
.beats { display: flex; flex-direction: column; gap: 10px; }
.beat { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; }
.beat.decided { border-left: 4px solid var(--good); }
.bh { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.tbl { width: 100%; }
@media (max-width: 700px) { .field > label:first-child { width: auto; } .tbl { display: block; overflow-x: auto; } }
</style>
