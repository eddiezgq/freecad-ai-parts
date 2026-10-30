<template>
  <!-- 帮助（第 30 轮 H-3）：登录前单独显示，登录后在工作台框架里 -->
  <router-view v-if="route.meta.public && !(route.meta.shell && session.token)" />
  <div v-else class="shell">
    <nav class="rail" aria-label="工作区">
      <router-link to="/" class="brand">
        <span class="logo">渠</span>
        <span class="brand-text"><b>问渠数字工厂</b><small>WenQuest Digital Factory{{ cfg.edition === 'local' ? ' · 本地版' : cfg.edition === 'enterprise' ? ' · 企业版' : '' }}</small></span>
      </router-link>
      <!-- 第 19 轮 J-8：按工厂的价值链分组（总览 / 从订单到回款 / 保障 / 设计与工艺 / 教学 / 资源） -->
      <div v-for="g in navGroups" :key="g.title" class="group">
        <span class="group-title">{{ g.title }}</span>
        <template v-for="n in g.items" :key="n.to || n.label">
          <a v-if="n.ai" href="#" class="nav" @click.prevent="ai.open = true">{{ n.label }}</a>
          <router-link v-else :to="n.to" class="nav" :class="{ mine: n.role === session.user?.role }" :data-help="n.help">
            {{ n.label }}<span v-if="n.role === session.user?.role" class="me">我的</span>
          </router-link>
        </template>
      </div>
      <div class="group">
        <span class="group-title">专业软件</span>
        <a v-for="a in apps" :key="a.name" :href="a.href" :target="a.ext ? '_blank' : null" class="app"
          @click="a.route && ($event.preventDefault(), openApp(a))">
          <span>{{ a.name }}</span><span class="muted-r">{{ a.role }}</span>
        </a>
      </div>
      <router-link to="/bus" class="busbox">
        <span class="group-title">统一数据总线</span>
        <span class="bus-state"><i :style="{ background: bus.connected ? 'var(--good)' : 'var(--bad)' }"></i>
          {{ bus.connected ? '已连接' : '未连接' }} · {{ Object.keys(bus.machines).length + Object.keys(bus.agvs).length }} 个设备</span>
        <span class="mono small">wq/gearbox/# · {{ bus.rate }} 条/分</span>
      </router-link>
    </nav>
    <main class="main">
      <header class="top">
        <div class="title">
          <b>{{ plantName }}{{ cfg.factory_name ? "（" + cfg.factory_name + "）" : "" }} · {{ pageName }}</b>
          <small>{{ clock }} · 第 1 班（{{ cfg.plant?.shift || '08:00–17:00' }}）· 数据实时刷新</small>
        </div>
        <div class="modes" role="group" aria-label="模式">
          <button type="button" :class="{ on: session.user?.mode === 'teach' }" @click="setMode('teach')">教学模式</button>
          <button type="button" :class="{ on: session.user?.mode === 'prod' }" :disabled="!canProd(session.user)"
            :title="canProd(session.user) ? '' : '生产模式只对老师和企业成员开放'" @click="setMode('prod')">生产模式</button>
        </div>
        <label class="role">角色
          <select :value="session.user?.role" @change="setRole($event.target.value)">
            <option v-for="r in rolesFor(session.user)" :key="r.key" :value="r.key">{{ r.name }}</option>
          </select>
        </label>
        <router-link :to="helpTo" class="helpbtn" title="这一页怎么用">帮助</router-link>
        <NotifyBell v-if="session.user" />
        <button class="avatar" :title="session.user?.name + '（点击退出）'" @click="doLogout">{{ (session.user?.name || '?').slice(0, 1) }}</button>
      </header>
      <router-view :key="session.user?.mode + session.user?.role" />
    </main>
    <AiDrawer />
  </div>
  <TourOverlay />
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { session, rolesFor, canProd, switchTo, logout, loadConfig } from './lib/api';
import { bus, connectBus, setBusMode } from './lib/bus';
import AiDrawer from './components/AiDrawer.vue';
import TourOverlay from './components/TourOverlay.vue';
import { helpLink, pageTitle } from './help/pages';
import NotifyBell from './components/NotifyBell.vue';
import { ai } from './lib/ai';

const route = useRoute();
const router = useRouter();
const hasRoute = (p) => router.getRoutes().some((r) => r.path === p);
const teachOnly = (u) => u?.mode === 'teach';
const cfg = ref({});
const NAV = [
  { title: '总览', items: [
    { to: '/', label: '首页 · 运营总览' },
    { to: '/ont', label: '厂情中枢' },                // 第 17 轮 B 期：有了指挥台，对所有角色开放
    { to: '/tasks', label: '我的任务' },
    { ai: true, label: 'AI 工厂助手' },
  ] },
  { title: '从订单到回款', items: [
    { to: '/service', label: '客户与服务', role: 'service' },          // 第 18 轮 E1
    { to: '/work/planner', label: '订单与计划', role: 'planner' },
    { to: '/supply', label: '采购与来料', role: 'planner' },          // 第 18 轮 E5
    { to: '/work/operator', label: '车间执行', role: 'operator' },
    { to: '/work/quality', label: '质量', role: 'quality' },
    { to: '/calib', label: '整机标定', role: 'quality', only: () => cfg.value.plant?.id === 'wenquest-robot' },   // 第 55 轮：机器人厂
    { to: '/finance', label: '经营与财务', role: 'manager' },         // 第 18 轮 E7；第 19 轮并入原“经营与成本”
    { to: '/cost', label: '生产成本', role: 'manager', only: () => !demoPlant.value },   // 第 30 轮：企业工厂没有“经营与财务”，厂长看这里
  ] },
  { title: '保障', items: [
    { to: '/maint', label: '设备维护', role: 'maintenance' },         // 第 18 轮 E3
    { to: '/people', label: '人员', role: 'lead' },                   // 第 18 轮 E4
    { to: '/ehs', label: '安全环保', role: 'safety' },                // 第 18 轮 E2
    { to: '/energy', label: '能源与环境', role: 'manager' },          // 第 18 轮 E6
  ] },
  { title: '设计与工艺', items: [
    { to: '/work/engineer', label: '设计与工艺', role: 'engineer' },
    { to: '/process', label: '工艺规程与 AI 评审' },
    { to: '/design', label: '设计发布与审批' },
    { to: '/cad', label: 'CAD 方案', only: () => hasRoute('/cad') },        // 企业页面：只在 freecad-ai-parts 有（main.js）
    { to: '/fap', label: '选型零件库', only: () => hasRoute('/fap') },
    { to: '/configurator', label: '参数配置器', role: 'sales' },
    { to: '/3d', label: '3D 车间' },
  ] },
  { title: '教学', only: teachOnly, items: [
    { to: '/director', label: '情景导演', only: (u) => u?.teacher },   // 第 19 轮：两周情景（老师）
    { to: '/labs', label: '实验与任务' },                              // 第 19 轮：实验 7、15–23 一个入口
  ] },
  { title: '资源', items: [
    { to: '/library', label: '零件与机器人库' },
    { to: '/members', label: '企业成员', only: (u) => u?.teacher !== false && !u?.acct },
    { to: '/accounts', label: '账号与角色', only: (u) => !!u?.acct && !!u?.teacher && hasRoute('/accounts') },   // 企业账号（freecad-ai-parts）
    { to: '/help', label: '帮助', help: 'nav-help' },
  ] },
];
// 第 30 轮 H-2：工厂清单。企业工厂（不是演示工厂）里，E1–E7、实验与任务、情景导演、虚拟 PLC 不显示——
// 哪些入口不显示由枢纽在 /api/config 的 plant.hidden 里给出；演示工厂为空，导航与以前完全一样
const hidden = computed(() => new Set(cfg.value.plant?.hidden || []));
const shown = (to) => !to || !hidden.value.has(to.split('?')[0]);
const plantName = computed(() => cfg.value.plant?.name || '问渠减速器厂');
const demoPlant = computed(() => cfg.value.plant?.demo !== false);
const navGroups = computed(() => NAV.filter((g) => !g.only || g.only(session.user))
  .map((g) => ({ ...g, items: g.items.filter((n) => (!n.only || n.only(session.user)) && shown(n.to)) })).filter((g) => g.items.length));
// 第 19 轮 J-10：右上角“帮助”打开这一页对应的帮助；第 30 轮改指网页帮助的章节（对照表在 help/pages.js）
const helpTo = computed(() => helpLink(route.path, demoPlant.value));
const apps = computed(() => [
  { name: 'ERPNext', role: 'ERP / MRP', href: cfg.value.erpnext_url || '#', ext: true },
  { name: '设计台', role: 'CAD', href: '/work/engineer', route: '/work/engineer' },
  { name: '仿真与分析', role: 'CAE', href: '/cae', route: '/cae' },
  { name: '流体分析', role: 'CFD', href: '/cfd', route: '/cfd' },
  { name: '运动与动力', role: 'MBD', href: '/mbd', route: '/mbd' },
  { name: '数控编程', role: 'CAM', href: '/cam', route: '/cam' },
  { name: '设计优化', role: 'OPT', href: '/opt', route: '/opt' },
  { name: '数字孪生', role: 'TWIN', href: '/twin', route: '/twin' },
  { name: '虚拟 PLC', role: 'PLC', href: '/plc', route: '/plc' },
  { name: '车间终端', role: 'MES', href: '/work/operator', route: '/work/operator' },
  { name: 'Node-RED', role: '数据流', href: cfg.value.nodered_url || '#', ext: true },
].filter((a) => (a.name !== 'Node-RED' || cfg.value.nodered_url) && shown(a.route)));   // 线上 Node-RED 不对外（第 3 轮 D8）
const pageName = computed(() => pageTitle(route.path));
const clock = ref('');
let timer;
function tick() {
  const d = new Date();
  clock.value = d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short',
    hour: '2-digit', minute: '2-digit', hour12: false });
}
async function setMode(m) {
  if (session.user.mode === m || (m === 'prod' && !canProd(session.user))) return;
  const ok = rolesFor(session.user, m).map((r) => r.key);           // 换模式时角色不可用就换成可用的第一个
  await switchTo({ mode: m, ...(ok.includes(session.user.role) ? {} : { role: ok[0] }) });
  setBusMode(m);
}
// 第 6 轮 W6：已经在这一页时也给出反应（回到页首），不再像“点了没反应”
function openApp(a) {
  if (route.path === a.route) window.scrollTo({ top: 0, behavior: 'smooth' });
  else router.push(a.route);
}
async function setRole(r) { await switchTo({ role: r }); }
function doLogout() { if (confirm('退出登录？')) { logout(); router.push('/login'); } }

onMounted(async () => {
  tick();
  timer = setInterval(tick, 20000);
  if (session.token) start();
});
watch(() => session.token, (t) => { if (t) start(); });
async function start() {
  try {
    cfg.value = await loadConfig();
    if (cfg.value.plant?.demo === false) document.title = plantName.value + ' · 问渠数字工厂';   // 演示工厂标题不变
    connectBus(cfg.value.mqtt_ws.replace('localhost', location.hostname), session.user.mode);
  } catch (e) { /* 首页会显示错误 */ }
}
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.shell { display: flex; min-height: 100vh; }
.rail { width: 208px; flex-shrink: 0; background: var(--rail); color: #E7ECEF; display: flex; flex-direction: column;
  padding: 20px 14px; gap: 22px; position: sticky; top: 0; height: 100vh; overflow-y: auto; }
.brand { display: flex; align-items: center; gap: 10px; padding: 0 6px; color: inherit; text-decoration: none; }
.logo { width: 34px; height: 34px; border-radius: 8px; background: var(--brand); color: var(--ink); display: flex;
  align-items: center; justify-content: center; font-weight: 700; font-size: 18px; }
.brand-text { display: flex; flex-direction: column; line-height: 1.25; }
.brand-text b { font-size: 15px; font-weight: 600; }
.brand-text small { font-size: 11px; color: #9AA8B4; }
.group { display: flex; flex-direction: column; gap: 2px; }
.group-title { font-size: 11px; letter-spacing: .08em; color: var(--rail-muted); padding: 0 10px 6px; }
.nav { display: flex; justify-content: space-between; align-items: center; padding: 9px 10px; border-radius: 6px;
  color: var(--rail-ink); text-decoration: none; font-size: 14px; }
.nav:hover { background: #22303C; text-decoration: none; }
.nav.router-link-exact-active { background: #2E3E4C; color: #fff; font-weight: 500; }
.me { font-size: 10px; background: var(--brand); color: var(--ink); border-radius: 8px; padding: 1px 6px; }
.app { display: flex; justify-content: space-between; align-items: center; padding: 8px 10px; border-radius: 6px;
  color: var(--rail-ink); text-decoration: none; font-size: 13px; }
.app:hover { background: #22303C; text-decoration: none; }
.muted-r { font-size: 11px; color: var(--rail-muted); }
.busbox { margin-top: auto; padding: 12px 10px; border-radius: 8px; background: var(--rail-2); display: flex;
  flex-direction: column; gap: 6px; color: #E7ECEF; text-decoration: none; }
.busbox .group-title { padding: 0; }
.bus-state { font-size: 13px; display: flex; align-items: center; gap: 8px; }
.bus-state i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.busbox .small { color: #9AA8B4; font-size: 11px; }
.main { flex-grow: 1; min-width: 0; display: flex; flex-direction: column; }
.top { height: 64px; flex-shrink: 0; background: #fff; border-bottom: 1px solid var(--line); display: flex;
  align-items: center; padding: 0 28px; gap: 20px; position: sticky; top: 0; z-index: 10; }
.title { display: flex; flex-direction: column; line-height: 1.3; }
.helpbtn { height: 30px; padding: 0 10px; border: 1px solid var(--line); border-radius: 6px; display: inline-flex; align-items: center; font-size: 13px; color: inherit; text-decoration: none; }
.title b { font-size: 17px; font-weight: 600; }
.title small { font-size: 12px; color: var(--muted); }
.modes { margin-left: auto; display: flex; gap: 4px; background: var(--bg); border-radius: 8px; padding: 3px; }
.modes button { height: 30px; padding: 0 14px; border: 0; border-radius: 6px; background: transparent; color: #3D4852; cursor: pointer; }
.modes button.on { background: var(--accent); color: #fff; font-weight: 500; }
.modes button:disabled { opacity: .45; cursor: not-allowed; }
.role { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); }
.role select { height: 34px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; background: #fff; }
.avatar { width: 34px; height: 34px; border-radius: 50%; background: var(--accent); color: #fff; border: 0;
  font-weight: 600; cursor: pointer; }
@media (max-width: 900px) {
  .shell { flex-direction: column; }
  .rail { width: 100%; height: auto; position: static; flex-direction: row; flex-wrap: wrap; gap: 8px; padding: 10px; }
  .group { flex-direction: row; flex-wrap: wrap; }
  .group-title, .busbox { display: none; }
  .top { padding: 0 16px; gap: 10px; height: auto; flex-wrap: wrap; padding-top: 8px; padding-bottom: 8px; }
  .title small { display: none; }
}
</style>
