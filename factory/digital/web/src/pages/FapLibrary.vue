<template>
  <div class="page">
    <div class="page-title"><h1>选型零件库</h1>
      <span class="muted">与 FreeCAD AI Parts 选型用的是同一份零件库：公共库叠加企业库（同一零件以企业库为准）；参数照样本原样，带资料出处，没有的不填</span></div>
    <section class="card">
      <div class="field-row">
        <select v-model="cat" @change="load"><option value="">全部品类</option>
          <option v-for="(n, k) in cats" :key="k" :value="k">{{ n }}</option></select>
        <input v-model="q" type="search" placeholder="厂商、型号，如 CSF 25" @keyup.enter="load">
        <button class="btn" type="button" @click="load">查</button>
      </div>
    </section>
    <div class="row">
      <section class="card side">
        <div v-if="!items.length" class="empty">没有符合条件的零件。本地版启动时把仓库的 data/library 挂进工厂；企业库在 FreeCAD 设置里选的文件夹。</div>
        <table v-else class="t">
          <thead><tr><th>品类</th><th>厂商</th><th>型号</th><th>库</th></tr></thead>
          <tbody><tr v-for="i in items" :key="i.id" :class="{ on: cur?.id === i.id }" @click="open(i.id)" style="cursor:pointer">
            <td>{{ i.category_name }}</td><td>{{ i.vendor }}</td><td class="mono">{{ i.model }}</td>
            <td class="small">{{ i.library === 'enterprise' ? '企业' : '公共' }}</td>
          </tr></tbody>
        </table>
      </section>
      <section class="card grow">
        <div v-if="!cur" class="empty">选一个零件看参数与出处。</div>
        <template v-else>
          <div class="card-head"><h2>{{ cur.vendor }} {{ cur.model }} <span class="muted small mono">{{ cur.id }}</span></h2></div>
          <table class="t">
            <thead><tr><th>参数</th><th class="num">值</th><th>条件</th><th>出处</th></tr></thead>
            <tbody><tr v-for="(pv, k) in cur.params" :key="k">
              <td class="mono small">{{ k }}</td><td class="num">{{ show(pv) }}</td>
              <td class="small">{{ pv.condition || '' }}</td>
              <td class="small">{{ pv.source ? pv.source.doc + (pv.source.page ? ' 第 ' + pv.source.page + ' 页' : '') : '—' }}</td>
            </tr></tbody>
          </table>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import { get } from '../lib/api';

const cats = ref({});
const items = ref([]);
const cat = ref('');
const q = ref('');
const cur = ref(null);
function show(pv) {
  if (pv == null || typeof pv !== 'object') return pv ?? '';
  if ('value' in pv) return pv.value;
  if ('nominal' in pv) return pv.nominal;
  if ('min' in pv || 'max' in pv) return (pv.min ?? '') + '–' + (pv.max ?? '');
  return '';
}
async function load() {
  const r = await get('/fap/components?category=' + encodeURIComponent(cat.value) + '&q=' + encodeURIComponent(q.value));
  cats.value = r.categories; items.value = r.items;
}
async function open(id) { cur.value = await get('/fap/components/' + encodeURIComponent(id)); }
onMounted(load);
</script>
