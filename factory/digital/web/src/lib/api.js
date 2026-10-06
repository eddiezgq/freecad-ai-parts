// 工作台与枢纽服务（hub）之间的全部请求都走这里
import { reactive } from 'vue';

const KEY = 'wq-df-session';
function load() {
  try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { return null; }
}

export const session = reactive({ token: null, user: null, config: null, ...(load() || {}) });

function save() {
  try { localStorage.setItem(KEY, JSON.stringify({ token: session.token, user: session.user })); } catch (e) { /* 无痕窗口 */ }
}

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(method, path, body) {
  const r = await fetch('/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(session.token ? { 'x-wq-token': session.token } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text }; }
  if (r.status === 401) { logout(); throw new ApiError(401, '请先登录'); }
  if (!r.ok) throw new ApiError(r.status, (data && data.detail) || `请求失败（${r.status}）`);
  return data;
}

export const get = (p) => api('GET', p);
export const post = (p, b) => api('POST', p, b ?? {});

// 本地版填名字；线上版（问渠账号）不传名字，枢纽凭全站登录凭证认人
export async function login(name, role, mode) {
  const r = await post('/login', name ? { name, role, mode } : { role, mode });
  session.token = r.token;
  session.user = r.user;
  save();
  return r.user;
}

export async function switchTo(patch) {
  const r = await post('/me/switch', patch);
  session.token = r.token;
  session.user = r.user;
  save();
}

export function logout() {
  session.token = null;
  session.user = null;
  save();
}

export async function loadConfig() {
  if (!session.config) session.config = await get('/config');
  return session.config;
}

export const ROLES = [
  { key: 'manager', name: '厂长', en: 'Plant manager' },
  { key: 'planner', name: '计划员', en: 'Planner' },
  { key: 'engineer', name: '工艺员', en: 'Process engineer' },
  { key: 'operator', name: '操作工', en: 'Operator' },
  { key: 'quality', name: '质检员', en: 'Quality inspector' },
  { key: 'approver', name: '审批人', en: 'Approver', prod: true },
  { key: 'sales', name: '销售', en: 'Sales', prod: true },
];
// 学生可选的岗位（厂长只给老师，第 3 轮 D3）
// 企业版（第 8 轮）：审批人、销售只在生产模式；企业成员在生产模式只能用授权给他的角色
export const rolesFor = (user, mode) => {
  const m = mode || user?.mode;
  if (!user || user.teacher !== false) return m === 'prod' ? ROLES : ROLES.filter((r) => !r.prod);
  if (m === 'prod') return ROLES.filter((r) => (user.member || []).includes(r.key));
  return ROLES.filter((r) => r.key !== 'manager' && !r.prod);
};
export const canProd = (user) => !user || user.teacher !== false || !!(user.member || []).length;
export const roleName = (k) => (ROLES.find((r) => r.key === k) || {}).name || k;
