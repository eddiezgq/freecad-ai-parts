<template>
  <div class="page">
    <div v-if="err" class="err">{{ err }} <router-link to="/ont/map">{{ $t('回厂情中枢') }}</router-link></div>
    <template v-if="o">
      <header class="head card" :style="{ '--c': DOMAIN_COLOR[o.domain] }">
        <div class="crumb small"><router-link to="/ont/map">{{ $t('厂情中枢') }}</router-link> / <span>{{ domainLabel }}</span> /
          <router-link :to="'/ont/' + o.type">{{ $td(o.label) }}</router-link></div>
        <div class="title">
          <span class="badge">{{ $td(o.label) }}</span>
          <h1>{{ $td(o.display) }}</h1>
          <span v-if="o.display !== o.key" class="mono muted">{{ $td(o.key) }}</span>
          <span v-if="tone" class="pill" :class="tone">{{ stateText }}</span>
          <button class="btn sm ghost askbtn" @click="ask($t('{a} 现在怎么样？有什么影响？', { a: $td(o.key) }))">{{ $t('问 AI 这个对象') }}</button>
        </div>
        <div class="small muted">
          {{ $t('{a} · 首次出现 {b} · 最近更新 {c}', { a: $td(o.label_en), b: fmtTs(o.first_ts) || '—', c: fmtTs(o.updated_at) }) }}
          <template v-if="o.aliases.length"> {{ $t('· 也叫：') }}<span class="mono">{{ o.aliases.join($t('、')) }}</span></template>
        </div>
      </header>

      <div class="cols">
        <section class="card attrs">
          <div class="card-head"><h2>{{ $t('属性') }}</h2><span class="muted small">{{ $t('ⓘ 看原始记录') }}</span></div>
          <table class="t">
            <tbody><tr v-for="a in o.attrs" :key="a.name">
              <th>{{ $td(a.label) }}</th>
              <td class="mono">{{ fmtVal(a.value, a.unit) }}</td>
              <td class="srccol"><button v-if="a.source" class="src-btn" :title="$t('来源：总线消息 #') + a.source" @click="showSource(a.source, a.label)">ⓘ</button></td>
            </tr></tbody>
          </table>
          <p v-if="!o.attrs.length" class="muted small">{{ $t('没有属性数据。') }}</p>
          <p class="muted small">{{ $t('数据来源：{a}', { a: o.sources.join($t('、')) || '—' }) }}</p>
        </section>

        <section class="card graph">
          <OntGraph :type="o.type" :obj-key="o.key" />
        </section>

        <section class="card tl">
          <div class="card-head"><h2>{{ $t('时间线') }}</h2>
            <select v-model="kind" class="more" :aria-label="$t('事件种类')"><option value="">{{ $t('全部') }}</option><option v-for="k in kinds" :key="k" :value="k">{{ kindLabel(k) }}</option></select></div>
          <ol class="events">
            <li v-for="(e, i) in shownEvents" :key="i">
              <span class="ts mono small">{{ fmtTs(e.ts) }}</span>
              <span class="ev">{{ e.text || kindLabel(e.kind) }}</span>
              <span v-for="c in e.changes" :key="c.prop" class="chg small"><b>{{ $td(c.label) }}</b> {{ fmtVal(c.old) }} → {{ fmtVal(c.new, c.unit) }}</span>
              <button v-if="e.seq" class="src-btn" :title="$t('来源：总线消息 #') + e.seq" @click="showSource(e.seq, e.text)">ⓘ</button>
            </li>
          </ol>
          <p v-if="!shownEvents.length" class="muted small">{{ $t('没有事件。') }}</p>
        </section>
      </div>

      <section class="card">
        <div class="card-head"><h2>{{ $t('影响面') }}</h2><span class="muted small">{{ $t('从这个对象出发，往上游找原因、往下游看影响（不开异常）') }}</span>
          <button v-if="!impact" class="more btn" :disabled="impactBusy" @click="loadImpact">{{ impactBusy ? $t('计算中…') : $t('算一下影响面') }}</button></div>
        <template v-if="impact">
          <ul class="small isum"><li v-for="(x, i) in impact.summary" :key="i">{{ x }}</li></ul>
          <div class="impact"><ChainGraph :chain="impact" @edge="(e) => (ibasis = e)" /></div>
          <p v-if="ibasis" class="small muted">{{ $t('依据：{a} —— {b}', { a: $td(ibasis.label), b: $td(ibasis.basis.how) }) }}<template v-if="ibasis.basis.seq">
            <button class="src-btn" @click="showSource(ibasis.basis.seq, ibasis.label)">ⓘ #{{ $td(ibasis.basis.seq) }}</button></template></p>
        </template>
      </section>

      <section class="card">
        <div class="card-head"><h2>{{ $t('相关对象') }}</h2><span class="muted small">{{ $t('按关系分组；每组最多显示 50 个') }}</span>
          <button class="more btn ghost sm" :disabled="!o.links.length" @click="exportCsv">{{ $t('导出 CSV') }}</button></div>
        <p v-if="!o.links.length" class="muted small">{{ $t('还没有和其他对象的关系。') }}</p>
        <details v-for="g in o.links" :key="g.link + g.direction" open class="grp">
          <summary><b>{{ $td(g.label) }}</b> <span class="muted">{{ $td(g.type_label) }}</span> <span class="pill mute">{{ $td(g.items.length) }}{{ g.more ? '+' : '' }}</span>
            <router-link v-if="g.more" class="small" :to="'/ont/' + g.type">{{ $t('查看全部') }}</router-link></summary>
          <table class="t">
            <tbody><tr v-for="it in g.items" :key="it.key">
              <td><ObjLink :type="g.type" :k="it.key">{{ $td(it.display) }}</ObjLink></td>
              <td class="small muted mono">{{ linkProps(it.props) }}</td>
              <td class="srccol"><button v-if="it.seq" class="src-btn" @click="showSource(it.seq, g.label)">ⓘ</button></td>
            </tr></tbody>
          </table>
        </details>
      </section>
    </template>

    <div v-if="src" class="modal-mask" @click.self="src = null">
      <div class="modal src-modal" role="dialog" :aria-label="$t('原始记录')">
        <div class="card-head"><h2>{{ $t('原始记录 · {a}', { a: srcTitle }) }}</h2><button class="more btn ghost sm" @click="src = null">{{ $t('关闭') }}</button></div>
        <div v-if="src.error" class="err">{{ $td(src.error) }}</div>
        <template v-else>
          <p class="small">{{ $t('总线消息') }} <b class="mono">#{{ $td(src.seq) }}</b> {{ $t('· {a} · 来源', { a: fmtTs(src.ts) }) }} <span class="mono">{{ $td(src.source) }}</span></p>
          <p class="small mono muted">{{ $t('{a}（{b}）', { a: $td(src.topic), b: $td(src.type) }) }}<template v-if="src.corr"> {{ $t('· 关联 {a}', { a: $td(src.corr) }) }}</template></p>
          <pre class="raw">{{ JSON.stringify(src.data, null, 2) }}</pre>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
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

const KIND = { created: $t('出现'), updated: $t('更新'), processed: $t('加工'), started: $t('开工'), completed: $t('完工'), runin: $t('跑合'), nonconforming: $t('不合格'),
  removed: $t('卸下'), recovered: $t('恢复'), down: $t('停机'), recover: $t('恢复'), tool_change: $t('换刀') };
const kindLabel = (k) => KIND[k] || (k.startsWith('erp.') ? 'ERPNext ' + k.slice(4) : k);
const kinds = computed(() => [...new Set(events.value.map((e) => e.kind))]);
const shownEvents = computed(() => events.value.filter((e) => !kind.value || e.kind === kind.value));
const domainLabel = computed(() => ont.domains[o.value?.domain]?.label || o.value?.domain);
const propsObj = computed(() => Object.fromEntries((o.value?.attrs || []).map((a) => [a.name, a.value])));
const tone = computed(() => stateTone(propsObj.value));
const stateText = computed(() => { const p = propsObj.value; return p.status ?? p.state ?? p.result ?? p.health; });

function linkProps(p) {
  if (!p) return '';
  const L = { machine: $t('设备'), operation: $t('工序'), tool: $t('刀具'), tool_life_pct: $t('刀具剩余%'), cycle_time_s: $t('节拍 s'), qty: $t('数量'), good: $t('合格') };
  return Object.entries(p).filter(([k]) => k !== 'start' && k !== 'end').map(([k, v]) => `${L[k] || k} ${fmtVal(v)}`).join(' · ');
}

async function showSource(seq, title) {
  srcTitle.value = title || '';
  src.value = { seq };
  try { src.value = await lineage(seq); } catch (e) { src.value = { error: e.message }; }
}

function exportCsv() {
  const rows = [[$t('关系'), $t('对象类型'), $t('编号'), $t('名称'), $t('链接属性')]];
  for (const g of o.value.links) for (const it of g.items) rows.push([g.label, g.type_label, it.key, it.display, it.props]);
  download($t('{a}_{b}_相关对象.csv', { a: o.value.type, b: o.value.key.replace(/\W+/g, '_') }), toCsv(rows));
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
