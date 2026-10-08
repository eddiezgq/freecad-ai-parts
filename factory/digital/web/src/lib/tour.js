// “带我去做”（ADR-0065）：打开页面后按步骤高亮要点的地方。页面元素用 data-help="标记" 标出，步骤定义在 help/tours.json。
import { reactive } from 'vue';
import TOURS from '../help/tours.json';

export const tour = reactive({ id: null, i: 0, steps: [], title: '' });

export function tourDef(id) { return TOURS[id] || null; }

// 由帮助页调用：跳到页面并开始引导
export function startTour(router, id) {
  const t = TOURS[id];
  if (!t) return;
  tour.id = id; tour.i = 0; tour.steps = t.steps; tour.title = t.title;
  router.push({ path: t.path, query: t.query || {} });
}

export function stopTour() { tour.id = null; tour.steps = []; tour.i = 0; }
export function nextStep() { if (tour.i < tour.steps.length - 1) tour.i += 1; else stopTour(); }
export function prevStep() { if (tour.i > 0) tour.i -= 1; }
