<template>
  <figure class="cz">
    <ol class="chain" aria-label="异常的因果链">
      <li v-for="(n, i) in NODES" :key="n.t" :class="{ lit: i <= lit, sel: i === pick }">
        <button type="button" @click="pick = i; lit = Math.max(lit, i)">
          <span class="k small">{{ n.k }}</span><b>{{ n.t }}</b>
        </button>
        <span v-if="i < NODES.length - 1" class="edge" :class="{ lit: i < lit }" aria-hidden="true"></span>
      </li>
    </ol>
    <div class="why" aria-live="polite">
      <p class="small"><b>{{ NODES[pick].t }}</b>：{{ NODES[pick].why }}</p>
      <p class="small muted">依据：{{ NODES[pick].basis }}</p>
    </div>
    <figcaption class="small muted">示例。厂情中枢的规则每 20 秒查一次全厂；发现异常后，沿着对象之间的关系往前找原因、往后找影响，每一环都附依据（哪条消息、哪个数）。点任一环看它的依据。</figcaption>
  </figure>
</template>

<script setup>
// 异常追因链（ADR-0065）：从根因一环一环亮到影响；点哪环看哪环的依据。
import { onMounted, onUnmounted, ref } from 'vue';

const NODES = [
  { k: '根因', t: '砂轮磨损', why: '磨床已经磨了很多件没有修整，砂轮变钝。', basis: '刀具寿命剩 8%（车间终端，设备状态消息）' },
  { k: '现象', t: '轴承位尺寸上移', why: '砂轮变钝后切得少，零件越磨越大。', basis: '三坐标测量值连续 7 点上升（控制图）' },
  { k: '质量', t: '检验不合格 2 件', why: '尺寸超过上限，判为不合格，送返修。', basis: '检验记录与不合格品单' },
  { k: '生产', t: '工单晚 1 天', why: '返修占用磨床，后面的件排队。', basis: '磨床排队 9 件，工单预计完工时间' },
  { k: '交付', t: '订单有延期风险', why: '这张工单是客户订单的一部分。', basis: '销售订单交期 vs 工单预计完工' },
];
const lit = ref(0);
const pick = ref(0);
let timer;
onMounted(() => {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { lit.value = NODES.length - 1; return; }
  timer = setInterval(() => { if (lit.value < NODES.length - 1) { lit.value += 1; pick.value = lit.value; } else clearInterval(timer); }, 1500);
});
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.cz { margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: #17212B; color: #E4E9EC; }
.chain { list-style: none; display: flex; padding: 0; margin: 0; gap: 0; }
.chain li { display: flex; align-items: center; flex: 1; min-width: 0; }
.chain li:last-child { flex: 0.82; }
.chain button { flex: 1; display: flex; flex-direction: column; gap: 2px; text-align: left; padding: 8px; border-radius: 8px; min-width: 0; font-size: 13px; cursor: pointer;
  background: #22303C; border: 2px solid #34485A; color: #8795A1; transition: all 0.4s; }
.chain .k { color: inherit; }
.chain li.lit button { color: #F4F6F3; border-color: #C98A12; background: #2A3542; }
.chain li.lit:first-child button { border-color: #F08A80; }
.chain li.sel button { box-shadow: 0 0 0 3px var(--brand); }
.chain button:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
.edge { width: 10px; height: 2px; background: #34485A; flex: none; transition: background 0.4s; }
.edge.lit { background: #C98A12; }
.why { margin-top: 12px; min-height: 48px; }
@media (max-width: 640px) { .chain { flex-direction: column; } .chain li { width: 100%; flex-direction: column; } .edge { width: 2px; height: 10px; } }
.why p { margin: 2px 0; }
.why .muted { color: #A9B5BF; }
figcaption { color: #A9B5BF; margin-top: 6px; line-height: 1.7; }
@media (prefers-reduced-motion: reduce) { .chain button, .edge { transition: none; } }
</style>
