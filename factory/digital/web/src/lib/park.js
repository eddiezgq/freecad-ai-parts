// 第 167d 轮：顶上厂名下拉切换工厂、问渠标志回官网首页。
// 线上每个厂一个子域名：factory.<主域名> 是减速器厂（演示工厂），<厂>.factory.<主域名> 是园里其他厂；
// 主域名国内是 wenquestech.online，美国是 wenquestrobotics.com。本机（localhost）不认这些子域名，下拉菜单就不出现。
const tk = (zh) => zh;   // 只标出要翻译的厂名（英文在 locales/en.json），显示时由 t() 换；本文件不引别的模块，好单独测

export const PARK = [
  { sub: '', id: 'wenquest-gearbox', name: tk('问渠减速器厂（演示工厂）') },
  { sub: 'robot', id: 'wenquest-robot', name: tk('机器人厂') },
  { sub: 'pcb', id: 'wenquest-pcb', name: tk('电路板厂') },
  { sub: 'chip', id: 'wenquest-chip', name: tk('芯片封测厂') },
  { sub: 'sensor', id: 'wenquest-sensor', name: tk('传感器厂') },
  { sub: 'motor', id: 'wenquest-motor', name: tk('电机厂') },
  { sub: 'computer', id: 'wenquest-computer', name: tk('计算机厂') },
  { sub: 'software', id: 'wenquest-software', name: tk('软件公司') },
  { sub: 'sewing', id: 'wenquest-sewing', name: tk('缝纫机厂') },
];

const SITES = ['wenquestech.online', 'wenquestrobotics.com'];

// 当前网址属于哪个主域名的数字工厂：{ base } 或 null（本机、其他网址）
export function factoryBase(host = location.hostname) {
  const labels = host.toLowerCase().split('.');
  const i = labels.indexOf('factory');
  if (i < 0 || i > 1) return null;
  const base = labels.slice(i + 1).join('.');
  return SITES.includes(base) ? { base } : null;
}

export function plantUrl(p, host = location.hostname) {
  const f = factoryBase(host);
  return f ? `https://${p.sub ? p.sub + '.' : ''}factory.${f.base}/` : null;
}

// 问渠标志指向的首页：线上是同一主域名的问渠官网首页，本机就回本厂首页（null）
export function homeUrl(host = location.hostname) {
  const h = host.toLowerCase();
  const site = SITES.find((s) => h === s || h.endsWith('.' + s));
  return site ? `https://${site}/` : null;
}
