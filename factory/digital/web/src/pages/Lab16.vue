<!-- 实验 16“客户投诉的追溯、召回与服务决策”（第 18 轮 E1-12）：先自己追溯、标风险、选方案，提交后才看中枢的建议 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('实验 16 · 客户投诉的追溯、召回与服务决策') }}</h1>
      <span class="muted">{{ $t('平台自动评 {a} 分（按平台里的事实），报告 {b} 分由老师在课程里批改', { a: s?.of || 60, b: s?.report_points || 40 }) }}</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab16/guide.docx">{{ $t('指导书') }}</a> · <a href="/api/cae/lab16/report-template.docx">{{ $t('报告模板') }}</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ $td(s.score) }} / {{ $td(s.of) }}</b>
        <span v-if="!s.teacher" class="pill" :class="s.locked ? 'warn' : 'good'">{{ s.locked ? $t('比对模式：提交任务 3 之前，指挥台和 AI 不显示建议') : $t('已提交选择：可以看中枢的建议，和你的对比') }}</span>
        <router-link v-if="s.anomaly_id" class="small" :to="{ path: '/ont', query: { view: 'anomalies', a: s.anomaly_id } }">{{ $t('打开这条投诉的异常') }}</router-link>
        <router-link class="small" to="/service">{{ $t('客户与服务') }}</router-link>
        <router-link class="small" to="/twin">{{ $t('数字孪生') }}</router-link>
        <span v-if="!s.teacher && session.user?.role !== 'service'" class="small warn-t">{{ $t('提示：服务动作要用“售后”角色发起（右上角切换角色）。') }}</span>
      </div>

      <section v-if="s.teacher" class="card">
        <div class="card-head"><h2>{{ $t('老师：注入批次投诉') }}</h2><span class="small muted">{{ $t('学生看不到这里') }}</span></div>
        <div class="row">
          {{ $t('同一片砂轮磨的轴所在的') }} <input v-model.number="inj.n" type="number" min="2" max="3" :aria-label="$t('台数')"> {{ $t('台设备出轴承问题') }}
          <button class="btn danger" @click="inject">{{ $t('注入') }}</button><span class="small ok">{{ injMsg }}</span>
        </div>
        <p class="small muted">{{ $t('注入后客户会在接下来几个现场日陆续来电（现场时钟默认 1 分钟 = 1 天，可在数字孪生页调）。学生采纳方案后，派工和备件出库要您（厂长）在动作收件箱批准。') }}</p>
        <table v-if="s.class?.length" class="tbl small"><thead><tr><th>{{ $t('学生') }}</th><th v-for="t in s.tasks" :key="t.id" class="num">{{ $td(t.title) }}</th><th class="num">{{ $t('合计') }}</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ $td(c.user) }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ $td(c.total) }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>{{ $t('任务 {a}　{b}', { a: i + 1, b: $td(t.title) }) }}</h2><span class="pts">{{ $td(t.score) }} / {{ $td(t.points) }}</span></div>
        <p>{{ $td(t.desc) }}</p>
        <p class="small muted">{{ $t('提示：{a}', { a: $td(t.hint) }) }}</p>
        <form v-if="t.id === 'l16_t1'" class="f" @submit.prevent="submit('l16_t1', a1)">
          <div class="field"><label>{{ $t('投诉') }}</label><select v-model="a1.complaint_id" required>
            <option v-for="o in s.options.complaints" :key="o.value" :value="o.value">{{ $td(o.label) }}</option></select></div>
          <div class="field"><label>{{ $t('磨削用的砂轮') }}</label><select v-model="a1.wheel" required>
            <option v-for="w in s.options.wheels" :key="w" :value="w">{{ $td(w) }}</option></select></div>
          <div class="field"><label>{{ $t('排查范围（不含投诉的那台）') }}</label><span class="cks">
            <label v-for="u in s.options.units" :key="u.value"><input v-model="a1.units" type="checkbox" :value="u.value"> {{ $td(u.label) }}</label></span></div>
          <button class="btn primary">{{ $t('提交追溯结果') }}</button>
        </form>
        <form v-if="t.id === 'l16_t2'" class="f" @submit.prevent="submit('l16_t2', a2)">
          <div class="field"><label>{{ $t('高风险的设备') }}</label><span class="cks">
            <label v-for="u in scopeUnits" :key="u.value"><input v-model="a2.units" type="checkbox" :value="u.value"> {{ $td(u.label) }}</label></span></div>
          <p v-if="!scopeUnits.length" class="small muted">{{ $t('先完成任务 1。') }}</p>
          <button class="btn primary" :disabled="!scopeUnits.length">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l16_t3'" class="f" @submit.prevent="submit('l16_t3', a3)">
          <div class="field"><label>{{ $t('选哪个方案') }}</label><span class="cks">
            <label v-for="k in ['A', 'B', 'C']" :key="k"><input v-model="a3.option" type="radio" :value="k" required> {{ $t('方案 {a}', { a: k }) }}</label></span></div>
          <div class="field"><label>{{ $t('理由与代价') }}</label><textarea v-model="a3.reason" rows="3" required :placeholder="$t('费用、风险（漏掉的高风险设备）、客户……')"></textarea></div>
          <button class="btn primary" :disabled="!s.complaint_id">{{ $t('提交选择') }}</button>
        </form>
        <div v-if="t.id === 'l16_t4'" class="small">
          <template v-if="t.evidence?.actions?.length">{{ $t('你的动作：') }}<span v-for="x in t.evidence.actions" :key="x.id"> {{ $t('ACT-{a} {b}（{c}）', { a: String(x.id).padStart(5, '0'), b: TY[x.type] || x.type, c: ST[x.status] || x.status }) }}</span></template>
          <template v-else>{{ $t('还没有动作。') }}</template> <router-link to="/ont/actions?box=mine">{{ $t('动作收件箱') }}</router-link>
        </div>
        <form v-if="t.id === 'l16_t5'" class="f" @submit.prevent="submit('l16_t5', a5)">
          <div class="field"><label>{{ $t('回访平均分') }}</label><span class="cks">
            <label v-for="b in s.buckets" :key="b"><input v-model="a5.bucket" type="radio" :value="b" required> {{ $td(b) }}</label></span></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <p v-if="fb[t.id]" class="small fb">{{ $td(fb[t.id]) }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, reactive, ref } from 'vue';
import { get, post, session } from '../lib/api';

const ST = { draft: $t('草稿'), submitted: $t('待批准'), approved: $t('已批准'), rejected: $t('已驳回'), executing: $t('执行中'), done: $t('已完成'), failed: $t('失败') };
const TY = { service_batch: $t('服务派工'), spare_ship: $t('备件出库'), customer_notice: $t('客户通知') };
const s = ref(null);
const err = ref('');
const fb = reactive({});
const a1 = reactive({ complaint_id: null, wheel: '', units: [] });
const a2 = reactive({ units: [] });
const a3 = reactive({ option: '', reason: '' });
const a5 = reactive({ bucket: '' });
const inj = reactive({ n: 3 });
const injMsg = ref('');

// 任务 2 只在任务 1 填的排查范围里选（加上系统给的，防止学生漏的设备没法标）
const scopeUnits = computed(() => {
  const t1 = s.value?.tasks?.find((t) => t.id === 'l16_t1')?.evidence;
  if (!t1) return [];
  const keep = new Set([...(t1.answer?.units || []), ...(t1.expected?.units || [])]);
  return (s.value.options.units || []).filter((u) => keep.has(u.value))
    .map((u) => ({ ...u, label: $t('{a}（健康度 {b}，轴承已用 {c}%）', { a: u.label, b: ({ red: $t('红'), yellow: $t('黄'), green: $t('绿') })[u.health] || u.health, c: Math.round(u.bearing_used * 100) }) }));
});

async function load() {
  try {
    s.value = await get('/lab16');
    if (s.value.complaint_id && !a1.complaint_id) a1.complaint_id = s.value.complaint_id;
  } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab16/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { alert(e.message); }
}
async function inject() {
  try { injMsg.value = (await post('/lab16/inject', { ...inj })).text; await load(); } catch (e) { alert(e.message); }
}
onMounted(load);
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.r { margin-left: auto; }
.sum { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
.big { font-size: 24px; }
.task.done { border-left: 4px solid var(--good); }
.pts { margin-left: auto; font-weight: 600; }
.f { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.field { display: flex; gap: 10px; align-items: flex-start; flex-wrap: wrap; }
.field > label:first-child { width: 170px; font-weight: 500; padding-top: 4px; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 300px; font-size: 13px; }
select, input[type=number] { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
textarea { flex: 1 1 300px; border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
input[type=number] { width: 70px; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.ok { color: var(--good); }
.warn-t { color: var(--warn); }
</style>
