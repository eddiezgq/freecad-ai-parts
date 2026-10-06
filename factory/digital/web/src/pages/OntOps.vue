<template>
  <div class="page">
    <div class="page-title"><h1>厂情中枢 · 指挥台</h1>
      <span class="muted">全厂态势、异常、原因和影响 · 规则每 20 秒检查一次全厂</span>
      <span class="tabs" role="tablist">
        <button type="button" role="tab" :class="{ on: view === 'situation' }" @click="go({ view: 'situation' })">全厂态势</button>
        <button type="button" role="tab" :class="{ on: view === 'anomalies' }" @click="go({ view: 'anomalies' })">异常处理
          <span v-if="openCount" class="cnt">{{ openCount }}</span></button>
        <router-link to="/ont/sim" class="tablink">推演工作台</router-link>
        <router-link to="/ont/actions" class="tablink">动作收件箱</router-link>
        <router-link to="/ont/map" class="tablink">全貌地图与搜索</router-link>
        <router-link to="/ont/rules" class="tablink">规则目录</router-link>
        <router-link to="/ont/reports" class="tablink">日报与周报</router-link>
        <router-link to="/ont/ai" class="tablink">AI 运行记录</router-link>
      </span>
    </div>
    <div v-if="err" class="err">{{ err }}</div>

    <!-- 第一屏：全厂态势 -->
    <template v-if="view === 'situation'">
      <div class="timebar card">
        <span class="small"><b>时间</b></span>
        <input v-model="atLocal" type="datetime-local" :max="maxLocal" :min="minLocal" aria-label="回看时刻" @change="loadHist">
        <button class="btn sm ghost" @click="shift(-1)">往前 1 小时</button>
        <button class="btn sm ghost" @click="shift(-24)">往前 1 天</button>
        <button v-if="hist" class="btn sm primary" @click="backToNow">回到现在</button>
        <span v-if="hist" class="small warnline">正在回看 {{ fmtTs(hist.at) }}（只能看；要问“如果当时那样做会怎样”，点“从这里推演”做复盘推演）</span>
        <router-link v-if="hist?.snapshot" class="btn sm" :to="{ path: '/ont/sim', query: { snap: hist.snapshot.id, retro: 1 } }">从这里推演</router-link>
      </div>
      <div v-if="!sit" class="empty">读取中…</div>
      <template v-else>
        <div v-for="row in rows" :key="row.key" class="maprow">
          <div class="rowlabel">{{ row.label }}</div>
          <div class="cards" :class="row.key">
            <button v-for="c in row.cards" :key="c.domain" type="button" class="sc" :style="{ '--c': DOMAIN_COLOR[c.domain] }"
              :class="{ waiting: c.waiting }" @click="go({ view: 'anomalies', domain: c.domain })">
              <span class="sc-h"><b>{{ c.label }}</b>
                <span class="badges">
                  <span v-if="c.anomalies.critical" class="b crit" :title="c.anomalies.critical + ' 个严重'">{{ c.anomalies.critical }}</span>
                  <span v-if="c.anomalies.warn" class="b warn" :title="c.anomalies.warn + ' 个警告'">{{ c.anomalies.warn }}</span>
                  <span v-if="c.anomalies.info" class="b info" :title="c.anomalies.info + ' 个提示'">{{ c.anomalies.info }}</span>
                </span></span>
              <span v-for="m in c.metrics" :key="m.key" class="met">
                <span class="ml small muted">{{ m.label }}</span>
                <span class="mv mono">{{ fmt(m.value, m.fmt) }}</span>
                <svg v-if="m.trend.length > 1" class="spark" viewBox="0 0 60 16" aria-hidden="true"><polyline :points="spark(m.trend)" /></svg>
              </span>
              <span v-if="c.waiting" class="small wait">{{ c.waiting }}</span>
              <span class="small muted foot">{{ c.rules_live.length ? c.rules_live.length + ' 条规则在跑' : '还没有规则在跑' }}<template
                v-if="c.rules_waiting.length"> · {{ c.rules_waiting.length }} 条待数据</template></span>
            </button>
          </div>
        </div>
        <p class="muted small">点卡片看这个领域的异常。指标每天记一次，小折线是近 7 天。</p>
        <section v-if="hist" class="card">
          <div class="card-head"><h2>那时开着的异常（{{ hist.anomalies.length }}）</h2>
            <span v-if="hist.snapshot" class="muted small">设备状态取 {{ fmtTs(hist.snapshot.ts) }} 的快照（{{ hist.snapshot.exact ? '精确' : '近似' }}）</span></div>
          <ul class="small hlist"><li v-for="a in hist.anomalies" :key="a.id"><span class="sev" :class="a.severity">{{ LVL[a.severity] }}</span>
            <router-link :to="{ path: '/ont', query: { view: 'anomalies', a: a.id } }">{{ a.title }}</router-link>
            <span class="muted"> · {{ fmtTs(a.first_seen) }} 起{{ a.closed_at ? '，' + fmtTs(a.closed_at) + ' 结束' : '' }}</span></li></ul>
          <table v-if="hist.machines" class="t small"><thead><tr><th>设备</th><th>状态</th><th class="num">派工</th><th class="num">排队</th><th class="num">在做</th></tr></thead>
            <tbody><tr v-for="(m, u) in hist.machines" :key="u"><td class="mono">{{ u.toUpperCase() }}</td><td>{{ m.state }}</td>
              <td class="num">{{ m.jobs }}</td><td class="num">{{ m.queue }}</td><td class="num">{{ m.busy }}</td></tr></tbody></table>
        </section>
      </template>
    </template>

    <!-- 第二屏：异常处理（三栏） -->
    <div v-else class="three">
      <section class="card list">
        <div class="filters">
          <select v-model="f.status" aria-label="状态" @change="loadList"><option value="open">开着的</option><option value="closed">已结束</option><option value="all">全部</option></select>
          <select v-model="f.domain" aria-label="领域" @change="loadList"><option value="">全部领域</option>
            <option v-for="c in sit?.cards || []" :key="c.domain" :value="c.domain">{{ c.label }}</option></select>
          <label class="small"><input v-model="f.mine" type="checkbox" @change="loadList"> 只看我负责的</label>
        </div>
        <div v-if="!list.length" class="empty">{{ f.status === 'open' ? '没有开着的异常。' : '没有记录。' }}</div>
        <ul class="items">
          <li v-for="a in list" :key="a.id" :class="{ sel: a.id === sel?.id }" @click="go({ a: a.id })">
            <span class="sev" :class="a.severity">{{ a.severity_label }}</span>
            <span class="it"><b>{{ a.title }}</b>
              <span class="small muted">{{ a.domain_label }} · {{ a.rule }} {{ a.rule_name }} · {{ a.status_label }} · {{ ago(a.last_seen) }}<template v-if="a.hits > 1"> · {{ a.hits }} 次</template></span></span>
          </li>
        </ul>
        <p v-if="last" class="small muted">上一轮检测 {{ ago(new Date(last.ts * 1000).toISOString()) }}，用时 {{ last.ms }} 毫秒</p>
      </section>

      <section class="card mid">
        <template v-if="sel">
          <div class="card-head"><h2>{{ sel.title }}</h2><span class="sev" :class="sel.severity">{{ sel.severity_label }}</span></div>
          <div class="sum">
            <p class="narr">{{ narr?.text || sel.text_rules }}</p>
            <p class="small muted">
              <template v-if="narr">{{ narr.by === 'rules' ? '规则版' : 'AI 润色（' + narr.by + '）' }}<template v-if="narr.note"> · {{ narr.note }}</template> · </template>
              <button class="linkbtn" :disabled="narrBusy" @click="narrate">{{ narrBusy ? '润色中…' : '讲成人话（AI 润色）' }}</button>
              · <button class="linkbtn" :disabled="ai.busy" @click="analyze(sel.id, sel.key)">让 AI 分析</button>
            </p>
          </div>
          <ChainGraph :chain="sel.chain" @edge="(e) => (basis = e)" @node="(n) => (node = n)" />
          <div v-if="basis" class="basis small">
            <b>依据</b>：{{ basis.label }} —— {{ basis.basis.how }}
            <template v-if="basis.basis.text">；{{ basis.basis.text }}</template>
            <button v-if="basis.basis.seq" class="linkbtn" @click="showSource(basis.basis.seq)">看原始记录 #{{ basis.basis.seq }}</button>
            <span v-for="(v, k) in basis.values" :key="k" class="muted"> · {{ k }} {{ fmtVal(v) }}</span>
          </div>
          <div v-if="node && !node.hidden" class="basis small">
            <span class="pill info">{{ node.label }}</span> <ObjLink :type="node.type" :k="node.key">{{ node.display }}</ObjLink>
            <span v-for="(v, k) in node.values" :key="k" class="muted"> · {{ k }} {{ fmtVal(v) }}</span>
          </div>
          <div v-else-if="node?.hidden" class="basis small muted">这一环的原因需要自己查（学生看不到老师注入的情景）。</div>
        </template>
        <div v-else class="empty">左边选一个异常，这里显示它的原因和影响。</div>
      </section>

      <section class="card right">
        <template v-if="sel">
          <h2>处理</h2>
          <p class="small"><b>{{ sel.rule_info.id }} {{ sel.rule_info.name }}</b>：<span class="muted">{{ sel.rule_info.desc }}</span></p>
          <p v-if="sel.hint" class="hint small">建议：{{ sel.hint }}</p>
          <p class="small muted">负责：{{ roleName(sel.role) }} · 状态：{{ sel.status_label }}<template v-if="sel.assignee"> · {{ sel.assignee }}</template>
            · 首次 {{ ago(sel.first_seen) }}</p>
          <div v-if="isOpen" class="acts">
            <button v-if="sel.status === 'open'" class="btn" :disabled="!sel.can_act" @click="act('ack')">确认</button>
            <button v-if="sel.status !== 'doing'" class="btn" :disabled="!sel.can_act" @click="act('doing')">开始处理</button>
            <select v-model="assignRole" :disabled="!sel.can_act" aria-label="指派给"><option value="">指派给…</option>
              <option v-for="(n, k) in ROLES" :key="k" :value="k">{{ n }}</option></select>
            <button v-if="assignRole" class="btn" @click="act('assign', { role: assignRole })">指派</button>
          </div>
          <p v-if="isOpen && !sel.can_act" class="small muted">这个异常由{{ roleName(sel.role) }}处理；你可以写备注。</p>
          <textarea v-model="text" rows="2" placeholder="备注，或关闭时写怎么处理的" aria-label="备注"></textarea>
          <div class="acts">
            <button class="btn ghost" :disabled="!text.trim()" @click="act('note')">写备注</button>
            <button v-if="isOpen" class="btn danger" :disabled="!sel.can_act || !text.trim()" @click="act('close')">关闭</button>
          </div>
          <div v-if="links.length" class="quick small"><b>去处理：</b>
            <router-link v-for="l in links" :key="l.to" :to="l.to">{{ l.label }}</router-link></div>
          <h3 class="small">记录</h3>
          <ol class="notes small">
            <li v-for="(n, i) in sel.notes" :key="i"><span class="muted mono">{{ ts(n.ts) }}</span> {{ n.who === 'system' ? '系统' : n.who }}：{{ n.text }}</li>
          </ol>
          <h3 class="small">原始记录</h3>
          <ul class="small ev">
            <li v-for="(e, i) in sel.evidence" :key="i"><span class="mono">{{ e.topic }}</span>
              <button v-if="e.seq" class="linkbtn" @click="showSource(e.seq)">#{{ e.seq }}</button>
              <span v-else class="muted"> {{ e.name || e.item || e.id || e.ts || '' }}</span></li>
          </ul>
          <OptionsPanel v-if="isOpen" :anomaly-id="sel.id" @adopted="loadSel" />
          <RetroPanel v-else :anomaly-id="sel.id" />
        </template>
      </section>
    </div>

    <div v-if="src" class="modal-mask" @click.self="src = null">
      <div class="modal src-modal" role="dialog" aria-label="原始记录">
        <div class="card-head"><h2>原始记录 #{{ src.seq }}</h2><button class="more btn ghost" @click="src = null">关闭</button></div>
        <div v-if="src.error" class="err">{{ src.error }}</div>
        <template v-else><p class="small mono muted">{{ src.topic }}（{{ src.type }}）· {{ ts(src.ts) }}</p>
          <pre class="raw">{{ JSON.stringify(src.data, null, 2) }}</pre></template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post, session } from '../lib/api';
import { DOMAIN_COLOR, fmtVal, fmtTs as ts, fmtTs, lineage } from '../lib/ont';
import ChainGraph from '../components/ChainGraph.vue';
import ObjLink from '../components/ObjLink.vue';
import OptionsPanel from '../components/OptionsPanel.vue';
import RetroPanel from '../components/RetroPanel.vue';
import { ai, analyze } from '../lib/ai';

const ROLES = { planner: '计划员', engineer: '工艺员', operator: '操作工', quality: '质检员', manager: '厂长', sales: '销售' };
const roleName = (r) => ROLES[r] || r;
const route = useRoute();
const router = useRouter();
const view = computed(() => route.query.view || (route.query.a ? 'anomalies' : 'situation'));
const err = ref('');
const sit = ref(null);
const list = ref([]);
const last = ref(null);
const sel = ref(null);
const basis = ref(null);
const node = ref(null);
const narr = ref(null);
const narrBusy = ref(false);
const text = ref('');
const assignRole = ref('');
const src = ref(null);
const isTeacher = session.user?.teacher === true || session.user?.role === 'manager';
const f = ref({ status: 'open', domain: route.query.domain || '', mine: !isTeacher });
const openCount = computed(() => (live.value?.total_open) || 0);
const LVL = { critical: '严重', warn: '警告', info: '提示' };
// 时间回看（C11）
const live = ref(null);
const hist = ref(null);
const atLocal = ref('');
const pad = (n) => String(n).padStart(2, '0');
const toLocal = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const maxLocal = toLocal(new Date());
const minLocal = toLocal(new Date(Date.now() - 7 * 86400e3));
async function loadHist() {
  if (!atLocal.value) return backToNow();
  try {
    hist.value = await get('/ont/history?at=' + encodeURIComponent(new Date(atLocal.value).toISOString()));
    sit.value = hist.value;
  } catch (e) { alert(e.message); }
}
function shift(h) {
  const base = atLocal.value ? new Date(atLocal.value) : new Date();
  const d = new Date(Math.max(Date.now() - 7 * 86400e3 + 60e3, base.getTime() + h * 3600e3));
  atLocal.value = toLocal(d);
  loadHist();
}
function backToNow() { hist.value = null; atLocal.value = ''; sit.value = live.value; }
const isOpen = computed(() => sel.value && ['open', 'ack', 'doing'].includes(sel.value.status));

const rows = computed(() => {
  const cs = [...(sit.value?.cards || [])].sort((a, b) => a.order - b.order);
  return [{ key: 'chain', label: '价值链', cards: cs.filter((c) => c.row === 'chain') },
    { key: 'support', label: '支撑面', cards: cs.filter((c) => c.row === 'support') }];
});

function fmt(v, f) {
  if (v === null || v === undefined) return '—';
  if (f === 'pct') return (v * 100).toFixed(1) + '%';
  if (f === 'pct_signed') return (v > 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
  return String(v);
}
function spark(tr) {
  const vs = tr.map((x) => x[1]);
  const lo = Math.min(...vs); const hi = Math.max(...vs);
  return vs.map((v, i) => `${(i / (vs.length - 1)) * 58 + 1},${hi === lo ? 8 : 15 - ((v - lo) / (hi - lo)) * 14}`).join(' ');
}
function ago(s) {
  const m = (Date.now() - new Date(s).getTime()) / 60000;
  if (m < 1) return '刚刚';
  if (m < 60) return Math.round(m) + ' 分钟前';
  if (m < 1440) return Math.round(m / 60) + ' 小时前';
  return Math.round(m / 1440) + ' 天前';
}

const links = computed(() => {
  const a = sel.value;
  if (!a) return [];
  const L = { production: [['/work/operator', '车间终端'], ['/work/manager', '经营与成本']], quality: [['/work/quality', '质量'], ['/quality/8d', '开 8D']],
    sales: [['/work/planner', '订单与计划']], planning: [['/work/planner', '订单与计划']], supply: [['/work/planner', '订单与计划（请购）']],
    service: [['/twin', '数字孪生']], maintenance: [['/work/manager', '经营与成本']], finance: [['/work/manager', '经营与成本']], product: [['/design', '设计发布与审批']] };
  const out = (L[a.domain] || []).map(([to, label]) => ({ to, label }));
  if (a.subject) out.unshift({ to: `/ont/${a.subject.type}/${encodeURIComponent(a.subject.key)}`, label: '对象页' });
  return out;
});

function go(q) { router.push({ path: '/ont', query: { ...route.query, ...q } }); }

async function loadSit() {
  try { live.value = await get('/ont/situation'); if (!hist.value) sit.value = live.value; } catch (e) { err.value = e.message; }
}
async function loadList() {
  try {
    const q = new URLSearchParams({ status: f.value.status, domain: f.value.domain, role: f.value.mine ? session.user?.role || '' : '' });
    const r = await get('/ont/anomalies?' + q);
    list.value = r.anomalies;
    last.value = r.last_round;
    if (!route.query.a && list.value.length && view.value === 'anomalies' && window.innerWidth > 900) go({ a: list.value[0].id });
  } catch (e) { err.value = e.message; }
}
async function loadSel() {
  basis.value = null; node.value = null; narr.value = null; text.value = ''; assignRole.value = '';
  if (!route.query.a) { sel.value = null; return; }
  try { sel.value = await get('/ont/anomalies/' + route.query.a); } catch (e) { err.value = e.message; sel.value = null; }
}
async function act(kind, extra = {}) {
  try {
    sel.value = await post(`/ont/anomalies/${sel.value.id}/${kind}`, { text: text.value, ...extra });
    text.value = ''; assignRole.value = '';
    loadList(); loadSit();
  } catch (e) { alert(e.message); }
}
async function narrate() {
  narrBusy.value = true;
  try { narr.value = await post(`/ont/anomalies/${sel.value.id}/narrate`); } catch (e) { alert(e.message); } finally { narrBusy.value = false; }
}
async function showSource(seq) { src.value = { seq }; try { src.value = await lineage(seq); } catch (e) { src.value = { seq, error: e.message }; } }

watch(() => route.query.domain, (d) => { f.value.domain = d || ''; loadList(); });
watch(() => route.query.a, loadSel);
let timer;
onMounted(() => {
  loadSit(); loadList(); loadSel();
  timer = setInterval(() => { loadSit(); loadList(); }, 30000);
});
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.tabs { margin-left: auto; display: flex; gap: 4px; align-items: center; }
.tabs button, .tablink { height: 32px; padding: 0 12px; border: 1px solid var(--line); background: var(--surface); border-radius: 6px; cursor: pointer;
  color: var(--ink); display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
.tabs button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.tablink:hover { text-decoration: none; background: var(--surface-2); }
.cnt { background: var(--bad); color: #fff; border-radius: 9px; font-size: 11px; padding: 0 6px; }
.maprow { display: flex; gap: 10px; margin-bottom: 10px; }
.rowlabel { writing-mode: vertical-rl; font-size: 12px; color: var(--muted); letter-spacing: 4px; text-align: center; }
.cards { display: grid; gap: 8px; flex: 1; }
.cards.chain { grid-template-columns: repeat(5, minmax(0, 1fr)); }
.cards.support { grid-template-columns: repeat(5, minmax(0, 1fr)); }
.sc { text-align: left; border: 1px solid var(--line); border-top: 4px solid var(--c); border-radius: 8px; background: var(--surface); padding: 9px 11px;
  cursor: pointer; display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.sc:hover { background: var(--surface-2); border-color: var(--c); }
.sc.waiting { background: repeating-linear-gradient(135deg, #fff, #fff 8px, #F6F7F4 8px, #F6F7F4 16px); }
.sc-h { display: flex; align-items: center; gap: 6px; }
.badges { margin-left: auto; display: flex; gap: 3px; }
.b { font-size: 11px; font-weight: 600; border-radius: 9px; padding: 0 7px; color: #fff; }
.b.crit { background: var(--bad); }
.b.warn { background: var(--warn); }
.b.info { background: var(--accent); }
.met { display: grid; grid-template-columns: 1fr auto 60px; align-items: center; gap: 6px; }
.mv { font-weight: 600; font-size: 15px; color: var(--c); }
.spark { width: 60px; height: 16px; }
.spark polyline { fill: none; stroke: var(--c); stroke-width: 1.5; }
.wait { color: var(--muted); }
.foot { margin-top: auto; font-size: 11px; }
.timebar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 8px 12px; margin-bottom: 10px; }
.timebar input { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 6px; }
.btn.sm { height: 30px; padding: 0 10px; }
.warnline { color: var(--warn-ink); background: var(--warn-bg); padding: 2px 8px; border-radius: 4px; }
.hlist { margin: 0 0 10px; padding-left: 0; list-style: none; }
.hlist li { padding: 3px 0; }
.three { display: grid; grid-template-columns: 320px minmax(0, 1fr) 320px; gap: 14px; align-items: start; }
.filters { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; align-items: center; }
.filters select { height: 30px; border: 1px solid var(--line); border-radius: 6px; }
.items { list-style: none; margin: 0; padding: 0; max-height: 66vh; overflow: auto; }
.items li { display: flex; gap: 8px; padding: 8px 6px; border-bottom: 1px solid var(--line-soft); cursor: pointer; align-items: flex-start; }
.items li:hover { background: var(--surface-2); }
.items li.sel { background: var(--accent-bg); }
.it { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.it b { font-weight: 500; font-size: 13px; }
.sev { font-size: 11px; font-weight: 600; border-radius: 4px; padding: 1px 6px; white-space: nowrap; color: #fff; flex-shrink: 0; }
.sev.critical { background: var(--bad); }
.sev.warn { background: var(--warn); }
.sev.info { background: var(--accent); }
.mid { min-height: 520px; display: flex; flex-direction: column; gap: 8px; }
.mid > .cg { flex: 1; }
.narr { margin: 0; line-height: 1.6; }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; padding: 0 4px; font-size: 12px; }
.basis { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.right h2 { font-size: 15px; margin-bottom: 6px; }
.right h3 { margin: 12px 0 4px; }
.hint { background: var(--task-bg); border: 1px solid var(--task-line); border-radius: 6px; padding: 6px 8px; color: var(--task-ink); }
.acts { display: flex; gap: 6px; flex-wrap: wrap; margin: 6px 0; }
.acts .btn { height: 30px; padding: 0 10px; }
.acts select { height: 30px; border: 1px solid var(--line); border-radius: 6px; }
textarea { width: 100%; border: 1px solid #C8CEC7; border-radius: 6px; padding: 6px 8px; font-family: inherit; }
.quick { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
.notes, .ev { margin: 0; padding-left: 18px; max-height: 180px; overflow: auto; }
.later { margin-top: 12px; border: 1px dashed var(--line); border-radius: 6px; padding: 8px; }
.src-modal { width: min(680px, 94vw); max-height: 86vh; overflow: auto; }
.raw { background: var(--surface-2); padding: 10px; border-radius: 6px; font-size: 12px; overflow: auto; max-height: 50vh; }
@media (max-width: 1200px) { .three { grid-template-columns: 300px minmax(0, 1fr); } .right { grid-column: 1 / -1; } }
@media (max-width: 900px) {
  .three { grid-template-columns: 1fr; }
  .cards.chain, .cards.support { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rowlabel { display: none; }
  .tabs { margin-left: 0; flex-wrap: wrap; }
}
</style>
