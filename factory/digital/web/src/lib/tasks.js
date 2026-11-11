// 工程任务单（第 11 轮《机械设计》2.7（4）（5））：页面共用的小工具
import { session } from './api';
import { t, tk } from './i18n';

// 第 130 轮：显示时按语言取（值是中文钥匙）
const tmap = (o) => new Proxy(o, { get: (x, k) => (typeof x[k] === 'string' ? t(x[k]) : x[k]) });

export const STATUS = tmap({ draft: tk('未提交'), submitted: tk('待老师审阅'), returned: tk('退回修改'), approved: tk('已批准'), graded: tk('已评分') });
export const TONE = { draft: '', submitted: 'warn', returned: 'bad', approved: 'good', graded: 'good' };
// 进度条：提交 → AI 评审 → 老师批准 → 加工 → 检验 → 评分
export const STAGES = tmap([tk('提交'), tk('AI 评审'), tk('老师批准'), tk('加工'), tk('检验'), tk('评分')]);
export function stageIndex(sub) {
  if (!sub) return -1;
  return { draft: -1, returned: 1, submitted: 1, approved: 3, inspected: 4, graded: 5 }[sub.stage || sub.status] ?? -1;
}
export const LEVEL = tmap({ error: tk('必改'), warning: tk('建议'), info: tk('说明') });

export async function upload(path, fields) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) if (v !== null && v !== undefined && v !== '') fd.append(k, v);
  const r = await fetch('/api' + path, { method: 'POST', headers: { 'x-wq-token': session.token }, body: fd });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || t('上传失败（{s}）', { s: r.status }));
  return d;
}
