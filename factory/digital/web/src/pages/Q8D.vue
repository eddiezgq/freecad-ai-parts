<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('质量异常单（8D）') }}</h1>
      <span class="muted">{{ $t('发现异常 → 描述问题 → 围堵 → 找根本原因 → 纠正措施（老师批准后在车间实施）→ 用数据验证 → 防止再发生 → 关闭') }}</span></div>
    <section v-if="!id" class="card">
      <div v-if="!list.length" class="empty">{{ $t('还没有质量异常单。在“质量”页的控制图旁为某个特性开单。') }}</div>
      <table v-else class="t">
        <thead><tr><th>{{ $t('编号') }}</th><th>{{ $t('现象') }}</th><th>{{ $t('特性') }}</th><th>{{ $t('状态') }}</th><th>{{ $t('开单人') }}</th><th>{{ $t('时间') }}</th></tr></thead>
        <tbody><tr v-for="q in list" :key="q.id">
          <td><router-link :to="'/quality/8d/' + q.id" class="mono">{{ $td(q.id) }}</router-link></td><td>{{ $td(q.title) }}</td>
          <td class="small">{{ CHARS[q.characteristic] || q.characteristic }}</td><td>{{ $td(STATUS[q.status]) }}</td>
          <td class="small">{{ $td(q.author) }}</td><td class="small">{{ timeOf(q.created_at) }}</td></tr></tbody>
      </table>
    </section>
    <template v-else-if="q">
      <section class="card">
        <div class="card-head"><h2><span class="mono">{{ $td(q.id) }}</span> {{ $td(q.title) }}</h2>
          <span class="pill" :class="q.status === 'closed' ? 'good' : 'warn'">{{ $td(STATUS[q.status]) }}</span></div>
        <p class="small muted">{{ $t('零件 {a} · 特性 {b} · 开单 {c} {d}', { a: $td(q.item), b: CHARS[q.characteristic] || q.characteristic, c: $td(q.author), d: timeOf(q.created_at) }) }}
          <router-link to="/work/quality">{{ $t('· 看控制图') }}</router-link></p>
        <div v-for="k in ORDER" :key="k" class="sec">
          <label><b>{{ (catalog.sections || {})[k] }}</b><span class="small muted"> {{ $td(HINT[k]) }}</span></label>
          <template v-if="k === 'd5'">
            <select v-model="fix" :disabled="!editableFix">
              <option value="">{{ $t('选择纠正措施…') }}</option>
              <option v-for="(t, f) in catalog.fixes || {}" :key="f" :value="f">{{ $td(t) }}</option>
            </select>
          </template>
          <textarea v-model="d[k]" :disabled="q.status === 'closed'" rows="3" />
        </div>
        <div v-if="q.d && q.d.teacher_note" class="err small">{{ $t('老师退回意见：{a}', { a: $td(q.d.teacher_note) }) }}</div>
        <div class="acts">
          <button class="btn" :disabled="q.status === 'closed'" @click="act('save')">{{ $t('保存') }}</button>
          <button v-if="['open', 'rejected'].includes(q.status)" class="btn primary" @click="act('submit')">{{ $t('提交纠正措施，请老师批准') }}</button>
          <template v-if="isTeacher && q.status === 'submitted'">
            <input v-model="note" :placeholder="$t('退回时写意见')" />
            <button class="btn primary" @click="act('approve')">{{ $t('批准并在车间实施') }}</button>
            <button class="btn danger" @click="act('reject')">{{ $t('退回') }}</button>
          </template>
          <button v-if="q.status === 'approved'" class="btn" @click="act('verify')">{{ $t('用措施后的数据验证（D6）') }}</button>
          <button v-if="q.status === 'approved'" class="btn primary" @click="act('close')">{{ $t('关闭') }}</button>
        </div>
        <div v-if="msg" class="small" :class="ok ? 'ok' : 'err'">{{ msg }}</div>
      </section>
      <section v-if="q.verify" class="card">
        <div class="card-head"><h2>{{ $t('D6 验证：措施前后对比') }}</h2>
          <span class="pill" :class="q.verify.effective ? 'good' : 'bad'">{{ q.verify.effective ? $t('措施有效') : $t('尚未证明有效') }}</span></div>
        <table class="t">
          <thead><tr><th></th><th class="num">{{ $t('件数') }}</th><th class="num">{{ $t('均值') }}</th><th class="num">{{ $t('超差件') }}</th><th class="num">C<sub>pk</sub></th></tr></thead>
          <tbody>
            <tr v-for="(r, k) in { [$t('措施前')]: q.verify.before, [$t('措施后')]: q.verify.after }" :key="k">
              <td>{{ k }}</td><td class="num">{{ r ? r.n : 0 }}</td><td class="num mono">{{ r && r.mean != null ? r.mean.toFixed(4) : '—' }}</td>
              <td class="num">{{ r ? r.fails : '—' }}</td><td class="num mono">{{ r && r.Cpk != null ? r.Cpk.toFixed(2) : '—' }}</td></tr>
          </tbody>
        </table>
        <p class="small muted">{{ $t('判定：措施后至少 {a} 件、全部合格且 C', { a: $td(q.verify.need) }) }}<sub>pk</sub> {{ $t('≥ 1.33。数据不够就等车间多做几件再验证。') }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { get, post, session } from '../lib/api';
import { timeOf } from '../lib/fmt';

const route = useRoute();
const id = computed(() => route.params.id);
const ORDER = ['d1', 'd2', 'd3', 'd4', 'd5', 'd6', 'd7', 'd8'];
const HINT = {
  d1: $t('谁参加：工艺、质检、操作工、设备……'), d2: $t('什么零件、什么特性、偏了多少、从什么时候开始、哪台设备（5W2H，引用控制图数据）'),
  d3: $t('在找到原因之前，怎样不让不合格品流出：全检、隔离、停机……'), d4: $t('5 Why、鱼骨图：人、机、料、法、测、环，哪个能解释数据的形态'),
  d5: $t('选一项纠正措施，并说明为什么它能消除根本原因'), d6: $t('措施实施后用数据证明有效（点“验证”）'),
  d7: $t('改了哪些工艺文件（工序卡、检验卡、点检表），加了什么防错'), d8: $t('经验与教训'),
};
const STATUS = { open: $t('填写中'), submitted: $t('措施待批准'), approved: $t('措施已实施'), rejected: $t('措施退回'), closed: $t('已关闭') };
const CHARS = { bearing_seat_d35: $t('轴承位直径（左）'), bearing_seat_d35_r: $t('轴承位直径（右）'), gear_seat_d40: $t('齿轮位直径'),
  keyway_width_12: $t('键槽宽'), runout_bearing: $t('轴承位圆跳动'), keyway_sym: $t('键槽对称度') };
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
    msg.value = { save: $t('已保存'), submit: $t('已提交，等老师批准'), approve: $t('已批准，措施已下发到车间'), reject: $t('已退回'), verify: r.effective ? $t('验证通过：措施有效') : $t('还不能证明有效，看下面的对比'), close: $t('已关闭') }[action];
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
