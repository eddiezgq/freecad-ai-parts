<template>
  <!-- 工艺规程与 AI 评审（第 13 轮 8.8（3a））：下载参照工艺规程，上传自己改过的，AI 预检或提交审批，看意见、处理意见 -->
  <div class="page">
    <div class="page-title"><h1>工艺规程与 AI 评审</h1>
      <span class="muted">工艺员工作区 · {{ item }} 的工艺规程：AI 工艺评审员逐道工序检查基准、余量、切削用量、定位误差、夹具、精度、尺寸链</span></div>
    <div v-if="err" class="err">{{ err }}</div>

    <template v-if="!sid">
      <section class="card">
        <div class="card-head" data-help="pp-reference"><h2>参照工艺规程</h2><span class="muted small">教材第 50 章的样例就是它；照着改，改完上传</span></div>
        <div class="line">
          <label class="small">零件 <select v-model="item"><option v-for="i in ITEMS" :key="i" :value="i">{{ i }}</option></select></label>
          <button class="btn" @click="cards('/process/cards/reference/' + item)">看全套工艺文件</button>
          <button class="btn ghost" @click="downloadRef">下载 YAML</button>
          <span class="small muted">当前生效：{{ info?.revision ? '第 ' + info.revision + ' 版' : '参照工艺规程（还没有批准过学生的版本）' }}</span>
        </div>
      </section>

      <section class="card">
        <div class="card-head" data-help="pp-upload"><h2>上传工艺规程</h2><span class="muted small">YAML 文件，格式同参照工艺规程</span></div>
        <div class="line">
          <label class="btn">选择文件<input type="file" accept=".yaml,.yml" hidden @change="pick"></label>
          <span class="small">{{ fileName || '未选文件' }}</span>
          <button class="btn" :disabled="!text || busy" @click="check(false)">AI 预检（不提交）</button>
          <button class="btn primary" :disabled="!text || busy" @click="check(true)">提交审批</button>
          <input v-model="note" class="note" maxlength="300" placeholder="改动说明（提交时一并记录）">
        </div>
        <p class="small muted">预检随时可点，只给意见、不记录；提交后 AI 评审员的意见写成批注，进“待审”，老师或审批人批准后成为新版本。</p>
        <div v-if="pre" class="result">
          <div class="score">AI 预检 · 建议分 <b>{{ pre.suggested_score }}</b>
            <span class="pill bad">{{ count(pre.findings, 'error') }} 必须改</span>
            <span class="pill warn">{{ count(pre.findings, 'warning') }} 建议</span></div>
          <Findings :list="pre.findings" />
        </div>
      </section>

      <section class="card">
        <div class="card-head"><h2>提交记录</h2><span class="muted small">点编号看详情</span></div>
        <div v-if="!info?.submissions?.length" class="empty">还没有提交。</div>
        <table v-else class="t">
          <thead><tr><th>编号</th><th>状态</th><th>提交人</th><th>时间</th><th class="num">AI 建议分</th></tr></thead>
          <tbody><tr v-for="s in info.submissions" :key="s.id">
            <td><router-link class="mono" :to="'/process/' + s.id">{{ s.id }}</router-link></td>
            <td><span class="pill" :class="TONE[s.status]">{{ STATUS[s.status] || s.status }}</span></td>
            <td>{{ s.author }}</td><td class="small">{{ timeOf(s.ts) }}</td><td class="num">{{ s.score ?? '—' }}</td></tr></tbody>
        </table>
      </section>
    </template>

    <template v-else-if="sub">
      <section class="card">
        <div class="card-head"><h2>提交 <span class="mono">{{ sub.id }}</span> · {{ sub.item }}</h2>
          <span class="pill" :class="TONE[sub.status]">{{ STATUS[sub.status] || sub.status }}</span>
          <router-link to="/process" class="small">← 工艺规程</router-link></div>
        <p class="small">提交人 {{ sub.author }} · {{ timeOf(sub.ts) }}<template v-if="sub.note"> · 说明：{{ sub.note }}</template>
          <template v-if="sub.revision"> · 已生效为第 {{ sub.revision }} 版</template></p>
        <div class="line"><button class="btn" @click="cards('/process/submissions/' + sub.id + '/cards')">看这份的全套工艺文件</button></div>
        <div class="result">
          <div class="score">{{ sub.review?.by || 'AI 工艺评审员' }} · 建议分 <b>{{ sub.review?.suggested_score ?? '—' }}</b>
            <span class="pill bad">{{ count(sub.review?.findings, 'error') }} 必须改</span>
            <span class="pill warn">{{ count(sub.review?.findings, 'warning') }} 建议</span></div>
          <Findings :list="sub.review?.findings || []" />
        </div>
      </section>
      <section class="card">
        <div class="card-head"><h2>批注</h2><span class="muted small">{{ open }} 条未处理</span></div>
        <div v-if="!sub.comments?.length" class="empty">没有批注。</div>
        <div v-for="c in sub.comments" :key="c.id" class="cm" :class="{ done: c.resolved }">
          <label class="small"><input type="checkbox" :checked="c.resolved" :disabled="sub.status !== 'pending'" @change="resolve(c, $event.target.checked)"> 已处理</label>
          <span class="small">{{ c.body }}</span> <span class="small muted">— {{ c.author }}</span>
        </div>
        <div v-if="sub.status === 'pending' && session.user?.teacher" class="line top">
          <input v-model="note" class="note" maxlength="300" placeholder="审批意见">
          <button class="btn primary" :disabled="busy" @click="decide('approve')">批准</button>
          <button class="btn" :disabled="busy" @click="decide('reject')">退回</button>
        </div>
      </section>
    </template>
    <div v-if="msg" class="small" :class="ok ? 'ok' : 'err'">{{ msg }}</div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { get, post, session } from '../lib/api';

const ITEMS = ['SH-301'];
const STATUS = { pending: '待审', approved: '已批准', rejected: '已退回' };
const TONE = { pending: 'warn', approved: 'ok', rejected: 'bad' };
const LEVEL = { error: '必须改', warning: '建议', info: '说明' };

// 意见表：级别、规则、工序、意见
const Findings = defineComponent({
  props: { list: { type: Array, default: () => [] } },
  setup(props) {
    return () => (!props.list.length ? h('div', { class: 'small ok' }, '没有发现问题。')
      : h('table', { class: 't small' }, [
        h('thead', h('tr', ['级别', '规则', '工序', '意见'].map((x) => h('th', x)))),
        h('tbody', props.list.map((f) => h('tr', [
          h('td', h('span', { class: 'pill ' + (f.level === 'error' ? 'bad' : f.level === 'warning' ? 'warn' : '') }, LEVEL[f.level] || f.level)),
          h('td', f.rule), h('td', { class: 'num' }, f.seq ?? '—'), h('td', f.text)]))),
      ]));
  },
});

const route = useRoute();
const sid = computed(() => route.params.sid);
const item = ref('SH-301');
const info = ref(null);
const sub = ref(null);
const text = ref('');
const fileName = ref('');
const note = ref('');
const pre = ref(null);
const err = ref('');
const msg = ref('');
const ok = ref(true);
const busy = ref(false);
const open = computed(() => (sub.value?.comments || []).filter((c) => !c.resolved).length);
const count = (l, lv) => (l || []).filter((f) => f.level === lv).length;
const timeOf = (t) => (t ? new Date(t).toLocaleString('zh-CN', { hour12: false }) : '');

async function load() {
  err.value = '';
  try {
    if (sid.value) sub.value = await get('/process/submissions/' + sid.value);
    else info.value = await get('/process/' + encodeURIComponent(item.value));
  } catch (e) { err.value = e.message; }
}
function pick(ev) {
  const f = ev.target.files[0]; ev.target.value = '';
  if (!f) return;
  fileName.value = f.name; pre.value = null;
  f.text().then((t) => { text.value = t; });
}
async function check(submit) {
  busy.value = true; msg.value = '';
  try {
    const r = await post('/process/check', { yaml: text.value, submit, note: note.value });
    if (submit) { msg.value = '已提交：' + r.id; ok.value = true; pre.value = r.review; await load(); }
    else pre.value = r;
  } catch (e) { msg.value = e.message; ok.value = false; } finally { busy.value = false; }
}
async function downloadRef() {
  try {
    const r = await get('/process/reference/' + item.value);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([r.yaml], { type: 'text/yaml' }));
    a.download = item.value + '_process.yaml'; a.click();
  } catch (e) { err.value = e.message; }
}
async function cards(path) {
  try {
    const r = await fetch('/api' + path + (path.includes('?') ? '&' : '?') + 'fmt=html', { headers: { 'x-wq-token': session.token || '' } });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || '生成卡片失败');
    window.open(URL.createObjectURL(new Blob([await r.text()], { type: 'text/html' })), '_blank');
  } catch (e) { err.value = e.message; }
}
async function resolve(c, v) {
  try { sub.value = await post(`/process/submissions/${sub.value.id}/comments/${c.id}`, { resolved: v }); } catch (e) { err.value = e.message; }
}
async function decide(d) {
  busy.value = true;
  try { sub.value = await post(`/process/submissions/${sub.value.id}/decision`, { decision: d, note: note.value }); msg.value = d === 'approve' ? '已批准' : '已退回'; ok.value = true; }
  catch (e) { msg.value = e.message; ok.value = false; } finally { busy.value = false; }
}
watch([sid, item], load);
onMounted(load);
</script>

<style scoped>
.line { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.line.top { margin-top: 10px; }
.note { flex: 1; min-width: 200px; }
.result { margin-top: 12px; }
.score { margin-bottom: 8px; display: flex; gap: 8px; align-items: center; }
.cm { padding: 6px 0; border-bottom: 1px solid var(--line, #e3e6e8); display: flex; gap: 8px; align-items: baseline; }
.cm.done { opacity: 0.55; }
td.num { text-align: right; }
:deep(table.t th), :deep(table.t td:nth-child(-n+3)) { white-space: nowrap; }
</style>
