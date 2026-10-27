<template>
  <!-- 当场动手（第 30 轮 §八 H-11 第 2 种）：按钮直接在演示工厂里做一件事，下面的实时数据跟着变。
       只在教学模式的演示工厂显示；学生只能按自己岗位能做的（服务器 /api/help/try 判定） -->
  <div v-if="show" class="hb try" :class="{ done: res, bad: err }">
    <div class="t-head">
      <span class="badge small">当场动手</span>
      <b>{{ args.label || a?.label || args.action }}</b>
    </div>
    <p v-if="args.note" class="small muted note">{{ args.note }}</p>
    <div class="acts">
      <router-link v-if="!loggedIn" class="btn" :to="{ path: '/login', query: { next: $route.fullPath } }">登录后可以当场动手</router-link>
      <template v-else-if="a">
        <button class="btn primary" :disabled="busy || !a.ok || left > 0" :aria-busy="busy" @click="go">
          <span v-if="busy" class="spin" aria-hidden="true"></span>{{ busy ? '正在做…' : left > 0 ? `${left} 秒后可以再按` : '现在就做' }}</button>
        <span v-if="!a.ok && !left" class="small muted">{{ a.why }}</span>
      </template>
      <span v-else-if="listErr" class="small muted">{{ listErr }}</span>
    </div>
    <div v-if="res || err" class="out" role="status" aria-live="polite">
      <p v-if="err" class="small errline">{{ err }}</p>
      <template v-else>
        <p class="small"><span class="ok">✓</span> {{ res.text }}</p>
        <p class="small muted">{{ at }} · <router-link :to="res.look">去{{ pageTitle(res.look) || '页面' }}看 →</router-link>
          <span v-if="teacher"> · 想复原：情景导演里“重置实验 7 情景”</span></p>
      </template>
    </div>
  </div>
</template>

<script>
// 一页里几个 try 块共用一份“此刻能不能按”（5 秒内不重取）；一个块按过以后大家一起刷新（每人 60 秒一次，不分动作）
import { reactive } from 'vue';
const shared = reactive({ list: null, err: '', p: null, t: 0 });
</script>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { api, get, loadConfig, session } from '../../lib/api';
import { pageTitle } from '../../help/pages';

const props = defineProps({ args: { type: Object, default: () => ({}) } });
const loggedIn = computed(() => !!session.token);
const demo = ref(true);
const list = computed(() => shared.list);
const listErr = computed(() => shared.err);
const busy = ref(false);
const res = ref(null);
const err = ref('');
const at = ref('');
const left = ref(0);
let tick = null;

// 非演示厂、生产模式不显示；没登录显示“登录后可以当场动手”
const show = computed(() => demo.value && (!loggedIn.value || session.user?.mode === 'teach'));
const a = computed(() => list.value?.actions?.[props.args.action] || null);
const teacher = computed(() => !!list.value?.teacher);

function refresh(force) {
  if (!shared.p || force || Date.now() - shared.t > 5000) {
    shared.t = Date.now();
    shared.p = get('/help/try').then((x) => { shared.list = x; shared.err = ''; }).catch((e) => { shared.err = e.message; });
  }
  return shared.p;
}
// 倒计时跟着共享的 wait_s 走（别的块按过，这里也开始倒数）
watch(() => a.value?.wait_s, (s) => countdown(s || 0));
function countdown(s) {
  clearInterval(tick); left.value = s;
  // 倒数完了重新问一次服务器（“刚动过手”的灰按钮要变回能按）；几个块同时到点只问一次
  if (s > 0) tick = setInterval(() => { left.value -= 1; if (left.value <= 0) { clearInterval(tick); if (Date.now() - shared.t > 1500) refresh(true); } }, 1000);
}
async function go() {
  busy.value = true; err.value = ''; res.value = null;
  try {
    res.value = await api('POST', '/help/try/' + encodeURIComponent(props.args.action), {});
    at.value = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    countdown(res.value.wait_s || 0);
    refresh(true);
  } catch (e) {
    err.value = e.message;
    if (e.status === 429 || e.status === 403) refresh(true);
  } finally { busy.value = false; }
}
onMounted(async () => {
  try { const c = await loadConfig(); demo.value = c?.plant?.demo !== false; } catch { /* 用缺省 */ }
  if (loggedIn.value && show.value) { await refresh(); countdown(a.value?.wait_s || 0); }
});
onUnmounted(() => clearInterval(tick));
</script>

<style scoped>
.try { margin: 18px 0; padding: 14px 16px; border-radius: 10px; border: 1px solid var(--line); border-left: 4px solid var(--accent);
  background: var(--surface); }
.try.done { border-left-color: var(--good); }
.try.bad { border-left-color: var(--bad); }
.t-head { display: flex; align-items: center; gap: 10px; }
.badge { padding: 1px 8px; border-radius: 999px; background: var(--accent-bg); color: var(--accent); font-weight: 600; }
.note { margin: 6px 0 0; }
.acts { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 10px; }
.out { margin-top: 10px; padding-top: 8px; border-top: 1px dashed var(--line); }
.out p { margin: 3px 0; }
.ok { color: var(--good); font-weight: 700; }
.errline { color: var(--bad); }
.spin { display: inline-block; width: 12px; height: 12px; margin-right: 6px; border: 2px solid currentColor; border-right-color: transparent;
  border-radius: 50%; vertical-align: -1px; animation: rot 0.8s linear infinite; }
@keyframes rot { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>
