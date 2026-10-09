// 帮助的章节（第 30 轮 H-3，搬自 freecad-ai-parts ADR-0065）：help/<版本>/<序号>-<名字>.md，一章一个文件，按文件名排序
const RAW = import.meta.glob('./*/*.md', { query: '?raw', import: 'default', eager: true });

export const EDITIONS = [
  { key: 'teach', name: '教学版', who: '学生与老师' },
  { key: 'enterprise', name: '企业版', who: '企业管理员与各岗位' },
];

export function chapterFiles(ed) {
  return Object.entries(RAW)
    .filter(([p]) => p.startsWith(`./${ed}/`))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([p, src]) => ({ slug: p.split('/').pop().replace(/^\d+-/, '').replace(/\.md$/, ''), src }));
}

// 首页全流程动画的七站（设计、ERP、MRP、MES、车间、质量、厂情中枢）各跳到哪一章
export const STAGE_CHAPTER = {
  teach: ['design-to-factory', 'design-to-factory', 'planning', 'workshop', 'workshop', 'quality', 'insight'],
  enterprise: ['plant', 'plant', 'daily-work', 'daily-work', 'daily-work', 'daily-work', 'insight'],
};
