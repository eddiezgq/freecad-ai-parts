<!-- 负载跑合台 + 实验 28“负载跑合台上的仿真与实测对比”（第 58 轮，机器人厂）：实测与仿真的力矩曲线、辨识摩擦、力矩裕量、把结果写回模型 -->
<template>
  <div class="page">
    <div class="page-title"><h1>负载跑合 · 实验 28 仿真与实测对比</h1>
      <span class="muted">平台自动评 {{ s?.of || 60 }} 分，报告 {{ s?.report_points || 40 }} 分由老师在课程里批改</span>
      <span class="r small" data-help="lab-links"><a href="/api/cae/lab28/guide.docx">指导书</a> · <a href="/api/cae/lab28/report-template.docx">报告模板</a></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="s">
      <div class="card sum" data-help="lab-sum">
        <b v-if="!s.prod" class="big">{{ s.score }} / {{ s.of }}</b>
        <span class="small">你的机器人
          <select v-model="serial" aria-label="机器人" @change="pick"><option v-for="r in s.robots" :key="r" :value="r">{{ r }}</option></select></span>
        <span v-if="!s.robots.length" class="small muted">还没有标定过的 WQ-CR5：先接一台（实验 24），做到整机标定（实验 26）</span>
        <a v-if="s.serial" class="small" :href="'/api/runin/' + s.serial + '/data.csv'">下载跑合数据（CSV）</a>
        <router-link class="small" to="/mbd">运动与动力分析（同一个模型）</router-link>
        <button class="btn sm" @click="load">刷新</button>
      </div>

      <section v-if="s.teacher && s.class?.length" class="card">
        <div class="card-head"><h2>老师：全班成绩</h2></div>
        <table class="tbl small"><thead><tr><th>学生</th><th v-for="(t, i) in s.tasks" :key="t.id" class="num">任务 {{ i + 1 }}</th><th class="num">合计</th></tr></thead>
          <tbody><tr v-for="c in s.class" :key="c.user"><td>{{ c.user }}</td><td v-for="t in s.tasks" :key="t.id" class="num">{{ c.scores[t.id] ?? '—' }}</td>
            <td class="num"><b>{{ c.total }}</b></td></tr></tbody></table>
      </section>

      <section v-if="c" class="card" data-help="runin-case">
        <div class="card-head"><h2>{{ c.serial }} 在负载跑合台上</h2>
          <span class="muted small">负载 {{ c.load_kg }} kg，标准动作 {{ c.duration_s }} s（三段，每段 {{ c.seg_s }} s、停 {{ c.dwell_s }} s），驱动器按电流记力矩 {{ c.hz }} Hz</span></div>
        <div class="tabs small"><button v-for="(j, i) in c.joints" :key="j.joint" class="btn sm" :class="{ primary: ji === i }" @click="ji = i">{{ j.joint }}</button></div>
        <TimeChart :title="c.joints[ji].joint + ' 力矩：实测与仿真'" unit="N·m" :t="tArr" :series="chartSeries" />
        <TimeChart :title="c.joints[ji].joint + ' 实测 − 仿真（差放大来看）'" unit="N·m" :t="tArr" :series="diffSeries" />
        <p class="small muted">仿真 = 零件库 B-ARM-WQCR5（名义摩擦）算的同一段动作；实测里有这台机器人自己的摩擦和测量噪声。</p>
        <div class="scroll"><table class="tbl small">
          <thead><tr><th>关节</th><th>模组</th><th class="num">峰值 实测</th><th class="num">峰值 仿真</th><th class="num">均方根 实测</th><th class="num">均方根 仿真</th>
            <th class="num">均方根差</th><th class="num">f_c 测试台</th><th class="num">f_c 辨识</th><th class="num">f_v 名义</th><th class="num">f_v 辨识</th>
            <th class="num">更新模型后均方根差</th><th class="num">噪声 σ</th><th class="num">额定 / 上限</th><th>裕量</th></tr></thead>
          <tbody><tr v-for="j in c.joints" :key="j.joint">
            <td>{{ j.joint }}</td><td>{{ j.module }}</td><td class="num">{{ j.peak_meas }}</td><td class="num">{{ j.peak_sim }}</td><td class="num">{{ j.rms_meas }}</td><td class="num">{{ j.rms_sim }}</td>
            <td class="num">{{ j.rms_diff }}</td><td class="num">{{ j.fc_bench }}</td><td class="num">{{ j.fc_hat }}</td><td class="num">{{ j.fv_nominal }}</td><td class="num">{{ j.fv_hat }}</td>
            <td class="num">{{ j.rms_diff_updated }}</td><td class="num">{{ j.noise_sigma }}</td><td class="num">{{ j.rated }} / {{ j.limit }}</td>
            <td :class="j.pass ? 'good' : 'bad'">{{ j.pass ? '合格' : '不合格' }}</td></tr></tbody></table></div>
        <p class="small">力矩 N·m，f_v 单位 N·m·s/rad。整台：<b :class="c.pass ? 'good' : 'bad'">{{ c.pass ? '力矩裕量合格' : '力矩裕量不合格' }}</b>
          <span v-if="!c.bench_known" class="muted">（这台有关节缺测试台记录，按名义值补了）</span></p>
        <p v-if="c.truth" class="small muted">老师可见·这台的“真实”摩擦：f_c {{ c.truth.fc.join('，') }}；f_v {{ c.truth.fv.join('，') }}</p>
      </section>

      <section v-for="(t, i) in s.tasks" :key="t.id" class="card task" data-help="lab-task" :class="{ done: t.done }">
        <div class="card-head"><h2>任务 {{ i + 1 }}　{{ t.title }}</h2><span class="pts">{{ t.score }} / {{ t.points }}</span></div>
        <p>{{ t.desc }}</p>
        <p class="small muted">提示：{{ t.hint }}</p>
        <form v-if="t.id === 'l28_t1'" class="f" @submit.prevent="submit(t.id, a1)">
          <div class="lf"><label>J2 峰值（N·m）</label><input v-model.number="a1.peak" type="number" step="0.001" required></div>
          <button class="btn primary" :disabled="!s.serial">提交</button>
        </form>
        <form v-if="t.id === 'l28_t2'" class="f" @submit.prevent="submit(t.id, a2)">
          <div class="lf"><label>差得最多的关节</label><span class="cks">
            <label v-for="j in s.joints" :key="j"><input v-model="a2.joint" type="radio" :value="j" required> {{ j }}</label></span></div>
          <button class="btn primary" :disabled="!s.serial">提交</button>
        </form>
        <form v-if="t.id === 'l28_t3'" class="f" @submit.prevent="submit(t.id, a3)">
          <div class="lf"><label>J1 f_c（N·m）</label><input v-model.number="a3.fc" type="number" step="0.0001" required></div>
          <div class="lf"><label>J1 f_v（N·m·s/rad）</label><input v-model.number="a3.fv" type="number" step="0.0001" required></div>
          <button class="btn primary" :disabled="!s.serial">提交</button>
        </form>
        <form v-if="t.id === 'l28_t5'" class="f" @submit.prevent="submit(t.id, a5)">
          <div class="lf"><label>J2 均方根（N·m）</label><input v-model.number="a5.rms" type="number" step="0.001" required></div>
          <div class="lf"><label>整台力矩裕量</label><span class="cks">
            <label><input v-model="a5.pass" type="radio" :value="true" required> 合格</label><label><input v-model="a5.pass" type="radio" :value="false"> 不合格</label></span></div>
          <button class="btn primary" :disabled="!s.serial">提交</button>
        </form>
        <form v-if="t.id === 'l28_t4' || t.id === 'l28_t6'" class="f" @submit.prevent="submit(t.id, t.id === 'l28_t4' ? a4 : a6)">
          <div class="lf"><label>选一项</label><span class="cks col">
            <label v-for="o in (t.id === 'l28_t4' ? s.t4_choices : s.t6_choices)" :key="o.value">
              <input v-if="t.id === 'l28_t4'" v-model="a4.choice" type="radio" :value="o.value" required>
              <input v-else v-model="a6.choice" type="radio" :value="o.value" required> {{ o.label }}</label></span></div>
          <button class="btn primary" :disabled="!s.serial">提交</button>
        </form>
        <p v-if="fb[t.id]" class="small fb">{{ fb[t.id] }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { get, post } from '../lib/api';
import TimeChart from '../components/TimeChart.vue';

const s = ref(null);
const c = ref(null);
const err = ref('');
const fb = reactive({});
const serial = ref('');
const ji = ref(1);
const a1 = reactive({ peak: null });
const a2 = reactive({ joint: '' });
const a3 = reactive({ fc: null, fv: null });
const a4 = reactive({ choice: '' });
const a5 = reactive({ rms: null, pass: null });
const a6 = reactive({ choice: '' });

const tArr = computed(() => Float32Array.from(c.value?.series?.t || []));
const chartSeries = computed(() => {
  const S = c.value?.series;
  if (!S) return [];
  return [{ name: 'meas', label: '实测', values: S.meas[ji.value], color: '#d9480f' },
          { name: 'sim', label: '仿真（名义模型）', values: S.sim[ji.value], color: '#1c7ed6' }];
});

const diffSeries = computed(() => {
  const S = c.value?.series;
  if (!S) return [];
  const m = S.meas[ji.value], q = S.sim[ji.value];
  return [{ name: 'diff', label: '实测 − 仿真', values: m.map((v, k) => +(v - q[k]).toFixed(3)), color: '#7048e8' }];
});

async function loadCase() {
  c.value = null;
  if (!s.value?.serial) return;
  try { c.value = await get('/runin/' + encodeURIComponent(s.value.serial)); } catch (e) { err.value = e.message; }
}
async function load() {
  try { s.value = await get('/lab28'); }
  catch (e) {                                   // 生产模式没有实验任务：只看跑合数据
    try { const r = await get('/runin'); s.value = { prod: true, tasks: [], score: 0, of: 0, robots: r.robots.map((x) => x.serial), serial: serial.value || r.robots[0]?.serial || null, joints: [] }; }
    catch (e2) { err.value = e2.message; return; }
  }
  serial.value = s.value.serial || ''; err.value = ''; await loadCase();
}
async function pick() {
  if (s.value?.prod) { s.value.serial = serial.value; await loadCase(); return; }
  try { await post('/lab28/pick', { serial: serial.value }); await load(); } catch (e) { err.value = e.message; }
}
async function submit(tid, body) {
  try { const r = await post('/lab28/' + tid, JSON.parse(JSON.stringify(body))); fb[tid] = r.feedback; s.value = await get('/lab28'); } catch (e) { err.value = e.message; }
}
onMounted(load);
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.r { margin-left: auto; }
.sum { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
.big { font-size: 24px; }
.tabs { display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }
.scroll { overflow-x: auto; }
.good { color: var(--good); }
.bad { color: var(--bad, #c92a2a); }
.task.done { border-left: 4px solid var(--good); }
.pts { margin-left: auto; font-weight: 600; }
.f { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.lf { display: flex; flex-direction: row; gap: 10px; align-items: flex-start; flex-wrap: wrap; }
.lf > label:first-child { width: 170px; font-weight: 500; padding-top: 4px; }
.cks { display: flex; flex-wrap: wrap; gap: 4px 14px; flex: 1 1 auto; min-width: 240px; font-size: 13px; }
.cks.col { flex-direction: column; }
.f .btn { align-self: flex-start; }
select, input[type=number] { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
input[type=number] { width: 130px; }
.tbl { width: 100%; border-collapse: collapse; }
.tbl th, .tbl td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
.num { text-align: right; }
.fb { background: var(--surface-2); border-radius: 6px; padding: 6px 8px; }
</style>
