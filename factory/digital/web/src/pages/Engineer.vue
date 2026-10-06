<template>
  <div class="page">
    <TaskBar v-if="teachStatus" :t="teachStatus" />
    <div class="page-title"><h1>设计与工艺</h1><span class="muted">工艺员工作区 · 输出轴 SH-301 的设计版本、工艺路线与键槽 G 代码</span></div>

    <!-- 第 6 轮 W2：网页设计台，不用装软件 -->
    <section id="design" class="card">
      <div class="card-head"><h2>在线设计 · 输出轴 SH-301</h2>
        <span class="muted small">改参数 → 看三维与校核 → 发布。服务器生成 STEP、零件图、键槽 G 代码，与 FreeCAD 发布效果相同</span></div>
      <div v-if="suggestNote" class="sugg small">已按“{{ suggestNote }}”填好参数（还没发布）：看三维和校核，满意就发布新版本，再回“仿真与分析”重新计算对比。
        <button class="btn ghost small" @click="suggestNote = ''; loadParams()">不用了，恢复现行版</button></div>
      <div v-if="!form" class="empty">正在读取现行设计…</div>
      <div v-else class="design">
        <div class="form">
          <table class="t segs">
            <thead><tr><th>轴段</th><th class="num">直径 mm</th><th class="num">长度 mm</th><th></th></tr></thead>
            <tbody><tr v-for="(sg, i) in form.segments" :key="i">
              <td>{{ i + 1 }}<span v-if="form.keyway && form.keyway.segment === i" class="pill info">键槽</span></td>
              <td class="num"><input v-model.number="sg[0]" type="number" step="0.5" min="5" max="48" :aria-label="'第' + (i + 1) + '段直径'"></td>
              <td class="num"><input v-model.number="sg[1]" type="number" step="1" min="2" max="300" :aria-label="'第' + (i + 1) + '段长度'"></td>
              <td><button class="btn ghost small" :disabled="form.segments.length <= 1" title="删除这一段" @click="delSeg(i)">删除</button></td>
            </tr></tbody>
          </table>
          <div class="line">
            <button class="btn ghost small" :disabled="form.segments.length >= 8" @click="addSeg">＋ 加一段</button>
            <label>两端倒角 <input v-model.number="form.chamfer" type="number" step="0.5" min="0" max="5"> mm</label>
            <label title="各台阶内角的过渡圆角，0 为尖角；轴承靠紧的轴肩要小于轴承内圈倒角">台阶圆角 <input v-model.number="form.fillet" type="number" step="0.2" min="0" max="5" placeholder="0"> mm</label>
          </div>
          <div class="line kw">
            <label><input v-model="hasKey" type="checkbox"> 平键槽</label>
            <template v-if="form.keyway">
              <label>在第 <select v-model.number="form.keyway.segment"><option v-for="(sg, i) in form.segments" :key="i" :value="i">{{ i + 1 }}</option></select> 段</label>
              <label>键宽 b <input v-model.number="form.keyway.b" type="number" step="1" min="1"></label>
              <label>槽深 t <input v-model.number="form.keyway.t" type="number" step="0.5" min="0.5"></label>
              <label>槽长 L <input v-model.number="form.keyway.L" type="number" step="1" min="1"></label>
            </template>
          </div>
          <div v-if="chk" class="checks small">
            <div v-for="e in chk.errors" :key="e" class="err">✗ {{ e }}</div>
            <div v-for="w in chk.warnings" :key="w" class="warnline">！{{ w }}
              <button v-if="chk.recommended" class="btn ghost small" @click="useRec">用推荐值</button></div>
            <div v-if="chk.ok" class="okline">✓ 校核通过 · 总长 {{ chk.total_length_mm }} mm · 45 钢下料 {{ chk.bom?.[0]?.qty }} kg</div>
          </div>
          <div class="line">
            <input v-model="note" class="note" maxlength="200" placeholder="改动说明，例如：键槽长 45 → 42">
            <button class="btn primary" :disabled="!chk?.ok || busy" @click="publish">{{ busy ? '正在生成…' : (session.user?.mode === 'prod' ? '提交审批' : '发布新版本') }}</button>
            <button class="btn ghost" :disabled="busy" @click="loadParams">恢复现行版</button>
          </div>
          <div v-if="pubMsg" :class="pubOk ? 'ok' : 'err'">{{ pubMsg }}</div>
        </div>
        <ShaftView class="view" :params="form" />
      </div>
    </section>

    <div class="row">
      <section class="card grow">
        <div class="card-head"><h2>设计版本</h2><span class="muted small">由上面的在线设计或 FreeCAD 发布宏经总线发来（design/sh-301/release）</span></div>
        <div v-if="!d.releases.length" class="empty">还没有发布过新版本。现行为工厂数据里的第 1 版。</div>
        <table v-else class="t">
          <thead><tr><th>版本</th><th>时间</th><th>设计者</th><th>改动</th><th>BOM（45 钢）</th><th>文件</th></tr></thead>
          <tbody><tr v-for="r in d.releases" :key="r.id">
            <td class="mono b">rev {{ r.revision }}</td><td class="small">{{ timeOf(r.ts) }}</td><td>{{ r.author }}</td>
            <td>{{ r.change_note || '—' }}</td><td class="mono">{{ r.bom?.[0]?.qty }} kg</td>
            <td class="small"><a v-for="f in r.files" :key="f.sha256" :href="'/api' + f.url.replace(/^\/api/, '')" target="_blank" class="flink">{{ f.kind === 'drawing' ? '零件图' : f.kind === 'step' ? 'STEP' : f.name }}</a></td>
          </tr></tbody>
        </table>
        <div v-if="drawing" class="drawing"><img :src="drawing" alt="最新版零件图"></div>
      </section>
      <section class="card side">
        <div class="card-head"><h2>进阶：用桌面 CAD 发布（选做）</h2></div>
        <p class="small muted">上面的“在线设计”不用装任何软件。想学真 CAD 的同学，可以用 FreeCAD 1.1 或 SolidWorks 的宏发布，效果相同（SolidWorks 步骤见宏包里的使用说明）：</p>
        <ol class="small steps">
          <li>安装 <a href="https://www.freecad.org/downloads.php" target="_blank" rel="noopener">FreeCAD 1.1</a>。</li>
          <li><button class="btn ghost small" :disabled="packBusy" @click="downloadPack">{{ packBusy ? '正在打包…' : '下载我的 CAD 宏包' }}</button>
            解压到任意文件夹（工作台地址和你的登录凭证已填好，7 天有效）。</li>
          <li>FreeCAD：宏 → 宏…，把“用户宏的位置”设为这个文件夹。</li>
          <li>编辑 <span class="mono">wq_shaft.py</span> 的 <span class="mono">PARAMS</span>（例如键槽长 45 → 42）并保存，再执行 <span class="mono">wq_publish.py</span>。</li>
          <li>回到这里刷新：新版本、零件图、G 代码出现。详细步骤见宏包里的“使用说明.txt”。</li>
        </ol>
        <div v-if="packErr" class="err small">{{ packErr }}</div>
        <div v-for="a in alerts" :key="a.id" class="alert small"><b>{{ a.title }}</b><div>{{ a.detail }}</div></div>
      </section>
    </div>

    <div class="row">
      <section class="card grow">
        <div class="card-head"><h2>键槽 G 代码</h2><span class="muted small">design/sh-301/gcode · 下达工单时随“铣键槽”工序派给 KEY-01</span>
          <router-link v-if="g" :to="{ path: '/3d', query: { gcode: g.gcode_ref } }" class="more">在 3D 车间回放 →</router-link></div>
        <div v-if="!g" class="empty">还没有 G 代码（随设计发布一起生成）。</div>
        <template v-else>
          <p class="small">rev {{ g.revision }} · 刀具 {{ g.tools.map((t) => t.type + ' Ø' + t.diameter_mm).join('、') }} ·
            切削长度 {{ g.cut_length_mm }} mm · 预计 {{ Math.round(g.est_time_s / 60 * 10) / 10 }} 分钟</p>
          <GcodeView :code="code" :slot="g.slot" />
          <pre class="code">{{ code }}</pre>
        </template>
      </section>
      <section class="card side">
        <div class="card-head"><h2>工艺路线 {{ rt?.routing }}</h2></div>
        <table v-if="rt" class="t">
          <thead><tr><th>工序</th><th class="num">分钟/件</th><th>设备</th></tr></thead>
          <tbody><tr v-for="o in rt.operations" :key="o.operation">
            <td>{{ o.operation.split(' ')[0] }}</td><td class="num">{{ o.minutes }}</td><td class="mono small">{{ o.units.map((u) => u.toUpperCase()).join(' / ') }}</td>
          </tr></tbody>
        </table>
        <p v-if="rt" class="small muted">标准成本：材料 ${{ rt.std_cost.material }} + 加工 ${{ rt.std_cost.operations }} / 件</p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { get, post, session } from '../lib/api';
import ShaftView from '../components/ShaftView.vue';
import { timeOf } from '../lib/fmt';
import GcodeView from '../components/GcodeView.vue';
import TaskBar from '../components/TaskBar.vue';

const route = useRoute();

const d = ref({ releases: [], gcode: [] });
const rt = ref(null);
const code = ref('');
const alerts = ref([]);
const teachStatus = ref(null);
const g = computed(() => d.value.gcode.find((x) => (x.operation || '').startsWith('铣键槽')) || null);   // 第 13 轮起还有车削等工序的程序
const drawing = computed(() => {
  const f = d.value.releases[0]?.files?.find((x) => x.kind === 'drawing');
  return f ? f.url : null;
});
// ---- 在线设计（第 6 轮 W2、W3）
const ITEM = 'SH-301';
const form = ref(null);
const chk = ref(null);
const note = ref('');
const busy = ref(false);
const pubMsg = ref('');
const pubOk = ref(true);
let lastKey = null;
const hasKey = computed({
  get: () => !!form.value?.keyway,
  set: (v) => { form.value.keyway = v ? (lastKey || { segment: 0, b: 6, t: 3.5, L: 20 }) : null; },
});
async function loadParams() {
  const r = await get(`/design/${ITEM}/params`);
  form.value = r.params;
  lastKey = r.params.keyway;
  chk.value = r.check;
}
// 第 11 轮：仿真与分析的建议（/work/engineer?suggest=…）先填进表单，确认后再发布
const suggestNote = ref('');
function applySuggest() {
  const q = route.query;
  if (!q.suggest) return;
  try {
    form.value = JSON.parse(q.suggest);
    lastKey = form.value.keyway;
    note.value = q.note || '按仿真建议修改';
    suggestNote.value = q.note || '仿真与分析的建议';
    setTimeout(() => document.getElementById('design')?.scrollIntoView({ behavior: 'smooth' }), 100);
  } catch (e) { /* 参数不对就用现行版 */ }
}
function addSeg() { const l = form.value.segments[form.value.segments.length - 1]; form.value.segments.push([l[0], 20]); }
function delSeg(i) {
  form.value.segments.splice(i, 1);
  const kw = form.value.keyway;
  if (kw && kw.segment >= form.value.segments.length) kw.segment = form.value.segments.length - 1;
}
function useRec() { Object.assign(form.value.keyway, { b: chk.value.recommended.b, t: chk.value.recommended.t }); }
let tmr;
watch(() => JSON.stringify(form.value), () => {
  if (!form.value) return;
  if (form.value.keyway) lastKey = form.value.keyway;
  clearTimeout(tmr);
  tmr = setTimeout(async () => {
    try { chk.value = await post(`/design/${ITEM}/check`, { params: form.value }); } catch (e) { chk.value = { ok: false, errors: [e.message], warnings: [] }; }
  }, 300);
});
async function publish() {
  busy.value = true; pubMsg.value = '';
  try {
    const r = await post(`/design/${ITEM}/publish`, { params: form.value, change_note: note.value });
    pubOk.value = true;
    pubMsg.value = r.pending
      ? '已提交审批（生产模式）：审批人在“设计发布与审批”里看图、批准后生效，ERPNext 和车间才会更新。'
      : `已发布 rev ${r.revision}：${r.step ? 'STEP、' : ''}零件图、键槽 G 代码（${r.gcode_lines} 行）已生成，ERPNext 设计版本随后更新。`;
    note.value = '';
    await loadDesign();
  } catch (e) { pubOk.value = false; pubMsg.value = e.message; } finally { busy.value = false; }
}
const packBusy = ref(false);
const packErr = ref('');
async function downloadPack() {
  packBusy.value = true; packErr.value = '';
  try {
    const r = await fetch('/api/freecad/pack.zip', { headers: { 'x-wq-token': session.token } });
    if (!r.ok) throw new Error('下载失败（' + r.status + '）');
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement('a');
    a.href = url; a.download = 'wenquest-freecad.zip'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (e) { packErr.value = e.message; } finally { packBusy.value = false; }
}
async function loadDesign() {
  d.value = await get('/design/' + ITEM);
  if (g.value) code.value = await (await fetch(g.value.gcode_ref)).text();
}

onMounted(async () => {
  loadParams().then(applySuggest);
  [d.value, rt.value] = await Promise.all([get('/design/SH-301'), get('/routing/SH-301')]);
  if (g.value) code.value = await (await fetch(g.value.gcode_ref)).text();
  const al = await get('/history?type=ai.alert&hours=72&limit=50');
  alerts.value = al.filter((a) => (a.data.key || '').startsWith('release:')).slice(0, 3).map((a) => ({ id: a.id, ...a.data }));
  if (session.user.mode === 'teach') teachStatus.value = await get('/teach');
});
</script>

<style scoped>
.grow { flex-grow: 1; min-width: 0; }
.side { width: 360px; flex-shrink: 0; }
.b { font-weight: 600; }
.flink { margin-right: 8px; }
.drawing { margin-top: 12px; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.drawing img { width: 100%; display: block; }
.steps { padding-left: 18px; line-height: 1.7; margin: 0 0 8px; }
.alert { background: var(--accent-bg); border-radius: 8px; padding: 8px 10px; margin-top: 8px; }
.sugg { background: var(--task-bg); border: 1px solid var(--task-line); color: var(--task-ink); border-radius: 8px; padding: 8px 12px; margin-bottom: 10px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.design { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
.form input[type=number] { width: 72px; }
.segs input { text-align: right; }
.line { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-top: 10px; }
.kw select { margin: 0 4px; }
.note { flex-grow: 1; min-width: 200px; }
.checks { margin-top: 10px; display: flex; flex-direction: column; gap: 4px; }
.err { color: var(--bad); }
.ok, .okline { color: var(--good); }
.warnline { color: var(--warn-ink); display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.pill.info { margin-left: 6px; }
@media (max-width: 900px) { .design { grid-template-columns: 1fr; } }
.code { background: var(--surface-2); border-radius: 8px; padding: 10px 12px; font-family: var(--mono); font-size: 12px; max-height: 220px; overflow: auto; }
@media (max-width: 1100px) { .side { width: auto; } }
</style>
