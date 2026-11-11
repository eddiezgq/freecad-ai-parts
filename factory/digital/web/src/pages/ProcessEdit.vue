<template>
  <!-- 第 128 轮（阶段 C1）：在页面上改工艺卡。改的是工艺规程的数据，卡片（过程卡、工序卡、检验卡、刀具卡）照 JB/T 9165.2 版式重排；
       边改边核算（卡片能否生成）和 AI 工艺评审员预检；草稿自动存；导出 Word / PDF；改好“提交审批”照旧走评审与批准。 -->
  <div class="page">
    <div class="page-title"><h1>{{ $t('在页面上改工艺卡 · {a}', { a: item }) }}</h1>
      <span class="muted">{{ $t('改格子里的数据，右边的卡片当场重排；红色是必须改的问题。不用下载、不用装 Office。') }}</span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div class="bar">
      <router-link to="/process" class="small">{{ $t('← 工艺规程') }}</router-link>
      <span class="small muted">{{ saving ? $t('保存中…') : dirty ? $t('未保存') : saved ? $t('草稿已保存 ') + timeOf(saved) : '' }}</span>
      <span class="grow" />
      <button class="btn ghost" :disabled="busy" @click="restart('reference')">{{ $t('从参照工艺规程重新开始') }}</button>
      <button class="btn" :disabled="busy || !plan" @click="exportAs('docx')">{{ $t('导出 Word') }}</button>
      <button class="btn" :disabled="busy || !plan" @click="exportAs('pdf')">{{ $t('导出 PDF') }}</button>
      <input v-model="note" class="note" maxlength="300" :placeholder="$t('改动说明（提交时一并记录）')">
      <button class="btn primary" :disabled="busy || !plan || problems.length > 0" :title="problems.length ? $t('先把红色问题改掉') : ''" @click="submit">{{ $t('提交审批') }}</button>
    </div>

    <div v-if="plan" class="cols">
      <div class="edit">
        <section class="card">
          <div class="card-head"><h2>{{ $t('文件头') }}</h2><span class="muted small">{{ $t('卡片表头和签署栏') }}</span></div>
          <div class="grid">
            <label v-for="f in HEAD" :key="f[0]" class="small">{{ $td(f[1]) }}<input :value="getp(f[0])" @input="setp(f[0], $event.target.value, f[2])"></label>
          </div>
          <div class="grid">
            <label v-for="s in SIGNS" :key="s[0]" class="small">{{ $td(s[1]) }}
              <span class="two"><input :value="sig(s[0]).by" :placeholder="$t('签字')" @input="setSig(s[0], 'by', $event.target.value)">
                <input :value="sig(s[0]).date" :placeholder="$t('日期')" @input="setSig(s[0], 'date', $event.target.value)"></span></label>
          </div>
        </section>

        <section class="card">
          <div class="card-head"><h2>{{ $t('机械加工工艺过程卡片') }}</h2><span class="muted small">{{ $t('工序：点“工步”在下面改这道工序的工序卡') }}</span></div>
          <ETable :cols="OPS" :rows="plan.operations" :bad="badSeqs" key-field="seq" @change="changed" @add="addOp" @pick="(i) => (opIdx = i)" :pick-label="$t('工步')" />
        </section>

        <section v-if="op" class="card">
          <div class="card-head"><h2>{{ $t('机械加工工序卡片 · 工序 {a} {b}', { a: $td(op.seq), b: $td(op.operation) }) }}</h2>
            <span class="muted small">{{ $t('转速、机动时间由切削用量算出，不手填；车削走刀写“切前直径,背吃刀量,走刀长度”，多刀用分号隔开') }}</span></div>
          <div class="grid">
            <label class="small">{{ $t('定位基准') }}<input v-model="op.datum" @input="changed"></label>
            <label class="small">{{ $t('装夹') }}<input v-model="op.clamping" @input="changed"></label>
            <label class="small">{{ $t('夹具') }}<input v-model="op.fixture" @input="changed"></label>
            <label class="small">{{ $t('切削液') }}<input v-model="op.coolant" @input="changed"></label>
          </div>
          <h3>{{ $t('工步') }}</h3>
          <ETable :cols="STEPS" :rows="op.steps || (op.steps = [])" @change="changed" @add="() => addRow(op.steps, { step: (op.steps.length || 0) + 1, content: '' })" />
          <h3>{{ $t('本工序检验') }}</h3>
          <ETable :cols="INSPECT" :rows="op.inspect || (op.inspect = [])" @change="changed" @add="() => addRow(op.inspect, { char: '', gauge: '', freq: '' })" />
        </section>

        <section class="card">
          <div class="card-head"><h2>{{ $t('检验卡片 · 图纸特性') }}</h2><span class="muted small">{{ $t('终检工序要逐条覆盖这些特性') }}</span></div>
          <ETable :cols="CHARS" :rows="plan.characteristics || (plan.characteristics = [])" @change="changed"
                  @add="() => addRow(plan.characteristics, { id: 'C' + ((plan.characteristics.length || 0) + 1), name: '', spec: '', kind: 'dim' })" />
        </section>

        <section class="card">
          <div class="card-head"><h2>{{ $t('刀具卡片') }}</h2></div>
          <ETable :cols="TOOLS" :rows="plan.tool_list || (plan.tool_list = [])" @change="changed"
                  @add="() => addRow(plan.tool_list, { id: 'T' + String((plan.tool_list.length || 0) + 1).padStart(2, '0'), name: '', spec: '', ops: [] })" />
          <h3>{{ $t('量检具') }}</h3>
          <ETable :cols="GAUGES" :rows="plan.gauges || (plan.gauges = [])" @change="changed"
                  @add="() => addRow(plan.gauges, { id: 'G' + String((plan.gauges.length || 0) + 1).padStart(2, '0'), name: '' })" />
        </section>

        <section class="card">
          <div class="card-head"><h2>{{ $t('更改记录') }}</h2></div>
          <ETable :cols="CHANGES" :rows="changes" @change="changed" @add="() => addRow(changes, { mark: '', count: 1, ecn: '', by: '', date: '' })" />
        </section>
      </div>

      <div class="side">
        <section class="card">
          <div class="card-head"><h2>{{ $t('核算与 AI 预检') }}</h2><span class="muted small">{{ checking ? $t('检查中…') : $t('改完 1 秒自动检查') }}</span></div>
          <div v-if="problems.length" class="probs"><div v-for="(p, i) in problems" :key="i" class="small bad-t">✗ {{ p }}</div></div>
          <div v-else class="small ok">{{ $t('卡片数据完整，可以生成全套卡片。') }}</div>
          <div v-if="live" class="score">{{ $t('AI 预检 · 建议分') }} <b>{{ $td(live.suggested_score) }}</b>
            <span class="pill bad">{{ $t('{a} 必须改', { a: count(live.findings, 'error') }) }}</span>
            <span class="pill warn">{{ $t('{a} 建议', { a: count(live.findings, 'warning') }) }}</span></div>
          <table v-if="live?.findings?.length" class="t small">
            <thead><tr><th>{{ $t('级别') }}</th><th>{{ $t('规则') }}</th><th>{{ $t('工序') }}</th><th>{{ $t('意见') }}</th></tr></thead>
            <tbody><tr v-for="(f, i) in live.findings" :key="i">
              <td><span class="pill" :class="f.level === 'error' ? 'bad' : f.level === 'warning' ? 'warn' : ''">{{ LEVEL[f.level] || f.level }}</span></td>
              <td>{{ $td(f.rule) }}</td><td class="num">{{ f.seq ?? '—' }}</td><td>{{ $td(f.text) }}</td></tr></tbody>
          </table>
        </section>
        <section class="card">
          <div class="card-head"><h2>{{ $t('卡片') }}</h2><span class="muted small">{{ $t('和导出的 Word / PDF 同一版式') }}</span></div>
          <iframe class="preview" :srcdoc="html" :title="$t('工艺卡片')"></iframe>
        </section>
      </div>
    </div>
    <div v-if="msg" class="small" :class="ok ? 'ok' : 'err'">{{ msg }}</div>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, defineComponent, h, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api, post, session } from '../lib/api';

const LEVEL = { error: $t('必须改'), warning: $t('建议'), info: $t('说明') };
// 列：[字段, 名称, 类型]；类型 n = 数字，l = 逗号分隔的数字表，b = 是 / 否，pd = 车削走刀（切前直径,背吃刀量,走刀长度; …）
const HEAD = [['doc.number', $t('文件编号')], ['doc.revision', $t('版本')], ['doc.product_model', $t('产品型号')], ['doc.product_name', $t('产品名称')],
  ['doc.drawing_no', $t('零件图号')], ['doc.part_name', $t('零件名称')], ['material', $t('材料牌号')], ['blank.kind', $t('毛坯种类')], ['blank.spec', $t('毛坯规格')],
  ['blank.length_mm', $t('毛坯长度 mm'), 'n'], ['doc.per_blank', $t('每毛坯件数'), 'n'], ['doc.per_unit', $t('每台件数'), 'n'], ['doc.batch', $t('批量'), 'n']];
const SIGNS = [['prepared', $t('编制')], ['checked', $t('审核')], ['standardized', $t('标准化')], ['approved', $t('批准')]];
const OPS = [['seq', $t('工序号'), 'n'], ['operation', $t('工序名称')], ['workstation', $t('设备')], ['shop', $t('车间')], ['content', $t('工序内容'), 'w'],
  ['datum', $t('定位基准')], ['setup_min', $t('准终 min'), 'n'], ['minutes', $t('单件 min'), 'n']];
const STEPS = [['step', $t('工步'), 'n'], ['content', $t('工步内容'), 'w'], ['tool', $t('刀具')], ['gauge', $t('量具')], ['op', $t('类型')], ['d', $t('直径 d'), 'n'],
  ['vc', 'vc m/min', 'n'], ['f', 'f mm/r', 'n'], ['ap', 'ap mm', 'n'], ['passes', $t('次数'), 'n'], ['depth', $t('孔深'), 'n'],
  ['passes_detail', $t('车削走刀'), 'pd'], ['ta_min', $t('辅助 min'), 'n'], ['tb_min', $t('机动 min（不填则算）'), 'n']];
const INSPECT = [['char', $t('检验项目'), 'w'], ['gauge', $t('量检具')], ['freq', $t('频次')]];
const CHARS = [['id', $t('编号')], ['name', $t('名称'), 'w'], ['spec', $t('技术要求'), 'w'], ['nominal', $t('基本尺寸'), 'n'], ['es', $t('上偏差'), 'n'], ['ei', $t('下偏差'), 'n'],
  ['kind', $t('类别')], ['key', $t('关键'), 'b']];
const TOOLS = [['id', $t('刀具号')], ['name', $t('名称')], ['spec', $t('规格'), 'w'], ['ops', $t('用于工序'), 'l'], ['life', $t('寿命 / 修磨')]];
const GAUGES = [['id', $t('编号')], ['name', $t('名称'), 'w']];
const CHANGES = [['mark', $t('标记')], ['count', $t('处数'), 'n'], ['ecn', $t('更改文件号')], ['by', $t('签字')], ['date', $t('日期')]];

function show(v, type) {
  if (v === undefined || v === null) return '';
  if (type === 'l') return (v || []).join(', ');
  if (type === 'pd') return (v || []).map((x) => x.join(',')).join('; ');
  return String(v);
}
function parse(s, type) {
  s = String(s).trim();
  if (type === 'b') return !!s;
  if (s === '') return undefined;
  if (type === 'n') { const n = Number(s); return Number.isFinite(n) ? n : s; }
  if (type === 'l') return s.split(/[,，\s]+/).filter(Boolean).map((x) => (Number.isFinite(Number(x)) ? Number(x) : x));   // i18n-ok 数据值比较
  if (type === 'pd') return s.split(/[;；]/).map((x) => x.split(/[,，]/).map((y) => Number(y.trim()))).filter((x) => x.length === 3 && x.every(Number.isFinite));   // i18n-ok 数据值比较
  return s;
}

// 可编辑表格：改格子、加行、删行、上下移
const ETable = defineComponent({
  props: { cols: Array, rows: Array, bad: { type: Set, default: () => new Set() }, keyField: String, pickLabel: String },
  emits: ['change', 'add', 'pick'],
  setup(props, { emit }) {
    const setCell = (r, c, v) => {
      const val = parse(v, c[2]);
      if (val === undefined) delete r[c[0]]; else r[c[0]] = val;
      emit('change');
    };
    const move = (i, d) => {
      const j = i + d;
      if (j < 0 || j >= props.rows.length) return;
      const x = props.rows[i]; props.rows[i] = props.rows[j]; props.rows[j] = x; emit('change');
    };
    return () => h('div', { class: 'tw' }, [
      h('table', { class: 't small et' }, [
        h('thead', h('tr', [...props.cols.map((c) => h('th', c[1])), h('th', '')])),
        h('tbody', props.rows.map((r, i) => h('tr', { class: props.keyField && props.bad.has(r[props.keyField]) ? 'badrow' : '' }, [
          ...props.cols.map((c) => h('td', { class: c[2] === 'w' ? 'wide' : '' }, c[2] === 'b'
            ? h('input', { type: 'checkbox', checked: !!r[c[0]], onChange: (e) => setCell(r, c, e.target.checked ? '1' : '') })
            : h('input', { value: show(r[c[0]], c[2]), onChange: (e) => setCell(r, c, e.target.value) }))),
          h('td', { class: 'acts' }, [
            props.pickLabel ? h('a', { onClick: () => emit('pick', i) }, props.pickLabel) : null,
            h('a', { onClick: () => move(i, -1) }, '↑'), h('a', { onClick: () => move(i, 1) }, '↓'),
            h('a', { class: 'del', onClick: () => { props.rows.splice(i, 1); emit('change'); } }, '✕')])]))),
      ]),
      h('button', { class: 'btn ghost small', onClick: () => emit('add') }, $t('＋ 加一行')),
    ]);
  },
});

const route = useRoute();
const router = useRouter();
const item = computed(() => route.params.item);
const plan = ref(null);
const opIdx = ref(0);
const op = computed(() => plan.value?.operations?.[opIdx.value] || null);
const changes = computed(() => {
  const d = plan.value.doc || (plan.value.doc = {});
  return d.changes || (d.changes = []);
});
const problems = ref([]);
const live = ref(null);
const html = ref('');
const err = ref('');
const msg = ref('');
const ok = ref(true);
const note = ref('');
const busy = ref(false);
const dirty = ref(false);
const saving = ref(false);
const checking = ref(false);
const saved = ref(null);
const badSeqs = computed(() => new Set((live.value?.findings || []).filter((f) => f.level === 'error').map((f) => f.seq)));
const count = (l, lv) => (l || []).filter((f) => f.level === lv).length;
const timeOf = (t) => (t ? new Date(t).toLocaleTimeString('zh-CN', { hour12: false }) : '');
let tSave = null, tCheck = null;

function getp(path) {
  return show(path.split('.').reduce((o, k) => (o ? o[k] : undefined), plan.value));
}
function setp(path, v, type) {
  const ks = path.split('.');
  let o = plan.value;
  for (const k of ks.slice(0, -1)) o = o[k] || (o[k] = {});
  const val = parse(v, type);
  if (val === undefined) delete o[ks[ks.length - 1]]; else o[ks[ks.length - 1]] = val;
  changed();
}
function sig(k) {
  const d = plan.value.doc || (plan.value.doc = {});
  const s = d.signatures || (d.signatures = {});
  return s[k] || (s[k] = { by: '', date: '' });
}
function setSig(k, f, v) { sig(k)[f] = v; changed(); }
function addRow(list, row) { list.push(row); changed(); }
function addOp() {
  const ops = plan.value.operations;
  const seq = ops.length ? Math.max(...ops.map((o) => Number(o.seq) || 0)) + 10 : 10;
  ops.push({ seq, operation: '', workstation: '', content: '', datum: '', minutes: 0, setup_min: 0, steps: [], inspect: [] });
  opIdx.value = ops.length - 1;
  changed();
}

function changed() {
  dirty.value = true;
  clearTimeout(tSave); clearTimeout(tCheck);
  tSave = setTimeout(save, 2000);
  tCheck = setTimeout(check, 1000);
}
async function save() {
  if (!dirty.value || !plan.value) return;
  saving.value = true;
  try { const r = await api('PUT', '/process/drafts/' + item.value, { plan: plan.value }); saved.value = r.saved; dirty.value = false; }
  catch (e) { err.value = e.message; } finally { saving.value = false; }
}
async function check() {
  if (!plan.value) return;
  checking.value = true;
  try {
    const r = await post('/process/live', { plan: plan.value });
    problems.value = r.problems; live.value = r;
    if (!r.problems.length) {
      const res = await fetch('/api/process/cards?fmt=html', { method: 'POST', headers: { 'Content-Type': 'application/json', 'x-wq-token': session.token || '' },
        body: JSON.stringify(plan.value) });
      if (res.ok) html.value = await res.text();
    }
  } catch (e) { err.value = e.message; } finally { checking.value = false; }
}
async function load(start = '') {
  err.value = '';
  try {
    const r = await api('GET', `/process/drafts/${item.value}${start ? '?start=' + encodeURIComponent(start) : ''}`);
    plan.value = r.plan; saved.value = r.saved; dirty.value = false; opIdx.value = 0;
    if (!plan.value.operations) plan.value.operations = [];
    await check();
  } catch (e) { err.value = e.message; }
}
async function restart(start) {
  if (!confirm($t('放弃草稿，从参照工艺规程重新开始？'))) return;
  await load(start);
  dirty.value = true; save();
}
async function exportAs(fmt) {
  busy.value = true; msg.value = '';
  try {
    await save();
    const res = await fetch('/api/process/cards?fmt=' + fmt, { method: 'POST', headers: { 'Content-Type': 'application/json', 'x-wq-token': session.token || '' },
      body: JSON.stringify(plan.value) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || $t('导出失败'));
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await res.blob());
    a.download = $t('{a}_工艺文件.{b}', { a: item.value, b: fmt }); a.click();
  } catch (e) { msg.value = e.message; ok.value = false; } finally { busy.value = false; }
}
async function submit() {
  busy.value = true; msg.value = '';
  try {
    await save();
    const r = await post('/process/check', { plan: plan.value, submit: true, note: note.value });
    await api('DELETE', '/process/drafts/' + item.value);
    router.push('/process/' + r.id);
  } catch (e) { msg.value = e.message; ok.value = false; } finally { busy.value = false; }
}
onMounted(() => load(route.query.start || ''));
onBeforeUnmount(() => { clearTimeout(tCheck); if (dirty.value) { clearTimeout(tSave); save(); } });
</script>

<style scoped>
.bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.grow { flex: 1; }
.note { min-width: 200px; }
.cols { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); gap: 14px; align-items: start; }
.side { position: sticky; top: 8px; display: flex; flex-direction: column; gap: 14px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 8px 12px; margin-bottom: 10px; }
.grid label { display: flex; flex-direction: column; gap: 3px; }
.two { display: flex; gap: 4px; }
.two input { min-width: 0; flex: 1; }
h3 { font-size: 14px; margin: 12px 0 6px; }
:deep(.tw) { overflow-x: auto; }
:deep(table.et input) { width: 100%; min-width: 60px; box-sizing: border-box; border: 1px solid transparent; padding: 3px 4px; background: transparent; }
:deep(table.et input:focus) { border-color: #9bb; background: #fff; }
:deep(table.et td.wide input) { min-width: 220px; }
:deep(table.et td.acts) { white-space: nowrap; }
:deep(table.et td.acts a) { cursor: pointer; margin-right: 6px; }
:deep(table.et td.acts a.del) { color: #b3261e; }
:deep(tr.badrow td) { background: #fdecea; }
.probs { margin-bottom: 8px; }
.bad-t { color: #b3261e; }
.score { margin: 8px 0; display: flex; gap: 8px; align-items: center; }
.preview { width: 100%; height: 70vh; border: 1px solid var(--line, #e3e6e8); border-radius: 6px; background: #fff; }
td.num { text-align: right; }
@media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } .side { position: static; } }
</style>
