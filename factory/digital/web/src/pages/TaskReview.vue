<template>
  <div class="page">
    <div class="page-title"><h1>审阅 · <span class="mono">{{ s?.task.code }}</span> · {{ s?.name }}</h1>
      <router-link v-if="s" :to="'/tasks/' + s.task.id" class="small">← 全部提交</router-link></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="s" class="row">
      <section class="card grow">
        <div class="tabs">
          <button v-for="d in s.task.deliverables" :key="d.i" class="tab" :class="{ on: d.i === cur }" @click="cur = d.i">{{ d.i + 1 }} {{ d.name[0] }}</button>
        </div>
        <template v-if="dv">
          <p class="small muted">验收：{{ dv.accept[0] }}</p>
          <div v-if="!got" class="empty">学生没有交这一项。</div>
          <template v-else-if="dv.kind === '文件'">
            <p class="small"><a :href="got.files[0].url" target="_blank">下载 {{ got.files[0].name }}</a></p>
            <iframe v-if="got.files[0].name.toLowerCase().endsWith('.pdf')" :src="got.files[0].url" class="view" title="预览"></iframe>
            <img v-else-if="/\.(png|jpe?g)$/i.test(got.files[0].name)" :src="got.files[0].url" class="view" alt="预览">
            <p v-else class="small muted">Word、Excel 文件请下载后查看。</p>
          </template>
          <template v-else-if="dv.kind === '设计发布'">
            <p class="small">设计发布提交 <router-link :to="'/design/' + got.plm" class="mono">{{ got.plm }}</router-link>（看三维模型、与现行版的差异、图纸）；任务单批准时一并生效。</p>
          </template>
          <template v-else-if="dv.kind === '分析'">
            <p class="small">仿真与分析作业 <span class="mono">{{ got.job }}</span>（{{ got.item }}，{{ got.status }}）。
              <a :href="'/api/cae/jobs/' + got.job + '/report'" target="_blank" @click.prevent="report(got.job)">下载 Word 计算报告</a> · <router-link to="/cae">打开仿真与分析</router-link></p>
          </template>
          <template v-else-if="dv.kind === '工艺规程'">
            <p class="small">工艺规程提交 <span class="mono">{{ got.process }}</span>；任务单批准时一并生效（ERPNext 新版 BOM、车间按新工艺派工）。</p>
          </template>
          <template v-else-if="dv.kind === 'PLC 程序'">
            <p class="small"><a :href="got.files[0].url" target="_blank">下载 {{ got.files[0].name }}</a> ·
              {{ got.check?.ok ? '编译通过' + (got.check.errors ? '，程序检查 ' + got.check.errors + ' 条错误' : '，程序检查没有错误') : '编译不过：' + (got.check?.error || '') }}。
              批准后程序自动下载到数字工厂的<router-link to="/plc">虚拟 PLC</router-link>，控制{{ { 'press-01': '压装工位', 'sort-01': '分拣线' }[got.unit] || got.unit }}跑一个班次。</p>
          </template>
          <template v-else-if="dv.kind === '更改单'">
            <table class="t small"><thead><tr><th>物料或文件</th><th>改什么</th><th>理由</th></tr></thead>
              <tbody><tr v-for="(r, i) in got.rows" :key="i"><td>{{ r.item }}</td><td>{{ r.change }}</td><td>{{ r.reason }}</td></tr></tbody></table>
            <p v-if="dv.must_list" class="small muted">任务单要求必列：{{ dv.must_list.join('、') }}</p>
          </template>
        </template>
        <div class="card-head top"><h2>评审要点</h2></div>
        <ol class="small"><li v-for="(p, i) in s.task.review_points" :key="i">{{ p[0] }}</li></ol>
        <template v-if="s.inspection?.length">
          <div class="card-head"><h2>检验结果（批准后）</h2></div>
          <p class="small">{{ s.inspection.length }} 条三坐标记录，{{ s.inspection.filter((m) => m.result !== 'pass').length }} 条不合格。</p>
        </template>
      </section>

      <section class="card side">
        <div class="card-head"><h2>意见</h2><span class="pill" :class="TONE[s.status]">{{ s.status_zh }}</span>
          <span class="muted small">第 {{ s.rounds }} 轮 · {{ openMust }} 条必改未关闭</span></div>
        <div v-for="c in s.comments" :key="c.id" class="cm" :class="{ done: c.resolved }">
          <div class="small"><span v-if="c.level" class="pill" :class="c.level === 'error' ? 'bad' : 'warn'">{{ LEVEL[c.level] }}</span>
            <b>{{ c.author }}</b> <span class="muted">· {{ timeOf(c.ts) }}</span></div>
          <div>{{ c.body }}</div>
          <div v-if="c.reply" class="reply small">学生：{{ c.reply }}</div>
          <button class="btn ghost small" @click="resolve(c)">{{ c.resolved ? '重新打开' : '关闭' }}</button>
        </div>
        <form class="add" @submit.prevent="addComment">
          <textarea v-model="body" rows="2" maxlength="2000" placeholder="老师意见"></textarea>
          <div class="line"><select v-model="level"><option value="error">必改</option><option value="warning">建议</option><option value="">说明</option></select>
            <button class="btn" :disabled="!body.trim()">添加</button></div>
        </form>

        <template v-if="s.status === 'submitted'">
          <div class="card-head"><h2>结论</h2></div>
          <textarea v-model="note" rows="2" maxlength="500" placeholder="审批意见（退回时必填）"></textarea>
          <div class="line">
            <button class="btn primary" :disabled="openMust > 0" :title="openMust ? '必改意见全部关闭后才能批准' : ''" @click="decide('approve')">批准</button>
            <button class="btn danger" @click="decide('return')">退回修改</button>
          </div>
          <p class="small muted">批准时，任务里的设计发布、工艺规程一并生效：ERPNext 版本加一，之后可以下工单加工、检验。</p>
        </template>

        <template v-if="['approved', 'graded'].includes(s.status)">
          <div class="card-head"><h2>评分</h2><span class="muted small">AI 建议分 {{ s.review?.suggested_score ?? '—' }}</span></div>
          <table class="t small">
            <thead><tr><th>评分项</th><th class="num">满分</th><th class="num">AI 建议</th><th class="num">老师</th></tr></thead>
            <tbody><tr v-for="(x, i) in s.task.rubric" :key="i"><td>{{ x['项'][0] }}</td><td class="num">{{ x['分'] }}</td>
              <td class="num">{{ s.review?.suggested_items?.[i] ?? '—' }}</td>
              <td class="num"><input v-model.number="items[i]" type="number" min="0" :max="x['分']" step="0.5" class="score"></td></tr>
              <tr><td><b>合计</b></td><td class="num">100</td><td class="num">{{ s.review?.suggested_score ?? '—' }}</td><td class="num"><b>{{ total }}</b></td></tr></tbody>
          </table>
          <textarea v-model="gradeNote" rows="2" maxlength="1000" placeholder="给学生的评语（随成绩写回课程）"></textarea>
          <button class="btn primary" @click="grade">{{ s.status === 'graded' ? '改分' : '评分' }}</button>
          <p class="small muted">评分后在学习平台课程的“任务单”里点“成绩回传”，写进成绩簿。</p>
        </template>
        <div v-if="msg" class="small" :class="ok ? 'ok' : 'err'">{{ msg }}</div>
      </section>
    </div>
  </div>
</template>

<script setup>
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
    ok.value = true; msg.value = d === 'approve' ? '已批准。' + (s.value.decision || '') : '已退回，学生修改后会重新提交。';
  } catch (e) { fail(e); }
}
async function grade() {
  msg.value = '';
  try { take(await post(`/task-submissions/${s.value.id}/grade`, { items: items.value, note: gradeNote.value })); ok.value = true; msg.value = `已评分：${s.value.score.total} 分`; } catch (e) { fail(e); }
}
async function report(jid) {
  try {
    const r = await fetch(`/api/cae/jobs/${jid}/report`, { method: 'POST', headers: { 'x-wq-token': session.token } });
    if (!r.ok) throw new Error('报告生成失败（' + r.status + '）');
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement('a'); a.href = url; a.download = `${jid}-计算报告.docx`; a.click();
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
