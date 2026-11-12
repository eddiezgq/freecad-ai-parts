// 第 158 轮：零件库条目“到外部库查”——按条目和所选规格拼外部网站的搜索地址（纯函数，配置在 extlinks.json）。
// 规则（细则第三节 A）：
// - 电子元件（类别 ELE）：规格里有厂商型号（part）就用型号查 SnapMagic、LCSC、DigiKey；
//   没有型号的被动件按 ele_templates 用“封装 + 数值”查 LCSC、DigiKey（SnapMagic 对这类查询没有结果，不放）；两者都没有就不出链接。
// - 其他标准件（A 部分）：英文名（去掉括号里和逗号后的说明）+ 规格，查 MISUMI、McMaster-Carr。
// - 厂商件（来源是厂商目录、有官网）：只给厂商官网。
// - 机器人、机构、夹具：不出（已有原仓库或参数表链接）。
import CFG from './extlinks.json' with { type: 'json' };

const PREFIX = [[1e-12, 'p'], [1e-9, 'n'], [1e-6, 'u'], [1e-3, 'm'], [1, ''], [1e3, 'k'], [1e6, 'M'], [1e9, 'G']];

// 工程记数：1e-7 F → "100nF"，0.002 Ohm → "2mOhm"，8e6 Hz → "8MHz"
export function si(v, unit) {
  const x = Number(v);
  if (!Number.isFinite(x) || x <= 0) return null;
  let pick = PREFIX[0];
  for (const p of PREFIX) if (x >= p[0] * 0.9995) pick = p;
  const n = Math.round((x / pick[0]) * 1000) / 1000;
  return String(n) + pick[1] + unit;
}

function fill(tpl, params) {
  let ok = true;
  const out = tpl.replace(/\{(\w+)(?::(\w+))?\}/g, (_, k, unit) => {
    const v = params[k];
    if (v === undefined || v === null || v === '') { ok = false; return ''; }
    if (!unit) return String(v);
    const s = si(v, unit);
    if (s === null) ok = false;
    return s || '';
  });
  return ok ? out : null;
}

function link(site, q) {
  const s = CFG.sites[site];
  const slug = q.replace(/[^A-Za-z0-9.]+/g, '-').replace(/^-+|-+$/g, '');
  return { site, name: s.name, url: s.url.replace('{q}', encodeURIComponent(q)).replace('{slug}', slug) };
}

const group = (g, q) => CFG.groups[g].map((s) => link(s, q));

export function extLinks(entry, size) {
  if (!entry) return [];
  const params = (size && size.params) || {};
  const id = entry.id || '';
  if (entry.category === 'ELE') {
    if (params.part) return group('ele_part', String(params.part));
    const tpl = CFG.ele_templates[id];
    const q = tpl ? fill(tpl, params) : null;
    return q ? group('ele_value', q) : [];
  }
  if (id.startsWith('A-')) {
    const name = String((entry.name && entry.name.en) || '').replace(/\s*\([^)]*\)/g, '').split(',')[0].trim();
    if (!name) return [];
    const q = size && size.size && size.size !== 'default' ? name + ' ' + size.size : name;
    return group('mech', q);
  }
  if (entry.source && entry.source.origin === 'vendor' && entry.vendor && entry.vendor.site) {
    return [{ site: 'vendor', name: (entry.vendor.name && entry.vendor.name.en) || entry.vendor.id, url: entry.vendor.site }];
  }
  return [];
}
