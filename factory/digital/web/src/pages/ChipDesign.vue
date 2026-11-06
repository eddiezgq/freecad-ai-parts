<!-- 第 92 轮（电子 E5）：芯片设计。编码器接口芯片 WQ-ENCIF：规格、Verilog、仿真波形（RTL 与参考模型逐拍一致）、综合、版图（SKY130，LibreLane）、
     检查（DRC / LVS / 时序 / 天线）、接上编码器（行为模型 + 逻辑分析仪）、下载。示例设计，未流片。 -->
<template>
  <div class="page">
    <div class="page-title"><h1>芯片设计</h1>
      <span class="muted">{{ d ? d.name + '（' + d.rev + '，' + d.pdk + '，' + d.clock_mhz + ' MHz）' : '读取中…' }}</span></div>
    <div v-if="d" class="warn small">⚠ {{ d.disclaimer }}。这颗芯片接在关节驱动板的编码器上，把 A/B/Z 脉冲变成计数，MCU 用 SPI 来读（驱动板这一版仍由 MCU 直接读编码器）。</div>
    <div v-if="err" class="err">{{ err }}</div>
    <div class="tabs">
      <button v-for="t in TABS" :key="t.k" class="tab" :class="{ on: tab === t.k }" @click="go(t.k)">{{ t.label }}</button>
    </div>

    <section v-if="d && tab === 'spec'" class="card">
      <h3>里面有什么</h3>
      <div class="flow">
        <template v-for="(b, i) in d.blocks" :key="b.key"><div class="blk"><b>{{ b.name }}</b><div class="small">{{ b.desc }}</div></div>
          <div v-if="i < d.blocks.length - 1" class="arrow">→</div></template>
      </div>
      <h3>引脚</h3>
      <table class="tbl"><thead><tr><th>引脚</th><th>方向</th><th>作用</th></tr></thead>
        <tbody><tr v-for="p in d.pins" :key="p.name"><td class="mono">{{ p.name }}</td><td>{{ p.dir }}</td><td>{{ p.desc }}</td></tr></tbody></table>
      <h3>寄存器</h3>
      <table class="tbl"><thead><tr><th>地址</th><th>名字</th><th>读写</th><th>复位值</th><th>位</th></tr></thead>
        <tbody><tr v-for="r in d.regs" :key="r.addr"><td class="mono">{{ r.addr }}</td><td class="mono">{{ r.name }}</td><td>{{ r.access }}</td><td class="mono">{{ r.reset }}</td>
          <td class="small"><div v-for="b in r.bits" :key="b[0]"><span class="mono">[{{ b[0] }}]</span> {{ b[1] }}</div></td></tr></tbody></table>
      <p class="small">SPI 一帧：CS 拉低 → 8 位命令（最高位 1 = 写，低 7 位是地址）→ 32 位数据，高位先出；SCLK 上升沿采样（模式 0）。例：读计数发 <span class="mono">0x03</span>，写滤波长度 5 发 <span class="mono">0x81 0x00000051</span>。</p>
    </section>

    <section v-if="d && tab === 'rtl'" class="card">
      <p class="small">Verilog 原文（{{ d.rtl_lines }} 行，可综合的 Verilog-2005，单时钟）。仿真、综合、版图都由这一份生成。</p>
      <pre class="code"><code><span v-for="(l, i) in rtlLines" :key="i" class="ln"><i>{{ i + 1 }}</i>{{ l }}
</span></code></pre>
    </section>

    <section v-if="d && tab === 'sim'" class="card">
      <p class="small">每个用例由 Python 参考模型逐拍算出“应该是多少”，Icarus Verilog 跑 RTL，<b>逐拍比对</b>；再和按规格书手算的值核对（{{ d.sim?.tool }}）。</p>
      <table class="tbl"><thead><tr><th>用例</th><th>拍数</th><th>与参考模型</th><th>最后计数</th><th>SPI 读回</th><th></th></tr></thead>
        <tbody><tr v-for="c in d.sim?.cases || []" :key="c.name">
          <td>{{ c.name }}</td><td>{{ c.cycles }}</td><td :class="c.match ? 'ok' : 'bad'">{{ c.match ? '✓ 逐拍一致' : '✗ 第 ' + c.first_mismatch + ' 拍不同' }}</td>
          <td class="mono">{{ c.final.count }}</td><td class="small mono">{{ c.reads.slice(0, 4).map((r) => REGNAME[r.addr] + '=' + hex(r.value)).join('  ') }}{{ c.reads.length > 4 ? ' …' : '' }}</td>
          <td><button class="btn sm" :class="{ on: wcase === c.wave }" @click="loadWave(c.wave)">看波形</button></td></tr></tbody></table>
      <div v-if="wave" class="wavebox">
        <div class="line small"><b>{{ wave.case }}</b> 第 {{ win[0] }}–{{ win[1] }} 拍（1 拍 = 20 ns）
          <label>起点 <input v-model.number="w0" type="range" :min="0" :max="Math.max(0, wave.n - span)" step="10"></label>
          <label>宽度 <select v-model.number="span"><option :value="200">200 拍</option><option :value="600">600</option><option :value="2000">2000</option><option :value="6000">6000</option><option :value="wave.n">全部（{{ wave.n }}）</option></select></label></div>
        <svg class="wave" :viewBox="'0 0 1000 ' + wave.signals.length * 26" preserveAspectRatio="none">
          <g v-for="(s, i) in wave.signals" :key="s.name" :transform="'translate(0,' + i * 26 + ')'">
            <text x="2" y="16" class="wn">{{ s.name }}</text>
            <path :d="wpath(s)" :class="s.bus ? 'wbus' : 'wbit'" />
            <template v-if="s.bus"><text v-for="(l, k) in wlabels(s)" :key="k" :x="l[0]" y="16" class="wv">{{ l[1] }}</text></template>
          </g>
        </svg>
      </div>
    </section>

    <section v-if="d && tab === 'syn'" class="card">
      <template v-if="L">
        <p class="small">Yosys 把 Verilog 综合成 SKY130 标准单元（门级网表），再由 OpenROAD 布局布线（LibreLane 流程）。数都取自工具报告。</p>
        <div class="kpis">
          <div class="kpi"><b>{{ L.logic_cells }}</b><span>逻辑单元</span></div><div class="kpi"><b>{{ L.flipflops }}</b><span>触发器</span></div>
          <div class="kpi"><b>{{ fmt(L.stdcell_area_um2, 0) }}</b><span>单元面积 μm²</span></div><div class="kpi"><b>{{ fmt(L.die_area_um2, 0) }}</b><span>芯片面积 μm²</span></div>
          <div class="kpi"><b>{{ L.power_total_w != null ? fmt(L.power_total_w * 1000, 3) : '—' }}</b><span>功耗估计 mW</span></div>
          <div class="kpi"><b>{{ L.wire_length_um != null ? fmt(L.wire_length_um / 1000, 2) : '—' }}</b><span>连线总长 mm</span></div></div>
        <h3>各类单元</h3>
        <div v-for="(n, k) in L.cells_by_kind" :key="k" class="krow"><span>{{ k }}</span><span class="ktrack"><span class="kfill" :style="{ width: 100 * n / maxKind + '%' }"></span></span><span class="kn">{{ n }}</span></div>
        <p class="small muted">去耦电容、填充、衬底接触是版图上必须放的“非逻辑”单元：稳电源、填满空位、把衬底接到电源和地。</p>
        <h3>用得最多的单元</h3>
        <p class="small mono">{{ L.cells_top.map((c) => c[0] + ' ×' + c[1]).join('、') }}</p>
      </template>
      <p v-else class="muted">版图产物还没生成（CI 的“芯片版图”工作流跑完后提交）。</p>
    </section>

    <section v-if="d && tab === 'lay'" class="card">
      <template v-if="IM">
        <div class="line">
          <button class="chip" :class="{ on: lay === 'all' }" @click="lay = 'all'">全部层</button>
          <button v-for="l in IM.layers.filter((x) => x.present)" :key="l.key" class="chip" :class="{ on: lay === l.key }" @click="lay = l.key">{{ l.name }}</button>
          <label class="small">放大 <input v-model.number="zoom" type="range" min="1" max="6" step="0.25"></label>
          <label class="small"><input v-model="detail" type="checkbox"> 看中心 30 × 30 μm 的单元</label></div>
        <div class="small muted">芯片 {{ IM.die_um[0] }} × {{ IM.die_um[1] }} μm（GDS 由 LibreLane 生成，KLayout 出图；颜色是 SKY130 的层颜色）</div>
        <div class="canvas"><div v-if="!detail" class="stack" :style="{ width: zoom * 100 + '%' }">
          <img :src="url('layout/' + layPng)" class="ly" :alt="lay"></div>
          <img v-else :src="url('layout/' + IM.detail.png)" :style="{ width: zoom * 60 + '%' }" alt="局部">
        </div>
      </template>
      <p v-else class="muted">版图还没生成。</p>
    </section>

    <section v-if="d && tab === 'chk'" class="card">
      <template v-if="L">
        <p class="small">结论：<b :class="L.pass ? 'ok' : 'bad'">{{ L.pass ? '全部通过，可以出 GDS' : '有不通过的项' }}</b>（{{ d.pdk }}，{{ d.clock_mhz }} MHz；时序按全部工艺角查，最慢的是 100 °C、1.6 V）</p>
        <table class="tbl"><thead><tr><th>检查</th><th>结果</th><th>数</th><th>查的是什么</th></tr></thead>
          <tbody><tr v-for="c in CHECKS" :key="c.k"><td>{{ c.name }}</td><td :class="L.clean[c.k] ? 'ok' : 'bad'">{{ L.clean[c.k] ? '✓ 通过' : '✗ 不通过' }}</td>
            <td class="mono">{{ c.v(L) }}</td><td class="small">{{ c.why }}</td></tr></tbody></table>
        <p v-if="L.max_slew_violations" class="small muted">提示：最慢工艺角（100 °C、1.6 V）下有 {{ L.max_slew_violations }} 处信号边沿偏慢（max slew），工具只报警告、不影响时序结论；量产前要再加缓冲器修掉。</p>
      </template>
      <p v-else class="muted">版图还没生成。</p>
    </section>

    <section v-if="d && tab === 'bench'" class="card">
      <p class="small">把芯片接到电机编码器上（{{ B.lines }} 线），用<b>逻辑分析仪</b>看：原始 A/B（带干扰毛刺）、芯片滤波后的 A/B、计数，以及最后 MCU 用 SPI 读计数的那一帧。芯片用的是与 RTL 逐拍一致的行为模型。</p>
      <div class="line">
        <label class="small">转速 <input v-model.number="B.rpm" type="range" min="300" max="6000" step="100"> {{ B.rpm }} rpm</label>
        <label class="small">方向 <select v-model.number="B.dir"><option :value="1">正转</option><option :value="-1">反转</option></select></label>
        <label class="small">滤波长度 N <input v-model.number="B.flen" type="range" min="0" max="8" step="1"> {{ B.flen }}（{{ (B.flen + 1) * 20 }} ns 以下的毛刺滤掉）</label>
        <label class="small">毛刺 <input v-model.number="B.glitch" type="range" min="0" max="0.1" step="0.01"> 每微秒 {{ B.glitch }} 个，最宽 {{ B.gmax * 20 }} ns
          <input v-model.number="B.gmax" type="range" min="1" max="6" step="1"></label>
      </div>
      <div v-if="bres" class="kpis">
        <div class="kpi"><b class="mono">{{ bres.readValue }}</b><span>SPI 读回的计数</span></div>
        <div class="kpi"><b>{{ bres.glitches }}</b><span>打了几个毛刺</span></div>
        <div class="kpi"><b :class="bres.passed ? 'bad' : 'ok'">{{ bres.passed }}</b><span>穿过滤波的</span></div>
        <div class="kpi"><b :class="bres.steps > bclean.steps ? 'bad' : 'ok'">{{ bres.steps - bclean.steps }}</b><span>计数多跳了几下（一来一回）</span></div>
        <div class="kpi"><b>{{ fmt(bres.edgesPerS / 1e3, 1) }} k</b><span>每秒边沿</span></div></div>
      <div class="line small">看 <select v-model="bwin"><option value="spi">SPI 读计数那一帧</option><option value="start">开头（写 CTRL）</option><option v-for="(g, i) in bres?.marks.filter((m) => m.glitch).slice(0, 12) || []" :key="i" :value="'g' + g.at">毛刺 @ 第 {{ g.at }} 拍（{{ g.width * 20 }} ns）</option></select></div>
      <svg v-if="bres" class="wave" :viewBox="'0 0 1000 ' + BSIG.length * 26" preserveAspectRatio="none">
        <g v-for="(s, i) in BSIG" :key="s.k" :transform="'translate(0,' + i * 26 + ')'">
          <text x="2" y="16" class="wn">{{ s.name }}</text>
          <path :d="bpath(s)" :class="s.bus ? 'wbus' : 'wbit'" />
          <template v-if="s.bus"><text v-for="(l, k) in blabels(s)" :key="k" :x="l[0]" y="16" class="wv">{{ l[1] }}</text></template>
        </g>
      </svg>
      <p class="small muted">{{ bwinText }}</p>
      <div class="line"><router-link class="btn" to="/instruments?task=encoder">去虚拟仪器量一台真编码器 →</router-link>
        <router-link class="btn" to="/pcb-design?tab=sch&sheet=io">驱动板的编码器接口这一页 →</router-link></div>
    </section>

    <section v-if="d && tab === 'dl'" class="card">
      <ul class="dl">
        <li><a :href="url('wq-encif.zip')" download>全部文件（Verilog、测试平台、参考模型、LibreLane 配置；有版图时含 GDS、门级网表、DEF、时序约束、报告）</a></li>
        <li v-if="L"><a :href="url('layout/wq_encif.gds')" download>GDS（版图，KLayout / Magic 能打开）</a>　<a :href="url('layout/wq_encif.nl.v')" download>门级网表</a>　<a :href="url('layout/metrics.json')" target="_blank">全部指标</a></li>
        <li><a :href="url('sim/summary.json')" target="_blank">仿真结果</a></li>
      </ul>
      <p class="small muted">生成方式：Verilog（factory/designs/wq-encif/rtl）→ Icarus 仿真与参考模型逐拍比对 → LibreLane（Yosys 综合、OpenROAD 布局布线、Magic / KLayout 检查、Netgen 版图对原理图）→ KLayout 出图。
        综合与版图在 CI 的“芯片版图”工作流里用微电子实验的基础镜像跑。</p>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { bench } from '../lib/encif.js';

const BASE = '/api/designs/wq-encif/';
const TABS = [{ k: 'spec', label: '规格' }, { k: 'rtl', label: 'Verilog' }, { k: 'sim', label: '仿真' }, { k: 'syn', label: '综合' },
  { k: 'lay', label: '版图' }, { k: 'chk', label: '检查' }, { k: 'bench', label: '接上编码器' }, { k: 'dl', label: '下载' }];
const REGNAME = { 0: 'ID', 1: 'CTRL', 2: 'STATUS', 3: 'COUNT', 4: 'INDEX' };
const CHECKS = [
  { k: 'drc', name: '设计规则（DRC）', v: (l) => l.magic_drc_errors + (l.klayout_drc_errors != null ? ' / ' + l.klayout_drc_errors : ''), why: '线宽、间距、包围这些工艺规则（Magic 与 KLayout 各查一遍）：不满足就造不出来' },
  { k: 'lvs', name: '版图对原理图（LVS）', v: (l) => l.lvs_errors, why: '从版图里提取出的电路和门级网表是不是同一个电路（Netgen）' },
  { k: 'setup', name: '建立时间', v: (l) => fmt(l.setup_ws_ns, 3) + ' ns 余量', why: '信号在下一个时钟沿之前到得了：余量为正，50 MHz 跑得动' },
  { k: 'hold', name: '保持时间', v: (l) => fmt(l.hold_ws_ns, 3) + ' ns 余量', why: '信号不会变得太快、冲掉上一拍的值' },
  { k: 'antenna', name: '天线效应', v: (l) => l.antenna_violations ?? '—', why: '制造时长金属线积累电荷会击穿栅氧，太长的线要加二极管或跳层' },
];
const route = useRoute();
const router = useRouter();
const d = ref(null);
const err = ref('');
const tab = ref(route.query.tab || 'spec');
const wave = ref(null);
const wcase = ref('');
const w0 = ref(0);
const span = ref(600);
const zoom = ref(1);
const lay = ref('all');
const detail = ref(false);
const B = reactive({ rpm: 3000, dir: 1, flen: 3, glitch: 0.04, gmax: 3, lines: 1000 });
const bres = ref(null);
const bclean = ref(null);
const bwin = ref('spi');

const url = (p) => BASE + p;
const L = computed(() => d.value?.layout || null);
const IM = computed(() => d.value?.images || null);
const layPng = computed(() => (lay.value === 'all' ? IM.value?.all : IM.value?.layers.find((l) => l.key === lay.value)?.png));
const rtlLines = computed(() => (d.value?.rtl || '').split('\n'));
const maxKind = computed(() => Math.max(1, ...Object.values(L.value?.cells_by_kind || { x: 1 })));
const win = computed(() => [w0.value, Math.min(wave.value?.n || 0, w0.value + span.value)]);
function go(k) { tab.value = k; router.replace({ query: { ...route.query, tab: k } }); }
function fmt(v, n = 2) { return typeof v === 'number' ? +v.toFixed(n) : (v ?? '—'); }
function hex(v) { return '0x' + (v >>> 0).toString(16).toUpperCase(); }

// ---------------------------------------------------------------- 波形（仿真）：pts = [[拍, 值], …] 只记变化
function wpath(s) {
  const [a, b] = win.value; const X = (t) => 120 + (880 * (t - a)) / Math.max(1, b - a);
  const pts = s.pts; let v = valAt(pts, a); let p = '';
  if (s.bus) {
    const xs = [a, ...pts.filter((q) => q[0] > a && q[0] < b).map((q) => q[0]), b];
    for (let i = 0; i < xs.length - 1; i++) { const x0 = X(xs[i]); const x1 = X(xs[i + 1]); p += `M${x0 + 2},4 L${x1 - 2},4 M${x0 + 2},20 L${x1 - 2},20 M${x0},12 L${x0 + 2},4 M${x0},12 L${x0 + 2},20 M${x1},12 L${x1 - 2},4 M${x1},12 L${x1 - 2},20 `; }
    return p;
  }
  const Y = (x) => (x === '1' ? 4 : 20);
  p = `M120,${Y(v)}`;
  for (const q of pts) { if (q[0] <= a) continue; if (q[0] >= b) break; p += ` L${X(q[0])},${Y(v)} L${X(q[0])},${Y(q[1])}`; v = q[1]; }
  return p + ` L1000,${Y(v)}`;
}
function valAt(pts, t) { let v = pts.length ? pts[0][1] : '0'; for (const q of pts) { if (q[0] > t) break; v = q[1]; } return v; }
function wlabels(s) {
  const [a, b] = win.value; const X = (t) => 120 + (880 * (t - a)) / Math.max(1, b - a);
  const xs = [a, ...s.pts.filter((q) => q[0] > a && q[0] < b).map((q) => q[0]), b];
  const out = [];
  for (let i = 0; i < xs.length - 1; i++) if (X(xs[i + 1]) - X(xs[i]) > 24) out.push([X(xs[i]) + 4, valAt(s.pts, xs[i])]);
  return out;
}
async function loadWave(fn) {
  wcase.value = fn;
  wave.value = await (await fetch(url('sim/' + fn))).json();
  w0.value = 0; span.value = wave.value.n <= 600 ? wave.value.n : 600;
}

// ---------------------------------------------------------------- 接上编码器（行为模型 + 逻辑分析仪）
const BSIG = [{ k: 'A', name: 'A（原始）' }, { k: 'B', name: 'B（原始）' }, { k: 'fA', name: 'A 滤波后' }, { k: 'fB', name: 'B 滤波后' },
  { k: 'cnt', name: '计数', bus: true }, { k: 'CS_N', name: 'CS_N' }, { k: 'SCLK', name: 'SCLK' }, { k: 'MOSI', name: 'MOSI' }, { k: 'MISO', name: 'MISO' }];
const bw = computed(() => {
  const r = bres.value; if (!r) return [0, 1];
  if (bwin.value === 'spi') return [r.readAt - 20, Math.min(r.cycles, r.readAt + 430)];
  if (bwin.value === 'start') return [0, 460];
  const at = +bwin.value.slice(1); return [Math.max(0, at - 60), Math.min(r.cycles, at + 140)];
});
const bwinText = computed(() => {
  if (!bres.value) return '';
  if (bwin.value === 'spi') return 'MCU 发命令 0x03（读 COUNT），芯片在命令收齐那一拍取快照，随后 32 位从 MISO 高位先出：读回 ' + bres.value.readValue + '。';
  if (bwin.value === 'start') return '复位后写 CTRL（命令 0x81 + 数据），设定滤波长度。';
  return '原始 A/B 上的毛刺：宽度不到 N+1 拍的，滤波后的 A/B 上看不到，计数也不跳；够宽的就穿过去，计数一来一回。';
});
function bpath(s) {
  const [a, b] = bw.value; const arr = bres.value.tr[s.k]; const X = (t) => 120 + (880 * (t - a)) / Math.max(1, b - a);
  if (s.bus) {
    let p = ''; let st = a;
    for (let t = a + 1; t <= b; t++) if (t === b || arr[t] !== arr[t - 1]) { const x0 = X(st); const x1 = X(t); p += `M${x0 + 1},4 L${x1 - 1},4 M${x0 + 1},20 L${x1 - 1},20 M${x0},12 L${x0 + 1},4 M${x0},12 L${x0 + 1},20 `; st = t; }
    return p;
  }
  const Y = (x) => (x ? 4 : 20); let p = `M120,${Y(arr[a])}`;
  for (let t = a + 1; t < b; t++) if (arr[t] !== arr[t - 1]) p += ` L${X(t)},${Y(arr[t - 1])} L${X(t)},${Y(arr[t])}`;
  return p + ` L1000,${Y(arr[b - 1])}`;
}
function blabels(s) {
  const [a, b] = bw.value; const arr = bres.value.tr[s.k]; const X = (t) => 120 + (880 * (t - a)) / Math.max(1, b - a);
  const out = []; let st = a;
  for (let t = a + 1; t <= b; t++) if (t === b || arr[t] !== arr[t - 1]) { if (X(t) - X(st) > 22) out.push([X(st) + 3, arr[st]]); st = t; }
  return out;
}
function runBench() {
  const o = { rpm: B.rpm, dir: B.dir, lines: B.lines, flen: B.flen, glitchMax: B.gmax };
  bres.value = bench({ ...o, glitchPerUs: B.glitch });
  bclean.value = bench({ ...o, glitchPerUs: 0 });
}
watch(B, runBench);

onMounted(async () => {
  try {
    const r = await fetch(url('design.json'));
    if (!r.ok) throw new Error('读不到芯片设计产物（' + r.status + '）');
    d.value = await r.json();
    if (d.value.sim?.cases?.length) loadWave(d.value.sim.cases[0].wave);
    runBench();
  } catch (e) { err.value = e.message || String(e); }
});
</script>

<style scoped>
.warn { background: #fff7e6; border: 1px solid #f5c26b; padding: 6px 10px; border-radius: 6px; margin: 6px 0; }
.tabs { display: flex; flex-wrap: wrap; gap: 4px; margin: 8px 0; }
.line { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 6px 0; }
.flow { display: flex; flex-wrap: wrap; align-items: stretch; gap: 6px; }
.blk { flex: 1 1 150px; border: 1px solid #c7d2fe; background: #eef2ff; border-radius: 8px; padding: 6px 8px; }
.arrow { align-self: center; color: #64748b; }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; margin: 6px 0; }
.tbl th, .tbl td { border-bottom: 1px solid #eef0f5; padding: 4px 6px; text-align: left; vertical-align: top; }
.code { background: #0f172a; color: #e2e8f0; padding: 8px; border-radius: 8px; max-height: 70vh; overflow: auto; font-size: 12px; line-height: 1.45; }
.ln i { display: inline-block; width: 3.2em; color: #64748b; font-style: normal; user-select: none; }
.wavebox { margin-top: 8px; }
.wave { width: 100%; height: auto; min-height: 200px; background: #0b1220; border-radius: 8px; }
.wn { fill: #93c5fd; font-size: 11px; }
.wv { fill: #fde68a; font-size: 10px; }
.wbit { fill: none; stroke: #4ade80; stroke-width: 1.2; vector-effect: non-scaling-stroke; }
.wbus { fill: none; stroke: #fbbf24; stroke-width: 1; vector-effect: non-scaling-stroke; }
.kpis { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
.kpi { border: 1px solid #e3e6ee; border-radius: 8px; padding: 6px 10px; min-width: 110px; }
.kpi b { display: block; font-size: 18px; } .kpi span { font-size: 12px; color: #64748b; }
.krow { display: grid; grid-template-columns: 7em 1fr 3.5em; align-items: center; gap: 8px; font-size: 13px; margin: 3px 0; }
.ktrack { height: 12px; background: #f1f5f9; border-radius: 3px; overflow: hidden; }
.kfill { display: block; height: 100%; background: #60a5fa; } .kn { color: #475569; }
.canvas { overflow: auto; max-height: 75vh; border: 1px solid #e3e6ee; border-radius: 8px; background: #000; }
.stack { position: relative; }
.stack .ly { width: 100%; display: block; }
.chip { border: 1px solid #ccd; background: #fff; border-radius: 14px; padding: 3px 10px; cursor: pointer; font-size: 13px; }
.chip.on { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
.ok { color: #15803d; } .bad { color: #b91c1c; }
.dl li { margin: 6px 0; }
.btn.sm { padding: 1px 8px; font-size: 12px; } .btn.on { background: #1d4ed8; color: #fff; }
</style>
