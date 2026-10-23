// 帮助里“本厂此刻”的领域数据（第 30 轮 §八 8-3）：```live kind: domain / domain: maint``` 取这个领域页上方那几个数。
// 每项 [字段, 名称, 格式]；格式：n 个数、pct 百分比、h 小时、money 钱、kwh 电量、kg、score 满意度（1–5）。
export const DOMAINS = {
  service: { api: '/service/kpis', page: '/service', name: '客户与服务', items: [
    ['open_complaints', '开着的投诉', 'n'], ['response_h', '平均响应', 'h'], ['open_jobs', '待上门的服务', 'n'],
    ['first_fix', '一次修复率', 'pct'], ['satisfaction', '满意度（近 30 天）', 'score'], ['warranty_cost', '保修成本', 'money']] },
  supply: { api: '/supply/kpis', page: '/supply', name: '采购与来料', items: [
    ['in_transit', '在途批次', 'n'], ['waiting_inspection', '到货待检', 'n'], ['rejected_open', '不合格待处理', 'n'],
    ['on_time', '准时率（近 30 天）', 'pct'], ['pass_rate', '合格率（近 30 天）', 'pct'], ['single_source', '单一来源的物料', 'n']] },
  maint: { api: '/maint/kpis', page: '/maint', name: '设备维护', items: [
    ['overdue', '保养逾期的设备', 'n'], ['open_repairs', '开着的维修单', 'n'], ['failure_down_7d', '近 7 天故障停机', 'h'],
    ['mtbf', '平均故障间隔', 'h'], ['open_inspections', '点检异常待处理', 'n']] },
  people: { api: '/people/kpis', page: '/people', name: '人员', items: [
    ['attendance_rate', '这一班出勤率', 'pct'], ['absent', '这一班不在岗', 'n'], ['gaps', '24 小时内排班缺口', 'n'],
    ['single_points', '只有一个人会开的设备', 'n'], ['overtime_h_week', '本周加班', 'h']] },
  ehs: { api: '/ehs/kpis', page: '/ehs', name: '安全环保', items: [
    ['open_issues', '开着的隐患', 'n'], ['major_open', '其中重大', 'n'], ['overdue', '整改逾期', 'n'], ['locked', '挂牌上锁的设备', 'n'],
    ['training_due', '培训 30 天内到期', 'n'], ['near_miss_30d', '未遂（近 30 天）', 'n']] },
  energy: { api: '/energy/kpis', page: '/energy', name: '能源', items: [
    ['kwh', '今天用电', 'kwh'], ['cost', '电费', 'money'], ['peak_share', '峰时占比', 'pct'], ['idle_share', '空转占比', 'pct'],
    ['co2_kg', '碳排放', 'kg'], ['demand_ratio', '需量 / 合同需量', 'pct']] },
  finance: { api: '/finance/kpis', page: '/finance', name: '经营与财务', items: [
    ['gross_margin', '毛利率', 'pct'], ['ar_total', '应收', 'money'], ['ar_overdue', '其中逾期', 'money'], ['dso', '应收周转天数', 'd'],
    ['cash', '现金', 'money'], ['budget_used', '本月预算已用', 'pct']] },
};

export function fmtItem(v, f, cur) {
  if (v == null || (typeof v === 'object')) return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  if (f === 'pct') return Math.round(n * 1000) / 10 + '%';
  if (f === 'h') return (Math.round(n * 10) / 10) + ' 小时';
  if (f === 'd') return Math.round(n) + ' 天';
  if (f === 'kwh') return Math.round(n).toLocaleString() + ' kWh';
  if (f === 'kg') return Math.round(n).toLocaleString() + ' kg';
  if (f === 'score') return n.toFixed(1) + ' 分';
  if (f === 'money') return (cur === 'USD' || !cur ? '$' : cur + ' ') + Math.round(n).toLocaleString();
  return String(Math.round(n * 10) / 10);
}

// 这一项值得提醒（标黄）：逾期、缺口、不合格这类数不为 0
const WARN = new Set(['open_complaints', 'rejected_open', 'overdue', 'open_repairs', 'gaps', 'major_open', 'ar_overdue', 'waiting_inspection', 'open_inspections']);
export const warnOf = (k, v) => WARN.has(k) && Number(v) > 0;
