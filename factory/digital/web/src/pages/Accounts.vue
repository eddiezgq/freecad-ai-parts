<!-- 账号与角色（企业版，本仓库 ADR-0063）：管理员开账号、分配角色、重置密码、停用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>账号与角色</h1>
      <span class="muted">企业版用户名 + 密码登录；管理员有全部权限，普通账号只能用分给他的角色。停用或重置密码后，对方的登录立即失效</span></div>
    <div v-if="err" class="err">{{ err }}</div>

    <section class="card" data-help="acct-new">
      <h2>新开账号</h2>
      <form class="new" @submit.prevent="create">
        <input v-model="f.username" placeholder="用户名（字母数字）" required>
        <input v-model="f.name" placeholder="姓名" required>
        <input v-model="f.password" type="password" placeholder="初始密码（至少 10 位，字母加数字）" required autocomplete="new-password">
        <label class="small"><input v-model="f.admin" type="checkbox"> 管理员</label>
        <span v-if="!f.admin" class="roles small">
          <label v-for="r in ROLES" :key="r.key"><input v-model="f.roles" type="checkbox" :value="r.key"> {{ r.name }}</label>
        </span>
        <button class="btn primary sm" :disabled="busy">开账号</button>
      </form>
    </section>

    <section class="card" data-help="acct-table">
      <table class="t">
        <thead><tr><th>用户名</th><th>姓名</th><th>最近登录</th><th>管理员</th><th v-for="r in ROLES" :key="r.key">{{ r.name }}</th><th>在用</th><th></th></tr></thead>
        <tbody><tr v-for="a in rows" :key="a.username" :class="{ off: !a.active }">
          <td class="mono">{{ a.username }}</td><td>{{ a.name }}</td><td class="small">{{ timeOf(a.last_login) }}</td>
          <td><input type="checkbox" :checked="a.admin" :aria-label="a.username + ' 管理员'" @change="save(a, { admin: $event.target.checked })"></td>
          <td v-for="r in ROLES" :key="r.key"><input type="checkbox" :disabled="a.admin" :checked="a.admin || a.roles.includes(r.key)"
            :aria-label="a.username + ' ' + r.name" @change="toggle(a, r.key, $event.target.checked)"></td>
          <td><input type="checkbox" :checked="a.active" :aria-label="a.username + ' 在用'" @change="save(a, { active: $event.target.checked })"></td>
          <td class="small"><button class="btn sm" @click="reset(a)">重置密码</button> {{ a.saved || '' }}</td>
        </tr></tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { get, post } from '../lib/api';
import { timeOf } from '../lib/fmt';

const ROLES = [
  { key: 'manager', name: '厂长' }, { key: 'planner', name: '计划员' }, { key: 'engineer', name: '工艺员' },
  { key: 'operator', name: '操作工' }, { key: 'quality', name: '质检员' }, { key: 'approver', name: '审批人' }, { key: 'sales', name: '销售' },
];
const rows = ref([]);
const err = ref('');
const busy = ref(false);
const f = reactive({ username: '', name: '', password: '', admin: false, roles: [] });

async function load() { try { rows.value = (await get('/accounts')).accounts; } catch (e) { err.value = e.message; } }
async function create() {
  busy.value = true; err.value = '';
  try {
    await post('/accounts', { ...f });
    Object.assign(f, { username: '', name: '', password: '', admin: false, roles: [] });
    await load();
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
async function save(a, patch) {
  err.value = '';
  try {
    Object.assign(a, await post('/accounts/' + encodeURIComponent(a.username), patch));
    a.saved = '已保存'; setTimeout(() => { a.saved = ''; }, 1500);
  } catch (e) { err.value = e.message; await load(); }
}
function toggle(a, role, on) { save(a, { roles: on ? [...new Set([...a.roles, role])] : a.roles.filter((r) => r !== role) }); }
function reset(a) {
  const pw = prompt(`给 ${a.username} 设新密码（至少 10 位，字母加数字）`);
  if (pw) save(a, { password: pw });
}
onMounted(load);
</script>

<style scoped>
.new { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.new input:not([type=checkbox]) { min-width: 160px; }
.roles { display: inline-flex; flex-wrap: wrap; gap: 8px; }
td input { width: 16px; height: 16px; }
tr.off td { color: var(--muted); }
</style>
