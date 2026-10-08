// 各页面的名字（顶栏标题、帮助里“打开某某页”共用）
export const PAGES = {
  '/': '运营总览', '/work/planner': '订单与计划', '/work/engineer': '设计与工艺', '/work/operator': '车间终端',
  '/work/quality': '质量', '/work/manager': '经营与成本', '/3d': '3D 车间', '/teach': '实验 7', '/bus': '统一数据总线', '/library': '零件与机器人库',
  '/design': '设计发布与审批', '/cad': 'CAD 方案', '/fap': '选型零件库', '/members': '企业成员', '/accounts': '账号与角色', '/configurator': '参数配置器', '/cae': '仿真与分析', '/cfd': '流体分析', '/mbd': '运动与动力分析', '/cam': '数控编程', '/opt': '设计优化', '/twin': '数字孪生', '/plc': '虚拟 PLC', '/tasks': '我的任务',
  '/quality/8d': '质量异常单（8D）', '/ont': '厂情中枢 · 指挥台', '/ont/map': '厂情中枢 · 全貌地图', '/ont/rules': '厂情中枢 · 规则目录', '/ont/sim': '厂情中枢 · 推演工作台', '/ont/actions': '厂情中枢 · 动作收件箱', '/ont/ai': '厂情中枢 · AI 运行记录', '/ont/notify': '通知设置', '/lab15': '实验 15 · 车间异常的追因、推演与决策', '/ont/reports': '厂情中枢 · 日报与周报',
};

export function pageTitle(path) {
  return PAGES[path] || (path === '/help' || path.startsWith('/help/') ? '帮助' : '')
    || (path.startsWith('/quality/8d/') ? '质量异常单（8D）' : path.startsWith('/ont/') ? '厂情中枢' : '')
    || (path.startsWith('/design/') ? '设计审阅' : path.startsWith('/tasks/review/') ? '任务单审阅' : path.startsWith('/tasks/') ? '工程任务单' : '');
}
