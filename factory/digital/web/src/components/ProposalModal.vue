<template>
  <div class="modal-mask" @click.self="$emit('close')">
    <div class="modal" role="dialog" aria-modal="true" :aria-label="p?.title || '提议'">
      <div v-if="!p" class="muted">载入中…</div>
      <template v-else>
        <div class="head">
          <h2>{{ p.title }}</h2>
          <span class="pill" :class="statusTone">{{ statusText }}</span>
        </div>
        <p class="muted small">提议 <span class="mono">{{ p.proposal_id }}</span> · 由 {{ p.requested_by }} 起草 ·
          确认后才由桥接写入 ERPNext（统一数据总线 ai/proposal）</p>

        <template v-if="p.action === 'create_order_and_plan'">
          <h3>销售订单</h3>
          <table class="t"><tbody>
            <tr><td>客户</td><td>{{ so.customer }}</td><td>产品</td><td class="mono">{{ so.item_code }} × {{ so.qty }}</td></tr>
            <tr><td>交期</td><td class="mono">{{ so.delivery_date }}</td><td>金额</td><td class="mono">{{ so.amount ? '$' + so.amount.toLocaleString() : '—' }}</td></tr>
          </tbody></table>
          <h3>算料结果（MRP）</h3>
          <table class="t">
            <thead><tr><th>物料</th><th>名称</th><th class="num">毛需求</th><th class="num">其他订单占用</th>
              <th class="num">库存</th><th class="num">在途</th><th class="num">安全库存</th><th class="num">净需求</th><th>动作</th></tr></thead>
            <tbody>
              <tr v-for="r in pv.mrp" :key="r.item_code" :class="{ need: r.net > 0 }">
                <td class="mono">{{ r.item_code }}</td><td>{{ r.name.split(' ')[0] }}</td>
                <td class="num">{{ n(r.gross) }}</td><td class="num">{{ n(r.committed) }}</td><td class="num">{{ n(r.stock) }}</td>
                <td class="num">{{ n(r.on_order) }}</td><td class="num">{{ n(r.safety) }}</td><td class="num">{{ n(r.net) }}</td>
                <td>{{ r.action }}</td>
              </tr>
            </tbody>
          </table>
          <p class="muted small">{{ pv.basis }}</p>
          <h3>工单（本轮只下达输出轴 SH-301）</h3>
          <table class="t">
            <thead><tr><th>物料</th><th class="num">数量</th><th>计划开工</th><th>计划完工</th><th class="num">理论工时</th></tr></thead>
            <tbody><tr v-for="w in pv.work_orders" :key="w.production_item">
              <td class="mono">{{ w.production_item }}</td><td class="num">{{ w.qty }}</td><td class="mono">{{ w.planned_start_date }}</td>
              <td class="mono">{{ w.expected_delivery_date }}</td><td class="num">{{ w.est_minutes }} 分钟</td></tr></tbody>
          </table>
          <p v-if="pv.deferred?.length" class="muted small">其余自制件（{{ pv.deferred.map((d) => d.item_code).join('、') }}）
            列出需求但本轮不下达工单（实施细则决定 F4）。</p>
        </template>
        <template v-if="pv.material_requests?.length">
          <h3>请购单</h3>
          <table class="t">
            <thead><tr><th>物料</th><th class="num">数量</th><th>需求日期</th><th>建议供应商</th><th>说明</th></tr></thead>
            <tbody><tr v-for="m in pv.material_requests" :key="m.item_code">
              <td class="mono">{{ m.item_code }}</td><td class="num">{{ m.qty }} {{ m.uom }}</td><td class="mono">{{ m.schedule_date }}</td>
              <td>{{ short(m.supplier) }}</td><td class="small">{{ m.reason }}</td></tr></tbody>
          </table>
        </template>
        <template v-if="p.action === 'release_work_order'">
          <p>把工单 <b class="mono">{{ pv.work_order }}</b> 按工艺路线逐道派给车间设备。</p>
        </template>
        <div v-if="pv.warnings?.length" class="warns">
          <b>注意</b><div v-for="w in pv.warnings" :key="w">{{ w }}</div>
        </div>

        <div v-if="p.results?.length" class="results">
          <h3>ERPNext 写入结果</h3>
          <div v-for="r in p.results" :key="r.doctype + r.name" class="small">
            <span :class="r.action === 'failed' ? 'err' : 'ok'">{{ r.action === 'failed' ? '失败' : '已建' }}</span>
            {{ r.doctype }} <b class="mono">{{ r.name }}</b> {{ r.error || '' }}
          </div>
        </div>
        <div v-if="error" class="err">{{ error }}</div>
        <div class="actions">
          <button class="btn ghost" @click="$emit('close')">关闭</button>
          <template v-if="p.status === 'pending'">
            <button class="btn danger" :disabled="busy" @click="decide('reject')">否决</button>
            <button class="btn primary" :disabled="busy" @click="decide('confirm')">确认执行</button>
          </template>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { get, post } from '../lib/api';
import { short } from '../lib/fmt';

const props = defineProps({ pid: String });
const emit = defineEmits(['close', 'done']);
const p = ref(null);
const busy = ref(false);
const error = ref(null);
let timer;
const pv = computed(() => p.value?.preview || {});
const so = computed(() => pv.value.sales_order || {});
const statusText = computed(() => ({ pending: '待确认', confirmed: '已确认，执行中', executed: '已执行', rejected: '已否决', failed: '执行失败' }[p.value?.status]));
const statusTone = computed(() => ({ pending: 'warn', confirmed: 'info', executed: 'good', rejected: 'mute', failed: 'bad' }[p.value?.status]));
const n = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 }));

async function load() { p.value = await get('/proposals/' + props.pid); }
async function decide(d) {
  busy.value = true; error.value = null;
  try {
    await post(`/proposals/${props.pid}/${d}`);
    await load();
    if (d === 'confirm') {
      timer = setInterval(async () => {
        await load();
        if (['executed', 'failed'].includes(p.value.status)) { clearInterval(timer); emit('done', p.value); }
      }, 1500);
    }
  } catch (e) { error.value = e.message; } finally { busy.value = false; }
}
onMounted(load);
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.head { display: flex; align-items: center; gap: 12px; }
h3 { font-size: 14px; margin: 18px 0 8px; }
tr.need td { background: #FFF8EC; }
.warns { margin-top: 12px; background: var(--warn-bg); border-radius: 8px; padding: 10px 12px; font-size: 13px; color: var(--warn-ink); }
.results { margin-top: 12px; }
.actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
</style>
