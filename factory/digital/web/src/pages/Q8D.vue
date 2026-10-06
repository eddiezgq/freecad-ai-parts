<template>
  <div class="page">
    <div class="page-title"><h1>质量异常单（8D）</h1>
      <span class="muted">发现异常 → 描述问题 → 围堵 → 找根本原因 → 纠正措施（老师批准后在车间实施）→ 用数据验证 → 防止再发生 → 关闭</span></div>
    <section v-if="!id" class="card">
      <div v-if="!list.length" class="empty">还没有质量异常单。在“质量”页的控制图旁为某个特性开单。</div>
      <table v-else class="t">
        <thead><tr><th>编号</th><th>现象</th><th>特性</th><th>状态</th><th>开单人</th><th>时间</th></tr></thead>
        <tbody><tr v-for="q in list" :key="q.id">
          <td><router-link :to="'/quality/8d/' + q.id" class="mono">{{ q.id }}</router-link></td><td>{{ q.title }}</td>
          <td class="small">{{ CHARS[q.characteristic] || q.characteristic }}</td><td>{{ STATUS[q.status] }}</td>
          <td class="small">{{ q.author }}</td><td class="small">{{ timeOf(q.created_at) }}</td></tr></tbody>
      </table>
    </section>
    <template v-else-if="q">
      <section class="card">
        <div class="card-head"><h2><span class="mono">{{ q.id }}</span> {{ q.title }}</h2>
          <span class="pill" :class="q.status === 'closed' ? 'good' : 'warn'">{{ STATUS[q.status] }}</span></div>
        <p class="small muted">零件 {{ q.item }} · 特性 {{ CHARS[q.characteristic] || q.characteristic }} · 开单 {{ q.author }} {{ timeOf(q.created_at) }}
          <router-link to="/work/quality">· 看控制图</router-link></p>
        <div v-for="k in ORDER" :key="k" class="sec">
          <label><b>{{ (catalog.sections || {})[k] }}</b><span class="small muted"> {{ HINT[k] }}</span></label>
          <template v-if="k === 'd5'">
            <select v-model="fix" :disabled="!editableFix">
              <option value="">选择纠正措施…</option>
              <option v-for="(t, f) in catalog.fixes || {}" :key="f" :value="f">{{ t }}</option>
            </select>
          </template>
          <textarea v-model="d[k]" :disabled="q.status === 'closed'" rows="3" />
        </div>
        <div v-if="q.d && q.d.teacher_note" class="err small">老师退回意见：{{ q.d.teacher_note }}</div>
        <div class="acts">
          <button class="btn" :disabled="q.status === 'closed'" @click="act('save')">保存</button>
          <button v-if="['open', 'rejected'].includes(q.status)" class="btn primary" @click="act('submit')">提交纠正措施，请老师批准</button>
          <template v-if="isTeacher && q.status === 'submitted'">
            <input v-model="note" placeholder="退回时写意见" />
            <button class="btn primary" @click="act('approve')">批准并在车间实施</button>
            <button class="btn danger" @click="act('reject')">退回</button>
          </template>
          <button v-if="q.status === 'approved'" class="btn" @click="act('verify')">用措施后的数据验证（D6）</button>
          <button v-if="q.status === 'approved'" class="btn primary" @click="act('close')">关闭</button>
        </div>
        <div v-if="msg" class="small" :class="ok ? 'ok' : 'err'">{{ msg }}</div>
      </section>
      <section v-if="q.verify" class="card">
        <div class="card-head"><h2>D6 验证：措施前后对比</h2>
          <span class="pill" :class="q.verify.effective ? 'good' : 'bad'">{{ q.verify.effective ? '措施有效' : '尚未证明有效' }}</span></div>
        <table class="t">
          <thead><tr><th></th><th class="num">件数</th><th class="num">均值</th><th class="num">超差件</th><th class="num">C<sub>pk</sub></th></tr></thead>
          <tbody>
            <tr v-for="(r, k) in { 措施前: q.verify.before, 措施后: q.verify.after }" :key="k">
              <td>{{ k }}</td><td class="num">{{ r ? r.n : 0 }}</td><td class="num mono">{{ r && r.mean != null ? r.mean.toFixed(4) : '—' }}</td>
              <td class="num">{{ r ? r.fails : '—' }}</td><td class="num mono">{{ r && r.Cpk != null ? r.Cpk.toFixed(2) : '—' }}</td></tr>
          </tbody>
        </table>
        <p class="small muted">判定：措施后至少 {{ q.verify.need }} 件、全部合格且 C<sub>pk</sub> ≥ 1.33。数据不够就等车间多做几件再验证。</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { get, post, session } from '../lib/api';
import { timeOf } from '../lib/fmt';

const route = useRoute();
const id = computed(() => route.params.id);
const ORDER = ['d1', 'd2', 'd3', 'd4', 'd5', 'd6', 'd7', 'd8'];
const HINT = {
  d1: '谁参加：工艺、质检、操作工、设备……', d2: '什么零件、什么特性、偏了多少、从什么时候开始、哪台设备（5W2H，引用控制图数据）',
  d3: '在找到原因之前，怎样不让不合格品流出：全检、隔离、停机……', d4: '5 Why、鱼骨图：人、机、料、法、测、环，哪个能解释数据的形态',
  d5: '选一项纠正措施，并说明为什么它能消除根本原因', d6: '措施实施后用数据证明有效（点“验证”）',
  d7: '改了哪些工艺文件（工序卡、检验卡、点检表），加了什么防错', d8: '经验与教训',
};
const STATUS = { open: '填写中', submitted: '措施待批准', approved: '措施已实施', rejected: '措施退回', closed: '已关闭' };
const CHARS = { bearing_seat_d35: '轴承位直径（左）', bearing_seat_d35_r: '轴承位直径（右）', gear_seat_d40: '齿轮位直径',
  keyway_width_12: '键槽宽', runout_bearing: '轴承位圆跳动', keyway_sym: '键槽对称度' };
const list = ref([]);
const q = ref(null);
const d = ref({});
const fix = ref('');
const note = ref('');
const msg = ref('');
const ok = ref(true);
const catalog = ref({});
const isTeacher = computed(() => session.user && session.user.mode === 'teach' && session.user.teacher);
const editableFix = computed(() => q.value && ['open', 'rejected'].includes(q.value.status));

async function load() {
  catalog.value = await get('/quality/problems/catalog');
  if (!id.value) { list.value = await get('/quality/8d'); return; }
  q.value = await get('/quality/8d/' + id.value);
  d.value = { ...(q.value.d || {}) };
  fix.value = q.value.fix || '';
}
async function act(action) {
  msg.value = '';
  try {
    if (action === 'save' || action === 'submit') await post('/quality/8d/' + id.value, { action: 'save', d: d.value, fix: fix.value || null });
    const r = await post('/quality/8d/' + id.value, { action, note: note.value });
    ok.value = true;
    msg.value = { save: '已保存', submit: '已提交，等老师批准', approve: '已批准，措施已下发到车间', reject: '已退回', verify: r.effective ? '验证通过：措施有效' : '还不能证明有效，看下面的对比', close: '已关闭' }[action];
    await load();
  } catch (e) {
    ok.value = false;
    msg.value = e.message;
  }
}
watch(id, load);
onMounted(load);
</script>

<style scoped>
.sec { display: flex; flex-direction: column; gap: 4px; margin: 10px 0; }
.sec textarea, .sec select { border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; font: inherit; }
.acts { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; align-items: center; }
.acts input { height: 32px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
</style>
