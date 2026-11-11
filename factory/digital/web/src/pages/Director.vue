<!-- 情景导演（第 19 轮 J-5）：两周情景的时间线——开始、下一幕、自动演示、复盘；教师控制台。只在教学模式、只给老师。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('情景导演') }}</h1>
      <span class="muted">{{ $t('{a} · 一张急单串起七个领域', { a: $td(st?.scenario?.name) || $t('两周情景') }) }}</span>
      <span class="r small"><router-link to="/help/teach/director">{{ $t('怎么用') }}</router-link> · <router-link to="/help/docs/学校版演示脚本">{{ $t('学校版演示脚本') }}</router-link> · <router-link to="/help/docs/企业版演示脚本">{{ $t('企业版演示脚本') }}</router-link> · <router-link to="/help/docs/演示前检查表">{{ $t('检查表') }}</router-link></span></div><!-- i18n-ok 数据值比较 -->
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="!isTeacher" class="card empty">{{ $t('情景导演只给老师（教学模式）。学生在“实验与任务 → 实验 23”里跟着情景做决定。') }}</div>

    <template v-if="isTeacher && st">
      <section class="card dbar" data-help="dir-bar">
        <div class="ctl">
          <label class="small">{{ $t('倍速') }} <select v-model.number="speed" :aria-label="$t('车间倍速')"><option v-for="x in [10, 20, 30, 60, 120]" :key="x" :value="x">{{ x }}×</option></select></label>
          <label class="small" :title="$t('停机挂牌整改、保养到了预计时长还没人收尾，由“情景里的人”整改验收、保养完工，设备解锁。课堂上要学生自己收尾就关掉')"><input v-model="wrapup" type="checkbox"> {{ $t('自动收尾') }}</label>
          <button class="btn danger" :disabled="busy" @click="start">{{ run && run.status !== 'ended' ? $t('重新开始') : $t('开始两周情景') }}</button>
          <button class="btn primary" :disabled="busy || !st.next?.ok" @click="next">{{ $t('下一幕{a}', { a: st.next?.ok ? $t('（第 ') + st.next.n + $t(' 幕）') : '' }) }}</button>
          <button v-if="live && !st.order?.done && run?.so" class="btn" :disabled="busy" @click="ff(!run.ff)">{{ run.ff ? $t('停止快进') : $t('快进到订单做完') }}</button>
          <label class="small"><input type="checkbox" :checked="run?.auto" :disabled="!live" @change="auto($event.target.checked)"> {{ $t('自动演示') }}</label>
          <label class="small">{{ $t('每幕停') }} <input v-model.number="dwell" type="number" min="10" max="600" step="10" :aria-label="$t('每幕停留秒数')"> {{ $t('秒') }}</label>
          <button class="btn" :disabled="!run?.so" @click="loadReview(true)">{{ $t('复盘') }}</button>
          <button v-if="live" class="btn" @click="end">{{ $t('结束') }}</button>
        </div>
        <div class="facts small">
          <span v-if="!run" class="muted">{{ $t('还没开始。“开始”会清空教学模式的历史、重新载入实验 7 情景（约 10–20 秒），再把车间设到所选倍速。') }}</span>
          <template v-else>
            <span>{{ $t('状态：') }}<b>{{ RUN[run.status] || run.status }}</b>{{ run.auto ? $t('（自动演示中）') : '' }}</span>
            <span>{{ $t('已演') }} <b>{{ $td(run.beat_no) }}</b> {{ $t('/ {a} 幕', { a: $td(st.beats.length) }) }}</span>
            <span v-if="run.so">{{ $t('订单') }} <router-link :to="'/ont/o/SalesOrder/' + run.so">{{ $td(run.so) }}</router-link></span>
            <span v-if="st.order?.qty">{{ $t('车间') }} <b>{{ $td(st.order.parts) }} / {{ $td(st.order.qty) }}</b> {{ $t('根{a}', { a: st.order.done ? $t('（做完了）') : '' }) }}</span>
            <span>{{ $t('倍速 {a}', { a: run.ff ? run.ff_speed + $t('×（快进中，做完回到 ') + run.speed + $t('×）') : run.speed + '×' }) }}</span>
            <span v-if="st.next && !st.next.ok" class="warn-t">{{ $td(st.next.why) }}</span>
          </template>
          <span class="ok">{{ msg }}</span>
        </div>
        <p v-if="run?.wrap_log?.length" class="small muted">{{ $t('自动收尾：{a}', { a: run.wrap_log.join($t('；')) }) }}</p>
      </section>

      <ol class="timeline" data-help="dir-timeline">
        <li v-for="b in st.beats" :key="b.n" class="card beat" :class="[b.status, { cur: run && b.n === run.beat_no }]">
          <div class="bh">
            <span class="no">{{ $t('第 {a} 幕', { a: $td(b.n) }) }}</span><span class="day small muted">{{ $t('第 {a} 天', { a: $td(b.day) }) }}</span>
            <span class="dom small">{{ $td(b.domain_name) }}</span>
            <h2>{{ $td(b.title) }}</h2>
            <span class="stt small" :class="b.status">{{ $td(STT[b.status]) }}<template v-if="b.status === 'waiting'">{{ $t('（{a} 秒）', { a: $td(b.elapsed_s) }) }}</template></span>
          </div>
          <p class="story">{{ $td(b.story) }}</p>
          <p v-if="b.note" class="small note">{{ $td(b.note) }}</p>
          <p v-if="b.pending?.length" class="small warn-t">{{ $t('还在等：{a}', { a: b.pending.join($t('；')) }) }}</p>
          <div v-if="b.seen?.length" class="seen small">
            <span v-for="x in b.seen" :key="x.id || x.check" class="pill" :class="x.status === 'open' ? 'warn' : 'good'">
              <router-link v-if="x.id" :to="{ path: '/ont', query: { view: 'anomalies', a: x.id } }">{{ $td(x.rule) }} {{ $td(x.title) }}</router-link>
              <template v-else>✓ {{ $td(x.title) }}</template></span>
          </div>
          <details :open="run && (b.n === run.beat_no || b.n === run.beat_no + 1)">
            <summary class="small">{{ $t('讲解要点 · 去看') }}</summary>
            <ul class="small"><li v-for="t in b.talk" :key="t">{{ t }}</li></ul>
            <p class="small looks"><router-link v-for="l in b.look" :key="l.to" :to="l.to">{{ $td(l.label) }}</router-link></p>
            <p class="small muted">{{ $t('谁处理：{a} · 预计厂情中枢报：{b}', { a: b.roles.map((r) => ROLE[r] || r).join($t('、')), b: b.expect.map((e) => RULE[e] || e).join($t('、')) }) }}</p>
            <p v-if="b.link" class="small link">↓ {{ $td(b.link) }}</p>
          </details>
        </li>
      </ol>

      <section v-if="rv" class="card">
        <div class="card-head"><h2>{{ $t('复盘：{a} 这张订单', { a: $td(rv.sales_order) }) }}</h2><span class="small muted">{{ $t('{a} · 车间 {b} / {c} 根', { a: rv.customer.split(' ')[0], b: $td(rv.order.parts), c: $td(rv.order.qty) }) }}</span></div>
        <p v-for="t in rv.chain.summary" :key="t">{{ t }}</p>
        <template v-if="rv.margin">
          <table class="tbl small"><thead><tr><th>{{ $t('项') }}</th><th class="num">$</th><th>{{ $t('怎么算') }}</th></tr></thead>
            <tbody>
              <tr><td>{{ $t('收入') }}</td><td class="num">{{ num(rv.margin.revenue) }}</td><td>{{ $t('{a} 台 × 订单单价', { a: $td(rv.margin.qty) }) }}</td></tr>
              <tr v-for="l in rv.margin.lines" :key="l.key"><td>{{ $td(l.label) }}</td><td class="num">−{{ num(l.usd) }}</td><td>{{ $td(l.how) }}<template v-if="l.actions?.length">{{ $t('：{a}', { a: l.actions.map((a) => a.title + ' $' + num(a.usd)).join($t('；')) }) }}</template></td></tr>
              <tr><td><b>{{ $t('毛利') }}</b></td><td class="num"><b>{{ num(rv.margin.margin) }}</b></td><td>{{ $t('毛利率') }} <b>{{ pct1(rv.margin.margin_pct) }}</b>{{ $t('（按标准 {a}）', { a: pct1(rv.margin.std_margin_pct) }) }}</td></tr>
            </tbody></table>
        </template>
        <p v-else class="muted">{{ $t('订单还没做完，毛利还算不出来。') }}</p>
        <h3>{{ $t('每一幕花在这张订单上的钱') }}</h3>
        <table class="tbl small"><thead><tr><th>{{ $t('幕') }}</th><th>{{ $t('领域') }}</th><th>{{ $t('异常') }}</th><th>{{ $t('采纳的动作') }}</th><th class="num">{{ $t('记到订单（$）') }}</th></tr></thead>
          <tbody><tr v-for="b in rv.beats" :key="b.n" :class="{ top: b.n === rv.top_beat }">
            <td>{{ $td(b.n) }} {{ $td(b.title) }}</td><td>{{ $td(b.domain_name) }}</td>
            <td>{{ b.anomalies.filter((x) => x.id).map((x) => x.rule).join($t('、')) || '—' }}</td>
            <td>{{ b.actions.map((a) => a.title + $t('（') + (ACT[a.status] || a.status) + $t('）')).join($t('；')) || '—' }}</td>
            <td class="num">{{ num(b.cost + (b.idle_usd || 0)) }}</td></tr></tbody></table>
        <p v-if="rv.invoice" class="small">{{ $t('这张订单的发票 {a}：${b}，{c}{d}。', { a: rv.invoice.doc || $t('（开票中）'), b: num(rv.invoice.amount), c: $td(rv.invoice.status_name), d: rv.invoice.dunned_n ? $t('，催过 ') + rv.invoice.dunned_n + $t(' 次') : '' }) }}</p>
        <h3>{{ $t('跨领域因果链') }}</h3>
        <div v-if="rv.chain.nodes.length > 1" class="cgbox"><ChainGraph :chain="rv.chain" /></div>
        <details v-if="rv.report"><summary>{{ $t('两周的周报（{a}）', { a: rv.report.at.slice(0, 16).replace('T', ' ') }) }}</summary><pre class="rep">{{ $td(rv.report.text) }}</pre></details>
      </section>

      <TeacherConsole data-help="dir-console" />
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { get, post, session } from '../lib/api';
import ChainGraph from '../components/ChainGraph.vue';
import TeacherConsole from '../components/TeacherConsole.vue';

const RUN = { loading: $t('载入实验 7 情景'), ready: $t('可以演'), ended: $t('已结束') };
const STT = { todo: $t('没演'), waiting: $t('等厂情中枢'), ok: $t('✓ 出来了'), timeout: $t('超时（可以先往下演）') };
const ROLE = { planner: $t('计划员'), quality: $t('质量'), lead: $t('班组长'), safety: $t('安全员'), maintenance: $t('维修'), sales: $t('销售'), manager: $t('厂长') };
const RULE = { order_released: $t('订单写进 ERPNext、下达车间'), W1: $t('缺料'), W3: $t('来料不合格'), H2: $t('排班缺口'), E1: $t('重大隐患'), M2: $t('保养逾期'), N2: $t('空转能耗高'), F2: $t('应收逾期') };
const ACT = { draft: $t('草稿'), submitted: $t('待批准'), approved: $t('已批准'), rejected: $t('已驳回'), executing: $t('执行中'), done: $t('已完成'), failed: $t('失败') };
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
  if (live.value && !confirm($t('重新开始会清空教学模式的历史、重新载入实验 7 情景。继续？'))) return;
  if (!live.value && !confirm($t('开始会清空教学模式的历史、重新载入实验 7 情景（学生的得分保留）。继续？'))) return;
  rv.value = null;
  act(() => post('/story/start', { speed: speed.value, wrapup: wrapup.value }), $t('已开始：车间正在载入实验 7 情景'));
}
function next() { act(() => post('/story/next', {}), $t('已执行，厂情中枢 20 秒内出异常')); }
function auto(on) { act(() => post('/story/auto', { on, dwell_s: dwell.value }), on ? $t('自动演示：每一幕的异常出来后停 ') + dwell.value + $t(' 秒进下一幕') : $t('自动演示已停')); }
function ff(on) { act(() => post('/story/ff', { on }), on ? $t('快进中：车间临时提到 300×，订单做完自动回到原来的倍速') : $t('已停止快进')); }
function end() { if (confirm($t('结束这次情景？'))) act(() => post('/story/end', {}), $t('已结束')); }
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
