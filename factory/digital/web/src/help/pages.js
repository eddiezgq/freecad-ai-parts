// 各页面的名字（顶栏标题、帮助里“打开某某页”共用；第 30 轮 H-3 从 App.vue 挪到这里）
export const PAGES = {
  '/': '运营总览', '/work/planner': '订单与计划', '/work/engineer': '设计与工艺', '/work/operator': '车间终端',
  '/work/quality': '质量', '/3d': '3D 车间', '/teach': '实验 7', '/bus': '统一数据总线', '/library': '零件与机器人库',
  '/design': '设计发布与审批', '/cad': 'CAD 方案', '/fap': '选型零件库', '/members': '企业成员', '/accounts': '账号与角色', '/configurator': '参数配置器', '/cae': '仿真与分析', '/cfd': '流体分析', '/mbd': '运动与动力分析', '/cam': '数控编程', '/opt': '设计优化', '/twin': '数字孪生', '/plc': '虚拟 PLC', '/tasks': '我的任务',
  '/process': '工艺规程与 AI 评审',
  '/quality/8d': '质量异常单（8D）', '/ont': '厂情中枢 · 指挥台', '/ont/map': '厂情中枢 · 全貌地图', '/ont/rules': '厂情中枢 · 规则目录', '/ont/sim': '厂情中枢 · 推演工作台', '/ont/actions': '厂情中枢 · 动作收件箱', '/ont/ai': '厂情中枢 · AI 运行记录', '/ont/notify': '通知设置', '/service': '客户与服务', '/lab15': '实验 15 · 车间异常的追因、推演与决策', '/lab16': '实验 16 · 客户投诉的追溯、召回与服务决策', '/lab17': '实验 17 · 安全隐患的识别、评估与停机决策', '/ehs': '安全环保', '/maint': '设备维护', '/lab18': '实验 18 · 设备维护策略：保养时机的决策', '/people': '人员', '/lab19': '实验 19 · 排班与技能：缺人时的决策', '/supply': '采购与来料', '/lab20': '实验 20 · 供应链：来料不合格与供应商选择', '/energy': '能源与环境', '/lab21': '实验 21 · 能源：空转、错峰与单件碳足迹', '/finance': '经营与财务', '/lab22': '实验 22 · 经营：订单毛利、应收与现金', '/ont/reports': '厂情中枢 · 日报与周报',
  '/director': '情景导演', '/labs': '实验与任务', '/lab23': '实验 23 · 两周情景：一张急单的全厂决策', '/help': '帮助',
  '/cost': '生产成本', '/lab28': '负载跑合 · 实验 28',
};

export function pageTitle(path) {
  return PAGES[path] || (path === '/help' || path.startsWith('/help/') ? '帮助' : '')
    || (path.startsWith('/quality/8d/') ? '质量异常单（8D）' : path.startsWith('/ont/') ? '厂情中枢' : '')
    || (path.startsWith('/design/') ? '设计审阅' : path.startsWith('/process/') ? '工艺规程与 AI 评审'
      : path.startsWith('/tasks/review/') ? '任务单审阅' : path.startsWith('/tasks/') ? '工程任务单' : '');
}

// 右上角“帮助”：这一页对应教学版的哪一章（第 19 轮 J-10 的对照表，第 30 轮改指新帮助的章节）。
export const PAGE_CHAPTER = [
  ['/work/planner', 'planning'], ['/work/operator', 'workshop'], ['/3d', 'workshop'], ['/bus', 'workshop'],
  ['/work/quality', 'quality'], ['/quality/8d', 'quality'],
  ['/work/engineer', 'design-to-factory'], ['/process', 'design-to-factory'], ['/design', 'design-to-factory'],
  ['/cae', 'design-to-factory'], ['/cfd', 'design-to-factory'], ['/mbd', 'design-to-factory'], ['/cam', 'design-to-factory'],
  ['/opt', 'design-to-factory'], ['/twin', 'design-to-factory'], ['/plc', 'design-to-factory'], ['/configurator', 'design-to-factory'],
  ['/ont', 'insight'], ['/service', 'service'], ['/lab16', 'service'], ['/supply', 'supply'], ['/lab20', 'supply'],
  ['/finance', 'finance'], ['/lab22', 'finance'], ['/maint', 'maint'], ['/lab18', 'maint'], ['/people', 'people'], ['/lab19', 'people'],
  ['/ehs', 'ehs'], ['/lab17', 'ehs'], ['/energy', 'energy'], ['/lab21', 'energy'],
  ['/labs', 'labs'], ['/teach', 'labs'], ['/lab15', 'labs'], ['/tasks', 'start'],
  ['/director', 'director'], ['/lab23', 'director'],
  // 没有对应章节的页面打开“资料”里的说明
  ['/library', '/help/docs/零件与机器人库'], ['/members', '/help/docs/数字工厂企业版使用说明'], ['/', 'dashboard'],
];
// 企业工厂：企业版章节少，只对照这几页，其余打开企业版目录
export const PAGE_CHAPTER_ENT = [
  ['/work/planner', 'daily-work'], ['/work/operator', 'daily-work'], ['/work/quality', 'daily-work'], ['/quality/8d', 'daily-work'],
  ['/cost', 'daily-work'], ['/ont/ai', 'ai'], ['/ont', 'insight'], ['/3d', 'plant'],
];
export function helpLink(path, demo = true) {
  if (!demo) {
    const e = PAGE_CHAPTER_ENT.find(([p]) => path === p || path.startsWith(p + '/'));
    return e ? '/help/enterprise/' + e[1] : '/help/enterprise';
  }
  const hit = PAGE_CHAPTER.find(([p]) => (p === '/' ? path === '/' : path === p || path.startsWith(p + '/')));
  if (!hit) return '/help/teach';
  return hit[1].startsWith('/') ? hit[1] : '/help/teach/' + hit[1];
}
