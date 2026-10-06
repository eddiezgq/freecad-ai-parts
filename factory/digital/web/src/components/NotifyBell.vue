<!-- 通知中心（第 17 轮 D 期 D6）：顶栏铃铛 + 未读数；新的严重异常、待我批准的动作、日报周报…… -->
<template>
  <div class="bell-wrap">
    <button class="bell" :aria-label="'通知，' + unread + ' 条未读'" @click="toggle">
      <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor"
        d="M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm7-6V11a7 7 0 0 0-5.5-6.84V3.5a1.5 1.5 0 0 0-3 0v.66A7 7 0 0 0 5 11v5l-2 2v1h18v-1l-2-2Z"/></svg>
      <span v-if="unread" class="cnt">{{ unread > 99 ? '99+' : unread }}</span>
    </button>
    <div v-if="open" class="pop" role="dialog" aria-label="通知">
      <div class="ph"><b>通知</b><button class="linkbtn" :disabled="!unread" @click="readAll">全部已读</button>
        <router-link class="linkbtn" to="/ont/notify" @click="open = false">通知设置</router-link></div>
      <p v-if="!items.length" class="muted small pad">没有通知。</p>
      <button v-for="n in items" :key="n.id" class="it" :class="{ unread: !n.read, [n.severity || 'info']: true }" @click="go(n)">
        <span class="t">{{ n.title }}</span>
        <span v-if="n.body" class="b">{{ n.body }}</span>
        <span class="ts">{{ fmtTs(n.created_at) }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { get, post } from '../lib/api';
import { fmtTs } from '../lib/ont';

const router = useRouter();
const open = ref(false);
const items = ref([]);
const unread = ref(0);
let timer = null;

async function load() {
  try { const r = await get('/notifications'); items.value = r.items; unread.value = r.unread; } catch { /* 未登录或网络问题：下次再取 */ }
}
function toggle() { open.value = !open.value; if (open.value) load(); }
async function readAll() { await post('/notifications/read', { all: true }); load(); }
async function go(n) {
  if (!n.read) { await post('/notifications/read', { ids: [n.id] }); n.read = true; unread.value = Math.max(0, unread.value - 1); }
  open.value = false;
  if (n.url) router.push(n.url);
}
onMounted(() => { load(); timer = setInterval(load, 30000); });
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.bell-wrap { position: relative; }
.bell { position: relative; width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--line); background: var(--surface); cursor: pointer;
  color: var(--ink, #17212B); display: grid; place-items: center; }
.cnt { position: absolute; top: -4px; right: -6px; background: var(--bad); color: #fff; border-radius: 9px; font-size: 10px; min-width: 16px;
  height: 16px; line-height: 16px; padding: 0 4px; }
.pop { position: absolute; right: 0; top: 40px; width: min(360px, 92vw); max-height: 70vh; overflow: auto; background: #fff; border: 1px solid var(--line);
  border-radius: 10px; box-shadow: 0 10px 30px rgba(23, 33, 43, .14); z-index: 50; }
.ph { display: flex; gap: 10px; align-items: center; padding: 10px 12px; border-bottom: 1px solid var(--line); position: sticky; top: 0; background: #fff; }
.ph b { margin-right: auto; }
.pad { padding: 12px; }
.it { display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left; border: none; border-bottom: 1px solid var(--line); background: none;
  padding: 8px 12px; cursor: pointer; border-left: 3px solid transparent; }
.it:hover { background: var(--surface-2); }
.it.unread { background: #F5F9FF; }
.it.critical { border-left-color: var(--bad); }
.it.warn { border-left-color: var(--warn); }
.t { font-size: 13px; font-weight: 500; }
.b { font-size: 12px; color: var(--muted); }
.ts { font-size: 11px; color: var(--muted); }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; }
</style>
