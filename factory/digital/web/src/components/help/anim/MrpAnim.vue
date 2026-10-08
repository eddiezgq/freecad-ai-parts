<template>
  <figure class="mrp">
    <div class="ctl">
      <label for="mrp-qty">订单数量</label>
      <input id="mrp-qty" v-model.number="qty" type="range" min="1" max="40" aria-describedby="mrp-note">
      <b class="mono">{{ qty }} 台</b>
      <button class="btn sm" @click="replay">从头演示</button>
    </div>
    <ol class="phases" aria-label="算料四步">
      <li v-for="(p, i) in PHASES" :key="p" :class="{ on: i <= phase }"><span>{{ i + 1 }}</span>{{ p }}</li>
    </ol>
    <div class="tablewrap">
      <table>
        <thead><tr><th>物料</th><th class="num">每台用量</th><th class="num">毛需求</th>
          <th class="num" :class="{ dim: phase < 1 }">库存</th><th class="num" :class="{ dim: phase < 1 }">在途</th>
          <th class="num" :class="{ dim: phase < 2 }">净需求</th><th :class="{ dim: phase < 3 }">动作</th></tr></thead>
        <tbody>
          <tr v-for="r in rows" :key="r.code" :class="{ need: phase >= 2 && r.net > 0 }">
            <td><b>{{ r.name }}</b> <span class="small muted">{{ r.kind }}</span></td>
            <td class="num">{{ r.per }} {{ r.uom }}</td>
            <td class="num">{{ fmt(r.gross) }}</td>
            <td class="num" :class="{ dim: phase < 1 }">{{ r.stock }}</td>
            <td class="num" :class="{ dim: phase < 1 }">{{ r.onOrder }}</td>
            <td class="num" :class="{ dim: phase < 2 }">{{ fmt(r.net) }}</td>
            <td :class="{ dim: phase < 3 }"><span v-if="phase >= 3" class="act" :class="r.actKind">{{ r.action }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
    <figcaption id="mrp-note" class="small muted">示例数据，不是本厂的。净需求 = 毛需求 − 库存 − 在途；采购按批量取整，自制件按净需求下工单。拖动数量看哪一行先变红。</figcaption>
  </figure>
</template>

<script setup>
// MRP 展开（ADR-0065）：拖订单数量，看毛需求、扣库存和在途、净需求、请购或工单怎么跟着变。分四步演示。
import { computed, onMounted, onUnmounted, ref } from 'vue';

const PHASES = ['按 BOM 展开毛需求', '扣掉库存和在途', '得出净需求', '生成工单和请购'];
const BOM = [
  { code: 'FG', name: '成品', kind: '订单', per: 1, uom: '台', stock: 0, onOrder: 0, make: true, lot: 1 },
  { code: 'SH', name: '输出轴', kind: '自制件', per: 1, uom: '件', stock: 4, onOrder: 0, make: true, lot: 1 },
  { code: 'BRG', name: '轴承', kind: '外购件', per: 2, uom: '个', stock: 16, onOrder: 10, make: false, lot: 10 },
  { code: 'RM', name: '45 钢棒料', kind: '原材料', per: 0.6, uom: 'kg', stock: 5, onOrder: 0, make: false, lot: 50 },
];
const qty = ref(10);
const phase = ref(3);
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
let timer;

const rows = computed(() => BOM.map((b) => {
  const gross = +(b.per * qty.value).toFixed(2);
  const net = Math.max(0, +(gross - b.stock - b.onOrder).toFixed(2));
  let action = '库存够用';
  let actKind = 'ok';
  if (net > 0) {
    if (b.make) { action = `工单 ${Math.ceil(net)} ${b.uom}`; actKind = 'wo'; } else {
      action = `请购 ${Math.ceil(net / b.lot) * b.lot} ${b.uom}（批量 ${b.lot}）`; actKind = 'mr';
    }
  }
  return { ...b, gross, net, action, actKind };
}));
const fmt = (v) => (Number.isInteger(v) ? v : v.toFixed(1));

function replay() {
  clearInterval(timer);
  if (reduced) { phase.value = 3; return; }
  phase.value = 0;
  timer = setInterval(() => { if (phase.value >= 3) clearInterval(timer); else phase.value += 1; }, 1300);
}
onMounted(replay);
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.mrp { margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); }
.ctl { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.ctl input[type=range] { flex: 1; min-width: 160px; accent-color: var(--accent); }
.phases { list-style: none; display: flex; gap: 6px; padding: 0; margin: 0 0 10px; flex-wrap: wrap; }
.phases li { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); padding: 4px 10px 4px 4px; border-radius: 999px;
  background: var(--surface-2); transition: background 0.3s, color 0.3s; }
.phases li span { width: 18px; height: 18px; border-radius: 50%; display: grid; place-items: center; background: var(--line); font-weight: 700; font-size: 11px; }
.phases li.on { background: var(--task-bg); color: var(--ink); }
.phases li.on span { background: var(--brand); }
.tablewrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { padding: 7px 8px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
th { font-weight: 600; background: var(--surface-2); }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.dim { opacity: 0.25; transition: opacity 0.4s; }
td, th { transition: opacity 0.4s; }
tr.need td { background: var(--bad-bg); }
.act { padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.act.ok { background: var(--good-bg); color: var(--good); }
.act.wo { background: var(--accent-bg); color: var(--accent); }
.act.mr { background: var(--warn-bg); color: var(--warn-ink); }
figcaption { margin-top: 8px; }
</style>
