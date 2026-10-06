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
  { path: '/work/manager', component: () => import('./pages/Manager.vue') },
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

const router = createRouter({ history: createWebHistory(), routes });
router.beforeEach((to) => {
  if (!to.meta.public && !session.token) return { path: '/login', query: { next: to.fullPath } };
  return true;
});

createApp(App).use(router).mount('#app');
