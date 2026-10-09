<template>
  <div class="wrap">
    <form class="box" @submit.prevent="go">
      <div class="brand"><span class="logo">渠</span><div><b>问渠数字工厂<span v-if="info?.edition === 'local'" class="ed">本地版</span></b><small>WenQuest Digital Factory</small></div></div>
      <p class="muted">一个平台，两种用途：学生在这里扮演工厂的各个岗位完成生产任务；企业在这里接单、设计、排产、加工、检验。</p>

      <div v-if="!info" class="muted">正在检查登录状态…</div>

      <!-- 线上：问渠账号（第 3 轮 D2） -->
      <template v-else-if="online && !info.account">
        <p>用问渠学习平台的账号登录。登录后会自动回到这里。</p>
        <a class="btn primary big center" :href="signInHref">用问渠账号登录</a>
        <small class="muted">还没有账号？在登录页可以注册。</small>
      </template>

      <template v-else>
        <div v-if="online" class="me">
          <span class="av">{{ info.account.fullname.slice(0, 1) }}</span>
          <div><b>{{ info.account.fullname }}</b><small>{{ info.account.teacher ? '老师' : '学生' }} · 问渠账号</small></div>
        </div>
        <div v-else class="field"><label for="n">姓名</label><input id="n" v-model="name" autocomplete="name" required placeholder="例如：王小明"></div>
        <!-- 本地版（第 30 轮 H-5）：学生选岗位；当老师要输老师密码（启动工厂时显示过，在 factory/digital/.env 的 WQ_TEACHER_PASSWORD） -->
        <div v-if="localRoles" class="field">
          <label class="check"><input id="t" v-model="asTeacher" type="checkbox"> 我是老师（可当厂长、用生产模式和教师控制台）</label>
          <input v-if="asTeacher" id="tp" v-model="teacherPassword" type="password" autocomplete="current-password" required
            placeholder="老师密码（启动工厂时显示过）" aria-label="老师密码">
        </div>
        <div class="field">
          <label>角色</label>
          <div class="roles" :class="{ four: roles.length === 4 }">
            <button v-for="r in roles" :key="r.key" type="button" :class="{ on: role === r.key }" @click="role = r.key">
              <b>{{ r.name }}</b><small>{{ r.en }}</small>
            </button>
          </div>
        </div>
        <div class="field">
          <label>模式</label>
          <div class="modes">
            <button type="button" :class="{ on: mode === 'teach' }" @click="mode = 'teach'"><b>教学模式</b><small>有任务、提示和评分，机床为仿真</small></button>
            <button type="button" :class="{ on: mode === 'prod' }" :disabled="!teacher" :title="teacher ? '' : '生产模式只对老师开放'"
              @click="mode = 'prod'"><b>生产模式</b><small>{{ teacher ? '工厂日常工作台，AI 可代办' : '只对老师开放' }}</small></button>
          </div>
        </div>
        <button class="btn primary big" :disabled="busy">进入工厂</button>
      </template>
      <div v-if="err" class="err">{{ err }}</div>
      <router-link to="/help" class="help-link">第一次用？看帮助（不用登录）→</router-link>
    </form>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, login, rolesFor } from '../lib/api';

const route = useRoute();
const router = useRouter();
const info = ref(null);
const name = ref('');
const role = ref('manager');
const mode = ref('teach');
const err = ref(null);
const busy = ref(false);

const asTeacher = ref(false);
const teacherPassword = ref('');

const online = computed(() => info.value?.auth === 'wenquest');
const localRoles = computed(() => !online.value && !!info.value?.teacher_password);   // 学校本地版
const teacher = computed(() => (online.value ? !!info.value?.account?.teacher : (!localRoles.value || asTeacher.value)));
const roles = computed(() => rolesFor({ teacher: teacher.value }));
const signInHref = computed(() => (info.value?.login_url || '/') + '?back=' + encodeURIComponent(location.href));
watch(teacher, (t) => {
  if (!t) { role.value = 'planner'; mode.value = 'teach'; } else if (localRoles.value) role.value = 'manager';
});

onMounted(async () => {
  try { info.value = await get('/login/info'); } catch (e) { err.value = e.message; info.value = { auth: 'local' }; }
});

async function go() {
  busy.value = true; err.value = null;
  try {
    await login(online.value ? null : name.value.trim(), role.value, mode.value,
      localRoles.value && asTeacher.value ? { teacher_password: teacherPassword.value } : undefined);
    router.push(route.query.next || '/');
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}
</script>

<style scoped>
.wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px; background: var(--rail); }
.box { width: min(560px, 100%); background: #fff; border-radius: 14px; padding: 28px; display: flex; flex-direction: column; gap: 16px; }
.brand { display: flex; align-items: center; gap: 12px; }
.brand b { font-size: 20px; display: block; }
.brand small { color: var(--muted); }
.logo { width: 44px; height: 44px; border-radius: 10px; background: var(--brand); display: flex; align-items: center;
  justify-content: center; font-weight: 700; font-size: 22px; }
.center { display: flex; align-items: center; justify-content: center; text-decoration: none; }
.center:hover { text-decoration: none; }
.me { display: flex; align-items: center; gap: 12px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; }
.me b { display: block; } .me small { color: var(--muted); font-size: 12px; }
.av { width: 36px; height: 36px; border-radius: 50%; background: var(--accent); color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 600; }
.roles { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; }
.roles.four { grid-template-columns: repeat(4, 1fr); }
.modes { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.roles button, .modes button { border: 1px solid var(--line); background: var(--surface-2); border-radius: 8px; padding: 10px;
  cursor: pointer; display: flex; flex-direction: column; gap: 3px; text-align: left; }
.roles button small, .modes button small { font-size: 11px; color: var(--muted); }
.roles button.on, .modes button.on { border-color: var(--accent); background: var(--accent-bg); }
.ed { font-size: 12px; font-weight: 600; margin-left: 8px; padding: 2px 8px; border-radius: 10px; background: var(--accent-bg); color: var(--accent); vertical-align: middle; }
.check { display: flex; align-items: center; gap: 8px; font-weight: normal; cursor: pointer; }
.check input { width: auto; }
.modes button:disabled { cursor: not-allowed; opacity: .55; }
@media (max-width: 560px) { .roles, .roles.four { grid-template-columns: repeat(2, 1fr); } .modes { grid-template-columns: 1fr; } }
.help-link { display: block; margin-top: 14px; text-align: center; font-size: 13px; color: var(--muted, #6b7785); }
</style>
