<template>
  <div class="page">
    <div class="page-title"><h1>流体分析</h1>
      <span class="muted">零件放进虚拟风洞或风道：看风怎么走、阻力多大、每个面的散热系数 h 是多少——算出的 h 一键送进温度场，代替查表（OpenFOAM 求解）</span>
      <span class="labs small">实验 14：<a href="/api/cae/lab14/guide.docx">指导书</a> · <a href="/api/cae/lab14/report-template.docx">报告模板</a></span></div>

    <div class="row">
      <section class="card side">
        <div class="step"><b>1</b> 零件</div>
        <div class="line">
          <select v-model="partSel" class="grow-in" aria-label="零件">
            <option value="">选一个零件…</option>
            <option v-for="e in examples" :key="e.key" :value="'ex:' + e.key">示例 · {{ e.label }}</option>
            <option v-for="p in parts" :key="p.item" :value="p.item">{{ p.item }} {{ p.name || '' }}</option>
          </select>
          <button class="btn" type="button" :disabled="!partSel || busy" @click="loadPart">读入</button>
        </div>
        <label class="small upload">或者上传 STEP（任何 CAD 导出）<input type="file" accept=".step,.stp,.STEP,.STP" :disabled="busy" @change="upload"></label>
        <div v-if="exSel" class="exbox small">
          <div class="muted">示例参数（改了点“读入”重新生成）</div>
          <div class="grid2"><label v-for="(n, k) in exSel.names" :key="k">{{ n }} <input v-model.number="exParams[k]" type="number" step="any"></label></div>
        </div>
        <div v-if="geo" class="small okline">{{ geo.name || geo.item || '零件' }} · {{ geo.faces.length }} 个面 · 外形 {{ dims }}</div>

        <div class="step"><b>2</b> 风</div>
        <div class="ai-box">
          <textarea v-model="aiText" rows="2" maxlength="300" placeholder="例如：轴端风扇 5 m/s 沿长边吹，空气 25 ℃，箱体表面 70 ℃，放在机座上"></textarea>
          <div class="line"><button class="btn small-btn" type="button" :disabled="!aiText.trim() || aiBusy" @click="aiFill">{{ aiBusy ? 'AI 正在理解…' : 'AI 填表' }}</button>
            <span class="small muted">AI 只填表，你确认后再算</span></div>
          <div v-if="aiRes" class="small"><div v-for="n in aiRes.notes" :key="n">✓ {{ n }}</div>
            <div v-for="n in aiRes.unmatched" :key="n" class="warnline">？没看懂：“{{ n }}”</div></div>
        </div>
        <div class="line">风速 <input v-model.number="vel" type="number" min="0.1" max="60" step="0.5" class="numin"> m/s
          来流方向 <select v-model="dir"><option v-for="(t, k) in DIRS" :key="k" :value="k">{{ t }}</option></select></div>
        <div class="line">空气 <input v-model.number="tAir" type="number" class="numin"> ℃
          <label class="chk"><input v-model="ground" type="checkbox"> 放在地面 / 机座上（底面不吹风）</label></div>

        <div class="step"><b>3</b> 换热</div>
        <label class="chk"><input v-model="heat" type="checkbox"> 算散热系数（零件表面定温）</label>
        <div v-if="heat" class="line">表面温度 <input v-model.number="tWall" type="number" class="numin"> ℃
          <span class="small muted">h 基本不随温差变（强制对流），取接近实际的温度即可</span></div>

        <div class="step"><b>4</b> 网格</div>
        <div class="seg"><button v-for="m in MESH" :key="m.k" type="button" :class="{ on: meshK === m.k }" @click="meshK = m.k">{{ m.label }}</button></div>
        <div class="small muted">约 {{ (MESH.find((m) => m.k === meshK).cells / 10000).toFixed(0) }} 万个单元，一般 2–8 分钟；计算服务排队，一次算一个。</div>

        <input v-model="title" class="full" placeholder="这次计算的名称（可不填）">
        <button class="btn primary big-w" type="button" :disabled="!geo || busy" @click="submit">{{ busy ? '提交中…' : '开始计算' }}</button>
        <div v-if="err" class="small warnline">{{ err }}</div>
      </section>

      <section class="card grow">
        <div class="card-head"><h2>{{ job ? job.title : '结果' }}</h2>
          <span v-if="job" class="pill" :class="TONE[job.status]">{{ STATUS[job.status] }}{{ job.status === 'queued' && job.position ? '（前面 ' + (job.position - 1) + ' 个）' : '' }}</span>
          <span v-if="progress && job?.status === 'running'" class="small muted">正在算：{{ progress }}</span></div>
        <div v-if="!job" class="big-empty muted">左边读入零件、填好风和换热，点“开始计算”。<br>也可以先做一次“标准题核对”（页面下方），看看这套方法和教材公式差多少。</div>
        <div v-else-if="job.status === 'failed'" class="jobbar failed">失败：{{ job.error }}</div>
        <div v-else-if="job.status !== 'done'" class="jobbar">计算中…（网格 → 流场 → 温度场，一般几分钟）</div>
        <template v-else-if="res && job.kind === 'cfd'">
          <CfdViewer ref="viewer" :surface="res.surface" :aux="res.aux" />
          <div class="cards">
            <div class="kpi"><span class="small muted">阻力</span><span class="big">{{ st.drag_n.toFixed(3) }} N</span>
              <span class="small">压差 {{ st.drag_pressure_n.toFixed(3) }} + 摩擦 {{ st.drag_friction_n.toFixed(3) }}；C_d ≈ {{ st.Cd?.toFixed(2) }}</span></div>
            <div v-if="st.heat_w != null" class="kpi"><span class="small muted">平均散热系数</span><span class="big">{{ st.h_mean.toFixed(1) }} W/(m²·K)</span>
              <span class="small">散热 {{ st.heat_w.toFixed(1) }} W（表面 {{ st.wall_t_c }} ℃、空气 {{ st.air_t_c }} ℃）</span></div>
            <div class="kpi"><span class="small muted">流动</span><span class="big">Re ≈ {{ fmtRe(st.Re) }}</span>
              <span class="small">{{ st.turbulence === 'laminar' ? '层流' : '湍流（k-ω SST）' }} · 特征尺寸 {{ st.L_char_mm }} mm</span></div>
            <div class="kpi" :class="st.converged ? '' : 'warn'"><span class="small muted">网格与收敛</span><span class="big">{{ (st.cells / 10000).toFixed(1) }} 万单元</span>
              <span class="small">{{ st.iterations }} 步{{ st.converged ? '收敛' : '（到步数上限，结果看趋势）' }} · {{ st.seconds }} 秒</span></div>
          </div>
          <div class="line">
            <button v-if="st.heat_w != null" class="btn primary" type="button" @click="toThermal">把散热系数送到温度场 →</button>
            <button class="btn" type="button" :disabled="expBusy" @click="explain">{{ expBusy ? 'AI 正在看…' : '请 AI 解释结果' }}</button>
            <button class="btn" type="button" :disabled="repBusy" @click="report">{{ repBusy ? '正在生成…' : '下载 Word 报告' }}</button>
          </div>
          <div v-if="exp" class="exp"><p v-for="(t, i) in exp.text.split('\n')" :key="i">{{ t }}</p>
            <div class="small muted">{{ exp.engine === 'rules' ? '（规则生成）' : '（由 AI 模型生成）' }}</div></div>
          <h3>每个面</h3>
          <table class="t">
            <thead><tr><th>面</th><th class="num">面积 mm²</th><th class="num">平均压力 Pa</th><th v-if="st.heat_w != null" class="num">h W/(m²·K)</th><th v-if="st.heat_w != null" class="num">散热 W</th></tr></thead>
            <tbody><tr v-for="f in facesSorted" :key="f.id"><td>面 {{ f.id }}</td><td class="num">{{ f.area_mm2.toFixed(0) }}</td><td class="num">{{ f.p_pa.toFixed(2) }}</td>
              <td v-if="st.heat_w != null" class="num">{{ f.h_w_m2k?.toFixed(1) }}</td><td v-if="st.heat_w != null" class="num">{{ f.heat_w?.toFixed(2) }}</td></tr></tbody>
          </table>
          <div class="small muted">压力是相对来流的表压（迎风面为正）；h = 该面散热量 ÷（面积 × 温差）。按面积排序，最多列 30 个面。</div>
        </template>
        <template v-else-if="res && job.kind === 'cfd_bench'">
          <BenchTable :rows="res.aux.bench" />
        </template>
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>标准题核对</h2><span class="small muted">四道题和教材公式比：平行平板层流压降、平板层流换热、湍流通道摩擦与换热、绕圆柱阻力（约 3–5 分钟）</span>
        <button class="btn small-btn" type="button" @click="bench">在服务器上跑一遍</button></div>
      <div class="small muted">方法：OpenFOAM simpleFoam 算流场；温度场在流场上自写有限体积求解；后处理全部按面元积分。</div>
    </section>

    <section class="card">
      <div class="card-head"><h2>{{ teacher ? '本厂的流体分析记录' : '我的流体分析记录' }}</h2></div>
      <div v-if="!jobs.length" class="empty">还没有记录。</div>
      <table v-else class="t">
        <thead><tr><th>名称</th><th v-if="teacher">提交人</th><th>时间</th><th>状态</th><th class="num">阻力 N</th><th class="num">平均 h</th><th></th></tr></thead>
        <tbody><tr v-for="j in jobs" :key="j.id">
          <td>{{ j.title }}</td><td v-if="teacher">{{ j.owner_name }}</td>
          <td class="small">{{ new Date(j.created * 1000).toLocaleString('zh-CN', { hour12: false }) }}</td>
          <td><span class="pill" :class="TONE[j.status]">{{ STATUS[j.status] }}</span></td>
          <td class="num">{{ j.stats?.drag_n?.toFixed?.(3) ?? '' }}</td><td class="num">{{ j.stats?.h_mean?.toFixed?.(1) ?? '' }}</td>
          <td><a href="#" @click.prevent="openJob(j.id)">看 →</a></td>
        </tr></tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { get, post, session } from '../lib/api';
import CfdViewer from '../components/CfdViewer.vue';

const BenchTable = defineComponent({
  props: { rows: Array },
  setup(p) {
    return () => h('table', { class: 't' }, [
      h('thead', h('tr', ['题', '计算', '教材 / 文献', '差', '公式'].map((x) => h('th', x)))),
      h('tbody', p.rows.map((r) => h('tr', { class: Math.abs(r.error) < 0.05 ? 'good' : 'warn' }, [
        h('td', r.name), h('td', { class: 'num' }, fmt4(r.value) + (r.unit ? ' ' + r.unit : '')),
        h('td', { class: 'num' }, r.range ? r.range.join('–') : fmt4(r.theory)), h('td', { class: 'num' }, (r.error * 100).toFixed(1) + '%'),
        h('td', { class: 'small' }, r.formula)]))),
    ]);
  },
});
function fmt4(v) { return Math.abs(v) < 0.1 ? v.toPrecision(3) : v.toFixed(Math.abs(v) >= 100 ? 1 : 3); }

const router = useRouter();
const STATUS = { queued: '排队', running: '计算中', done: '完成', failed: '失败' };
const TONE = { queued: 'mute', running: 'info', done: 'good', failed: 'bad' };
const DIRS = { '+x': '沿 +X（从左往右）', '-x': '沿 −X', '+y': '沿 +Y（从前往后）', '-y': '沿 −Y', '+z': '沿 +Z（从下往上）', '-z': '沿 −Z（从上往下）' };
const MESH = [{ k: 'c', label: '粗（快）', cells: 60000 }, { k: 'm', label: '中', cells: 120000 }, { k: 'f', label: '细（慢）', cells: 250000 }];
const EX_DEFAULT = { housing: { dir: '+x', vel: 5, ground: true, wall: 70 }, heatsink: { dir: '+y', vel: 3, ground: true, wall: 70 },
  agv_box: { dir: '+x', vel: 1.5, ground: true, wall: 50, level: 3, mesh: 'm' } };
const teacher = computed(() => !!session.user?.teacher);
const parts = ref([]), examples = ref([]), partSel = ref(''), exParams = ref({}), geo = ref(null);
const vel = ref(5), dir = ref('+x'), tAir = ref(25), ground = ref(false), heat = ref(true), tWall = ref(70), meshK = ref('m'), title = ref('');
const busy = ref(false), err = ref(''), job = ref(null), res = ref(null), jobs = ref([]), progress = ref('');
const aiText = ref(''), aiBusy = ref(false), aiRes = ref(null), exp = ref(null), expBusy = ref(false);
const viewer = ref(null), repBusy = ref(false);
let pollT = null, exKey = null;

const exSel = computed(() => (partSel.value.startsWith('ex:') ? examples.value.find((e) => 'ex:' + e.key === partSel.value) : null));
watch(exSel, (e) => { if (e) exParams.value = { ...e.params }; });
const dims = computed(() => { const b = geo.value?.solid?.bbox_mm; return b ? `${(b[3] - b[0]).toFixed(0)} × ${(b[4] - b[1]).toFixed(0)} × ${(b[5] - b[2]).toFixed(0)} mm` : ''; });
const st = computed(() => job.value?.stats || {});
const facesSorted = computed(() => [...(res.value?.aux?.faces || [])].sort((a, b) => b.area_mm2 - a.area_mm2).slice(0, 30));
const fmtRe = (x) => (x >= 1e4 ? (x / 1e4).toFixed(1) + ' 万' : x.toFixed(0));

async function loadPart() {
  busy.value = true; err.value = '';
  try {
    if (exSel.value) {
      geo.value = await post('/cae/geometry/example/' + exSel.value.key, { params: exParams.value });
      exKey = exSel.value.key;
      const d = EX_DEFAULT[exKey];
      if (d) { dir.value = d.dir; vel.value = d.vel; ground.value = d.ground; tWall.value = d.wall; if (d.mesh) meshK.value = d.mesh; }
    } else {
      geo.value = await post('/cae/geometry/item/' + encodeURIComponent(partSel.value)); exKey = null;
    }
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
async function upload(e) {
  const f = e.target.files[0]; if (!f) return;
  busy.value = true; err.value = '';
  try {
    const fd = new FormData(); fd.append('step', f);
    const r = await fetch('/api/cae/geometry/upload', { method: 'POST', headers: { 'x-wq-token': session.token }, body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || '读不了这个文件');
    geo.value = d; exKey = null;
  } catch (x) { err.value = x.message; } finally { busy.value = false; e.target.value = ''; }
}
async function submit() {
  busy.value = true; err.value = ''; res.value = null; exp.value = null;
  const setup = { flow: { velocity_ms: vel.value, direction: dir.value, air_t_c: tAir.value }, heat: heat.value ? { wall_t_c: tWall.value } : null,
    domain: { ground: ground.value }, mesh: { cells_target: MESH.find((m) => m.k === meshK.value).cells, level: (exKey && EX_DEFAULT[exKey]?.level) || 2 } };
  if (exKey && geo.value?.example) setup.example = { key: exKey, params: geo.value.example.params };
  try {
    job.value = await post('/cfd/jobs', { step_sha: geo.value.sha, setup, title: title.value || `${geo.value.name || '零件'} · ${vel.value} m/s ${dir.value}`, item: geo.value.item });
    poll(); loadJobs();
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
async function poll() {
  clearTimeout(pollT);
  try {
    job.value = await get('/cfd/jobs/' + encodeURIComponent(job.value.id));
    if (job.value.status === 'done') { res.value = await get(`/cfd/jobs/${encodeURIComponent(job.value.id)}/result`); loadJobs(); return; }
    if (job.value.status === 'failed') { loadJobs(); return; }
    if (job.value.status === 'running') {
      try { const r = await get(`/cfd/jobs/${encodeURIComponent(job.value.id)}/result`); progress.value = { 网格: '划网格', 流场: '算流场', 温度场: '算温度场' }[r.progress?.stage] || ''; } catch (e) { /* */ }
    }
  } catch (e) { err.value = e.message; return; }
  pollT = setTimeout(poll, 3000);
}
async function openJob(id) { job.value = { id }; res.value = null; exp.value = null; poll(); }
async function bench() { try { job.value = await post('/cfd/bench'); res.value = null; poll(); loadJobs(); } catch (e) { err.value = e.message; } }
function toThermal() { router.push({ path: '/cae', query: { cfd: job.value.id } }); }
async function explain() {
  expBusy.value = true;
  try { exp.value = await post(`/cfd/jobs/${encodeURIComponent(job.value.id)}/explain`); } catch (e) { err.value = e.message; } finally { expBusy.value = false; }
}
const frame = () => new Promise((r) => requestAnimationFrame(() => r()));
async function report() {
  repBusy.value = true;
  try {
    const images = [];
    const shots = [['p', '零件表面压力（Pa，相对来流）、流线（按速度着色）和水平速度截面']];
    if (st.value.heat_w != null) shots.push(['h', '零件表面散热系数 h（W/(m²·K)）']);
    for (const [f, cap] of shots) {
      viewer.value.setField(f); await frame(); await frame(); await frame();
      images.push({ data: viewer.value.snapshot(), caption: cap + '，色标蓝 → 红 = 低 → 高' });
    }
    const r = await fetch(`/api/cfd/jobs/${encodeURIComponent(job.value.id)}/report`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'x-wq-token': session.token }, body: JSON.stringify({ images, ai_text: exp.value?.text }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || '报告生成失败');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await r.blob());
    a.download = `流体分析报告-${job.value.id}.docx`;
    document.body.appendChild(a); a.click(); a.remove();
  } catch (e) { err.value = e.message; } finally { repBusy.value = false; }
}
async function aiFill() {
  aiBusy.value = true;
  try {
    const r = await post('/cfd/ai-setup', { text: aiText.value, bbox: geo.value?.solid?.bbox_mm });
    aiRes.value = r;
    const f = r.form;
    if (f.velocity_ms != null) vel.value = f.velocity_ms;
    if (f.direction) dir.value = f.direction;
    if (f.air_t_c != null) tAir.value = f.air_t_c;
    if (f.heat != null) heat.value = f.heat;
    if (f.wall_t_c != null) tWall.value = f.wall_t_c;
    if (f.ground != null) ground.value = f.ground;
  } catch (e) { err.value = e.message; } finally { aiBusy.value = false; }
}
async function loadJobs() { try { jobs.value = (await get('/cfd/jobs')).jobs; } catch (e) { /* */ } }

onMounted(async () => {
  try { const p = await get('/cae/parts'); parts.value = p.items; examples.value = p.examples || []; } catch (e) { err.value = e.status === 503 ? '计算服务暂时连不上，请稍后再试' : e.message; }
  loadJobs();
});
onUnmounted(() => clearTimeout(pollT));
</script>

<style scoped>
.labs { margin-left: auto; white-space: nowrap; }
.side { width: 380px; flex-shrink: 0; display: flex; flex-direction: column; gap: 9px; align-self: flex-start; }
.grow { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.step { display: flex; align-items: center; gap: 8px; font-weight: 600; margin-top: 6px; }
.step b { width: 22px; height: 22px; border-radius: 50%; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; }
.line { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.grow-in { flex: 1; } .grow-in, .full { height: 34px; box-sizing: border-box; border: 1px solid #C8CEC7; border-radius: 6px; padding: 0 8px; background: #fff; width: 100%; }
.numin { width: 64px; height: 26px; border: 1px solid #C8CEC7; border-radius: 5px; padding: 0 4px; }
select { height: 28px; border: 1px solid #C8CEC7; border-radius: 5px; }
.upload { display: flex; flex-direction: column; gap: 4px; color: var(--muted); }
.exbox { border: 1px dashed var(--line); border-radius: 8px; padding: 6px 8px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; margin-top: 4px; }
.grid2 input { width: 70px; height: 26px; border: 1px solid #C8CEC7; border-radius: 5px; }
.chk { display: flex; gap: 6px; align-items: center; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; align-self: flex-start; }
.seg button { border: 0; background: #fff; padding: 6px 12px; cursor: pointer; font-size: 13px; }
.seg button.on { background: var(--accent-bg); font-weight: 600; }
.ai-box { display: flex; flex-direction: column; gap: 6px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
.ai-box textarea { border: 1px solid #C8CEC7; border-radius: 6px; padding: 6px 8px; resize: vertical; }
.big-w { height: 42px; font-size: 15px; margin-top: 6px; }
.small-btn { height: 28px; font-size: 12px; }
.warnline { color: var(--warn-ink); }
.okline { color: var(--good, #1B5E20); }
.big-empty { padding: 140px 0; text-align: center; line-height: 1.8; }
.jobbar { border-radius: 8px; padding: 10px 14px; background: var(--accent-bg); color: var(--accent); }
.jobbar.failed { background: var(--bad-bg); color: var(--bad); }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
.kpi { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 2px; }
.kpi.warn { background: #FFF6DD; }
.big { font-size: 16px; font-weight: 600; }
.exp { background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 6px 12px; }
.exp p { margin: 3px 0; line-height: 1.7; }
h3 { margin: 6px 0 0; font-size: 15px; }
@media (max-width: 1100px) { .side { width: 100%; } }
</style>
