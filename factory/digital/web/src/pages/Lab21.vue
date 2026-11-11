<!-- 实验 21“能源：空转、错峰与单件碳足迹”（第 18 轮 E6-10）：空转最多的设备、单件电量与碳、比较待机方案（比对模式）、执行、一个月省多少 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('实验 21 · 能源：空转、错峰与单件碳足迹') }}</h1>
      <span class="muted">{{ $t('平台自动评 {a} 分（按平台里的事实），报告 {b} 分由老师在课程里批改', { a: s?.of || 60, b: s?.report_points || 40 }) }}</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab21/guide.docx">{{ $t('指导书') }}</a> · <a href="/api/cae/lab21/report-template.docx">{{ $t('报告模板') }}</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b class="big">{{ $td(s.score) }} / {{ $td(s.of) }}</b>
        <span v-if="!s.teacher" class="pill" :class="s.locked ? 'warn' : 'good'">{{ s.locked ? $t('比对模式：提交任务 3 之前，指挥台和 AI 不显示建议') : $t('已提交选择：可以看中枢的建议，和你的对比') }}</span>
        <span class="small" :class="s.sim ? 'ok' : 'muted'">{{ $t('能源模拟器{a}', { a: s.sim ? $t('已打开') : $t('没打开') }) }}</span>
        <span v-if="s.lab" class="small">{{ $t('已注入：{a} 下班忘关、峰时开炉', { a: s.unit.toUpperCase() }) }}</span>
        <router-link v-if="s.anomaly_id" class="small" :to="{ path: '/ont', query: { view: 'anomalies', a: s.anomaly_id } }">{{ $t('打开 {a} 空转异常', { a: s.unit.toUpperCase() }) }}</router-link>
        <router-link class="small" to="/energy?tab=overview">{{ $t('能源总览') }}</router-link>
        <router-link class="small" to="/energy?tab=unit">{{ $t('单耗') }}</router-link>
        <span class="small muted">{{ $t('电价 峰 ${a} / 平 ${b} / 谷 ${c}；排放因子 {d} kg/度', { a: $td(s.price.peak), b: $td(s.price.flat), c: $td(s.price.valley), d: $td(s.factor) }) }}</span>
        <span v-if="!s.teacher && session.user?.role !== 'planner'" class="small warn-t">{{ $t('提示：节能设定用“计划员”角色发起（右上角切换角色）。') }}</span>
      </div>

      <section v-if="s.teacher" class="card">
        <div class="card-head"><h2>{{ $t('老师：设置') }}</h2><span class="small muted">{{ $t('学生看不到这里') }}</span></div>
        <div class="row">
          <button class="btn" @click="inject({ enable: !s.sim, only_toggle: true })">{{ $t('{a}能源模拟器', { a: s.sim ? $t('关闭') : $t('打开') }) }}</button>
          <button class="btn danger" @click="inject({ enable: true })">{{ $t('注入：{a} 下班忘关 + 峰时开炉', { a: s.unit.toUpperCase() }) }}</button>
          <span class="small ok">{{ injMsg }}</span>
        </div>
        <p class="small muted">{{ $t('空转满 1 小时（工厂时间；20 倍速约 3 分钟）后厂情中枢出异常；这两个问题不会被模拟器自动“修好”。') }}</p>
        <table v-if="s.class?.length" class="tbl small"><thead><tr><th>{{ $t('学生') }}</th><th v-for="t in s.tasks" :key="t.id" class="num">{{ $td(t.title) }}</th><th class="num">{{ $t('合计') }}</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ $td(c.user) }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ $td(c.total) }}</b></td></tr></tbody></table>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>{{ $t('任务 {a}　{b}', { a: i + 1, b: $td(t.title) }) }}</h2><span class="pts">{{ $td(t.score) }} / {{ $td(t.points) }}</span></div>
        <p>{{ $td(t.desc) }}</p>
        <p class="small muted">{{ $t('提示：{a}', { a: $td(t.hint) }) }}</p>
        <form v-if="t.id === 'l21_t1'" class="f" @submit.prevent="submit('l21_t1', a1)">
          <div class="field"><label>{{ $t('空转电量最多的设备') }}</label><select v-model="a1.unit" required><option v-for="u in s.units" :key="u.value" :value="u.value">{{ $td(u.label) }}</option></select></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l21_t2'" class="f" @submit.prevent="submit('l21_t2', a2)">
          <div class="field"><label>{{ $t('SH-301 每件运行电量（度，不含热处理）') }}</label><input v-model.number="a2.kwh" type="number" step="0.01" required></div>
          <div class="field"><label>{{ $t('每件碳排放（kg CO2e）') }}</label><input v-model.number="a2.co2_kg" type="number" step="0.01" required></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 'l21_t3'" class="f" @submit.prevent="submit('l21_t3', a3)">
          <div class="field"><label>{{ $t('选哪个方案') }}</label><span class="cks">
            <label v-for="o in s.options" :key="o.value"><input v-model="a3.option" type="radio" :value="o.value" required> {{ $td(o.label) }}</label></span></div>
          <div class="field"><label>{{ $t('理由与代价') }}</label><textarea v-model="a3.reason" rows="3" required :placeholder="$t('省多少度、多少钱、多少碳；预热会不会耽误交期……')"></textarea></div>
          <button class="btn primary" :disabled="!s.anomaly_id">{{ $t('提交选择') }}</button>
        </form>
        <div v-if="t.id === 'l21_t4'" class="small">
          <template v-if="t.evidence?.actions?.length">{{ $t('你的动作：') }}<span v-for="x in t.evidence.actions" :key="x.id"> {{ $t('ACT-{a}（{b}）', { a: String(x.id).padStart(5, '0'), b: ST[x.status] || x.status }) }}</span>
            <span> {{ $t('· 车间设定：{a}', { a: t.evidence.standby_on ? s.unit.toUpperCase() + $t(' 已自动待机') : $t('还没生效') }) }}</span></template>
          <template v-else>{{ $t('还没有包含 {a} 的节能设定动作。', { a: s.unit.toUpperCase() }) }}</template> <router-link to="/ont/actions?box=mine">{{ $t('动作收件箱') }}</router-link>
        </div>
        <form v-if="t.id === 'l21_t5'" class="f" @submit.prevent="submit('l21_t5', a5)">
          <div class="field"><label>{{ $t('① 错峰一个月省的电费（$）') }}</label><input v-model.number="a5.tou_usd" type="number" step="0.01" required></div>
          <div class="field"><label>{{ $t('② 错峰一个月少排的碳（kg）') }}</label><input v-model.number="a5.tou_co2" type="number" step="0.1" required></div>
          <div class="field"><label>{{ $t('③ {a} 每晚待机一个月少排的碳（kg）', { a: s.unit.toUpperCase() }) }}</label><input v-model.number="a5.standby_co2" type="number" step="0.1" required></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <p v-if="fb[t.id]" class="small fb">{{ $td(fb[t.id]) }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { onMounted, reactive, ref } from 'vue';
import { get, post, session } from '../lib/api';

const ST = { draft: $t('草稿'), submitted: $t('待批准'), approved: $t('已批准'), rejected: $t('已驳回'), executing: $t('执行中'), done: $t('已完成'), failed: $t('失败') };
const s = ref(null);
const err = ref('');
const fb = reactive({});
const a1 = reactive({ unit: '' });
const a2 = reactive({ kwh: null, co2_kg: null });
const a3 = reactive({ option: '', reason: '' });
const a5 = reactive({ tou_usd: null, tou_co2: null, standby_co2: null });
const injMsg = ref('');

async function load() {
  try { s.value = await get('/lab21'); } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab21/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; await load(); } catch (e) { alert(e.message); }
}
async function inject(body) {
  try { injMsg.value = (await post('/lab21/inject', body)).text; await load(); } catch (e) { alert(e.message); }
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
.field { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.field > label:first-child { width: 260px; font-weight: 500; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 300px; font-size: 13px; }
input[type=number] { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; width: 110px; }
textarea { flex: 1 1 300px; border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
.ok { color: var(--good); }
.warn-t { color: var(--warn); }
</style>
