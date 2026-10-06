<!-- AI 运行记录与评测（第 17 轮 D 期 D3、D4）：每次提问都存档，可逐步回放；评测集的分数 -->
<template>
  <div class="page">
    <div class="page-title"><h1><router-link to="/ont" class="back">厂情中枢</router-link> / AI 运行记录</h1>
      <span class="muted">AI 代理每次运行都存档：问了什么、调了哪些工具、引用了什么、数字核对是否通过</span>
      <span class="tabs"><button :class="{ on: tab === 'runs' }" @click="tab = 'runs'">运行记录</button>
        <button v-if="boss" :class="{ on: tab === 'evals' }" @click="tab = 'evals'; loadEvals()">评测</button></span></div>
    <div v-if="err" class="err">{{ err }}</div>

    <template v-if="tab === 'runs'">
      <div class="filters small">
        <label v-if="boss"><input v-model="f.mine" type="checkbox" @change="load"> 只看我的</label>
        <label><input v-model="f.bad" type="checkbox" @change="load"> 只看 👎 或数字未核实</label>
        <select v-model="f.kind" @change="load"><option value="">全部种类</option><option value="chat">聊天</option>
          <option value="analyze">让 AI 分析</option><option value="report">报告</option><option value="eval">评测</option></select>
        <span class="muted">引擎：{{ engine === 'rules' ? '规则版（没配模型）' : engine }}</span>
      </div>
      <div class="grid">
        <div class="card list">
          <p v-if="!runs.length" class="muted small">还没有运行记录。</p>
          <button v-for="r in runs" :key="r.id" class="row" :class="{ on: sel?.id === r.id }" @click="open(r.id)">
            <span class="mono small">AI-{{ String(r.id).padStart(5, '0') }}</span>
            <span class="q">{{ r.question }}</span>
            <span class="small muted">{{ r.user }} · {{ fmtTs(r.created_at) }} · {{ r.nsteps }} 步 · {{ r.duration_ms }} ms</span>
            <span class="tags"><span v-if="r.ok === false" class="pill warn">数字未核实</span><span v-if="r.feedback === 1" class="pill good">👍</span>
              <span v-if="r.feedback === -1" class="pill bad">👎</span><span class="pill mute">{{ r.engine === 'rules' ? '规则版' : r.engine }}</span></span>
          </button>
        </div>
        <div v-if="sel" class="card detail">
          <h2>AI-{{ String(sel.id).padStart(5, '0') }}：{{ sel.question }}</h2>
          <p class="small muted">{{ sel.user }}（{{ sel.role }}）· {{ fmtTs(sel.created_at) }} · {{ sel.kind }} · {{ sel.engine }} · {{ sel.duration_ms }} ms
            <template v-if="sel.feedback_text"> · 意见：{{ sel.feedback_text }}</template></p>
          <h3>回答</h3>
          <pre class="ans">{{ sel.answer }}</pre>
          <div v-if="sel.check && !sel.check.ok" class="warnbox small">
            <b>数字核对没通过：</b>
            <div v-for="(x, i) in sel.check.unverified" :key="i">“{{ x.sentence }}” 里的 {{ x.numbers.join('、') }}</div>
            <div v-if="sel.check.bad_refs?.length">无效引用：{{ sel.check.bad_refs.join('、') }}</div>
          </div>
          <h3>步骤（{{ sel.steps.length }}）</h3>
          <ol class="steps small">
            <li v-for="(s, i) in sel.steps" :key="i">
              <b class="mono">{{ s.tool }}</b> <span class="muted">{{ JSON.stringify(s.args) }}</span> → {{ s.summary }} <span class="muted">（{{ s.ms }} ms）</span>
              <details><summary>结果</summary><pre>{{ JSON.stringify(s.output, null, 1).slice(0, 4000) }}</pre></details>
            </li>
          </ol>
          <h3>引用（{{ sel.refs.length }}）</h3>
          <ul class="refs small"><li v-for="r in sel.refs" :key="r.n"><b>[{{ r.n }}]</b>
            <router-link v-if="r.url" :to="r.url">{{ r.label }}</router-link><span v-else>{{ r.label }}</span></li></ul>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="card">
        <div class="card-head"><h2>评测集</h2>
          <span class="small muted">{{ ev?.items.length }} 题 · 在临时库里载入实验 7 情景后逐题提问、逐项核对（不碰正在用的数据）</span>
          <button class="btn primary sm r" :disabled="ev?.running || running" @click="runEvals">{{ ev?.running || running ? '正在考…' : '现在跑一遍（' + (ev?.model ? '模型版' : '规则版') + '）' }}</button></div>
        <p class="small">规则版每次推送都在测试里跑，要求全过；接了模型后在这里跑模型版，目标 ≥ 90%。{{ ev && !ev.model ? '现在没配模型，只有规则版。' : '' }}</p>
        <table v-if="ev?.history.length" class="tbl small">
          <thead><tr><th>编号</th><th>时间</th><th>引擎</th><th>得分</th><th>代码版本</th><th>发起</th></tr></thead>
          <tbody><tr v-for="h in ev.history" :key="h.id"><td>{{ h.id }}</td><td>{{ fmtTs(h.started_at) }}</td><td>{{ h.engine }}</td>
            <td><b v-if="h.total">{{ h.passed }}/{{ h.total }}（{{ Math.round(h.passed / h.total * 100) }}%）</b><span v-else class="muted">进行中</span></td>
            <td class="mono">{{ h.git_sha || '—' }}</td><td>{{ h.started_by || '测试' }}</td></tr></tbody>
        </table>
      </div>
      <div v-if="ev?.last" class="card">
        <div class="card-head"><h2>最近一次：{{ ev.last.passed }}/{{ ev.last.total }}</h2><span class="small muted">{{ ev.last.engine }} · {{ fmtTs(ev.last.finished_at) }}</span></div>
        <table class="tbl small">
          <thead><tr><th>题</th><th>领域</th><th>谁问</th><th>问题</th><th>结果</th></tr></thead>
          <tbody><tr v-for="x in ev.last.results" :key="x.id" :class="{ bad: !x.ok }"><td class="mono">{{ x.id }}</td><td>{{ x.domain }}</td>
            <td>{{ { teacher: '老师', student: '学生', prod_manager: '厂长' }[x.as] }}</td><td>{{ x.q }}
              <details><summary class="muted">回答</summary><pre>{{ x.answer }}</pre></details></td>
            <td><span v-if="x.ok" class="pill good">通过</span><span v-else class="pill bad" :title="x.why.join('；')">{{ x.why.join('；') }}</span></td></tr></tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup>
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
onMounted(load);
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
