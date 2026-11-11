<!-- AI 运行记录与评测（第 17 轮 D 期 D3、D4）：每次提问都存档，可逐步回放；评测集的分数 -->
<template>
  <div class="page">
    <div class="page-title"><h1><router-link to="/ont" class="back">{{ $t('厂情中枢') }}</router-link> {{ $t('/ AI 运行记录') }}</h1>
      <span class="muted">{{ $t('AI 代理每次运行都存档：问了什么、调了哪些工具、引用了什么、数字核对是否通过') }}</span>
      <span class="tabs"><button :class="{ on: tab === 'runs' }" @click="tab = 'runs'">{{ $t('运行记录') }}</button>
        <button v-if="boss" :class="{ on: tab === 'evals' }" @click="tab = 'evals'; loadEvals()">{{ $t('评测') }}</button></span></div>
    <div v-if="err" class="err">{{ err }}</div>

    <template v-if="tab === 'runs'">
      <div class="filters small">
        <label v-if="boss"><input v-model="f.mine" type="checkbox" @change="load"> {{ $t('只看我的') }}</label>
        <label><input v-model="f.bad" type="checkbox" @change="load"> {{ $t('只看 👎 或数字未核实') }}</label>
        <select v-model="f.kind" @change="load"><option value="">{{ $t('全部种类') }}</option><option value="chat">{{ $t('聊天') }}</option>
          <option value="analyze">{{ $t('让 AI 分析') }}</option><option value="report">{{ $t('报告') }}</option><option value="eval">{{ $t('评测') }}</option></select>
        <span class="muted">{{ $t('引擎：{a}', { a: engine === 'rules' ? $t('规则版（没配模型）') : engine }) }}</span>
        <span v-if="boss && ai" class="small" data-help="ai-model">{{ $t('模型') }}
          <select v-model="ai.setting" @change="setAi">
            <option value="auto">{{ $t('自动（{a}）', { a: ai.region === 'cn' ? $t('国内 → DeepSeek') : $t('国外 → Claude') }) }}</option>
            <option value="claude" :disabled="ai.region === 'cn'">Claude{{ ai.region === 'cn' ? $t('（国内部署不用）') : ai.configured.claude ? '' : $t('（没配密钥）') }}</option>
            <option value="deepseek">DeepSeek{{ ai.configured.deepseek ? '' : $t('（没配密钥）') }}</option>
          </select>
          <span class="muted">{{ $t('现在用 {a}', { a: ai.name === 'rules' ? $t('规则版') : ai.name }) }}<template v-if="ai.last">{{ $t('；上次 {a} {b}{c}', { a: $td(ai.last.provider), b: ai.last.ok ? $t('成功') : $t('出错'), c: ai.last.fallback_from ? $t('（') + ai.last.fallback_from + $t(' 出错后换的）') : '' }) }}</template></span>
        </span>
      </div>
      <div class="grid">
        <div class="card list">
          <p v-if="!runs.length" class="muted small">{{ $t('还没有运行记录。') }}</p>
          <button v-for="r in runs" :key="r.id" class="row" :class="{ on: sel?.id === r.id }" @click="open(r.id)">
            <span class="mono small">AI-{{ String(r.id).padStart(5, '0') }}</span>
            <span class="q">{{ $td(r.question) }}</span>
            <span class="small muted">{{ $t('{a} · {b} · {c} 步 · {d} ms', { a: $td(r.user), b: fmtTs(r.created_at), c: $td(r.nsteps), d: $td(r.duration_ms) }) }}</span>
            <span class="tags"><span v-if="r.ok === false" class="pill warn">{{ $t('数字未核实') }}</span><span v-if="r.feedback === 1" class="pill good">👍</span>
              <span v-if="r.feedback === -1" class="pill bad">👎</span><span class="pill mute">{{ r.engine === 'rules' ? $t('规则版') : r.engine }}</span></span>
          </button>
        </div>
        <div v-if="sel" class="card detail">
          <h2>{{ $t('AI-{a}：{b}', { a: String(sel.id).padStart(5, '0'), b: $td(sel.question) }) }}</h2>
          <p class="small muted">{{ $t('{a}（{b}）· {c} · {d} · {e} · {f} ms', { a: $td(sel.user), b: $td(sel.role), c: fmtTs(sel.created_at), d: $td(sel.kind), e: $td(sel.engine), f: $td(sel.duration_ms) }) }}
            <template v-if="sel.feedback_text"> {{ $t('· 意见：{a}', { a: $td(sel.feedback_text) }) }}</template></p>
          <h3>{{ $t('回答') }}</h3>
          <pre class="ans">{{ $td(sel.answer) }}</pre>
          <div v-if="sel.check && !sel.check.ok" class="warnbox small">
            <b>{{ $t('数字核对没通过：') }}</b>
            <div v-for="(x, i) in sel.check.unverified" :key="i">{{ $t('“{a}” 里的 {b}', { a: $td(x.sentence), b: x.numbers.join($t('、')) }) }}</div>
            <div v-if="sel.check.bad_refs?.length">{{ $t('无效引用：{a}', { a: sel.check.bad_refs.join($t('、')) }) }}</div>
          </div>
          <h3>{{ $t('步骤（{a}）', { a: $td(sel.steps.length) }) }}</h3>
          <ol class="steps small">
            <li v-for="(s, i) in sel.steps" :key="i">
              <b class="mono">{{ $td(s.tool) }}</b> <span class="muted">{{ JSON.stringify(s.args) }}</span> → {{ $td(s.summary) }} <span class="muted">{{ $t('（{a} ms）', { a: $td(s.ms) }) }}</span>
              <details><summary>{{ $t('结果') }}</summary><pre>{{ JSON.stringify(s.output, null, 1).slice(0, 4000) }}</pre></details>
            </li>
          </ol>
          <h3>{{ $t('引用（{a}）', { a: $td(sel.refs.length) }) }}</h3>
          <ul class="refs small"><li v-for="r in sel.refs" :key="r.n"><b>[{{ $td(r.n) }}]</b>
            <router-link v-if="r.url" :to="r.url">{{ $td(r.label) }}</router-link><span v-else>{{ $td(r.label) }}</span></li></ul>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="card">
        <div class="card-head"><h2>{{ $t('评测集') }}</h2>
          <span class="small muted">{{ $t('{a} 题 · 在临时库里载入实验 7 情景后逐题提问、逐项核对（不碰正在用的数据）', { a: $td(ev?.items.length) }) }}</span>
          <button class="btn primary sm r" :disabled="ev?.running || running" @click="runEvals">{{ ev?.running || running ? $t('正在考…') : $t('现在跑一遍（') + (ev?.model ? $t('模型版') : $t('规则版')) + $t('）') }}</button></div>
        <p class="small">{{ $t('规则版每次推送都在测试里跑，要求全过；接了模型后在这里跑模型版，目标 ≥ 90%。{a}', { a: ev && !ev.model ? $t('现在没配模型，只有规则版。') : '' }) }}</p>
        <table v-if="ev?.history.length" class="tbl small">
          <thead><tr><th>{{ $t('编号') }}</th><th>{{ $t('时间') }}</th><th>{{ $t('引擎') }}</th><th>{{ $t('得分') }}</th><th>{{ $t('代码版本') }}</th><th>{{ $t('发起') }}</th></tr></thead>
          <tbody><tr v-for="h in ev.history" :key="h.id"><td>{{ $td(h.id) }}</td><td>{{ fmtTs(h.started_at) }}</td><td>{{ $td(h.engine) }}</td>
            <td><b v-if="h.total">{{ $t('{a}/{b}（{c}%）', { a: $td(h.passed), b: $td(h.total), c: Math.round(h.passed / h.total * 100) }) }}</b><span v-else class="muted">{{ $t('进行中') }}</span></td>
            <td class="mono">{{ h.git_sha || '—' }}</td><td>{{ h.started_by || $t('测试') }}</td></tr></tbody>
        </table>
      </div>
      <div v-if="ev?.last" class="card">
        <div class="card-head"><h2>{{ $t('最近一次：{a}/{b}', { a: $td(ev.last.passed), b: $td(ev.last.total) }) }}</h2><span class="small muted">{{ $td(ev.last.engine) }} · {{ fmtTs(ev.last.finished_at) }}</span></div>
        <table class="tbl small">
          <thead><tr><th>{{ $t('题') }}</th><th>{{ $t('领域') }}</th><th>{{ $t('谁问') }}</th><th>{{ $t('问题') }}</th><th>{{ $t('结果') }}</th></tr></thead>
          <tbody><tr v-for="x in ev.last.results" :key="x.id" :class="{ bad: !x.ok }"><td class="mono">{{ $td(x.id) }}</td><td>{{ $td(x.domain) }}</td>
            <td>{{ { teacher: $t('老师'), student: $t('学生'), prod_manager: $t('厂长') }[x.as] }}</td><td>{{ $td(x.q) }}
              <details><summary class="muted">{{ $t('回答') }}</summary><pre>{{ $td(x.answer) }}</pre></details></td>
            <td><span v-if="x.ok" class="pill good">{{ $t('通过') }}</span><span v-else class="pill bad" :title="x.why.join($t('；'))">{{ x.why.join($t('；')) }}</span></td></tr></tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, reactive, ref } from 'vue';
import { get, post, session } from '../lib/api';
import { fmtTs } from '../lib/ont';

const boss = computed(() => !!session.user?.teacher || (session.user?.mode === 'prod' && session.user?.role === 'manager'));
const tab = ref('runs');
const runs = ref([]);
const sel = ref(null);
const ev = ref(null);
const engine = ref('rules');
const err = ref('');
const running = ref(false);
const f = reactive({ mine: false, bad: false, kind: '' });
const ai = ref(null);       // AI 模型选择（第 30 轮 H-6）：Claude / DeepSeek / 按地区自动

async function loadAi() { if (boss.value) { try { ai.value = await get('/admin/ai'); } catch { ai.value = null; } } }
async function setAi() {
  try { ai.value = await post('/admin/ai', { provider: ai.value.setting }); engine.value = ai.value.name; } catch (e) { alert(e.message); }
}

async function load() {
  try {
    const q = new URLSearchParams({ mine: f.mine || !boss.value ? 1 : 0, bad: f.bad ? 1 : 0, kind: f.kind });
    const r = await get('/ai/runs?' + q);
    runs.value = r.runs; engine.value = r.engine;
  } catch (e) { err.value = e.message; }
}
async function open(id) { try { sel.value = await get('/ai/runs/' + id); } catch (e) { err.value = e.message; } }
async function loadEvals() { try { ev.value = await get('/ai/evals'); } catch (e) { err.value = e.message; } }
async function runEvals() {
  running.value = true;
  try {
    await post('/ai/evals/run', {});
    const t = setInterval(async () => { await loadEvals(); if (!ev.value.running) { clearInterval(t); running.value = false; } }, 4000);
  } catch (e) { alert(e.message); running.value = false; }
}
onMounted(() => { load(); loadAi(); });
</script>

<style scoped>
.back { color: var(--muted); font-weight: 500; }
.page-title { flex-wrap: wrap; }
.tabs { margin-left: auto; display: flex; gap: 4px; }
.tabs button { height: 30px; padding: 0 12px; border: 1px solid var(--line); background: var(--surface); border-radius: 6px; cursor: pointer; }
.tabs button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.filters { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.grid { display: grid; grid-template-columns: minmax(0, 380px) minmax(0, 1fr); gap: 14px; align-items: start; }
@media (max-width: 900px) { .grid { grid-template-columns: minmax(0, 1fr); } }
.list { padding: 6px; max-height: 75vh; overflow: auto; }
.row { display: flex; flex-direction: column; gap: 2px; text-align: left; width: 100%; border: none; background: none; padding: 8px; border-radius: 6px;
  cursor: pointer; border-bottom: 1px solid var(--line); }
.row.on, .row:hover { background: var(--surface-2); }
.q { font-size: 13px; }
.tags { display: flex; gap: 4px; flex-wrap: wrap; }
.detail h2 { font-size: 16px; margin: 0 0 4px; }
.detail h3 { font-size: 13px; margin: 14px 0 4px; }
.ans { white-space: pre-wrap; background: var(--surface-2); border-radius: 8px; padding: 8px 10px; font-size: 13px; }
.warnbox { background: #FFF4CC; border-radius: 6px; padding: 6px 8px; margin-top: 6px; }
.steps pre, td pre { white-space: pre-wrap; font-size: 11px; max-height: 240px; overflow: auto; }
.refs { padding-left: 18px; }
.card-head .r { margin-left: auto; }
.btn.sm { height: 28px; padding: 0 10px; }
tr.bad td { background: #FFF6F4; }
</style>
