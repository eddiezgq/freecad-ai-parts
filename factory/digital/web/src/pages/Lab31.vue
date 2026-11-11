<!-- 实验 31“关节终检抱闸报警的排查”（第 123 轮，机器人厂）：报警帧 → 线圈电流 → 坏件 → 安全逻辑 → 处置 → 复测放行 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('实验 31 · 关节终检抱闸报警的排查') }}</h1>
      <span class="muted">{{ $t('平台自动评 {a} 分，报告 {b} 分由老师在课程里批改', { a: s?.of || 60, b: s?.report_points || 40 }) }}</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab31/guide.docx">{{ $t('指导书') }}</a> · <a href="/api/cae/lab31/report-template.docx">{{ $t('报告模板') }}</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ $td(s.score) }} / {{ $td(s.of) }}</b>
        <span class="small">{{ $t('终检报故障 7（抱闸）的 3 台关节模组：') }}<b v-for="j in s.joints" :key="j.serial" class="mono sn">{{ $td(j.serial) }}</b></span>
        <button class="btn sm" @click="load">{{ $t('刷新') }}</button>
      </div>
      <div v-if="s.sim_missing" class="err">{{ $t('固件仿真结果缺失（designs/drv-joint-b/fw/out/sim_motor.json），这个实验暂时做不了。') }}</div>

      <section v-if="s.teacher && s.class?.length" class="card">
        <div class="card-head"><h2>{{ $t('老师：全班成绩') }}</h2></div>
        <table class="tbl small"><thead><tr><th>{{ $t('学生') }}</th><th v-for="(t, i) in s.tasks" :key="t.id" class="num">{{ $t('任务 {a}', { a: i + 1 }) }}</th><th class="num">{{ $t('合计') }}</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ $td(c.user) }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ $td(c.total) }}</b></td></tr></tbody></table>
      </section>

      <section class="card" data-help="lab31-protocol">
        <div class="card-head"><h2>{{ $t('协议摘录（驱动板 B 版 CAN，经典 CAN 1 Mbit/s，节点 1）') }}</h2></div>
        <ul class="small proto"><li v-for="p in s.protocol" :key="p">{{ $td(p) }}</li></ul>
        <p class="small muted">{{ $t('测试记录是驱动板 B 版固件在 Renode 仿真器里跑出来的真实输出（第 114 轮场景 ⑮ ⑯ ⑰）。报文只给原始数据，自己按上面解。') }}</p>
      </section>

      <section v-for="j in s.joints" :key="j.serial" class="card" data-help="lab31-record">
        <div class="card-head"><h2 class="mono">{{ $td(j.serial) }}</h2><span class="small muted">{{ $t('{a} · 抱闸保持力矩名义 {b} N·m', { a: $td(j.item), b: $td(j.brake_nominal) }) }}</span></div>
        <template v-if="j.record">
          <p class="small">{{ $td(j.record.desc) }}</p>
          <div class="charts">
            <div v-for="tr in TRACES" :key="tr.k" class="chart">
              <div class="small"><b>{{ $td(tr.name) }}</b> <span class="muted">{{ $td(tr.unit) }}</span></div>
              <svg viewBox="0 0 600 110" preserveAspectRatio="none" class="svg">
                <line x1="40" y1="100" x2="595" y2="100" class="ax" /><line x1="40" y1="5" x2="40" y2="100" class="ax" />
                <polyline :points="pts(j.record.series, tr)" class="ln" :style="{ stroke: tr.c }" />
                <text x="36" y="12" class="tk" text-anchor="end">{{ fmt(range(j.record.series, tr)[1]) }}</text>
                <text x="36" y="100" class="tk" text-anchor="end">{{ fmt(range(j.record.series, tr)[0]) }}</text>
                <text x="42" y="109" class="tk">{{ j.record.series.t[0].toFixed(2) }} s</text>
                <text x="595" y="109" class="tk" text-anchor="end">{{ j.record.series.t[j.record.series.t.length - 1].toFixed(2) }} s</text>
              </svg>
            </div>
          </div>
          <div class="frames">
            <div class="small">{{ $t('报文') }}
              <label v-for="id in IDS" :key="id" class="ck"><input v-model="show[j.serial + id]" type="checkbox"> {{ $td(id) }}</label></div>
            <div class="scroll"><table class="tbl small mono"><thead><tr><th class="num">{{ $t('时间 s') }}</th><th>{{ $t('方向') }}</th><th>ID</th><th>{{ $t('数据') }}</th></tr></thead>
              <tbody><tr v-for="(f, k) in frames(j)" :key="k" :class="{ alarm: f.id === '0x081' }">
                <td class="num">{{ f.t.toFixed(5) }}</td><td>{{ f.dir === 'tx' ? $t('驱动板 →') : $t('→ 驱动板') }}</td><td>{{ $td(f.id) }}</td><td>{{ f.data.match(/../g).join(' ') }}</td></tr></tbody></table></div>
          </div>
        </template>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>{{ $t('任务 {a}　{b}', { a: i + 1, b: $td(t.title) }) }}</h2><span class="pts">{{ $td(t.score) }} / {{ $td(t.points) }}</span></div>
        <p>{{ $td(t.desc) }}</p>
        <p class="small muted">{{ $t('提示：{a}', { a: $td(t.hint) }) }}</p>
        <form v-if="t.id === 'l31_t1'" class="f" @submit.prevent="submit(t.id, a1)">
          <div v-for="j in s.joints" :key="j.serial" class="lf"><label class="mono">{{ $td(j.serial) }}</label>
            {{ $t('故障码') }} <input v-model="a1[j.serial].code" class="n" required> {{ $t('子码') }} <input v-model="a1[j.serial].sub" class="n" required></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l31_t2' || t.id === 'l31_t5'" class="f" @submit.prevent="submit(t.id, t.id === 'l31_t2' ? a2 : a5)">
          <div v-for="j in s.joints" :key="j.serial" class="lf"><label class="mono">{{ $td(j.serial) }}</label>
            <select v-if="t.id === 'l31_t2'" v-model="a2[j.serial]" class="w2" required><option v-for="o in s.parts" :key="o.value" :value="o.value">{{ $td(o.label) }}</option></select>
            <select v-else v-model="a5[j.serial]" class="w2" required><option v-for="o in s.actions" :key="o.value" :value="o.value">{{ $td(o.label) }}</option></select></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l31_t3'" class="f" @submit.prevent="submit(t.id, a3)">
          <div class="lf"><label>{{ $t('报警 → 抱住（ms）') }}</label><input v-model.number="a3.engage_ms" type="number" step="1" required></div>
          <div class="lf"><label>{{ $t('报警 → 关输出（ms）') }}</label><input v-model.number="a3.off_ms" type="number" step="1" required></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l31_t4'" class="f" @submit.prevent="submit(t.id, a4)">
          <div class="lf"><label>{{ $t('选一项') }}</label><span class="cks col">
            <label v-for="o in s.t4_choices" :key="o.value"><input v-model="a4.choice" type="radio" :value="o.value" required> {{ $td(o.label) }}</label></span></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <div v-if="t.id === 'l31_t6'" class="f">
          <button class="btn primary" @click="submit(t.id, {})">{{ $t('复测') }}</button>
          <table v-if="s.retest" class="tbl small"><thead><tr><th>{{ $t('关节') }}</th><th>{{ $t('上电抱闸时序') }}</th><th class="num">{{ $t('抱闸保持力矩 N·m') }}</th><th>{{ $t('规格') }}</th><th>{{ $t('判定') }}</th></tr></thead>
            <tbody><tr v-for="r in s.retest.rows" :key="r.serial"><td class="mono">{{ $td(r.serial) }}</td><td>{{ r.sequence_ok ? $t('通过') : $t('不通过') }}</td>
              <td class="num">{{ $td(r.brake_hold) }}</td><td>{{ $td(r.lo) }}–{{ $td(r.hi) }}</td><td><b>{{ r.ok ? $t('合格，放行') : $t('不合格') }}</b></td></tr></tbody></table>
          <p v-if="s.retest" class="small muted">{{ $t('时序：{a}（{b}）。{c}', { a: $td(s.retest.sequence), b: s.retest.checks.join($t('；')), c: $td(s.retest.note) }) }}</p>
        </div>
        <p v-if="fb[t.id]" class="small fb">{{ $td(fb[t.id]) }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { onMounted, reactive, ref } from 'vue';
import { get, post } from '../lib/api';

const TRACES = [
  { k: 'brake_i', name: $t('抱闸线圈电流'), unit: $t('A（额定 0.42 A）'), c: '#d9480f' },
  { k: 'joint', name: $t('关节角度'), unit: '°', c: '#1971c2' },
  { k: 'moe', name: $t('输出开关（逆变桥）'), unit: $t('1 开、0 关'), c: '#2b8a3e' },
];
const IDS = ['0x081', '0x701', '0x181', '0x201'];
const s = ref(null);
const err = ref('');
const fb = reactive({});
const show = reactive({});
const a1 = reactive({});
const a2 = reactive({});
const a3 = reactive({ engage_ms: null, off_ms: null });
const a4 = reactive({ choice: '' });
const a5 = reactive({});

function range(se, tr) {
  const v = se[tr.k];
  let lo = Math.min(...v), hi = Math.max(...v);
  if (tr.k === 'moe') { lo = 0; hi = 1; }
  if (hi - lo < 1e-6) { hi = lo + 1; }
  return [lo, hi];
}
function pts(se, tr) {
  const [lo, hi] = range(se, tr);
  const t0 = se.t[0], t1 = se.t[se.t.length - 1];
  return se[tr.k].map((y, i) => (40 + 555 * (se.t[i] - t0) / (t1 - t0)).toFixed(1) + ',' + (100 - 95 * (y - lo) / (hi - lo)).toFixed(1)).join(' ');
}
function fmt(x) { return Math.abs(x) >= 10 ? x.toFixed(0) : x.toFixed(2); }
function frames(j) { return j.record.frames.filter(f => show[j.serial + f.id]); }

async function load() {
  try {
    s.value = await get('/lab31'); err.value = '';
    for (const j of s.value.joints) {
      if (!a1[j.serial]) a1[j.serial] = { code: '', sub: '' };
      if (show[j.serial + '0x081'] === undefined) { show[j.serial + '0x081'] = true; show[j.serial + '0x701'] = true; }
    }
  } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab31/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { err.value = e.message; }
}
onMounted(load);
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.r { margin-left: auto; }
.sum { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
.big { font-size: 24px; }
.sn { margin-left: 8px; }
.proto { margin: 0; padding-left: 18px; line-height: 1.7; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; margin: 8px 0; }
.svg { width: 100%; height: 110px; background: var(--surface-2); border-radius: 6px; }
.ax { stroke: var(--line); stroke-width: 1; }
.ln { fill: none; stroke-width: 1.6; vector-effect: non-scaling-stroke; }
.tk { font-size: 9px; fill: var(--muted, #888); }
.frames .ck { margin-left: 12px; }
.scroll { max-height: 240px; overflow: auto; border: 1px solid var(--line); border-radius: 6px; margin-top: 4px; }
tr.alarm td { color: #c92a2a; font-weight: 600; }
.task.done { border-left: 4px solid var(--good); }
.pts { margin-left: auto; font-weight: 600; }
.f { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.lf { display: flex; flex-direction: row; gap: 10px; align-items: center; flex-wrap: wrap; }
.lf > label:first-child { width: 190px; font-weight: 500; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 auto; min-width: 240px; font-size: 13px; }
.cks.col { flex-direction: column; }
.f .btn { align-self: flex-start; }
input, select { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; width: 140px; }
input.n { width: 70px; }
select.w2 { width: min(520px, 100%); }
input[type=radio], input[type=checkbox] { height: auto; width: auto; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; }
.num { text-align: right; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
</style>
