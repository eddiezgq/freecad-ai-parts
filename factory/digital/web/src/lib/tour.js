// “带我去做”（ADR-0065）：打开页面后按步骤高亮要点的地方。页面元素用 data-help="标记" 标出，步骤定义在 help/tours.json。
// 第 30 轮 §八 8-1“做完打勾”：步骤可以带 done 条件，系统检测到这一步真的做了就打勾、自动进下一步，最后显示“这一节完成”。
//   done: { route: '/maint', query: { tab: 'pm' } }                 地址到了
//   done: { selector: '[data-help="planner-mrp"]' }                  页面上出现了这个元素
//   done: { api: '/ehs/issues', path: 'issues.length', grew: true }  接口里的数比这一步开始时多了（也可以 gt / gte / eq 一个数）
//   done: { api: '/proposals', path: '0.proposal_id', changed: true } 接口里的这个值和这一步开始时不一样了（列表有条数上限时用：最新一条换了）
import { reactive } from 'vue';
import BASE from '../help/tours.json';
import EXTRA from '../help/extra.json';        // 本仓库独有的引导（freecad-ai-parts 的企业功能；问渠这边是空的，factory/SYNC.md）

const TOURS = { ...BASE, ...(EXTRA.tours || {}) };

export const tour = reactive({ id: null, i: 0, steps: [], title: '', ok: [], finished: false });

const DONE_KEY = 'wq-help-tours-done';

export function tourDef(id) { return TOURS[id] || null; }
export function hasDone(t) { return !!t && t.steps.some((s) => s.done); }

// 由帮助页调用：跳到页面并开始引导
export function startTour(router, id) {
  const t = TOURS[id];
  if (!t) return;
  tour.id = id; tour.i = 0; tour.steps = t.steps; tour.title = t.title; tour.ok = t.steps.map(() => false); tour.finished = false;
  router.push({ path: t.path, query: t.query || {} });
}

export function stopTour() { tour.id = null; tour.steps = []; tour.i = 0; tour.ok = []; tour.finished = false; }
export function nextStep() {
  if (tour.i < tour.steps.length - 1) { tour.i += 1; return; }
  // 最后一步：带“做完检测”的引导，要检测的步骤都打了勾才显示“这一节完成”
  const t = TOURS[tour.id];
  if (hasDone(t) && tour.steps.every((s, k) => !s.done || tour.ok[k])) finish(); else stopTour();
}
export function prevStep() { if (tour.i > 0) tour.i -= 1; }

// 这一步检测到做了：打勾，过一会儿自动进下一步
export function markDone(i) {
  if (!tour.id || tour.ok[i]) return;
  tour.ok[i] = true;
  if (i === tour.i) setTimeout(() => { if (tour.id && tour.i === i && !tour.finished) nextStep(); }, 900);
}

function finish() {
  tour.finished = true;
  try {
    const s = new Set(JSON.parse(localStorage.getItem(DONE_KEY) || '[]'));
    s.add(tour.id);
    localStorage.setItem(DONE_KEY, JSON.stringify([...s]));
  } catch { /* 无痕窗口：不记 */ }
}

export function tourDoneBefore(id) {
  try { return JSON.parse(localStorage.getItem(DONE_KEY) || '[]').includes(id); } catch { return false; }
}

// 取接口返回里的一个数：path 写成 'issues.length'、'kpis.overdue'
export function pick(obj, path) {
  return String(path || '').split('.').filter(Boolean).reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

// 条件满足没有。base：这一步开始时接口里的数（grew 用）
export function met(done, ctx) {
  if (done.route) {
    if (ctx.route.path !== done.route) return false;
    return Object.entries(done.query || {}).every(([k, v]) => String(ctx.route.query[k] ?? '') === String(v));
  }
  if (done.selector) return !!ctx.doc.querySelector(done.selector);
  if (done.api) {
    if (done.changed) return ctx.value != null && String(ctx.value) !== String(ctx.base ?? '');
    const v = Number(ctx.value);
    if (ctx.value == null || Number.isNaN(v)) return false;
    if (done.grew) return ctx.base != null && v > Number(ctx.base);
    if (done.gt != null) return v > Number(done.gt);
    if (done.gte != null) return v >= Number(done.gte);
    if (done.eq != null) return v === Number(done.eq);
  }
  return false;
}
