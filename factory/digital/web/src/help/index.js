// 帮助的章节（第 30 轮 H-3，搬自 freecad-ai-parts ADR-0065）：help/<版本>/<序号>-<名字>.md，一章一个文件，按文件名排序
const RAW = import.meta.glob('./*/*.md', { query: '?raw', import: 'default', eager: true });

export const EDITIONS = [
  { key: 'teach', name: '教学版', who: '学生与老师' },
  { key: 'enterprise', name: '企业版', who: '企业管理员与各岗位' },
  // 第 45 轮：问渠数字工业园的机器人厂（plant：只在按这份清单起的厂里显示，并且是那里的缺省一册）
  { key: 'robot', name: '机器人厂', who: '问渠数字工业园 · 机器人厂', plant: 'wenquest-robot' },
  // 第 85 轮：第三座厂，电路板厂
  { key: 'pcb', name: '电路板厂', who: '问渠数字工业园 · 电路板厂', plant: 'wenquest-pcb' },
  // 第 103 轮：第四座厂，芯片厂（封装测试厂）
  { key: 'chip', name: '芯片厂', who: '问渠数字工业园 · 芯片厂', plant: 'wenquest-chip' },
  // 第 125 轮：第五座厂，传感器厂（关节编码器与扭矩传感器）
  { key: 'sensor', name: '传感器厂', who: '问渠数字工业园 · 传感器厂', plant: 'wenquest-sensor' },
  // 第 131 轮：第六座厂，电机厂（伺服电机、AGV 驱动电机）
  { key: 'motor', name: '电机厂', who: '问渠数字工业园 · 电机厂', plant: 'wenquest-motor' },
  // 第 166 轮：第八座厂，计算机厂（台式机、笔记本、服务器、整机柜、工控机）
  { key: 'computer', name: '计算机厂', who: '问渠数字工业园 · 计算机厂', plant: 'wenquest-computer' },
  // 第 134 轮：问渠缝纫机厂（按工艺方案建的整机厂，不在工业园的买卖链里）
  { key: 'sewing', name: '缝纫机厂', who: '问渠缝纫机厂', plant: 'wenquest-sewing' },
];

// 这座厂能看到哪几册：带 plant 的只在那座厂显示
export function editionsFor(plantId) {
  return EDITIONS.filter((e) => !e.plant || e.plant === plantId);
}

// 第 130 轮第四批（细则 D-13）：英文稿放在 help/<版本>/en/<同名>.md；英文界面有英文稿用英文稿，没有就用中文稿（页面顶上说明）
const RAW_EN = import.meta.glob('./*/en/*.md', { query: '?raw', import: 'default', eager: true });

export function chapterFiles(ed, en = false) {
  return Object.entries(RAW)
    .filter(([p]) => p.startsWith(`./${ed}/`))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([p, src]) => {
      const e = en ? RAW_EN[p.replace(/\/([^/]+)$/, '/en/$1')] : null;
      return { slug: p.split('/').pop().replace(/^\d+-/, '').replace(/\.md$/, ''), src: e || src, enMissing: en && !e };
    });
}

// 首页全流程动画的七站（设计、ERP、MRP、MES、车间、质量、厂情中枢）各跳到哪一章。
// “a|b”：有 a 章跳 a，没有跳 b（企业版的章节两个仓库各自写：freecad-ai-parts 有“新产品进工厂”“模型网关”，问渠这边没有）
export const STAGE_CHAPTER = {
  teach: ['design-to-factory', 'design-to-factory', 'planning', 'workshop', 'workshop', 'quality', 'insight'],
  enterprise: ['new-product|plant', 'new-product|plant', 'daily-work', 'daily-work', 'gateway|daily-work', 'daily-work', 'insight'],
  robot: ['plant', 'products-bom', 'order-to-invoice', 'order-to-invoice', 'plant', 'joint-test', 'plant'],
  pcb: ['plant', 'products-bom', 'order-park', 'order-park', 'plant', 'smt-inspection', 'equip-ai'],
  chip: ['plant', 'products-bom', 'products-bom', 'products-bom', 'plant', 'wafer-test', 'equip-ai'],
  sensor: ['plant', 'products-bom', 'products-bom', 'products-bom', 'plant', 'encoder-line', 'equip-ai'],
  motor: ['plant', 'products-bom', 'products-bom', 'products-bom', 'plant', 'final-test', 'equip-ai'],
  computer: ['plant', 'products-bom', 'products-bom', 'lines', 'lines', 'burn-in', 'equip-ai'],
  sewing: ['plant', 'products-bom', 'products-bom', 'products-bom', 'foundry-housing', 'foundry-housing', 'equip-ai'],
};
