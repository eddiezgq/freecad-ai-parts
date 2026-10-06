<template>
  <div class="page">
    <div class="page-title"><h1>CAD 方案</h1>
      <span class="muted">在 FreeCAD 里选型、校验后“发布到工厂”的方案：BOM 里每个零件都来自零件库（公共库或企业库），带资料出处</span></div>
    <div class="row">
      <section class="card side">
        <div class="card-head"><h2>方案</h2></div>
        <div v-if="!rows.length" class="empty">还没有方案。在 FreeCAD 的 AI Parts 工作台点“发布到工厂”。</div>
        <table v-else class="t">
          <thead><tr><th>编号</th><th>名称</th><th class="num">版本</th><th>校验</th></tr></thead>
          <tbody><tr v-for="r in rows" :key="r.code" :class="{ on: cur?.code === r.code }" @click="open(r.code)" style="cursor:pointer">
            <td class="mono b">{{ r.code }}</td><td>{{ r.name }}</td><td class="num">{{ r.revision }}</td>
            <td><span class="pill" :class="TONE[r.overall] || ''">{{ VERDICT[r.overall] || '—' }}</span></td>
          </tr></tbody>
        </table>
      </section>
      <section class="card grow">
        <div v-if="!cur" class="empty">选一个方案看 BOM。</div>
        <template v-else>
          <div class="card-head"><h2>{{ cur.code }} · {{ cur.name }} <span class="muted small">rev {{ cur.revision }} · {{ cur.author }} · {{ timeOf(cur.ts) }}</span></h2></div>
          <table class="t">
            <thead><tr><th>品类</th><th>厂商</th><th>型号</th><th class="num">数量</th><th class="num">单件 kg</th><th>来源</th><th>库</th></tr></thead>
            <tbody><tr v-for="b in cur.bom" :key="b.component_id">
              <td>{{ CAT[b.category] || b.category }}</td><td>{{ b.vendor }}</td><td class="mono">{{ b.model }}</td>
              <td class="num">{{ b.quantity }}</td><td class="num">{{ b.unit_mass_kg ?? '未知' }}</td>
              <td class="small">{{ (b.source_docs || []).join('、') || '—' }}</td>
              <td class="small">{{ b.library === 'enterprise' ? '企业' : b.library === 'public' ? '公共' : '—' }}</td>
            </tr></tbody>
          </table>
          <p v-if="cur.files?.length" class="small">附件：<a v-for="f in cur.files" :key="f.url" :href="f.url">{{ f.name }} </a></p>
          <p v-if="cur.note" class="small">说明：{{ cur.note }}</p>
          <h3 class="small">版本记录</h3>
          <ul class="small"><li v-for="h in cur.history" :key="h.revision">rev {{ h.revision }} · {{ h.author }} · {{ timeOf(h.ts) }}{{ h.note ? '：' + h.note : '' }}</li></ul>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import { get } from '../lib/api';
import { timeOf } from '../lib/fmt';

const CAT = { servo_motor: '伺服电机', reducer: '减速器', drive: '驱动器', bearing: '轴承', adapter: '转接件' };
const VERDICT = { pass: '通过', warn: '注意', unknown: '待确认', fail: '不通过' };
const TONE = { pass: 'ok', warn: 'warn', unknown: 'warn', fail: 'bad' };
const rows = ref([]);
const cur = ref(null);
async function open(code) { cur.value = await get('/cad/designs/' + encodeURIComponent(code)); }
onMounted(async () => { rows.value = await get('/cad/designs'); if (rows.value.length) open(rows.value[0].code); });
</script>
