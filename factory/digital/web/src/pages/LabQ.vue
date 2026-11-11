<!-- 通用质量追因实验页（第 147 轮，照实验 32）：/labq/35、/labq/36……一座厂一份配置（hub/labq.py）。控制图判异 → 按设备分层 → 8D → 数据验证 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('实验 {a} · {b}', { a: no, b: s ? $td(s.title) : '' }) }}</h1>
      <span class="muted">{{ $t('平台自动评 {a} 分（按平台里的事实），报告 {b} 分由老师在课程里批改', { a: s?.of || 60, b: s?.report_points || 40 }) }}</span>
      <span class="r small" data-help="lab-links"><a :href="`/api/cae/lab${no}/guide.docx`">{{ $t('指导书') }}</a> · <a :href="`/api/cae/lab${no}/report-template.docx`">{{ $t('报告模板') }}</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ $td(s.score) }} / {{ $td(s.of) }}</b>
        <span class="pill" :class="s.injected ? 'warn' : ''">{{ s.injected ? $t('老师已注入问题：从数据里找原因') : $t('等老师注入问题') }}</span>
        <router-link class="small" to="/work/quality">{{ $t('质量（控制图）') }}</router-link>
        <router-link class="small" to="/quality/8d">{{ $t('质量异常单（8D）') }}</router-link>
        <button class="btn sm" @click="load">{{ $t('刷新') }}</button>
      </div>

      <section v-if="s.teacher" class="card">
        <div class="card-head"><h2>{{ $t('老师：注入隐藏问题') }}</h2><span class="small muted">{{ $t('学生看不到这里') }}</span></div>
        <div class="row">
          <select v-model="kind" :aria-label="$t('问题')"><option value="random">{{ $t('随机五选一（学生不知道是哪种）') }}</option>
            <option v-for="k in s.inject_kinds" :key="k.value" :value="k.value">{{ $td(k.label) }}</option></select>
          <button class="btn danger" @click="inject">{{ $t('注入') }}</button><span class="small ok">{{ injMsg }}</span>
        </div>
        <p v-if="s.problem" class="small">{{ $t('当前：{a}（{b} 注入{c}）', { a: $td(s.problem.name), b: timeOf(s.problem.injected_at), c: s.problem.cleared_at ? $t('，已被措施消除') : '' }) }}</p>
        <p class="small muted">{{ $t('注入后让车间接着做：在“订单与计划”接几张单（每张 6–10 件）并下达。学生的 8D 措施要您在“质量异常单”里批准，批准后才下发车间。') }}</p>
        <table v-if="s.class?.length" class="tbl small"><thead><tr><th>{{ $t('学生') }}</th><th v-for="(t, i) in s.tasks" :key="t.id" class="num">{{ $t('任务 {a}', { a: i + 1 }) }}</th><th class="num">{{ $t('合计') }}</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ $td(c.user) }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ $td(c.total) }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>{{ $t('任务 {a}　{b}', { a: i + 1, b: $td(t.title) }) }}</h2><span class="pts">{{ $td(t.score) }} / {{ $td(t.points) }}</span></div>
        <p>{{ $td(t.desc) }}</p>
        <p class="small muted">{{ $t('提示：{a}', { a: $td(t.hint) }) }}</p>
        <form v-if="t.id === pre + 't1'" class="f" @submit.prevent="submit(t.id, a1)">
          <div class="lf"><label>{{ $t('出问题的特性') }}</label><select v-model="a1.characteristic" required>
            <option v-for="c in s.characteristics" :key="c.value" :value="c.value">{{ $td(c.label) }}</option></select></div>
          <div class="lf"><label>{{ $t('触发的判异规则') }}</label><span class="cks">
            <label v-for="r in s.rules" :key="r"><input v-model="a1.rule" type="radio" :value="r" required> {{ $t('规则 {a}', { a: r }) }}</label></span></div>
          <button class="btn primary" :disabled="!s.injected">{{ $t('提交') }}</button>
        </form>
        <template v-if="t.id === pre + 't2'">
          <div class="lf f"><label>{{ $t('看哪个特性分层') }}</label><select v-model="sel" @change="loadStrata">
            <option v-for="c in s.characteristics" :key="c.value" :value="c.value">{{ $td(c.label) }}</option></select></div>
          <div v-if="strata" class="strata">
            <div v-if="strata.station">
              <b class="small">{{ $td(s.station) }}</b>
              <table class="tbl small"><thead><tr><th>{{ $t('设备') }}</th><th class="num">{{ $t('件数') }}</th><th class="num">{{ $t('均值') }}</th><th class="num">{{ $t('超差') }}</th></tr></thead>
                <tbody><tr v-for="(x, k) in strata.station" :key="k"><td class="mono">{{ k }}</td><td class="num">{{ $td(x.n) }}</td><td class="num">{{ $td(x.mean) }}</td>
                  <td class="num" :class="{ 'bad-t': x.fails }">{{ $td(x.fails) }}</td></tr></tbody></table>
              <p v-if="!Object.keys(strata.station).length" class="small muted">{{ $t('这个特性没有按设备分组的数据。') }}</p>
            </div>
            <div v-if="strata.lot">
              <b class="small">{{ $td(s.lot) }}</b>
              <table class="tbl small"><thead><tr><th>{{ $t('批次') }}</th><th class="num">{{ $t('件数') }}</th><th class="num">{{ $t('均值') }}</th><th class="num">{{ $t('超差') }}</th></tr></thead>
                <tbody><tr v-for="(x, k) in strata.lot" :key="k"><td class="mono">{{ k }}</td><td class="num">{{ $td(x.n) }}</td><td class="num">{{ $td(x.mean) }}</td>
                  <td class="num" :class="{ 'bad-t': x.fails }">{{ $td(x.fails) }}</td></tr></tbody></table>
              <p v-if="!Object.keys(strata.lot).length" class="small muted">{{ $t('这个特性没有按批次分组的数据。') }}</p>
            </div>
            <p v-if="!strata.station && !strata.lot" class="small muted">{{ $t('这座厂按工序和设备找原因：看哪道工序之后的数据偏了，对照“设备”页。') }}</p>
          </div>
          <form class="f" @submit.prevent="submit(t.id, a2)">
            <div class="lf"><label>{{ $t('问题出在') }}</label><span class="cks">
              <label v-for="l in s.layers" :key="l.value"><input v-model="a2.by" type="radio" :value="l.value" required> {{ $td(l.label) }}</label></span></div>
            <div v-if="a2.by" class="lf"><label>{{ a2.by === 'lot' ? $t('哪一批（批次号）') : $t('哪台设备（编号）') }}</label><input v-model="a2.group" :placeholder="a2.by === 'lot' ? $t('批次号，见上面的分批表') : $t('设备编号，见“设备”页')" required></div>
            <button class="btn primary" :disabled="!s.injected">{{ $t('提交') }}</button>
          </form>
        </template>
        <div v-if="[pre + 't3', pre + 't4', pre + 't5'].includes(t.id)" class="small">
          <template v-if="t.evidence?.q8d">{{ $t('你的 8D：') }}<router-link :to="'/quality/8d/' + t.evidence.q8d">{{ $td(t.evidence.q8d) }}</router-link>
            <span v-if="t.id === pre + 't4' && t.evidence.effective === false">{{ $t('（措施对了，等车间再做 10 台后在 8D 页点“验证”）') }}</span></template>
          <template v-else-if="t.evidence?.note">{{ $td(t.evidence.note) }}</template>
          <template v-else>{{ $t('平台自动检查你的 8D 单。') }}</template>
        </div>
        <p v-if="fb[t.id]" class="small fb">{{ $td(fb[t.id]) }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { get, post } from '../lib/api';
import { timeOf } from '../lib/fmt';

const route = useRoute();
const no = computed(() => Number(route.params.no));
const pre = computed(() => 'l' + no.value + '_');
const s = ref(null);
const err = ref('');
const fb = reactive({});
const a1 = reactive({ characteristic: '', rule: null });
const a2 = reactive({ by: '', group: '' });
const kind = ref('random');
const injMsg = ref('');
const sel = ref('');
const strata = ref(null);

async function load() {
  try {
    s.value = await get('/labq/' + no.value); err.value = '';
    if (!sel.value && s.value.characteristics.length) { sel.value = s.value.characteristics[0].value; loadStrata(); }
  } catch (e) { err.value = e.message; }
}
async function loadStrata() {
  try { strata.value = await get('/labq/' + no.value + '/strata?sel=' + encodeURIComponent(sel.value)); } catch { strata.value = null; }
}
async function submit(tid, body) {
  try { const r = await post('/labq/' + no.value + '/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { alert(e.message); }
}
async function inject() {
  try { injMsg.value = (await post('/labq/' + no.value + '/inject', { kind: kind.value })).text; await load(); } catch (e) { alert(e.message); }
}
onMounted(load);
watch(no, () => { s.value = null; sel.value = ''; strata.value = null; load(); });
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.r { margin-left: auto; }
.sum { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
.big { font-size: 24px; }
.task.done { border-left: 4px solid var(--good); }
.pts { margin-left: auto; font-weight: 600; }
.f { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.lf { display: flex; flex-direction: row; gap: 10px; align-items: flex-start; flex-wrap: wrap; }
.lf > label:first-child { width: 170px; font-weight: 500; padding-top: 4px; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 auto; min-width: 240px; font-size: 13px; }
.f .btn { align-self: flex-start; }
select, input:not([type]) { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.strata { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; margin: 8px 0; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; }
.num { text-align: right; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.ok { color: var(--good); }
.bad-t { color: var(--bad); }
</style>
