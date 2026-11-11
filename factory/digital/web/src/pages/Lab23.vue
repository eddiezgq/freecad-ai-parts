<!-- 实验 23“两周情景：一张急单的全厂决策”（第 19 轮 J-7）：组队分角色、每一幕的小组决定（比对模式）、发起动作、复盘。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('实验 23 · 两周情景：一张急单的全厂决策') }}</h1>
      <span class="muted">{{ $t('两周课程设计，4–6 人一组；平台自动评 {a} 分，报告 {b} 分由老师在课程里批改', { a: s?.of || 60, b: s?.report_points || 40 }) }}</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab23/guide.docx">{{ $t('指导书') }}</a> · <a href="/api/cae/lab23/report-template.docx">{{ $t('报告模板') }}</a> · <router-link to="/help/teach/director">{{ $t('帮助') }}</router-link></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ $td(s.score) }} / {{ $td(s.of) }}</b>
        <span v-if="s.team" class="small">{{ $t('小组') }} <b>{{ $td(s.team) }}</b>{{ $t('：{a}', { a: s.members.map((m) => m.user + $t('（') + m.roles.join($t('、')) + $t('）')).join($t('；')) }) }}</span>
        <span v-if="!s.teacher && s.team" class="pill" :class="s.locked ? 'warn' : 'good'">{{ s.locked ? $t('比对模式：本组还有幕没交决定，这些异常在指挥台上不显示建议') : $t('各幕都交了决定：指挥台显示中枢的建议') }}</span>
        <span v-if="s.run" class="small">{{ $t('情景：已演 {a} / 8 幕', { a: $td(s.run.beat_no) }) }}<template v-if="s.order?.qty">{{ $t('，车间 {a} / {b} 根', { a: $td(s.order.parts), b: $td(s.order.qty) }) }}</template></span>
        <span v-else class="small muted">{{ $t('老师还没开始两周情景') }}</span>
        <router-link v-if="s.teacher" class="small" to="/director">{{ $t('情景导演') }}</router-link>
      </div>

      <section v-if="s.teacher && s.class?.length" class="card">
        <div class="card-head"><h2>{{ $t('老师：全班') }}</h2><span class="small muted">{{ $t('学生看不到这里') }}</span></div>
        <table class="tbl small"><thead><tr><th>{{ $t('小组') }}</th><th>{{ $t('学生') }}</th><th v-for="t in s.tasks" :key="t.id" class="num">{{ $td(t.title) }}</th><th class="num">{{ $t('合计') }}</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ c.team || '—' }}</td><td>{{ $td(c.user) }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ $td(c.total) }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>{{ $t('任务 {a}　{b}', { a: i + 1, b: $td(t.title) }) }}</h2><span class="pts">{{ $td(t.score) }} / {{ $td(t.points) }}</span></div>
        <p>{{ $td(t.desc) }}</p>
        <p class="small muted">{{ $t('提示：{a}', { a: $td(t.hint) }) }}</p>

        <form v-if="t.id === 'l23_t1'" class="f" @submit.prevent="register">
          <div class="field"><label>{{ $t('小组名') }}</label><input v-model="reg.team" required maxlength="30" :placeholder="$t('例如：第 3 组')"></div>
          <div class="field"><label>{{ $t('我的角色') }}</label><select v-model="reg.role" required><option v-for="r in s.roles" :key="r.key" :value="r.key">{{ $td(r.name) }}</option></select></div>
          <button class="btn primary">{{ $t('登记') }}</button>
          <span v-if="s.my_roles.length" class="small">{{ $t('已登记：{a}（兼角色就再登记一次）', { a: s.my_roles.map((k) => s.roles.find((r) => r.key === k)?.name || k).join($t('、')) }) }}</span>
        </form>

        <div v-if="t.id === 'l23_t2'" class="beats">
          <div v-for="b in s.beats.filter((x) => x.decide)" :key="b.n" class="beat" :class="{ decided: b.decision }">
            <div class="bh"><b>{{ $t('第 {a} 幕 · {b}', { a: $td(b.n), b: $td(b.title) }) }}</b><span class="small muted">{{ $t('{a} · 该{b}处理', { a: $td(b.domain_name), b: b.roles.map((r) => $td(r.name)).join($t('或')) }) }}</span>
              <span class="small r">{{ b.decision ? $t('✓ 已交：') + b.decision.label : (b.anomaly ? $t('待决定') : $t('还没演')) }}</span></div>
            <template v-if="b.anomaly">
              <p class="small">{{ $td(b.story) }}</p>
              <p class="small"><router-link :to="{ path: '/ont', query: { view: 'anomalies', a: b.anomaly.id } }">{{ $td(b.anomaly.rule) }} {{ $td(b.anomaly.title) }}</router-link></p>
              <p v-if="b.decision" class="small fb">{{ $t('{a}：{b}', { a: $td(b.decision.by), b: $td(b.decision.reason) }) }}<template v-if="b.decision.recommended">{{ $t('（中枢推荐：{a}）', { a: b.decision.recommended === b.decision.option ? $t('和你们一样') : $t('另一个方案，到指挥台看理由') }) }}</template></p>
              <template v-else-if="canDecide(b)">
                <button v-if="!opts[b.n]" class="btn" type="button" @click="loadOpts(b)">{{ $t('看方案（推演，要几秒）') }}</button>
                <form v-else class="f" @submit.prevent="decide(b)">
                  <table class="tbl small"><thead><tr><th></th><th>{{ $t('方案') }}</th><th class="num">{{ $t('多花（$）') }}</th><th>{{ $t('说明') }}</th></tr></thead>
                    <tbody><tr v-for="o in opts[b.n].options" :key="o.kind">
                      <td><input v-model="dec[b.n].option" type="radio" :value="o.kind" required :aria-label="o.label"></td><td>{{ $td(o.label) }}</td>
                      <td class="num">{{ o.result?.cost_total != null ? Math.round(o.result.cost_total).toLocaleString() : '—' }}</td><td>{{ o.note || '' }}</td></tr></tbody></table>
                  <div class="field"><label>{{ $t('理由与代价') }}</label><textarea v-model="dec[b.n].reason" rows="2" required :placeholder="$t('多花多少、交期变不变、风险在哪')"></textarea></div>
                  <button class="btn primary">{{ $t('代表小组提交第 {a} 幕的决定', { a: $td(b.n) }) }}</button>
                </form>
              </template>
              <p v-else class="small muted">{{ $t('这一幕由组里的{a}提交（右上角切到这个角色、并在任务 1 登记过）。', { a: b.roles.map((r) => r.name).join($t('或')) }) }}</p>
            </template>
          </div>
        </div>

        <div v-if="t.id === 'l23_t3'" class="small">
          <template v-if="t.evidence?.beats?.length">
            <span v-for="x in t.evidence.beats" :key="x.beat">{{ $t('第 {a} 幕：{b}；', { a: $td(x.beat), b: x.actions.map((a) => 'ACT-' + String(a.id).padStart(5, '0') + $t('（') + (ST[a.status] || a.status) + $t('）')).join($t('、')) }) }}</span>
          </template>
          <template v-else>{{ $t('本组还没有挂在情景异常上的动作。') }}</template> <router-link to="/ont/actions?box=mine">{{ $t('动作收件箱') }}</router-link>
        </div>

        <form v-if="t.id === 'l23_t4'" class="f" @submit.prevent="submit('l23_t4', a4)">
          <div class="field"><label>{{ $t('这张订单的毛利率（%）') }}</label><input v-model.number="a4.margin_pct" type="number" step="0.1" required></div>
          <div class="field"><label>{{ $t('记到订单上的钱最多的是第几幕') }}</label><input v-model.number="a4.top_beat" type="number" min="1" max="8" required></div>
          <div class="field"><label>{{ $t('动作费用合计（$）') }}</label><input v-model.number="a4.actions_usd" type="number" step="1" required></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <p v-if="fb[t.id]" class="small fb">{{ $td(fb[t.id]) }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { onMounted, reactive, ref } from 'vue';
import { get, post, session } from '../lib/api';

const ST = { draft: $t('草稿'), submitted: $t('待批准'), approved: $t('已批准'), rejected: $t('已驳回'), executing: $t('执行中'), done: $t('已完成'), failed: $t('失败') };
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
  try { s.value = await post('/lab23/decide/' + b.n, { ...dec[b.n] }); fb.l23_t2 = $t('已交第 ') + b.n + $t(' 幕的决定。到指挥台在这个方案下“采纳，生成动作”。'); await load(); } catch (e) { alert(e.message); }
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
