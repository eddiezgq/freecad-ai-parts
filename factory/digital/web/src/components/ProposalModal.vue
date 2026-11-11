<template>
  <div class="modal-mask" @click.self="$emit('close')">
    <div class="modal" role="dialog" aria-modal="true" :aria-label="p?.title || t('提议')">
      <div v-if="!p" class="muted">{{ t('载入中…') }}</div>
      <template v-else>
        <div class="head">
          <h2>{{ td(p.title) }}</h2>
          <span class="pill" :class="statusTone">{{ statusText }}</span>
        </div>
        <p class="muted small">{{ t('提议') }} <span class="mono">{{ p.proposal_id }}</span> · {{ t('由 {w} 起草', { w: p.requested_by }) }} ·
          {{ t('确认后才由桥接写入 ERPNext（统一数据总线 ai/proposal）') }}</p>

        <template v-if="p.action === 'create_order_and_plan'">
          <h3>{{ t('销售订单') }}</h3>
          <table class="t"><tbody>
            <tr><td>{{ t('客户') }}</td><td>{{ bi(so.customer) }}</td><td>{{ t('产品') }}</td><td class="mono">{{ so.item_code }} × {{ so.qty }}</td></tr>
            <tr><td>{{ t('交期') }}</td><td class="mono">{{ so.delivery_date }}</td><td>{{ t('金额') }}</td><td class="mono">{{ so.amount ? '$' + so.amount.toLocaleString() : '—' }}</td></tr>
          </tbody></table>
          <h3>{{ t('算料结果（MRP）') }}</h3>
          <table class="t">
            <thead><tr><th>{{ t('物料') }}</th><th>{{ t('名称') }}</th><th class="num">{{ t('毛需求') }}</th><th class="num">{{ t('其他订单占用') }}</th>
              <th class="num">{{ t('库存') }}</th><th class="num">{{ t('在途') }}</th><th class="num">{{ t('安全库存') }}</th><th class="num">{{ t('净需求') }}</th><th>{{ t('动作') }}</th></tr></thead>
            <tbody>
              <tr v-for="r in pv.mrp" :key="r.item_code" :class="{ need: r.net > 0 }">
                <td class="mono">{{ r.item_code }}</td><td>{{ isEn() ? bi(r.name) : r.name.split(' ')[0] }}</td>
                <td class="num">{{ n(r.gross) }}</td><td class="num">{{ n(r.committed) }}</td><td class="num">{{ n(r.stock) }}</td>
                <td class="num">{{ n(r.on_order) }}</td><td class="num">{{ n(r.safety) }}</td><td class="num">{{ n(r.net) }}</td>
                <td>{{ td(r.action) }}</td>
              </tr>
            </tbody>
          </table>
          <p class="muted small">{{ td(pv.basis) }}</p>
          <h3>{{ t('工单（本轮只下达输出轴 SH-301）') }}</h3>
          <table class="t">
            <thead><tr><th>{{ t('物料') }}</th><th class="num">{{ t('数量') }}</th><th>{{ t('计划开工') }}</th><th>{{ t('计划完工') }}</th><th class="num">{{ t('理论工时') }}</th></tr></thead>
            <tbody><tr v-for="w in pv.work_orders" :key="w.production_item">
              <td class="mono">{{ w.production_item }}</td><td class="num">{{ w.qty }}</td><td class="mono">{{ w.planned_start_date }}</td>
              <td class="mono">{{ w.expected_delivery_date }}</td><td class="num">{{ t('{n} 分钟', { n: w.est_minutes }) }}</td></tr></tbody>
          </table>
          <p v-if="pv.deferred?.length" class="muted small">{{ t('其余自制件（{l}）列出需求但本轮不下达工单（实施细则决定 F4）。', { l: pv.deferred.map((d) => d.item_code).join(', ') }) }}</p>
        </template>
        <template v-if="pv.material_requests?.length">
          <h3>{{ t('请购单') }}</h3>
          <table class="t">
            <thead><tr><th>{{ t('物料') }}</th><th class="num">{{ t('数量') }}</th><th>{{ t('需求日期') }}</th><th>{{ t('建议供应商') }}</th><th>{{ t('说明') }}</th></tr></thead>
            <tbody><tr v-for="m in pv.material_requests" :key="m.item_code">
              <td class="mono">{{ m.item_code }}</td><td class="num">{{ m.qty }} {{ m.uom }}</td><td class="mono">{{ m.schedule_date }}</td>
              <td>{{ isEn() ? bi(m.supplier) : short(m.supplier) }}</td><td class="small">{{ td(m.reason) }}</td></tr></tbody>
          </table>
        </template>
        <template v-if="p.action === 'eto_quote'">
          <table class="t"><tbody>
            <tr><td>{{ t('作业号') }}</td><td class="mono">{{ pv.job.job_no }}</td><td>{{ t('客户') }}</td><td>{{ bi(pv.job.customer) }}</td></tr>
            <tr><td>{{ t('名称') }}</td><td>{{ pv.job.title }}</td><td>{{ t('估算版本') }}</td><td>{{ t('第 {r} 版', { r: pv.job.rev }) }}</td></tr>
            <tr><td>{{ t('报价') }}</td><td class="mono">{{ pv.quotation.qty }} × {{ money(pv.quotation.rate) }} = {{ money(pv.quotation.amount) }}</td>
              <td>{{ t('有效期至') }}</td><td class="mono">{{ pv.quotation.valid_till }}</td></tr>
          </tbody></table>
          <h3>{{ t('数量阶梯') }}</h3>
          <table class="t">
            <thead><tr><th class="num">{{ t('数量') }}</th><th class="num">{{ t('成本') }}</th><th class="num">{{ t('单价') }}</th><th class="num">{{ t('合计') }}</th></tr></thead>
            <tbody><tr v-for="b in pv.breaks" :key="b.qty"><td class="num">{{ b.qty }}</td><td class="num mono">{{ money(b.cost) }}</td>
              <td class="num mono">{{ money(b.unit_price) }}</td><td class="num mono">{{ money(b.price) }}</td></tr></tbody>
          </table>
          <p class="muted small">{{ t('确认后在 ERPNext 建：项目 {p}（作业号）、物料 {i}、报价单（条款写数量阶梯和付款条件）。', { p: pv.project.project_name, i: pv.item.item_code }) }}</p>
        </template>
        <template v-if="p.action === 'eto_order'">
          <table class="t"><tbody>
            <tr><td>{{ t('作业号') }}</td><td class="mono">{{ pv.job.job_no }}</td><td>{{ t('客户') }}</td><td>{{ bi(pv.sales_order.customer) }}</td></tr>
            <tr><td>{{ t('订单') }}</td><td class="mono">{{ pv.sales_order.qty }} × {{ money(pv.sales_order.rate) }} = {{ money(pv.sales_order.amount) }}</td>
              <td>{{ t('交期') }}</td><td class="mono">{{ pv.sales_order.delivery_date }}</td></tr>
          </tbody></table>
          <h3>{{ t('付款计划') }}</h3>
          <table class="t">
            <thead><tr><th>{{ t('名称') }}</th><th class="num">{{ t('比例') }}</th><th class="num">{{ t('金额') }}</th><th>{{ t('计划日期') }}</th></tr></thead>
            <tbody><tr v-for="m in pv.sales_order.payment_schedule" :key="m.key"><td>{{ bi(m.description) }}</td><td class="num">{{ m.invoice_portion }}%</td>
              <td class="num mono">{{ money(m.payment_amount) }}</td><td class="mono">{{ m.due_date }}</td></tr></tbody>
          </table>
          <p class="muted small">{{ t('确认后在 ERPNext 建销售订单（引用报价单 {q}、挂项目 {p}）。各期到了里程碑才开票。', { q: pv.sales_order.quotation, p: pv.sales_order.project }) }}</p>
        </template>
        <template v-if="p.action === 'eto_materials'">
          <p>{{ t('作业 {j}（设计第 {r} 版）：工单、请购单都挂作业号，专料专用。', { j: pv.job.job_no, r: pv.job.design_rev }) }}</p>
          <h3>{{ t('工单') }}</h3>
          <table class="t">
            <thead><tr><th>{{ t('物料') }}</th><th class="num">{{ t('数量') }}</th><th>{{ t('计划开工') }}</th><th>{{ t('计划完工') }}</th><th class="num">{{ t('理论工时') }}</th></tr></thead>
            <tbody><tr v-for="w in pv.work_orders" :key="w.production_item">
              <td class="mono">{{ w.production_item }}</td><td class="num">{{ w.qty }}</td><td class="mono">{{ w.planned_start_date }}</td>
              <td class="mono">{{ w.expected_delivery_date }}</td><td class="num">{{ t('{n} 分钟', { n: w.est_minutes }) }}</td></tr></tbody>
          </table>
        </template>
        <template v-if="p.action === 'eto_change'">
          <p>{{ t('作业 {j}：设计第 {a} 版 → 第 {b} 版，旧单据逐条处理。', { j: pv.job.job_no, a: pv.job.from_rev, b: pv.job.rev }) }}</p>
          <table class="t">
            <thead><tr><th>{{ t('单据') }}</th><th>{{ t('处理') }}</th><th class="num">{{ t('变更损失') }}</th></tr></thead>
            <tbody><tr v-for="a in pv.actions" :key="a.doctype + a.name"><td class="mono">{{ a.name }}</td><td>{{ t(a.action_zh) }}
              <span v-if="a.lines" class="muted small">{{ a.lines.map((l) => l.item_code + ' → ' + l.qty).join(', ') }}</span></td>
              <td class="num mono">{{ a.loss === null || a.loss === undefined ? (a.action === 'keep' ? '' : t('未知')) : (a.loss ? money(a.loss) : '') }}</td></tr></tbody>
          </table>
          <p class="muted small">{{ t('确认后在 ERPNext 取消、停止、改量或关闭这些单据；“照用”只在平台记下。处理完再算料，按新版补工单和请购。') }}</p>
        </template>
        <template v-if="p.action === 'eto_ship'">
          <p>{{ t('作业 {j}：按销售订单 {s} 发货 {n} 件给 {c}。首件、终检、不合格品处置都已核过。', { j: pv.job.job_no, s: pv.sales_order, n: pv.qty, c: bi(pv.job.customer) }) }}</p>
          <p class="muted small">{{ t('确认后在 ERPNext 建发货单（发货那一期到了，可以在“开票与毛利”开票）。') }}</p>
        </template>
        <template v-if="p.action === 'eto_invoice'">
          <p>{{ t('作业 {j}：按销售订单 {s} 开第“{d}”期发票 {a}（{p}%），客户 {c}，到期 {u}。', { j: pv.job.job_no, s: pv.sales_order, d: bi(pv.description), a: '$' + Number(pv.amount).toLocaleString('en-US', { minimumFractionDigits: 2 }), p: pv.pct, c: bi(pv.job.customer), u: pv.due_date }) }}</p>
          <p class="muted small">{{ t('这一期的里程碑已经到了。确认后在 ERPNext 开销售发票（金额按接单时定的付款计划）。') }}</p>
        </template>
        <template v-if="p.action === 'eto_inspection'">
          <p>{{ t('{k} {w} 第 {n} 件：{r}，写进 ERPNext 质量检验单。', { k: pv.kind === 'fai' ? t('首件检验') : t('终检'), w: pv.work_order, n: pv.piece, r: pv.result }) }}</p>
        </template>
        <template v-if="p.action === 'eto_hours'">
          <p>{{ t('作业 {j}：{h} 小时设计工时（{w}，{d}）进 ERPNext 工时表，挂项目 {p}。', { j: pv.job.job_no, h: pv.hours, w: pv.who, d: pv.day, p: pv.job.project }) }}</p>
        </template>
        <template v-if="p.action === 'eto_early_buy'">
          <p class="warns">{{ t('设计第 {r} 版还没发布：这些长周期件先请购，设计改了要人处理这些请购单。', { r: pv.job.design_rev }) }}</p>
        </template>
        <template v-if="p.action === 'eto_release'">
          <p>{{ t('作业 {j} 第 {r} 版设计，指纹 {f}', { j: pv.job.job_no, r: pv.job.rev, f: pv.fingerprint.slice(0, 12) }) }}</p>
          <h3>{{ t('新物料') }}</h3>
          <table class="t">
            <thead><tr><th>{{ t('编号') }}</th><th>{{ t('名称') }}</th><th>{{ t('类别') }}</th><th class="num">{{ t('单价') }}</th></tr></thead>
            <tbody><tr v-for="i in pv.items" :key="i.code"><td class="mono">{{ i.code }}</td><td>{{ i.name }}</td><td>{{ td(i.item_group) }}</td>
              <td class="num mono">{{ money(i.price) }}</td></tr></tbody>
          </table>
          <h3>{{ t('物料清单（子件先建）') }}</h3>
          <div v-for="b in pv.boms" :key="b.item" class="small"><b class="mono">{{ b.item }}</b>
            {{ t('：{c}；{n} 道工序', { c: b.components.map((c) => c.item_code + ' × ' + c.qty).join(', '), n: b.operations.length }) }}</div>
          <p v-if="pv.affected?.length" class="warns">{{ t('改版影响：{a}', { a: pv.affected.map((a) => a.name).join(', ') }) }}</p>
          <p class="muted small">{{ t('确认后在 ERPNext 建新物料和物料清单（带工序）并设为默认；这一版冻结，再改出新版本。') }}</p>
        </template>
        <template v-if="p.action === 'release_work_order'">
          <p>{{ t('把工单 {w} 按工艺路线逐道派给车间设备。', { w: pv.work_order }) }}</p>
        </template>
        <div v-if="pv.warnings?.length" class="warns">
          <b>{{ t('注意') }}</b><div v-for="w in pv.warnings" :key="w">{{ td(w) }}</div>
        </div>

        <div v-if="p.results?.length" class="results">
          <h3>{{ t('ERPNext 写入结果') }}</h3>
          <div v-for="r in p.results" :key="r.doctype + r.name" class="small">
            <span :class="r.action === 'failed' ? 'err' : 'ok'">{{ r.action === 'failed' ? t('失败') : t('已建') }}</span>
            {{ r.doctype }} <b class="mono">{{ r.name }}</b> {{ r.error || '' }}
          </div>
        </div>
        <div v-if="error" class="err">{{ error }}</div>
        <div class="actions">
          <button class="btn ghost" @click="$emit('close')">{{ t('关闭') }}</button>
          <template v-if="p.status === 'pending'">
            <button class="btn danger" :disabled="busy" @click="decide('reject')">{{ t('否决') }}</button>
            <button class="btn primary" :disabled="busy" @click="decide('confirm')">{{ t('确认执行') }}</button>
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
import { bi, isEn, t, td, tk } from '../lib/i18n';

const props = defineProps({ pid: String });
const emit = defineEmits(['close', 'done']);
const p = ref(null);
const busy = ref(false);
const error = ref(null);
let timer;
const pv = computed(() => p.value?.preview || {});
const so = computed(() => pv.value.sales_order || {});
const STATUS = { pending: tk('待确认'), confirmed: tk('已确认，执行中'), executed: tk('已执行'), rejected: tk('已否决'), failed: tk('执行失败') };
const statusText = computed(() => t(STATUS[p.value?.status] || ''));
const statusTone = computed(() => ({ pending: 'warn', confirmed: 'info', executed: 'good', rejected: 'mute', failed: 'bad' }[p.value?.status]));
const money = (x) => (x === null || x === undefined ? '—' : '$' + Number(x).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
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
