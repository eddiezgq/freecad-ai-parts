<template>
  <!-- 帮助（第 30 轮 H-3）：登录前单独显示，登录后在工作台框架里 -->
  <router-view v-if="route.meta.public && !(route.meta.shell && session.token)" />
  <div v-else class="shell">
    <nav class="rail" :aria-label="t('工作区')">
      <router-link to="/" class="brand">
        <span class="logo">渠</span><!-- i18n-ok 标志字 -->
        <span class="brand-text"><b>{{ t('问渠数字工厂') }}</b><small>{{ isEn() ? '' : 'WenQuest Digital Factory' }}{{ cfg.edition === 'local' ? ' · ' + t('本地版') : cfg.edition === 'enterprise' ? ' · ' + t('企业版') : '' }}</small></span>
      </router-link>
      <!-- 第 19 轮 J-8：按工厂的价值链分组（总览 / 从订单到回款 / 保障 / 设计与工艺 / 教学 / 资源） -->
      <div v-for="g in navGroups" :key="g.title" class="group">
        <span class="group-title">{{ t(g.title) }}</span>
        <template v-for="n in g.items" :key="n.to || n.label">
          <a v-if="n.ai" href="#" class="nav" @click.prevent="ai.open = true">{{ t(n.label) }}</a>
          <router-link v-else :to="n.to" class="nav" :class="{ mine: n.role === session.user?.role }" :data-help="n.help">
            {{ t(n.label) }}<span v-if="n.role === session.user?.role" class="me">{{ t('我的') }}</span>
          </router-link>
        </template>
      </div>
      <div class="group">
        <span class="group-title">{{ t('专业软件') }}</span>
        <a v-for="a in apps" :key="a.name" :href="a.href" :target="a.ext ? '_blank' : null" class="app"
          @click="a.route && ($event.preventDefault(), openApp(a))">
          <span>{{ t(a.name) }}</span><span class="muted-r">{{ t(a.role) }}</span>
        </a>
      </div>
      <router-link to="/bus" class="busbox">
        <span class="group-title">{{ t('统一数据总线') }}</span>
        <span class="bus-state"><i :style="{ background: bus.connected ? 'var(--good)' : 'var(--bad)' }"></i>
          {{ bus.connected ? t('已连接') : t('未连接') }} · {{ t('{n} 个设备', { n: Object.keys(bus.machines).length + Object.keys(bus.agvs).length }) }}</span>
        <span class="mono small">wq/gearbox/# · {{ t('{n} 条/分', { n: bus.rate }) }}</span>
      </router-link>
    </nav>
    <main class="main">
      <header class="top">
        <div class="title">
          <b>{{ plantName }}{{ cfg.factory_name ? t('（{n}）', { n: cfg.factory_name }) : '' }} · {{ pageName }}</b>
          <small>{{ clock }} · {{ t('第 1 班（{s}）', { s: cfg.plant?.shift || '08:00–17:00' }) }} · {{ t('数据实时刷新') }}</small>
        </div>
        <div class="modes" role="group" :aria-label="t('模式')">
          <button type="button" :class="{ on: session.user?.mode === 'teach' }" @click="setMode('teach')">{{ t('教学模式') }}</button>
          <button type="button" :class="{ on: session.user?.mode === 'prod' }" :disabled="!canProd(session.user)"
            :title="canProd(session.user) ? '' : t('生产模式只对老师和企业成员开放')" @click="setMode('prod')">{{ t('生产模式') }}</button>
        </div>
        <label class="role">{{ t('角色') }}
          <select :value="session.user?.role" @change="setRole($event.target.value)">
            <option v-for="r in rolesFor(session.user)" :key="r.key" :value="r.key">{{ isEn() ? r.en : r.name }}</option>
          </select>
        </label>
        <div class="langs" role="group" aria-label="Language / 语言"><!-- i18n-ok 语言切换本身两种文字都写 -->
          <button type="button" :class="{ on: i18n.lang === 'zh' }" lang="zh-CN" @click="setLang('zh')">中文</button><!-- i18n-ok -->
          <button type="button" :class="{ on: i18n.lang === 'en' }" lang="en" @click="setLang('en')">EN</button>
        </div>
        <router-link :to="helpTo" class="helpbtn" :title="t('这一页怎么用')">{{ t('帮助') }}</router-link>
        <NotifyBell v-if="session.user" />
        <button class="avatar" :title="t('{n}（点击退出）', { n: session.user?.name })" @click="doLogout">{{ (session.user?.name || '?').slice(0, 1) }}</button>
      </header>
      <router-view :key="session.user?.mode + session.user?.role + i18n.lang" />
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
import { bi, i18n, isEn, loc, setLang, t, tk } from './lib/i18n';

const route = useRoute();
const router = useRouter();
const hasRoute = (p) => router.getRoutes().some((r) => r.path === p);
const teachOnly = (u) => u?.mode === 'teach';
const cfg = ref({});
const NAV = [
  { title: tk('总览'), items: [
    { to: '/', label: tk('首页 · 运营总览') },
    { to: '/ont', label: tk('厂情中枢') },                // 第 17 轮 B 期：有了指挥台，对所有角色开放
    { to: '/tasks', label: tk('我的任务') },
    { ai: true, label: tk('AI 工厂助手') },
  ] },
  { title: tk('从订单到回款'), items: [
    { to: '/service', label: tk('客户与服务'), role: 'service' },          // 第 18 轮 E1
    { to: '/rservice', label: tk('客户与服务'), role: 'service', only: () => cfg.value.plant?.id === 'wenquest-robot' },   // 第 64 轮：现场的机器人
    { to: '/work/planner', label: tk('订单与计划'), role: 'planner' },
    { to: '/eto', label: tk('按单设计（ETO）'), role: 'sales' },          // 第 139 轮：估算、报价（后续段：设计、物料、计划、质量、开票）
    { to: '/supply', label: tk('采购与来料'), role: 'planner' },          // 第 18 轮 E5
    { to: '/work/operator', label: tk('车间执行'), role: 'operator' },
    { to: '/work/quality', label: tk('质量'), role: 'quality' },
    { to: '/calib', label: tk('整机标定'), role: 'quality', only: () => cfg.value.plant?.id === 'wenquest-robot' },   // 第 55 轮：机器人厂
    { to: '/lab28', label: tk('负载跑合'), role: 'quality', only: () => cfg.value.plant?.id === 'wenquest-robot' },   // 第 58 轮：机器人厂
    { to: '/fct', label: tk('功能测试台'), role: 'quality', only: () => cfg.value.plant?.id === 'wenquest-pcb' },   // 第 88 轮：电路板厂
    { to: '/wafer-map', label: tk('晶圆图'), role: 'quality', only: () => cfg.value.plant?.id === 'wenquest-chip' },   // 第 103 轮：芯片封测厂
    { to: '/enc-curve', label: tk('编码器误差曲线'), role: 'quality', only: () => cfg.value.plant?.id === 'wenquest-sensor' },   // 第 125 轮：传感器厂
    { to: '/motor-wave', label: tk('电机终检波形'), role: 'quality', only: () => cfg.value.plant?.id === 'wenquest-motor' },   // 第 131 轮：电机厂
    { to: '/finance', label: tk('经营与财务'), role: 'manager' },         // 第 18 轮 E7；第 19 轮并入原“经营与成本”
    { to: '/cost', label: tk('生产成本'), role: 'manager', only: () => !demoPlant.value },   // 第 30 轮：企业工厂没有“经营与财务”，厂长看这里
  ] },
  { title: tk('保障'), items: [
    { to: '/maint', label: tk('设备维护'), role: 'maintenance' },         // 第 18 轮 E3
    { to: '/people', label: tk('人员'), role: 'lead' },                   // 第 18 轮 E4
    { to: '/ehs', label: tk('安全环保'), role: 'safety' },                // 第 18 轮 E2
    { to: '/energy', label: tk('能源与环境'), role: 'manager' },          // 第 18 轮 E6
  ] },
  { title: tk('设计与工艺'), items: [
    { to: '/work/engineer', label: tk('设计与工艺'), role: 'engineer' },
    { to: '/process', label: tk('工艺规程与 AI 评审') },
    { to: '/design', label: tk('设计发布与审批') },
    { to: '/cad', label: tk('CAD 方案'), only: () => hasRoute('/cad') },        // 企业页面：只在 freecad-ai-parts 有（main.js）
    { to: '/fap', label: tk('选型零件库'), only: () => hasRoute('/fap') },
    { to: '/configurator', label: tk('参数配置器'), role: 'sales' },
    { to: '/3d', label: tk('3D 车间') },
  ] },
  { title: tk('教学'), only: teachOnly, items: [
    { to: '/director', label: tk('情景导演'), only: (u) => u?.teacher },   // 第 19 轮：两周情景（老师）
    { to: '/labs', label: tk('实验与任务') },                              // 第 19 轮：实验 7、15–23 一个入口
  ] },
  { title: tk('资源'), items: [
    { to: '/library', label: tk('零件与机器人库') },
    { to: '/members', label: tk('企业成员'), only: (u) => u?.teacher !== false && !u?.acct },
    { to: '/accounts', label: tk('账号与角色'), only: (u) => !!u?.acct && !!u?.teacher && hasRoute('/accounts') },   // 企业账号（freecad-ai-parts）
    { to: '/help', label: tk('帮助'), help: 'nav-help' },
  ] },
];
// 第 30 轮 H-2：工厂清单。企业工厂（不是演示工厂）里，E1–E7、实验与任务、情景导演、虚拟 PLC 不显示——
// 哪些入口不显示由枢纽在 /api/config 的 plant.hidden 里给出；演示工厂为空，导航与以前完全一样
const hidden = computed(() => new Set(cfg.value.plant?.hidden || []));
const shown = (to) => !to || !hidden.value.has(to.split('?')[0]);
const plantName = computed(() => (isEn() ? cfg.value.plant?.name_en || bi(cfg.value.plant?.name) || 'WenQuest Gearbox' : cfg.value.plant?.name || '问渠减速器厂'));   // i18n-ok
const demoPlant = computed(() => cfg.value.plant?.demo !== false);
const navGroups = computed(() => NAV.filter((g) => !g.only || g.only(session.user))
  .map((g) => ({ ...g, items: g.items.filter((n) => (!n.only || n.only(session.user)) && shown(n.to)) })).filter((g) => g.items.length));
// 第 19 轮 J-10：右上角“帮助”打开这一页对应的帮助；第 30 轮改指网页帮助的章节（对照表在 help/pages.js）
const helpTo = computed(() => helpLink(route.path, demoPlant.value));
const apps = computed(() => [
  { name: 'ERPNext', role: 'ERP / MRP', href: cfg.value.erpnext_url || '#', ext: true },
  { name: tk('设计台'), role: 'CAD', href: '/work/engineer', route: '/work/engineer' },
  { name: tk('仿真与分析'), role: 'CAE', href: '/cae', route: '/cae' },
  { name: tk('流体分析'), role: 'CFD', href: '/cfd', route: '/cfd' },
  { name: tk('运动与动力'), role: 'MBD', href: '/mbd', route: '/mbd' },
  { name: tk('电路分析'), role: 'SPICE', href: '/circuit', route: '/circuit' },
  { name: tk('虚拟仪器'), role: 'DAQ', href: '/instruments', route: '/instruments' },
  { name: tk('电路板设计'), role: 'EDA', href: '/pcb-design', route: '/pcb-design' },
  { name: tk('芯片设计'), role: 'EDA', href: '/chip-design', route: '/chip-design' },
  { name: tk('数控编程'), role: 'CAM', href: '/cam', route: '/cam' },
  { name: tk('设计优化'), role: 'OPT', href: '/opt', route: '/opt' },
  { name: tk('数字孪生'), role: 'TWIN', href: '/twin', route: '/twin' },
  { name: tk('虚拟 PLC'), role: 'PLC', href: '/plc', route: '/plc' },
  { name: tk('车间终端'), role: 'MES', href: '/work/operator', route: '/work/operator' },
  { name: 'Node-RED', role: tk('数据流'), href: cfg.value.nodered_url || '#', ext: true },
].filter((a) => (a.name !== 'Node-RED' || cfg.value.nodered_url) && shown(a.route)));   // 线上 Node-RED 不对外（第 3 轮 D8）
const pageName = computed(() => t(pageTitle(route.path)));
const clock = ref('');
let timer;
function tick() {
  const d = new Date();
  clock.value = d.toLocaleString(loc(), { year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short',
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
function doLogout() { if (confirm(t('退出登录？'))) { logout(); router.push('/login'); } }

onMounted(async () => {
  tick();
  timer = setInterval(tick, 20000);
  if (session.token) start();
});
watch(() => session.token, (t) => { if (t) start(); });
async function start() {
  try {
    cfg.value = await loadConfig();
    if (cfg.value.plant?.demo === false) document.title = plantName.value + ' · ' + t('问渠数字工厂');   // 演示工厂标题不变
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
.langs { display: flex; flex-shrink: 0; gap: 2px; background: var(--bg); border-radius: 8px; padding: 3px; }
.langs button { height: 26px; padding: 0 8px; white-space: nowrap; border: 0; border-radius: 6px; background: transparent; color: #3D4852; cursor: pointer; font-size: 12px; }
.langs button.on { background: #fff; color: var(--ink, #17212B); font-weight: 600; box-shadow: 0 1px 2px rgba(0,0,0,.08); }
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
