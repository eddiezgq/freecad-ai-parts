<template>
  <div class="page lib">
    <div class="head">
      <h1>{{ t('零件与机器人库') }}</h1>
      <span class="src mono" v-if="index">
        library-v{{ index.version }} · {{ t('{a} 个标准件族 / {s} 个规格 · {b} 个机器人', { a: counts.A, s: counts.Asizes, b: counts.B }) }}
        <template v-for="c in index.collections" :key="c.id"> · {{ zhen(c.name) }} {{ t('{n} 个（只含索引）', { n: c.count }) }}</template>
      </span>
    </div>

    <div v-if="error" class="card empty">{{ error }}</div>
    <template v-else-if="index">
      <section class="card">
        <label class="lbl" for="q">{{ t('检索：名称、编号、标准号、规格、工厂物料号') }}</label>
        <div class="field-row">
          <input id="q" v-model="q" type="search" :placeholder="t('如 6207、GB/T 1096、M8x25、UR5e、humanoid')" autocomplete="off">
          <button class="btn ghost" type="button" @click="q = ''">{{ t('清除') }}</button>
        </div>
        <label class="lbl ai-lbl" for="ask">{{ t('AI 选型：一句话说需求，只从零件库里挑') }}</label>
        <form class="field-row" @submit.prevent="ask">
          <input id="ask" v-model="askQ" type="text" :placeholder="t('如：35 mm 轴、1450 r/min、径向载荷为主用什么轴承')" autocomplete="off" maxlength="500">
          <button class="btn primary" type="submit" :disabled="asking || !askQ.trim()">{{ asking ? t('正在查库…') : t('选型') }}</button>
        </form>
        <div v-if="askErr" class="small err">{{ askErr }}</div>
        <div v-if="askRes" class="ai-res">
          <p class="ai-text">{{ td(askRes.answer) }}</p>
          <div v-if="askRes.refs.length" class="ai-refs">
            <button v-for="r in askRes.refs" :key="r.ref" type="button" class="chip mono" @click="openRef(r)" :title="r.name">{{ r.ref }}</button>
          </div>
          <p class="small muted">{{ askRes.engine === 'rules' ? t('规则匹配（未配 AI 模型）') : t('由 {e} 回答', { e: askRes.engine }) }}{{ t('；只推荐零件库 v{v} 里有的规格，答案里的编号已逐个核对', { v: askRes.library_version }) }}<template v-if="askRes.invalid_refs.length">{{ t('（去掉了库里没有的：{x}）', { x: askRes.invalid_refs.join(', ') }) }}</template>{{ t('。点编号打开详情；寿命、强度请按样本另行计算。') }}</p>
        </div>
      </section>

      <div class="tabs" role="tablist">
        <button v-for="t in tabs" :key="t.key" class="tab" :class="{ on: part === t.key }" role="tab" :aria-selected="part === t.key"
          type="button" @click="setPart(t.key)">{{ t.name }}<span class="n">{{ t.count }}</span></button>
      </div>

      <section class="work">
        <aside class="filters card" :aria-label="t('筛选')">
          <template v-if="part !== 'F'">
            <div><h3>{{ t('类别') }}</h3>
              <label v-for="c in catList" :key="c.key"><input type="checkbox" :checked="cats.has(c.key)" @change="toggle(cats, c.key)">
                {{ c.name }}<span class="c">{{ c.count }}</span></label>
            </div>
            <div><h3>{{ t('来源') }}</h3>
              <label v-for="s in srcList" :key="s.key"><input type="checkbox" :checked="srcs.has(s.key)" @change="toggle(srcs, s.key)">
                {{ s.name }}<span class="c">{{ s.count }}</span></label>
            </div>
            <div><h3>{{ t('用途') }}</h3>
              <label><input type="checkbox" v-model="wqr"> {{ t('WQR-105 用到') }}</label>
            </div>
          </template>
          <template v-else>
            <div><h3>{{ t('分类') }}</h3>
              <label v-for="c in fcCats" :key="c.key"><input type="checkbox" :checked="fcSel.has(c.key)" @change="toggle(fcSel, c.key)">
                {{ c.name }}<span class="c">{{ c.count }}</span></label>
            </div>
            <p class="small muted">{{ t('FreeCAD 零件库（CC BY 3.0）只收索引和缩略图；模型点击后从原仓库下载，使用时请署名。') }}</p>
          </template>
        </aside>

        <div>
          <div class="grid" aria-live="polite">
            <template v-if="part !== 'F'">
              <button v-for="f in shown" :key="f.id" class="item" :class="{ on: sel === f.id }" type="button" @click="select(f.id)">
                <span class="thumb"><img :src="fileUrl(f.thumb)" alt="" loading="lazy"></span>
                <span class="meta">
                  <span class="id">{{ f.id }}</span><b>{{ zhen(f.name) }}</b>
                  <span class="std">{{ f.line }}</span>
                  <span class="pills"><span class="pill good">{{ f.license }}</span>
                    <span v-if="f.wqr" class="pill task">WQR-105</span></span>
                </span>
              </button>
            </template>
            <template v-else>
              <button v-for="f in shown" :key="f.id" class="item" :class="{ on: sel === f.id }" type="button" @click="sel = f.id">
                <span class="thumb"><img v-if="f.thumb" :src="fileUrl(f.thumb)" alt="" loading="lazy"><span v-else class="muted small">{{ t('无缩略图') }}</span></span>
                <span class="meta"><b>{{ f.name }}</b><span class="std">{{ f.path.slice(1).join(' / ') }}</span>
                  <span class="pills"><span class="pill info">{{ zhen(f.top) }}</span></span></span>
              </button>
            </template>
          </div>
          <div v-if="!shown.length" class="empty">{{ t('没有符合条件的条目。试试清除检索词或筛选。') }}</div>
          <div v-if="more > 0" class="more-row"><button class="btn ghost" type="button" @click="limit += 120">{{ t('再显示 {n} 个（还有 {m} 个）', { n: Math.min(more, 120), m: more }) }}</button></div>
        </div>

        <article class="card detail" :aria-label="t('条目详情')">
          <template v-if="part === 'F' && fcItem">
            <div class="d-head"><div class="src mono">FreeCAD-library · {{ fcItem.path.join(' / ') }}</div><h2>{{ fcItem.name }}</h2></div>
            <div class="viewer flat"><img v-if="fcItem.thumb" :src="fileUrl(fcItem.thumb)" alt=""><span v-else class="muted">{{ t('没有缩略图') }}</span></div>
            <div class="actions">
              <a v-for="(u, k) in fcItem.formats" :key="k" class="btn" :class="{ primary: k === 'step' }" :href="u" target="_blank" rel="noopener">{{ t('下载') }} {{ k.toUpperCase() }}</a>
              <a class="btn ghost" :href="fcItem.source_url" target="_blank" rel="noopener">{{ t('原仓库页面') }}</a>
            </div>
            <div class="dbody"><div class="attr">{{ fc.attribution }}<br>{{ zhen(fc.note) }}</div></div>
          </template>
          <template v-else-if="entry">
            <div class="d-head">
              <div class="src mono">{{ entry.id }}<template v-if="size !== 'default'"> / {{ size }}</template></div>
              <h2>{{ zhen(entry.name) }}{{ size !== 'default' ? ' ' + size : '' }}</h2>
              <div v-if="!isEn()" class="small muted">{{ entry.name.en }}</div>
              <div v-if="entry.source.origin === 'vendor' && entry.model.note" class="small proxy-note">{{ td(entry.model.note) }}</div>
            </div>
            <div class="viewer" ref="viewerEl">
              <div class="v-tools" v-if="entry.robot || entry.mechanism || canExplode">
                <button v-if="canExplode" class="btn ghost" type="button" @click="toggleExplode">{{ exploded ? t('装回') : t('拆开') }}</button>
                <button v-if="entry.mechanism?.motion" class="btn ghost" type="button" @click="toggleMotion"
                  :title="zhen(entry.mechanism.input?.path)">{{ playing ? t('停止') : t('播放运动') }}</button>
                <button v-if="entry.robot && !entry.robot.parallel" class="btn ghost" type="button" @click="resetJoints('zero')">{{ t('零位') }}</button>
                <button v-if="entry.robot?.rest && !entry.robot.parallel" class="btn ghost" type="button" @click="resetJoints('init')"
                  :title="t('取自模型的关键帧 ') + (entry.robot.rest_source || '')">{{ t('初始姿态') }}</button>
              </div>
              <div class="v-note">{{ viewNote }}</div>
            </div>
            <p v-if="entry.robot?.parallel" class="small muted pad-x">{{ t('并联机构是闭链，只拖主动臂不能保持闭合；点“播放运动”看{x}。', { x: zhen(entry.mechanism?.input?.path) || t('运动') }) }}</p>
            <div v-if="entry.robot && !entry.robot.parallel && joints.length" class="joints">
              <label v-for="j in joints" :key="j.name" :title="j.name">
                <span class="jn mono">{{ j.short }}</span>
                <input type="range" :min="j.min" :max="j.max" :step="(j.max - j.min) / 400" v-model.number="j.value" @input="applyJoint(j)">
                <span class="v">{{ j.type === 'prismatic' ? (j.value * 1000).toFixed(0) + ' mm' : (j.value * 180 / Math.PI).toFixed(0) + '°' }}</span>
              </label>
            </div>
            <div class="actions">
              <a class="btn primary" :href="fileUrl(curSize?.files.glb)" download>{{ t('glTF（米）') }}</a>
              <a v-if="curSize?.files.urdf" class="btn" :href="fileUrl(curSize.files.urdf)" download>URDF</a>
              <a v-if="curSize?.files.motion" class="btn ghost" :href="fileUrl(curSize.files.motion)" download>{{ t('运动表 CSV') }}</a>
              <a v-if="curSize?.files.svg" class="btn ghost" :href="fileUrl(curSize.files.svg)" download>{{ t('二维图 SVG') }}</a>
              <a v-if="!entry.robot && entry.kind !== 'mechanism'" class="btn" :href="entry.package">{{ t('STEP / STL 压缩包（整族）') }}</a>
              <a v-else-if="entry.model.engine.startsWith('menagerie:')" class="btn" :href="entry.package" target="_blank" rel="noopener">{{ t('原始模型 MJCF（{o}）', { o: originName(entry.source.origin) }) }}</a>
              <a v-else-if="entry.model.engine.startsWith('urdf:')" class="btn" :href="entry.package" target="_blank" rel="noopener">{{ t('原始模型 URDF（原仓库）') }}</a>
              <a v-else-if="entry.model.engine.startsWith('xacro:')" class="btn" :href="entry.package" target="_blank" rel="noopener">{{ t('原始模型 xacro（ROS-Industrial）') }}</a>
              <a v-else-if="entry.source.origin === 'vendor'" class="btn" :href="entry.package" target="_blank" rel="noopener">{{ t('官方技术参数表') }}</a>
              <a v-else class="btn ghost" :href="entry.package" target="_blank" rel="noopener">{{ t('生成程序') }}</a>
              <button class="btn ghost" type="button" @click="copy(size === 'default' ? entry.id : entry.id + '/' + size)">{{ t('复制编号') }}</button>
            </div>
            <div class="tabs dtabs">
              <button v-for="x in dtabList" :key="x" class="tab" :class="{ on: dtab === x }" type="button" @click="dtab = x">{{ t(x) }}</button>
            </div>
            <div class="dbody">
              <template v-if="dtab === tk('规格')">
                <input v-if="entry.sizes.length > 12" v-model="sq" class="sq" type="search" :placeholder="t('在规格里找，如 6207、M8')">
                <div class="tbl-wrap">
                  <table class="t">
                    <thead><tr><th>{{ t('规格') }}</th><th v-for="p in cols" :key="p.key">{{ zhen(p) }}</th><th>{{ t('工厂物料') }}</th></tr></thead>
                    <tbody>
                      <tr v-for="s in sizeRows" :key="s.size" :class="{ sel: s.size === size }" @click="pickSize(s.size)">
                        <td class="mono">{{ s.size }}</td>
                        <td v-for="p in cols" :key="p.key" class="num">{{ s.params[p.key] ?? '' }}</td>
                        <td class="mono small">{{ (erp[s.size] || []).join(' ') }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p v-if="entry.standards?.length" class="small muted">{{ t('标准：') }}{{ entry.standards.map((s) => s.code).join(' · ') }}</p>
              </template>
              <template v-else-if="dtab === tk('参数')">
                <dl class="kv wide">
                  <template v-for="(v, k) in entry.datasheet.values" :key="k">
                    <dt>{{ zhen(entry.datasheet.labels?.[k]) || k }}</dt>
                    <dd class="mono">{{ v }} {{ entry.datasheet.labels?.[k]?.unit || '' }}</dd>
                  </template>
                </dl>
                <p class="small muted">{{ entry.datasheet.vendor }} {{ entry.datasheet.model }} {{ t('官方技术参数，') }}
                  <a :href="entry.datasheet.src" target="_blank" rel="noopener">{{ t('出处') }}</a><template v-if="entry.datasheet.note"> · {{ td(entry.datasheet.note) }}</template></p>
                <div v-if="entry.datasheet.axes?.length" class="tbl-wrap"><table class="t">
                  <thead><tr><th>{{ t('轴') }}</th><th>{{ t('运动范围（°）') }}</th><th>{{ t('最大速度（°/s）') }}</th></tr></thead>
                  <tbody><tr v-for="a in entry.datasheet.axes" :key="a.axis">
                    <td>{{ a.axis }}</td>
                    <td class="mono">{{ a.range_deg ? `${a.range_deg[0]} ~ ${a.range_deg[1]}` : '—' }}</td>
                    <td class="mono">{{ a.speed_deg_s ?? '—' }}</td>
                  </tr></tbody>
                </table></div>
                <template v-if="entry.dh">
                  <div class="small muted" style="margin-top:8px">{{ t('DH 参数（{c}，米、弧度）', { c: entry.dh.convention }) }}</div>
                  <div class="tbl-wrap"><table class="t">
                    <thead><tr><th>{{ t('关节') }}</th><th>a</th><th>d</th><th>α</th><th>{{ t('最大速度') }}</th></tr></thead>
                    <tbody><tr v-for="(p, i) in entry.dh.params" :key="i"><td class="mono">{{ i + 1 }}</td>
                      <td class="num">{{ p[0] }}</td><td class="num">{{ p[1] }}</td><td class="num">{{ (p[2] * 180 / Math.PI).toFixed(0) }}°</td>
                      <td class="num">{{ entry.dh.speed_deg_s?.[i] ? entry.dh.speed_deg_s[i] + ' °/s' : '' }}</td></tr></tbody>
                  </table></div>
                </template>
              </template>
              <template v-else-if="dtab === tk('图纸')">
                <a :href="fileUrl(curSize.files.svg)" target="_blank" rel="noopener" :title="t('新窗口打开（可缩放、打印）')">
                  <img class="drawing" :src="fileUrl(curSize.files.svg)" :alt="zhen(entry.name) + ' ' + t('二维图')"></a>
                <p class="small muted">{{ entry.id.startsWith('A') ? t('主视图 + 俯视/侧视图，标总体尺寸，主要尺寸见标题栏上方') : entry.id.startsWith('B') ? t('关节示意图（零位）') : entry.id.startsWith('E') ? t('示意二维图（总体尺寸）') : t('机构运动简图（默认参数）') }}{{ t('；点图在新窗口打开。格式见《数字工厂资源接口约定》2.4。') }}</p>
              </template>
              <template v-else-if="dtab === tk('零件表')">
                <div class="tbl-wrap">
                  <table class="t">
                    <thead><tr><th>{{ t('序号') }}</th><th>{{ t('零件') }}</th><th>{{ t('作用') }}</th></tr></thead>
                    <tbody><tr v-for="p in entry.assembly.parts" :key="p.node">
                      <td class="mono">{{ p.number ?? '' }}</td><td><span class="swatch" :style="{ background: p.color }"></span>{{ p.name }}</td><td>{{ p.role }}</td>
                    </tr></tbody>
                  </table>
                </div>
                <p class="small muted">{{ t('E 部分的模型与教材插图、数字工厂用的是同一份（factory/digital/models3d）；点“拆开”按爆炸方向分开各零件。') }}</p>
              </template>
              <template v-else-if="dtab === tk('机构')">
                <div class="tbl-wrap">
                  <table class="t">
                    <thead><tr><th>{{ t('构件') }}</th><th>{{ t('节点') }}</th></tr></thead>
                    <tbody><tr v-for="m in entry.mechanism?.members || []" :key="m.id">
                      <td>{{ zhen(m.name) }}<template v-if="m.ground">{{ t('（固定）') }}</template><template v-if="m.id === entry.mechanism.input?.member">{{ t('（主动）') }}</template></td>
                      <td class="mono small">{{ m.node }}</td></tr></tbody>
                  </table>
                </div>
                <dl class="kv wide">
                  <template v-for="(v, k) in entry.defaults || {}" :key="k">
                    <dt>{{ zhen((entry.params || []).find((x) => x.key === k)) || k }}</dt>
                    <dd class="mono">{{ v }} {{ (entry.params || []).find((x) => x.key === k)?.unit || '' }}</dd>
                  </template>
                </dl>
                <p v-if="entry.mechanism?.analysis?.formula" class="small">{{ zhen(entry.mechanism.analysis.formula) }}</p>
                <p class="small muted">{{ t('{d} 个自由度；输入：', { d: entry.mechanism?.dof }) }}{{ zhen(entry.mechanism?.input?.path)
                  || (zhen((entry.mechanism?.members || []).find((m) => m.id === entry.mechanism?.input?.member)?.name) + ' ' + (entry.mechanism?.input?.range || []).join(' ~ ') + ' ' + (entry.mechanism?.input?.unit || '')) }}{{ t('。') }}
                  {{ t('点“播放运动”看运动；运动表格式见《数字工厂资源接口约定》2.4。') }}<template v-if="entry.mechanism?.note"> {{ zhen(entry.mechanism.note) }}</template></p>
              </template>
              <template v-else-if="dtab === tk('关节')">
                <div class="tbl-wrap">
                  <table class="t">
                    <thead><tr><th>{{ t('关节') }}</th><th>{{ t('类型') }}</th><th>{{ t('父 → 子') }}</th><th>{{ t('范围') }}</th></tr></thead>
                    <tbody><tr v-for="j in entry.robot.joints" :key="j.name">
                      <td class="mono">{{ j.name }}</td><td class="nw">{{ JT[j.type] ? t(JT[j.type]) : j.type }}<template v-if="j.mimic"> {{ t('（从动：跟随 {j} ×{m}）', { j: j.mimic.joint, m: j.mimic.multiplier }) }}</template></td><td class="small">{{ j.parent }} → {{ j.child }}</td>
                      <td class="num">{{ j.limit && j.limit.lower != null ? fmtLim(j) : t('不限') }}</td></tr></tbody>
                  </table>
                </div>
                <p class="small muted">{{ t('{d} 个自由度；连杆 {l} 个。字段见《数字工厂资源接口约定》R4。', { d: entry.robot.dof, l: entry.robot.links.length }) }}</p>
              </template>
              <template v-else-if="dtab === tk('教学')">
                <dl class="kv">
                  <template v-if="entry.teaching.principle"><dt>{{ t('原理') }}</dt><dd>{{ entry.teaching.principle }}</dd></template>
                  <template v-if="entry.teaching.uses"><dt>{{ t('用途') }}</dt><dd>{{ [].concat(entry.teaching.uses).map((u) => td(u)).join(isEn() ? '; ' : '；') }}</dd><!-- i18n-ok 中文分隔号 --></template>
                </dl>
              </template>
              <template v-else>
                <dl class="kv">
                  <dt>{{ t('来源') }}</dt><dd>{{ originName(entry.source.origin) }}<template v-if="entry.source.repo"> · <a :href="entry.package" target="_blank" rel="noopener">{{ t('原仓库') }}</a></template></dd>
                  <dt>{{ t('许可') }}</dt><dd>{{ entry.source.license }}</dd>
                  <dt v-if="entry.source.checked">{{ t('核对') }}</dt><dd v-if="entry.source.checked">{{ entry.source.checked.by }} · {{ entry.source.checked.on }}<template v-if="entry.source.checked.note"> · {{ entry.source.checked.note }}</template></dd>
                </dl>
                <div v-if="entry.source.attribution" class="attr">{{ entry.source.attribution }}</div>
                <div v-if="entry.alt_models?.length" class="dsrc">
                  <div class="small muted">{{ t('另有版本') }}</div>
                  <div v-for="m in entry.alt_models" :key="m.url" class="small">
                    <a :href="m.url" target="_blank" rel="noopener">{{ m.format.toUpperCase() }}</a> · {{ m.license }} · {{ m.via }}
                  </div>
                </div>
                <div v-if="entry.source.notes" class="attr">{{ entry.source.notes }}</div>
                <div v-if="entry.source.data_sources?.length" class="dsrc">
                  <div class="small muted">{{ t('尺寸与参数出处') }}</div>
                  <div v-for="d in entry.source.data_sources" :key="d.url" class="small">
                    <a :href="d.url" target="_blank" rel="noopener">{{ d.title }}</a> · {{ t('取用') }} {{ d.retrieved }}<span v-if="d.note" class="muted"> · {{ td(d.note) }}</span>
                  </div>
                </div>
              </template>
            </div>
          </template>
          <div v-else class="empty pad">{{ t('在左边选一个条目，这里显示三维模型、规格和下载。') }}</div>
        </article>
      </section>
    </template>
    <div v-else class="card empty">{{ t('正在读取零件库…') }}</div>
    <div v-if="toast" class="toast">{{ toast }}</div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { useRoute } from 'vue-router';
import { post } from '../lib/api.js';
import { isEn, t, td, tk, zhen } from '../lib/i18n';

const BASE = '/library/';
const ORIGINS = { bd_warehouse: 'bd_warehouse', wenquest: tk('问渠自建'), menagerie: 'MuJoCo Menagerie', vendor: tk('厂商目录'),
  robot_descriptions: 'robot_descriptions', ros_industrial: 'ROS-Industrial', 'freecad-library': 'FreeCAD-library' };
const JT = { revolute: tk('转动'), continuous: tk('转动（不限位）'), prismatic: tk('移动') };
const originName = (o) => (ORIGINS[o] ? t(ORIGINS[o]) : o);

const useRouteRef = useRoute();
const askQ = ref('');
const asking = ref(false);
const askErr = ref('');
const askRes = ref(null);
async function ask() {
  askErr.value = ''; asking.value = true;
  try { askRes.value = await post('/library/select', { question: askQ.value.trim() }); }
  catch (e) { askErr.value = e.message; askRes.value = null; }
  finally { asking.value = false; }
}
function openRef(r) {
  const f = families.value.find((x) => x.id === r.entry);
  if (!f) return;
  part.value = f.part;
  select(r.entry, r.size || '');
}
const index = ref(null);
const error = ref('');
const q = ref('');
const part = ref('A');
const cats = reactive(new Set());
const srcs = reactive(new Set());
const wqr = ref(false);
const sel = ref('');
const limit = ref(120);
const fc = ref(null);
const fcSel = reactive(new Set());
const entry = ref(null);
const size = ref('default');
const dtab = ref(tk('规格'));
const sq = ref('');
const toast = ref('');
const viewerEl = ref(null);
const viewNote = ref('');
const joints = ref([]);

const fileUrl = (p) => (p ? BASE + index.value.version + '/' + p : '');
function toggle(set, k) { set.has(k) ? set.delete(k) : set.add(k); limit.value = 120; }

// ---------------------------------------------------------------- 索引 → 条目（按族归并）
const families = computed(() => {
  if (!index.value) return [];
  const m = new Map();
  for (const it of index.value.items) {
    let f = m.get(it.id);
    if (!f) {
      f = { id: it.id, part: it.part, kind: it.kind, category: it.category, name: it.family || it.name, license: it.license,
        origin: it.origin, vendor: it.vendor, standards: it.standards, tags: it.tags, sizes: [], erp: [], thumb: null, dof: it.dof };
      m.set(it.id, f);
    }
    f.sizes.push(it.size);
    f.erp.push(...it.erp_items);
    if (it.default || !f.thumb) f.thumb = it.files.png;
  }
  return [...m.values()].map((f) => {
    const cat = catName(f.part, f.category);
    const who = f.vendor ? zhen(f.vendor) : '';
    const line = f.kind === 'robot' ? `${who ? who + ' · ' : ''}${cat} · ` + t('{n} 个关节', { n: f.dof ?? '?' })
      : `${who || f.standards.slice(0, 2).join(' · ') || cat} · ` + t('{n} 个规格', { n: f.sizes.length });
    const text = [f.id, f.name.zh, f.name.en, cat, who, f.vendor?.zh || '', f.vendor?.en || '', ...f.standards, ...f.tags, ...f.sizes, ...f.erp]
      .join(' ').toLowerCase();
    return { ...f, line, text, wqr: f.erp.length > 0 };
  });
});
const catName = (p, c) => zhen(index.value?.categories?.[p]?.[c]) || c;
const counts = computed(() => {
  const A = families.value.filter((f) => f.part === 'A');
  return { A: A.length, Asizes: A.reduce((n, f) => n + f.sizes.length, 0), B: families.value.filter((f) => f.part === 'B').length,
    C: families.value.filter((f) => f.part === 'C').length, D: families.value.filter((f) => f.part === 'D').length,
    E: families.value.filter((f) => f.part === 'E').length };
});
const tabs = computed(() => [
  { key: 'A', name: t('A 标准件'), count: counts.value.A },
  { key: 'B', name: t('B 机器人'), count: counts.value.B },
  ...(counts.value.C ? [{ key: 'C', name: t('C 机构'), count: counts.value.C }] : []),
  ...(counts.value.D ? [{ key: 'D', name: t('D 机器人零部件'), count: counts.value.D }] : []),
  ...(counts.value.E ? [{ key: 'E', name: t('E 工装夹具'), count: counts.value.E }] : []),
  ...(index.value?.collections || []).map((c) => ({ key: 'F', name: zhen(c.name), count: c.count })),
]);
const pool = computed(() => families.value.filter((f) => f.part === part.value));
const catList = computed(() => countBy(pool.value, (f) => f.category).map(([k, n]) => ({ key: k, name: catName(part.value, k), count: n })));
const srcList = computed(() => countBy(pool.value, (f) => f.origin).map(([k, n]) => ({ key: k, name: originName(k), count: n })));
function countBy(list, fn) {
  const m = new Map();
  for (const x of list) m.set(fn(x), (m.get(fn(x)) || 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}
const fcCats = computed(() => countBy(fc.value?.items || [], (i) => i.path[0]).map(([k, n]) => ({
  key: k, name: zhen((fc.value.items.find((i) => i.path[0] === k) || {}).top) || k, count: n })));

const filtered = computed(() => {
  const words = q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (part.value === 'F') {
    return (fc.value?.items || []).filter((i) => (!fcSel.size || fcSel.has(i.path[0]))
      && words.every((w) => (i.name + ' ' + i.path.join(' ')).toLowerCase().includes(w)));
  }
  return pool.value.filter((f) => (!cats.size || cats.has(f.category)) && (!srcs.size || srcs.has(f.origin))
    && (!wqr.value || f.wqr) && words.every((w) => f.text.includes(w)));
});
const shown = computed(() => filtered.value.slice(0, limit.value));
const more = computed(() => filtered.value.length - shown.value.length);
const fcItem = computed(() => (part.value === 'F' ? (fc.value?.items || []).find((i) => i.id === sel.value) : null));

async function setPart(p) {
  part.value = p; cats.clear(); srcs.clear(); limit.value = 120;
  if (p === 'F' && !fc.value) {
    const c = index.value.collections[0];
    fc.value = await getJson(BASE + index.value.version + '/' + c.url);
  }
  if (p !== 'F') { const first = filtered.value[0]; if (first && !families.value.some((f) => f.id === sel.value && f.part === p)) select(first.id); }
  else sel.value = '';
}

async function getJson(url) {
  const r = await fetch(url, { cache: url.endsWith('latest.json') ? 'no-cache' : 'default' });
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}

// ---------------------------------------------------------------- 条目详情
const curSize = computed(() => entry.value?.sizes.find((s) => s.size === size.value) || entry.value?.sizes[0]);
const cols = computed(() => (entry.value?.params || []).filter((p) => p.role === 'key' || p.role === 'perf').slice(0, 6));
const erp = computed(() => {
  const m = {};
  for (const x of entry.value?.factory?.erp_items || []) (m[String(x.size ?? 'default')] ||= []).push(x.item_code);
  return m;
});
const sizeRows = computed(() => {
  const w = sq.value.trim().toLowerCase();
  const rows = entry.value?.sizes || [];
  return w ? rows.filter((s) => s.size.toLowerCase().includes(w) || (erp.value[s.size] || []).join(' ').toLowerCase().includes(w)) : rows;
});
const dtabList = computed(() => {
  if (!entry.value) return [];
  return [...(entry.value.datasheet ? [tk('参数')] : []), entry.value.robot ? tk('关节') : entry.value.kind === 'mechanism' ? tk('机构') : tk('规格'), ...(entry.value.assembly?.parts?.length > 1 ? [tk('零件表')] : []), ...(curSize.value?.files?.svg ? [tk('图纸')] : []), ...(entry.value.teaching?.principle || entry.value.teaching?.uses ? [tk('教学')] : []), tk('来源')];
});

async function select(id, wantSize) {
  sel.value = id;
  sq.value = '';
  const f = families.value.find((x) => x.id === id);
  try {
    const e = await getJson(BASE + index.value.version + '/' + id + '/entry.json');
    if (sel.value !== id) return;
    entry.value = e;
    const want = (wantSize || q.value).trim().toLowerCase();
    const hit = e.sizes.find((s) => s.size.toLowerCase() === want);
    size.value = hit ? hit.size : (e.sizes.find((s) => s.size === String(e.default))?.size || e.sizes[0]?.size || 'default');
    dtab.value = e.datasheet ? tk('参数') : e.robot ? tk('关节') : e.kind === 'mechanism' ? tk('机构') : tk('规格');
    await nextTick();
    loadModel();
  } catch (err) {
    say(t('读取 {x} 失败：', { x: f?.id || id }) + err.message);
  }
}
function pickSize(s) { size.value = s; loadModel(); }
function fmtLim(j) {
  const l = j.limit;
  return j.type === 'prismatic' ? `${(l.lower * 1000).toFixed(0)} ~ ${(l.upper * 1000).toFixed(0)} mm`
    : `${(l.lower * 180 / Math.PI).toFixed(0)}° ~ ${(l.upper * 180 / Math.PI).toFixed(0)}°`;
}
function copy(s) { navigator.clipboard?.writeText(s).then(() => say(t('已复制 ') + s), () => say(s)); }
function say(t) { toast.value = t; clearTimeout(say.t); say.t = setTimeout(() => (toast.value = ''), 2800); }

// ---------------------------------------------------------------- 三维预览
let renderer, scene, camera, controls, model, raf, ro;
const loader = new GLTFLoader();
function initViewer() {
  if (renderer || !viewerEl.value) return;
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  viewerEl.value.prepend(renderer.domElement);
  scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a949c, 1.4));
  const d = new THREE.DirectionalLight(0xffffff, 1.6); d.position.set(2, 3, 4); scene.add(d);
  camera = new THREE.PerspectiveCamera(35, 1, 0.001, 100);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  ro = new ResizeObserver(resize); ro.observe(viewerEl.value);
  resize();
  const loop = () => { controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(loop); };
  loop();
}
function resize() {
  if (!renderer || !viewerEl.value) return;
  const { clientWidth: w, clientHeight: h } = viewerEl.value;
  renderer.setSize(w, h); camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix();
}
// 运动表（R5）：每行各活动构件在机构坐标系下的位姿，按行循环播放
const playing = ref(false);
let motion = null, motionTimer = null;
async function toggleMotion() {
  if (playing.value) { stopMotion(); return; }
  if (!model || !curSize.value?.files.motion) return;
  if (!motion || motion.id !== entry.value.id) {
    const text = await (await fetch(fileUrl(curSize.value.files.motion))).text();
    const lines = text.trim().split(/\r?\n/);
    const head = lines[0].split(',');
    motion = { id: entry.value.id, head, rows: lines.slice(1).map((l) => l.split(',').map(Number)) };
  }
  const ids = [...new Set(motion.head.slice(1).map((h) => h.split('.')[0]))];
  const nodes = Object.fromEntries(ids.map((id) => {
    const m = entry.value.mechanism.members.find((x) => x.id === id);
    return [id, model.getObjectByName(THREE.PropertyBinding.sanitizeNodeName(m?.node || id))];
  }));
  const col = (id, k) => motion.head.indexOf(id + '.' + k);
  let i = 0;
  playing.value = true;
  motionTimer = setInterval(() => {
    const r = motion.rows[i % motion.rows.length];
    for (const id of ids) {
      const n = nodes[id];
      if (!n) continue;
      n.matrixAutoUpdate = false;
      n.matrix.compose(new THREE.Vector3(r[col(id, 'x_m')], r[col(id, 'y_m')], r[col(id, 'z_m')]),
        new THREE.Quaternion(r[col(id, 'qx')], r[col(id, 'qy')], r[col(id, 'qz')], r[col(id, 'qw')]), new THREE.Vector3(1, 1, 1));
      n.matrixWorldNeedsUpdate = true;
    }
    viewNote.value = t('运动表第 {i}/{n} 行 · 输入 {v}', { i: (i % motion.rows.length) + 1, n: motion.rows.length, v: r[0] + ' ' + (entry.value.mechanism.input?.unit || '') });
    i += 1;
  }, 80);
}
function stopMotion() { clearInterval(motionTimer); motionTimer = null; playing.value = false; }
function disposeModel() {
  stopMotion();
  if (!model) return;
  scene.remove(model);
  model.traverse((o) => { o.geometry?.dispose(); [].concat(o.material || []).forEach((m) => m.dispose()); });
  model = null;
}
function loadModel() {
  if (!entry.value || !curSize.value) return;
  if (!viewerEl.value?.isConnected) { renderer?.dispose(); renderer = null; }
  initViewer();
  if (!renderer) return;
  const url = fileUrl(curSize.value.files.glb);
  const id = entry.value.id;
  viewNote.value = t('正在读取模型…');
  loader.load(url, (g) => {
    if (entry.value?.id !== id) return;
    disposeModel();
    model = g.scene;
    model.traverse((o) => { if (o.isMesh && o.material) { o.material.side = THREE.DoubleSide; } });
    scene.add(model);
    fit(model);
    setupJoints();
    exploded.value = false;
    const box = new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3());
    viewNote.value = t('拖动旋转 · 滚轮缩放 · 外形约 {x} × {z} × {y}（单位：米制）', { x: fmtLen(box.x), z: fmtLen(box.z), y: fmtLen(box.y) });
  }, undefined, () => { viewNote.value = t('模型读取失败'); });
}
const fmtLen = (m) => (m >= 1 ? m.toFixed(2) + ' m' : (m * 1000).toFixed(m < 0.01 ? 1 : 0) + ' mm');
function fit(obj) {
  const box = new THREE.Box3().setFromObject(obj);
  const c = box.getCenter(new THREE.Vector3());
  const r = box.getSize(new THREE.Vector3()).length() / 2 || 0.05;
  const dist = r / Math.sin((camera.fov * Math.PI) / 360) * 1.1;
  camera.position.copy(c).add(new THREE.Vector3(1, 0.7, 1.2).normalize().multiplyScalar(dist));
  camera.near = dist / 200; camera.far = dist * 20; camera.updateProjectionMatrix();
  controls.target.copy(c);
}

// 夹具总成（E 部分）：按 entry.assembly.parts 的爆炸方向（毫米，Z 向上的模型坐标）拆开、装回
const exploded = ref(false);
const canExplode = computed(() => (entry.value?.assembly?.parts || []).some((p) => (p.explode_mm || []).some((x) => x)));
function toggleExplode() {
  if (!model) return;
  exploded.value = !exploded.value;
  for (const p of entry.value.assembly.parts) {
    const n = model.getObjectByName(p.node);
    if (!n) continue;
    if (!n.userData.p0) n.userData.p0 = n.position.clone();
    const e = p.explode_mm || [0, 0, 0];
    n.position.copy(n.userData.p0);
    if (exploded.value) n.position.add(new THREE.Vector3(e[0], e[1], e[2]).multiplyScalar(0.001));
  }
}

// 关节（约定 R4）：子连杆节点在零位矩阵上叠加绕轴转动（转轴过 anchor）或沿轴移动
function setupJoints() {
  joints.value = [];
  if (!entry.value?.robot || !model) return;
  const list = [];
  mimics = {};
  for (const j of entry.value.robot.joints) {
    const node = model.getObjectByName(THREE.PropertyBinding.sanitizeNodeName(j.child));
    if (!node) continue;
    node.matrixAutoUpdate = false;
    node.updateMatrix();
    const lim = j.limit && j.limit.lower != null ? j.limit : { lower: -Math.PI, upper: Math.PI };
    const zero = Math.min(Math.max(0, lim.lower), lim.upper);
    const restQ = entry.value.robot.rest?.[j.name];
    const item = { name: j.name, short: j.name.replace(/_joint$|joint_?/i, '').slice(0, 10) || j.name, type: j.type,
      min: lim.lower, max: lim.upper, value: restQ ?? zero, zero, init: restQ ?? zero, node, rest: node.matrix.clone(),
      axis: new THREE.Vector3(...j.axis).normalize(), anchor: new THREE.Vector3(...(j.anchor || [0, 0, 0])) };
    if (j.mimic) (mimics[j.mimic.joint] ||= []).push({ ...item, mimic: j.mimic });   // 从动关节：跟随主动关节，不出滑块
    else list.push(item);
  }
  joints.value = list;
  list.forEach(applyJoint);
}
let mimics = {};
function applyJoint(j) {
  for (const f of mimics[j.name] || []) { f.value = f.mimic.multiplier * j.value + f.mimic.offset; applyJoint(f); }
  const m = new THREE.Matrix4();
  if (j.type === 'prismatic') m.makeTranslation(j.axis.x * j.value, j.axis.y * j.value, j.axis.z * j.value);
  else {
    m.makeTranslation(j.anchor.x, j.anchor.y, j.anchor.z)
      .multiply(new THREE.Matrix4().makeRotationAxis(j.axis, j.value))
      .multiply(new THREE.Matrix4().makeTranslation(-j.anchor.x, -j.anchor.y, -j.anchor.z));
  }
  j.node.matrix.copy(j.rest).multiply(m);
  j.node.matrixWorldNeedsUpdate = true;
}
function resetJoints(to = 'zero') { joints.value.forEach((j) => { j.value = to === 'init' ? j.init : j.zero; applyJoint(j); }); }

onMounted(async () => {
  try {
    const latest = await getJson(BASE + 'latest.json');
    index.value = await getJson('/' + latest.index);
    // ?ref=A-BRG-DG/6207：从 ERPNext 物料上的“零件库页面”链接进来，直接打开这个规格（第 5 轮 P10②）
    const [rid, rsize] = String(useRouteRef.query.ref || '').split('/');
    const hit = families.value.find((f) => f.id === rid);
    if (hit) { part.value = hit.part; select(hit.id, rsize || ''); return; }
    const first = families.value.find((f) => f.id === 'A-BRG-DG') || families.value[0];
    if (first) select(first.id);
  } catch (e) {
    error.value = e.message === '404' ? t('零件库还没有发布。发布后（GitHub 工作流“零件库发布”）这里自动显示。') : t('读取零件库失败：') + e.message;
  }
});
watch(part, () => { if (part.value === 'F') { disposeModel(); } });
onUnmounted(() => { cancelAnimationFrame(raf); ro?.disconnect(); disposeModel(); renderer?.dispose(); });
</script>

<style scoped>
.lib { padding: 20px 28px 28px; display: flex; flex-direction: column; gap: 16px; }
.head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.head h1 { font-size: 20px; }
.src { font-size: 11px; color: var(--muted); }
.lbl { font-size: 12px; color: var(--muted); margin-bottom: 6px; display: block; }
.field-row { display: flex; gap: 8px; }
.field-row input { flex: 1; min-width: 0; height: 38px; border: 1px solid var(--line); border-radius: 6px; padding: 0 12px; background: var(--surface); }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.tab { background: none; border: 0; border-bottom: 2px solid transparent; padding: 8px 14px; cursor: pointer; color: var(--muted); font-size: 14px; }
.tab.on { color: var(--ink); border-bottom-color: var(--accent); font-weight: 600; }
.tab .n { font-family: var(--mono); font-size: 11px; margin-left: 4px; }
.work { display: grid; grid-template-columns: 200px minmax(0, 1fr) minmax(0, 460px); gap: 16px; align-items: start; }
.filters { display: flex; flex-direction: column; gap: 18px; }
.filters h3 { font-size: 12px; color: var(--muted); font-weight: 500; letter-spacing: .04em; margin-bottom: 6px; }
.filters label { display: flex; align-items: center; gap: 8px; font-size: 13px; padding: 3px 0; cursor: pointer; }
.filters label .c { margin-left: auto; font-family: var(--mono); font-size: 11px; color: var(--muted); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; align-content: start; }
.item { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 0; cursor: pointer; text-align: left;
  display: flex; flex-direction: column; overflow: hidden; }
.item:hover { border-color: var(--accent); }
.item.on { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-bg); }
.thumb { background: #F3F5F2; height: 120px; display: flex; align-items: center; justify-content: center; border-bottom: 1px solid var(--line-soft); }
.thumb img { max-width: 100%; max-height: 116px; object-fit: contain; }
.meta { padding: 10px 12px 12px; display: flex; flex-direction: column; gap: 5px; }
.meta b { font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
.meta .id { font-family: var(--mono); font-size: 11px; color: var(--muted); }
.meta .std { font-size: 12px; color: var(--muted); }
.pills { display: flex; gap: 4px; flex-wrap: wrap; }
.pill { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 10px; white-space: nowrap; }
.pill.good { color: var(--good); background: var(--good-bg); }
.pill.info { color: var(--accent); background: var(--accent-bg); }
.pill.task { color: var(--task-ink); background: var(--task-bg); border: 1px solid var(--task-line); }
.empty { color: var(--muted); padding: 20px 0; }
.empty.pad { padding: 40px 18px; }
.more-row { padding: 14px 0; text-align: center; }
.detail { position: sticky; top: 12px; display: flex; flex-direction: column; gap: 12px; padding: 0; overflow: hidden; }
.d-head { padding: 14px 18px 0; display: flex; flex-direction: column; gap: 4px; }
.d-head h2 { font-size: 17px; }
.viewer { position: relative; height: 320px; background: #F3F5F2; border-top: 1px solid var(--line-soft); border-bottom: 1px solid var(--line-soft); }
.viewer :deep(canvas) { display: block; width: 100%; height: 100%; }
.viewer.flat { display: flex; align-items: center; justify-content: center; }
.viewer.flat img { max-height: 300px; max-width: 100%; }
.v-note { position: absolute; left: 10px; bottom: 8px; font-size: 11px; color: var(--muted); pointer-events: none; }
.v-tools { position: absolute; right: 10px; top: 10px; display: flex; gap: 6px; }
.v-tools .btn { height: 28px; font-size: 12px; padding: 0 10px; }
.ai-lbl { margin-top: 12px; }
.ai-res { margin-top: 10px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg-soft, #F7F8F6); }
.ai-text { white-space: pre-wrap; margin: 0 0 8px; font-size: 13px; line-height: 1.6; }
.ai-refs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }
.ai-refs .chip { border: 1px solid var(--accent); color: var(--accent); background: #fff; border-radius: 999px; padding: 2px 10px; font-size: 12px; cursor: pointer; }
.err { color: #B3261E; margin-top: 6px; }
.drawing { width: 100%; border: 1px solid var(--line); background: #fff; display: block; }
.joints { padding: 0 18px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 16px; max-height: 220px; overflow-y: auto; }
.joints label { font-size: 12px; display: grid; grid-template-columns: 64px minmax(0, 1fr) 48px; align-items: center; gap: 6px; }
.joints .jn { font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.joints input { width: 100%; accent-color: var(--accent); }
.joints .v { font-family: var(--mono); font-size: 11px; text-align: right; color: var(--muted); }
.actions { padding: 0 18px; display: flex; gap: 8px; flex-wrap: wrap; }
.actions .btn { display: inline-flex; align-items: center; text-decoration: none; }
.dtabs { padding: 0 18px; }
.dbody { padding: 0 18px 18px; font-size: 13px; line-height: 1.6; min-width: 0; }
.sq { width: 100%; height: 32px; border: 1px solid var(--line); border-radius: 6px; padding: 0 10px; margin-bottom: 8px; background: var(--surface); }
.tbl-wrap { overflow: auto; max-height: 340px; }
table.t { width: 100%; border-collapse: collapse; font-size: 12.5px; }
table.t th { text-align: left; font-weight: 500; color: var(--muted); font-size: 11.5px; padding: 6px 8px; border-bottom: 1px solid var(--line);
  white-space: nowrap; position: sticky; top: 0; background: var(--surface); }
table.t td { padding: 6px 8px; border-bottom: 1px solid var(--line-soft); }
table.t td.num, table.t td.nw { white-space: nowrap; }
table.t td.num { text-align: right; font-family: var(--mono); font-variant-numeric: tabular-nums; }
table.t tr.sel td { background: var(--accent-bg); }
table.t tbody tr { cursor: pointer; }
dl.kv.wide { grid-template-columns: 120px minmax(0, 1fr); }
dl.kv { display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 6px 12px; margin: 0; }
dl.kv dt { color: var(--muted); }
dl.kv dd { margin: 0; overflow-wrap: anywhere; }
.pad-x { padding: 0 18px; margin: 0; }
.proxy-note { color: var(--warn-ink); background: var(--warn-bg); border-radius: 6px; padding: 4px 8px; margin-top: 4px; }
.swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; border: 1px solid rgba(0, 0, 0, 0.25); vertical-align: -1px; }
.dsrc { margin-top: 10px; display: flex; flex-direction: column; gap: 4px; overflow-wrap: anywhere; }
.attr { margin-top: 10px; background: var(--surface-2); border: 1px dashed var(--line); border-radius: 6px; padding: 8px 10px; font-size: 12px; }
.toast { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); background: var(--ink); color: var(--bg); padding: 10px 16px;
  border-radius: 8px; font-size: 13px; z-index: 50; }
@media (max-width: 1280px) { .work { grid-template-columns: 180px minmax(0, 1fr); } .detail { grid-column: 1 / -1; position: static; } }
@media (max-width: 900px) {
  .lib { padding: 16px; }
  .work { grid-template-columns: minmax(0, 1fr); }
  .filters { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
  .joints { grid-template-columns: 1fr; }
}
</style>
