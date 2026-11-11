<template>
  <div class="page">
    <TaskBar v-if="teachStatus" :t="teachStatus" />
    <div class="page-title"><h1>{{ $t('质量') }}</h1><span class="muted">{{ $t('质检员工作区 · {a}、控制图、不合格品评审', { a: demo ? $t('三坐标测量值') : $t('测量值') }) }}</span></div>
    <div class="row">
      <section class="card grow" data-help="q-chart">
        <div class="card-head">
          <h2>{{ $t('控制图') }}</h2>
          <select v-model="sel" @change="load" :aria-label="$t('测量特性')">
            <option v-for="c in chars" :key="c.item + '|' + c.key" :value="c.item + '|' + c.key">{{ $td(c.name) }}</option>
          </select>
          <span class="muted small">{{ $t('{a}最近 {b} 件', { a: demo ? 'quality/qc-01/measurement · ' : '', b: $td(rows.length) }) }}</span>
        </div>
        <ControlChart v-if="chart.points.length && !attr" :chart="chart" :height="220" />
        <div v-else-if="!chart.points.length" class="empty">{{ $t('还没有这个特性的测量值。') }}</div>
        <p v-if="chart.points.length && attr" class="small attr">{{ $t('计数型检验项目（有或无），不画控制图、不算过程能力，只统计不合格件数：最近') }} <b class="mono">{{ $td(chart.points.length) }}</b> {{ $t('件里不合格') }} <b class="mono">{{ attrFails }}</b> {{ $t('件。') }}</p>
        <p v-else-if="chart.points.length && unit === 'mm'" class="small">{{ $t('最近 5 件均值') }} <b class="mono">{{ mean5.toFixed(4) }}</b> {{ $t('mm，偏离公差中值') }}
          <b class="mono">{{ ((mean5 - chart.center) * 1000).toFixed(1) }}</b> {{ $t('µm，距上限') }} <b class="mono">{{ ((chart.upper - max5) * 1000).toFixed(1) }}</b> {{ $t('µm。') }}</p>
        <p v-else-if="chart.points.length" class="small">{{ $t('最近 5 件均值') }} <b class="mono">{{ mean5.toFixed(3) }}</b> {{ $t('{a}，偏离公差中值', { a: unit }) }}
          <b class="mono">{{ (mean5 - chart.center).toFixed(3) }}</b> {{ $t('{a}，距上限', { a: unit }) }} <b class="mono">{{ (chart.upper - max5).toFixed(3) }}</b> {{ $t('{a}。', { a: unit }) }}</p>
        <div v-if="strata.length" class="strata" data-help="q-strata">
          <div v-for="g in strata" :key="g.by"><b class="small">{{ $t('按{a}分层', { a: $td(g.label) }) }}</b>
            <table class="t small"><thead><tr><th>{{ $td(g.label) }}</th><th class="num">{{ $t('件数') }}</th><th class="num">{{ $t('均值 {a}', { a: unit }) }}</th><th class="num">{{ $t('超差') }}</th></tr></thead>
              <tbody><tr v-for="x in g.rows" :key="x.k"><td class="mono">{{ $td(x.k) }}</td><td class="num">{{ $td(x.n) }}</td><td class="num">{{ $td(x.mean) }}</td>
                <td class="num">{{ $td(x.fails) }}</td></tr></tbody></table></div>
        </div>
        <table class="t">
          <thead><tr><th>{{ $t('时间') }}</th><th>{{ $t('零件') }}</th><th>{{ $t('工单') }}</th><th class="num">{{ attr ? $t('检验结果') : $t('实测 ') + unit }}</th><th class="num">{{ attr ? '' : $t('公差') }}</th><th>{{ $t('判定') }}</th></tr></thead>
          <tbody><tr v-for="r in rows.slice().reverse().slice(0, 30)" :key="r.id">
            <td class="small">{{ timeOf(r.ts) }}</td><td class="mono small"><ObjLink type="PartSerial" :k="r.part_serial" /></td><td class="mono small"><ObjLink v-if="r.work_order" type="WorkOrder" :k="r.work_order" /></td>
            <td class="num">{{ attr ? (r.value_mm > 0 ? $t('有') : $t('无')) : r.value_mm.toFixed(unit === 'mm' ? 4 : 3) }}</td><td class="num small">{{ attr ? '' : r.lower_tol_mm + '–' + r.upper_tol_mm }}</td>
            <td><span class="pill" :class="r.result === 'pass' ? 'good' : 'bad'">{{ r.result === 'pass' ? $t('合格') : (attr ? $t('不合格') : $t('超差')) }}</span></td>
          </tr></tbody>
        </table>
      </section>
      <section class="card side">
        <div class="card-head"><h2>{{ $t('不合格品') }}</h2><span class="muted small">{{ $t('超差零件自动开单{a}', { a: demo ? $t('（quality/qc-01/ncr）') : '' }) }}</span></div>
        <div v-if="!ncr.length" class="empty">{{ $t('没有不合格品。') }}</div>
        <div v-for="n in ncr" :key="n.ncr_id" class="ncr">
          <div><b class="mono"><ObjLink type="Ncr" :k="n.ncr_id" /></b> <span class="mono small"><ObjLink type="PartSerial" :k="n.part_serial" /></span>
            <span class="pill" :class="n.status === 'open' ? 'bad' : 'good'">{{ $td(DISP[n.status]) }}</span></div>
          <div v-if="n.detail.upper_tol_mm - n.detail.lower_tol_mm <= 0" class="small muted">{{ $t('{a}：{b}，不合格', { a: $td(n.detail.name), b: n.detail.value_mm > 0 ? $t('有') : $t('无') }) }}</div>
          <div v-else class="small muted">{{ $t('{a} 实测 {b} {c}（{d}–{e}）', { a: $td(n.detail.name), b: $td(n.detail.value_mm), c: n.detail.unit || unitOf(n.detail.characteristic), d: $td(n.detail.lower_tol_mm), e: $td(n.detail.upper_tol_mm) }) }}</div>
          <div v-if="n.status === 'open'" class="acts">
            <button class="btn" @click="decide(n, 'rework')">{{ $t('返修') }}</button>
            <button class="btn danger" @click="decide(n, 'scrap')">{{ $t('报废') }}</button>
            <button class="btn ghost" @click="decide(n, 'use_as_is')">{{ $t('让步接收') }}</button>
          </div>
          <div v-else class="small muted">{{ $t('由 {a} 评审', { a: $td(n.decided_by) }) }}</div>
        </div>
        <div class="card-head" data-help="q-8d" style="margin-top: 18px;"><h2>{{ $t('质量异常单（8D）') }}</h2>
          <router-link to="/quality/8d" class="small">{{ $t('全部') }}</router-link></div>
        <p class="small muted">{{ $t('控制图上发现异常（超差、趋势、锥度……），开一张质量异常单，按 8D 找原因、定措施、用数据验证。') }}</p>
        <div class="new8d">
          <input v-model="newTitle" :placeholder="$t('现象，如：右轴承位偏大')" />
          <button class="btn primary" :disabled="!newTitle.trim()" @click="open8d">{{ $t('为当前特性开单') }}</button>
        </div>
        <div v-for="q in q8d.slice(0, 5)" :key="q.id" class="ncr">
          <router-link :to="'/quality/8d/' + q.id"><b class="mono">{{ $td(q.id) }}</b> {{ $td(q.title) }}</router-link>
          <span class="small muted">{{ $td(STATUS8D[q.status]) }} · {{ $td(q.author) }}</span>
        </div>
        <template v-if="isTeacher && demo">
          <div class="card-head" data-help="q-problems" style="margin-top: 18px;"><h2>{{ $t('问题情景（老师）') }}</h2></div>
          <p class="small muted">{{ $t('注入一个隐藏的加工问题，学生只能从数据里找原因。学生看不到这一栏。') }}</p>
          <div v-for="a in problems" :key="a.id" class="small">{{ $t('● {a}（量值 {b}，{c}）', { a: $td(a.name), b: $td(a.magnitude), c: timeOf(a.injected_at) }) }}</div>
          <div class="new8d">
            <select v-model="prob"><option value="">{{ $t('选择问题…') }}</option>
              <option v-for="(p, k) in catalog.problems || {}" :key="k" :value="k">{{ $td(p.name) }}</option></select>
            <button class="btn" :disabled="!prob" @click="inject">{{ $t('注入') }}</button>
            <button class="btn ghost" @click="clearProblems">{{ $t('全部清除') }}</button>
          </div>
        </template>
        <template v-if="demo">     <!-- 问题情景、砂轮是减速器厂输出轴的（第 45 轮：别的工厂不显示） -->
          <div class="card-head" style="margin-top: 18px;"><h2>{{ $t('砂轮') }}</h2></div>
          <p class="small">{{ $t('磨床 GRD-01 砂轮剩余寿命') }} <b class="mono">{{ grdLife }}</b>{{ $t('。砂轮越磨损，磨出的轴承位直径越偏大；寿命低于 8% 时自动修整。') }}</p>
        </template>
        <template v-if="teachStatus">
          <div class="card-head" style="margin-top: 18px;"><h2>{{ $t('任务 5 问答') }}</h2></div>
          <p class="small">{{ $t('轴承位直径为什么会逐渐变大？') }}</p>
          <label v-for="c in teachStatus.t5_choices" :key="c" class="choice small"><input v-model="t5" type="radio" :value="c"> {{ $td(c) }}</label>
          <button class="btn primary" :disabled="!t5" @click="answer">{{ $t('提交') }}</button>
          <div v-if="fb" class="small" :class="fbOk ? 'ok' : 'err'">{{ fb }}</div>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { get, loadConfig, post, session } from '../lib/api';
import { bus } from '../lib/bus';
import { timeOf } from '../lib/fmt';
import ControlChart from '../components/ControlChart.vue';
import TaskBar from '../components/TaskBar.vue';
import ObjLink from '../components/ObjLink.vue';

// 能选的测量特性：/api/quality/characteristics（第 45 轮：演示工厂是输出轴 SH-301 的三坐标特性，别的工厂来自工厂清单）
const chars = ref([{ item: 'SH-301', key: 'bearing_seat_d35', name: $t('轴承位直径 Ø35 k6（左）'), unit: 'mm' }]);
const sel = ref('SH-301|bearing_seat_d35');
const cur = computed(() => chars.value.find((c) => c.item + '|' + c.key === sel.value) || chars.value[0]);
const unit = computed(() => cur.value?.unit ?? 'mm');
const attr = computed(() => !!cur.value?.attribute);
const unitOf = (key) => (chars.value.find((c) => c.key === key) || {}).unit || 'mm';
const DISP = { open: $t('待评审'), rework: $t('返修'), scrap: $t('报废'), use_as_is: $t('让步接收') };
const STATUS8D = { open: $t('填写中'), submitted: $t('措施待批准'), approved: $t('措施已实施'), rejected: $t('措施退回'), closed: $t('已关闭') };
const ch = computed(() => cur.value?.key || 'bearing_seat_d35');
const q8d = ref([]);
const newTitle = ref('');
const problems = ref([]);
const catalog = ref({});
const prob = ref('');
const router = useRouter();
const isTeacher = computed(() => session.user && session.user.mode === 'teach' && session.user.teacher);
const rows = ref([]);
const ncr = ref([]);
const t5 = ref('');
const fb = ref('');
const fbOk = ref(true);
const teachStatus = ref(null);
const chart = computed(() => {
  const r = rows.value.slice(-30);
  if (!r.length) return { points: [] };
  const lo = r[0].lower_tol_mm, hi = r[0].upper_tol_mm;
  return { lower: lo, upper: hi, center: (lo + hi) / 2,
    points: r.map((x) => ({ id: x.id, value: x.value_mm, serial: x.part_serial, result: x.result })) };
});
const last5 = computed(() => rows.value.slice(-5).map((r) => r.value_mm));
const mean5 = computed(() => last5.value.reduce((a, b) => a + b, 0) / Math.max(1, last5.value.length));
const max5 = computed(() => Math.max(...last5.value));
const attrFails = computed(() => chart.value.points.filter((p) => p.result !== 'pass').length);
const grdLife = computed(() => {
  const g = bus.machines['grd-01'];
  return g ? Math.round(g.tool_life_left * 100) + '%' : '—';
});
async function load() {
  [rows.value, ncr.value] = await Promise.all([get('/quality/measurements?characteristic=' + ch.value + '&item=' + encodeURIComponent(cur.value?.item || '') + '&limit=' + (demo.value ? 60 : 200)), get('/ncr')]);
}
async function load8d() {
  q8d.value = await get('/quality/8d');
  if (isTeacher.value) problems.value = await get('/quality/problems');
}
async function open8d() {
  const r = await post('/quality/8d', { item: cur.value?.item || 'SH-301', characteristic: ch.value, title: newTitle.value });
  newTitle.value = '';
  router.push('/quality/8d/' + r.id);
}
async function inject() {
  problems.value = await post('/quality/problems', { problem: prob.value });
  prob.value = '';
}
async function clearProblems() {
  problems.value = await post('/quality/problems', { clear: true });
}
async function decide(n, d) {
  await post('/ncr/' + n.ncr_id, { disposition: d });
  load();
}
async function answer() {
  const r = await post('/teach/t5', { reason: t5.value });
  fb.value = $t('{a}（本题得 {b} / {c}）', { a: r.feedback, b: r.score, c: r.of });
  fbOk.value = r.score >= 8;
  teachStatus.value = await get('/teach').catch(() => null);   // 实验 7 只在减速器厂，别的厂回 404
}
// 分层（第 47 轮实验 25）：机器人厂的关节记了装配工位、谐波减速器批次，按它们分组比均值
const strata = computed(() => [['assembled_on', $t('装配工位')], ['lot', $t('减速器批次')]].map(([by, label]) => {
  const m = {};
  for (const r of rows.value) {
    const k = r[by];
    if (!k) continue;
    const x = m[k] || (m[k] = { k, n: 0, sum: 0, fails: 0 });
    x.n += 1; x.sum += r.value_mm; x.fails += r.result === 'fail' ? 1 : 0;
  }
  return { by, label, rows: Object.values(m).sort((a, b) => a.k.localeCompare(b.k)).map((x) => ({ ...x, mean: (x.sum / x.n).toFixed(3) })) };
}).filter((g) => g.rows.length));
const demo = ref(true);                     // 演示工厂（减速器厂）；别的工厂不显示问题情景、砂轮
onMounted(async () => {
  try { demo.value = (await loadConfig())?.plant?.demo !== false; } catch { /* 取不到按演示工厂 */ }
  try {
    const cs = await get('/quality/characteristics');
    if (cs.length) { chars.value = cs; sel.value = cs[0].item + '|' + cs[0].key; }
  } catch { /* 取不到就用缺省（输出轴） */ }
  load();
  catalog.value = await get('/quality/problems/catalog');
  load8d();
  if (session.user.mode === 'teach') teachStatus.value = await get('/teach').catch(() => null);   // 实验 7 只在减速器厂，别的厂回 404
});
</script>

<style scoped>
.grow { flex-grow: 1; min-width: 0; }
.strata { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 10px 0; }
.side { width: 380px; flex-shrink: 0; }
.card-head select { height: 32px; border: 1px solid var(--line); border-radius: 6px; }
.ncr { padding: 10px 0; border-top: 1px solid var(--line-soft); display: flex; flex-direction: column; gap: 4px; }
.acts { display: flex; gap: 6px; margin-top: 4px; }
.choice { display: block; padding: 4px 0; }
.new8d { display: flex; gap: 6px; margin: 6px 0; }
.new8d input, .new8d select { flex: 1; height: 32px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; min-width: 0; }
@media (max-width: 1100px) { .side { width: auto; } }
</style>
