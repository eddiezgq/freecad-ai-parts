<!-- 第 88 轮（电子 E4）：电路板设计（第 98 轮加 B 版，第 100 轮加 B 版固件）。关节驱动板 DRV-JOINT 的 KiCad 设计产物（CI 里用 KiCad 生成，随仓库发布）：
     原理图逐页、PCB 各层、三维、BOM（与电路板厂物料对照）、可制造性检查（点一项在 PCB 图上标位置）、下载。示例设计，未经硬件验证。 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ t('电路板设计') }}</h1>
      <span class="muted">{{ d ? td(d.name) + ' (' + td(d.rev) + ', ' + td(d.tool) + ')' : t('读取中…') }}</span></div>
    <div class="line"><button class="chip" :class="{ on: rev === 'A' }" @click="setRev('A')">{{ t('A 版（投产）') }}</button>
      <button class="chip" :class="{ on: rev === 'B' }" @click="setRev('B')">{{ t('B 版：编码器接口芯片 + 抱闸（设计对照）') }}</button>
      <button class="chip" :class="{ on: rev === 'C' }" @click="setRev('C')">{{ t('平缝机控制器 CTRL-LS') }}</button></div>
    <div v-if="d && rev !== 'C'" class="warn small">⚠ {{ td(d.disclaimer) }}{{ t('。芯片是 KiCad 官方库里有的器件做的示例选型；数值由电路公式算（与“电路分析”的例题同一组数）。') }}</div>
    <div v-if="d && rev === 'C'" class="warn small">⚠ {{ td(d.disclaimer) }}{{ t('。第 159 轮：平缝机控制器（220 V 输入、伺服主轴 + 步进送布 + 电磁铁、隔离面板口）从选型、计算仿真到原理图、PCB 的全过程；元器件按规格书选，规格书数据“待核对”，定制磁性元件按理论算。') }}</div>
    <div v-if="d && rev === 'B'" class="small muted">{{ t('第 106 轮起：数字工业园（仿真）里电路板厂按 B 版试产（产品 DRV-JOINT-B），编码器接口芯片向工业园的芯片厂买；现实里照旧不投产。') }}</div>
    <div v-if="err" class="err">{{ err }}</div>
    <div class="tabs">
      <button v-for="x in tabsFor" :key="x.k" class="tab" :class="{ on: tab === x.k }" @click="go(x.k)">{{ t(x.label) }}</button>
    </div>

    <section v-if="d && tab === 'sch'" class="card">
      <div class="line">
        <button v-for="(s, i) in d.sheets" :key="s.key" class="chip" :class="{ on: sheet === s.key }" @click="pickSheet(s.key)">{{ i + 1 }} {{ nm(s) }}</button>
        <label class="small">{{ t('放大') }} <input v-model.number="zoom" type="range" min="1" max="4" step="0.25"></label>
      </div>
      <p v-if="cur" class="small">{{ td(cur.note) }}</p>
      <div v-if="cur" class="canvas"><img :src="url('schematic/' + cur.svg)" :style="{ width: zoom * 100 + '%' }" :alt="nm(cur)"></div>
      <div v-if="cur" class="small muted">{{ t('这一页的器件：') }}{{ partsOn(cur.key).map((p) => p.ref + ' ' + td(p.value)).join(', ') }}</div>
      <div v-if="cur && cur.key === 'io' && rev !== 'C'" class="line"><router-link class="btn" to="/chip-design?tab=bench">{{ t('板上编码器接口芯片的设计（WQ-ENCIF，Verilog 到版图）→') }}</router-link></div>
      <div v-if="cur && rev !== 'C' && EXAMPLE[cur.key]" class="line"><router-link class="btn" :to="'/circuit?ex=' + EXAMPLE[cur.key]">{{ t('在“电路分析”里算这一页的电路 →') }}</router-link></div>
    </section>

    <section v-if="d && tab === 'pcb'" class="card">
      <div class="line">
        <label v-for="l in d.pcb_layers" :key="l.key" class="small"><input v-model="layers" type="checkbox" :value="l.key"> {{ td(l.name) }}</label>
        <label class="small">{{ t('放大') }} <input v-model.number="zoom" type="range" min="1" max="4" step="0.25"></label>
      </div>
      <div class="small muted">{{ t('板子 {w} × {h} mm，{l} 层；器件 {p} 个、网络 {n} 个、走线 {t} 段（{tm} mm）、过孔 {v} 个。', { w: d.board_mm[0], h: d.board_mm[1], l: d.layers, p: d.stats.parts, n: d.nets, t: d.stats.tracks, tm: d.stats.track_mm, v: d.stats.vias }) }}
        {{ t('设计规则检查：错误 {e}、警告 {w}（丝印类）、未连接 {u}。', { e: d.drc.errors, w: d.drc.warnings, u: d.drc.unconnected }) }}</div>
      <div class="canvas"><div class="stack" :style="{ width: zoom * 100 + '%' }">
        <img v-for="l in shownLayers" :key="l.key" :src="url('pcb/' + l.svg)" :class="'ly ly-' + l.key" :alt="td(l.name)">
        <svg class="marks" :viewBox="'0 0 ' + d.board_mm[0] + ' ' + d.board_mm[1]" preserveAspectRatio="none">
          <g v-for="(m, i) in marks" :key="i"><circle :cx="m[0]" :cy="m[1]" r="2.2" class="mk" /><text :x="m[0] + 2.6" :y="m[1] - 1.5" class="mt">{{ m[2] }}</text></g>
        </svg>
      </div></div>
      <div v-if="marks.length" class="small">{{ t('标出的位置：') }}{{ td(markTitle) }} <button class="btn sm" @click="marks = []">{{ t('清除') }}</button></div>
    </section>

    <section v-if="d && tab === '3d'" class="card">
      <ModelViewer :key="rev" :url="url(stem + '.glb')" />
      <p class="small muted">{{ t('三维由 KiCad 导出 STEP（器件外形取自 KiCad 官方三维模型库，CC-BY-SA 4.0 附例外），再转成网页用的 GLB。STEP 可以下载到 FreeCAD 里装进关节模组。') }}</p>
      <p v-if="rev === 'C'" class="small muted">{{ t('升压电感（ETD59）和隔离电源（SIP-4）的封装是工程自带库里按理论画的，没有三维模型。') }}</p>
    </section>

    <section v-if="d && tab === 'bom'" class="card">
      <p v-if="rev === 'A'" class="small">{{ t('同一物料编号、同一数值和封装合为一行；“物料编号”就是电路板厂清单里的编号（贴片板 SMT-DRV 与成品板 DRV-JOINT 的物料清单按这份设计的数量写，测试核对）。') }}</p>
      <p v-else-if="rev === 'B'" class="small">{{ t('B 版：现实里不投产（芯片未流片）；数字工业园里电路板厂试产，贴片板 SMT-DRV-B 与成品板 DRV-JOINT-B 的物料清单按这份设计的数量写（测试核对）。比 A 版多出的见“A→B 改了什么”。') }}</p>
      <p v-else class="small">{{ t('型号、厂家、立创编号来自第 159 轮选型（外部零件库查到、规格书核过的写在设计描述里）；同一物料编号、数值和封装合为一行。') }}</p>
      <table class="tbl">
        <thead><tr><th>{{ t('物料编号') }}</th><th>{{ t('数值') }}</th><th>{{ t('封装') }}</th><th>{{ t('数量') }}</th><th>{{ t('位号') }}</th>
          <th v-if="rev === 'C'">{{ t('型号 / 厂家') }}</th><th>{{ t('说明') }}</th><th>{{ t('到外部库查') }}</th></tr></thead>
        <tbody><tr v-for="(r, i) in bom" :key="i"><td class="mono">{{ r.item }}</td><td>{{ td(r.value) }}</td><td class="small">{{ r.package }}</td><td>{{ r.qty }}</td>
          <td class="small mono">{{ r.refs }}</td><td v-if="rev === 'C'" class="small">{{ r.mpn }}<span v-if="r.maker" class="muted"> · {{ r.maker }}</span></td><td class="small">{{ td(r.note) }}</td>
          <td class="small ext"><a v-for="l in bomLinks(r)" :key="l.site" :href="l.url" target="_blank" rel="noopener external">{{ l.name }}</a></td></tr></tbody>
      </table>
      <p class="small muted">{{ t('“到外部库查”只拼对方网站的搜索地址、新窗口打开，内容以对方为准；没有尺寸码的电解电容、二极管、端子、自研芯片不出链接（不猜）。') }}</p>
      <p class="small muted">{{ t('不进 BOM 的：测试点（ICT 针床、烧录夹具扎的焊盘）、网络连接点（开尔文引线）、安装孔。') }}</p>
    </section>

    <section v-if="d && tab === 'dfm' && dfm" class="card">
      <p class="small">{{ t('按一份示例板厂工艺能力检查：线宽 / 线距 {a} mm、最小孔 {b} mm、孔环 {c} mm、阻焊桥 {d} mm、元件到板边 {e} mm、ICT 覆盖率 ≥ {f}%。', { a: dfm.capability.track_min, b: dfm.capability.drill_min, c: dfm.capability.annular_min, d: dfm.capability.mask_bridge_min, e: dfm.capability.edge_min, f: Math.round(dfm.capability.ict_coverage_min * 100) }) }}
        {{ t('结论：') }}<b :class="dfm.pass ? 'ok' : 'bad'">{{ dfm.pass ? t('全部通过') : t('有不通过的项') }}</b></p>
      <table class="tbl">
        <thead><tr><th>{{ t('检查') }}</th><th>{{ t('结果') }}</th><th>{{ t('这块板') }}</th><th>{{ t('要求') }}</th><th>{{ t('为什么板厂在乎') }}</th><th></th></tr></thead>
        <tbody><tr v-for="c in dfm.checks" :key="c.key">
          <td>{{ td(c.name) }}</td><td :class="c.pass ? 'ok' : 'bad'">{{ c.pass ? t('✓ 通过') : t('✗ 不通过') }}</td>
          <td class="mono">{{ fmt(c.value) }} {{ td(c.unit) }}</td><td class="mono">{{ fmt(c.limit) }} {{ td(c.unit) }}</td>
          <td class="small">{{ td(c.why) }}<div v-if="c.detail" class="muted">{{ td(c.detail) }}</div></td>
          <td><button v-if="c.at.length" class="btn sm" @click="show(c)">{{ t('在 PCB 上标出') }}</button></td></tr></tbody>
      </table>
    </section>

    <section v-if="d && tab === 'chk' && rev === 'C'" class="card">
      <h3>{{ t('安全距离') }}</h3>
      <p class="small">{{ t('按网络分组量同一层上两组铜的最近直线距离，和规则里的电气间隙、爬电距离比（偏保守）。规则数都是示例值，企业按自己产品适用的安全标准查表后填（factory/designs/ctrl-ls/safety.yaml）。') }}</p>
      <table class="tbl">
        <thead><tr><th>{{ t('规则') }}</th><th>{{ t('结果') }}</th><th>{{ t('板上最近') }}</th><th>{{ t('要求（示例值）') }}</th><th>{{ t('绝缘') }}</th><th></th></tr></thead>
        <tbody><tr v-for="c in safety" :key="c.key">
          <td>{{ td(c.name) }}</td><td :class="cls(c.status)">{{ st(c.status) }}</td><td class="mono">{{ fmt(c.value) }} mm</td><td class="mono">{{ fmt(c.limit) }} mm</td>
          <td class="small">{{ td(c.insulation) }}<div class="muted">{{ td(c.rule) }}</div></td>
          <td><button v-if="c.at.length" class="btn sm" @click="show(c)">{{ t('在 PCB 上标出') }}</button></td></tr></tbody>
      </table>
      <template v-if="rep">
        <h3>{{ t('统一报告：工艺与布局') }}</h3>
        <p class="small">{{ t('按一份示例板厂工艺能力表检查（eda/examples/factories/example-smt.yaml）。报告结论：') }}
          <b>{{ t('通过 {p}、不通过 {f}、待核对 {w}、未知 {u}', { p: rep.count.pass, f: rep.count.fail, w: rep.count.pending, u: rep.count.unknown }) }}</b>
          (<a :href="url('report/report.html')" target="_blank">{{ t('报告全文') }}</a> · <a :href="url('report/calc.html')" target="_blank">{{ t('计算书') }}</a>)</p>
        <table class="tbl">
          <thead><tr><th>{{ t('检查') }}</th><th>{{ t('结果') }}</th><th>{{ t('这块板') }}</th><th>{{ t('要求') }}</th><th>{{ t('说明') }}</th><th></th></tr></thead>
          <tbody><tr v-for="c in rep.process.concat(rep.layout)" :key="c.key">
            <td><span class="mono">{{ c.key }}</span> {{ td(c.name) }}</td><td :class="cls(c.status)">{{ st(c.status) }}</td>
            <td class="mono">{{ fmt(c.value) }} {{ td(c.unit) }}</td><td class="mono">{{ fmt(c.limit) }} {{ td(c.unit) }}</td>
            <td class="small">{{ td(c.why) }}<div v-if="c.detail" class="muted">{{ td(c.detail) }}</div></td>
            <td><button v-if="(c.at || []).length" class="btn sm" @click="show(c)">{{ t('在 PCB 上标出') }}</button></td></tr></tbody>
        </table>
        <h3>{{ t('板级热') }}</h3>
        <p class="small">{{ t('板上发热件的损耗取计算书的结果，按一块平板算焊盘下的板温（环境 {a} ℃，两面自然对流 {h} W/(m²·K)，示例值）；散热器上的大件在计算书“散热器”一节。', { a: rep.thermal.ambient_c, h: rep.thermal.h_w_m2k }) }}</p>
        <table class="tbl">
          <thead><tr><th>{{ t('位号') }}</th><th>{{ t('损耗') }}</th><th>{{ t('焊盘下板温') }}</th><th>{{ t('板子允许') }}</th><th>{{ t('结果') }}</th></tr></thead>
          <tbody><tr v-for="r in rep.thermal.rows" :key="r.ref"><td class="mono">{{ r.ref }}</td><td class="mono">{{ fmt(r.p_w) }} W</td>
            <td class="mono">{{ r.t_board_c }} ℃</td><td class="mono">{{ r.t_limit_c }} ℃</td><td :class="cls(r.status)">{{ st(r.status) }}</td></tr></tbody>
        </table>
        <p class="small muted">{{ td(rep.thermal.detail) }}</p>
      </template>
    </section>

    <section v-if="d && tab === 'diff' && d.changes" class="card">
      <p class="small">{{ t('B 版 = A 版 + 编码器接口芯片 WQ-ENCIF（') }}<router-link to="/chip-design">{{ t('芯片设计') }}</router-link>{{ t('，第 92 轮）：编码器 A/B/Z 经原来的 RC 滤波进芯片，芯片计数，MCU 用 SPI 读；') }}
        {{ t('第 110 轮加抱闸驱动：J6 接电机轴上的失电制动抱闸，U16 栅极驱动 + Q7 从母线 PWM 供电，D5 续流，R38 下拉保证 MCU 没输出时抱住；母线铺铜往右接出一条供电。') }}
        {{ t('同一份设计描述打补丁生成（factory/designs/drv-joint-b/variant.yaml），其余电路一字不动。') }}</p>
      <h3>{{ t('器件') }}</h3>
      <table class="tbl"><thead><tr><th>{{ t('位号') }}</th><th>{{ t('改了什么') }}</th></tr></thead>
        <tbody><tr v-for="(c, i) in d.changes" :key="i"><td class="mono">{{ td(c.ref) }}</td><td class="small">{{ td(c.what) }}</td></tr></tbody></table>
      <h3>{{ t('MCU 引脚（STM32G431，LQFP-48）') }}</h3>
      <table class="tbl"><thead><tr><th>{{ t('引脚') }}</th><th>{{ t('A 版') }}</th><th>{{ t('B 版') }}</th></tr></thead>
        <tbody><tr v-for="m in d.mcu_pins" :key="m.pin"><td class="mono">{{ m.pin }}</td><td class="mono">{{ m.a || t('未用') }}</td><td class="mono">{{ m.b || t('未用') }}</td></tr></tbody></table>
      <h3>{{ t('物料（比 A 版多）') }}</h3>
      <p class="small mono">{{ Object.entries(d.bom_delta).map(([k, n]) => k + ' ' + (n > 0 ? '+' : '') + n).join(', ') }}</p>
      <h3>{{ t('新网络') }}</h3>
      <p class="small mono">{{ d.nets_added.join(', ') }}</p>
      <h3>{{ t('固件要改的配置') }}</h3>
      <ul class="small"><li v-for="(f, i) in d.firmware" :key="i">{{ td(f) }}</li></ul>
      <p class="small"><a href="#" @click.prevent="go('fw')">{{ t('这段固件已经写好，在 Renode 里跑过 →') }}</a></p>
      <p class="small muted">{{ t('新增器件放在底面（顶面这一带已满，底面原来只有测试点）；布线、设计规则检查、可制造性检查都按 A 版同一套流程重跑：') }}
        {{ t('错误 {e}、未连接 {u}，可制造性 {d}。', { e: d.drc.errors, u: d.drc.unconnected, d: d.dfm.pass ? t('全部通过') : t('有不通过') }) }}</p>
    </section>

    <section v-if="d && tab === 'fw' && rev === 'B'" class="card">
      <FirmwarePanel />
    </section>
    <section v-if="d && tab === 'fw' && rev === 'C'" class="card">
      <SewFirmwarePanel />
    </section>

    <section v-if="d && tab === 'dl'" class="card">
      <ul class="dl">
        <li><a :href="url('kicad-project.zip')" download>{{ t('KiCad 工程（原理图 + PCB，KiCad 7 能打开）') }}</a></li>
        <li><a :href="url('gerber.zip')" download>{{ t('Gerber 与钻孔文件（给板厂）') }}</a></li>
        <li><a :href="url('bom.csv')" download>BOM (CSV)</a> · <a :href="url('pos.csv')" download>{{ t('贴片坐标（CSV，给贴片机编程）') }}</a></li>
        <li><a :href="url(stem + '.step')" download>{{ t('三维 STEP（FreeCAD）') }}</a></li>
        <li v-if="rev !== 'C'"><a :href="url('drc.json')" target="_blank">{{ t('设计规则检查结果') }}</a> · <a :href="url('dfm.json')" target="_blank">{{ t('可制造性检查结果') }}</a></li>
        <li v-else><a :href="url('drc.json')" target="_blank">{{ t('设计规则检查结果') }}</a> · <a :href="url('safety.json')" target="_blank">{{ t('安全距离检查结果') }}</a>
          · <a :href="url('report/report.html')" target="_blank">{{ t('报告全文') }}</a> · <a :href="url('report/calc.html')" target="_blank">{{ t('计算书') }}</a></li>
      </ul>
      <p class="small muted">{{ t('生成方式：设计描述（器件、数值、引脚接哪个网络）→ 脚本写 KiCad 原理图与 PCB → Freerouting 自动布线 → KiCad 设计规则检查与导出（仓库 factory/designs/tools/build.py）。') }}</p>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import ModelViewer from '../components/ModelViewer.vue';
import FirmwarePanel from '../components/FirmwarePanel.vue';
import SewFirmwarePanel from '../components/SewFirmwarePanel.vue';
import { nm, t, td, tk } from '../lib/i18n';
import { bomLinks } from '../lib/extlinks.js';

// 第 159 轮（159d3）加 C：平缝机控制器 CTRL-LS（检查页签放安全距离与统一报告，不放关节驱动板的可制造性、A→B）；159f 加 C 的固件页签
const STEM = { A: 'drv-joint', B: 'drv-joint-b', C: 'ctrl-ls' };
const TABS = [{ k: 'sch', label: tk('原理图') }, { k: 'pcb', label: 'PCB' }, { k: '3d', label: tk('三维') }, { k: 'bom', label: 'BOM' },
  { k: 'dfm', label: tk('可制造性检查'), ab: true }, { k: 'chk', label: tk('检查'), c: true }, { k: 'diff', label: tk('A→B 改了什么'), b: true },
  { k: 'fw', label: tk('固件（Renode 仿真）'), bc: true }, { k: 'dl', label: tk('下载') }];
const okTab = (y, r) => (!y.b || r === 'B') && (!y.bc || r !== 'A') && (!y.ab || r !== 'C') && (!y.c || r === 'C');
const STATUS = { pass: tk('✓ 通过'), fail: tk('✗ 不通过'), unknown: tk('未知'), pending: tk('待核对') };
// 原理图这一页 ↔ 电路分析的例题（同一组数）
const EXAMPLE = { sense: 'sense', gate: 'gate', power: 'bus', io: 'encoder' };
const route = useRoute();
const router = useRouter();
const d = ref(null);
const dfm = ref(null);
const bom = ref([]);
const safety = ref([]);
const rep = ref(null);
const err = ref('');
const tab = ref(route.query.tab || 'sch');
const sheet = ref(route.query.sheet || 'power');
const zoom = ref(1);
const layers = ref(['F_Cu', 'F_Silk']);
const marks = ref([]);
const markTitle = ref('');

const rev = ref(['B', 'C'].includes(route.query.rev) ? route.query.rev : 'A');
const tabsFor = computed(() => TABS.filter((y) => okTab(y, rev.value)));
const stem = computed(() => STEM[rev.value]);
const url = (p) => '/api/designs/' + stem.value + '/' + p;
function setRev(r) {
  rev.value = r; marks.value = [];
  const ct = TABS.find((y) => y.k === tab.value);
  if (!ct || !okTab(ct, r)) tab.value = 'sch';
  sheet.value = '';
  router.replace({ query: { ...route.query, rev: r, tab: tab.value } });
  load();
}
const cur = computed(() => d.value?.sheets.find((s) => s.key === sheet.value));
const shownLayers = computed(() => (d.value?.pcb_layers || []).filter((l) => layers.value.includes(l.key)));
function partsOn(key) { return (d.value?.parts || []).filter((p) => p.sheet === key && !p.ref.startsWith('TP') && !p.ref.startsWith('NT')); }
function go(k) { tab.value = k; router.replace({ query: { ...route.query, tab: k } }); }
function pickSheet(k) { sheet.value = k; router.replace({ query: { ...route.query, sheet: k } }); }
function fmt(v) { return typeof v === 'number' ? +v.toFixed(3) : v; }
// 关节驱动板的可制造性检查给的是板框内坐标；CTRL-LS 的检查给 KiCad 绝对坐标（y 有的取了负号），减掉板框左上角
function toBoard(m) {
  const o = d.value?.origin_mm;
  if (!o) return m;
  return [m[0] - o[0], Math.abs(m[1]) - o[1], m.slice(2).filter((v) => typeof v === 'string').join(' ')];
}
function show(c) { marks.value = c.at.map(toBoard); markTitle.value = c.name; layers.value = ['F_Cu', 'B_Cu', 'F_Silk']; go('pcb'); }
function st(s) { return t(STATUS[s] || s); }
function cls(s) { return s === 'pass' ? 'ok' : s === 'fail' ? 'bad' : 'muted'; }
// 物料清单按表头取列（关节驱动板没有型号、厂家两列）
const COLS = { item: '物料编号', value: '数值', package: '封装', qty: '数量', refs: '位号', mpn: '型号', maker: '厂家', note: '说明' }; // i18n-ok 物料清单 CSV 的表头（数据，不显示）
function parseBom(text) {
  const rows = parseCsv(text, true);
  const head = rows.shift() || [];
  return rows.map((r) => Object.fromEntries(Object.entries(COLS).map(([k, h]) => [k, head.indexOf(h) >= 0 ? r[head.indexOf(h)] : ''])));
}
function parseCsv(t, withHead) {
  return t.trim().split('\n').slice(withHead ? 0 : 1).map((line) => {
    const out = []; let cur = ''; let q = false;
    for (const ch of line) {
      if (ch === '"') q = !q; else if (ch === ',' && !q) { out.push(cur); cur = ''; } else cur += ch;
    }
    out.push(cur);
    return out;
  });
}
async function load() {
  err.value = ''; d.value = null;
  try {
    const r = await fetch(url('design.json'));
    if (!r.ok) throw new Error(t('读不到设计产物（{s}）', { s: r.status }));
    d.value = await r.json();
    if (!d.value.sheets.find((s) => s.key === sheet.value)) sheet.value = d.value.sheets[0]?.key || '';
    dfm.value = null; safety.value = []; rep.value = null;
    if (rev.value === 'C') {
      safety.value = await (await fetch(url('safety.json'))).json();
      rep.value = await (await fetch(url('report/report.json'))).json();
    } else {
      dfm.value = await (await fetch(url('dfm.json'))).json();
    }
    bom.value = parseBom(await (await fetch(url('bom.csv'))).text());
  } catch (e) { err.value = e.message || String(e); }
}
onMounted(load);
</script>

<style scoped>
.warn { background: #fff7e6; border: 1px solid #f5c26b; padding: 6px 10px; border-radius: 6px; margin: 6px 0; }
.tabs { display: flex; flex-wrap: wrap; gap: 4px; margin: 8px 0; }
.chip { border: 1px solid var(--line, #ccd); background: #fff; border-radius: 14px; padding: 3px 10px; cursor: pointer; font-size: 13px; }
.chip.on { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
.line { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 6px 0; }
.canvas { overflow: auto; max-height: 75vh; border: 1px solid #e3e6ee; border-radius: 8px; background: #fff; }
.canvas img { display: block; }
.stack { position: relative; background: #0b1220; }
.stack .ly { position: absolute; left: 0; top: 0; width: 100%; }
.stack .ly:first-child { position: relative; }
.ly-F_Cu { opacity: 0.95; } .ly-B_Cu { opacity: 0.6; } .ly-In1_Cu, .ly-In2_Cu { opacity: 0.5; }
.marks { position: absolute; left: 0; top: 0; width: 100%; height: 100%; pointer-events: none; }
.mk { fill: none; stroke: #ef4444; stroke-width: 0.5; }
.mt { fill: #ef4444; font-size: 2.2px; }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.tbl th, .tbl td { border-bottom: 1px solid #eef0f5; padding: 4px 6px; text-align: left; vertical-align: top; }
.ok { color: #15803d; } .bad { color: #b91c1c; }
.dl li { margin: 6px 0; }
.btn.sm { padding: 1px 8px; font-size: 12px; }
.ext a + a { margin-left: 8px; }
.ext { white-space: nowrap; }
.tbl td.mono:first-child, .tbl th { white-space: nowrap; }
</style>
