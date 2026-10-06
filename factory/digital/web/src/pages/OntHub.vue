<template>
  <div class="page">
    <div class="page-title"><h1><router-link to="/ont" class="back">厂情中枢</router-link> / 全貌地图</h1>
      <span class="muted">工厂本体：15 个业务领域、{{ nTypes }} 类对象，人、机、料、法、环、客户、服务、安全……都在一张图里，每个数字都能追到原始记录</span></div>

    <section class="card search-card">
      <form class="search" role="search" @submit.prevent="doSearch">
        <input v-model="q" placeholder="搜任何东西：订单号、工单、零件序列号、设备号、物料编码、客户名…（如 SH301、grd-01、6207）"
          aria-label="搜索对象" autofocus @input="debounced">
        <select v-model="qType" aria-label="对象类型" @change="doSearch">
          <option value="">全部类型</option>
          <option v-for="t in typeOptions" :key="t.name" :value="t.name">{{ t.label }}</option>
        </select>
        <button class="btn primary">搜索</button>
      </form>
      <div v-if="searching" class="muted small">搜索中…</div>
      <div v-else-if="q && results && !results.length" class="empty">没有找到“{{ q }}”。可以换个写法，或去掉类型筛选。</div>
      <ul v-if="results?.length" class="hits">
        <li v-for="r in results" :key="r.id">
          <router-link :to="objPath(r.type, r.key)">
            <i class="dot" :style="{ background: DOMAIN_COLOR[r.domain] }"></i>
            <span class="pill mute">{{ r.label }}</span> <b>{{ r.display }}</b>
            <span v-if="r.display !== r.key" class="mono muted small">{{ r.key }}</span>
            <span class="muted small how">{{ r.how }}匹配</span>
          </router-link>
        </li>
      </ul>
    </section>

    <div v-if="err" class="err">{{ err }}</div>

    <section v-if="ont.types" class="card">
      <div class="card-head"><h2>全貌地图</h2>
        <span class="muted small">上排是价值链（从经营到服务），下排是支撑面。色块深浅表示数据成熟度；数字：对象数 · 有数据的类型 / 全部类型 · 近 24 小时变化</span>
        <span class="more legend">
          <span v-for="(m, k) in MATURITY_STYLE" :key="k" class="lg" :class="m.cls">{{ m.label }}</span>
        </span>
      </div>
      <div v-for="row in rows" :key="row.key" class="maprow">
        <div class="rowlabel">{{ row.label }}</div>
        <div class="domains" :class="row.key">
          <button v-for="d in row.domains" :key="d.domain" type="button" class="dom" :class="{ open: open === d.domain }"
            :style="{ '--c': DOMAIN_COLOR[d.domain] }" @click="toggle(d.domain)">
            <span class="dname">{{ d.label }}</span>
            <span class="dnum mono">{{ d.count.toLocaleString() }}</span>
            <span class="small dsub">{{ d.with_data }} / {{ d.types.length }} 类有数据 · 24h {{ sum(d, 'changes_24h') }}</span>
            <span class="mbar"><i v-for="t in d.types" :key="t.name" :class="MATURITY_STYLE[t.maturity].cls" :title="t.label + '：' + t.maturity_label"></i></span>
          </button>
        </div>
      </div>
    </section>

    <section v-if="openDomain" class="card">
      <div class="card-head"><h2><i class="dot" :style="{ background: DOMAIN_COLOR[openDomain.domain] }"></i> {{ openDomain.label }}</h2>
        <span class="muted small">{{ openDomain.label_en }} · 点对象类型看对象列表</span>
        <button class="more btn ghost" @click="open = ''">收起</button></div>
      <div class="types">
        <component :is="t.hidden ? 'div' : 'router-link'" v-for="t in openDomain.types" :key="t.name" class="type" :class="[MATURITY_STYLE[t.maturity].cls, { hidden: t.hidden }]"
          :to="t.hidden ? undefined : '/ont/' + t.name">
          <b>{{ t.label }}</b> <span class="muted small">{{ t.label_en }}</span>
          <span class="tcount mono">{{ t.hidden ? '无权限' : t.count.toLocaleString() }}</span>
          <span class="small muted">{{ t.maturity_label }}<template v-if="t.changes_24h"> · 24h {{ t.changes_24h }} 次变化</template></span>
          <span class="small muted src">{{ (t.sources || []).join('、') || '—' }}</span>
        </component>
      </div>
    </section>

    <section class="card health small muted" v-if="health">
      同步状态：已处理到第 {{ health.cursor?.toLocaleString() }} 条总线消息，落后 {{ health.behind }} 条，延迟 {{ health.lag_s }} 秒
      <template v-if="health.errors"> · <span class="bad">跳过 {{ health.errors }} 条（{{ health.last_error }}）</span></template>
      <button v-if="canReplay" class="btn ghost sm" :disabled="replaying" @click="replay">{{ replaying ? '重建中…' : '从头重建本体' }}</button>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { session, get, post } from '../lib/api';
import { ont, loadTypes, search, objPath, DOMAIN_COLOR, MATURITY_STYLE } from '../lib/ont';

const q = ref('');
const qType = ref('');
const results = ref(null);
const searching = ref(false);
const err = ref('');
const open = ref('');
const health = ref(null);
const replaying = ref(false);
const canReplay = computed(() => session.user?.teacher && session.user?.role === 'manager');

const nTypes = computed(() => (ont.types || []).reduce((n, d) => n + d.types.length, 0));
const typeOptions = computed(() => (ont.types || []).flatMap((d) => d.types.filter((t) => !t.hidden && t.count)));
const rows = computed(() => {
  const ds = [...(ont.types || [])].sort((a, b) => a.order - b.order);
  return [
    { key: 'chain', label: '价值链', domains: ds.filter((d) => d.row === 'chain') },
    { key: 'support', label: '支撑面', domains: ds.filter((d) => d.row === 'support') },
    { key: 'core', label: '中枢', domains: ds.filter((d) => d.row === 'core') },
  ];
});
const openDomain = computed(() => (ont.types || []).find((d) => d.domain === open.value));
const sum = (d, k) => d.types.reduce((n, t) => n + (t.hidden ? 0 : t[k] || 0), 0);

function toggle(d) { open.value = open.value === d ? '' : d; }

let timer;
function debounced() { clearTimeout(timer); timer = setTimeout(doSearch, 250); }
async function doSearch() {
  if (!q.value.trim()) { results.value = null; return; }
  searching.value = true;
  try { results.value = (await search(q.value.trim(), qType.value)).results; } catch (e) { err.value = e.message; } finally { searching.value = false; }
}
async function replay() {
  if (!confirm('清空当前模式的本体，从总线历史从头重建？数据量大时要几分钟。')) return;
  replaying.value = true;
  try { health.value = await post('/ont/replay'); await loadTypes(true); } catch (e) { err.value = e.message; } finally { replaying.value = false; }
}

onMounted(async () => {
  try { await loadTypes(true); } catch (e) { err.value = e.message; }
  try { health.value = await get('/ont/health'); } catch (e) { /* 不影响地图 */ }
});
</script>

<style scoped>
.back { color: var(--muted); font-weight: 500; }
.search { display: flex; gap: 8px; }
.search input { flex: 1; height: 40px; border: 1px solid #C8CEC7; border-radius: 8px; padding: 0 12px; font-size: 14px; min-width: 0; }
.search select { height: 40px; border: 1px solid #C8CEC7; border-radius: 8px; max-width: 160px; }
.hits { list-style: none; margin: 10px 0 0; padding: 0; max-height: 360px; overflow: auto; }
.hits li a { display: flex; gap: 8px; align-items: center; padding: 7px 6px; border-bottom: 1px solid var(--line-soft); color: var(--ink); }
.hits li a:hover { background: var(--surface-2); text-decoration: none; }
.how { margin-left: auto; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.legend { display: flex; gap: 8px; }
.lg { font-size: 11px; padding: 2px 8px; border-radius: 4px; }
.maprow { display: flex; gap: 10px; margin-bottom: 10px; align-items: stretch; }
.rowlabel { writing-mode: vertical-rl; font-size: 12px; color: var(--muted); letter-spacing: 4px; text-align: center; padding: 4px 0; }
.domains { display: grid; gap: 8px; flex: 1; }
.domains.chain { grid-template-columns: repeat(10, minmax(0, 1fr)); }
.domains.support { grid-template-columns: repeat(5, minmax(0, 1fr)); }
.domains.core { grid-template-columns: minmax(0, 1fr); }
.dom { text-align: left; border: 1px solid var(--line); border-top: 4px solid var(--c); border-radius: 8px; background: var(--surface);
  padding: 8px 9px; cursor: pointer; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.dom:hover, .dom.open { background: var(--surface-2); border-color: var(--c); }
.dname { font-weight: 600; font-size: 13px; }
.dnum { font-size: 18px; font-weight: 600; color: var(--c); }
.dsub { color: var(--muted); font-size: 11px; }
.mbar { display: flex; gap: 2px; margin-top: 3px; flex-wrap: wrap; }
.mbar i { width: 9px; height: 9px; border-radius: 2px; }
.m-have { background: var(--accent); color: #fff; }
.m-erp { background: #9CC7CF; color: var(--ink); }
.m-sim { background: #E8D58E; color: var(--ink); }
.m-capture { background: #fff; border: 1px dashed #9AA3AD; color: var(--muted); }
.m-next { background: #fff; border: 1px dotted #0E5E6F; color: var(--accent); }
.types { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
.type { display: flex; flex-direction: column; gap: 3px; padding: 9px 11px; border-radius: 8px; color: var(--ink); background: var(--surface) !important;
  border: 1px solid var(--line); border-left: 5px solid; }
.type.m-have { border-left-color: var(--accent); }
.type.m-erp { border-left-color: #9CC7CF; }
.type.m-sim { border-left-color: #E8D58E; }
.type.m-capture { border-left: 5px dashed #9AA3AD; }
.type.m-next { border-left: 5px dotted var(--accent); }
.type:hover { text-decoration: none; background: var(--surface-2) !important; }
.type.hidden { opacity: .55; }
.tcount { font-size: 16px; font-weight: 600; }
.src { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.health { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.health .bad { color: var(--bad); }
.btn.sm { height: 28px; padding: 0 10px; margin-left: auto; }
@media (max-width: 900px) {
  .domains.chain { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .domains.support { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rowlabel { display: none; }
  .search { flex-wrap: wrap; }
  .legend { display: none; }
}
</style>
