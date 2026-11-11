<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('审阅 ·') }} <span class="mono">{{ $td(s?.task.code) }}</span> · {{ $td(s?.name) }}</h1>
      <router-link v-if="s" :to="'/tasks/' + s.task.id" class="small">{{ $t('← 全部提交') }}</router-link></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="s" class="row">
      <section class="card grow">
        <div class="tabs">
          <button v-for="d in s.task.deliverables" :key="d.i" class="tab" :class="{ on: d.i === cur }" @click="cur = d.i">{{ d.i + 1 }} {{ $td(d.name[0]) }}</button>
        </div>
        <template v-if="dv">
          <p class="small muted">{{ $t('验收：{a}', { a: $td(dv.accept[0]) }) }}</p>
          <div v-if="!got" class="empty">{{ $t('学生没有交这一项。') }}</div>
          <template v-else-if="dv.kind === '文件'"><!-- i18n-ok 数据值比较 -->
            <p class="small"><a :href="got.files[0].url" target="_blank">{{ $t('下载 {a}', { a: $td(got.files[0].name) }) }}</a></p>
            <iframe v-if="got.files[0].name.toLowerCase().endsWith('.pdf')" :src="got.files[0].url" class="view" :title="$t('预览')"></iframe>
            <img v-else-if="/\.(png|jpe?g)$/i.test(got.files[0].name)" :src="got.files[0].url" class="view" :alt="$t('预览')">
            <p v-else class="small muted">{{ $t('Word、Excel 文件请下载后查看。') }}</p>
          </template>
          <template v-else-if="dv.kind === '设计发布'"><!-- i18n-ok 数据值比较 -->
            <p class="small">{{ $t('设计发布提交') }} <router-link :to="'/design/' + got.plm" class="mono">{{ $td(got.plm) }}</router-link>{{ $t('（看三维模型、与现行版的差异、图纸）；任务单批准时一并生效。') }}</p>
          </template>
          <template v-else-if="dv.kind === '分析'"><!-- i18n-ok 数据值比较 -->
            <p class="small">{{ $t('仿真与分析作业') }} <span class="mono">{{ $td(got.job) }}</span>{{ $t('（{a}，{b}）。', { a: $td(got.item), b: $td(got.status) }) }}
              <a :href="'/api/cae/jobs/' + got.job + '/report'" target="_blank" @click.prevent="report(got.job)">{{ $t('下载 Word 计算报告') }}</a> · <router-link to="/cae">{{ $t('打开仿真与分析') }}</router-link></p>
          </template>
          <template v-else-if="dv.kind === '工艺规程'"><!-- i18n-ok 数据值比较 -->
            <p class="small">{{ $t('工艺规程提交') }} <span class="mono">{{ $td(got.process) }}</span>{{ $t('；任务单批准时一并生效（ERPNext 新版 BOM、车间按新工艺派工）。') }}</p>
          </template>
          <template v-else-if="dv.kind === 'PLC 程序'"><!-- i18n-ok 数据值比较 -->
            <p class="small"><a :href="got.files[0].url" target="_blank">{{ $t('下载 {a}', { a: $td(got.files[0].name) }) }}</a> {{ $t('·{a}。批准后程序自动下载到数字工厂的', { a: got.check?.ok ? $t('编译通过') + (got.check.errors ? $t('，程序检查 ') + got.check.errors + $t(' 条错误') : $t('，程序检查没有错误')) : $t('编译不过：') + (got.check?.error || '') }) }}<router-link to="/plc">{{ $t('虚拟 PLC') }}</router-link>{{ $t('，控制{a}跑一个班次。', { a: { 'press-01': $t('压装工位'), 'sort-01': $t('分拣线') }[got.unit] || got.unit }) }}</p>
          </template>
          <template v-else-if="dv.kind === '更改单'"><!-- i18n-ok 数据值比较 -->
            <table class="t small"><thead><tr><th>{{ $t('物料或文件') }}</th><th>{{ $t('改什么') }}</th><th>{{ $t('理由') }}</th></tr></thead>
              <tbody><tr v-for="(r, i) in got.rows" :key="i"><td>{{ $td(r.item) }}</td><td>{{ $td(r.change) }}</td><td>{{ $td(r.reason) }}</td></tr></tbody></table>
            <p v-if="dv.must_list" class="small muted">{{ $t('任务单要求必列：{a}', { a: dv.must_list.join($t('、')) }) }}</p>
          </template>
        </template>
        <div class="card-head top"><h2>{{ $t('评审要点') }}</h2></div>
        <ol class="small"><li v-for="(p, i) in s.task.review_points" :key="i">{{ $td(p[0]) }}</li></ol>
        <template v-if="s.inspection?.length">
          <div class="card-head"><h2>{{ $t('检验结果（批准后）') }}</h2></div>
          <p class="small">{{ $t('{a} 条三坐标记录，{b} 条不合格。', { a: $td(s.inspection.length), b: s.inspection.filter((m) => m.result !== 'pass').length }) }}</p>
        </template>
      </section>

      <section class="card side">
        <div class="card-head"><h2>{{ $t('意见') }}</h2><span class="pill" :class="TONE[s.status]">{{ $td(s.status_zh) }}</span>
          <span class="muted small">{{ $t('第 {a} 轮 · {b} 条必改未关闭', { a: $td(s.rounds), b: openMust }) }}</span></div>
        <div v-for="c in s.comments" :key="c.id" class="cm" :class="{ done: c.resolved }">
          <div class="small"><span v-if="c.level" class="pill" :class="c.level === 'error' ? 'bad' : 'warn'">{{ $td(LEVEL[c.level]) }}</span>
            <b>{{ $td(c.author) }}</b> <span class="muted">· {{ timeOf(c.ts) }}</span></div>
          <div>{{ $td(c.body) }}</div>
          <div v-if="c.reply" class="reply small">{{ $t('学生：{a}', { a: $td(c.reply) }) }}</div>
          <button class="btn ghost small" @click="resolve(c)">{{ c.resolved ? $t('重新打开') : $t('关闭') }}</button>
        </div>
        <form class="add" @submit.prevent="addComment">
          <textarea v-model="body" rows="2" maxlength="2000" :placeholder="$t('老师意见')"></textarea>
          <div class="line"><select v-model="level"><option value="error">{{ $t('必改') }}</option><option value="warning">{{ $t('建议') }}</option><option value="">{{ $t('说明') }}</option></select>
            <button class="btn" :disabled="!body.trim()">{{ $t('添加') }}</button></div>
        </form>

        <template v-if="s.status === 'submitted'">
          <div class="card-head"><h2>{{ $t('结论') }}</h2></div>
          <textarea v-model="note" rows="2" maxlength="500" :placeholder="$t('审批意见（退回时必填）')"></textarea>
          <div class="line">
            <button class="btn primary" :disabled="openMust > 0" :title="openMust ? $t('必改意见全部关闭后才能批准') : ''" @click="decide('approve')">{{ $t('批准') }}</button>
            <button class="btn danger" @click="decide('return')">{{ $t('退回修改') }}</button>
          </div>
          <p class="small muted">{{ $t('批准时，任务里的设计发布、工艺规程一并生效：ERPNext 版本加一，之后可以下工单加工、检验。') }}</p>
        </template>

        <template v-if="['approved', 'graded'].includes(s.status)">
          <div class="card-head"><h2>{{ $t('评分') }}</h2><span class="muted small">{{ $t('AI 建议分 {a}', { a: s.review?.suggested_score ?? '—' }) }}</span></div>
          <table class="t small">
            <thead><tr><th>{{ $t('评分项') }}</th><th class="num">{{ $t('满分') }}</th><th class="num">{{ $t('AI 建议') }}</th><th class="num">{{ $t('老师') }}</th></tr></thead>
            <tbody><tr v-for="(x, i) in s.task.rubric" :key="i"><td>{{ x[$t('项')][0] }}</td><td class="num">{{ x[$t('分')] }}</td>
              <td class="num">{{ s.review?.suggested_items?.[i] ?? '—' }}</td>
              <td class="num"><input v-model.number="items[i]" type="number" min="0" :max="x['分']" step="0.5" class="score"></td></tr><!-- i18n-ok 数据值比较 -->
              <tr><td><b>{{ $t('合计') }}</b></td><td class="num">100</td><td class="num">{{ s.review?.suggested_score ?? '—' }}</td><td class="num"><b>{{ total }}</b></td></tr></tbody>
          </table>
          <textarea v-model="gradeNote" rows="2" maxlength="1000" :placeholder="$t('给学生的评语（随成绩写回课程）')"></textarea>
          <button class="btn primary" @click="grade">{{ s.status === 'graded' ? $t('改分') : $t('评分') }}</button>
          <p class="small muted">{{ $t('评分后在学习平台课程的“任务单”里点“成绩回传”，写进成绩簿。') }}</p>
        </template>
        <div v-if="msg" class="small" :class="ok ? 'ok' : 'err'">{{ msg }}</div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { get, post, session } from '../lib/api';
import { timeOf } from '../lib/fmt';
import { LEVEL, TONE } from '../lib/tasks';

const route = useRoute();
const s = ref(null);
const err = ref('');
const cur = ref(0);
const body = ref('');
const level = ref('error');
const note = ref('');
const gradeNote = ref('');
const items = ref([]);
const msg = ref('');
const ok = ref(true);
const dv = computed(() => s.value?.task.deliverables[cur.value]);
const got = computed(() => s.value?.deliverables?.[String(cur.value)]);
const openMust = computed(() => (s.value?.comments || []).filter((c) => !c.resolved && c.level === 'error').length);
const total = computed(() => items.value.reduce((a, b) => a + (Number(b) || 0), 0));

function take(r) {
  s.value = r;
  items.value = (r.score?.items || r.review?.suggested_items || r.task.rubric.map(() => 0)).slice();
  if (r.score?.note && !gradeNote.value) gradeNote.value = r.score.note;
}
async function load() { try { take(await get('/task-submissions/' + route.params.sid)); } catch (e) { err.value = e.message; } }
function fail(e) { ok.value = false; msg.value = e.message; }
async function addComment() {
  try { take(await post(`/task-submissions/${s.value.id}/comments`, { body: body.value, level: level.value })); body.value = ''; } catch (e) { fail(e); }
}
async function resolve(c) { try { take(await post(`/task-submissions/${s.value.id}/comments/${c.id}`, { resolved: !c.resolved })); } catch (e) { fail(e); } }
async function decide(d) {
  msg.value = '';
  try {
    take(await post(`/task-submissions/${s.value.id}/decision`, { decision: d, note: note.value }));
    ok.value = true; msg.value = d === 'approve' ? $t('已批准。') + (s.value.decision || '') : $t('已退回，学生修改后会重新提交。');
  } catch (e) { fail(e); }
}
async function grade() {
  msg.value = '';
  try { take(await post(`/task-submissions/${s.value.id}/grade`, { items: items.value, note: gradeNote.value })); ok.value = true; msg.value = $t('已评分：{a} 分', { a: s.value.score.total }); } catch (e) { fail(e); }
}
async function report(jid) {
  try {
    const r = await fetch(`/api/cae/jobs/${jid}/report`, { method: 'POST', headers: { 'x-wq-token': session.token } });
    if (!r.ok) throw new Error($t('报告生成失败（') + r.status + $t('）'));
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement('a'); a.href = url; a.download = $t('{a}-计算报告.docx', { a: jid }); a.click();
  } catch (e) { fail(e); }
}
onMounted(load);
</script>

<style scoped>
.grow { flex-grow: 1; min-width: 0; }
.side { width: 400px; flex-shrink: 0; display: flex; flex-direction: column; gap: 8px; }
.tabs { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 8px; }
.tab { border: 1px solid var(--line); background: var(--surface); border-radius: 6px; padding: 4px 10px; font: inherit; font-size: 13px; cursor: pointer; }
.tab.on { background: #2E3E4C; color: #fff; }
.view { width: 100%; height: 560px; border: 1px solid var(--line); border-radius: 8px; object-fit: contain; }
.cm { border-top: 1px solid var(--line-soft); padding: 8px 0; display: flex; flex-direction: column; gap: 4px; }
.cm.done > div:nth-child(2) { color: var(--muted); text-decoration: line-through; }
.reply { background: var(--surface-2); border-radius: 6px; padding: 4px 8px; }
.add, .side textarea { display: flex; flex-direction: column; gap: 6px; }
.side textarea { border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; font: inherit; }
.line { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.score { width: 64px; border: 1px solid var(--line); border-radius: 4px; padding: 2px 4px; text-align: right; }
.top { margin-top: 12px; }
.pill { margin-right: 4px; }
.btn.small { height: 26px; font-size: 12px; align-self: flex-start; }
.ok { color: var(--good); } .err { color: var(--bad); }
@media (max-width: 1100px) { .row { flex-direction: column; } .side { width: auto; } }
</style>
