<template>
  <!-- 工艺规程与 AI 评审（第 13 轮 8.8（3a））：下载参照工艺规程，上传自己改过的，AI 预检或提交审批，看意见、处理意见 -->
  <div class="page">
    <div class="page-title"><h1>{{ $t('工艺规程与 AI 评审') }}</h1>
      <span class="muted">{{ $t('工艺员工作区 · {a} 的工艺规程：AI 工艺评审员逐道工序检查基准、余量、切削用量、定位误差、夹具、精度、尺寸链', { a: (sid && sub && sub.item) || item }) }}</span></div>
    <div v-if="err" class="err">{{ err }}</div>

    <template v-if="!sid">
      <section v-if="HAS_REF[item]" class="card">
        <div class="card-head" data-help="pp-reference"><h2>{{ $t('参照工艺规程') }}</h2><span class="muted small">{{ $t('教材第 50 章的样例就是它；照着改，改完上传') }}</span></div>
        <div class="line">
          <label class="small">{{ $t('零件') }} <select v-model="item"><option v-for="i in ITEMS" :key="i" :value="i">{{ $td(i) }}</option></select></label>
          <button class="btn" @click="cards('/process/cards/reference/' + item)">{{ $t('看全套工艺文件') }}</button>
          <router-link class="btn primary" :to="'/process/edit/' + item">{{ $t('在页面上改工艺卡') }}</router-link>
          <button class="btn ghost" @click="downloadRef">{{ $t('下载 YAML') }}</button>
          <span class="small muted">{{ $t('当前生效：{a}', { a: info?.revision ? $t('第 ') + info.revision + $t(' 版') : $t('参照工艺规程（还没有批准过学生的版本）') }) }}</span>
        </div>
      </section>
      <section v-else class="card">
        <div class="card-head" data-help="pp-part"><h2>{{ $t('零件图要求') }}</h2><span class="muted small">{{ $t('按图纸要求自己拟定工艺路线（教材第 56 章；全套工艺规程的写法见第 57 章），AI 预检按图纸核对') }}</span></div>
        <div class="line">
          <label class="small">{{ $t('零件') }} <select v-model="item"><option v-for="i in ITEMS" :key="i" :value="i">{{ $td(i) }}</option></select></label>
          <button class="btn ghost" @click="downloadPart">{{ $t('下载零件图要求（YAML）') }}</button>
          <button class="btn ghost" @click="downloadStart">{{ $t('下载工厂现行工序（起点）') }}</button>
          <span class="small muted">{{ $t('当前生效：{a}', { a: info?.revision ? $t('第 ') + info.revision + $t(' 版') : $t('工厂现行工艺（还没有批准过学生的版本）') }) }}</span>
        </div>
      </section>

      <section class="card">
        <div class="card-head" data-help="pp-upload"><h2>{{ $t('上传工艺规程') }}</h2><span class="muted small">{{ $t('YAML 文件，格式同参照工艺规程') }}</span></div>
        <div class="line">
          <label class="btn">{{ $t('选择文件') }}<input type="file" accept=".yaml,.yml" hidden @change="pick"></label>
          <span class="small">{{ fileName || $t('未选文件') }}</span>
          <button class="btn" :disabled="!text || busy" @click="check(false)">{{ $t('AI 预检（不提交）') }}</button>
          <button class="btn primary" :disabled="!text || busy" @click="check(true)">{{ $t('提交审批') }}</button>
          <input v-model="note" class="note" maxlength="300" :placeholder="$t('改动说明（提交时一并记录）')">
        </div>
        <p class="small muted">{{ $t('预检随时可点，只给意见、不记录；提交后 AI 评审员的意见写成批注，进“待审”，老师或审批人批准后成为新版本。') }}</p>
        <div v-if="pre" class="result">
          <div class="score">{{ $t('AI 预检 · 建议分') }} <b>{{ $td(pre.suggested_score) }}</b>
            <span class="pill bad">{{ $t('{a} 必须改', { a: count(pre.findings, 'error') }) }}</span>
            <span class="pill warn">{{ $t('{a} 建议', { a: count(pre.findings, 'warning') }) }}</span></div>
          <Findings :list="pre.findings" />
        </div>
      </section>

      <section class="card">
        <div class="card-head"><h2>{{ $t('提交记录') }}</h2><span class="muted small">{{ $t('点编号看详情') }}</span></div>
        <div v-if="!info?.submissions?.length" class="empty">{{ $t('还没有提交。') }}</div>
        <table v-else class="t">
          <thead><tr><th>{{ $t('编号') }}</th><th>{{ $t('状态') }}</th><th>{{ $t('提交人') }}</th><th>{{ $t('时间') }}</th><th class="num">{{ $t('AI 建议分') }}</th></tr></thead>
          <tbody><tr v-for="s in info.submissions" :key="s.id">
            <td><router-link class="mono" :to="'/process/' + s.id">{{ $td(s.id) }}</router-link></td>
            <td><span class="pill" :class="TONE[s.status]">{{ STATUS[s.status] || s.status }}</span></td>
            <td>{{ $td(s.author) }}</td><td class="small">{{ timeOf(s.ts) }}</td><td class="num">{{ s.score ?? '—' }}</td></tr></tbody>
        </table>
      </section>
    </template>

    <template v-else-if="sub">
      <section class="card">
        <div class="card-head"><h2>{{ $t('提交') }} <span class="mono">{{ $td(sub.id) }}</span> · {{ $td(sub.item) }}</h2>
          <span class="pill" :class="TONE[sub.status]">{{ STATUS[sub.status] || sub.status }}</span>
          <router-link to="/process" class="small">{{ $t('← 工艺规程') }}</router-link></div>
        <p class="small">{{ $t('提交人 {a} · {b}', { a: $td(sub.author), b: timeOf(sub.ts) }) }}<template v-if="sub.note"> {{ $t('· 说明：{a}', { a: $td(sub.note) }) }}</template>
          <template v-if="sub.revision"> {{ $t('· 已生效为第 {a} 版', { a: $td(sub.revision) }) }}</template></p>
        <div class="line"><button class="btn" @click="cards('/process/submissions/' + sub.id + '/cards')">{{ $t('看这份的全套工艺文件') }}</button>
          <router-link v-if="sub.plan?.doc" class="btn" :to="{ path: '/process/edit/' + sub.item, query: { start: sub.id } }">{{ $t('在这一份上改') }}</router-link></div>
        <div class="result">
          <div class="score">{{ $t('{a} · 建议分', { a: sub.review?.by || $t('AI 工艺评审员') }) }} <b>{{ sub.review?.suggested_score ?? '—' }}</b>
            <span class="pill bad">{{ $t('{a} 必须改', { a: count(sub.review?.findings, 'error') }) }}</span>
            <span class="pill warn">{{ $t('{a} 建议', { a: count(sub.review?.findings, 'warning') }) }}</span></div>
          <Findings :list="sub.review?.findings || []" />
        </div>
      </section>
      <section class="card">
        <div class="card-head"><h2>{{ $t('批注') }}</h2><span class="muted small">{{ $t('{a} 条未处理', { a: open }) }}</span></div>
        <div v-if="!sub.comments?.length" class="empty">{{ $t('没有批注。') }}</div>
        <div v-for="c in sub.comments" :key="c.id" class="cm" :class="{ done: c.resolved }">
          <label class="small"><input type="checkbox" :checked="c.resolved" :disabled="sub.status !== 'pending'" @change="resolve(c, $event.target.checked)"> {{ $t('已处理') }}</label>
          <span class="small">{{ $td(c.body) }}</span> <span class="small muted">— {{ $td(c.author) }}</span>
        </div>
        <div v-if="sub.status === 'pending' && session.user?.teacher" class="line top">
          <input v-model="note" class="note" maxlength="300" :placeholder="$t('审批意见')">
          <button class="btn primary" :disabled="busy" @click="decide('approve')">{{ $t('批准') }}</button>
          <button class="btn" :disabled="busy" @click="decide('reject')">{{ $t('退回') }}</button>
        </div>
      </section>
    </template>
    <div v-if="msg" class="small" :class="ok ? 'ok' : 'err'">{{ msg }}</div>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, defineComponent, h, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { get, post, session } from '../lib/api';

const ITEMS = ['SH-301', 'SH-101'];
const HAS_REF = { 'SH-301': true };   // SH-101 网页上只给零件图要求（第 13 轮十二），路线由学生拟定；std/SH-101_process.yaml（第 57 章）可经接口下载
const STATUS = { pending: $t('待审'), approved: $t('已批准'), rejected: $t('已退回') };
const TONE = { pending: 'warn', approved: 'ok', rejected: 'bad' };
const LEVEL = { error: $t('必须改'), warning: $t('建议'), info: $t('说明') };

// 意见表：级别、规则、工序、意见
const Findings = defineComponent({
  props: { list: { type: Array, default: () => [] } },
  setup(props) {
    return () => (!props.list.length ? h('div', { class: 'small ok' }, $t('没有发现问题。'))
      : h('table', { class: 't small' }, [
        h('thead', h('tr', [$t('级别'), $t('规则'), $t('工序'), $t('意见')].map((x) => h('th', x)))),
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
    if (submit) { msg.value = $t('已提交：') + r.id; ok.value = true; pre.value = r.review; await load(); }
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
function save(name, body) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([body], { type: 'text/yaml' }));
  a.download = name; a.click();
}
async function downloadPart() {
  try { save(item.value + '_part.yaml', (await get('/process/part/' + item.value)).yaml); } catch (e) { err.value = e.message; }
}
function downloadStart() {
  const p = info.value?.factory_plan;
  if (!p) { err.value = $t('这个零件没有工厂现行工艺'); return; }
  const lines = ['# ' + item.value + $t(' 的工厂现行工序（起点）：补毛坯、基准、各道的工序尺寸与粗糙度、热处理与辅助工序（aux），见教材第 56 章'),
    'item: ' + p.item, 'blank: {kind: "", spec: ""}', 'operations:'];
  for (const o of p.operations) {
    lines.push('  - seq: ' + o.seq, '    operation: ' + o.operation, '    workstation: ' + o.workstation, '    content: ""', '    datum: ""',
      '    minutes: ' + o.minutes, '    setup_min: 0', '    features: []');
  }
  save(item.value + '_process.yaml', lines.join('\n') + '\n');
}
async function cards(path) {
  try {
    const r = await fetch('/api' + path + (path.includes('?') ? '&' : '?') + 'fmt=html', { headers: { 'x-wq-token': session.token || '' } });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || $t('生成卡片失败'));
    window.open(URL.createObjectURL(new Blob([await r.text()], { type: 'text/html' })), '_blank');
  } catch (e) { err.value = e.message; }
}
async function resolve(c, v) {
  try { sub.value = await post(`/process/submissions/${sub.value.id}/comments/${c.id}`, { resolved: v }); } catch (e) { err.value = e.message; }
}
async function decide(d) {
  busy.value = true;
  try { sub.value = await post(`/process/submissions/${sub.value.id}/decision`, { decision: d, note: note.value }); msg.value = d === 'approve' ? $t('已批准') : $t('已退回'); ok.value = true; }
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
