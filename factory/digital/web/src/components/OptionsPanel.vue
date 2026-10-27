<!-- 指挥台右栏“推演与建议”（第 17 轮 C 期 C8）：按预案自动推演几个方案，推荐一个，可以采纳生成动作 -->
<template>
  <div class="op">
    <div class="op-h"><h3>推演与建议</h3>
      <span v-if="data" class="small muted">{{ data.service ? '按服务排班估算 · 现场日 ' + data.factory_now : (data.exact ? '精确快照' : '近似快照') + ' · ' + fmtTs(data.factory_now) }}<template v-if="data.shift_mode"> ·
        {{ data.shift_mode === 'shift' ? '按班次' : '24 小时连续' }}</template></span>
      <button class="linkbtn" :disabled="busy" @click="load">{{ busy ? '推演中…' : '重新推演' }}</button></div>
    <div v-if="busy && !data" class="small muted">正在用当前快照推演各方案…</div>
    <div v-if="err" class="small err">{{ err }}</div>
    <template v-if="data">
      <p v-if="!data.options.length" class="small muted">这类异常还没有处理方案。</p>
      <p v-if="data.locked" class="small lockn">比对模式（实验 15）：先在实验页提交你自己的因果链和方案选择，提交后这里才显示“建议”和推荐理由。推演数字照常可看。</p>
      <p v-if="data.reason" class="reason small">{{ data.reason }}<span v-if="data.reason_by && data.reason_by !== 'rules'" class="muted"> · AI 改写</span></p>
      <div v-for="o in data.options" :key="o.key" class="opt" :class="{ rec: o.recommended, bad: !o.result.ok }">
        <div class="o-h"><b>{{ o.key }}</b> {{ o.label }} <span v-if="o.recommended" class="pill good">建议</span>
          <span v-if="!o.result.ok" class="pill bad">校验不通过</span></div>
        <div v-if="o.note" class="small muted">{{ o.note }}</div>
        <div v-if="o.result.service" class="small svc">
          <div>{{ o.result.service.units }} 台 · {{ o.result.service.engineers.join('、') || '排不进' }} · {{ o.result.service.days }} 天做完（到 {{ o.result.service.finish || '—' }}）</div>
          <div v-if="Object.keys(o.result.service.spares).length" class="muted">备件：{{ Object.entries(o.result.service.spares).map(([k, q]) => k + ' × ' + q).join('、') }}</div>
          <div class="muted">保修内由工厂承担 ${{ Math.round(o.result.service.cost.warranty).toLocaleString() }}，向客户收 ${{ Math.round(o.result.service.cost.billable).toLocaleString() }} · 涉及客户 {{ o.result.service.customers.length }} 个</div>
          <details><summary class="muted">派工明细</summary><ul class="sos"><li v-for="j in o.result.service.jobs" :key="j.serial">{{ j.serial }}（{{ j.customer }}）：{{ j.kind_label }} → {{ j.engineer_name || '待定' }} {{ j.day || '' }}{{ j.other_region ? '（跨区域）' : '' }}</li></ul></details>
          <div v-if="o.uncovered_high?.length" class="err">还有 {{ o.uncovered_high.length }} 台高风险设备没覆盖</div>
        </div>
        <ul v-else class="small sos">
          <li v-for="s in o.result.sales_orders" :key="s.name">{{ s.name }}：
            <template v-if="s.late_days === null">{{ s.note || '做不完' }}</template>
            <template v-else>预计 {{ s.projected }} 交，<b :class="s.late_days > 0 ? 'late' : 'ok'">{{ s.late_days > 0 ? '晚 ' + s.late_days + ' 天' : '按时（余 ' + (-s.late_days) + ' 天）' }}</b></template>
            <span v-if="s.split" class="muted">；首批 {{ s.split.first_qty }} 台 {{ s.split.first_projected }}</span>
          </li>
        </ul>
        <div v-if="o.result.energy" class="small muted">未来 24 小时：{{ Math.round(o.result.energy.kwh).toLocaleString() }} 度，其中空转 {{ Math.round(o.result.energy.idle).toLocaleString() }} 度；
          电费 ${{ o.result.energy.cost.toFixed(2) }}，峰时占 {{ Math.round(o.result.energy.peak_share * 100) }}%；碳 {{ Math.round(o.result.energy.co2_kg) }} kg</div>
        <div class="small">{{ o.result.cost_total < 0 ? '省' : '多花' }} <b>${{ Math.abs(o.result.cost_total) < 100 ? Math.abs(o.result.cost_total).toFixed(2) : Math.round(Math.abs(o.result.cost_total)).toLocaleString() }}</b><template v-if="o.result.overtime_min"> · 加班 {{ o.result.overtime_min }} 分钟 × {{ o.result.overtime_units }} 台</template></div>
        <div v-for="(c, i) in o.result.checks.filter((x) => !x.ok)" :key="i" class="small err">{{ c.text }}</div>
        <div v-if="o.kind !== 'none'" class="o-a">
          <button v-if="data.can_initiate" class="btn sm" :class="o.recommended ? 'primary' : ''" :disabled="!o.result.ok || adopting"
            @click="adopt(o)">采纳，生成动作</button>
          <router-link v-if="!data.service" :to="{ path: '/ont/sim', query: { a: anomalyId, opt: o.key, snap: data.snapshot_id } }" class="small">在推演工作台细调</router-link>
          <router-link v-else :to="{ path: '/service', query: { tab: 'service' } }" class="small">看排班</router-link>
        </div>
      </div>
      <p v-if="msg" class="small ok">{{ msg }} <router-link to="/ont/actions">去动作收件箱</router-link></p>
      <p v-if="!data.can_initiate && data.options.length > 1" class="small muted">动作由计划员或厂长发起；你可以在推演工作台试算。</p>
    </template>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue';
import { get, post } from '../lib/api';
import { fmtTs } from '../lib/ont';

const props = defineProps({ anomalyId: Number });
const emit = defineEmits(['adopted']);
const data = ref(null);
const busy = ref(false);
const err = ref('');
const msg = ref('');
const adopting = ref(false);

async function load() {
  if (!props.anomalyId) return;
  busy.value = true; err.value = ''; msg.value = '';
  try { data.value = await get(`/ont/anomalies/${props.anomalyId}/options`); } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
async function adopt(o) {
  adopting.value = true;
  try {
    const r = await post('/ont/actions', { changes: o.changes, anomaly_id: props.anomalyId, snapshot_id: data.value.snapshot_id });
    msg.value = `已生成动作 ${r.ids.map((i) => 'ACT-' + String(i).padStart(5, '0')).join('、')}，等待批准。`;
    emit('adopted', r);
  } catch (e) { err.value = e.message; } finally { adopting.value = false; }
}
watch(() => props.anomalyId, () => { data.value = null; load(); }, { immediate: true });
</script>

<style scoped>
.op-h { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; margin-top: 14px; }
.op-h h3 { font-size: 14px; margin: 0; }
.op-h .linkbtn { margin-left: auto; }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; }
.reason { background: var(--good-bg); border-radius: 6px; padding: 6px 8px; color: var(--good); }
.lockn { background: #FFF4CC; border-radius: 6px; padding: 6px 8px; }
.opt { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; margin-top: 8px; }
.opt.rec { border-color: var(--good); box-shadow: 0 0 0 1px var(--good) inset; }
.opt.bad { opacity: .75; }
.o-h { display: flex; gap: 6px; align-items: center; }
.sos { margin: 4px 0; padding-left: 16px; }
.svc { display: flex; flex-direction: column; gap: 2px; margin: 4px 0; }
.late { color: var(--bad); }
.ok { color: var(--good); }
.err { color: var(--bad); }
.o-a { display: flex; gap: 10px; align-items: center; margin-top: 6px; }
.btn.sm { height: 28px; padding: 0 10px; }
</style>
