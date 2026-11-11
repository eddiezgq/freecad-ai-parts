<!-- 第 103 轮（电子 E9）：芯片封测厂的晶圆图。CP（晶圆测试）后每片晶圆约 3.8 万颗芯片的分档；按探针卡测试位统计失效率，
     帮学生从“图形”追到原因：随机缺陷是散点、成簇，边缘 IDDQ 是一圈，某个测试位探针磨损是一格一格规律地红。 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('晶圆图') }}</h1>
      <span class="muted">{{ $t('CP 做完的每片晶圆：每颗芯片的测试结果画在晶圆上；按探针卡的 8 个测试位分开看失效率，找出是芯片坏了还是测试没扎好') }}</span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div class="cols">
      <section class="card list">
        <div class="card-head"><h2>{{ $t('最近的晶圆（{a} 片）', { a: $td(list.length) }) }}</h2></div>
        <div v-if="!list.length" class="small muted">{{ $t('还没有。接一张 WQ-ENCIF 订单，或下一张“已测晶圆 WAF-ENCIF-CP”工单，让车间做到“晶圆测试 CP”。') }}</div>
        <button v-for="w in list" :key="w.serial" class="brd" :class="{ on: sel === w.serial }" @click="open(w.serial)">
          <span class="mono">{{ $td(w.serial) }}</span>
          <span class="small" :class="w.pass ? 'ok' : 'bad'">{{ $t('良率 {a} %', { a: w.yield_pct.toFixed(1) }) }}</span>
          <span class="small muted">{{ $t('最差测试位 {a}：{b} %', { a: $td(w.worst_site), b: w.site_fail_pct[w.worst_site - 1] }) }}</span>
          <span class="spark"><i v-for="(f, k) in w.site_fail_pct" :key="k" :style="{ height: Math.min(100, f * 2) + '%' }" :class="{ hot: f > 15 }" /></span>
        </button>
      </section>
      <section v-if="m" class="card main">
        <div class="card-head"><h2>{{ $td(m.serial) }} · <small class="muted">{{ $t('工单 {a}　{b} 颗　良率 {c} %', { a: $td(m.work_order), b: m.total.toLocaleString(), c: m.yield_pct.toFixed(2) }) }}</small></h2></div>
        <div class="grid2">
          <div>
            <canvas ref="cv" class="wafer" :width="CW" :height="CW" @mousemove="hover" @mouseleave="tip = ''" />
            <div class="small muted">{{ tip || $t('把鼠标移到芯片上看坐标、测试位、分档') }}</div>
            <div class="legend small">
              <span v-for="(n, b) in m.bins" :key="b"><i :style="{ background: COL[b] }" />{{ $t('{a}（{b}）', { a: n, b: m.by_bin[b].toLocaleString() }) }}</span>
            </div>
            <label class="small"><input v-model.number="only" type="number" min="0" max="8" style="width: 3em" /> {{ $t('只看第几测试位（0 = 全部）') }}</label>
          </div>
          <div>
            <h3>{{ $t('按测试位的失效率') }}</h3>
            <div class="sbars">
              <div v-for="(f, k) in m.site_fail_pct" :key="k" class="sbar">
                <div class="sb" :class="{ hot: f > 15 }" :style="{ height: (78 * f / Math.max(...m.site_fail_pct, 1)) + '%' }" />
                <div class="small mono">{{ f }}%</div><div class="small">{{ $t('位 {a}', { a: k + 1 }) }}</div>
              </div>
            </div>
            <table class="tbl small">
              <thead><tr><th>{{ $t('测试位') }}</th><th v-for="k in 8" :key="k">{{ k }}</th></tr></thead>
              <tbody><tr><td>{{ $t('接触电阻 Ω') }}</td><td v-for="(r, k) in m.site_rc" :key="k" class="mono" :class="{ bad: r > 2.5 }">{{ r.toFixed(2) }}</td></tr></tbody>
            </table>
            <p class="small">{{ $t('探针卡一次扎') }} <b>{{ $t('2 行 × 4 列') }}</b> {{ $t('共 8 颗芯片：测试位 1–4 在上一行、5–8 在下一行。某个测试位的探针磨损、接触电阻升高时，它扎到的芯片会被误判“开路”——晶圆图上就是每隔 4 列、每隔 1 行规律地红一颗；而真正的缺陷是散点、成簇，IDDQ 超标集中在边缘一圈。误判的芯片其实是好的，复测能过；不清洁 / 不换探针卡，每片都白白损失这些好芯片。') }}</p>
            <p class="small muted">{{ $t('示例：200 mm 晶圆、步距 {a} mm、边缘去除 {b} mm；缺陷率、簇、接触电阻阈值 2.5 Ω 都是示例值。', { a: $td(m.pitch_mm), b: $td(m.edge_mm) }) }}</p>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { nextTick, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { get } from '../lib/api';

const COL = { 1: '#86efac', 2: '#ef4444', 3: '#f59e0b', 4: '#7c3aed' };
const CW = 460;
const list = ref([]);
const sel = ref('');
const m = ref(null);
const err = ref('');
const only = ref(0);
const tip = ref('');
const cv = ref(null);
const route = useRoute();

function draw() {
  const c = cv.value; if (!c || !m.value) return;
  const g = c.getContext('2d'); const n = m.value.n; const px = CW / n;
  g.clearRect(0, 0, CW, CW);
  g.fillStyle = '#e5e7eb'; g.beginPath(); g.arc(CW / 2, CW / 2, CW / 2 - 1, 0, 2 * Math.PI); g.fill();
  m.value.rows.forEach((row, i) => {
    for (let j = 0; j < n; j++) {
      const b = row[j]; if (b === ' ') continue;
      const s = (i % 2) * 4 + (j % 4) + 1;
      g.fillStyle = only.value && s !== only.value ? '#f3f4f6' : COL[b];
      g.fillRect(j * px, i * px, Math.max(1, px - 0.2), Math.max(1, px - 0.2));
    }
  });
  g.fillStyle = '#374151'; g.beginPath(); g.moveTo(CW / 2 - 6, CW - 2); g.lineTo(CW / 2 + 6, CW - 2); g.lineTo(CW / 2, CW - 9); g.fill();   // 缺口
}
function hover(e) {
  if (!m.value) return;
  const r = cv.value.getBoundingClientRect(); const n = m.value.n;
  const j = Math.floor((e.clientX - r.left) / r.width * n); const i = Math.floor((e.clientY - r.top) / r.height * n);
  const b = m.value.rows[i]?.[j];
  tip.value = b && b !== ' ' ? $t('行 ') + i + $t('、列 ') + j + $t('、测试位 ') + ((i % 2) * 4 + (j % 4) + 1) + $t('：') + m.value.bins[b] : '';
}
async function open(s) {
  sel.value = s; err.value = '';
  try { m.value = await get('/chip/wafer/' + encodeURIComponent(s)); await nextTick(); draw(); } catch (e) { err.value = e.message; }
}
watch(only, draw);
onMounted(async () => {
  try {
    list.value = (await get('/chip/wafers')).wafers;
    const want = route.query.serial || (list.value[0] && list.value[0].serial);
    if (want) open(want);
  } catch (e) { err.value = e.message; }
});
</script>

<style scoped>
.cols { display: grid; grid-template-columns: minmax(220px, 300px) 1fr; gap: 12px; }
@media (max-width: 800px) { .cols { grid-template-columns: 1fr; } }
.brd { display: grid; grid-template-columns: 1fr auto; gap: 2px 8px; width: 100%; text-align: left; border: 1px solid #e3e6ee; background: #fff; border-radius: 8px; padding: 6px 8px; margin: 4px 0; cursor: pointer; }
.brd.on { border-color: #1d4ed8; background: #eff6ff; }
.spark { grid-column: 1 / -1; display: flex; gap: 2px; height: 18px; align-items: flex-end; }
.spark i { flex: 1; background: #93c5fd; min-height: 1px; } .spark i.hot { background: #dc2626; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }
.wafer { width: 100%; max-width: 460px; height: auto; display: block; }
.legend { display: flex; flex-wrap: wrap; gap: 10px; margin: 6px 0; } .legend i { display: inline-block; width: 10px; height: 10px; margin-right: 4px; border-radius: 2px; }
.sbars { display: flex; gap: 6px; align-items: stretch; height: 160px; margin: 6px 0 4px; }
.sbar { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; }
.sb { width: 70%; background: #60a5fa; border-radius: 3px 3px 0 0; min-height: 2px; } .sb.hot { background: #dc2626; }
.tbl { width: 100%; border-collapse: collapse; margin: 6px 0; } .tbl th, .tbl td { border-bottom: 1px solid #eef0f5; padding: 3px 4px; text-align: center; }
.ok { color: #15803d; } .bad { color: #b91c1c; }
</style>
