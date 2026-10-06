<template>
  <aside v-if="ai.open" class="drawer" aria-label="AI 工厂助手">
    <header>
      <b>AI 工厂助手</b>
      <span class="muted small">{{ session.user?.mode === 'teach' ? (session.user?.teacher ? '教学模式（老师）：完整分析' : '教学模式：只提示方向') : '生产模式：可代办，写操作只起草、要你确认' }}</span>
      <button class="x" aria-label="关闭" @click="ai.open = false">×</button>
    </header>
    <div ref="box" class="msgs">
      <p v-if="!ai.messages.length" class="muted small">
        问我全厂的任何情况：我在工厂本体上查、追因、推演，每个结论后面的 [n] 点开就是依据。例如：
      </p>
      <div v-if="!ai.messages.length" class="chips">
        <button v-for="q in samples" :key="q" class="chip" @click="ask(q)">{{ q }}</button>
      </div>
      <div v-for="(m, i) in ai.messages" :key="i" class="msg" :class="m.role">
        <div v-if="m.role === 'user'" class="bubble">{{ m.content }}</div>
        <div v-else class="bubble">
          <div v-for="(ln, k) in segments(m)" :key="k" :class="{ flag: ln.flagged }" class="ln">
            <template v-for="(p, j) in ln.parts" :key="j">
              <span v-if="p.text !== undefined">{{ p.text }}</span>
              <button v-else class="ref" :class="{ missing: p.ref.missing }" :title="p.ref.label || '没有这个依据'" @click="openRef(p.ref)">{{ p.ref.n }}</button>
            </template>
            <span v-if="ln.flagged" class="flag-tag" title="这句里的数字没能在查到的数据里找到">未经核实</span>
          </div>
        </div>
        <div v-if="src && src.from === m" class="src small">
          <template v-if="src.error">{{ src.error }}</template>
          <template v-else><b class="mono">#{{ src.seq }}</b> {{ src.type }} · {{ src.topic }} · {{ src.ts?.slice(0, 19).replace('T', ' ') }}
            <pre>{{ JSON.stringify(src.data, null, 1).slice(0, 600) }}</pre></template>
          <button class="linkbtn" @click="src = null">收起</button>
        </div>
        <div v-if="m.role === 'assistant'" class="meta small muted">
          <span>{{ engineLabel(m.engine) }}</span>
          <span v-if="m.refs?.length">· 依据 {{ m.refs.length }} 条</span>
          <span v-if="m.check && !m.check.ok" class="warn-t">· 有数字未经核实</span>
          <template v-if="m.run_id">
            <button class="fb" :class="{ on: m.feedback === 1 }" title="有用" @click="feedback(m, 1)">👍</button>
            <button class="fb" :class="{ on: m.feedback === -1 }" title="不对 / 没用" @click="feedback(m, -1)">👎</button>
          </template>
        </div>
        <div v-if="m.note" class="muted small">{{ m.note }}</div>
        <div v-if="m.actions?.length" class="prop">
          <span>已起草动作（草稿）<b class="mono">{{ m.actions.map((a) => 'ACT-' + String(a).padStart(5, '0')).join('、') }}</b></span>
          <router-link class="btn" :to="{ path: '/ont/actions', query: { box: 'mine' } }" @click="ai.open = false">去提交</router-link>
        </div>
        <div v-for="pid in m.proposals || []" :key="pid" class="prop">
          <span>已起草提议 <b class="mono">{{ pid }}</b></span>
          <button class="btn primary" @click="openProposal(pid)">预览并确认</button>
        </div>
      </div>
      <div v-if="ai.busy" class="muted small">正在查本体、追因、推演…</div>
      <div v-if="ai.error" class="err">{{ ai.error }}</div>
    </div>
    <form class="ask" @submit.prevent="send">
      <input v-model="text" placeholder="例如：SO 为什么会延期？本周瓶颈在哪？" aria-label="问 AI 工厂助手">
      <button class="btn primary" :disabled="ai.busy">发送</button>
    </form>
    <ProposalModal v-if="pid" :pid="pid" @close="pid = null" />
  </aside>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { get, session } from '../lib/api';
import { ai, ask, feedback, segments } from '../lib/ai';
import ProposalModal from './ProposalModal.vue';

const text = ref('');
const box = ref(null);
const pid = ref(null);
const router = useRouter();
const src = ref(null);
const samples = computed(() => (session.user?.mode === 'teach' && !session.user?.teacher
  ? ['我下一步做什么？', 'MRP 是什么？', '本周瓶颈在哪？']
  : ['现在有哪些异常？', '外圆磨床要是再停一天，哪张订单受影响？怎么办最划算？', '哪张订单可能延期？为什么？', '10 台 WQR-105，10 月 15 日交货']));
function engineLabel(e) { return !e || e === 'rules' ? '规则版' : '模型：' + e.split(':').pop(); }
async function openRef(r) {
  if (r.missing) return;
  if (r.kind === 'message') {
    const m = ai.messages.find((x) => (x.refs || []).includes(r));
    try { src.value = { ...(await get('/ont/lineage/' + r.seq)), from: m }; } catch (e) { src.value = { error: e.message, from: m }; }
    return;
  }
  if (r.url) router.push(r.url);
}
function send() { const t = text.value; text.value = ''; ask(t); }
function openProposal(id) { pid.value = id; }
watch(() => ai.messages.length, async () => { await nextTick(); if (box.value) box.value.scrollTop = box.value.scrollHeight; });
</script>

<style scoped>
.drawer { position: fixed; right: 0; top: 0; bottom: 0; width: min(420px, 100%); background: #fff; border-left: 1px solid var(--line);
  box-shadow: -8px 0 24px rgba(23, 33, 43, .08); display: flex; flex-direction: column; z-index: 40; }
header { display: flex; align-items: baseline; gap: 10px; padding: 16px 18px; border-bottom: 1px solid var(--line); }
.x { margin-left: auto; border: 0; background: none; font-size: 22px; cursor: pointer; color: var(--muted); }
.msgs { flex-grow: 1; overflow-y: auto; padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }
.msg.user { align-self: flex-end; max-width: 85%; }
.msg.user .bubble { background: var(--accent); color: #fff; }
.msg.assistant { align-self: flex-start; max-width: 95%; }
.bubble { background: var(--surface-2); border-radius: 10px; padding: 10px 12px; white-space: pre-wrap; line-height: 1.55; font-size: 13px; }
.prop { display: flex; align-items: center; gap: 10px; margin-top: 6px; font-size: 13px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { height: 28px; padding: 0 10px; border-radius: 14px; border: 1px solid var(--line); background: var(--surface-2); cursor: pointer; font-size: 12px; }
.ln { min-height: 1em; }
.ln.flag { background: #FFF4CC; border-radius: 4px; }
.flag-tag { font-size: 11px; color: #8A5A00; margin-left: 4px; border: 1px solid #E8C770; border-radius: 4px; padding: 0 3px; }
.ref { border: 1px solid var(--line); background: #fff; color: var(--accent); border-radius: 4px; font-size: 11px; padding: 0 4px; margin: 0 1px;
  cursor: pointer; line-height: 16px; vertical-align: 1px; }
.ref.missing { color: var(--bad); border-color: var(--bad); }
.meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 4px; }
.warn-t { color: #8A5A00; }
.fb { border: none; background: none; cursor: pointer; opacity: .45; font-size: 13px; padding: 0 2px; }
.fb.on { opacity: 1; }
.src { background: var(--surface-2); border-radius: 8px; padding: 6px 8px; margin-top: 4px; }
.src pre { white-space: pre-wrap; font-size: 11px; margin: 4px 0; max-height: 160px; overflow: auto; }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; }
.ask { display: flex; gap: 8px; padding: 12px 18px; border-top: 1px solid var(--line); }
.ask input { flex-grow: 1; height: 38px; border: 1px solid #C8CEC7; border-radius: 8px; padding: 0 12px; }
</style>
