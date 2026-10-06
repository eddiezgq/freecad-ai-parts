<template>
  <div class="page">
    <div class="page-title"><h1>设计优化</h1>
      <span class="muted">人只定目标和要求，平台自己改尺寸、跑几十次有限元 / 温度场，找出满足要求的最好方案（Optuna 贝叶斯优化）；结果送设计台或回仿真与分析</span>
      <span class="labs small">实验 11：<a href="/api/cae/lab11/guide.docx">指导书</a> · <a href="/api/cae/lab11/report-template.docx">报告模板</a></span></div>

    <div class="seg modeseg">
      <button type="button" :class="{ on: mode === 'param' }" @click="setMode('param')">参数优化（改尺寸）</button>
      <button type="button" :class="{ on: mode === 'topo' }" @click="setMode('topo')">拓扑优化（平面件：材料该放在哪）</button>
    </div>

    <TopoPanel v-if="mode === 'topo'" />
    <template v-else>
    <div class="row">
      <section class="card side">
        <div class="step"><b>1</b> 优化什么</div>
        <select v-model="pid" class="full" aria-label="优化问题">
          <option v-for="p in problems" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
        <div v-if="prob" class="small muted">现行：{{ Object.entries(prob.current).filter(([k]) => prob.vars.some((v) => v.name === k)).map(([k, v]) => varLabel(k) + ' ' + v).join('，') }}</div>

        <template v-if="prob">
          <div class="ai-box">
            <textarea v-model="aiText" rows="2" maxlength="500" :placeholder="AI_HINT[pid]"></textarea>
            <div class="line"><button class="btn" :disabled="aiBusy || !aiText.trim()" @click="aiFill">{{ aiBusy ? 'AI 正在理解…' : 'AI 填表' }}</button>
              <span class="small muted">AI 只填下面的表，你确认后再开始</span></div>
            <div v-if="aiRes" class="small">
              <div v-for="n in aiRes.notes" :key="n">✓ {{ n }}</div>
              <div v-for="n in aiRes.unmatched" :key="n" class="warnline">？没看懂：“{{ n }}”</div>
            </div>
          </div>

          <div class="step"><b>2</b> 可以改的尺寸</div>
          <div v-for="v in prob.vars" :key="v.name" class="vrow small">
            <label class="chk"><input v-model="form.vars[v.name].on" type="checkbox"> {{ v.label }}</label>
            <span v-if="form.vars[v.name].on">从 <input v-model.number="form.vars[v.name].low" type="number" :step="v.step"> 到 <input v-model.number="form.vars[v.name].high" type="number" :step="v.step">，每档 {{ v.step }}</span>
          </div>

          <div class="step"><b>3</b> 目标</div>
          <div class="seg">
            <button v-for="o in objChoices" :key="o.k" type="button" :class="{ on: form.obj === o.k }" @click="form.obj = o.k">{{ o.label }}</button>
          </div>

          <div class="step"><b>4</b> 要求（约束）</div>
          <template v-if="pid === 'shaft'">
            <label class="small">安全系数 ≥ <input v-model.number="form.sf_min" type="number" step="0.1"> （扭矩 350 N·m，45 钢调质）</label>
            <label class="small">疲劳寿命（0 → 350 N·m 脉动）
              <select v-model="form.life"><option value="infinite">无限寿命</option><option value="hours">至少若干小时</option><option value="">不要求</option></select>
              <input v-if="form.life === 'hours'" v-model.number="form.life_h" type="number"> {{ form.life === 'hours' ? '小时' : '' }}</label>
            <div class="small muted">另外每组尺寸都要通过设计台的校核（键槽能放下、直径范围等），通不过的直接算不可行。</div>
          </template>
          <label v-else class="small">最高温度 ≤ <input v-model.number="form.t_max" type="number"> ℃</label>

          <div class="step"><b>5</b> 算多少次</div>
          <label class="small">分析次数 <input v-model.number="form.n" type="number" min="4" :max="maxTrials"> 次（最多 {{ maxTrials }} 次、15 分钟；每次 3–10 秒）</label>
          <div class="small muted">第 1 次固定是现行设计，方便对比。优化作为一个任务排队，跑的时候别人的有限元会排在后面。</div>
          <label class="small">名称 <input v-model.trim="title" class="full" maxlength="80"></label>
          <button class="btn primary big-w" :disabled="submitting || !nVars" @click="submit">{{ submitting ? '正在提交…' : '开始优化' }}</button>
          <div v-if="!nVars" class="small err">至少勾一个可以改的尺寸。</div>
        </template>
        <div v-if="err" class="err small">{{ err }}</div>
      </section>

      <section class="card grow">
        <div class="card-head"><h2>{{ job ? (job.title || '优化') : '结果' }}</h2>
          <span v-if="job" class="pill" :class="TONE[job.status]">{{ STATUS[job.status] }}</span></div>
        <div v-if="!job" class="empty big-empty">左边选问题、勾要改的尺寸、定目标和要求，点“开始优化”。</div>
        <template v-else>
          <div v-if="job.status === 'queued'" class="jobbar">排队中{{ job.position ? '：前面还有 ' + (job.position - 1) + ' 个任务' : '' }}…</div>
          <div v-if="job.status === 'failed'" class="jobbar failed">没算成：{{ job.error }}</div>
          <div v-if="job.status === 'running' && !rows.length" class="jobbar">正在算第 1 次（现行设计）…每次 3–10 秒，结果会一行行出来。</div>
          <div v-if="rows.length" class="progress small">
            <div class="bar"><i :style="{ width: Math.min(100, rows.length / nTotal * 100) + '%' }"></i></div>
            已算 {{ rows.length }} / {{ nTotal }} 次，满足要求 {{ rows.filter((r) => r.ok).length }} 次{{ job.status === 'running' ? '，正在算…' : '' }}
          </div>

          <div v-if="best" class="cards">
            <div class="kpi good"><div class="muted small">最好的一组</div>
              <div class="big">{{ fmtX(best.x) }}</div>
              <div class="small">{{ metric(best) }}</div>
              <button class="btn primary small-btn" @click="use(best)">{{ spec.problem === 'shaft' ? '送到设计台 →' : '到仿真与分析看温度场 →' }}</button></div>
            <div v-if="base" class="kpi"><div class="muted small">现行设计</div>
              <div class="big">{{ fmtX(base.x) }}</div>
              <div class="small">{{ metric(base) }}</div>
              <div class="small" :class="base.ok ? 'okline' : 'err'">{{ base.ok ? '满足要求' : '不满足：' + base.violation.join('；') }}</div></div>
            <div v-if="best && base && best.mass_kg && base.mass_kg" class="kpi"><div class="muted small">比现行</div>
              <div class="big">{{ ((best.mass_kg / base.mass_kg - 1) * 100).toFixed(1) }}%</div>
              <div class="small muted">质量变化{{ best.t_max != null && base.t_max != null ? '；最高温度 ' + (best.t_max - base.t_max).toFixed(1) + ' ℃' : '' }}</div></div>
          </div>

          <svg v-if="rows.length > 1" class="chart" viewBox="0 0 640 220" aria-label="优化过程">
            <template v-if="!multi">
              <text x="8" y="14" font-size="11">每次分析的{{ objLabel }}（绿 = 满足要求，灰 = 不满足），红线 = 到这次为止最好的</text>
              <g v-for="(p, i) in convPts" :key="i"><circle :cx="p.x" :cy="p.y" r="3.5" :fill="p.ok ? '#2E7D32' : '#B0B6AE'" /></g>
              <polyline :points="bestLine" fill="none" stroke="#C62828" stroke-width="1.5" />
            </template>
            <template v-else>
              <text x="8" y="14" font-size="11">横轴质量（kg）、纵轴最高温度（℃）：灰 = 不满足，绿 = 满足，红圈 = 帕累托前沿（再轻就会更热）</text>
              <g v-for="(p, i) in scatter" :key="i">
                <circle :cx="p.x" :cy="p.y" :r="p.front ? 6 : 3.5" :fill="p.ok ? '#2E7D32' : '#B0B6AE'" :stroke="p.front ? '#C62828' : 'none'" stroke-width="2" />
              </g>
              <line v-if="limitY != null" x1="40" :x2="630" :y1="limitY" :y2="limitY" stroke="#C62828" stroke-dasharray="4 3" />
            </template>
            <text x="40" y="214" font-size="10" fill="#666">{{ axisNote }}</text>
          </svg>

          <table v-if="rows.length" class="t small">
            <thead><tr><th>#</th><th v-for="v in spec.vars || []" :key="v.name || v">{{ varLabel(v.name || v) }}</th><th class="num">质量 kg</th>
              <th v-if="spec.problem === 'shaft'" class="num">安全系数</th><th v-if="spec.problem === 'shaft'">寿命</th>
              <th v-else class="num">最高 ℃</th><th>要求</th><th class="num">s</th><th></th></tr></thead>
            <tbody><tr v-for="r in sortedRows" :key="r.trial" :class="{ base: r.base, top: best && r.trial === best.trial }">
              <td>{{ r.trial + 1 }}{{ r.base ? ' 现行' : '' }}</td>
              <td v-for="v in spec.vars || []" :key="v.name || v" class="mono">{{ r.x[v.name || v] }}</td>
              <td class="num">{{ r.mass_kg?.toFixed(3) ?? '—' }}</td>
              <td v-if="spec.problem === 'shaft'" class="num">{{ r.sf?.toFixed(2) ?? '—' }}</td>
              <td v-if="spec.problem === 'shaft'">{{ r.life_inf ? '无限' : r.life_h != null ? r.life_h.toExponential(1) + ' h' : '—' }}</td>
              <td v-else class="num">{{ r.t_max?.toFixed(1) ?? '—' }}</td>
              <td :class="r.ok ? 'okline' : 'err'">{{ r.ok ? '✓' : '✗ ' + (r.violation || []).join('；') }}</td>
              <td class="num">{{ r.repeat ? '重复' : r.seconds }}</td>
              <td><a v-if="r.ok" href="#" @click.prevent="use(r)">用这组</a></td>
            </tr></tbody>
          </table>
          <div v-if="job.status === 'done'" class="ai-exp">
            <div class="line"><b>AI 解释</b><button class="btn" :disabled="expBusy" @click="explain">{{ expBusy ? 'AI 正在分析…' : (exp ? '重新分析' : '请 AI 解释结果') }}</button></div>
            <p v-for="(l, i) in (exp?.text || '').split('\n').filter(Boolean)" :key="i" class="exp-p">{{ l }}</p>
          </div>
        </template>
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>{{ teacher ? '本厂的优化记录' : '我的优化记录' }}</h2></div>
      <div v-if="!jobs.length" class="empty">还没有优化记录。</div>
      <table v-else class="t">
        <thead><tr><th>名称</th><th v-if="teacher">提交人</th><th>时间</th><th>状态</th><th class="num">次数</th><th>最好的一组</th><th></th></tr></thead>
        <tbody><tr v-for="j in jobs" :key="j.id">
          <td>{{ j.title }}</td><td v-if="teacher">{{ j.owner_name }}</td>
          <td class="small">{{ new Date(j.created * 1000).toLocaleString('zh-CN', { hour12: false }) }}</td>
          <td><span class="pill" :class="TONE[j.status]">{{ STATUS[j.status] }}</span></td>
          <td class="num">{{ j.stats?.trials ?? '' }}</td>
          <td class="small mono">{{ j.stats?.best ? fmtX(j.stats.best.x) : '' }}</td>
          <td><a href="#" @click.prevent="openJob(j.id)">看 →</a></td>
        </tr></tbody>
      </table>
    </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post, session } from '../lib/api';
import TopoPanel from '../components/TopoPanel.vue';

const router = useRouter();
const route = useRoute();
const mode = ref(route.query.mode === 'topo' ? 'topo' : 'param');
function setMode(m) { mode.value = m; router.replace({ query: { ...route.query, mode: m === 'topo' ? 'topo' : undefined } }); }
const STATUS = { queued: '排队', running: '计算中', done: '完成', failed: '失败' };
const TONE = { queued: 'mute', running: 'info', done: 'good', failed: 'bad' };
const AI_HINT = {
  shaft: '例如：输出轴越轻越好，安全系数不小于 1.3，寿命无限，齿轮位只能在 38 到 44 之间',
  housing: '例如：箱体最高温度不超过 80 度，散热筋越少越好，算 30 次',
  heatsink: '例如：散热片最轻，CPU 不超过 85 度，片厚 1 到 2 毫米',
};
const teacher = computed(() => !!session.user?.teacher);
const problems = ref([]), maxTrials = ref(60);
const pid = ref('shaft');
const form = ref({ vars: {}, obj: 'mass', sf_min: 1.3, life: 'infinite', life_h: 20000, t_max: 80, n: 20 });
const title = ref('');
const submitting = ref(false), err = ref('');
const job = ref(null), jobs = ref([]), rows = ref([]), final = ref(null);
const aiText = ref(''), aiBusy = ref(false), aiRes = ref(null);
const exp = ref(null), expBusy = ref(false);
let pollT = null;

const prob = computed(() => problems.value.find((p) => p.id === pid.value));
const varLabel = (n) => { for (const p of problems.value) { const v = p.vars.find((x) => x.name === n); if (v) return v.label; } return n; };
const nVars = computed(() => Object.values(form.value.vars).filter((v) => v.on).length);
const objChoices = computed(() => (pid.value === 'shaft' ? [{ k: 'mass', label: '最轻' }]
  : [{ k: 'mass', label: '最轻' }, { k: 't_max', label: '最凉' }, { k: 'both', label: '又轻又凉（两个目标）' }]));
watch(prob, (p) => {
  if (!p) return;
  const d = p.default;
  form.value.vars = Object.fromEntries(p.vars.map((v) => [v.name, { on: d.vars.includes(v.name), low: v.low, high: v.high }]));
  form.value.obj = d.objectives.length > 1 ? 'both' : d.objectives[0];
  if (d.constraints.sf_min != null) form.value.sf_min = d.constraints.sf_min;
  if (d.constraints.t_max != null) form.value.t_max = d.constraints.t_max;
  title.value = p.label.split('（')[0] + ' 优化';
  aiRes.value = null;
});

const spec = computed(() => job.value?.spec || {});
const multi = computed(() => (spec.value.objectives || []).length > 1);
const nTotal = computed(() => spec.value.n_trials || 30);
const objKey = computed(() => ({ mass: 'mass_kg', t_max: 't_max', sf: 'sf' }[(spec.value.objectives || ['mass'])[0]]));
const objLabel = computed(() => ({ mass_kg: '质量（kg）', t_max: '最高温度（℃）', sf: '安全系数' }[objKey.value]));
const base = computed(() => rows.value.find((r) => r.base));
const best = computed(() => {
  if (final.value?.best?.length) return final.value.best[0];
  const ok = rows.value.filter((r) => r.ok && !r.repeat);
  if (!ok.length) return null;
  return ok.reduce((a, b) => (b[objKey.value] < a[objKey.value] ? b : a));
});
const sortedRows = computed(() => [...rows.value].sort((a, b) => (b.ok - a.ok) || ((a[objKey.value] ?? 1e9) - (b[objKey.value] ?? 1e9))));
function fmtX(x) { return Object.entries(x || {}).map(([k, v]) => `${varLabel(k).split(' ')[0]} ${v}`).join('，'); }
function metric(r) {
  const s = [];
  if (r.mass_kg != null) s.push(`质量 ${r.mass_kg.toFixed(3)} kg`);
  if (r.sf != null) s.push(`安全系数 ${r.sf.toFixed(2)}`);
  if (r.life_inf) s.push('无限寿命'); else if (r.life_h != null) s.push(`寿命 ${r.life_h.toExponential(1)} h`);
  if (r.t_max != null) s.push(`最高 ${r.t_max.toFixed(1)} ℃`);
  return s.join(' · ');
}
// 收敛图：每次的目标值（满足 / 不满足）、到这次为止最好的
const convPts = computed(() => {
  const vals = rows.value.map((r) => r[objKey.value]).filter((v) => v != null);
  if (!vals.length) return [];
  const lo = Math.min(...vals), hi = Math.max(...vals) || lo + 1;
  const n = rows.value.length;
  return rows.value.map((r, i) => ({ x: 40 + i / Math.max(n - 1, 1) * 590, y: r[objKey.value] == null ? 200 : 195 - (r[objKey.value] - lo) / ((hi - lo) || 1) * 170, ok: r.ok, v: r[objKey.value] }));
});
const bestLine = computed(() => {
  let b = null; const pts = [];
  convPts.value.forEach((p) => { if (p.ok && (b == null || p.y > b)) b = p.y; if (b != null) pts.push(`${p.x.toFixed(1)},${b.toFixed(1)}`); });
  return pts.join(' ');
});
const axisNote = computed(() => {
  if (multi.value) return '';
  const v = rows.value.map((r) => r[objKey.value]).filter((x) => x != null);
  return v.length ? `纵轴 ${Math.min(...v).toFixed(3)} – ${Math.max(...v).toFixed(3)}，横轴第 1 – ${rows.value.length} 次` : '';
});
const scatterRange = computed(() => {
  const m = rows.value.filter((r) => r.mass_kg != null && r.t_max != null);
  if (!m.length) return null;
  const xs = m.map((r) => r.mass_kg), ys = m.map((r) => r.t_max).concat(spec.value.constraints?.t_max ?? []);
  return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
});
const sx = (v) => { const r = scatterRange.value; return 40 + (v - r.x0) / ((r.x1 - r.x0) || 1) * 590; };
const sy = (v) => { const r = scatterRange.value; return 200 - (v - r.y0) / ((r.y1 - r.y0) || 1) * 175; };
const scatter = computed(() => {
  if (!scatterRange.value) return [];
  const front = new Set((final.value?.pareto || []).map((r) => r.trial));
  return rows.value.filter((r) => r.mass_kg != null && r.t_max != null).map((r) => ({ x: sx(r.mass_kg), y: sy(r.t_max), ok: r.ok, front: front.has(r.trial) }));
});
const limitY = computed(() => (scatterRange.value && spec.value.constraints?.t_max != null ? sy(spec.value.constraints.t_max) : null));

function buildSpec() {
  const vars = Object.entries(form.value.vars).filter(([, v]) => v.on).map(([name, v]) => ({ name, low: +v.low, high: +v.high }));
  const objectives = form.value.obj === 'both' ? ['mass', 't_max'] : [form.value.obj];
  const constraints = pid.value === 'shaft'
    ? { sf_min: +form.value.sf_min, life: form.value.life === 'infinite' ? 'infinite' : form.value.life === 'hours' ? +form.value.life_h : null }
    : { t_max: +form.value.t_max };
  if (constraints.life === null) delete constraints.life;
  return { problem: pid.value, vars, objectives, constraints, n_trials: Math.min(+form.value.n, maxTrials.value) };
}
async function submit() {
  submitting.value = true; err.value = '';
  try {
    job.value = await post('/opt/jobs', { spec: buildSpec(), title: title.value });
    rows.value = []; final.value = null; exp.value = null;
    poll(); loadJobs();
  } catch (e) { err.value = e.message; } finally { submitting.value = false; }
}
async function refresh() {
  job.value = await get('/opt/jobs/' + job.value.id);
  const t = await get(`/opt/jobs/${job.value.id}/trials`);
  rows.value = t.final ? t.trials : t.rows;
  final.value = t.final ? t : null;
}
function poll() {
  clearTimeout(pollT);
  pollT = setTimeout(async () => {
    try { await refresh(); } catch (e) { /* 下次再问 */ }
    if (['queued', 'running'].includes(job.value?.status)) poll(); else loadJobs();
  }, 2500);
}
async function openJob(id) {
  err.value = ''; exp.value = null;
  try { job.value = await get('/opt/jobs/' + id); await refresh(); if (['queued', 'running'].includes(job.value.status)) poll(); }
  catch (e) { err.value = e.message; }
}
async function use(r) {
  try { const res = await post(`/opt/jobs/${job.value.id}/use`, { x: r.x }); router.push(res.url); } catch (e) { err.value = e.message; }
}
async function aiFill() {
  aiBusy.value = true; err.value = '';
  try {
    const r = await post('/opt/ai-setup', { text: aiText.value, problem: pid.value, form: form.value });
    form.value = { ...form.value, ...r.form, vars: { ...form.value.vars, ...(r.form?.vars || {}) } };
    aiRes.value = r;
  } catch (e) { err.value = e.message; } finally { aiBusy.value = false; }
}
async function explain() {
  expBusy.value = true;
  try { exp.value = await post(`/opt/jobs/${job.value.id}/explain`, {}); } catch (e) { err.value = e.message; } finally { expBusy.value = false; }
}
async function loadJobs() { try { jobs.value = (await get('/opt/jobs')).jobs; } catch (e) { /* */ } }

onMounted(async () => {
  try { const r = await get('/opt/problems'); problems.value = r.problems; maxTrials.value = r.max_trials; }
  catch (e) { err.value = e.status === 503 ? '计算服务暂时连不上，请稍后再试' : e.message; }
  loadJobs();
});
onUnmounted(() => clearTimeout(pollT));
</script>

<style scoped>
.side { width: 400px; flex-shrink: 0; display: flex; flex-direction: column; gap: 9px; align-self: flex-start; }
.grow { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.step { display: flex; align-items: center; gap: 8px; font-weight: 600; margin-top: 6px; }
.step b { width: 22px; height: 22px; border-radius: 50%; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; }
.full { width: 100%; height: 34px; border: 1px solid #C8CEC7; border-radius: 6px; padding: 0 8px; background: #fff; }
.modeseg { margin-bottom: 12px; }
.labs { margin-left: auto; white-space: nowrap; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; align-self: flex-start; flex-wrap: wrap; }
.seg button { border: 0; background: #fff; padding: 6px 12px; cursor: pointer; font-size: 13px; }
.seg button.on { background: var(--accent-bg); font-weight: 600; }
.vrow { display: flex; flex-direction: column; gap: 2px; border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; }
.chk { display: flex; gap: 6px; align-items: center; }
input[type=number] { width: 70px; height: 26px; border: 1px solid #C8CEC7; border-radius: 5px; padding: 0 4px; }
select { height: 26px; border: 1px solid #C8CEC7; border-radius: 5px; }
.line { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.big-w { height: 42px; font-size: 15px; margin-top: 6px; }
.small-btn { height: 28px; font-size: 12px; margin-top: 4px; }
.ai-box { display: flex; flex-direction: column; gap: 6px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
.ai-box textarea { border: 1px solid #C8CEC7; border-radius: 6px; padding: 6px 8px; resize: vertical; }
.warnline { color: var(--warn-ink); }
.okline { color: var(--good, #1B5E20); }
.big-empty { padding: 120px 0; text-align: center; }
.jobbar { border-radius: 8px; padding: 10px 14px; background: var(--accent-bg); color: var(--accent); }
.jobbar.failed { background: var(--bad-bg); color: var(--bad); }
.progress .bar { height: 8px; background: var(--surface-2); border-radius: 4px; overflow: hidden; margin-bottom: 4px; }
.progress .bar i { display: block; height: 100%; background: var(--accent); }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
.kpi { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 2px; }
.kpi.good { border-color: var(--good, #2E7D32); background: var(--good-bg); }
.big { font-size: 16px; font-weight: 600; }
.chart { width: 100%; height: 220px; background: var(--surface-2); border-radius: 8px; }
tr.base td { background: var(--surface-2); }
tr.top td { background: var(--good-bg); }
.ai-exp { border-top: 1px solid var(--line); padding-top: 8px; display: flex; flex-direction: column; gap: 4px; }
.exp-p { margin: 2px 0; line-height: 1.7; }
@media (max-width: 1100px) { .side { width: 100%; } }
</style>
