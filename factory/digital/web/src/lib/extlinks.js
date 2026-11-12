// 第 158 轮：“到外部库查”——按零件库条目（extLinks）或物料清单行（bomLinks）拼外部网站的搜索地址（纯函数）。
// 只拼地址、新窗口打开，不抓取、不转存对方内容；结果不进零件参数、不参与任何判定（freecad-ai-parts ADR-0092）。
// 每个地址模板 2026-11-11 在浏览器里实际打开核实过（细则第八节 158a）；换网站、加网站只改下面的 CFG。
// 问渠贴片页（services/eda/web/factory/extlinks.js）用这份文件的逐字副本，测试核对两份相同。
//
// 零件库条目（细则第三节 A）：
// - 电子元件（类别 ELE）：规格里有厂商型号（part）就用型号查 SnapMagic、LCSC、DigiKey；
//   没有型号的被动件按 ele_templates 用“封装 + 数值”查 LCSC、DigiKey（SnapMagic 对这类查询没有结果，不放）；两者都没有就不出链接。
// - 其他标准件（A 部分）：英文名（去掉括号里和逗号后的说明）+ 规格，查 MISUMI、McMaster-Carr。
// - 厂商件（来源是厂商目录、有官网）：只给厂商官网。
// - 机器人、机构、夹具：不出（已有原仓库或参数表链接）。
// 物料清单行（细则第三节 B）：见 bomLinks。
export const CFG = {
  "sites": {
    "snapeda": {
      "name": "SnapMagic",
      "url": "https://www.snapeda.com/search/?q={q}"
    },
    "lcsc": {
      "name": "LCSC",
      "url": "https://www.lcsc.com/search?q={q}"
    },
    "digikey": {
      "name": "DigiKey",
      "url": "https://www.digikey.com/en/products/result?keywords={q}"
    },
    "misumi": {
      "name": "MISUMI",
      "url": "https://us.misumi-ec.com/vona2/result/?Keyword={q}"
    },
    "mcmaster": {
      "name": "McMaster-Carr",
      "url": "https://www.mcmaster.com/products/{slug}/"
    }
  },
  "groups": {
    "ele_part": [
      "snapeda",
      "lcsc",
      "digikey"
    ],
    "ele_value": [
      "lcsc",
      "digikey"
    ],
    "mech": [
      "misumi",
      "mcmaster"
    ]
  },
  "ele_templates": {
    "A-ELE-C0402": "0402 {c_f:F}",
    "A-ELE-C1206": "1206 {c_f:F} {v_rated}V",
    "A-ELE-CPEL": "{c_f:F} {v_rated}V aluminum electrolytic",
    "A-ELE-DSCH": "{pkg} schottky {v_rated}V",
    "A-ELE-LPWR": "SRN6045 {l_h:H}",
    "A-ELE-R0402": "0402 {r_ohm:Ohm} {tol_pct}%",
    "A-ELE-SHUNT": "2512 {r_ohm:Ohm}",
    "A-ELE-TB": "terminal block 5mm {n_pin} pin",
    "A-ELE-XH": "JST B{n_pin}B-XH-A",
    "A-ELE-XTAL": "3225 {f_hz:Hz} crystal"
  }
};

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

// 物料清单一行 {item: 物料编号, value: 数值, package: 封装名} → 链接（细则第三节 B；不认得的行不出，不猜）：
// - IC-、MOS- 开头、数值是厂商型号：型号查 SnapMagic、LCSC、DigiKey（自研芯片 WQ- 开头的不查）
// - CAP-、RES-、IND-、XTAL：封装名里的四位尺寸码 + 数值补单位（100n → 0402 100nF；2m 1% → 2512 2mOhm 1%）查 LCSC、DigiKey；
//   Bourns 功率电感按封装里的系列号（L_Bourns_SRN6045TA → SRN6045TA 22uH）
// - 封装名里有 JST 插座型号（JST_XH_B4B-XH-A_… → B4B-XH-A）：型号查 LCSC、DigiKey
const UNIT = { CAP: 'F', RES: 'Ohm', IND: 'H' };

export function bomQuery(row) {
  const item = String((row && row.item) || '').toUpperCase();
  const value = String((row && row.value) || '').trim();
  const pkg = String((row && row.package) || '');
  if (/^(IC|MOS)-/.test(item)) {
    if (!/^[A-Za-z0-9][A-Za-z0-9.\-/]*$/.test(value) || /^WQ-/i.test(value)) return null;
    return { q: value, group: 'ele_part' };
  }
  const jst = pkg.match(/JST_(?:XH|PH)_(B\d+B-(?:XH|PH)-[A-Z])/);
  if (jst) return { q: jst[1], group: 'ele_value' };
  if (item.startsWith('XTAL')) {
    const code = pkg.match(/_SMD_(\d{4})-/);
    return code && /^[\d.]+[kM]?Hz$/i.test(value) ? { q: code[1] + ' ' + value + ' crystal', group: 'ele_value' } : null;
  }
  const kind = item.split('-')[0];
  const unit = UNIT[kind];
  if (!unit) return null;
  const v = value.match(/^([\d.]+)([pnumkM]?)(?:\/(\d+(?:\.\d+)?V))?(?:\s+(\d+(?:\.\d+)?%))?$/);
  if (!v) return null;
  const val = v[1] + v[2] + unit + (v[3] ? ' ' + v[3] : '') + (v[4] ? ' ' + v[4] : '');
  const code = pkg.match(/_(\d{4})_\d{4}Metric/);
  if (code) return { q: code[1] + ' ' + val, group: 'ele_value' };
  const fam = kind === 'IND' && pkg.match(/^L_Bourns_(SRN\w+)$/);
  if (fam) return { q: fam[1] + ' ' + val, group: 'ele_value' };
  return null;
}

export function bomLinks(row) {
  const r = bomQuery(row);
  return r ? group(r.group, r.q) : [];
}
