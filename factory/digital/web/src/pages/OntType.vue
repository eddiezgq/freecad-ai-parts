<template>
  <div class="page">
    <div class="page-title">
      <h1><router-link to="/ont/map" class="back">{{ $t('全貌地图') }}</router-link> / {{ spec?.label || type }}</h1>
      <span class="muted">{{ $td(spec?.label_en) }} · {{ $td(spec?.domain_label) }} · {{ $td(spec?.maturity_label) }}<template v-if="spec?.key"> {{ $t('· 编号：{a}', { a: $td(spec.key) }) }}</template></span>
    </div>
    <div v-if="err" class="err">{{ err }}</div>

    <section v-if="spec" class="card">
      <div class="card-head"><h2>{{ $t('筛选') }}</h2><span class="muted small">{{ $t('按属性条件筛出一组对象（最多 5000 个），可导出 CSV') }}</span></div>
      <div class="filters">
        <div v-for="(w, i) in where" :key="i" class="cond">
          <select v-model="w.prop" :aria-label="$t('属性')"><option v-for="p in spec.props" :key="p.name" :value="p.name">{{ $td(p.label) }}</option></select>
          <select v-model="w.op" :aria-label="$t('条件')"><option v-for="o in ops" :key="o" :value="o">{{ o === 'contains' ? $t('包含') : o }}</option></select>
          <input v-model="w.value" :aria-label="$t('值')">
          <button class="btn ghost sm" @click="where.splice(i, 1)">×</button>
        </div>
        <button class="btn ghost sm" @click="where.push({ prop: spec.props[0]?.name, op: '=', value: '' })">{{ $t('+ 条件') }}</button>
        <button class="btn primary sm" @click="run">{{ $t('查询') }}</button>
        <button class="btn sm" :disabled="!rows.length" @click="exportCsv">{{ $t('导出 CSV') }}</button>
      </div>
    </section>

    <section v-if="spec" class="card">
      <div class="card-head"><h2>{{ $t('{a} 个对象', { a: count.toLocaleString() }) }}</h2><span v-if="count >= 500" class="muted small">{{ $t('只显示前 500 个，用筛选缩小范围') }}</span></div>
      <div v-if="!rows.length && !loading" class="empty">
        {{ spec.maturity === 'have' ? $t('还没有这类对象。') : $t('这类对象的数据还没有接入（') + spec.maturity_label + $t('）。') }}
        <span class="muted small">{{ $t('数据来源：{a}', { a: (spec.sources || []).join($t('、')) || $t('待定') }) }}</span>
      </div>
      <div v-else class="scroll">
        <table class="t">
          <thead><tr><th>{{ $t('对象') }}</th><th v-for="p in cols" :key="p.name">{{ $td(p.label) }}<span v-if="p.unit" class="muted">{{ $t('（{a}）', { a: $td(p.unit) }) }}</span></th></tr></thead>
          <tbody><tr v-for="r in rows" :key="r.key">
            <td><router-link :to="objPath(type, r.key)"><b>{{ $td(r.display) }}</b></router-link></td>
            <td v-for="p in cols" :key="p.name" class="mono small">{{ fmtVal(r.props[p.name]) }}</td>
          </tr></tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ont, loadTypes, query, objPath, fmtVal, toCsv, download } from '../lib/ont';

const route = useRoute();
const type = computed(() => route.params.type);
const spec = computed(() => ont.byName[type.value]);
const where = ref([]);
const rows = ref([]);
const count = ref(0);
const err = ref('');
const loading = ref(false);
const ops = ['=', '!=', '>', '<', '>=', '<=', 'contains'];
const cols = computed(() => (spec.value?.props || []).filter((p) => p.type !== 'json').slice(0, 8));

async function run() {
  loading.value = true;
  err.value = '';
  try {
    const r = await query({ type: type.value, where: where.value.filter((w) => w.prop && w.value !== ''), limit: 5000 });
    count.value = r.count;
    rows.value = r.objects.slice(0, 500);
    all = r.objects;
  } catch (e) { err.value = e.message; } finally { loading.value = false; }
}
let all = [];
function exportCsv() {
  const ps = spec.value.props;
  download(`${type.value}.csv`, toCsv([[$t('编号'), $t('名称'), ...ps.map((p) => p.label)], ...all.map((r) => [r.key, r.display, ...ps.map((p) => r.props[p.name])])]));
}

onMounted(async () => {
  try { await loadTypes(); } catch (e) { err.value = e.message; return; }
  if (!spec.value) { err.value = $t('没有这类对象：') + type.value; return; }
  run();
});
watch(type, () => { where.value = []; run(); });
</script>

<style scoped>
.back { color: var(--muted); font-weight: 500; }
.filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.cond { display: flex; gap: 4px; }
.cond select, .cond input { height: 30px; border: 1px solid #C8CEC7; border-radius: 6px; padding: 0 6px; }
.cond input { width: 140px; }
.btn.sm { height: 30px; padding: 0 10px; }
.scroll { overflow-x: auto; }
</style>
