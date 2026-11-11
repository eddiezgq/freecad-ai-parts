<template>
  <div class="design">
    <div class="tools">
      <span class="muted small">{{ d?.design ? $t('第 {r} 版设计', { r: d.design.rev }) : $t('还没有设计') }}
        <template v-if="d?.design?.status === 'released'"> · {{ $t('已发布，改动会出新版本') }}</template></span>
      <button class="btn ghost" :disabled="!editable || busy" @click="draft">{{ $t('照估算起草') }}</button>
      <button class="btn ghost" :disabled="!editable" @click="addItem">{{ $t('加新物料') }}</button>
      <button class="btn" :disabled="!editable || busy || !dirty" @click="save">{{ $t('保存设计') }}</button>
      <button class="btn primary" :disabled="!canRelease || busy" @click="release">{{ $t('发布设计') }}</button>
    </div>
    <p v-if="spec.note" class="notebox small">{{ $td(spec.note) }}</p>
    <p v-if="!job.sales_order" class="small warnline">{{ $t('作业还没接单：可以先做设计，接单后才能发布。') }}</p>

    <h3>{{ $t('本单新物料') }}</h3>
    <table class="t">
      <thead><tr><th>{{ $t('编号') }}</th><th>{{ $t('名称') }}</th><th>{{ $t('类别') }}</th><th>{{ $t('单位') }}</th>
        <th class="num">{{ $t('单价') }}</th><th>{{ $t('供应商') }}</th><th></th></tr></thead>
      <tbody>
        <tr v-for="(it, i) in spec.items" :key="i">
          <td><input v-model="it.code" class="mono code" :disabled="!editable" @input="touch"></td>
          <td><input v-model="it.name" :disabled="!editable" @input="touch"></td>
          <td><select v-model="it.kind" :disabled="!editable" @change="kindChanged(it)"><option v-for="k in KINDS" :key="k" :value="k">{{ $t(KIND_ZH[k]) }}</option></select></td>
          <td><input v-model="it.uom" class="short" :disabled="!editable" @input="touch"></td>
          <td class="num"><input v-if="it.kind !== 'make'" v-model.number="it.price" type="number" step="any" class="short" :disabled="!editable" @input="touch"></td>
          <td><select v-if="it.kind !== 'make'" v-model="it.supplier" :disabled="!editable" @change="touch">
            <option :value="undefined">{{ $t('（未定）') }}</option>
            <option v-for="(s, k) in suppliers" :key="k" :value="k">{{ $td(s) }}</option></select></td>
          <td><button v-if="editable" class="x" :aria-label="$t('删去这一行')" @click="spec.items.splice(i, 1); touch()">×</button></td>
        </tr>
        <tr v-if="!spec.items.length"><td colspan="7" class="muted small">{{ $t('没有新物料：全部用现有物料。要改的现有自制件，在下面点“复制为新件”。') }}</td></tr>
      </tbody>
    </table>

    <div v-for="(b, bi) in spec.boms" :key="b.item" class="bom">
      <h3><span class="mono">{{ b.item }}</span> {{ nameOf(b.item) }}</h3>
      <div class="cols">
        <div>
          <div class="sub">{{ $t('工艺（每件分钟）') }}</div>
          <div v-for="(st, si) in b.routing" :key="si" class="line">
            <select v-model="st[0]" :disabled="!editable" @change="touch"><option v-for="o in ops" :key="o" :value="o">{{ $td(o) }}</option></select>
            <input v-model.number="st[1]" type="number" step="any" class="short" :disabled="!editable" @input="touch">
            <button v-if="editable" class="x" :aria-label="$t('删去这一行')" @click="b.routing.splice(si, 1); touch()">×</button>
          </div>
          <button v-if="editable" class="btn ghost tiny" @click="b.routing.push([ops[0], 10]); touch()">{{ $t('加工序') }}</button>
        </div>
        <div>
          <div class="sub">{{ $t('子件（每件用量）') }}</div>
          <div v-for="(c, ci) in b.components" :key="ci" class="line">
            <input v-model="c[0]" class="mono code" list="etod-items" :disabled="!editable" @input="touch">
            <input v-model.number="c[1]" type="number" step="any" class="short" :disabled="!editable" @input="touch">
            <span class="small muted nm">{{ nameOf(c[0]) }}</span>
            <button v-if="editable && makeable(c[0])" class="btn ghost tiny" :disabled="dirty" :title="dirty ? $t('先保存设计') : ''"
              @click="copyAsNew(b.item, c[0])">{{ $t('复制为新件') }}</button>
            <button v-if="editable" class="x" :aria-label="$t('删去这一行')" @click="b.components.splice(ci, 1); touch()">×</button>
          </div>
          <button v-if="editable" class="btn ghost tiny" @click="b.components.push(['', 1]); touch()">{{ $t('加子件') }}</button>
        </div>
      </div>
      <button v-if="editable && bi > 0" class="btn ghost tiny" @click="spec.boms.splice(bi, 1); touch()">{{ $t('删去这组物料清单') }}</button>
    </div>
    <datalist id="etod-items"><option v-for="it in allItems" :key="it.code" :value="it.code">{{ $td(it.name) }}</option></datalist>
    <p v-if="!spec.boms.length" class="empty">{{ $t('还没有物料清单：点“照估算起草”。') }}</p>

    <div v-if="spec.outside?.length" class="small muted">{{ $t('外协（接单后转采购，第 139c 段）：{a}', { a: spec.outside.map((o) => o.desc).join(', ') }) }}</div>
    <div v-if="dirty" class="small warnline">{{ $t('有改动还没保存：检查结果是上次保存的。') }}</div>
    <div v-for="e in d?.errors || []" :key="e" class="err small">✗ {{ $td(e) }}</div>
    <div v-for="w in d?.warnings || []" :key="w" class="warnline small">{{ $t('！{a}', { a: $td(w) }) }}</div>
    <div v-if="d?.affected?.length" class="warnbox small">{{ $t('设计改版会影响这些单据，发布后请逐条处理：') }}
      <span v-for="a in d.affected" :key="a.name" class="mono">{{ a.doctype }} {{ a.name }} </span></div>
    <EtoChange :key="'chg' + (d?.revisions?.length || 0)" :job="job" @changed="load(); $emit('changed')" />

    <h3>{{ $t('设计版本') }}</h3>
    <div v-for="r in d?.revisions || []" :key="r.rev" class="small">
      <b>{{ $t('第 {r} 版', { r: r.rev }) }}</b>
      <span class="pill" :class="r.status === 'released' ? 'good' : 'info'">{{ $t(ST[r.status] || r.status) }}</span>
      <span class="muted"> {{ r.created_by }}<template v-if="r.released_by"> · {{ $t('{w} 确认发布', { w: r.released_by }) }}</template></span>
      <span v-if="r.fingerprint" class="mono muted"> · {{ r.fingerprint.slice(0, 12) }}</span></div>
    <div v-if="msg" :class="msgOk ? 'ok' : 'err'" class="small">{{ msg }}</div>
    <ProposalModal v-if="pid" :pid="pid" @close="pid = null; load()" @done="load(); $emit('changed')" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { api, get, post } from '../lib/api';
import { t as $t, td as $td, tk } from '../lib/i18n';
import ProposalModal from './ProposalModal.vue';
import EtoChange from './EtoChange.vue';

const props = defineProps({ job: Object, ops: Array, items: Array, suppliers: Object });
defineEmits(['changed']);
const KINDS = ['make', 'buy', 'raw'];
const KIND_ZH = { make: tk('自制件'), buy: tk('外购件'), raw: tk('原材料') };
const ST = { released: tk('已发布'), draft: tk('草稿') };
const d = ref(null);
const spec = ref({ items: [], boms: [], outside: [], note: '' });
const dirty = ref(false);
const busy = ref(false);
const pid = ref(null);
const msg = ref('');
const msgOk = ref(true);

const jn = computed(() => props.job.job_no);
const editable = computed(() => !d.value?.pending_proposal);
const canRelease = computed(() => props.job.sales_order && d.value?.design && d.value.design.status === 'draft' && !d.value.errors.length
  && !dirty.value && editable.value);
const allItems = computed(() => [...spec.value.items.map((i) => ({ code: i.code, name: i.name })), ...(props.items || [])]);
const nameOf = (c) => (c === jn.value ? props.job.title : (allItems.value.find((i) => i.code === c)?.name || ''));
const makeable = (c) => (props.items || []).some((i) => i.code === c && i.bom);
function touch() { dirty.value = true; }
function say(t, ok = true) { msg.value = t; msgOk.value = ok; }
function kindChanged(it) {
  touch();
  if (it.kind === 'make' && !spec.value.boms.some((b) => b.item === it.code)) spec.value.boms.push({ item: it.code, routing: [], components: [] });
}
function addItem() { spec.value.items.push({ code: jn.value + '-', name: '', kind: 'buy', uom: 'Nos' }); touch(); }

async function load() {
  d.value = await get(`/eto/jobs/${encodeURIComponent(jn.value)}/design`);
  spec.value = JSON.parse(JSON.stringify(d.value.design?.spec || { items: [], boms: [], outside: [], note: '' }));
  dirty.value = false;
}
async function draft() {
  if (spec.value.boms.length && !window.confirm($t('起草的结果会替换现在的设计（保存后才生效），继续吗？'))) return;
  busy.value = true;
  try { spec.value = await post(`/eto/jobs/${encodeURIComponent(jn.value)}/design/draft`); dirty.value = true; } catch (e) { say(e.message, false); } finally { busy.value = false; }
}
async function save() {
  busy.value = true;
  try {
    d.value = await api('PUT', `/eto/jobs/${encodeURIComponent(jn.value)}/design`, { spec: spec.value });
    spec.value = JSON.parse(JSON.stringify(d.value.design.spec));
    dirty.value = false;
    say($t('已保存第 {r} 版设计。', { r: d.value.design.rev }));
  } catch (e) { say(e.message, false); } finally { busy.value = false; }
}
async function copyAsNew(parent, code) {
  const suffix = window.prompt($t('新件编号的后缀（新编号 = 作业号-后缀），如 SH：'), '');
  if (!suffix) return;
  try {
    spec.value = await post(`/eto/jobs/${encodeURIComponent(jn.value)}/design/copy`, { spec: spec.value, parent, code, suffix });
    touch();
  } catch (e) { say(e.message, false); }
}
async function release() {
  busy.value = true;
  try { pid.value = (await post(`/eto/jobs/${encodeURIComponent(jn.value)}/design/release`)).proposal_id; await load(); } catch (e) { say(e.message, false); } finally { busy.value = false; }
}
watch(jn, load);
onMounted(load);
</script>

<style scoped>
.tools { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.tools > span { margin-right: auto; }
h3 { font-size: 14px; margin: 14px 0 6px; }
.t td { padding: 3px 4px; }
input, select { border: 1px solid var(--line); border-radius: 5px; padding: 3px 5px; font: inherit; font-size: 13px; }
input.code { width: 170px; } input.short { width: 76px; text-align: right; }
.bom { border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; margin: 10px 0; }
.bom h3 { margin-top: 2px; }
.cols { display: grid; grid-template-columns: 1fr 1.3fr; gap: 16px; }
.sub { font-size: 12px; color: var(--muted, #888); margin-bottom: 4px; }
.line { display: flex; gap: 6px; align-items: center; margin-bottom: 4px; }
.line select { max-width: 240px; }
.nm { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.btn.tiny { height: 24px; font-size: 12px; padding: 0 8px; }
.x { border: none; background: none; font-size: 16px; cursor: pointer; color: var(--muted, #888); }
.notebox { background: var(--accent-bg); border-radius: 8px; padding: 8px 10px; }
.warnbox { background: var(--warn-bg); color: var(--warn-ink); border-radius: 8px; padding: 8px 10px; margin-top: 8px; }
.err { color: var(--bad); } .ok { color: var(--good); } .warnline { color: var(--warn-ink); }
.empty { color: var(--muted, #888); }
@media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
</style>
