<template>
  <div class="page">
    <div class="page-title"><h1>实验 7 · 数字工厂闭环</h1><span class="muted">6 个任务，满分 100；系统按统一数据总线上的事实自动评分</span></div>
    <div v-if="s" class="score card">
      <span class="mono big">{{ s.score }} / {{ s.of }}</span>
      <span class="muted">已用 {{ s.elapsed_min }} 分钟{{ s.work_order ? ' · 你的工单 ' + s.work_order : '' }}</span>
    </div>
    <div v-if="s" class="tasks">
      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" :class="{ done: t.done, cur: i === s.current }">
        <div class="thead">
          <span class="num">{{ i + 1 }}</span>
          <h2>{{ t.title }}</h2>
          <span class="pill task">{{ roleName(t.role) }}</span>
          <span class="pts mono">{{ t.score }} / {{ t.points }}</span>
        </div>
        <p>{{ t.desc }}</p>
        <p class="muted small">提示：{{ t.hint }}</p>
        <router-link v-if="!['t1', 't6'].includes(t.id) || t.done" :to="'/work/' + t.role" class="small">去{{ roleName(t.role) }}工作区 →</router-link>

        <form v-if="t.id === 't1'" class="ans" @submit.prevent="submit('t1', t1)">
          <div class="field"><label>现在停机的设备</label><select v-model="t1.machine" required>
            <option v-for="o in s.t1_options.machines" :key="o.value" :value="o.value">{{ o.label }}</option></select></div>
          <div class="field"><label>有延期风险的订单</label><select v-model="t1.order" required>
            <option v-for="o in s.t1_options.orders" :key="o.value" :value="o.value">{{ o.label }}</option></select></div>
          <div class="field"><label>低于安全库存的物料</label><select v-model="t1.material" required>
            <option v-for="o in s.t1_options.materials" :key="o.value" :value="o.value">{{ o.label }}</option></select></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 't5'" class="ans" @submit.prevent="submit('t5', t5)">
          <div class="field"><label>轴承位直径为什么会逐渐变大？</label><select v-model="t5.reason" required>
            <option v-for="c in s.t5_choices" :key="c" :value="c">{{ c }}</option></select></div>
          <button class="btn primary">提交</button>
        </form>
        <form v-if="t.id === 't6'" class="ans" @submit.prevent="submit('t6', t6)">
          <div class="field"><label>实际加工成本比标准高百分之几</label><input v-model="t6.variance_pct" required placeholder="例如 12.5"></div>
          <div class="field grow"><label>主要原因（一句话）</label><input v-model="t6.reason" required></div>
          <button class="btn primary">提交</button>
          <router-link to="/work/manager" class="small">打开成本分解 →</router-link>
        </form>
        <div v-if="fb[t.id]" class="small" :class="fb[t.id].ok ? 'ok' : 'err'">{{ fb[t.id].text }}</div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { get, post, roleName } from '../lib/api';

const s = ref(null);
const t1 = reactive({ machine: '', order: '', material: '' });
const t5 = reactive({ reason: '' });
const t6 = reactive({ variance_pct: '', reason: '' });
const fb = reactive({});
async function load() { s.value = await get('/teach'); }
async function submit(id, body) {
  try {
    const r = await post('/teach/' + id, { ...body });
    fb[id] = { ok: r.score === r.of, text: `${r.feedback}（得 ${r.score} / ${r.of}）` };
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
