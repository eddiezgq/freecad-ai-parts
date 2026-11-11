<!-- 人员（第 18 轮 E4）：组织与员工、技能矩阵、排班（缺口标红，点格子调班）、出勤与加班。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('人员') }}</h1>
      <span class="muted">{{ $t('部门岗位 → 员工 → 谁能开哪台设备 → 排班 → 出勤；缺人的那一班设备开不了') }}</span>
      <span class="tabs" data-help="people-tabs" role="tablist"><button v-for="(l, k) in TABS" :key="k" type="button" role="tab" :class="{ on: tab === k }" @click="go(k)">{{ l }}</button></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="msg" class="ok small">{{ msg }}</div>

    <section v-if="kp" class="kpis" data-help="people-kpis">
      <div class="card k"><span class="small muted">{{ $t('这一班出勤率') }}</span><b>{{ Math.round(kp.attendance_rate * 100) }}%</b>
        <span class="small muted">{{ $t('{a} {b}，在岗 {c} / {d}', { a: $td(kp.day), b: kp.shift === 'day' ? ($td(ro?.shift_names?.day || kp?.shift_names?.day) || $t('早班')) : $t('晚班'), c: kp.on_shift - kp.absent, d: $td(kp.on_shift) }) }}</span></div>
      <div class="card k"><span class="small muted">{{ $t('24 小时内排班缺口') }}</span><b :class="{ bad: kp.gaps }">{{ $td(kp.gaps) }}</b></div>
      <div class="card k"><span class="small muted">{{ $t('单点依赖的设备') }}</span><b :class="{ warn: kp.single_points }">{{ $td(kp.single_points) }}</b><span class="small muted">{{ $t('只有一个人会开') }}</span></div>
      <div class="card k"><span class="small muted">{{ $t('本周加班') }}</span><b>{{ $td(kp.overtime_h_week) }}</b><span class="small muted">{{ $t('小时') }}</span></div>
      <div class="card k"><span class="small muted">{{ $t('车间“要有人”') }}</span><b>{{ kp.enabled ? $t('开') : $t('关') }}</b>
        <span v-if="teacher" class="row small"><button class="btn sm" @click="setEnabled(!kp.enabled)">{{ kp.enabled ? $t('关闭') : $t('打开') }}</button></span>
        <span v-else class="small muted">{{ kp.enabled ? $t('没人的班设备会停') : $t('缺人不影响车间') }}</span></div>
    </section>

    <!-- ① 组织与员工 -->
    <template v-if="tab === 'org' && em">
      <div class="card">
        <div class="row small"><span v-for="d in em.departments" :key="d.name" class="pill">{{ $t('{a} {b} 人', { a: $td(d.name), b: $td(d.count) }) }}</span></div>
        <table class="tbl small"><thead><tr><th>{{ $t('工号') }}</th><th>{{ $t('姓名') }}</th><th>{{ $t('部门') }}</th><th>{{ $t('岗位') }}</th><th>{{ $t('班次') }}</th><th>{{ $t('入职') }}</th><th>ERPNext</th><th v-if="em.employees.some((e) => e.phone)">{{ $t('电话') }}</th><th>{{ $t('会开的设备') }}</th></tr></thead>
          <tbody><tr v-for="e in em.employees" :key="e.id"><td>{{ $td(e.id) }}</td><td>{{ $td(e.name) }}</td><td>{{ $td(e.dept) }}</td><td>{{ $td(e.post) }}</td><td>{{ $td(e.shift_name) }}</td>
            <td>{{ $td(e.hired) }}</td><td>{{ e.erp_id || '—' }}</td><td v-if="em.employees.some((x) => x.phone)">{{ $td(e.phone) }}</td>
            <td>{{ Object.entries(e.skills).map(([u, l]) => u.toUpperCase() + (l === 1 ? $t('（学徒）') : '')).join($t('、')) || '—' }}</td></tr></tbody></table>
        <p class="small muted">{{ $t('员工、部门、岗位以 ERPNext 为准（第一次打开时自动建好）；技能、排班、出勤在平台。电话只有厂长和老师看得到。') }}</p>
      </div>
    </template>

    <!-- ② 技能矩阵 -->
    <template v-if="tab === 'skills' && sk">
      <div class="card">
        <table class="tbl small mx"><thead><tr><th>{{ $t('员工') }}</th><th>{{ $t('班次') }}</th>
          <th v-for="u in sk.units" :key="u.unit" :class="{ bad: u.single || u.none }" :title="u.name">{{ u.unit.toUpperCase() }}<br><span class="muted">{{ $t('{a} 人', { a: $td(u.skilled) }) }}</span></th></tr></thead>
          <tbody><tr v-for="r in sk.rows" :key="r.id"><td>{{ $td(r.id) }} {{ $td(r.name) }}<br><span class="muted">{{ $td(r.post) }}</span></td><td>{{ r.shift === 'day' ? $t('早') : $t('晚') }}</td>
            <td v-for="u in sk.units" :key="u.unit" class="c" :class="'l' + (r.cells[u.unit]?.level || 0)" :title="r.cells[u.unit]?.valid_until ? $t('有效期到 ') + r.cells[u.unit].valid_until : ''">
              {{ LV[r.cells[u.unit]?.level] || '' }}</td></tr></tbody></table>
        <p class="small muted">{{ $t('学 = 学徒（要人带，速度 60%）；熟 = 熟练；师 = 可带徒。列头标红的设备熟练以上只有一个人（单点依赖）：{a}。', { a: sk.single_points.map((x) => x.unit.toUpperCase() + $t('（') + x.emp_name + $t('）')).join($t('、')) || $t('没有') }) }}</p>
      </div>
      <div v-if="tr" class="card">
        <h3>{{ $t('技能培训（带教）') }}</h3>
        <table v-if="tr.trainings.length" class="tbl small"><thead><tr><th>{{ $t('编号') }}</th><th>{{ $t('谁') }}</th><th>{{ $t('设备') }}</th><th class="num">{{ $t('带教小时') }}</th><th>{{ $t('状态') }}</th><th>{{ $t('开始') }}</th><th></th></tr></thead>
          <tbody><tr v-for="t in tr.trainings" :key="t.id"><td>{{ $td(t.key) }}</td><td>{{ $td(t.emp_name) }}</td><td>{{ t.unit.toUpperCase() }}</td><td class="num">{{ $td(t.hours) }}</td>
            <td>{{ t.status === 'passed' ? $t('考核通过') : $t('带教中') }}</td><td>{{ t.started_at.slice(0, 16).replace('T', ' ') }}</td>
            <td><button v-if="tr.can_manage && t.status === 'doing'" class="linkbtn" @click="passIt(t)">{{ $t('考核通过') }}</button></td></tr></tbody></table>
        <p v-else class="small muted">{{ $t('还没有。在厂情中枢打开“关键资质单点依赖”异常，采纳“技能培训”。') }}</p>
      </div>
    </template>

    <!-- ③ 排班 -->
    <template v-if="tab === 'roster' && ro">
      <div class="card" data-help="people-roster">
        <div class="row small"><button class="btn sm" @click="shiftWeek(-7)">{{ $t('上一周') }}</button><button class="btn sm" @click="shiftWeek(7)">{{ $t('下一周') }}</button>
          <span class="muted">{{ $t('现在：{a} {b}', { a: $td(ro.now.day), b: ro.now.shift === 'day' ? ($td(ro?.shift_names?.day || kp?.shift_names?.day) || $t('早班')) : $t('晚班') }) }}</span>
          <span v-if="!ro.enabled" class="pill warn">{{ $t('车间“要有人”没打开：缺人不会让设备停下') }}</span></div>
        <table class="tbl small mx"><thead><tr><th>{{ $t('日期 / 班') }}</th><th v-for="u in UNITS" :key="u">{{ u.toUpperCase() }}</th></tr></thead>
          <tbody><tr v-for="r in ro.rows" :key="r.day + r.shift" :class="{ now: r.day === ro.now.day && r.shift === ro.now.shift }">
            <td>{{ r.day.slice(5) }} {{ $td(r.shift_name) }}</td>
            <td v-for="u in UNITS" :key="u" class="c" :class="cellClass(r.cells[u])" @click="pick(r, u)">
              <template v-if="r.cells[u]">{{ $td(r.cells[u].name) }}<span v-if="r.cells[u].attendance" class="small">{{ $t('（{a}）', { a: $td(r.cells[u].attendance) }) }}</span>
                <span v-if="r.cells[u].source !== 'post'" class="small muted">· {{ SRC[r.cells[u].source] }}</span></template>
              <span v-else class="muted">{{ $t('不开') }}</span></td></tr></tbody></table>
        <p class="small muted">{{ $t('红：这一班没人能开（请假、调走、不会开）；黄：学徒带着开（60%）。点一个格子可以换人（生成“调班”动作，班组长或厂长批准后生效）。') }}</p>
      </div>
      <div v-if="cell" class="card">
        <h3>{{ $t('{a} {b} {c}：换人', { a: $td(cell.day), b: cell.shift === 'day' ? (ro?.shift_names?.day || kp?.shift_names?.day || $t('早班')) : $t('晚班'), c: cell.unit.toUpperCase() }) }}</h3>
        <div class="row">
          <select v-model="cell.emp" :aria-label="$t('谁来顶')"><option value="">{{ $t('选人') }}</option>
            <option v-for="c in cands" :key="c.id" :value="c.id">{{ $t('{a} {b}（{c}，{d}）', { a: $td(c.id), b: $td(c.name), c: $td(LVN[c.level]), d: c.shift === 'day' ? (ro?.shift_names?.day || kp?.shift_names?.day || $t('早班')) : $t('晚班') }) }}</option></select>
          <label class="small"><input v-model="cell.ot" type="checkbox"> {{ $t('加班顶班（原岗位不动，要厂长批）') }}</label>
          <button class="btn primary sm" :disabled="!cell.emp" @click="swap">{{ $t('生成动作') }}</button>
          <button class="btn sm" @click="cell = null">{{ $t('取消') }}</button></div>
      </div>
      <div v-if="ro.gaps.length" class="card">
        <h3>{{ $t('24 小时内的缺口') }}</h3>
        <ul class="small"><li v-for="g in ro.gaps" :key="g.day + g.shift + g.unit">{{ $t('{a} {b} {c}：{d}', { a: g.day.slice(5), b: $td(g.shift_name), c: g.unit.toUpperCase(), d: $td(g.why) }) }}</li></ul>
        <router-link class="small" :to="{ path: '/ont', query: { view: 'anomalies' } }">{{ $t('到指挥台看处理方案') }}</router-link>
      </div>
    </template>

    <!-- ④ 出勤与加班 -->
    <template v-if="tab === 'attendance' && td">
      <div class="card">
        <h3>{{ $td(td.day) }} {{ $td(td.shift_name) }}</h3>
        <table class="tbl small"><thead><tr><th>{{ $t('工号') }}</th><th>{{ $t('姓名') }}</th><th>{{ $t('岗位') }}</th><th>{{ $t('这一班的设备') }}</th><th>{{ $t('出勤') }}</th><th v-if="em?.can_manage"></th></tr></thead>
          <tbody><tr v-for="p in td.people" :key="p.id"><td>{{ $td(p.id) }}</td><td>{{ $td(p.name) }}</td><td>{{ $td(p.post) }}</td>
            <td>{{ p.units.map((u) => u.toUpperCase()).join($t('、')) || '—' }}</td><td :class="{ bad: p.attendance !== '在岗' && p.attendance !== '迟到' }">{{ $td(p.attendance) }}</td><!-- i18n-ok 数据值比较 -->
            <td v-if="em?.can_manage"><button v-for="(l, k) in ATT" :key="k" class="linkbtn" @click="mark(p, k)">{{ l }}</button>
              <button v-if="p.attendance !== '在岗'" class="linkbtn" @click="unmark(p)">{{ $t('恢复在岗') }}</button></td></tr></tbody></table><!-- i18n-ok 数据值比较 -->
        <p class="small muted">{{ $t('出勤只记请假、迟到、缺勤，不记原因。请假后排班里他的格子变红，设备这一班没人能开。') }}</p>
      </div>
      <div v-if="ot" class="card">
        <h3>{{ $t('本周加班（上限 {a} 小时）', { a: $td(ot.limit_h) }) }}</h3>
        <table v-if="ot.week.length" class="tbl small"><thead><tr><th>{{ $t('姓名') }}</th><th class="num">{{ $t('小时') }}</th></tr></thead>
          <tbody><tr v-for="x in ot.week" :key="x.emp_id"><td>{{ $td(x.name) }}</td><td class="num" :class="{ bad: x.hours > ot.limit_h }">{{ $td(x.hours) }}</td></tr></tbody></table>
        <p v-else class="small muted">{{ $t('本周还没有人加班。') }}</p>
        <h3>{{ $t('近 7 天缺勤率') }}</h3>
        <table class="tbl small"><thead><tr><th>{{ $t('班组') }}</th><th class="num">{{ $t('排班人次') }}</th><th class="num">{{ $t('请假 / 缺勤') }}</th><th class="num">{{ $t('缺勤率') }}</th></tr></thead>
          <tbody><tr v-for="(x, t) in ot.absence" :key="t"><td>{{ t }}</td><td class="num">{{ $td(x.scheduled) }}</td><td class="num">{{ $td(x.missed) }}</td>
            <td class="num" :class="{ bad: x.rate > 0.1 }">{{ Math.round(x.rate * 1000) / 10 }}%</td></tr></tbody></table>
      </div>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post, session } from '../lib/api';

const TABS = { org: $t('组织与员工'), skills: $t('技能矩阵'), roster: $t('排班'), attendance: $t('出勤与加班') };
const UNITS_DEMO = ['saw-01', 'cnc-l01-a', 'cnc-l01-b', 'ht-01', 'key-01', 'grd-01', 'hob-01', 'vmc-01', 'hmc-01', 'press-01', 'asm-01'];
const UNITS = computed(() => ro.value?.units || UNITS_DEMO);      // 第 61 轮：要有人的设备随工厂变
const LV = { 1: $t('学'), 2: $t('熟'), 3: $t('师') };
const LVN = { 1: $t('学徒'), 2: $t('熟练'), 3: $t('可带徒') };
const SRC = { swap: $t('调班'), overtime: $t('加班'), apprentice: $t('学徒') };
const ATT = { leave: $t('请假'), late: $t('迟到'), absent: $t('缺勤') };
const route = useRoute();
const router = useRouter();
const tab = ref(TABS[route.query.tab] ? route.query.tab : 'roster');
const err = ref('');
const msg = ref('');
const kp = ref(null);
const em = ref(null);
const sk = ref(null);
const tr = ref(null);
const ro = ref(null);
const td = ref(null);
const ot = ref(null);
const week = ref('');
const cell = ref(null);
const teacher = computed(() => session.user?.teacher && session.user?.mode === 'teach');

function go(k) { tab.value = k; router.replace({ query: { ...route.query, tab: k } }); load(); }
async function wrap(fn) { err.value = ''; try { await fn(); } catch (e) { err.value = e.message; } }
function load() {
  wrap(async () => { kp.value = await get('/people/kpis'); });
  wrap(async () => { em.value = await get('/people/employees'); });
  ({
    org: () => {},
    skills: () => wrap(async () => { sk.value = await get('/people/skills'); tr.value = await get('/people/trainings'); }),
    roster: () => wrap(async () => { ro.value = await get('/people/roster' + (week.value ? '?week=' + week.value : '')); if (!sk.value) sk.value = await get('/people/skills'); }),
    attendance: () => wrap(async () => { td.value = await get('/people/today'); ot.value = await get('/people/overtime'); }),
  })[tab.value]();
}
function shiftWeek(n) {
  const d = new Date((week.value || ro.value.rows[0].day) + 'T12:00:00');
  d.setDate(d.getDate() + n);
  week.value = d.toISOString().slice(0, 10);
  load();
}
function cellClass(c) {
  if (!c) return 'off';
  return { gap: c.gap, appr: c.level === 1, mine: c.source !== 'post' };
}
function pick(r, u) {
  if (!r.cells[u] && !UNITS.value.includes(u)) return;
  cell.value = { day: r.day, shift: r.shift, unit: u, emp: '', ot: false };
}
const cands = computed(() => {
  if (!cell.value || !sk.value) return [];
  return sk.value.rows.filter((r) => r.cells[cell.value.unit]?.level).map((r) => ({ id: r.id, name: r.name, level: r.cells[cell.value.unit].level, shift: r.shift }))
    .sort((a, b) => b.level - a.level);
});
async function swap() {
  const c = cell.value;
  await wrap(async () => {
    const ch = c.ot ? { type: 'overtime_assign', day: c.day, shift: c.shift, unit: c.unit, emp_id: c.emp, minutes: 720 }
      : { type: 'shift_swap', day: c.day, shift: c.shift, unit: c.unit, emp_id: c.emp };
    const r = await post('/ont/actions', { changes: [ch] });
    msg.value = $t('已提交动作 ') + r.ids.map((i) => 'ACT-' + String(i).padStart(5, '0')).join($t('、')) + $t('，批准后排班生效（动作收件箱）');
    cell.value = null;
  });
}
async function mark(p, k) { await wrap(async () => { await post('/people/attendance', { emp_id: p.id, status: k, day: td.value.day, shift: td.value.shift }); load(); }); }
async function unmark(p) { await wrap(async () => { await post('/people/attendance/clear', { emp_id: p.id, day: td.value.day, shift: td.value.shift }); load(); }); }
async function passIt(t) { await wrap(async () => { await post(`/people/trainings/${t.id}/pass`); load(); }); }
async function setEnabled(on) { await wrap(async () => { await post('/people/staffing', { enabled: on }); load(); }); }
load();
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.tabs { margin-left: auto; display: flex; gap: 4px; flex-wrap: wrap; }
.tabs button { height: 30px; padding: 0 12px; border: 1px solid var(--line); background: var(--surface); border-radius: 6px; cursor: pointer; }
.tabs button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; margin-bottom: 12px; }
.k { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; }
.k b { font-size: 22px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
select, input[type=number] { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; min-width: 0; }
.card .tbl { display: block; overflow-x: auto; }
.mx td.c { text-align: center; white-space: nowrap; min-width: 52px; cursor: pointer; }
.mx td.l1, .mx td.appr { background: color-mix(in srgb, var(--warn) 18%, transparent); }
.mx td.l2 { background: color-mix(in srgb, var(--good) 16%, transparent); }
.mx td.l3 { background: color-mix(in srgb, var(--good) 32%, transparent); }
.mx td.gap { background: color-mix(in srgb, var(--bad) 22%, transparent); }
.mx td.off { color: var(--muted); cursor: default; }
.mx td.mine { font-weight: 600; }
.mx th.bad { color: var(--bad); }
tr.now td:first-child { font-weight: 700; }
.bad { color: var(--bad); }
.warn { color: var(--warn); }
.ok { color: var(--good); }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; padding: 0 4px; }
.btn.sm { height: 28px; padding: 0 10px; }
h3 { font-size: 14px; margin: 8px 0 6px; }
.num { text-align: right; }
.pill { margin-right: 6px; }
</style>
