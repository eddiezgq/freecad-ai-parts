// “点哪看哪”（第 30 轮 §八 H-11 第 5 种）：3D 车间、首页上点一台设备，弹出它此刻的状态和对应的帮助章节。
// 只用已有的数据：总线上的设备状态（state、locked、run_h_pm）、/api/layout（名字、标准保养周期 pm_h），
// 演示工厂再加设备维护的 /api/maint/risk/<设备>（老师在“设备维护”里改过的保养周期以它为准，和设备维护页、厂情中枢一致）。
import { STATE } from './fmt';

// m：总线上的设备状态（可能为空）；u：/api/layout 里这台设备（可能为空）；demo：是不是演示工厂；
// risk：/api/maint/risk/<设备> 的结果（可能为空：企业工厂、还没取到、取不到）
export function machineInfo(m, u, demo = true, risk = null) {
  const st = STATE[m?.state] ? m.state : 'idle';
  const runH = risk?.run_h ?? m?.run_h_pm;
  const pmH = risk?.pm_h ?? u?.pm_h;
  const overdueH = pmH && runH != null && runH > pmH ? Math.round(runH - pmH) : 0;
  const tags = [];
  if (m?.locked) tags.push({ text: '🔒 挂牌上锁', tone: 'bad' });
  if (overdueH) tags.push({ text: `保养逾期 ${overdueH} 小时`, tone: 'warn' });
  if (m?.off_shift) tags.push({ text: '下班', tone: 'mute' });
  // 停了、锁了、保养逾期 → 设备维护；在跑或空闲 → 车间一章。企业工厂没有“设备维护”，看工厂清单一章
  const maint = ['down', 'fault'].includes(st) || m?.locked || overdueH > 0;
  const help = !demo ? { to: '/help/enterprise/plant', label: '帮助：工厂清单与 3D 车间' }
    : maint ? { to: '/help/teach/maint', label: '帮助：设备维护', domain: '设备维护' }
      : { to: '/help/teach/workshop', label: '帮助：车间与派工', domain: '生产' };
  return { state: st, label: STATE[st].label, color: STATE[st].color, bg: STATE[st].bg, reason: m?.reason || '', tags, help,
    runH: runH != null ? Math.round(runH) : null, pmH };
}
