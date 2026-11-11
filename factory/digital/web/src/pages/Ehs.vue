<!-- 安全环保（第 18 轮 E2）：隐患随手拍、作业许可、事故与未遂、培训与资质、化学品与废弃物。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('安全环保') }}</h1>
      <span class="muted">{{ $t('隐患随手拍 → 整改 → 验收；作业许可核对资质；挂牌上锁时车间里这台设备真的停下') }}</span>
      <span class="tabs" data-help="ehs-tabs" role="tablist"><button v-for="(l, k) in TABS" :key="k" type="button" role="tab" :class="{ on: tab === k }" @click="go(k)">{{ l }}
        <span v-if="k === 'issues' && kp?.major_open" class="cnt">{{ $td(kp.major_open) }}</span></button></span></div>
    <div v-if="err" class="err">{{ err }}</div>

    <section v-if="kp" class="kpis" data-help="ehs-kpis">
      <div class="card k"><span class="small muted">{{ $t('开着的隐患') }}</span><b>{{ $td(kp.open_issues) }}</b><span class="small" :class="{ bad: kp.major_open }">{{ $t('重大 {a} · 逾期 {b}', { a: $td(kp.major_open), b: $td(kp.overdue) }) }}</span></div>
      <div class="card k"><span class="small muted">{{ $t('整改按期率（近 30 天）') }}</span><b>{{ kp.on_time == null ? '—' : Math.round(kp.on_time * 100) + '%' }}</b></div>
      <div class="card k"><span class="small muted">{{ $t('挂牌上锁的设备') }}</span><b>{{ $td(kp.locked) }}</b></div>
      <div class="card k"><span class="small muted">{{ $t('培训 30 天内到期') }}</span><b>{{ $td(kp.training_due) }}</b><span class="small muted">{{ $t('已过期 {a}', { a: $td(kp.training_expired) }) }}</span></div>
      <div class="card k"><span class="small muted">{{ $t('未遂（近 30 天）') }}</span><b>{{ $td(kp.near_miss_30d) }}</b><span class="small muted">{{ $t('危废超期 {a} 批', { a: $td(kp.waste_over) }) }}</span></div>
    </section>

    <!-- ① 隐患 -->
    <template v-if="tab === 'issues' && is">
      <div class="card" data-help="ehs-report">
        <h3>{{ $t('随手拍') }}</h3>
        <div class="grid3">
          <label>{{ $t('设备 / 位置') }}<select v-model="ni.unit"><option value="">{{ $t('（区域，不是某台设备）') }}</option>
            <option v-for="(n, u) in UNITS" :key="u" :value="u">{{ u.toUpperCase() }} {{ $td(n) }}</option></select></label>
          <label>{{ $t('种类') }}<select v-model="ni.kind" @change="ni.level = is.kinds[ni.kind].level">
            <option v-for="(v, k) in is.kinds" :key="k" :value="k">{{ $td(v.label) }}</option></select></label>
          <label>{{ $t('等级') }}<select v-model="ni.level"><option v-for="(l, k) in is.levels" :key="k" :value="k">{{ $td(l) }}</option></select></label>
          <label class="w2">{{ $t('一句话') }}<input v-model="ni.subject" :placeholder="$t('例如：磨床防护罩螺丝松了，砂轮露出一截')"></label>
          <label>{{ $t('照片') }}<input type="file" accept="image/*" capture="environment" @change="photo"></label>
        </div>
        <button class="btn primary sm" :disabled="busy" @click="newIssue">{{ $t('提交') }}</button> <span class="small ok">{{ msg }}</span>
        <span v-if="ni.photo_ids.length" class="small muted">{{ $t('已附 {a} 张照片', { a: $td(ni.photo_ids.length) }) }}</span>
      </div>
      <div class="filters small"><label><input v-model="isOpen" type="checkbox" @change="loadIs"> {{ $t('只看没关闭的') }}</label></div>
      <p v-if="!is.issues.length" class="muted small">{{ $t('没有隐患。') }}</p>
      <div v-for="x in is.issues" :key="x.id" class="card item" :class="x.level">
        <div class="ih"><span class="mono small">{{ $td(x.key) }}</span><b>{{ $td(x.subject) }}</b>
          <span class="pill" :class="x.level === 'major' ? 'bad' : 'mute'">{{ $td(x.level_label) }}</span>
          <span class="pill" :class="x.status === 'closed' ? 'good' : x.overdue ? 'bad' : 'warn'">{{ $td(x.status_label) }}{{ x.overdue ? $t(' · 逾期') : '' }}</span></div>
        <div class="small">{{ $t('{a} · 发现人 {b} · {c}· 整改期限 {d}', { a: x.unit ? x.unit.toUpperCase() + ' ' + $td(x.unit_name || '') : x.area || '—', b: $td(x.found_by), c: fmtTs(x.found_at), d: $td(x.due_day) }) }}<template v-if="x.owner"> {{ $t('· 整改人 {a}', { a: who(x.owner) }) }}</template><template v-if="x.permit_id"> {{ $t('· 挂牌上锁 PTW-{a}', { a: String(x.permit_id).padStart(5, '0') }) }}</template></div>
        <div v-if="x.photo_ids.length" class="photos"><a v-for="p in x.photo_ids" :key="p" :href="'/api/files/' + p" target="_blank"><img :src="'/api/files/' + p" :alt="$t('隐患照片')"></a></div>
        <div class="act">
          <router-link v-if="x.anomaly_id" :to="{ path: '/ont', query: { view: 'anomalies', a: x.anomaly_id } }" class="btn sm primary">{{ $t('影响与处理方案') }}</router-link>
          <template v-if="x.status !== 'closed'">
            <template v-if="is.can_manage && x.status === 'open'">
              <select v-model="own[x.id]" :aria-label="$t('整改人')"><option v-for="p in is.people" :key="p.id" :value="p.id">{{ $t('{a}（{b}）', { a: $td(p.name), b: $td(p.post) }) }}</option></select>
              <button class="btn sm" @click="assign(x)">{{ $t('指派') }}</button></template>
            <button v-if="x.status !== 'fixed'" class="btn sm" @click="fixIt(x)">{{ $t('整改完成') }}</button>
            <button v-if="is.can_manage && x.status === 'fixed'" class="btn sm primary" @click="verify(x)">{{ $t('验收关闭{a}', { a: x.permit_id ? $t('并解锁') : '' }) }}</button>
          </template>
        </div>
      </div>

      <details class="card" @toggle="loadHz"><summary><b>{{ $t('危险源清单') }}</b> <span class="small muted">{{ $t('（可能性 × 严重度：≥ 15 重大，8–14 较大）') }}</span></summary>
        <table v-if="hz" class="tbl small"><thead><tr><th>{{ $t('编号') }}</th><th>{{ $t('危险源') }}</th><th>{{ $t('设备') }}</th><th class="num">{{ $t('可能性') }}</th><th class="num">{{ $t('严重度') }}</th><th>{{ $t('风险') }}</th><th>{{ $t('控制措施') }}</th></tr></thead>
          <tbody><tr v-for="h in hz.hazards" :key="h.id"><td class="mono">{{ $td(h.id) }}</td><td>{{ $td(h.name) }}</td><td>{{ (h.unit || '—').toUpperCase() }}</td>
            <td class="num">{{ $td(h.likelihood) }}</td><td class="num">{{ $td(h.severity) }}</td><td>{{ $t('{a}（{b}）', { a: $td(h.risk.score), b: $td(h.risk.level) }) }}</td><td>{{ h.controls.join($t('、')) }}</td></tr></tbody></table>
      </details>
    </template>

    <!-- ② 作业许可 -->
    <template v-if="tab === 'permits' && pm">
      <div v-if="pm.can_manage" class="card">
        <h3>{{ $t('申请作业许可') }}</h3>
        <div class="grid3">
          <label>{{ $t('种类') }}<select v-model="np.kind"><option v-for="(l, k) in pm.kinds" :key="k" :value="k">{{ $td(l) }}</option></select></label>
          <label>{{ $t('设备') }}<select v-model="np.unit"><option value="">{{ $t('（不限设备）') }}</option><option v-for="(n, u) in UNITS" :key="u" :value="u">{{ u.toUpperCase() }} {{ $td(n) }}</option></select></label>
          <label>{{ $t('作业人') }}<select v-model="np.holder_id"><option v-for="p in pm.people" :key="p.id" :value="p.id">{{ $t('{a}（{b}）', { a: $td(p.name), b: $td(p.post) }) }}</option></select></label>
          <label>{{ $t('预计时长（分钟）') }}<input v-model.number="np.minutes" type="number" min="10" step="10"></label>
          <label class="w2">{{ $t('内容') }}<input v-model="np.reason" :placeholder="$t('例如：热处理炉炉膛检修')"></label>
        </div>
        <p class="small muted">{{ $t('提交时自动核对作业人的培训：动火、高处、受限空间、挂牌上锁各要对应的培训在有效期内，否则许可被拦下。挂牌上锁批准后，车间里这台设备马上停下，直到验收解锁。') }}</p>
        <button class="btn primary sm" @click="newPermit">{{ $t('提交申请') }}</button> <span class="small" :class="pmMsgOk ? 'ok' : 'bad'">{{ pmMsg }}</span>
      </div>
      <table class="tbl small card"><thead><tr><th>{{ $t('许可') }}</th><th>{{ $t('种类') }}</th><th>{{ $t('设备') }}</th><th>{{ $t('作业人') }}</th><th>{{ $t('状态') }}</th><th>{{ $t('内容') }}</th><th></th></tr></thead>
        <tbody><tr v-for="p in pm.permits" :key="p.id"><td class="mono">{{ $td(p.key) }}</td><td>{{ $td(p.kind_label) }}</td><td>{{ (p.unit || '—').toUpperCase() }}</td>
          <td>{{ $td(p.holder) }}</td>
          <td><span class="pill" :class="{ active: 'warn', blocked: 'bad', closed: 'good', requested: 'info' }[p.status] || 'mute'">{{ $td(p.status_label) }}</span>
            <div v-if="p.block_reason" class="small bad">{{ $td(p.block_reason) }}</div></td>
          <td>{{ $td(p.reason) }}<div v-if="p.minutes" class="small muted">{{ $t('{a} 分钟{b}', { a: $td(p.minutes), b: p.delay_minutes ? $t('，') + p.delay_minutes + $t(' 分钟后开始') : '' }) }}</div></td>
          <td><template v-if="pm.can_manage">
            <button v-if="['requested', 'blocked'].includes(p.status)" class="linkbtn" @click="approveP(p)">{{ $t('批准') }}</button>
            <button v-if="p.status === 'active'" class="linkbtn" @click="closeP(p)">{{ p.kind === 'loto' ? $t('验收解锁') : $t('关闭') }}</button></template></td></tr></tbody></table>
    </template>

    <!-- ③ 事故与未遂 -->
    <template v-if="tab === 'incidents' && ic">
      <div class="card">
        <h3>{{ $t('报告事故 / 未遂') }}</h3>
        <div class="grid3">
          <label>{{ $t('种类') }}<select v-model="nn.kind"><option v-for="(l, k) in ic.kinds" :key="k" :value="k">{{ $td(l) }}</option></select></label>
          <label>{{ $t('设备') }}<select v-model="nn.unit"><option value="">—</option><option v-for="(n, u) in UNITS" :key="u" :value="u">{{ u.toUpperCase() }} {{ $td(n) }}</option></select></label>
          <label>{{ $t('日期') }}<input v-model="nn.day" type="date"></label>
          <label class="w2">{{ $t('经过') }}<input v-model="nn.description" :placeholder="$t('发生了什么')"></label>
          <label class="w2">{{ $t('根因（5 个为什么）') }}<input v-model="nn.root_cause"></label>
        </div>
        <button class="btn primary sm" @click="newIncident">{{ $t('提交') }}</button> <span class="small ok">{{ msg }}</span>
      </div>
      <div class="card"><h3>{{ $t('近期数量') }}</h3>
        <p class="small"><span v-for="(n, k) in ic.counts" :key="k">{{ $t('{a} {b} 起', { a: k, b: n }) }} · </span><span v-if="!Object.keys(ic.counts).length" class="muted">{{ $t('没有记录。') }}</span></p>
        <p v-if="!ic.full" class="small muted">{{ $t('事故调查记录是 3 级敏感：只有厂长和老师能看详情。') }}</p>
        <table v-else-if="ic.incidents.length" class="tbl small"><thead><tr><th>{{ $t('编号') }}</th><th>{{ $t('日期') }}</th><th>{{ $t('种类') }}</th><th>{{ $t('设备') }}</th><th>{{ $t('经过') }}</th><th>{{ $t('根因') }}</th><th>{{ $t('报告人') }}</th></tr></thead>
          <tbody><tr v-for="x in ic.incidents" :key="x.id"><td class="mono">{{ $td(x.key) }}</td><td>{{ $td(x.day) }}</td><td>{{ $td(x.kind_label) }}</td><td>{{ (x.unit || '—').toUpperCase() }}</td>
            <td>{{ $td(x.description) }}</td><td>{{ x.root_cause || '—' }}</td><td>{{ $td(x.created_by) }}</td></tr></tbody></table>
      </div>
    </template>

    <!-- ④ 培训与资质 -->
    <template v-if="tab === 'people' && pp">
      <div class="card">
        <table class="tbl small"><thead><tr><th>{{ $t('员工') }}</th><th>{{ $t('岗位') }}</th><th v-for="(l, k) in pp.kinds" :key="k">{{ l }}</th></tr></thead>
          <tbody><tr v-for="p in pp.people" :key="p.id"><td>{{ $td(p.name) }} <span class="muted">{{ $td(p.id) }}</span></td><td>{{ $td(p.post) }} · {{ $td(p.team) }}</td>
            <td v-for="(l, k) in pp.kinds" :key="k" :class="cls(p, k)" :title="tip(p, k)">{{ cell(p, k) }}</td></tr></tbody></table>
        <p class="small muted">{{ $t('红：已过期；黄：30 天内到期；空：没有这项培训。') }}</p>
      </div>
      <div v-if="pp.can_manage" class="card">
        <h3>{{ $t('登记一场培训') }}</h3>
        <div class="grid3">
          <label>{{ $t('培训') }}<select v-model="nt.kind"><option v-for="(l, k) in pp.kinds" :key="k" :value="k">{{ $td(l) }}</option></select></label>
          <label>{{ $t('日期') }}<input v-model="nt.day" type="date"></label>
        </div>
        <span class="cks"><label v-for="p in pp.people" :key="p.id"><input v-model="nt.people" type="checkbox" :value="p.id"> {{ $td(p.name) }}</label></span>
        <div><button class="btn primary sm" @click="newTraining">{{ $t('登记') }}</button> <span class="small ok">{{ msg }}</span></div>
      </div>
    </template>

    <!-- ⑤ 化学品与废弃物 -->
    <template v-if="tab === 'chem' && ch">
      <div class="card"><h3>{{ $t('化学品') }}</h3>
        <table class="tbl small"><thead><tr><th>{{ $t('编号') }}</th><th>{{ $t('名称') }}</th><th class="num">{{ $t('存量 kg') }}</th><th class="num">{{ $t('安全库存') }}</th><th class="num">{{ $t('现场限额') }}</th><th>{{ $t('安全数据表') }}</th></tr></thead>
          <tbody><tr v-for="c in ch.chemicals" :key="c.code"><td class="mono">{{ $td(c.code) }}</td><td>{{ $td(c.name) }}</td>
            <td class="num" :class="{ bad: c.stock_kg < c.min_kg || c.stock_kg > c.max_kg }">{{ c.stock_kg.toFixed(1) }}</td><td class="num">{{ $td(c.min_kg) }}</td><td class="num">{{ $td(c.max_kg) }}</td>
            <td class="small">{{ $td(c.sds) }}</td></tr></tbody></table></div>
      <div class="card"><h3>{{ $t('废弃物台账') }}</h3>
        <p class="small muted">{{ $t('危险废物产生后 {a} 天内要交有资质的单位处置。', { a: $td(ch.limit_days) }) }}</p>
        <table class="tbl small"><thead><tr><th>{{ $t('种类') }}</th><th class="num">kg</th><th>{{ $t('产生') }}</th><th class="num">{{ $t('天数') }}</th><th>{{ $t('处置') }}</th></tr></thead>
          <tbody><tr v-for="w in ch.wastes" :key="w.id"><td>{{ $td(w.label) }}<span v-if="w.hazardous" class="pill warn">{{ $t('危废') }}</span></td><td class="num">{{ w.qty_kg.toFixed(1) }}</td>
            <td>{{ $td(w.produced_day) }}</td><td class="num" :class="{ bad: w.over_limit }">{{ $td(w.age_days) }}</td>
            <td><template v-if="w.disposed_day">{{ $td(w.disposed_day) }} · {{ $td(w.disposed_by) }}</template>
              <template v-else-if="ch.can_manage"><input v-model="disp[w.id]" :placeholder="$t('处置单位')" class="d"><button class="linkbtn" @click="dispose(w)">{{ $t('登记处置') }}</button></template></td></tr></tbody></table></div>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post, session } from '../lib/api';
import { fmtTs } from '../lib/ont';

const TABS = { issues: $t('隐患'), permits: $t('作业许可'), incidents: $t('事故与未遂'), people: $t('培训与资质'), chem: $t('化学品与废弃物') };
const UNITS = ref({});           // 第 61 轮：设备清单随工厂变（/api/ehs/units）
const route = useRoute();
const router = useRouter();
const tab = ref(TABS[route.query.tab] ? route.query.tab : 'issues');
const err = ref('');
const msg = ref('');
const busy = ref(false);
const kp = ref(null);
const is = ref(null);
const pm = ref(null);
const ic = ref(null);
const pp = ref(null);
const ch = ref(null);
const hz = ref(null);
const loadHz = () => { if (!hz.value) wrap(async () => { hz.value = await get('/ehs/hazards'); }); };
const isOpen = ref(true);
const own = reactive({});
const disp = reactive({});
const ni = reactive({ unit: '', kind: 'guard', level: 'major', subject: '', photo_ids: [] });
const np = reactive({ kind: 'loto', unit: '', holder_id: '', minutes: 120, reason: '' });
const nn = reactive({ kind: 'near_miss', unit: '', day: new Date().toISOString().slice(0, 10), description: '', root_cause: '' });
const nt = reactive({ kind: 'confined', day: new Date().toISOString().slice(0, 10), people: [] });
const pmMsg = ref('');
const pmMsgOk = ref(true);

function go(k) { tab.value = k; router.replace({ query: { ...route.query, tab: k } }); load(); }
async function wrap(fn) { err.value = ''; try { await fn(); } catch (e) { err.value = e.message; } }
const loadKp = () => wrap(async () => { kp.value = await get('/ehs/kpis'); });
const loadIs = () => wrap(async () => { is.value = await get('/ehs/issues' + (isOpen.value ? '' : '?status=all')); });
const loadPm = () => wrap(async () => {
  pm.value = await get('/ehs/permits');
  if (!np.holder_id) np.holder_id = (pm.value.people.find((p) => p.id === 'P06') || pm.value.people.find((p) => p.post === '维修工') || pm.value.people[0] || {}).id || '';   // i18n-ok 数据比较
});
const loadIc = () => wrap(async () => { ic.value = await get('/ehs/incidents'); });
const loadPp = () => wrap(async () => { pp.value = await get('/ehs/people'); });
const loadCh = () => wrap(async () => { ch.value = await get('/ehs/chemicals'); });
function load() { loadKp(); ({ issues: loadIs, permits: loadPm, incidents: loadIc, people: loadPp, chem: loadCh })[tab.value](); }
function who(id) { return (is.value?.people || []).find((p) => p.id === id)?.name || id; }

async function photo(e) {
  const f = e.target.files?.[0];
  if (!f) return;
  busy.value = true;
  try {
    const fd = new FormData(); fd.append('file', f);
    const r = await fetch('/api/files', { method: 'POST', body: fd, headers: session.token ? { 'x-wq-token': session.token } : {} });
    if (!r.ok) throw new Error($t('照片上传失败'));
    ni.photo_ids.push((await r.json()).sha256);
  } catch (x) { err.value = x.message; } finally { busy.value = false; }
}
async function newIssue() {
  await wrap(async () => {
    const r = await post('/ehs/issues', { ...ni, unit: ni.unit || null });
    msg.value = $t('已登记 ') + r.key + $t('；厂情中枢下一轮检测（20 秒内）会看到');
    ni.subject = ''; ni.photo_ids = []; loadIs(); loadKp();
  });
}
async function assign(x) { await wrap(async () => { if (!own[x.id]) throw new Error($t('选整改人')); await post(`/ehs/issues/${x.id}/assign`, { owner: own[x.id] }); loadIs(); }); }
async function fixIt(x) { await wrap(async () => { await post(`/ehs/issues/${x.id}/fix`, {}); loadIs(); }); }
async function verify(x) { await wrap(async () => { await post(`/ehs/issues/${x.id}/verify`); loadIs(); loadKp(); }); }
async function newPermit() {
  pmMsg.value = '';
  await wrap(async () => {
    const r = await post('/ehs/permits', { ...np, unit: np.unit || null });
    pmMsgOk.value = r.status !== 'blocked';
    pmMsg.value = r.status === 'blocked' ? $t('{a} 被拦下：{b}', { a: r.key, b: r.why }) : $t('{a} 已提交，等安全员 / 厂长批准', { a: r.key });
    loadPm();
  });
}
async function approveP(p) { await wrap(async () => { await post(`/ehs/permits/${p.id}/approve`); loadPm(); loadKp(); }); }
async function closeP(p) { await wrap(async () => { await post(`/ehs/permits/${p.id}/close`); loadPm(); loadKp(); }); }
async function newIncident() { await wrap(async () => { const r = await post('/ehs/incidents', { ...nn, unit: nn.unit || null }); msg.value = $t('已记录 ') + r.key; nn.description = ''; nn.root_cause = ''; loadIc(); }); }
async function newTraining() { await wrap(async () => { const r = await post('/ehs/trainings', { ...nt }); msg.value = r.text; nt.people = []; loadPp(); loadKp(); }); }
async function dispose(w) { await wrap(async () => { await post(`/ehs/waste/${w.id}/dispose`, { by: disp[w.id] || '' }); loadCh(); loadKp(); }); }
const tr = (p, k) => p.trainings.find((t) => t.kind === k);
const cell = (p, k) => { const t = tr(p, k); return t ? t.valid_until.slice(2) : ''; };
const tip = (p, k) => { const t = tr(p, k); return t ? $t('{a}：{b} 培训，有效期到 {c}', { a: t.label, b: t.done_day, c: t.valid_until }) : $t('没有这项培训'); };
const cls = (p, k) => { const t = tr(p, k); return !t ? '' : t.days_left < 0 ? 'exp' : t.days_left <= 30 ? 'soon' : 'okc'; };
watch(() => route.query.tab, (t) => { if (t && TABS[t] && t !== tab.value) { tab.value = t; load(); } });
onMounted(async () => { try { UNITS.value = (await get('/ehs/units')).units; } catch (e) { /* 旧接口 */ } load(); });
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.tabs { margin-left: auto; display: flex; gap: 4px; flex-wrap: wrap; }
.tabs button { height: 30px; padding: 0 12px; border: 1px solid var(--line); background: var(--surface); border-radius: 6px; cursor: pointer; }
.tabs button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.cnt { background: var(--bad); color: #fff; border-radius: 8px; font-size: 10px; padding: 0 5px; margin-left: 4px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; margin-bottom: 12px; }
.k { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; }
.k b { font-size: 22px; }
input, select { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; min-width: 0; }
input[type=file] { height: auto; padding: 4px; }
.grid3 { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px 12px; margin: 8px 0; }
.grid3 label { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--muted); }
.grid3 .w2 { grid-column: span 2; }
@media (max-width: 600px) { .grid3 .w2 { grid-column: span 1; } }
.item { margin-bottom: 8px; border-left: 4px solid var(--warn); }
.item.major { border-left-color: var(--bad); }
.ih { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.act { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 6px; }
.photos { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
.photos img { width: 90px; height: 68px; object-fit: cover; border-radius: 6px; border: 1px solid var(--line); }
.filters { margin: 6px 0; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 13px; margin: 6px 0; }
.tbl.card { display: block; overflow-x: auto; }
td.exp { background: #FDE8E8; color: #9B1C1C; font-weight: 600; }
td.soon { background: #FFF4D6; color: #8A5A00; }
td.okc { color: var(--muted); }
.d { width: 130px; }
.bad { color: var(--bad); }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; padding: 0 4px; }
.btn.sm { height: 28px; padding: 0 10px; }
.ok { color: var(--good); }
h3 { font-size: 14px; margin: 0 0 6px; }
.num { text-align: right; }
</style>
