<!-- 第 88 轮（电子 E4）：电路板设计（第 98 轮加 B 版，第 100 轮加 B 版固件）。关节驱动板 DRV-JOINT 的 KiCad 设计产物（CI 里用 KiCad 生成，随仓库发布）：
     原理图逐页、PCB 各层、三维、BOM（与电路板厂物料对照）、可制造性检查（点一项在 PCB 图上标位置）、下载。示例设计，未经硬件验证。 -->
<template>
  <div class="page">
    <div class="page-title"><h1>电路板设计</h1>
      <span class="muted">{{ d ? d.name + '（' + d.rev + '，' + d.tool + '）' : '读取中…' }}</span></div>
    <div class="line"><button class="chip" :class="{ on: rev === 'A' }" @click="setRev('A')">A 版（投产）</button>
      <button class="chip" :class="{ on: rev === 'B' }" @click="setRev('B')">B 版：编码器接口芯片 + 抱闸（设计对照）</button></div>
    <div v-if="d" class="warn small">⚠ {{ d.disclaimer }}。芯片是 KiCad 官方库里有的器件做的示例选型；数值由电路公式算（与“电路分析”的例题同一组数）。</div>
    <div v-if="d && rev === 'B'" class="small muted">第 106 轮起：数字工业园（仿真）里电路板厂按 B 版试产（产品 DRV-JOINT-B），编码器接口芯片向工业园的芯片厂买；现实里照旧不投产。</div>
    <div v-if="err" class="err">{{ err }}</div>
    <div class="tabs">
      <button v-for="t in TABS.filter((x) => !x.b || rev === 'B')" :key="t.k" class="tab" :class="{ on: tab === t.k }" @click="go(t.k)">{{ t.label }}</button>
    </div>

    <section v-if="d && tab === 'sch'" class="card">
      <div class="line">
        <button v-for="(s, i) in d.sheets" :key="s.key" class="chip" :class="{ on: sheet === s.key }" @click="pickSheet(s.key)">{{ i + 1 }} {{ s.name }}</button>
        <label class="small">放大 <input v-model.number="zoom" type="range" min="1" max="4" step="0.25"></label>
      </div>
      <p v-if="cur" class="small">{{ cur.note }}</p>
      <div v-if="cur" class="canvas"><img :src="url('schematic/' + cur.svg)" :style="{ width: zoom * 100 + '%' }" :alt="cur.name"></div>
      <div v-if="cur" class="small muted">这一页的器件：{{ partsOn(cur.key).map((p) => p.ref + ' ' + p.value).join('、') }}</div>
      <div v-if="cur && cur.key === 'io'" class="line"><router-link class="btn" to="/chip-design?tab=bench">板上编码器接口芯片的设计（WQ-ENCIF，Verilog 到版图）→</router-link></div>
      <div v-if="cur && EXAMPLE[cur.key]" class="line"><router-link class="btn" :to="'/circuit?ex=' + EXAMPLE[cur.key]">在“电路分析”里算这一页的电路 →</router-link></div>
    </section>

    <section v-if="d && tab === 'pcb'" class="card">
      <div class="line">
        <label v-for="l in d.pcb_layers" :key="l.key" class="small"><input v-model="layers" type="checkbox" :value="l.key"> {{ l.name }}</label>
        <label class="small">放大 <input v-model.number="zoom" type="range" min="1" max="4" step="0.25"></label>
      </div>
      <div class="small muted">板子 {{ d.board_mm[0] }} × {{ d.board_mm[1] }} mm，{{ d.layers }} 层；器件 {{ d.stats.parts }} 个、网络 {{ d.nets }} 个、走线 {{ d.stats.tracks }} 段（{{ d.stats.track_mm }} mm）、过孔 {{ d.stats.vias }} 个。
        设计规则检查：错误 {{ d.drc.errors }}、警告 {{ d.drc.warnings }}（丝印类）、未连接 {{ d.drc.unconnected }}。</div>
      <div class="canvas"><div class="stack" :style="{ width: zoom * 100 + '%' }">
        <img v-for="l in shownLayers" :key="l.key" :src="url('pcb/' + l.svg)" :class="'ly ly-' + l.key" :alt="l.name">
        <svg class="marks" :viewBox="'0 0 ' + d.board_mm[0] + ' ' + d.board_mm[1]" preserveAspectRatio="none">
          <g v-for="(m, i) in marks" :key="i"><circle :cx="m[0]" :cy="m[1]" r="2.2" class="mk" /><text :x="m[0] + 2.6" :y="m[1] - 1.5" class="mt">{{ m[2] }}</text></g>
        </svg>
      </div></div>
      <div v-if="marks.length" class="small">标出的位置：{{ markTitle }} <button class="btn sm" @click="marks = []">清除</button></div>
    </section>

    <section v-if="d && tab === '3d'" class="card">
      <ModelViewer :key="rev" :url="url(stem + '.glb')" />
      <p class="small muted">三维由 KiCad 导出 STEP（器件外形取自 KiCad 官方三维模型库，CC-BY-SA 4.0 附例外），再转成网页用的 GLB。STEP 可以下载到 FreeCAD 里装进关节模组。</p>
    </section>

    <section v-if="d && tab === 'bom'" class="card">
      <p v-if="rev === 'A'" class="small">同一物料编号、同一数值和封装合为一行；“物料编号”就是电路板厂清单里的编号（贴片板 SMT-DRV 与成品板 DRV-JOINT 的物料清单按这份设计的数量写，测试核对）。</p>
      <p v-else class="small">B 版：现实里不投产（芯片未流片）；数字工业园里电路板厂试产，贴片板 SMT-DRV-B 与成品板 DRV-JOINT-B 的物料清单按这份设计的数量写（测试核对）。比 A 版多出的见“A→B 改了什么”。</p>
      <table class="tbl">
        <thead><tr><th>物料编号</th><th>数值</th><th>封装</th><th>数量</th><th>位号</th><th>说明</th></tr></thead>
        <tbody><tr v-for="(r, i) in bom" :key="i"><td class="mono">{{ r[0] }}</td><td>{{ r[1] }}</td><td class="small">{{ r[2] }}</td><td>{{ r[3] }}</td>
          <td class="small mono">{{ r[4] }}</td><td class="small">{{ r[5] }}</td></tr></tbody>
      </table>
      <p class="small muted">不进 BOM 的：测试点（ICT 针床、烧录夹具扎的焊盘）、网络连接点（开尔文引线）、安装孔。</p>
    </section>

    <section v-if="d && tab === 'dfm' && dfm" class="card">
      <p class="small">按一份<b>示例板厂工艺能力</b>检查：线宽 / 线距 {{ dfm.capability.track_min }} mm、最小孔 {{ dfm.capability.drill_min }} mm、孔环 {{ dfm.capability.annular_min }} mm、
        阻焊桥 {{ dfm.capability.mask_bridge_min }} mm、元件到板边 {{ dfm.capability.edge_min }} mm、ICT 覆盖率 ≥ {{ Math.round(dfm.capability.ict_coverage_min * 100) }}%。
        结论：<b :class="dfm.pass ? 'ok' : 'bad'">{{ dfm.pass ? '全部通过' : '有不通过的项' }}</b></p>
      <table class="tbl">
        <thead><tr><th>检查</th><th>结果</th><th>这块板</th><th>要求</th><th>为什么板厂在乎</th><th></th></tr></thead>
        <tbody><tr v-for="c in dfm.checks" :key="c.key">
          <td>{{ c.name }}</td><td :class="c.pass ? 'ok' : 'bad'">{{ c.pass ? '✓ 通过' : '✗ 不通过' }}</td>
          <td class="mono">{{ fmt(c.value) }} {{ c.unit }}</td><td class="mono">{{ fmt(c.limit) }} {{ c.unit }}</td>
          <td class="small">{{ c.why }}<div v-if="c.detail" class="muted">{{ c.detail }}</div></td>
          <td><button v-if="c.at.length" class="btn sm" @click="show(c)">在 PCB 上标出</button></td></tr></tbody>
      </table>
    </section>

    <section v-if="d && tab === 'diff' && d.changes" class="card">
      <p class="small">B 版 = A 版 + 编码器接口芯片 WQ-ENCIF（<router-link to="/chip-design">芯片设计</router-link>，第 92 轮）：编码器 A/B/Z 经原来的 RC 滤波进芯片，芯片计数，MCU 用 SPI 读；
        第 110 轮加抱闸驱动：J6 接电机轴上的失电制动抱闸，U16 栅极驱动 + Q7 从母线 PWM 供电，D5 续流，R38 下拉保证 MCU 没输出时抱住；母线铺铜往右接出一条供电。
        同一份设计描述打补丁生成（factory/designs/drv-joint-b/variant.yaml），其余电路一字不动。</p>
      <h3>器件</h3>
      <table class="tbl"><thead><tr><th>位号</th><th>改了什么</th></tr></thead>
        <tbody><tr v-for="(c, i) in d.changes" :key="i"><td class="mono">{{ c.ref }}</td><td class="small">{{ c.what }}</td></tr></tbody></table>
      <h3>MCU 引脚（STM32G431，LQFP-48）</h3>
      <table class="tbl"><thead><tr><th>引脚</th><th>A 版</th><th>B 版</th></tr></thead>
        <tbody><tr v-for="m in d.mcu_pins" :key="m.pin"><td class="mono">{{ m.pin }}</td><td class="mono">{{ m.a || '未用' }}</td><td class="mono">{{ m.b || '未用' }}</td></tr></tbody></table>
      <h3>物料（比 A 版多）</h3>
      <p class="small mono">{{ Object.entries(d.bom_delta).map(([k, n]) => k + ' ' + (n > 0 ? '+' : '') + n).join('、') }}</p>
      <h3>新网络</h3>
      <p class="small mono">{{ d.nets_added.join('、') }}</p>
      <h3>固件要改的配置</h3>
      <ul class="small"><li v-for="(f, i) in d.firmware" :key="i">{{ f }}</li></ul>
      <p class="small"><a href="#" @click.prevent="go('fw')">这段固件已经写好，在 Renode 里跑过 →</a></p>
      <p class="small muted">新增器件放在底面（顶面这一带已满，底面原来只有测试点）；布线、设计规则检查、可制造性检查都按 A 版同一套流程重跑：
        错误 {{ d.drc.errors }}、未连接 {{ d.drc.unconnected }}，可制造性 {{ d.dfm.pass ? '全部通过' : '有不通过' }}。</p>
    </section>

    <section v-if="d && tab === 'fw' && rev === 'B'" class="card">
      <FirmwarePanel />
    </section>

    <section v-if="d && tab === 'dl'" class="card">
      <ul class="dl">
        <li><a :href="url('kicad-project.zip')" download>KiCad 工程（原理图 + PCB，KiCad 7 能打开）</a></li>
        <li><a :href="url('gerber.zip')" download>Gerber 与钻孔文件（给板厂）</a></li>
        <li><a :href="url('bom.csv')" download>BOM（CSV）</a>　<a :href="url('pos.csv')" download>贴片坐标（CSV，给贴片机编程）</a></li>
        <li><a :href="url(stem + '.step')" download>三维 STEP（FreeCAD）</a></li>
        <li><a :href="url('drc.json')" target="_blank">设计规则检查结果</a>　<a :href="url('dfm.json')" target="_blank">可制造性检查结果</a></li>
      </ul>
      <p class="small muted">生成方式：设计描述（器件、数值、引脚接哪个网络）→ 脚本写 KiCad 原理图与 PCB → Freerouting 自动布线 → KiCad 设计规则检查与导出（仓库 factory/designs/tools/build.py）。</p>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import ModelViewer from '../components/ModelViewer.vue';
import FirmwarePanel from '../components/FirmwarePanel.vue';

const STEM = { A: 'drv-joint', B: 'drv-joint-b' };
const TABS = [{ k: 'sch', label: '原理图' }, { k: 'pcb', label: 'PCB' }, { k: '3d', label: '三维' }, { k: 'bom', label: 'BOM' },
  { k: 'dfm', label: '可制造性检查' }, { k: 'diff', label: 'A→B 改了什么', b: true },
  { k: 'fw', label: '固件（Renode 仿真）', b: true }, { k: 'dl', label: '下载' }];
// 原理图这一页 ↔ 电路分析的例题（同一组数）
const EXAMPLE = { sense: 'sense', gate: 'gate', power: 'bus', io: 'encoder' };
const route = useRoute();
const router = useRouter();
const d = ref(null);
const dfm = ref(null);
const bom = ref([]);
const err = ref('');
const tab = ref(route.query.tab || 'sch');
const sheet = ref(route.query.sheet || 'power');
const zoom = ref(1);
const layers = ref(['F_Cu', 'F_Silk']);
const marks = ref([]);
const markTitle = ref('');

const rev = ref(route.query.rev === 'B' ? 'B' : 'A');
const stem = computed(() => STEM[rev.value]);
const url = (p) => '/api/designs/' + stem.value + '/' + p;
function setRev(r) {
  rev.value = r; marks.value = [];
  if (r === 'A' && TABS.find((t) => t.k === tab.value)?.b) tab.value = 'sch';
  router.replace({ query: { ...route.query, rev: r, tab: tab.value } });
  load();
}
const cur = computed(() => d.value?.sheets.find((s) => s.key === sheet.value));
const shownLayers = computed(() => (d.value?.pcb_layers || []).filter((l) => layers.value.includes(l.key)));
function partsOn(key) { return (d.value?.parts || []).filter((p) => p.sheet === key && !p.ref.startsWith('TP') && !p.ref.startsWith('NT')); }
function go(k) { tab.value = k; router.replace({ query: { ...route.query, tab: k } }); }
function pickSheet(k) { sheet.value = k; router.replace({ query: { ...route.query, sheet: k } }); }
function fmt(v) { return typeof v === 'number' ? +v.toFixed(3) : v; }
function show(c) { marks.value = c.at; markTitle.value = c.name; layers.value = ['F_Cu', 'B_Cu', 'F_Silk']; go('pcb'); }
function parseCsv(t) {
  return t.trim().split('\n').slice(1).map((line) => {
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
    if (!r.ok) throw new Error('读不到设计产物（' + r.status + '）');
    d.value = await r.json();
    dfm.value = await (await fetch(url('dfm.json'))).json();
    bom.value = parseCsv(await (await fetch(url('bom.csv'))).text());
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
</style>
