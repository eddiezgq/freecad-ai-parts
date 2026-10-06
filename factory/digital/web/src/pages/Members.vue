<template>
  <div class="page">
    <div class="page-title"><h1>企业成员</h1>
      <span class="muted">给登录过工作台的问渠账号授权生产（企业）模式的角色；老师账号本来就有全部权限</span></div>
    <section class="card">
      <div v-if="!rows.length" class="empty">还没有人登录过。请对方先用问渠账号登录一次数字工厂，这里就会出现。</div>
      <table v-else class="t">
        <thead><tr><th>姓名（账号编号）</th><th>最近登录</th><th v-for="r in ROLES" :key="r.key">{{ r.name }}</th><th></th></tr></thead>
        <tbody><tr v-for="m in rows" :key="m.uid">
          <td>{{ m.name }}<span v-if="m.teacher" class="pill good small">老师</span></td>
          <td class="small">{{ timeOf(m.last_seen) }}</td>
          <td v-for="r in ROLES" :key="r.key"><input type="checkbox" :disabled="m.teacher" :checked="m.teacher || m.roles.includes(r.key)"
            :aria-label="m.name + ' ' + r.name" @change="toggle(m, r.key, $event.target.checked)"></td>
          <td class="small">{{ m.saved || '' }}</td>
        </tr></tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import { get, post } from '../lib/api';
import { timeOf } from '../lib/fmt';

const ROLES = [
  { key: 'engineer', name: '设计/工艺' }, { key: 'approver', name: '审批人' }, { key: 'sales', name: '销售' },
  { key: 'planner', name: '计划员' }, { key: 'operator', name: '操作工' }, { key: 'quality', name: '质检员' },
];
const rows = ref([]);
async function load() { rows.value = await get('/plm/members'); }
async function toggle(m, role, on) {
  const roles = on ? [...new Set([...m.roles, role])] : m.roles.filter((r) => r !== role);
  const r = await post('/plm/members/' + encodeURIComponent(m.uid), { roles });
  m.roles = r.roles;
  m.saved = '已保存';
  setTimeout(() => { m.saved = ''; }, 1500);
}
onMounted(load);
</script>

<style scoped>
td input { width: 16px; height: 16px; }
.pill.small { margin-left: 6px; }
</style>
