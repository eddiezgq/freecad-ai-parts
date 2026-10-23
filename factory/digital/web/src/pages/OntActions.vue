<template>
  <div class="page">
    <div class="page-title"><h1><router-link to="/ont" class="back">厂情中枢</router-link> / 动作收件箱</h1>
      <span class="muted">处理方案变成动作：先试运行，再审批，批准后由执行器真的去做（车间、班次表、ERPNext），全程留记录</span>
      <span class="tabs" data-help="act-boxes"><button v-for="(l, k) in BOX" :key="k" :class="{ on: box === k }" @click="box = k; load()">{{ l }}</button></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <p class="small muted" data-help="act-rules">花钱的动作（加班、紧急采购、外协、维修加急）要厂长批准；改派、调序、分批交货计划员或厂长都能批。生产模式下不能批准自己发起的动作。</p>
    <div v-if="!list.length" class="empty">{{ box === 'todo' ? '没有等你批准的动作。' : '还没有动作。' }}</div>
    <section v-for="a in list" :key="a.id" class="card act" data-help="act-list" :class="a.status">
      <div class="a-h">
        <span class="mono small">{{ a.key }}</span>
        <b>{{ a.title }}</b>
        <span v-if="a.costly" class="pill warn">花钱</span>
        <span class="pill" :class="tone(a.status)">{{ a.status_label }}</span>
        <span class="small muted r">{{ a.initiator }} 发起 · {{ fmtTs(a.created_at) }}<template v-if="a.approver"> · {{ a.approver }} {{ a.status === 'rejected' ? '驳回' : '批准' }}</template></span>
      </div>
      <div v-if="a.trial" class="trial small">
        <span class="muted">试运行（{{ fmtTs(a.trial.at) }}）：</span>
        <span v-for="s in a.trial.sales_orders" :key="s.name" class="so">{{ s.name }}
          <template v-if="s.late_days !== null"><b :class="s.late_days > 0 ? 'late' : 'ok'">{{ s.late_days > 0 ? '晚 ' + s.late_days + ' 天' : '按时' }}</b>
            <span class="muted">（不处理：{{ baseLate(a, s.name) }}）</span></template>
          <template v-else>{{ s.note }}</template></span>
        <span>· 多花 <b>${{ Math.round(a.trial.cost_total || 0).toLocaleString() }}</b></span>
        <span v-for="(c, i) in (a.trial.checks || []).filter((x) => !x.ok)" :key="i" class="late"> · {{ c.text }}</span>
      </div>
      <div v-if="a.result" class="small">{{ a.result.text || a.result.error }}</div>
      <div class="a-a">
        <template v-if="a.status === 'draft' && a.mine">
          <button class="btn sm primary" @click="act(a, 'submit')">提交（附试运行）</button>
          <span class="small muted">草稿：提交以后才进入审批</span>
        </template>
        <template v-if="a.status === 'submitted'">
          <button class="btn sm primary" :disabled="!a.can_approve" :title="a.why_not" @click="act(a, 'approve')">批准并执行</button>
          <input v-model="reason[a.id]" placeholder="驳回原因" aria-label="驳回原因">
          <button class="btn sm danger" :disabled="!a.can_approve" @click="act(a, 'reject', { text: reason[a.id] })">驳回</button>
          <button class="btn sm ghost" @click="act(a, 'rerun')">用最新快照重新试运行</button>
          <span v-if="!a.can_approve && a.why_not" class="small muted">{{ a.why_not }}</span>
        </template>
        <router-link v-if="a.anomaly_id" class="small" :to="{ path: '/ont', query: { view: 'anomalies', a: a.anomaly_id } }">看对应的异常</router-link>
        <button class="linkbtn" @click="toggle(a)">{{ open[a.id] ? '收起记录' : '看记录' }}</button>
      </div>
      <ol v-if="open[a.id]" class="small log"><li v-for="(n, i) in open[a.id]" :key="i"><span class="mono muted">{{ fmtTs(n.ts) }}</span> {{ n.who }}：{{ n.text }}</li></ol>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import { get, post } from '../lib/api';
import { fmtTs } from '../lib/ont';

const BOX = { todo: '待我批准', mine: '我发起的', all: '全部' };
const route = useRoute();
const box = ref(BOX[route.query.box] ? route.query.box : 'todo');
const list = ref([]);
const err = ref('');
const reason = reactive({});
const open = reactive({});
function tone(s) { return { done: 'good', failed: 'bad', rejected: 'bad', submitted: 'warn', executing: 'info', draft: 'info' }[s] || 'mute'; }
function baseLate(a, name) {
  const s = (a.trial?.base?.sales_orders || []).find((x) => x.name === name);
  if (!s || s.late_days === null) return '—';
  return s.late_days > 0 ? '晚 ' + s.late_days + ' 天' : '按时';
}
async function load() { try { list.value = (await get('/ont/actions?box=' + box.value)).actions; } catch (e) { err.value = e.message; } }
async function act(a, kind, body) {
  try { await post(`/ont/actions/${a.id}/${kind}`, body || {}); await load(); if (open[a.id]) open[a.id] = (await get('/ont/actions/' + a.id)).log; } catch (e) { alert(e.message); }
}
async function toggle(a) { open[a.id] = open[a.id] ? null : (await get('/ont/actions/' + a.id)).log; }
onMounted(async () => { await load(); if (!list.value.length && box.value === 'todo') { box.value = 'all'; load(); } });
</script>

<style scoped>
.back { color: var(--muted); font-weight: 500; }
.page-title { flex-wrap: wrap; }
.tabs { margin-left: auto; display: flex; gap: 4px; }
.tabs button { height: 30px; padding: 0 12px; border: 1px solid var(--line); background: var(--surface); border-radius: 6px; cursor: pointer; }
.tabs button.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.act { margin-bottom: 10px; }
.act.submitted { border-left: 4px solid var(--warn); }
.act.done { border-left: 4px solid var(--good); }
.act.failed, .act.rejected { border-left: 4px solid var(--bad); }
.a-h { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.a-h .r { margin-left: auto; }
.trial { margin: 6px 0; display: flex; gap: 8px; flex-wrap: wrap; }
.late { color: var(--bad); }
.ok { color: var(--good); }
.a-a { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 6px; }
.a-a input { height: 28px; border: 1px solid var(--line); border-radius: 6px; padding: 0 6px; width: 140px; }
.btn.sm { height: 28px; padding: 0 10px; }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; }
.log { margin: 6px 0 0; padding-left: 18px; }
</style>
