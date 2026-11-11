<template>
  <div class="page">
    <div v-if="error" class="card err">{{ t('看板数据取不到：{e}（检查枢纽服务与历史库是否在运行）', { e: error }) }}</div>
    <div v-if="!ov && !error" class="muted">{{ t('正在从历史库计算…') }}</div>
    <template v-if="ov">
      <TaskBar v-if="ov.teach" :t="ov.teach" />
      <div v-if="ov.demo" class="demo small">{{ t('含“实验 7”教学情景的演示数据（订单、库存等由情景生成，不在 ERPNext 里）。教师可在“情景导演”的教师控制台重置或清空。') }}</div>

      <!-- 厂情中枢提醒条（第 17 轮 D 期 D6）：严重异常和带处理预案的异常；教学模式的学生不显示（实验 7 要自己从看板里找） -->
      <router-link v-for="b in banner" :key="b.id" :to="b.url" class="ont-banner" :class="b.severity">
        <b>{{ b.severity === 'critical' ? t('严重') : t('注意') }}</b><span>{{ td(b.text) }}</span><span class="go">{{ t('去处理 →') }}</span>
      </router-link>

      <!-- AI 今日简报 -->
      <section class="card brief" data-help="home-brief" :aria-label="t('AI 今日简报')">
        <div class="brief-main">
          <div class="brief-head">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/></svg>
            <h2>{{ t('AI 今日简报') }}{{ teach ? ' · ' + t('教学模式只提示方向') : '' }}</h2>
            <span class="muted small">{{ t('{t} 更新 · 依据统一数据总线', { t: briefTime }) }}</span>
            <button class="link small" @click="refreshBrief">{{ t('重新生成') }}</button>
          </div>
          <div v-if="!brief" class="muted small">{{ t('还没有简报：AI 每 20 秒巡检一次全厂，稍等片刻或点“重新生成”。') }}</div>
          <div v-for="(b, i) in brief?.items || []" :key="i" class="brief-item">
            <span class="dot" :style="{ background: toneColor(b.tone) }"></span>
            <div>
              <div class="brief-text">{{ td(b.text) }}</div>
              <div class="src">{{ t('来源：') }}{{ srcText(b.evidence) }}</div>
            </div>
          </div>
        </div>
        <form class="brief-ask" @submit.prevent="askAi">
          <label for="ask" class="muted small">{{ t('问 AI 工厂助手') }}</label>
          <input id="ask" v-model="q" :placeholder="teach ? t('例如：我下一步做什么？') : t('例如：哪张订单会延期？为什么？')">
          <div class="chips">
            <button v-for="c in chips" :key="c" type="button" class="chip" @click="ask(t(c))">{{ t(c) }}</button>
          </div>
        </form>
      </section>

      <!-- 关键指标 -->
      <section class="kpis" data-help="home-kpis" :aria-label="t('关键指标')">
        <div v-for="k in ov.kpis" :key="k.key" class="card kpi" :class="{ focus: focus.kpis.includes(k.key) }">
          <span class="muted small">{{ k.label }}</span>
          <span class="mono kv">{{ kpiValue(k) }}</span>
          <span class="small" :style="{ color: toneColor(k.tone) }">{{ k.note }}</span>
        </div>
      </section>

      <!-- 车间实况 + 订单与交期 -->
      <div class="row">
        <section class="card shop" data-help="home-shop" :class="{ focus: focus.shop }" :aria-label="t('车间实况')">
          <div class="card-head">
            <h2>{{ t('车间实况') }}</h2>
            <div class="legend small muted">
              <span v-for="s in ['run', 'idle', 'setup', 'down']" :key="s"><i :style="{ background: STATE[s].color }"></i>{{ STATE[s].label }} {{ counts[s] || 0 }}</span>
            </div>
            <router-link to="/3d" class="more">{{ t('进入 3D 车间 →') }}</router-link>
          </div>
          <div class="machines">
            <!-- 点哪看哪（第 30 轮 §八）：点设备弹出此刻状态、对应帮助；车间终端在弹窗里 -->
            <div v-for="m in machines" :key="m.unit" role="button" tabindex="0" :aria-expanded="picked === m.unit"
              class="mcard" :class="{ down: ['down', 'fault'].includes(m.state), on: picked === m.unit }"
              @click="pickM(m.unit)" @keydown.enter.self.prevent="pickM(m.unit)" @keydown.space.self.prevent="pickM(m.unit)">
              <div class="mtop">
                <span class="mono b">{{ m.code }}</span>
                <span class="pill" :style="{ color: STATE[m.state].color, background: STATE[m.state].bg }">{{ STATE[m.state].label }}</span>
              </div>
              <span class="muted small">{{ nm(m) }}<span v-if="m.bottleneck" class="bn">{{ t('瓶颈') }}</span></span>
              <span class="job">{{ jobText(m) }}</span>
              <div class="bar"><div :style="{ width: Math.round((m.progress || 0) * 100) + '%', background: STATE[m.state].color }"></div></div>
              <div v-if="focus.dispatch && m.dispatched?.length" class="disp small">
                <div v-for="d in m.dispatched" :key="d.work_order + d.operation">
                  {{ d.work_order.slice(-5) }} {{ opText(d.operation) }} {{ d.done }}/{{ d.qty }} {{ d.started ? t('已开工') : t('待开工') }}
                </div>
              </div>
              <div v-if="picked === m.unit" class="pop small" role="dialog" :aria-label="m.code + ' ' + nm(m)" @click.stop>
                <b>{{ m.code }} {{ nm(m) }}</b>
                <span><span class="pill" :style="{ color: pinfo.color, background: pinfo.bg }">{{ pinfo.label }}</span>
                  <span v-if="pinfo.reason" class="muted"> {{ td(pinfo.reason) }}</span></span>
                <span v-if="pinfo.tags.length" class="ptags"><span v-for="t in pinfo.tags" :key="t.text" :class="t.tone">{{ t.text }}</span></span>
                <span v-if="pinfo.help.domain" class="muted">{{ t('领域：') }}{{ pinfo.help.domain }}</span>
                <router-link :to="{ path: '/work/operator', query: { unit: m.unit } }">{{ t('打开车间终端 →') }}</router-link>
                <router-link :to="pinfo.help.to">{{ pinfo.help.label }} →</router-link>
              </div>
            </div>
          </div>
          <div class="agv small muted">
            <span v-for="a in agvs" :key="a.unit"><ObjLink type="Agv" :k="a.unit">{{ a.unit.toUpperCase() }}</ObjLink>: <template v-if="a.task">{{ t('运送') }} <ObjLink type="PartSerial" :k="a.load" mono /> ({{ td(a.task) }})</template><template v-else>{{ t('待命 · 电量 {p}%', { p: Math.round((a.battery || 0) * 100) }) }}</template></span>
            <span class="r">{{ t('在制品 {n} 件', { n: ov.wip.now }) }}<template v-if="bott"> · {{ t('{c} 前排队 {n} 件', { c: bott.code, n: bott.queue }) }}</template></span>
          </div>
        </section>

        <section class="card orders" data-help="home-orders" :class="{ focus: focus.orders }" :aria-label="t('订单与交期')">
          <div class="card-head"><h2>{{ t('订单与交期') }}</h2><a :href="erpUrl" target="_blank" class="more">ERPNext →</a></div>
          <div v-if="!ov.orders.length" class="empty">{{ t('没有在手订单') }}</div>
          <div v-for="o in ov.orders" :key="o.name" class="order">
            <div class="otop">
              <ObjLink type="SalesOrder" :k="o.name" mono class="b" />
              <ObjLink type="Customer" :k="o.customer">{{ isEn() ? bi(o.customer) : short(o.customer) }}</ObjLink>
              <span class="pill" :class="o.tone" :title="o.risk">{{ o.risk }}</span>
            </div>
            <span class="muted small">{{ o.item }} × {{ o.qty }} · {{ t('交期 {d}', { d: o.delivery_date.slice(5) }) }} · {{ o.work_orders }}</span>
            <div class="bar"><div :style="{ width: Math.max(2, o.progress * 100) + '%', background: toneColor(o.tone) }"></div></div>
          </div>
        </section>
      </div>

      <!-- 计划与实际 / 质量 / 物料 -->
      <div class="three">
        <section class="card" :aria-label="t('生产计划与实际')">
          <div class="card-head"><h2>{{ t('本周计划与实际') }}</h2><span class="muted small">{{ t('{i} 完工件数', { i: ov.week.item }) }}</span></div>
          <div class="bars">
            <div v-for="d in ov.week.days" :key="d.date" class="day">
              <span class="mono small muted">{{ d.actual === null ? '—' : d.actual }} / {{ d.plan }}</span>
              <div class="pair">
                <div class="plan" :style="{ height: h(d.plan) + 'px' }"></div>
                <div class="act" :style="{ height: h(d.actual || 0) + 'px' }"></div>
              </div>
            </div>
          </div>
          <div class="days"><span v-for="d in ov.week.days" :key="d.date" class="small muted">{{ d.day }}</span></div>
          <div class="legend small muted">
            <span><i class="lp"></i>{{ t('计划') }}</span><span><i :style="{ background: 'var(--accent)' }"></i>{{ t('实际') }}</span>
            <span class="r">{{ t('瓶颈工序：') }}{{ ov.week.bottleneck ? nm(ov.week, 'bottleneck_name') + ' ' + ov.week.bottleneck.toUpperCase() : '—' }}</span>
          </div>
        </section>

        <section class="card" data-help="home-quality" :class="{ focus: focus.quality }" :aria-label="t('质量')">
          <div class="card-head"><h2>{{ t('质量') }}</h2><span class="muted small">{{ td(ov.quality.chart.title) }} · {{ t('最近 {n} 件', { n: ov.quality.chart.points.length }) }}</span></div>
          <ControlChart v-if="ov.quality.chart.points.length" :chart="ov.quality.chart" />
          <div v-else class="empty">{{ t('还没有测量数据') }}</div>
          <div class="q3">
            <div><span class="muted small">{{ t('本周一次合格率') }}</span><b class="mono">{{ pct(ov.quality.fpy_week.value, 1) }}</b></div>
            <div><span class="muted small">{{ t('待处理不合格品') }}</span><b class="mono">{{ ov.quality.ncr_open }}</b></div>
            <div><span class="muted small">{{ t('今日检验') }}</span><b class="mono">{{ t('{n} 件', { n: ov.quality.inspected_today }) }}</b></div>
          </div>
        </section>

        <section class="card" :class="{ focus: focus.materials }" :aria-label="t('物料')">
          <div class="card-head"><h2>{{ t('关键物料') }}</h2><span class="muted small">{{ t('库存 · 在途 · 可用天数') }}</span></div>
          <div v-for="x in ov.materials" :key="x.code" class="mat">
            <div class="mname"><span class="mono b small">{{ x.code }}</span><span class="muted small">{{ nm(x) }}</span></div>
            <span class="mono">{{ x.qty_text }}</span>
            <span class="pill" :class="x.tone">{{ x.status }}</span>
          </div>
        </section>
      </div>

      <!-- 提醒与待办 -->
      <section class="card" :aria-label="t('提醒与待办')">
        <div class="card-head"><h2>{{ t('提醒与待办') }}</h2><span class="muted small">{{ roleName(session.user.role) }} · {{ teach ? t('实验任务') : t('按优先级') }}</span></div>
        <div v-if="!ov.todos.length" class="empty">{{ t('现在没有需要你处理的事。') }}</div>
        <div v-for="(x, i) in ov.todos" :key="i" class="todo">
          <span class="pill" :class="x.tone">{{ td(x.kind) }}</span>
          <span class="ttext">{{ td(x.text) }}<span v-if="x.hint" class="muted small"> · {{ t('建议：') }}{{ td(x.hint) }}</span></span>
          <span class="src">{{ todoSrc(x.src) }}</span>
          <button class="btn" @click="act(x)">{{ td(x.act) }}</button>
        </div>
      </section>
    </template>
    <ProposalModal v-if="pid" :pid="pid" @close="pid = null; load()" @done="load" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { get, post, roleName, session } from '../lib/api';
import { bus } from '../lib/bus';
import { useOverview } from '../lib/overview';
import { ask as aiAsk } from '../lib/ai';
import { kpiValue, opShort, pct, short, STATE, TONE, timeOf } from '../lib/fmt';
import { machineInfo } from '../lib/machinfo';
import ControlChart from '../components/ControlChart.vue';
import ProposalModal from '../components/ProposalModal.vue';
import TaskBar from '../components/TaskBar.vue';
import ObjLink from '../components/ObjLink.vue';
import { bi, isEn, nm, t, td, tk } from '../lib/i18n';
// 工序名“中文 English”：英文界面取英文部分
const opText = (s) => (isEn() ? bi(s || '') : opShort(s));

const router = useRouter();
const { ov, error, load, machines } = useOverview();
const q = ref('');
const pid = ref(null);
const teach = computed(() => session.user.mode === 'teach');
const brief = computed(() => ov.value?.briefing?.data);
const briefTime = computed(() => (ov.value?.briefing ? timeOf(ov.value.briefing.ts).slice(-5) : '—'));
const chips = computed(() => (teach.value ? [tk('MRP 是什么？'), tk('安全库存怎么定？'), tk('我下一步做什么？')]
  : [tk('哪张订单会延期？'), tk('本周瓶颈在哪？'), tk('成本为什么超标？')]));
const counts = computed(() => machines.value.reduce((a, m) => { a[m.state] = (a[m.state] || 0) + 1; return a; }, {}));
const bott = computed(() => machines.value.find((m) => m.bottleneck && m.queue));
const agvs = computed(() => (ov.value?.agvs || []).map((a) => ({ ...a, ...(bus.agvs[a.unit] || {}) })));
const erpUrl = computed(() => session.config?.erpnext_url || '#');
const FOCUS = {
  manager: { kpis: ['on_time', 'cost'], orders: true },
  planner: { kpis: ['on_time', 'output'], orders: true, materials: true },
  quality: { kpis: ['fpy'], quality: true },
  operator: { kpis: ['oee'], shop: true, dispatch: true },
  engineer: { kpis: ['oee', 'fpy'], quality: true },
};
const focus = computed(() => ({ kpis: [], ...(FOCUS[session.user.role] || {}) }));
const maxPlan = computed(() => Math.max(1, ...(ov.value?.week.days || []).map((d) => Math.max(d.plan, d.actual || 0))));
const h = (v) => Math.round((v / maxPlan.value) * 100);
const toneColor = (t) => TONE[t] || 'var(--muted)';

function jobText(m) {
  if (m.state === 'down' || m.state === 'fault') {
    return `${m.locked ? '🔒 ' : ''}${td(m.reason) || t('停机')} · ` + t('已停 {m} 分钟 · 排队 {q} 件', { m: Math.round((m.down_for_s || 0) / 60), q: m.queue || 0 });
  }
  if (m.no_staff) return '👤 ' + t('这一班没人能开（缺人）· 排队 {q} 件', { q: m.queue || 0 });      // 第 18 轮 E4
  if (!m.work_order) return m.state === 'idle' ? t('等待派工') : '';
  return `${m.item || ''} ${opText(m.operation)} · ` + t('第 {i} / {n} 件', { i: Math.min(m.qty_done + (m.state === 'run' ? 1 : 0), m.qty), n: m.qty })
    + (m.job_started ? '' : ' · ' + t('待开工')) + (m.staff_level === 1 ? ' · ' + t('学徒带着开') : '');
}
// 待办来源“Lab 7 · 任务名”（枢纽已把“实验 7”换成英文）：任务名按英文表译（第 130 轮第二批）
const todoSrc = (s) => { const m = /^(Lab 7 · |实验 7 · )(.+)$/.exec(s || ''); return m ? (isEn() ? 'Lab 7 · ' : '实验 7 · ') + td(m[2]) : td(s); };   // i18n-ok 识别枢纽给的前缀
function srcText(ev) {
  if (!ev || !ev.length) return t('全厂汇总');
  const e = ev[0];
  const tp = (e.topic || '').replace('wq/gearbox/', '');
  return tp + (e.name ? ' · ' + bi(e.name) : e.item ? ' · ' + e.item : e.ts ? ' · ' + timeOf(e.ts) : '') + (ev.length > 1 ? ' ' + t('（等 {n} 条）', { n: ev.length }) : '');
}
const banner = ref([]);
async function loadBanner() {
  if (teach.value && !session.user.teacher) { banner.value = []; return; }
  try { banner.value = (await get('/ont/banner')).items; } catch { banner.value = []; }
}
let bannerTimer = null;
onMounted(() => { loadBanner(); bannerTimer = setInterval(loadBanner, 30000); });
onUnmounted(() => clearInterval(bannerTimer));

// 点哪看哪（第 30 轮 §八 8-1）：设备的此刻状态 + 对应帮助章节；标准保养周期取自 /api/layout（第一次点时取）
const picked = ref(null);
const units = ref(null);
const prisk = ref(null);
const isDemo = () => session.config?.plant?.demo !== false;
const pinfo = computed(() => {
  const m = machines.value.find((x) => x.unit === picked.value);
  return machineInfo(m, units.value?.[picked.value], isDemo(), prisk.value?.unit === picked.value ? prisk.value : null);
});
async function pickM(unit) {
  picked.value = picked.value === unit ? null : unit;
  prisk.value = null;
  if (!picked.value) return;
  if (!units.value) units.value = await get('/layout').then((L) => L.units).catch(() => ({}));
  if (isDemo() && units.value?.[unit]?.pm_h) get('/maint/risk/' + unit).then((r) => { if (picked.value === unit) prisk.value = r; }).catch(() => {});
}
// 点卡片外面、按 Esc 收起弹窗
const closePick = (e) => { if (picked.value && (e.key === 'Escape' || (e.type === 'click' && !e.target.closest?.('.mcard')))) picked.value = null; };
onMounted(() => { document.addEventListener('click', closePick); document.addEventListener('keydown', closePick); });
onUnmounted(() => { document.removeEventListener('click', closePick); document.removeEventListener('keydown', closePick); });
function ask(s) { aiAsk(s); }
function askAi() { const s = q.value; q.value = ''; aiAsk(s); }
async function refreshBrief() { await post('/ai/briefing/refresh'); load(); }
function act(x) {
  if (x.proposal_id) pid.value = x.proposal_id;
  else if (x.link) router.push(x.link);
  else aiAsk(t('请解释这条提醒并告诉我怎么处理：') + x.text);
}
</script>

<style scoped>
.demo { background: var(--accent-bg); color: var(--accent); border-radius: 8px; padding: 8px 12px; }
.brief { display: flex; gap: 20px; }
.brief-main { display: flex; flex-direction: column; gap: 10px; flex-grow: 1; }
.brief-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.link { border: 0; background: none; color: var(--accent); cursor: pointer; padding: 0; }
.brief-item { display: flex; gap: 12px; align-items: baseline; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; position: relative; top: -1px; }
.ont-banner { display: flex; gap: 10px; align-items: center; padding: 10px 14px; border-radius: 10px; margin-bottom: 10px; text-decoration: none;
  background: #FFF6E5; border: 1px solid #F2C46D; color: #6B4500; font-size: 13px; }
.ont-banner.critical { background: #FDECEA; border-color: #E8A39B; color: #8A1F14; }
.ont-banner .go { margin-left: auto; white-space: nowrap; font-weight: 500; }
.brief-text { font-size: 14px; line-height: 1.55; }
.brief-ask { width: 320px; flex-shrink: 0; display: flex; flex-direction: column; gap: 8px; justify-content: flex-end; }
.brief-ask input { height: 40px; border: 1px solid #C8CEC7; border-radius: 8px; padding: 0 12px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip { height: 28px; padding: 0 10px; border-radius: 14px; border: 1px solid var(--line); background: var(--surface-2); font-size: 12px; cursor: pointer; }
.kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.kpi { padding: 14px 16px; display: flex; flex-direction: column; gap: 6px; }
.kv { font-size: 26px; font-weight: 600; line-height: 1.1; }
.focus { box-shadow: inset 3px 0 0 var(--brand); }
.shop { flex-grow: 1; min-width: 0; }
.legend { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
.legend i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; margin-right: 5px; }
.legend .lp { border: 1.5px solid #8C96A0; background: #fff; box-sizing: border-box; width: 10px; height: 10px; }
.legend .r, .agv .r { margin-left: auto; }
.machines { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.mcard { display: flex; flex-direction: column; gap: 5px; padding: 10px 12px; border-radius: 8px; border: 1px solid #E1E5DF;
  background: #FBFBF9; color: inherit; text-decoration: none; }
.mcard:hover { border-color: var(--accent); text-decoration: none; }
.mcard.down { border-color: #E7A39B; background: #FFF8F7; }
.mcard { position: relative; cursor: pointer; }
.mcard.on { border-color: var(--accent); }
.pop { position: absolute; left: 8px; right: 8px; top: calc(100% - 6px); z-index: 20; display: flex; flex-direction: column; gap: 5px;
  padding: 10px 12px; border-radius: 8px; background: #fff; border: 1px solid var(--line); box-shadow: 0 10px 24px rgba(23, 33, 43, 0.18);
  cursor: default; min-width: 200px; }
.ptags { display: flex; gap: 4px; flex-wrap: wrap; }
.ptags span { padding: 0 6px; border-radius: 999px; background: var(--surface-2); }
.ptags .bad { color: var(--bad); background: var(--bad-bg); } .ptags .warn { color: var(--warn-ink); background: var(--warn-bg); }
.mtop { display: flex; justify-content: space-between; align-items: center; }
.b { font-weight: 600; }
.bn { margin-left: 6px; font-size: 10px; color: var(--task-ink); background: #F9E7A8; border-radius: 6px; padding: 0 5px; }
.job { font-size: 13px; line-height: 1.4; min-height: 36px; }
.mcard .bar { height: 5px; }
.disp { color: var(--muted); border-top: 1px dashed var(--line); padding-top: 4px; }
.agv { display: flex; gap: 16px; border-top: 1px solid var(--line-soft); padding-top: 10px; margin-top: 12px; flex-wrap: wrap; }
.orders { width: 360px; flex-shrink: 0; }
.order { display: flex; flex-direction: column; gap: 6px; padding: 10px 0; border-top: 1px solid var(--line-soft); }
.otop { display: flex; align-items: baseline; gap: 8px; white-space: nowrap; min-width: 0; }
.otop > span:nth-child(2) { overflow: hidden; text-overflow: ellipsis; }
.otop .pill { margin-left: auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }   /* 第 130 轮：英文较长时截断，不撑出卡片 */
.three { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.bars { display: flex; gap: 16px; align-items: flex-end; height: 132px; padding: 0 6px; border-bottom: 1px solid #C8CEC7; }
.day { flex-grow: 1; display: flex; flex-direction: column; align-items: center; gap: 6px; }
.pair { display: flex; gap: 4px; align-items: flex-end; }
.plan { width: 18px; border: 1.5px solid #8C96A0; box-sizing: border-box; background: #fff; }
.act { width: 18px; background: var(--accent); }
.days { display: flex; gap: 16px; padding: 6px 6px 10px; }
.days span { flex-grow: 1; text-align: center; }
.q3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 8px; }
.q3 div { display: flex; flex-direction: column; }
.q3 b { font-size: 17px; }
.mat { display: flex; align-items: center; gap: 10px; padding: 7px 0; border-top: 1px solid var(--line-soft); }
.mname { display: flex; flex-direction: column; flex-grow: 1; gap: 2px; }
.todo { display: flex; align-items: center; gap: 12px; padding: 8px 0; border-top: 1px solid var(--line-soft); }
.ttext { flex-grow: 1; font-size: 13px; }
@media (max-width: 1200px) {
  .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .three { grid-template-columns: 1fr; }
  .machines { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .brief { flex-direction: column; }
  .brief-ask, .orders { width: auto; }
  .kpis, .machines { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .todo { flex-wrap: wrap; }
}
</style>
