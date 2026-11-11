<!-- 第 88 轮（电子 E4）：电路板厂功能测试台。驱动板 DRV-JOINT 的出厂测试程序，每一步用第 82 轮的仪器模型画出仪器画面
     （读数来自这块板在车间功能测试工位的记录）；学生可以复测一块板：自己读仪器、判合格与否，复测记录进这块板的单件档案。 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ t('功能测试台') }}</h1>
      <span class="muted">{{ t('关节驱动板 DRV-JOINT 的出厂测试：选一块做过功能测试的板，看测试程序每一步的仪器画面，自己复测、判合格与否') }}</span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div class="cols">
      <section class="card list">
        <div class="card-head"><h2>{{ t('做过功能测试的板（最近 {n} 块）', { n: boards.length }) }}</h2></div>
        <div v-if="!boards.length" class="small muted">{{ t('还没有。先接一张 DRV-JOINT 订单、让车间做到“功能测试”这一道。') }}</div>
        <button v-for="b in boards" :key="b.serial" class="brd" :class="{ on: sel === b.serial }" @click="open(b.serial)">
          <span class="mono">{{ b.serial }}</span><span class="small" :class="b.fail ? 'bad' : 'ok'">{{ b.fail ? t('{n} 项不合格', { n: b.fail }) : t('合格') }}</span>
          <span v-if="b.lot" class="small muted">{{ t('采样电阻卷') }} {{ b.lot }}</span></button>
      </section>
      <section v-if="c" class="card main">
        <div class="card-head"><h2>{{ c.board.serial }} <small class="muted">{{ t('工单') }} {{ c.board.work_order }} · {{ t('采样电阻卷') }} {{ c.board.lot || '—' }}</small></h2></div>
        <div class="steps">
          <button v-for="(s, i) in c.steps" :key="s.key" class="tab" :class="{ on: step === i }" @click="step = i">{{ i + 1 }} {{ t(s.title) }}</button>
        </div>
        <div v-if="st" class="bench">
          <p class="small"><b>{{ t('怎么测') }}</b> {{ t(st.how) }} <span class="muted">{{ t('规范：') }}{{ st.lo }} ~ {{ st.hi }} {{ st.unit }}</span></p>
          <div v-if="st.inst === 'scope'">
            <ScopeScreen :traces="traces" :vdiv="[5, 5]" :off="[-5, 15]" :tdiv="tdiv" />
            <div class="line small">{{ t('时基') }} <select v-model.number="tdiv"><option :value="50e-9">{{ t('50 ns/格') }}</option><option :value="100e-9">{{ t('100 ns/格') }}</option><option :value="200e-9">{{ t('200 ns/格') }}</option></select>
              {{ t('把鼠标移到波形上读时间：先找下管栅极（CH2）掉到 2 V 以下的时刻，再找上管栅极（CH1）升过 2 V 的时刻，两者之差就是死区。') }}</div>
          </div>
          <div v-else class="meter">
            <div class="disp mono">{{ meter.text }}</div>
            <div class="small muted">{{ meter.sub }}</div>
            <button class="btn sm" @click="tick++">{{ t('再读一次') }}</button>
          </div>
        </div>
        <div class="card-head"><h3>{{ t('复测') }}</h3></div>
        <p class="small">{{ t('按上面四步（采样电阻、母线电压、相电流、死区）读出的值填进来，判这块板合格还是不合格；平台按这块板的车间记录和测试规范核对。') }}</p>
        <div class="form">
          <label v-for="k in RETEST" :key="k">{{ t(name(k)) }} ({{ unit(k) }})<input v-model="ans[k]" type="number" step="any"></label>
          <label>{{ t('判定') }} <select v-model="verdict"><option value="">—</option><option value="pass">{{ t('合格') }}</option><option value="fail">{{ t('不合格') }}</option></select></label>
          <button class="btn" :disabled="!verdict" @click="submit">{{ t('提交复测') }}</button>
        </div>
        <div v-if="res" class="res">
          <div :class="res.verdict_ok ? 'ok' : 'bad'">{{ res.verdict_ok ? t('✓ 判定对') : t('✗ 判定不对') }}{{ t('，这块板应判 {v}', { v: res.should_be === 'pass' ? t('合格') : t('不合格') }) }}</div>
          <table class="tbl"><thead><tr><th>{{ t('项目') }}</th><th>{{ t('你的读数') }}</th><th>{{ t('车间记录') }}</th><th>{{ t('允许差') }}</th><th>{{ t('读得对吗') }}</th><th>{{ t('在规范内') }}</th></tr></thead>
            <tbody><tr v-for="r in res.rows" :key="r.key"><td>{{ t(name(r.key)) }}</td><td class="mono">{{ r.given ?? '—' }}</td><td class="mono">{{ fmt(r.recorded) }}</td>
              <td class="mono">±{{ r.tol }}</td><td :class="r.close ? 'ok' : 'bad'">{{ r.close ? '✓' : '✗' }}</td><td :class="r.in_spec ? 'ok' : 'bad'">{{ r.in_spec ? t('是') : t('否') }}</td></tr></tbody></table>
        </div>
        <div v-if="c.retests.length" class="small"><b>{{ t('这块板的复测记录（单件档案）') }}</b>
          <div v-for="(r, i) in c.retests" :key="i">{{ r.ts.slice(0, 16) }} · {{ r.user }} · {{ t('判 {v}', { v: r.verdict === 'pass' ? t('合格') : t('不合格') }) }} {{ r.rows?.verdict_ok ? t('（对）') : t('（不对）') }}</div></div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { get, post } from '../lib/api';
import ScopeScreen from '../components/ScopeScreen.vue';
import { dmmRead, mulberry32, gaussFrom, scopeAcquire } from '../lib/instruments';
import { t } from '../lib/i18n';

const RETEST = ['ict_shunt', 'fct_vbus', 'fct_isense', 'fct_deadtime'];
const route = useRoute();
const boards = ref([]);
const sel = ref('');
const c = ref(null);
const step = ref(0);
const err = ref('');
const ans = ref({});
const verdict = ref('');
const res = ref(null);
const tdiv = ref(100e-9);
const tick = ref(0);
const st = computed(() => c.value?.steps[step.value]);
function name(k) { return (c.value?.steps.find((s) => s.key === k) || {}).title || k; }
function unit(k) { return (c.value?.steps.find((s) => s.key === k) || {}).unit || ''; }
function fmt(v) { return typeof v === 'number' ? +v.toPrecision(5) : v; }
function seedOf(s) { let h = 2166136261; for (const ch of s) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619) >>> 0; } return h; }

// 万用表类的读数：按这块板的记录值换算成仪器上看到的数（带万用表的分辨力与读数抖动）
const meter = computed(() => {
  tick.value;
  const s = st.value;
  if (!s) return { text: '', sub: '' };
  const g = gaussFrom(mulberry32(seedOf(sel.value + s.key) + tick.value));
  if (s.inst === 'dmm4w') {          // 四线法：用 200 mV 档量 10 A 测试电流下的压降，换算成阻值
    const v = 10 * s.true / 1000;
    const r = dmmRead(v, g, 0.2);
    return { text: (r.value / 10 * 1000).toFixed(4) + ' mΩ', sub: t('四线电阻：测试电流 10.000 A，压降 {v} mV（200 mV 档）', { v: (r.value * 1000).toFixed(3) }) };
  }
  if (s.inst === 'dmm') {
    const vt = 48.0;
    const m = dmmRead(vt, g, 200);
    const board = vt * (1 + s.true / 100);
    return { text: t('万用表 {m} V　板子报 {b} V', { m: m.value.toFixed(3), b: board.toFixed(2) }), sub: t('误差 = (板子 − 万用表) ÷ 万用表 × 100%') };
  }
  if (s.inst === 'isrc') return { text: t('电流源 10.000 A　板子报 {b} A', { b: (10 * (1 + s.true / 100)).toFixed(3) }), sub: t('误差 = (板子 − 10) ÷ 10 × 100%') };
  if (s.inst === 'enc') return { text: t('发出 4000 计数　板子报 {b}', { b: Math.round(4000 + s.true) }), sub: t('误差 = 板子 − 4000') };
  if (s.inst === 'zero') return { text: t('零电流时板子报 {b} mA', { b: (s.true).toFixed(0) }), sub: t('老化 2 小时后') };
  return { text: '', sub: '' };
});

// 死区：上下管栅极 0 / 12 V，开关沿 30 ns（示例）；下管 t=0 关断，过 dead 后上管开通
const traces = computed(() => {
  const s = st.value;
  if (!s || s.inst !== 'scope') return [];
  const dead = s.true * 1e-9;
  const edge = 30e-9;
  const ramp = (t) => Math.max(0, Math.min(1, t / edge));
  const gl = { name: 'GL_A', fn: (t) => (t < 0 ? 12 : 12 * (1 - ramp(t))) };
  const gh = { name: 'GH_A', fn: (t) => 12 * ramp(t - dead - edge * 2 / 3) };   // 两条在 2 V 处的间隔 = 死区
  const g = gaussFrom(mulberry32(seedOf(sel.value)));
  return scopeAcquire([gh, gl], { tdiv: tdiv.value, vdiv: [5, 5], off: [-5, 15], trigCh: 1, trigLevel: null }, g);
});

async function load() {
  try { boards.value = (await get('/fct')).boards; } catch (e) { err.value = e.message; }
}
async function open(s) {
  sel.value = s; res.value = null; ans.value = {}; verdict.value = ''; step.value = 0;
  try { c.value = await get('/fct/' + encodeURIComponent(s)); } catch (e) { err.value = e.message; }
}
async function submit() {
  try {
    res.value = await post('/fct/' + encodeURIComponent(sel.value) + '/retest', { readings: ans.value, verdict: verdict.value });
    c.value = await get('/fct/' + encodeURIComponent(sel.value));
  } catch (e) { err.value = e.message; }
}
watch(step, () => { tick.value = 0; });
onMounted(async () => { await load(); const s = route.query.serial || boards.value[0]?.serial; if (s) open(String(s)); });
</script>

<style scoped>
.cols { display: grid; grid-template-columns: 260px 1fr; gap: 12px; }
@media (max-width: 800px) { .cols { grid-template-columns: 1fr; } }
.list { max-height: 80vh; overflow: auto; }
.brd { display: flex; flex-direction: column; align-items: flex-start; width: 100%; border: 1px solid #e3e6ee; background: #fff; border-radius: 6px; padding: 4px 8px; margin: 3px 0; cursor: pointer; text-align: left; }
.brd.on { border-color: #1d4ed8; background: #eef4ff; }
.steps { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; }
.meter { background: #0b1220; color: #a7f3d0; border-radius: 8px; padding: 12px 16px; max-width: 560px; }
.disp { font-size: 22px; }
.form { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: end; }
.form input { width: 110px; }
.line { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 6px 0; }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; margin: 6px 0; }
.tbl th, .tbl td { border-bottom: 1px solid #eef0f5; padding: 3px 6px; text-align: left; }
.ok { color: #15803d; } .bad { color: #b91c1c; }
.btn.sm { padding: 1px 8px; font-size: 12px; }
</style>
