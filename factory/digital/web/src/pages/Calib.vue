<!-- 整机标定（第 55 轮，机器人厂）：一台 WQ-CR5 的测量位姿、标定前后误差、辨识出的参数偏差；可以换位姿（数量、铺满 / 集中）重新辨识。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>整机标定</h1>
      <span class="muted">激光跟踪仪测工具点 → 最小二乘辨识 24 个参数偏差 → 补偿 → 另取 20 个位姿验证（误差量级、噪声都是示例值）</span></div>
    <div v-if="err" class="err">{{ err }}</div>

    <section class="card" data-help="calib-robots">
      <div class="card-head"><h2>做过标定的机器人</h2><span class="muted small">整机标定工位每做完一台出一行</span>
        <button class="btn ghost sm more" @click="load">刷新</button></div>
      <p v-if="list && !list.robots.length" class="empty">还没有。先在“订单与计划”接一台 WQ-CR5，做到整机标定。</p>
      <div v-else-if="list" class="scroll"><table class="tbl small">
        <thead><tr><th>出厂编号</th><th>工单</th><th class="num">标定前（mm）</th><th class="num">标定后（mm）</th><th class="num">条件数</th><th>判定</th></tr></thead>
        <tbody><tr v-for="r in list.robots" :key="r.serial" :class="{ sel: r.serial === serial }" @click="choose(r.serial)">
          <td class="mono">{{ r.serial }}</td><td class="mono">{{ r.work_order }}</td><td class="num">{{ f3(r.before_mm) }}</td><td class="num">{{ f3(r.after_mm) }}</td>
          <td class="num">{{ r.cond ?? '—' }}</td><td :class="r.pass ? 'ok' : 'bad-t'">{{ r.pass ? '合格' : '不合格' }}</td></tr></tbody></table></div>
    </section>

    <template v-if="serial">
      <section class="card ctl" data-help="calib-controls">
        <b class="mono">{{ serial }}</b>
        <label>测量位姿 <select v-model.number="n" aria-label="位姿数" @change="run"><option v-for="k in [6, 8, 12, 20, 30, 50]" :key="k" :value="k">{{ k }} 个</option></select></label>
        <span class="cks"><label><input v-model="spread" type="radio" value="full" @change="run"> 铺满工作空间</label>
          <label><input v-model="spread" type="radio" value="cluster" @change="run"> 集中在常用姿态附近 ±10°</label></span>
        <span v-if="busy" class="muted small">计算中…</span>
      </section>

      <template v-if="r">
        <section class="kpis" data-help="calib-result">
          <div class="card k"><span class="small muted">条件数</span><b :class="{ warn: r.cond > 100 }">{{ r.cond }}</b>
            <span class="small muted">分得开的参数组合 {{ r.rank }} / {{ r.params }}</span></div>
          <div class="card k"><span class="small muted">标定前（验证 20 个位姿）</span><b>{{ f3(r.before_mean_mm) }} mm</b><span class="small muted">最大 {{ f3(r.before_max_mm) }}</span></div>
          <div class="card k"><span class="small muted">标定后</span><b :class="r.pass ? 'ok' : 'bad-t'">{{ f3(r.after_mean_mm) }} mm</b>
            <span class="small muted">最大 {{ f3(r.after_max_mm) }}；≤ {{ r.limit_mm }} 合格</span></div>
        </section>

        <div class="two">
          <section class="card">
            <div class="card-head"><h2>测量位姿（工具点）</h2><span class="muted small">俯视 x–y、侧视 x–z（mm）</span></div>
            <div class="views">
              <svg v-for="v in views" :key="v.key" :viewBox="'0 0 ' + W + ' ' + W" class="view" role="img" :aria-label="v.label">
                <rect x="0" y="0" :width="W" :height="W" class="frame" />
                <line :x1="W / 2" y1="0" :x2="W / 2" :y2="W" class="axis" /><line x1="0" :y1="W / 2" :x2="W" :y2="W / 2" class="axis" />
                <circle v-for="(p, i) in r.points_mm" :key="i" :cx="sx(p[v.a])" :cy="sy(p[v.b])" r="3.5" class="pt" />
                <text x="6" y="14" class="lbl">{{ v.label }}</text>
              </svg>
            </div>
          </section>
          <section class="card">
            <div class="card-head"><h2>验证：每个位姿的误差</h2><span class="muted small"><i class="sw b"></i> 标定前 <i class="sw a"></i> 标定后（mm）；红虚线 = {{ r.limit_mm }} mm 合格线</span></div>
            <svg :viewBox="'0 0 ' + BW + ' ' + BH" class="bars" role="img" aria-label="验证误差">
              <line :x1="0" :y1="by(r.limit_mm)" :x2="BW" :y2="by(r.limit_mm)" class="lim" />
              <g v-for="(v, i) in r.verify_before_mm" :key="i">
                <rect :x="i * bw + 2" :y="by(v)" :width="bw / 2 - 2" :height="BH - by(v)" class="b" />
                <rect :x="i * bw + bw / 2" :y="by(r.verify_after_mm[i])" :width="bw / 2 - 2" :height="BH - by(r.verify_after_mm[i])" class="a" />
              </g>
            </svg>
          </section>
        </div>

        <section class="card" data-help="calib-params">
          <div class="card-head"><h2>辨识出的参数偏差</h2>
            <span class="muted small">相邻平行轴（J2、J3、J4）沿轴向的偏距只分得出它们的和：分不开的组合按最小范数取</span></div>
          <div class="scroll"><table class="tbl small">
            <thead><tr><th>关节</th><th class="num">零位 Δθ（°）</th><th class="num">偏距 Δd（mm）</th><th class="num">连杆长度 Δa（mm）</th><th class="num">扭角 Δα（°）</th>
              <th v-if="r.truth" class="num">老师：真实 Δθ（°）</th></tr></thead>
            <tbody><tr v-for="(p, i) in r.identified" :key="p.joint"><td>{{ p.joint }}</td><td class="num">{{ p.dtheta_deg }}</td><td class="num">{{ p.dd_mm }}</td>
              <td class="num">{{ p.da_mm }}</td><td class="num">{{ p.dalpha_deg }}</td><td v-if="r.truth" class="num">{{ r.truth[i].dtheta_deg }}</td></tr></tbody></table></div>
          <p class="small muted">名义 DH 参数（示例值）与实验 26 的任务在“实验与任务 → 实验 26”。</p>
        </section>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { get } from '../lib/api';

const route = useRoute();
const list = ref(null);
const serial = ref('');
const n = ref(30);
const spread = ref('full');
const r = ref(null);
const err = ref('');
const busy = ref(false);
const W = 220;
const BW = 400;
const BH = 160;
const f3 = (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(3));
const views = [{ key: 'xy', a: 0, b: 1, label: '俯视 x–y' }, { key: 'xz', a: 0, b: 2, label: '侧视 x–z' }];
const R = 1000;                                      // 坐标范围 ±1000 mm
const sx = (v) => W / 2 + (v / R) * (W / 2 - 6);
const sy = (v) => W / 2 - (v / R) * (W / 2 - 6);
const bw = computed(() => BW / Math.max(1, r.value?.verify_before_mm.length || 1));
const top = computed(() => Math.max(1, ...(r.value?.verify_before_mm || [1]), ...(r.value?.verify_after_mm || [1])) * 1.1);
const by = (v) => BH - (Math.min(v, top.value) / top.value) * (BH - 14);

async function load() {
  try {
    list.value = await get('/calib');
    if (!serial.value) {
      const want = route.query.serial;
      const s0 = list.value.robots.find((x) => x.serial === want) || list.value.robots[0];
      if (s0) await choose(s0.serial);
    }
    err.value = '';
  } catch (e) { err.value = e.message; }
}
async function choose(s) { serial.value = s; await run(); }
async function run() {
  busy.value = true;
  try { r.value = await get(`/calib/${encodeURIComponent(serial.value)}?n=${n.value}&spread=${spread.value}`); err.value = ''; } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
onMounted(load);
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.more { margin-left: auto; }
.scroll { overflow-x: auto; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
.tbl tbody tr { cursor: pointer; }
.tbl tr.sel td { background: var(--surface-2); }
.num { text-align: right !important; }
.ctl { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 13px; }
select { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 12px; }
.k { display: flex; flex-direction: column; gap: 2px; }
.k b { font-size: 22px; }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
.views { display: flex; gap: 8px; flex-wrap: wrap; }
.view { width: calc(50% - 4px); min-width: 140px; max-width: 260px; }
.frame { fill: var(--surface-2); stroke: var(--line); }
.axis { stroke: var(--line); stroke-dasharray: 3 3; }
.pt { fill: var(--accent, #2b6cb0); opacity: 0.8; }
.lbl { font-size: 11px; fill: var(--muted, #777); }
.bars { width: 100%; height: auto; }
.bars .b, .sw.b { fill: #c9b8a6; background: #c9b8a6; }
.bars .a, .sw.a { fill: #2b8a5f; background: #2b8a5f; }
.sw { display: inline-block; width: 10px; height: 10px; margin: 0 2px 0 8px; vertical-align: -1px; }
.lim { stroke: var(--bad, #c0392b); stroke-dasharray: 4 3; }
.ok { color: var(--good); }
.bad-t { color: var(--bad); }
.warn { color: var(--warn-ink); }
</style>
