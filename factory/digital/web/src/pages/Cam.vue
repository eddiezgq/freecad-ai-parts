<template>
  <div class="page">
    <div class="page-title"><h1>数控编程</h1>
      <span class="muted">从工艺规程的一道工序出发：几何、机床、刀具、切削参数都取自工艺规程 → 生成 G 代码（FANUC）→ 浏览器里试切：回放、去除材料、和目标比对、检查、算加工时间</span>
    </div>

    <div class="row">
      <section class="card side">
        <div class="step"><b>1</b> 零件与工序</div>
        <div class="seg">
          <button v-for="s in SRC" :key="s.k" type="button" :class="{ on: src === s.k }" @click="src = s.k">{{ s.label }}</button>
        </div>
        <template v-if="src === 'plan'">
          <select v-model="item" class="full" aria-label="零件">
            <option v-for="i in parts" :key="i.item" :value="i.item">{{ i.item }} {{ i.name || '' }}</option>
          </select>
          <div v-if="opsInfo" class="small muted">工艺规程：{{ opsInfo.plan_source }}</div>
          <div v-if="opsInfo" class="ops">
            <label v-for="o in opsInfo.ops" :key="o.seq" class="op" :class="{ dis: !o.cam, on: seq === o.seq }" :title="o.why">
              <input v-model="seq" type="radio" :value="o.seq" :disabled="!o.cam">
              <span class="mono">{{ o.seq }}</span><span class="grow1">{{ o.operation }}</span>
              <span class="small muted">{{ o.workstation }} · {{ o.minutes }} 分</span>
            </label>
          </div>
          <button class="btn" :disabled="busy || !seq" @click="loadSpec">{{ busy ? '正在排编程单…' : '按这道工序排编程单' }}</button>
        </template>
        <template v-else-if="src === 'example'">
          <div v-for="e in examples" :key="e.id" class="small">{{ e.name }}</div>
          <button class="btn" :disabled="busy" @click="loadExample">{{ busy ? '正在识别…' : '读入示例并识别特征' }}</button>
        </template>
        <template v-else>
          <label class="small upload">任何 CAD 导出的 STEP（30 MB 以内）。回转零件按“粗车 → 精车”编；平板、箱体类按 2.5 轴铣削编。
            <input type="file" accept=".step,.stp" @change="pickFile"></label>
          <div class="line small">
            <label><input v-model="upKind" type="radio" value="turn"> 车削</label>
            <label><input v-model="upKind" type="radio" value="mill"> 铣削</label>
            <select v-if="upKind === 'mill'" v-model="upMat"><option v-for="m in ['45', '6061', 'Q235', '40Cr', '7075']" :key="m">{{ m }}</option></select>
            <select v-if="upKind === 'turn'" v-model.number="upSeq"><option :value="10">粗车</option><option :value="20">精车</option></select>
          </div>
          <button class="btn" :disabled="busy || !file" @click="loadUpload">{{ busy ? '正在识别…' : '读入并识别' }}</button>
        </template>

        <template v-if="spec">
          <div class="step"><b>2</b> 编程单 <span class="small muted">{{ KIND[spec.kind] }}{{ spec.mode ? '（' + MODE[spec.mode] + '）' : '' }} · {{ machines[spec.machine]?.name || spec.machine }}</span></div>
          <div v-if="spec.plan_source" class="small muted">{{ spec.plan_source }}</div>
          <div class="ai-box">
            <textarea v-model="aiText" rows="2" maxlength="500" :placeholder="AI_HINT[spec.kind]"></textarea>
            <div class="line"><button class="btn" :disabled="aiBusy || !aiText.trim()" @click="aiFill">{{ aiBusy ? 'AI 正在理解…' : 'AI 改编程单' }}</button>
              <span class="small muted">AI 只改下面的表，你看过再生成</span></div>
            <div v-if="aiRes" class="small">
              <div v-for="n in aiRes.notes" :key="n">✓ {{ n }}</div>
              <div v-for="n in aiRes.unmatched" :key="n" class="warnline">？没看懂或不能改：“{{ n }}”</div>
              <div v-if="aiRes.note" class="muted">{{ aiRes.note }}</div>
            </div>
          </div>

          <template v-if="spec.kind === 'turn'">
            <div class="kv small"><span>毛坯</span><span>{{ stockText }}</span><span class="src">{{ spec.sources?.stock }}</span></div>
            <div class="kv small"><span>本工序总长</span><span><input v-model.number="spec.length" type="number" step="0.1"> mm</span><span class="src">{{ spec.sources?.length }}</span></div>
            <table class="t small">
              <thead><tr><th>部位</th><th class="num">图纸 Ø</th><th class="num">本工序编程 Ø</th></tr></thead>
              <tbody><tr v-for="s in spec.sizes" :key="s.name"><td>{{ s.name }}</td><td class="num">{{ s.design }}</td><td class="num">{{ s.op }}</td></tr>
                <tr v-if="spec.unmapped?.length"><td colspan="3" class="muted">工序里没列出的 {{ spec.unmapped.map((d) => 'Ø' + d).join('、') }} 加 {{ spec.extra }} mm（与列出的部位同样的车削余量）</td></tr></tbody>
            </table>
            <div class="line small"><span>装夹</span>
              <label><input v-model="spec.setups" type="checkbox" value="right"> 右端（第一次装夹）</label>
              <label><input v-model="spec.setups" type="checkbox" value="left"> 左端（调头）</label></div>
            <div class="small muted">编程直径取公差带中间。轮廓：{{ spec.profile.length }} 个点，<a href="#" @click.prevent="showProf = !showProf">{{ showProf ? '收起' : '展开' }}</a></div>
            <div v-if="showProf" class="mono small prof">{{ spec.profile.map((p) => `t${p[0]} Ø${p[1]}`).join('  ') }}</div>
          </template>
          <template v-if="spec.kind === 'slot'">
            <div v-for="f in SLOT_F" :key="f.k" class="kv small"><span>{{ f.label }}</span>
              <span><input v-model.number="spec[f.k]" type="number" step="0.01"> mm</span><span class="src">{{ spec.sources?.[f.k] }}</span></div>
            <div class="small muted">{{ spec.sources?.x0_from_left }}（距左端 {{ spec.x0_from_left }} mm）</div>
          </template>
          <template v-if="spec.kind === 'mill25'">
            <div class="small muted">{{ spec.sources?.ops }}</div>
            <div v-for="(o, i) in spec.ops" :key="i" class="jrow small">
              <div><b>{{ OPN[o.type] }}</b>{{ o.type === 'drill' ? ' ×' + o.holes.length : '' }} · 深 <input v-model.number="o.depth" type="number" step="0.1"> mm
                · 刀 Ø<input v-model.number="o.tool.d" type="number" step="0.5"></div>
              <div class="jctl">
                <label>vc <input v-model.number="o.cut.vc" type="number"> m/min</label>
                <template v-if="o.type === 'drill'"><label>f <input v-model.number="o.cut.f" type="number" step="0.01"> mm/r</label>
                  <label>啄钻 <input v-model.number="o.peck" type="number" step="0.5"> mm</label></template>
                <template v-else><label>fz <input v-model.number="o.cut.fz" type="number" step="0.005"></label><label>齿数 <input v-model.number="o.cut.z" type="number"></label>
                  <label>ap <input v-model.number="o.cut.ap" type="number" step="0.5"></label>
                  <label v-if="o.type === 'pocket'">行距 <input v-model.number="o.cut.stepover" type="number" step="0.05"> ×D</label></template>
              </div>
            </div>
          </template>

          <div v-if="spec.kind !== 'mill25'" class="cut">
            <div class="small"><b>刀具</b> T{{ String(spec.tool.n).padStart(2, '0') }} {{ spec.tool.name }}<span v-if="spec.tool.d"> Ø{{ spec.tool.d }}</span></div>
            <div v-for="f in cutFields" :key="f.k" class="kv small" :class="{ changed: changed(f.k) }"><span>{{ f.label }}</span>
              <span><input v-model.number="spec.cut[f.k]" type="number" :step="f.step"> {{ f.unit }}</span>
              <span class="src">{{ changed(f.k) ? '手改（工艺规程是 ' + orig.cut[f.k] + '，提交审批时会提示）' : spec.sources?.['cut.' + f.k] }}</span></div>
          </div>
          <label class="small">名称 <input v-model.trim="title" class="full" maxlength="80"></label>
          <button class="btn primary big-w" :disabled="generating || busy" @click="generate">{{ generating ? '正在生成、仿真…' : '生成程序并仿真' }}</button>
        </template>
        <div v-if="err" class="err small">{{ err }}</div>
      </section>

      <section class="card grow">
        <div class="card-head"><h2>{{ job ? (job.title || '结果') : '结果' }}</h2>
          <div v-if="job?.programs?.length > 1" class="seg tabs">
            <button v-for="(p, k) in job.programs" :key="k" type="button" :class="{ on: pk === k }" @click="pick(k)">O{{ p.number }} {{ p.title }}</button>
          </div>
          <template v-if="prog"><button class="btn ghost" @click="download">下载程序 O{{ prog.number }}</button></template>
        </div>
        <div v-if="!job" class="empty big-empty">左边选一道工序（或示例、上传的零件），排好编程单，点“生成程序并仿真”。</div>
        <div v-else-if="job.status === 'failed'" class="jobbar failed">没生成成：{{ job.error }}</div>
        <template v-else-if="prog">
          <CamLathe v-if="isLathe" :prog="prog" :time="time" />
          <CamMill v-else :prog="prog" :stock="job.spec.stock" :time="time" :final="final" />
          <div class="player">
            <button class="btn ghost" @click="toggle">{{ playing ? '暂停' : '播放' }}</button>
            <input v-model.number="time" type="range" :min="0" :max="tmax" step="0.01" aria-label="加工时间">
            <span class="mono small">{{ fmtMin(time) }} / {{ fmtMin(tmax) }}</span>
            <select v-model.number="speed" class="small"><option :value="5">5×</option><option :value="20">20×</option><option :value="60">60×</option><option :value="200">200×</option></select>
          </div>

          <div class="cards">
            <div class="kpi"><div class="muted small">加工时间（本程序）</div><div class="big">{{ fmtMin(prog.time.total_s) }}</div>
              <div class="small muted">切削 {{ fmtMin(prog.time.cut_s) }} · 快移 {{ fmtMin(prog.time.rapid_s) }} · 换刀 {{ prog.time.tool_changes }} 次 {{ fmtMin(prog.time.tool_s) }}</div></div>
            <div v-if="job.compare" class="kpi"><div class="muted small">与工艺规程比</div>
              <div class="big">{{ job.compare.program_minutes }} 分</div>
              <div class="small muted">全部程序合计<span v-if="job.compare.plan_minutes">；工艺规程工时 {{ job.compare.plan_minutes }} 分（含装夹、测量等辅助时间）</span>
                <span v-if="job.compare.basic_minutes">；按工艺规程公式的基本时间 {{ job.compare.basic_minutes }} 分</span></div></div>
            <div class="kpi" :class="simTone"><div class="muted small">仿真比对</div>
              <div class="big">{{ simHead }}</div><div class="small muted">{{ simNote }}</div></div>
            <div class="kpi"><div class="muted small">程序</div><div class="big">{{ prog.lines }} 行</div>
              <div class="small muted">实际最大切深 {{ prog.sim.ap_max }} mm<span v-if="prog.rpm"> · S{{ prog.rpm }} F{{ prog.feed }}</span></div>
              <div v-if="prog.power" class="small muted" :title="`Kienzle：${prog.power.material_row}，kc1.1 = ${prog.power.kc11_MPa} MPa，mc = ${prog.power.mc}（${prog.power.table}）`">
                切削功率 {{ prog.power.items.map((x) => x.name.split(' ')[0] + ' ' + x.need_kw.toFixed(1)).join('、') }} kW（含效率）/ 机床 {{ prog.power.machine_kw }} kW</div></div>
          </div>
          <div class="checks">
            <div v-if="!prog.checks.length" class="okline small">✓ 检查通过：没有超程、超速、功率超限、快移撞工件、过切</div>
            <div v-for="(c, i) in prog.checks" :key="i" class="small" :class="c.level === 'error' ? 'err' : 'warnline'">
              {{ c.level === 'error' ? '✗' : '!' }} <a v-if="c.line" href="#" @click.prevent="jump(c.line)">第 {{ c.line }} 行</a> {{ c.text }}</div>
          </div>
          <div v-if="job.spec?.op" class="release">
            <div><b>下发</b> <span class="small muted">程序挂到工艺规程工序 {{ job.spec.op.seq }} 上，走工艺规程的“提交 → 审批 → 生效”；生效后 ERPNext 物料附上程序，车间派工时随这道工序发给机床，3D 车间可以回放。</span></div>
            <template v-if="!sub">
              <div class="line"><input v-model.trim="subNote" class="full grow1" maxlength="200" placeholder="提交说明（可不填）">
                <button class="btn primary" :disabled="subBusy || hasErrors" @click="submitPlan">{{ subBusy ? '正在提交…' : '挂到工艺规程并提交审批' }}</button></div>
              <div v-if="hasErrors" class="small err">检查还有错误，改好再提交。</div>
              <div v-if="err" class="small err">{{ err }}</div>
            </template>
            <template v-else>
              <div class="line small"><span class="pill" :class="SUB_TONE[sub.status]">{{ SUB_NAME[sub.status] }}</span>
                <span>{{ sub.note }}</span></div>
              <div v-for="c in sub.comments" :key="c.id" class="cmt small">
                <label><input type="checkbox" :checked="c.resolved" :disabled="sub.status !== 'pending'" @change="resolve(c, $event.target.checked)"> 已处理</label>
                <span><b>{{ c.author }}</b>：{{ c.body }}</span></div>
              <template v-if="sub.status === 'pending' && canApprove">
                <div class="line"><input v-model.trim="decisionNote" class="full grow1" maxlength="200" placeholder="审批意见（退回时必填）">
                  <button class="btn primary" :disabled="subBusy" @click="decide('approve')">批准生效</button>
                  <button class="btn ghost" :disabled="subBusy" @click="decide('reject')">退回</button></div>
              </template>
              <div v-else-if="sub.status === 'pending'" class="small muted">等老师或审批人批准（不能批准自己的提交）。</div>
              <div v-if="sub.status === 'approved'" class="okline small">✓ 已生效：工艺规程第 {{ sub.revision }} 版{{ released !== null ? '，这一版挂着的 ' + released + ' 个程序已下发' : '' }}。
                <router-link :to="{ path: '/3d', query: { unit: job.spec.kind === 'turn' ? 'cnc-l01-a' : 'key-01' } }">到 3D 车间回放 →</router-link></div>
              <div v-if="sub.status === 'rejected'" class="small err">退回：{{ sub.decision }}——改好后重新生成、再提交。</div>
              <div v-if="err" class="small err">{{ err }}</div>
            </template>
          </div>
          <div class="explain">
            <div class="line"><b>AI 讲解程序</b>
              <button class="btn ghost" :disabled="expBusy" @click="explain">{{ expBusy ? 'AI 正在读程序…' : (exp ? '重新讲解' : '请 AI 逐段讲解这个程序') }}</button>
              <span v-if="exp" class="small muted">{{ exp.engine === 'rules' ? '规则讲解（没配模型）' : '模型：' + exp.engine }}</span></div>
            <template v-if="exp">
              <div v-for="(b, i) in exp.blocks" :key="i" class="blk small" :class="{ on: curLine >= b.from && curLine <= b.to }">
                <a href="#" class="mono" @click.prevent="jump(b.from)">第 {{ b.from }}{{ b.to > b.from ? '–' + b.to : '' }} 行</a> {{ b.text }}</div>
              <div v-if="exp.risks.length" class="small"><b>上机前注意</b>
                <div v-for="(r, i) in exp.risks" :key="i" class="warnline">! {{ r }}</div></div>
            </template>
          </div>
          <div class="gcode">
            <div class="small muted">G 代码（回放时高亮当前行；点一行跳到那里）</div>
            <pre ref="pre" class="mono small"><span v-for="(l, i) in ncLines" :key="i" :class="{ cur: i + 1 === curLine }" @click="jump(i + 1)">{{ String(i + 1).padStart(4, ' ') }}  {{ l }}</span></pre>
          </div>
        </template>
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>{{ teacher ? '本厂的编程记录' : '我的编程记录' }}</h2></div>
      <div v-if="!jobs.length" class="empty">还没有编程记录。</div>
      <table v-else class="t">
        <thead><tr><th>名称</th><th>零件 / 工序</th><th v-if="teacher">编程人</th><th>时间</th><th class="num">程序合计 分</th><th>检查</th><th></th></tr></thead>
        <tbody><tr v-for="j in jobs" :key="j.id">
          <td>{{ j.title || '—' }}</td><td>{{ j.item }} {{ j.op ? j.op.seq + ' ' + j.op.name : KIND[j.kind] }}</td><td v-if="teacher">{{ j.owner_name }}</td>
          <td class="small">{{ new Date(j.created * 1000).toLocaleString('zh-CN', { hour12: false }) }}</td>
          <td class="num">{{ j.compare?.program_minutes ?? '' }}</td>
          <td><span class="pill" :class="j.status !== 'done' ? 'bad' : (j.stats?.errors ? 'bad' : 'good')">{{ j.status !== 'done' ? '失败' : (j.stats?.errors ? j.stats.errors + ' 个问题' : '通过') }}</span></td>
          <td><a v-if="j.status === 'done'" href="#" @click.prevent="openJob(j.id)">看结果 →</a></td>
        </tr></tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { get, post, session, ApiError } from '../lib/api';
import { fetchHeight, fetchNc, fmtMin, toolAt } from '../lib/cam';
import CamLathe from '../components/CamLathe.vue';
import CamMill from '../components/CamMill.vue';

const SRC = [{ k: 'plan', label: '按工艺规程' }, { k: 'example', label: '示例零件' }, { k: 'upload', label: '上传 STEP' }];
const KIND = { turn: '数控车', slot: '铣键槽', mill25: '2.5 轴铣' };
const MODE = { rough: '粗车', finish: '精车' };
const OPN = { contour: '外轮廓', pocket: '型腔', drill: '钻孔' };
const AI_HINT = {
  turn: '一句话改参数，例如“每刀 2.5，留 0.3 精车余量，限速 2500”“线速度 150，进给 0.12”“只车右端”',
  slot: '一句话改参数，例如“分 5 层，每齿 0.04”“转速 800”',
  mill25: '一句话改参数，例如“型腔用 Ø8 的刀，行距 40%，每层 3”“啄钻每次 5”',
};
const SLOT_F = [{ k: 'width', label: '槽宽' }, { k: 'length', label: '槽长' }, { k: 'depth', label: '槽深（从外圆最高点）' }];
const CUT = {
  turn: [{ k: 'vc', label: '切削速度 vc', unit: 'm/min', step: 5 }, { k: 'f', label: '进给量 f', unit: 'mm/r', step: 0.01 },
    { k: 'ap', label: '每刀切深 ap', unit: 'mm', step: 0.1 }, { k: 'max_rpm', label: '限速 G50', unit: 'r/min', step: 100 },
    { k: 'axial_allow', label: '轴肩留余量', unit: 'mm', step: 0.05 }, { k: 'radial_allow', label: '外圆再留（单边）', unit: 'mm', step: 0.05 }],
  slot: [{ k: 'vc', label: '切削速度 vc', unit: 'm/min', step: 1 }, { k: 'fz', label: '每齿进给 fz', unit: 'mm', step: 0.005 },
    { k: 'z', label: '齿数', unit: '', step: 1 }, { k: 'ap', label: '每层切深', unit: 'mm', step: 0.1 }],
};

const teacher = computed(() => !!session.user?.teacher);
const src = ref('plan');
const parts = ref([]), examples = ref([]), machines = ref({});
const item = ref('SH-301'), opsInfo = ref(null), seq = ref(null);
const file = ref(null), upKind = ref('mill'), upMat = ref('45'), upSeq = ref(10);
const spec = ref(null), orig = ref(null), title = ref(''), showProf = ref(false);
const busy = ref(false), generating = ref(false), err = ref('');
const job = ref(null), jobs = ref([]), pk = ref(0), nc = ref(''), final = ref(null);
const time = ref(0), playing = ref(false), speed = ref(20);
const pre = ref(null);
const aiText = ref(''), aiBusy = ref(false), aiRes = ref(null);
const exp = ref(null), expBusy = ref(false);
const SUB_NAME = { pending: '待审', approved: '已生效', rejected: '已退回' };
const SUB_TONE = { pending: 'info', approved: 'good', rejected: 'bad' };
const sub = ref(null), subNote = ref(''), subBusy = ref(false), decisionNote = ref(''), released = ref(null);
const canApprove = computed(() => !!session.user?.teacher || ['approver', 'manager'].includes(session.user?.role));
const hasErrors = computed(() => (job.value?.programs || []).some((p) => p.checks.some((c) => c.level === 'error')));
let raf = 0;

const prog = computed(() => job.value?.programs?.[pk.value] || null);
const isLathe = computed(() => job.value?.spec?.kind === 'turn');
const tmax = computed(() => (prog.value ? prog.value.path[prog.value.path.length - 1][5] : 0));
const ncLines = computed(() => nc.value.split('\n').filter((l, i, a) => i < a.length - 1 || l));
const curLine = computed(() => (prog.value ? toolAt(prog.value.path, time.value).p?.[4] : 0));
const cutFields = computed(() => CUT[spec.value?.kind] || []);
const stockText = computed(() => {
  const s = spec.value?.stock; if (!s) return '';
  return s.kind === 'bar' ? `圆钢 Ø${s.d} × ${s.length}` : `上一道工序（${s.from_seq || ''}）车好的形状，总长 ${s.length}`;
});
const changed = (k) => orig.value && orig.value.cut && spec.value.cut[k] !== orig.value.cut[k];
const simTone = computed(() => {
  const s = prog.value?.sim; if (!s) return '';
  return (s.over || s.dev_min < -0.01) ? 'bad' : 'good';
});
const simHead = computed(() => {
  const s = prog.value?.sim; if (!s) return '';
  if (s.over || s.dev_min < -0.01) return '有过切';
  if (isLathe.value) return `差 ${Math.max(Math.abs(s.dev_min), s.dev_max).toFixed(3)} mm`;
  return s.under ? `残留 ${s.under} 格` : '与目标一致';
});
const simNote = computed(() => {
  const s = prog.value?.sim; if (!s) return '';
  if (isLathe.value) return `本次装夹车到的长度上，仿真轮廓与本工序尺寸（半径）比：最多切少 ${s.dev_max} mm、最多切多 ${Math.max(0, -s.dev_min)} mm；端面${s.face_left > 0 ? '没车净' : '车净'}`;
  return `高度图每格 ${s.h.toFixed(2)} mm；过切 ${s.over} 格；没铣到 ${s.under ?? 0} 格（型腔尖角处刀具铣不到的地方会算在这里）`;
});

watch(item, loadOps);
watch(prog, async (p) => {
  time.value = 0; playing.value = false; nc.value = ''; final.value = null;
  if (!p) return;
  try {
    nc.value = await fetchNc(job.value.id, pk.value);
    if (p.sim.height) final.value = await fetchHeight(job.value.id, pk.value);
  } catch (e) { err.value = e.message; }
  time.value = tmax.value;                                 // 先看最终结果
});
watch(curLine, async (l) => {
  if (!playing.value || !pre.value || !l) return;
  await nextTick();
  const el = pre.value.children[l - 1];
  if (el) pre.value.scrollTop = el.offsetTop - pre.value.offsetTop - pre.value.clientHeight / 2;
});

async function loadOps() {
  opsInfo.value = null; seq.value = null;
  if (!item.value) return;
  try {
    opsInfo.value = await get('/cam/ops?item=' + encodeURIComponent(item.value));
    seq.value = opsInfo.value.ops.find((o) => o.cam)?.seq ?? null;
  } catch (e) { err.value = e.message; }
}
function setSpec(s, name) {
  aiRes.value = null;
  spec.value = s; orig.value = JSON.parse(JSON.stringify(s));
  title.value = name || `${s.item || ''} ${s.op ? s.op.seq + ' ' + s.op.name.split(' ')[0] : KIND[s.kind]}`.trim();
}
async function loadSpec() {
  busy.value = true; err.value = '';
  try { setSpec(await post('/cam/spec', { item: item.value, seq: seq.value })); } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
async function loadExample() {
  busy.value = true; err.value = '';
  try {
    const ex = await post('/cam/examples/WQ-PLATE');
    setSpec(await post('/cam/spec/geometry', { sha: ex.sha, kind: 'mill', material: '45', name: ex.name }), '示例平板 铣削');
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
function pickFile(ev) { file.value = ev.target.files[0] || null; }
async function loadUpload() {
  busy.value = true; err.value = '';
  try {
    const fd = new FormData(); fd.append('step', file.value);
    const res = await fetch('/api/cae/geometry/upload', { method: 'POST', headers: { 'x-wq-token': session.token }, body: fd });
    const g = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(res.status, g.detail || '读不了这个 STEP');
    const name = file.value.name.replace(/\.(step|stp)$/i, '');
    setSpec(await post('/cam/spec/geometry', { sha: g.sha, kind: upKind.value, material: upMat.value, seq: upSeq.value, name }), name);
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
async function generate() {
  if (spec.value.kind === 'turn' && !(spec.value.setups || []).length) { err.value = '至少选一次装夹（右端或左端）'; return; }
  generating.value = true; err.value = '';
  try {
    const j = await post('/cam/jobs', { spec: spec.value, title: title.value });
    if (j.status === 'failed') err.value = j.error;
    job.value = j; pk.value = 0;
    loadJobs();
  } catch (e) { err.value = e.message; } finally { generating.value = false; }
}
async function openJob(id) {
  err.value = '';
  try { job.value = await get('/cam/jobs/' + id); pk.value = 0; window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) { err.value = e.message; }
}
function pick(k) { pk.value = k; }
function jump(line) {
  const p = prog.value?.path; if (!p) return;
  const i = p.findIndex((x) => x[4] >= line);
  if (i >= 0) { playing.value = false; time.value = p[i][5]; }
}
function toggle() {
  playing.value = !playing.value;
  if (!playing.value) return;
  if (time.value >= tmax.value) time.value = 0;
  let last = performance.now();
  const step = (now) => {
    if (!playing.value) return;
    time.value = Math.min(tmax.value, time.value + (now - last) / 1000 * speed.value);
    last = now;
    if (time.value >= tmax.value) { playing.value = false; return; }
    raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
}
function download() {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([nc.value], { type: 'text/plain' }));
  a.download = `O${prog.value.number}-${job.value.item || 'program'}.nc`;
  document.body.appendChild(a); a.click(); a.remove();
}
function setPath(obj, keys, v) {
  let o = obj;
  for (const k of keys.slice(0, -1)) { if (o[k] === undefined) return; o = o[k]; }
  o[keys[keys.length - 1]] = v;
}
async function aiFill() {
  aiBusy.value = true; err.value = '';
  try {
    const r = await post('/cam/ai-setup', { text: aiText.value, spec: spec.value });
    for (const p of r.patch) {
      if (p.path === 'setups') { spec.value.setups = p.value; continue; }
      if (p.path.startsWith('ops.')) {
        const [, sel, ...rest] = p.path.split('.');
        for (const o of spec.value.ops) {
          if (sel !== '*' && o.type !== sel) continue;
          if (sel === '*' && o.type === 'drill' && rest[1] !== 'vc') continue;     // 钻孔没有 fz、ap
          setPath(o, rest, p.value);
        }
      } else setPath(spec.value, p.path.split('.'), p.value);
    }
    aiRes.value = r;
  } catch (e) { err.value = e.message; } finally { aiBusy.value = false; }
}
async function explain() {
  expBusy.value = true; err.value = '';
  try { exp.value = await post(`/cam/jobs/${job.value.id}/explain`, { k: pk.value }); } catch (e) { err.value = e.message; } finally { expBusy.value = false; }
}
watch([job, pk], () => { exp.value = null; });
async function loadSub() {
  sub.value = null; released.value = null;
  if (job.value?.submission) {
    try { sub.value = await get('/process/submissions/' + job.value.submission); } catch (e) { /* 别的模式的提交 */ }
  }
}
watch(job, loadSub);
async function submitPlan() {
  subBusy.value = true; err.value = '';
  try {
    const r = await post(`/cam/jobs/${job.value.id}/submit`, { note: subNote.value });
    job.value = { ...job.value, submission: r.submission };
  } catch (e) { err.value = e.message; } finally { subBusy.value = false; }
}
async function resolve(c, v) {
  try { sub.value = await post(`/process/submissions/${sub.value.id}/comments/${c.id}`, { resolved: v }); } catch (e) { err.value = e.message; }
}
async function decide(d) {
  subBusy.value = true; err.value = '';
  try {
    const r = await post(`/process/submissions/${sub.value.id}/decision`, { decision: d, note: decisionNote.value });
    sub.value = r; released.value = r.programs_released ?? null;
  } catch (e) { err.value = e.message; } finally { subBusy.value = false; }
}
async function loadJobs() { try { jobs.value = (await get('/cam/jobs')).jobs; } catch (e) { /* */ } }

onMounted(async () => {
  try {
    const [p, m] = await Promise.all([get('/cam/parts'), get('/cam/machines')]);
    parts.value = p.items.filter((i) => i.has_plan); examples.value = p.examples; machines.value = m.machines;
    if (!parts.value.find((i) => i.item === item.value)) item.value = parts.value[0]?.item || '';
    loadOps();
  } catch (e) { err.value = e.status === 503 ? '计算服务暂时连不上，请稍后再试' : e.message; }
  loadJobs();
});
onUnmounted(() => { cancelAnimationFrame(raf); playing.value = false; });
</script>

<style scoped>
.side { width: 400px; flex-shrink: 0; display: flex; flex-direction: column; gap: 9px; align-self: flex-start; }
.grow { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.step { display: flex; align-items: center; gap: 8px; font-weight: 600; margin-top: 6px; }
.step b { width: 22px; height: 22px; border-radius: 50%; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; align-self: flex-start; flex-wrap: wrap; }
.seg button { border: 0; background: #fff; padding: 6px 12px; cursor: pointer; font-size: 13px; }
.seg button.on { background: var(--accent-bg); font-weight: 600; }
.tabs { margin-left: 8px; }
.full { width: 100%; height: 34px; border: 1px solid #C8CEC7; border-radius: 6px; padding: 0 8px; background: #fff; }
.ops { display: flex; flex-direction: column; gap: 3px; }
.op { display: flex; gap: 8px; align-items: center; border: 1px solid var(--line); border-radius: 7px; padding: 5px 8px; cursor: pointer; }
.op.on { border-color: var(--accent); background: var(--accent-bg); }
.op.dis { opacity: 0.5; cursor: default; }
.grow1 { flex: 1; }
.upload { display: flex; flex-direction: column; gap: 4px; color: var(--muted); }
.line { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.kv { display: grid; grid-template-columns: 110px 150px 1fr; gap: 6px; align-items: center; }
.kv.changed .src { color: var(--warn-ink); }
.src { color: var(--muted); font-size: 11px; line-height: 1.3; }
.cut { display: flex; flex-direction: column; gap: 4px; border-top: 1px solid var(--line); padding-top: 6px; }
.prof { background: var(--surface-2); border-radius: 6px; padding: 6px; word-break: break-all; }
.jrow { border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; display: flex; flex-direction: column; gap: 4px; }
.jctl { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: center; }
input[type=number] { width: 70px; height: 26px; border: 1px solid #C8CEC7; border-radius: 5px; padding: 0 4px; }
select { height: 26px; border: 1px solid #C8CEC7; border-radius: 5px; }
.big-w { height: 42px; font-size: 15px; margin-top: 6px; }
.card-head { flex-wrap: wrap; align-items: center; gap: 8px; }
.jobbar { border-radius: 8px; padding: 10px 14px; }
.jobbar.failed { background: var(--bad-bg); color: var(--bad); }
.big-empty { padding: 120px 0; text-align: center; }
.player { display: flex; align-items: center; gap: 10px; }
.player input[type=range] { flex: 1; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
.kpi { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; }
.kpi.bad { border-color: var(--bad); background: var(--bad-bg); }
.kpi.good .big { color: var(--good, #1B5E20); }
.big { font-size: 20px; font-weight: 600; margin: 2px 0; }
.checks { display: flex; flex-direction: column; gap: 2px; }
.okline { color: var(--good, #1B5E20); }
.warnline { color: var(--warn-ink); }
.ai-box { display: flex; flex-direction: column; gap: 6px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
.ai-box textarea { border: 1px solid #C8CEC7; border-radius: 6px; padding: 6px 8px; resize: vertical; }
.explain { border-top: 1px solid var(--line); padding-top: 8px; display: flex; flex-direction: column; gap: 4px; }
.blk { padding: 4px 6px; border-radius: 6px; line-height: 1.6; }
.blk.on { background: var(--accent-bg); }
.release { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; background: var(--surface-2); }
.cmt { display: flex; gap: 8px; align-items: flex-start; }
.cmt label { white-space: nowrap; }
.gcode pre { max-height: 300px; overflow: auto; background: #1E2420; color: #D8E0D8; border-radius: 8px; padding: 8px; margin: 4px 0 0; line-height: 1.45; }
.gcode pre span { cursor: pointer; display: block; white-space: pre; }
.gcode pre span.cur { background: #3D5A40; color: #fff; }
@media (max-width: 1100px) { .side { width: 100%; } }
</style>
