<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('实验 7 · 数字工厂闭环') }}</h1><span class="muted">{{ $t('6 个任务，满分 100；系统按统一数据总线上的事实自动评分') }}</span></div>
    <p v-if="loadErr" class="card muted">{{ loadErr }}</p>
    <div v-if="s" class="score card">
      <span class="mono big">{{ $td(s.score) }} / {{ $td(s.of) }}</span>
      <span class="muted">{{ $t('已用 {a} 分钟{b}', { a: $td(s.elapsed_min), b: s.work_order ? $t(' · 你的工单 ') + s.work_order : '' }) }}</span>
    </div>
    <div v-if="s" class="tasks">
      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" :class="{ done: t.done, cur: i === s.current }">
        <div class="thead">
          <span class="num">{{ i + 1 }}</span>
          <h2>{{ $td(t.title) }}</h2>
          <span class="pill task">{{ roleName(t.role) }}</span>
          <span class="pts mono">{{ $td(t.score) }} / {{ $td(t.points) }}</span>
        </div>
        <p>{{ $td(t.desc) }}</p>
        <p class="muted small">{{ $t('提示：{a}', { a: $td(t.hint) }) }}</p>
        <router-link v-if="!['t1', 't6'].includes(t.id) || t.done" :to="'/work/' + t.role" class="small">{{ $t('去{a}工作区 →', { a: roleName(t.role) }) }}</router-link>

        <form v-if="t.id === 't1'" class="ans" @submit.prevent="submit('t1', t1)">
          <div class="field"><label>{{ $t('现在停机的设备') }}</label><select v-model="t1.machine" required>
            <option v-for="o in s.t1_options.machines" :key="o.value" :value="o.value">{{ $td(o.label) }}</option></select></div>
          <div class="field"><label>{{ $t('有延期风险的订单') }}</label><select v-model="t1.order" required>
            <option v-for="o in s.t1_options.orders" :key="o.value" :value="o.value">{{ $td(o.label) }}</option></select></div>
          <div class="field"><label>{{ $t('低于安全库存的物料') }}</label><select v-model="t1.material" required>
            <option v-for="o in s.t1_options.materials" :key="o.value" :value="o.value">{{ $td(o.label) }}</option></select></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 't5'" class="ans" @submit.prevent="submit('t5', t5)">
          <div class="field"><label>{{ $t('轴承位直径为什么会逐渐变大？') }}</label><select v-model="t5.reason" required>
            <option v-for="c in s.t5_choices" :key="c" :value="c">{{ $td(c) }}</option></select></div>
          <button class="btn primary">{{ $t('提交') }}</button>
        </form>
        <form v-if="t.id === 't6'" class="ans" @submit.prevent="submit('t6', t6)">
          <div class="field"><label>{{ $t('实际加工成本比标准高百分之几') }}</label><input v-model="t6.variance_pct" required :placeholder="$t('例如 12.5')"></div>
          <div class="field grow"><label>{{ $t('主要原因（一句话）') }}</label><input v-model="t6.reason" required></div>
          <button class="btn primary">{{ $t('提交') }}</button>
          <router-link to="/work/manager" class="small">{{ $t('打开成本分解 →') }}</router-link>
        </form>
        <div v-if="fb[t.id]" class="small" :class="fb[t.id].ok ? 'ok' : 'err'">{{ $td(fb[t.id].text) }}</div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { onMounted, reactive, ref } from 'vue';
import { get, post, roleName } from '../lib/api';

const s = ref(null);
const t1 = reactive({ machine: '', order: '', material: '' });
const t5 = reactive({ reason: '' });
const t6 = reactive({ variance_pct: '', reason: '' });
const fb = reactive({});
const loadErr = ref('');
async function load() { try { s.value = await get('/teach'); loadErr.value = ''; } catch (e) { loadErr.value = e.message; } }   // 别的厂：“实验 7 只在减速器厂”
async function submit(id, body) {
  try {
    const r = await post('/teach/' + id, { ...body });
    fb[id] = { ok: r.score === r.of, text: $t('{a}（得 {b} / {c}）', { a: r.feedback, b: r.score, c: r.of }) };
  } catch (e) { fb[id] = { ok: false, text: e.message }; }
  load();
}
onMounted(load);
</script>

<style scoped>
.score { display: flex; align-items: baseline; gap: 14px; }
.big { font-size: 26px; font-weight: 600; }
.tasks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.task.cur { border-color: var(--task-line); box-shadow: inset 3px 0 0 var(--brand); }
.task.done { background: #F7FBF8; }
.thead { display: flex; align-items: center; gap: 10px; }
.num { width: 24px; height: 24px; border-radius: 50%; background: var(--ink); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 12px; }
.pts { margin-left: auto; font-weight: 600; }
.ans { display: flex; gap: 10px; align-items: end; flex-wrap: wrap; margin-top: 10px; }
.grow { flex-grow: 1; }
@media (max-width: 1000px) { .tasks { grid-template-columns: 1fr; } }
</style>
