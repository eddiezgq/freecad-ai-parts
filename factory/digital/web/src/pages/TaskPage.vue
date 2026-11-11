<template>
  <div class="page">
    <div class="page-title"><h1><span class="mono">{{ $td(task?.code) }}</span> {{ task?.title?.[0] }}</h1>
      <router-link to="/tasks" class="small">{{ $t('← 我的任务') }}</router-link></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="task">
      <section class="card">
        <p class="small">{{ $t('角色：') }}<b>{{ task.role?.[0] }}</b> {{ $t('· 建议 {a} 学时 · 交期', { a: $td(task.hours) }) }} <b>{{ task.due ? timeOf(task.due) : $t('未定') }}</b>
          <span v-if="left" class="muted">{{ $t('（{a}）', { a: left }) }}</span> {{ $t('· 工位') }} <span v-for="s in task.stations" :key="s" class="pill">{{ s }}</span></p>
        <p>{{ task.background?.[0] }}</p>
        <p v-if="task.docs_base" class="small">{{ $t('下载：') }}
          <a v-for="k in task.docs" :key="k" :href="task.docs_base + k" target="_blank">{{ $td(DOCS[k]) }}</a></p>
        <div class="stages">
          <span v-for="(n, i) in STAGES" :key="n" class="stage" :class="{ done: i <= stage, now: i === stage + 1 }">{{ i + 1 }} {{ n }}</span>
        </div>
      </section>

      <!-- 老师：本任务单的全部提交 -->
      <section v-if="teacher" class="card">
        <div class="card-head"><h2>{{ $t('学生提交') }}</h2><span class="muted small">{{ $t('点“审阅”看交付物、关闭意见、批准、评分') }}</span></div>
        <div v-if="!subs.length" class="empty">{{ $t('还没有人开始。') }}</div>
        <table v-else class="t">
          <thead><tr><th>{{ $t('学生') }}</th><th>{{ $t('状态') }}</th><th class="num">{{ $t('轮次') }}</th><th>{{ $t('AI 意见（未关闭）') }}</th><th class="num">{{ $t('AI 建议分') }}</th><th class="num">{{ $t('成绩') }}</th><th></th></tr></thead>
          <tbody><tr v-for="s in subs" :key="s.id">
            <td>{{ $td(s.name) }}</td><td><span class="pill" :class="TONE[s.status]">{{ $td(s.status_zh) }}</span></td>
            <td class="num">{{ $td(s.rounds) }}</td>
            <td class="small">{{ $t('{a} 必改 · {b} 建议', { a: $td(s.open_errors), b: $td(s.open_warnings) }) }}</td>
            <td class="num">{{ s.suggested ?? '—' }}</td><td class="num">{{ s.total ?? '—' }}</td>
            <td><router-link v-if="s.status !== 'draft'" :to="'/tasks/review/' + s.id">{{ $t('审阅') }}</router-link></td></tr></tbody>
        </table>
      </section>

      <!-- 学生：交付物 -->
      <section v-else class="card">
        <div class="card-head"><h2>{{ $t('交付物') }}</h2>
          <span class="pill" :class="TONE[sub?.status || 'draft']">{{ sub ? sub.status_zh : $t('未开始') }}</span>
          <span v-if="sub?.status === 'returned'" class="err small">{{ $t('老师退回：{a}', { a: $td(sub.decision) }) }}</span></div>
        <table class="t">
          <thead><tr><th>#</th><th>{{ $t('交付物') }}</th><th>{{ $t('验收标准') }}</th><th>{{ $t('状态') }}</th><th></th></tr></thead>
          <tbody><tr v-for="d in task.deliverables" :key="d.i">
            <td>{{ d.i + 1 }}</td>
            <td>{{ $td(d.name[0]) }}<div class="small muted">{{ $td(KIND[d.kind]) }}{{ d.formats ? $t('（') + d.formats.join($t('、')) + $t('）') : '' }}{{ d.item ? ' · ' + d.item : '' }}</div></td>
            <td class="small">{{ $td(d.accept[0]) }}</td>
            <td class="small">
              <template v-if="got(d)">
                <span v-if="d.kind === '文件'">✓ <a :href="got(d).files[0].url" target="_blank">{{ got(d).files[0].name }}</a></span><!-- i18n-ok 数据值比较 -->
                <span v-else-if="d.kind === '设计发布'">{{ $t('✓ 设计发布') }} <router-link :to="'/design/' + got(d).plm">{{ got(d).plm }}</router-link></span><!-- i18n-ok 数据值比较 -->
                <span v-else-if="d.kind === '分析'">{{ $t('✓ 仿真与分析 作业') }} <span class="mono">{{ got(d).job }}</span></span><!-- i18n-ok 数据值比较 -->
                <span v-else-if="d.kind === '工艺规程'">{{ $t('✓ 工艺规程提交') }} <router-link class="mono" :to="'/process/' + got(d).process">{{ got(d).process }}</router-link></span><!-- i18n-ok 数据值比较 -->
                <span v-else-if="d.kind === '更改单'">{{ $t('✓ {a} 项', { a: got(d).rows.length }) }}</span><!-- i18n-ok 数据值比较 -->
                <span v-else-if="d.kind === 'PLC 程序'">✓ <a :href="got(d).files[0].url" target="_blank">{{ got(d).files[0].name }}</a><!-- i18n-ok 数据值比较 -->
                  <span v-if="!got(d).check?.ok" class="err">{{ $t('编译不过：{a}', { a: got(d).check?.error }) }}</span>
                  <span v-else-if="got(d).check.errors" class="err">{{ $t('程序检查 {a} 条错误', { a: got(d).check.errors }) }}</span>
                  <span v-else class="ok">{{ $t('编译通过') }}</span></span>
              </template>
              <span v-else class="muted">{{ $t('○ 未交') }}</span></td>
            <td class="act">
              <template v-if="editable">
                <label v-if="d.kind === '文件' || d.kind === 'PLC 程序'" class="btn small">{{ $t('上传') }}<input type="file" hidden @change="sendFile(d, $event)"></label><!-- i18n-ok 数据值比较 -->
                <button v-else-if="d.kind === '设计发布'" class="btn small" @click="open = { d, kind: 'design' }">{{ $t('提交模型') }}</button><!-- i18n-ok 数据值比较 -->
                <button v-else-if="d.kind === '分析'" class="btn small" @click="pickJob(d)">{{ $t('选择作业') }}</button><!-- i18n-ok 数据值比较 -->
                <button v-else-if="d.kind === '工艺规程'" class="btn small" @click="pickProcess(d)">{{ $t('选择工艺规程') }}</button><!-- i18n-ok 数据值比较 -->
                <button v-else-if="d.kind === '更改单'" class="btn small" @click="editChange(d)">{{ $t('填写') }}</button><!-- i18n-ok 数据值比较 -->
              </template></td>
          </tr></tbody>
        </table>

        <!-- 弹出的小表单 -->
        <div v-if="open" class="pop">
          <template v-if="open.kind === 'design'">
            <b>{{ $t('提交 {a} 的模型（进“待审”，任务单批准时一并生效）', { a: $td(open.d.item) }) }}</b>
            <label>{{ $t('STEP 模型') }} <input type="file" accept=".step,.stp" @change="(e) => (open.step = e.target.files[0])"></label>
            <label>{{ $t('图纸（可选，PDF 或 SVG）') }}<input type="file" accept=".pdf,.svg" @change="(e) => (open.drawing = e.target.files[0])"></label>
            <label>{{ $t('改动说明') }} <input v-model="open.note" maxlength="300"></label>
            <div class="line"><button class="btn primary" :disabled="!open.step || busy" @click="sendDesign">{{ $t('提交') }}</button>
              <button class="btn ghost" @click="open = null">{{ $t('取消') }}</button></div>
          </template>
          <template v-else-if="open.kind === 'job'">
            <b>{{ $t('选择“仿真与分析”里自己算完的作业') }}</b>
            <div v-if="!jobs.length" class="small muted">{{ $t('还没有作业。先到') }} <router-link to="/cae">{{ $t('仿真与分析') }}</router-link> {{ $t('算一个。') }}</div>
            <label v-for="j in jobs" :key="j.id" class="opt"><input v-model="open.job" type="radio" :value="j.id">
              <span class="mono">{{ $td(j.id) }}</span> {{ j.title || j.item }} · {{ $td(j.status) }}</label>
            <div class="line"><button class="btn primary" :disabled="!open.job" @click="sendLink({ job: open.job })">{{ $t('选定') }}</button>
              <button class="btn ghost" @click="open = null">{{ $t('取消') }}</button></div>
          </template>
          <template v-else-if="open.kind === 'process'">
            <b>{{ $t('选择自己提交的工艺规程') }}</b>
            <label v-for="p in procs" :key="p.id" class="opt"><input v-model="open.process" type="radio" :value="p.id">
              <span class="mono">{{ $td(p.id) }}</span> {{ $t('{a} · {b} · AI 建议分 {c}', { a: $td(p.status), b: timeOf(p.ts), c: p.score ?? '—' }) }}</label>
            <div class="line"><button class="btn primary" :disabled="!open.process" @click="sendLink({ process: open.process })">{{ $t('选定') }}</button>
              <button class="btn ghost" @click="open = null">{{ $t('取消') }}</button></div>
          </template>
          <template v-else-if="open.kind === 'change'">
            <b>{{ $t('工程更改申请：受影响的物料和文件') }}</b>
            <table class="t small">
              <thead><tr><th>{{ $t('物料或文件（编号、名称）') }}</th><th>{{ $t('改什么') }}</th><th>{{ $t('理由') }}</th><th></th></tr></thead>
              <tbody><tr v-for="(r, i) in open.rows" :key="i">
                <td><input v-model="r.item" maxlength="300"></td><td><input v-model="r.change" maxlength="300"></td>
                <td><input v-model="r.reason" maxlength="300"></td><td><a href="#" @click.prevent="open.rows.splice(i, 1)">{{ $t('删除') }}</a></td></tr></tbody>
            </table>
            <div class="line"><button class="btn ghost" @click="open.rows.push({ item: '', change: '', reason: '' })">{{ $t('加一行') }}</button>
              <button class="btn primary" @click="sendChange">{{ $t('保存') }}</button><button class="btn ghost" @click="open = null">{{ $t('取消') }}</button></div>
          </template>
        </div>

        <div class="line top">
          <button class="btn" :disabled="busy" @click="precheck">{{ $t('AI 预检') }}</button>
          <button v-if="editable" class="btn primary" :disabled="busy" @click="submit">{{ sub?.status === 'returned' ? $t('改好了，重新提交') : $t('提交审批') }}</button>
          <span class="small muted">{{ $t('预检随时可点，只给意见、不记录；提交后进“待老师审阅”，不能再改，退回后才能改。') }}</span>
        </div>
        <div v-if="pre" class="pre">
          <b>{{ $t('AI 预检：建议分 {a}', { a: $td(pre.suggested_score) }) }}</b>
          <div v-if="!pre.findings.length" class="small ok">{{ $t('没有发现问题。') }}</div>
          <div v-for="(f, i) in pre.findings" :key="i" class="small"><span class="pill" :class="f.level === 'error' ? 'bad' : f.level === 'warning' ? 'warn' : ''">{{ $td(LEVEL[f.level]) }}</span>
            {{ f.d !== null ? $t('〔') + task.deliverables[f.d].name[0] + $t('〕') : '' }}{{ $td(f.text) }}</div>
        </div>
        <div v-if="msg" class="small" :class="ok ? 'ok' : 'err'">{{ msg }}</div>
      </section>

      <section v-if="sub && sub.comments?.length && !teacher" class="card">
        <div class="card-head"><h2>{{ $t('评审意见') }}</h2><span class="muted small">{{ $t('{a} 条未关闭（老师看过你的回复后关闭）', { a: openCount }) }}</span></div>
        <div v-for="c in sub.comments" :key="c.id" class="cm" :class="{ done: c.resolved }">
          <div class="small"><span v-if="c.level" class="pill" :class="c.level === 'error' ? 'bad' : 'warn'">{{ $td(LEVEL[c.level]) }}</span>
            <b>{{ $td(c.author) }}</b> <span class="muted">· {{ timeOf(c.ts) }}{{ c.resolved ? $t(' · 已关闭') : '' }}</span></div>
          <div>{{ $td(c.body) }}</div>
          <div v-if="c.reply" class="reply small">{{ $t('我的回复：{a}', { a: $td(c.reply) }) }}</div>
          <form v-if="!c.resolved" class="line" @submit.prevent="reply(c)">
            <input v-model="replies[c.id]" maxlength="1000" :placeholder="$t('回复：改了什么，或为什么不改')">
            <button class="btn small" :disabled="!(replies[c.id] || '').trim()">{{ $t('回复') }}</button>
            <button type="button" class="btn ghost small" @click="replies[c.id] = '已改'; reply(c)">{{ $t('已改') }}</button><!-- i18n-ok 数据值比较 -->
          </form>
        </div>
      </section>

      <section v-if="sub?.inspection?.length" class="card">
        <div class="card-head"><h2>{{ $t('检验结果（仿真车间三坐标）') }}</h2></div>
        <table class="t small">
          <thead><tr><th>{{ $t('零件序号') }}</th><th>{{ $t('特性') }}</th><th class="num">{{ $t('名义') }}</th><th class="num">{{ $t('实测') }}</th><th>{{ $t('结论') }}</th></tr></thead>
          <tbody><tr v-for="(m, i) in sub.inspection" :key="i"><td class="mono">{{ $td(m.part_serial) }}</td><td>{{ $td(m.characteristic) }}</td>
            <td class="num">{{ $td(m.nominal_mm) }}</td><td class="num mono">{{ $td(m.value_mm) }}</td>
            <td><span class="pill" :class="m.result === 'pass' ? 'good' : 'bad'">{{ m.result === 'pass' ? $t('合格') : $t('不合格') }}</span></td></tr></tbody>
        </table>
      </section>

      <section v-if="sub?.plc_runs?.length" class="card">
        <div class="card-head"><h2>{{ $t('虚拟 PLC 试生产') }}</h2><router-link to="/plc" class="more">{{ $t('打开“虚拟 PLC”页看详情') }}</router-link></div>
        <table class="t small">
          <thead><tr><th>{{ $t('班次') }}</th><th>{{ $t('状态') }}</th><th class="num">{{ $t('产量') }}</th><th class="num">{{ $t('合格 / 不合格') }}</th><th class="num">{{ $t('平均节拍') }}</th><th class="num">{{ $t('报警') }}</th><th class="num">{{ $t('停机') }}</th><th>{{ $t('OpenPLC 兼容') }}</th></tr></thead>
          <tbody><tr v-for="r in sub.plc_runs" :key="r.id"><td class="mono">{{ $td(r.id) }}</td>
            <td>{{ { queued: $t('排队'), running: $t('运行中'), done: $t('班次完成'), failed: $t('失败'), cancelled: $t('已停止') }[r.status] }}{{ r.status === 'running' ? $t('（') + Math.round((r.live.progress || 0) * 100) + $t('%）') : '' }}</td>
            <td class="num">{{ r.summary ? r.summary.parts : r.live.n || 0 }}</td>
            <td class="num">{{ r.summary ? r.summary.good + ' / ' + r.summary.nok : (r.live.good_n || 0) + ' / ' + (r.live.nok_n || 0) }}</td>
            <td class="num">{{ r.summary?.cycle_mean_s ?? r.live.cycle_s ?? '—' }} s</td><td class="num">{{ $td(r.alarms.length) }}</td>
            <td class="num">{{ r.summary ? r.summary.downtime_min + $t(' 分') : '—' }}</td>
            <td>{{ !r.compat ? '—' : r.compat.ok ? $t('通过') : r.compat.stage === 'compile' ? $t('编译不过（看详情）') : $t('没做成') }}</td></tr></tbody>
        </table>
        <div v-for="r in sub.plc_runs.filter((x) => x.error)" :key="r.id + 'e'" class="err small">{{ $t('{a}：{b}', { a: $td(r.id), b: $td(r.error) }) }}</div>
      </section>

      <section v-if="sub?.score" class="card">
        <div class="card-head"><h2>{{ $t('成绩：{a} 分', { a: $td(sub.score.total) }) }}</h2></div>
        <table class="t small"><tbody><tr v-for="(x, i) in task.rubric" :key="i"><td>{{ x[$t('项')][0] }}</td><td class="num">{{ $td(sub.score.items[i]) }} / {{ x[$t('分')] }}</td></tr></tbody></table>
        <p v-if="sub.score.note" class="small">{{ $td(sub.score.note) }}</p>
      </section>

      <section class="card">
        <div class="card-head"><h2>{{ $t('步骤') }}</h2></div>
        <ol class="small"><li v-for="(s, i) in task.steps" :key="i">{{ $td(s[0]) }}</li></ol>
        <div class="card-head"><h2>{{ $t('评审要点') }}</h2></div>
        <ol class="small"><li v-for="(s, i) in task.review_points" :key="i">{{ $td(s[0]) }}</li></ol>
        <div class="card-head"><h2>{{ $t('评分量规') }}</h2></div>
        <table class="t small"><tbody><tr v-for="(x, i) in task.rubric" :key="i"><td>{{ x[$t('项')][0] }}</td><td class="num">{{ x[$t('分')] }}</td><td>{{ x[$t('标准')][0] }}</td></tr></tbody></table>
      </section>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { get, post, session } from '../lib/api';
import { timeOf } from '../lib/fmt';
import { LEVEL, STAGES, STATUS, TONE, stageIndex, upload } from '../lib/tasks';

const DOCS = { task: $t('任务单（Word）'), rubric: $t('评分量规（Word）'), calc: $t('空白计算书（Word）') };
const KIND = { 文件: $t('上传文件'), 设计发布: $t('设计发布（模型、图纸）'), 分析: $t('仿真与分析的作业'), 工艺规程: $t('工艺规程'), 更改单: $t('表单'), 'PLC 程序': $t('PLC 程序（批准后在虚拟 PLC 上跑一个班次）') };   // i18n-ok 数据值比较
const route = useRoute();
const task = ref(null);
const sub = ref(null);
const subs = ref([]);
const err = ref('');
const msg = ref('');
const ok = ref(true);
const busy = ref(false);
const pre = ref(null);
const open = ref(null);
const jobs = ref([]);
const procs = ref([]);
const replies = reactive({});
const teacher = computed(() => !!session.user?.teacher);
const editable = computed(() => !sub.value || ['draft', 'returned'].includes(sub.value.status));
const stage = computed(() => stageIndex(sub.value));
const openCount = computed(() => (sub.value?.comments || []).filter((c) => !c.resolved).length);
const left = computed(() => {
  if (!task.value?.due) return '';
  const d = (new Date(task.value.due) - Date.now()) / 86400000;
  return d >= 0 ? $t('还有 {a} 天', { a: Math.ceil(d) }) : $t('已过 {a} 天', { a: Math.ceil(-d) });
});
const tid = () => route.params.tid;
const got = (d) => sub.value?.deliverables?.[String(d.i)];

async function load() {
  try {
    const r = await get('/tasks/' + tid());
    task.value = r.task; sub.value = r.submission;
    if (teacher.value) subs.value = (await get(`/tasks/${tid()}/submissions`)).submissions;
  } catch (e) { err.value = e.message; }
}
function done(r, text) { sub.value = r; msg.value = text; ok.value = true; open.value = null; }
function fail(e) { msg.value = e.message; ok.value = false; }
async function sendFile(d, ev) {
  const f = ev.target.files[0]; ev.target.value = '';
  if (!f) return;
  busy.value = true;
  try { done(await upload(`/tasks/${tid()}/deliverables/${d.i}/file`, { file: f }), $t('已上传“{a}”', { a: d.name[0] })); } catch (e) { fail(e); } finally { busy.value = false; }
}
async function sendDesign() {
  busy.value = true;
  const o = open.value;
  try { done(await upload(`/tasks/${tid()}/deliverables/${o.d.i}/design`, { step: o.step, drawing: o.drawing, note: o.note || '' }), $t('模型已提交（待审）')); } catch (e) { fail(e); } finally { busy.value = false; }
}
async function pickJob(d) {
  try { jobs.value = ((await get('/cae/jobs')).jobs || []).filter((j) => j.status === 'done' && (!d.item || !j.item || j.item === d.item)); } catch (e) { jobs.value = []; }
  open.value = { d, kind: 'job', job: got(d)?.job || '' };
}
async function pickProcess(d) {
  try { procs.value = (await get('/process/' + encodeURIComponent(d.item))).submissions; } catch (e) { procs.value = []; }
  open.value = { d, kind: 'process', process: got(d)?.process || '' };
}
function editChange(d) {
  const rows = (got(d)?.rows || []).map((r) => ({ ...r }));
  open.value = { d, kind: 'change', rows: rows.length ? rows : [{ item: '', change: '', reason: '' }] };
}
async function sendLink(body) {
  try { done(await post(`/tasks/${tid()}/deliverables/${open.value.d.i}/link`, body), $t('已选定')); } catch (e) { fail(e); }
}
async function sendChange() {
  try { done(await post(`/tasks/${tid()}/deliverables/${open.value.d.i}/change`, { rows: open.value.rows }), $t('更改申请已保存')); } catch (e) { fail(e); }
}
async function precheck() {
  busy.value = true; msg.value = '';
  try { pre.value = await post(`/tasks/${tid()}/precheck`); } catch (e) { fail(e); } finally { busy.value = false; }
}
async function submit() {
  busy.value = true; msg.value = '';
  try {
    sub.value = await post(`/tasks/${tid()}/submit`);
    pre.value = null;
    const n = sub.value.comments.filter((c) => !c.resolved && c.level === 'error').length;
    done(sub.value, n ? $t('已提交。AI 评审员提了 {a} 条“必改”意见，逐条回复（改了什么，或为什么不改），等老师审阅。', { a: n }) : $t('已提交，等老师审阅。'));
  } catch (e) { fail(e); } finally { busy.value = false; }
}
async function reply(c) {
  try { sub.value = await post(`/task-submissions/${sub.value.id}/comments`, { reply_to: c.id, body: replies[c.id] }); replies[c.id] = ''; } catch (e) { fail(e); }
}
onMounted(load);
</script>

<style scoped>
.stages { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.stage { padding: 3px 10px; border-radius: 12px; background: var(--surface-2); font-size: 12px; color: var(--muted); }
.stage.done { background: #2e8b57; color: #fff; }
.stage.now { outline: 2px solid #2e8b57; color: var(--text); }
.act { white-space: nowrap; }
.btn.small { height: 26px; font-size: 12px; }
.pop { border: 1px solid var(--line); border-radius: 8px; padding: 10px; margin-top: 10px; display: flex; flex-direction: column; gap: 8px; background: var(--surface-2); }
.pop label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.pop label.opt { flex-direction: row; align-items: center; gap: 6px; }
.pop input:not([type=file]):not([type=radio]) { border: 1px solid var(--line); border-radius: 6px; padding: 4px 6px; font: inherit; width: 100%; }
.line { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.line.top { margin-top: 12px; }
.line input { flex: 1; min-width: 160px; border: 1px solid var(--line); border-radius: 6px; padding: 4px 8px; font: inherit; }
.pre { margin-top: 10px; background: var(--surface-2); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 4px; }
.cm { border-top: 1px solid var(--line-soft); padding: 8px 0; display: flex; flex-direction: column; gap: 4px; }
.cm.done > div:nth-child(2) { color: var(--muted); text-decoration: line-through; }
.reply { background: var(--surface-2); border-radius: 6px; padding: 4px 8px; }
.pill { margin-right: 4px; }
.ok { color: var(--good); } .err { color: var(--bad); }
</style>
