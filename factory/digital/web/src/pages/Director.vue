<!-- 情景导演（第 19 轮 J-5）：两周情景的时间线——开始、下一幕、自动演示、复盘；教师控制台。只在教学模式、只给老师。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>情景导演</h1>
      <span class="muted">{{ st?.scenario?.name || '两周情景' }} · 一张急单串起七个领域</span>
      <span class="r small"><router-link to="/help/teach/director">怎么用</router-link> · <router-link to="/help/docs/学校版演示脚本">学校版演示脚本</router-link> · <router-link to="/help/docs/企业版演示脚本">企业版演示脚本</router-link> · <router-link to="/help/docs/演示前检查表">检查表</router-link></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="!isTeacher" class="card empty">情景导演只给老师（教学模式）。学生在“实验与任务 → 实验 23”里跟着情景做决定。</div>

    <template v-if="isTeacher && st">
      <section class="card dbar" data-help="dir-bar">
        <div class="ctl">
          <label class="small">倍速 <select v-model.number="speed" aria-label="车间倍速"><option v-for="x in [10, 20, 30, 60, 120]" :key="x" :value="x">{{ x }}×</option></select></label>
          <label class="small" title="停机挂牌整改、保养到了预计时长还没人收尾，由“情景里的人”整改验收、保养完工，设备解锁。课堂上要学生自己收尾就关掉"><input v-model="wrapup" type="checkbox"> 自动收尾</label>
          <button class="btn danger" :disabled="busy" @click="start">{{ run && run.status !== 'ended' ? '重新开始' : '开始两周情景' }}</button>
          <button class="btn primary" :disabled="busy || !st.next?.ok" @click="next">下一幕{{ st.next?.ok ? '（第 ' + st.next.n + ' 幕）' : '' }}</button>
          <button v-if="live && !st.order?.done && run?.so" class="btn" :disabled="busy" @click="ff(!run.ff)">{{ run.ff ? '停止快进' : '快进到订单做完' }}</button>
          <label class="small"><input type="checkbox" :checked="run?.auto" :disabled="!live" @change="auto($event.target.checked)"> 自动演示</label>
          <label class="small">每幕停 <input v-model.number="dwell" type="number" min="10" max="600" step="10" aria-label="每幕停留秒数"> 秒</label>
          <button class="btn" :disabled="!run?.so" @click="loadReview(true)">复盘</button>
          <button v-if="live" class="btn" @click="end">结束</button>
        </div>
        <div class="facts small">
          <span v-if="!run" class="muted">还没开始。“开始”会清空教学模式的历史、重新载入实验 7 情景（约 10–20 秒），再把车间设到所选倍速。</span>
          <template v-else>
            <span>状态：<b>{{ RUN[run.status] || run.status }}</b>{{ run.auto ? '（自动演示中）' : '' }}</span>
            <span>已演 <b>{{ run.beat_no }}</b> / {{ st.beats.length }} 幕</span>
            <span v-if="run.so">订单 <router-link :to="'/ont/o/SalesOrder/' + run.so">{{ run.so }}</router-link></span>
            <span v-if="st.order?.qty">车间 <b>{{ st.order.parts }} / {{ st.order.qty }}</b> 根{{ st.order.done ? '（做完了）' : '' }}</span>
            <span>倍速 {{ run.ff ? run.ff_speed + '×（快进中，做完回到 ' + run.speed + '×）' : run.speed + '×' }}</span>
            <span v-if="st.next && !st.next.ok" class="warn-t">{{ st.next.why }}</span>
          </template>
          <span class="ok">{{ msg }}</span>
        </div>
        <p v-if="run?.wrap_log?.length" class="small muted">自动收尾：{{ run.wrap_log.join('；') }}</p>
      </section>

      <ol class="timeline" data-help="dir-timeline">
        <li v-for="b in st.beats" :key="b.n" class="card beat" :class="[b.status, { cur: run && b.n === run.beat_no }]">
          <div class="bh">
            <span class="no">第 {{ b.n }} 幕</span><span class="day small muted">第 {{ b.day }} 天</span>
            <span class="dom small">{{ b.domain_name }}</span>
            <h2>{{ b.title }}</h2>
            <span class="stt small" :class="b.status">{{ STT[b.status] }}<template v-if="b.status === 'waiting'">（{{ b.elapsed_s }} 秒）</template></span>
          </div>
          <p class="story">{{ b.story }}</p>
          <p v-if="b.note" class="small note">{{ b.note }}</p>
          <p v-if="b.pending?.length" class="small warn-t">还在等：{{ b.pending.join('；') }}</p>
          <div v-if="b.seen?.length" class="seen small">
            <span v-for="x in b.seen" :key="x.id || x.check" class="pill" :class="x.status === 'open' ? 'warn' : 'good'">
              <router-link v-if="x.id" :to="{ path: '/ont', query: { view: 'anomalies', a: x.id } }">{{ x.rule }} {{ x.title }}</router-link>
              <template v-else>✓ {{ x.title }}</template></span>
          </div>
          <details :open="run && (b.n === run.beat_no || b.n === run.beat_no + 1)">
            <summary class="small">讲解要点 · 去看</summary>
            <ul class="small"><li v-for="t in b.talk" :key="t">{{ t }}</li></ul>
            <p class="small looks"><router-link v-for="l in b.look" :key="l.to" :to="l.to">{{ l.label }}</router-link></p>
            <p class="small muted">谁处理：{{ b.roles.map((r) => ROLE[r] || r).join('、') }} · 预计厂情中枢报：{{ b.expect.map((e) => RULE[e] || e).join('、') }}</p>
            <p v-if="b.link" class="small link">↓ {{ b.link }}</p>
          </details>
        </li>
      </ol>

      <section v-if="rv" class="card">
        <div class="card-head"><h2>复盘：{{ rv.sales_order }} 这张订单</h2><span class="small muted">{{ rv.customer.split(' ')[0] }} · 车间 {{ rv.order.parts }} / {{ rv.order.qty }} 根</span></div>
        <p v-for="t in rv.chain.summary" :key="t">{{ t }}</p>
        <template v-if="rv.margin">
          <table class="tbl small"><thead><tr><th>项</th><th class="num">$</th><th>怎么算</th></tr></thead>
            <tbody>
              <tr><td>收入</td><td class="num">{{ num(rv.margin.revenue) }}</td><td>{{ rv.margin.qty }} 台 × 订单单价</td></tr>
              <tr v-for="l in rv.margin.lines" :key="l.key"><td>{{ l.label }}</td><td class="num">−{{ num(l.usd) }}</td><td>{{ l.how }}<template v-if="l.actions?.length">：{{ l.actions.map((a) => a.title + ' $' + num(a.usd)).join('；') }}</template></td></tr>
              <tr><td><b>毛利</b></td><td class="num"><b>{{ num(rv.margin.margin) }}</b></td><td>毛利率 <b>{{ pct1(rv.margin.margin_pct) }}</b>（按标准 {{ pct1(rv.margin.std_margin_pct) }}）</td></tr>
            </tbody></table>
        </template>
        <p v-else class="muted">订单还没做完，毛利还算不出来。</p>
        <h3>每一幕花在这张订单上的钱</h3>
        <table class="tbl small"><thead><tr><th>幕</th><th>领域</th><th>异常</th><th>采纳的动作</th><th class="num">记到订单（$）</th></tr></thead>
          <tbody><tr v-for="b in rv.beats" :key="b.n" :class="{ top: b.n === rv.top_beat }">
            <td>{{ b.n }} {{ b.title }}</td><td>{{ b.domain_name }}</td>
            <td>{{ b.anomalies.filter((x) => x.id).map((x) => x.rule).join('、') || '—' }}</td>
            <td>{{ b.actions.map((a) => a.title + '（' + (ACT[a.status] || a.status) + '）').join('；') || '—' }}</td>
            <td class="num">{{ num(b.cost + (b.idle_usd || 0)) }}</td></tr></tbody></table>
        <p v-if="rv.invoice" class="small">这张订单的发票 {{ rv.invoice.doc || '（开票中）' }}：${{ num(rv.invoice.amount) }}，{{ rv.invoice.status_name }}{{ rv.invoice.dunned_n ? '，催过 ' + rv.invoice.dunned_n + ' 次' : '' }}。</p>
        <h3>跨领域因果链</h3>
        <div v-if="rv.chain.nodes.length > 1" class="cgbox"><ChainGraph :chain="rv.chain" /></div>
        <details v-if="rv.report"><summary>两周的周报（{{ rv.report.at.slice(0, 16).replace('T', ' ') }}）</summary><pre class="rep">{{ rv.report.text }}</pre></details>
      </section>

      <TeacherConsole data-help="dir-console" />
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { get, post, session } from '../lib/api';
import ChainGraph from '../components/ChainGraph.vue';
import TeacherConsole from '../components/TeacherConsole.vue';

const RUN = { loading: '载入实验 7 情景', ready: '可以演', ended: '已结束' };
const STT = { todo: '没演', waiting: '等厂情中枢', ok: '✓ 出来了', timeout: '超时（可以先往下演）' };
const ROLE = { planner: '计划员', quality: '质量', lead: '班组长', safety: '安全员', maintenance: '维修', sales: '销售', manager: '厂长' };
const RULE = { order_released: '订单写进 ERPNext、下达车间', W1: '缺料', W3: '来料不合格', H2: '排班缺口', E1: '重大隐患', M2: '保养逾期', N2: '空转能耗高', F2: '应收逾期' };
const ACT = { draft: '草稿', submitted: '待批准', approved: '已批准', rejected: '已驳回', executing: '执行中', done: '已完成', failed: '失败' };
const st = ref(null);
const rv = ref(null);
const err = ref('');
const msg = ref('');
const busy = ref(false);
const speed = ref(30);
const dwell = ref(90);
const wrapup = ref(true);
const isTeacher = computed(() => session.user?.mode === 'teach' && session.user?.teacher);
const run = computed(() => st.value?.run);
const live = computed(() => run.value && run.value.status !== 'ended');
const num = (v) => (v === null || v === undefined ? '—' : Math.round(v).toLocaleString());
const pct1 = (v) => (v === null || v === undefined ? '—' : (v * 100).toFixed(1) + '%');
let timer;

async function load() {
  if (!isTeacher.value) return;
  try { st.value = await get('/story/state'); err.value = ''; if (run.value?.dwell_s) dwell.value = run.value.dwell_s; } catch (e) { err.value = e.message; }
}
async function act(fn, text) {
  busy.value = true;
  try { st.value = await fn(); msg.value = text || ''; err.value = ''; } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
function start() {
  if (live.value && !confirm('重新开始会清空教学模式的历史、重新载入实验 7 情景。继续？')) return;
  if (!live.value && !confirm('开始会清空教学模式的历史、重新载入实验 7 情景（学生的得分保留）。继续？')) return;
  rv.value = null;
  act(() => post('/story/start', { speed: speed.value, wrapup: wrapup.value }), '已开始：车间正在载入实验 7 情景');
}
function next() { act(() => post('/story/next', {}), '已执行，厂情中枢 20 秒内出异常'); }
function auto(on) { act(() => post('/story/auto', { on, dwell_s: dwell.value }), on ? '自动演示：每一幕的异常出来后停 ' + dwell.value + ' 秒进下一幕' : '自动演示已停'); }
function ff(on) { act(() => post('/story/ff', { on }), on ? '快进中：车间临时提到 300×，订单做完自动回到原来的倍速' : '已停止快进'); }
function end() { if (confirm('结束这次情景？')) act(() => post('/story/end', {}), '已结束'); }
async function loadReview(report) {
  try { rv.value = await get('/story/review' + (report ? '?report=1' : '')); } catch (e) { err.value = e.message; }
}
onMounted(() => { load(); timer = setInterval(load, 5000); });
onBeforeUnmount(() => clearInterval(timer));
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.r { margin-left: auto; }
.dbar { display: flex; flex-direction: column; gap: 8px; position: sticky; top: 0; z-index: 2; }
.ctl { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.ctl select, .ctl input[type=number] { height: 32px; border: 1px solid var(--line); border-radius: 6px; padding: 0 6px; }
.ctl input[type=number] { width: 70px; }
.facts { display: flex; gap: 14px; flex-wrap: wrap; align-items: center; }
.timeline { list-style: none; padding: 0; margin: 12px 0; display: flex; flex-direction: column; gap: 10px; }
.beat { border-left: 4px solid var(--line); }
.beat.ok { border-left-color: var(--good); }
.beat.waiting { border-left-color: var(--warn); }
.beat.timeout { border-left-color: var(--bad); }
.beat.cur { box-shadow: 0 0 0 2px var(--accent); }
.bh { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.bh h2 { margin: 0; font-size: 17px; }
.no { font-weight: 700; }
.dom { background: var(--surface-2); border-radius: 10px; padding: 1px 8px; }
.stt { margin-left: auto; }
.stt.ok { color: var(--good); }
.stt.waiting { color: var(--warn); }
.stt.timeout { color: var(--bad); }
.story { margin: 6px 0; }
.note { background: var(--surface-2); border-radius: 6px; padding: 4px 8px; }
.seen { display: flex; gap: 6px; flex-wrap: wrap; margin: 4px 0; }
.seen .pill { white-space: normal; max-width: 100%; }
.looks { display: flex; gap: 12px; flex-wrap: wrap; }
.link { color: var(--accent); }
.tbl { width: 100%; }
tr.top td { background: #FFF6E5; font-weight: 600; }
.cgbox { height: 480px; }
.rep { white-space: pre-wrap; font-size: 12px; background: var(--surface-2); padding: 8px; border-radius: 6px; }
.ok { color: var(--good); }
.warn-t { color: var(--warn); }
@media (max-width: 700px) { .stt { margin-left: 0; } .tbl { display: block; overflow-x: auto; } }
</style>
