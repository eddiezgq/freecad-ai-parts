<template>
  <div class="page">
    <div v-if="err" class="err">{{ err }} <router-link to="/ont/map">回厂情中枢</router-link></div>
    <template v-if="o">
      <header class="head card" :style="{ '--c': DOMAIN_COLOR[o.domain] }">
        <div class="crumb small"><router-link to="/ont/map">厂情中枢</router-link> / <span>{{ domainLabel }}</span> /
          <router-link :to="'/ont/' + o.type">{{ o.label }}</router-link></div>
        <div class="title">
          <span class="badge">{{ o.label }}</span>
          <h1>{{ o.display }}</h1>
          <span v-if="o.display !== o.key" class="mono muted">{{ o.key }}</span>
          <span v-if="tone" class="pill" :class="tone">{{ stateText }}</span>
          <button class="btn sm ghost askbtn" @click="ask(o.key + ' 现在怎么样？有什么影响？')">问 AI 这个对象</button>
        </div>
        <div class="small muted">
          {{ o.label_en }} · 首次出现 {{ fmtTs(o.first_ts) || '—' }} · 最近更新 {{ fmtTs(o.updated_at) }}
          <template v-if="o.aliases.length"> · 也叫：<span class="mono">{{ o.aliases.join('、') }}</span></template>
        </div>
      </header>

      <div class="cols">
        <section class="card attrs">
          <div class="card-head"><h2>属性</h2><span class="muted small">ⓘ 看原始记录</span></div>
          <table class="t">
            <tbody><tr v-for="a in o.attrs" :key="a.name">
              <th>{{ a.label }}</th>
              <td class="mono">{{ fmtVal(a.value, a.unit) }}</td>
              <td class="srccol"><button v-if="a.source" class="src-btn" :title="'来源：总线消息 #' + a.source" @click="showSource(a.source, a.label)">ⓘ</button></td>
            </tr></tbody>
          </table>
          <p v-if="!o.attrs.length" class="muted small">没有属性数据。</p>
          <p class="muted small">数据来源：{{ o.sources.join('、') || '—' }}</p>
        </section>

        <section class="card graph">
          <OntGraph :type="o.type" :obj-key="o.key" />
        </section>

        <section class="card tl">
          <div class="card-head"><h2>时间线</h2>
            <select v-model="kind" class="more" aria-label="事件种类"><option value="">全部</option><option v-for="k in kinds" :key="k" :value="k">{{ kindLabel(k) }}</option></select></div>
          <ol class="events">
            <li v-for="(e, i) in shownEvents" :key="i">
              <span class="ts mono small">{{ fmtTs(e.ts) }}</span>
              <span class="ev">{{ e.text || kindLabel(e.kind) }}</span>
              <span v-for="c in e.changes" :key="c.prop" class="chg small"><b>{{ c.label }}</b> {{ fmtVal(c.old) }} → {{ fmtVal(c.new, c.unit) }}</span>
              <button v-if="e.seq" class="src-btn" :title="'来源：总线消息 #' + e.seq" @click="showSource(e.seq, e.text)">ⓘ</button>
            </li>
          </ol>
          <p v-if="!shownEvents.length" class="muted small">没有事件。</p>
        </section>
      </div>

      <section class="card">
        <div class="card-head"><h2>影响面</h2><span class="muted small">从这个对象出发，往上游找原因、往下游看影响（不开异常）</span>
          <button v-if="!impact" class="more btn" :disabled="impactBusy" @click="loadImpact">{{ impactBusy ? '计算中…' : '算一下影响面' }}</button></div>
        <template v-if="impact">
          <ul class="small isum"><li v-for="(x, i) in impact.summary" :key="i">{{ x }}</li></ul>
          <div class="impact"><ChainGraph :chain="impact" @edge="(e) => (ibasis = e)" /></div>
          <p v-if="ibasis" class="small muted">依据：{{ ibasis.label }} —— {{ ibasis.basis.how }}<template v-if="ibasis.basis.seq">
            <button class="src-btn" @click="showSource(ibasis.basis.seq, ibasis.label)">ⓘ #{{ ibasis.basis.seq }}</button></template></p>
        </template>
      </section>

      <section class="card">
        <div class="card-head"><h2>相关对象</h2><span class="muted small">按关系分组；每组最多显示 50 个</span>
          <button class="more btn ghost sm" :disabled="!o.links.length" @click="exportCsv">导出 CSV</button></div>
        <p v-if="!o.links.length" class="muted small">还没有和其他对象的关系。</p>
        <details v-for="g in o.links" :key="g.link + g.direction" open class="grp">
          <summary><b>{{ g.label }}</b> <span class="muted">{{ g.type_label }}</span> <span class="pill mute">{{ g.items.length }}{{ g.more ? '+' : '' }}</span>
            <router-link v-if="g.more" class="small" :to="'/ont/' + g.type">查看全部</router-link></summary>
          <table class="t">
            <tbody><tr v-for="it in g.items" :key="it.key">
              <td><ObjLink :type="g.type" :k="it.key">{{ it.display }}</ObjLink></td>
              <td class="small muted mono">{{ linkProps(it.props) }}</td>
              <td class="srccol"><button v-if="it.seq" class="src-btn" @click="showSource(it.seq, g.label)">ⓘ</button></td>
            </tr></tbody>
          </table>
        </details>
      </section>
    </template>

    <div v-if="src" class="modal-mask" @click.self="src = null">
      <div class="modal src-modal" role="dialog" aria-label="原始记录">
        <div class="card-head"><h2>原始记录 · {{ srcTitle }}</h2><button class="more btn ghost sm" @click="src = null">关闭</button></div>
        <div v-if="src.error" class="err">{{ src.error }}</div>
        <template v-else>
          <p class="small">总线消息 <b class="mono">#{{ src.seq }}</b> · {{ fmtTs(src.ts) }} · 来源 <span class="mono">{{ src.source }}</span></p>
          <p class="small mono muted">{{ src.topic }}（{{ src.type }}）<template v-if="src.corr"> · 关联 {{ src.corr }}</template></p>
          <pre class="raw">{{ JSON.stringify(src.data, null, 2) }}</pre>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import OntGraph from '../components/OntGraph.vue';
import ChainGraph from '../components/ChainGraph.vue';
import { get } from '../lib/api';
import { ask } from '../lib/ai';
import ObjLink from '../components/ObjLink.vue';
import { ont, loadTypes, getObj, getTimeline, lineage, fmtVal, fmtTs, stateTone, toCsv, download, DOMAIN_COLOR } from '../lib/ont';

const route = useRoute();
const o = ref(null);
const events = ref([]);
const err = ref('');
const kind = ref('');
const src = ref(null);
const srcTitle = ref('');
const impact = ref(null);
const impactBusy = ref(false);
const ibasis = ref(null);
async function loadImpact() {
  impactBusy.value = true;
  try { impact.value = await get(`/ont/impact/${o.value.type}/${o.value.key.split('/').map(encodeURIComponent).join('/')}`); } catch (e) { alert(e.message); } finally { impactBusy.value = false; }
}

const KIND = { created: '出现', updated: '更新', processed: '加工', started: '开工', completed: '完工', runin: '跑合', nonconforming: '不合格',
  removed: '卸下', recovered: '恢复', down: '停机', recover: '恢复', tool_change: '换刀' };
const kindLabel = (k) => KIND[k] || (k.startsWith('erp.') ? 'ERPNext ' + k.slice(4) : k);
const kinds = computed(() => [...new Set(events.value.map((e) => e.kind))]);
const shownEvents = computed(() => events.value.filter((e) => !kind.value || e.kind === kind.value));
const domainLabel = computed(() => ont.domains[o.value?.domain]?.label || o.value?.domain);
const propsObj = computed(() => Object.fromEntries((o.value?.attrs || []).map((a) => [a.name, a.value])));
const tone = computed(() => stateTone(propsObj.value));
const stateText = computed(() => { const p = propsObj.value; return p.status ?? p.state ?? p.result ?? p.health; });

function linkProps(p) {
  if (!p) return '';
  const L = { machine: '设备', operation: '工序', tool: '刀具', tool_life_pct: '刀具剩余%', cycle_time_s: '节拍 s', qty: '数量', good: '合格' };
  return Object.entries(p).filter(([k]) => k !== 'start' && k !== 'end').map(([k, v]) => `${L[k] || k} ${fmtVal(v)}`).join(' · ');
}

async function showSource(seq, title) {
  srcTitle.value = title || '';
  src.value = { seq };
  try { src.value = await lineage(seq); } catch (e) { src.value = { error: e.message }; }
}

function exportCsv() {
  const rows = [['关系', '对象类型', '编号', '名称', '链接属性']];
  for (const g of o.value.links) for (const it of g.items) rows.push([g.label, g.type_label, it.key, it.display, it.props]);
  download(`${o.value.type}_${o.value.key.replace(/\W+/g, '_')}_相关对象.csv`, toCsv(rows));
}

async function load() {
  err.value = '';
  o.value = null;
  impact.value = null;
  ibasis.value = null;
  events.value = [];
  kind.value = '';
  const { type, key } = route.params;
  const k = Array.isArray(key) ? key.join('/') : key;
  try {
    await loadTypes();
    o.value = await getObj(type, k);
    events.value = (await getTimeline(type, k)).events;
  } catch (e) { err.value = e.message; }
}
watch(() => route.fullPath, () => { if (route.path.startsWith('/ont/')) load(); }, { immediate: true });
</script>

<style scoped>
.askbtn { margin-left: auto; }
.head { border-top: 5px solid var(--c); }
.crumb { color: var(--muted); margin-bottom: 4px; }
.title { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.title h1 { font-size: 20px; }
.badge { background: var(--c); color: #fff; font-size: 12px; padding: 2px 8px; border-radius: 4px; align-self: center; }
.cols { display: grid; grid-template-columns: 300px minmax(0, 1fr) 320px; gap: 16px; align-items: start; }
.attrs th { width: 40%; font-weight: 500; color: var(--muted); }
.attrs td { word-break: break-all; }
.srccol { width: 22px; text-align: right; }
.src-btn { border: none; background: none; color: var(--accent); cursor: pointer; padding: 0 2px; font-size: 13px; }
.graph { min-height: 480px; display: flex; flex-direction: column; }
.graph > * { flex: 1; }
.tl { max-height: 560px; overflow: auto; }
.tl select { height: 28px; border: 1px solid var(--line); border-radius: 6px; }
.events { list-style: none; margin: 0; padding: 0; }
.events li { padding: 6px 0 6px 12px; border-left: 2px solid var(--line); position: relative; display: flex; flex-direction: column; gap: 2px; }
.events li::before { content: ''; position: absolute; left: -5px; top: 10px; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
.events .src-btn { position: absolute; right: 0; top: 4px; }
.ts { color: var(--muted); }
.chg { color: var(--muted); }
.grp { margin-bottom: 8px; }
.impact { min-height: 500px; display: flex; flex-direction: column; }
.impact > * { flex: 1; }
.isum { margin: 0 0 8px; padding-left: 18px; }
.grp summary { cursor: pointer; padding: 4px 0; display: flex; gap: 8px; align-items: center; }
.btn.sm { height: 28px; padding: 0 10px; }
.src-modal { width: min(680px, 94vw); max-height: 86vh; overflow: auto; }
.raw { background: var(--surface-2); padding: 10px; border-radius: 6px; font-size: 12px; overflow: auto; max-height: 50vh; }
@media (max-width: 1200px) { .cols { grid-template-columns: 1fr 1fr; } .graph { grid-column: 1 / -1; order: 3; } }
@media (max-width: 720px) { .cols { grid-template-columns: 1fr; } }
</style>
