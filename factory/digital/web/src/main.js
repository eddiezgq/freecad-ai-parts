import { createApp } from 'vue';
import { createRouter, createWebHistory } from 'vue-router';
import App from './App.vue';
import './styles.css';
import { session } from './lib/api';

const routes = [
  { path: '/login', component: () => import('./pages/Login.vue'), meta: { public: true } },
  { path: '/embed/workshop', component: () => import('./pages/EmbedWorkshop.vue'), meta: { public: true } },
  { path: '/', component: () => import('./pages/Home.vue') },
  { path: '/work/planner', component: () => import('./pages/Planner.vue') },
  { path: '/work/engineer', component: () => import('./pages/Engineer.vue') },
  { path: '/work/operator', component: () => import('./pages/Operator.vue') },
  { path: '/work/quality', component: () => import('./pages/Quality.vue') },
  { path: '/quality/8d', component: () => import('./pages/Q8D.vue') },
  { path: '/quality/8d/:id', component: () => import('./pages/Q8D.vue') },
  { path: '/work/manager', redirect: { path: '/finance', query: { tab: 'production' } } },     // 第 19 轮：“经营与成本”并进“经营与财务 → 生产与成本”
  { path: '/3d', component: () => import('./pages/Factory3D.vue') },
  { path: '/teach', component: () => import('./pages/Teach.vue') },
  { path: '/bus', component: () => import('./pages/BusView.vue') },
  { path: '/library', component: () => import('./pages/Library.vue') },
  { path: '/design', component: () => import('./pages/DesignRelease.vue') },
  { path: '/process', component: () => import('./pages/ProcessPlan.vue') },
  { path: '/process/:sid', component: () => import('./pages/ProcessPlan.vue') },
  { path: '/design/:id', component: () => import('./pages/DesignReview.vue') },
  { path: '/members', component: () => import('./pages/Members.vue') },
  { path: '/configurator', component: () => import('./pages/Configurator.vue') },
  { path: '/cae', component: () => import('./pages/Cae.vue') },
  { path: '/mbd', component: () => import('./pages/Mbd.vue') },
  { path: '/cam', component: () => import('./pages/Cam.vue') },
  { path: '/opt', component: () => import('./pages/Opt.vue') },
  { path: '/cfd', component: () => import('./pages/Cfd.vue') },
  { path: '/twin', component: () => import('./pages/Twin.vue') },
  { path: '/plc', component: () => import('./pages/VirtualPlc.vue') },
  { path: '/lab15', component: () => import('./pages/Lab15.vue') },
  { path: '/lab16', component: () => import('./pages/Lab16.vue') },
  { path: '/lab17', component: () => import('./pages/Lab17.vue') },
  { path: '/ehs', component: () => import('./pages/Ehs.vue') },
  { path: '/maint', component: () => import('./pages/Maint.vue') },
  { path: '/lab18', component: () => import('./pages/Lab18.vue') },
  { path: '/people', component: () => import('./pages/People.vue') },
  { path: '/lab19', component: () => import('./pages/Lab19.vue') },
  { path: '/supply', component: () => import('./pages/Supply.vue') },
  { path: '/calib', component: () => import('./pages/Calib.vue') },          // 第 55 轮：整机标定（机器人厂）
  { path: '/lab26', component: () => import('./pages/Lab26.vue') },
  { path: '/lab27', component: () => import('./pages/Lab27.vue') },        // 第 57 轮
  { path: '/lab28', component: () => import('./pages/Lab28.vue') },        // 第 58 轮：负载跑合台
  { path: '/lab20', component: () => import('./pages/Lab20.vue') },
  { path: '/energy', component: () => import('./pages/Energy.vue') },
  { path: '/lab21', component: () => import('./pages/Lab21.vue') },
  { path: '/finance', component: () => import('./pages/Finance.vue') },
  { path: '/lab22', component: () => import('./pages/Lab22.vue') },
  { path: '/lab23', component: () => import('./pages/Lab23.vue') },
  { path: '/lab24', component: () => import('./pages/Lab24.vue') },              // 第 47 轮：机器人厂的实验
  { path: '/lab25', component: () => import('./pages/Lab25.vue') },
  { path: '/labs', component: () => import('./pages/Labs.vue') },              // 第 19 轮：实验与任务（一个入口）
  { path: '/director', component: () => import('./pages/Director.vue') },      // 第 19 轮：情景导演
  // 帮助（第 30 轮 H-3，搬自 freecad-ai-parts ADR-0065）：教学版、企业版、资料；登录前也能看，登录后在工作台框架里
  { path: '/help/:ed?/:ch?', component: () => import('./pages/Help.vue'), meta: { public: true, shell: true } },
  { path: '/cost', component: () => import('./pages/Cost.vue') },              // 第 30 轮：企业工厂的“生产成本”
  { path: '/service', component: () => import('./pages/CustomerService.vue') },
  { path: '/ont', component: () => import('./pages/OntOps.vue') },
  { path: '/ont/map', component: () => import('./pages/OntHub.vue') },
  { path: '/ont/rules', component: () => import('./pages/OntRules.vue') },
  { path: '/ont/sim', component: () => import('./pages/OntSim.vue') },
  { path: '/ont/actions', component: () => import('./pages/OntActions.vue') },
  { path: '/ont/ai', component: () => import('./pages/OntAi.vue') },
  { path: '/ont/notify', component: () => import('./pages/OntNotify.vue') },
  { path: '/ont/reports', component: () => import('./pages/OntReports.vue') },
  { path: '/ont/:type', component: () => import('./pages/OntType.vue') },
  { path: '/ont/:type/:key(.*)', component: () => import('./pages/OntObject.vue') },
  { path: '/tasks', component: () => import('./pages/Tasks.vue') },
  { path: '/tasks/review/:sid', component: () => import('./pages/TaskReview.vue') },
  { path: '/tasks/:tid', component: () => import('./pages/TaskPage.vue') },
  { path: '/:p(.*)*', redirect: '/' },
];
// 企业页面（CAD 方案、选型零件库、账号与角色）只在 freecad-ai-parts 有（factory/SYNC.md）：有这几个页面文件才加路由；问渠这边没有
export const ENTERPRISE_PAGES = { './pages/CadDesigns.vue': '/cad', './pages/FapLibrary.vue': '/fap', './pages/Accounts.vue': '/accounts' };
for (const [f, load] of Object.entries(import.meta.glob(['./pages/CadDesigns.vue', './pages/FapLibrary.vue', './pages/Accounts.vue']))) {
  routes.splice(routes.length - 1, 0, { path: ENTERPRISE_PAGES[f], component: load });
}

const router = createRouter({ history: createWebHistory(), routes });
router.beforeEach((to) => {
  if (!to.meta.public && !session.token) return { path: '/login', query: { next: to.fullPath } };
  return true;
});

createApp(App).use(router).mount('#app');
