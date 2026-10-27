// 帮助的章节（第 30 轮 H-3，搬自 freecad-ai-parts ADR-0065）：help/<版本>/<序号>-<名字>.md，一章一个文件，按文件名排序
const RAW = import.meta.glob('./*/*.md', { query: '?raw', import: 'default', eager: true });

export const EDITIONS = [
  { key: 'teach', name: '教学版', who: '学生与老师' },
  { key: 'enterprise', name: '企业版', who: '企业管理员与各岗位' },
  // 第 45 轮：问渠数字工业园的机器人厂（plant：只在按这份清单起的厂里显示，并且是那里的缺省一册）
  { key: 'robot', name: '机器人厂', who: '问渠数字工业园 · 机器人厂', plant: 'wenquest-robot' },
];

// 这座厂能看到哪几册：带 plant 的只在那座厂显示
export function editionsFor(plantId) {
  return EDITIONS.filter((e) => !e.plant || e.plant === plantId);
}

export function chapterFiles(ed) {
  return Object.entries(RAW)
    .filter(([p]) => p.startsWith(`./${ed}/`))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([p, src]) => ({ slug: p.split('/').pop().replace(/^\d+-/, '').replace(/\.md$/, ''), src }));
}

// 首页全流程动画的七站（设计、ERP、MRP、MES、车间、质量、厂情中枢）各跳到哪一章。
// “a|b”：有 a 章跳 a，没有跳 b（企业版的章节两个仓库各自写：freecad-ai-parts 有“新产品进工厂”“模型网关”，问渠这边没有）
export const STAGE_CHAPTER = {
  teach: ['design-to-factory', 'design-to-factory', 'planning', 'workshop', 'workshop', 'quality', 'insight'],
  enterprise: ['new-product|plant', 'new-product|plant', 'daily-work', 'daily-work', 'gateway|daily-work', 'daily-work', 'insight'],
  robot: ['plant', 'products-bom', 'order-to-invoice', 'order-to-invoice', 'plant', 'joint-test', 'plant'],
};
