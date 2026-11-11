// 第 130 轮：数字工厂英文版的纯函数部分（不依赖 Vue、不读文件），网页和测试脚本（web/tools/i18n_check.mjs）共用。
// 做法（细则 D-1）：页面上的中文原文就是“钥匙”，英文表里有就用英文，没有就显示中文——不会空白、不会报错。

// 站点定默认语言（同第 129 轮）：国内站 wenquestech.online 默认中文，其余（美国站、wenquestrobotics.com 各子域名、localhost）默认英文
export function siteLang(host) {
  return /(^|\.)wenquestech\.online$/i.test(String(host || '')) ? 'zh' : 'en';
}

const CJK = /[　-〿㐀-鿿＀-￯]/;
export const hasCjk = (s) => CJK.test(String(s ?? ''));

// {名字} 换成 vars 里的值；没给的保持原样
export function fill(s, vars) {
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (m, k) => (Object.prototype.hasOwnProperty.call(vars, k) && vars[k] != null ? String(vars[k]) : m));
}

// 精确查表；查不到再按“句型表”（后端写的句子，第三批）整句套，再按“词组表”逐段替换（数据里带数字的句子，如 CAN 帧解释、判据读数），
// 再按“；”“。”分句各自换；换完还剩中文就整句退回中文
// phrases：[[中文, 英文], …]，长的先换；tpls：compileTemplates() 的结果
export function translate(zh, dict, phrases, tpls, depth = 0) {
  if (zh == null) return '';
  const s = String(zh);
  if (!hasCjk(s)) return s;
  const alt = (k) => dict[k] && dict[k].replace(/^[\s,;.:]+|[\s:]+$/g, '');
  const hit = dict[s] || alt(s + '：') || alt('，' + s) || alt('；' + s);   // “客户反映”也认“客户反映：”，“影响…”也认“，影响…”
  if (hit) return hit;
  const lead = s.match(/^\s*/)[0], tail = s.match(/\s*$/)[0], core = s.trim();
  if (core !== s) { const r = translate(core, dict, phrases, tpls, depth); return hasCjk(r) ? s : lead + r + tail; }
  if (tpls && depth < 4) {
    const r = applyTemplates(s, dict, phrases, tpls, depth);
    if (r != null) return r;
  }
  if (phrases && phrases.length) {
    let out = s;
    for (const [a, b] of phrases) if (out.includes(a)) out = out.split(a).join(b);
    if (!hasCjk(out)) return out;
  }
  if (depth < 4) {
    const sub = (x) => translate(x, dict, phrases, tpls, depth + 1);
    // 开头是编号（A-00012、SH-301…）再空一格：编号照抄，后面再换
    let m = /^([^\s　-〿㐀-鿿＀-￯]+) (.+)$/.exec(s);
    if (m) { const r = sub(m[2]); if (!hasCjk(r)) return m[1] + ' ' + r; }
    // 结尾是括号里的补充：“X（Y）”
    m = /^(.+?)（([^（）]+)）$/.exec(s);
    if (m) { const a = sub(m[1]), b = sub(m[2]); if (!hasCjk(a + b)) return a + ' (' + b + ')'; }
    for (const [sep, join] of [['；', '; '], ['。', '. '], ['，', ', '], ['：', ': '], ['、', ', ']]) {
      if (!s.includes(sep)) continue;
      const parts = s.split(sep);
      const tr = parts.map((p) => (p ? translate(p, dict, phrases, tpls, depth + 1) : p));
      if (tr.every((p) => !hasCjk(p))) return tr.join(join).replace(/\s+$/, '').replace(/ ([.,;])/g, '$1');
    }
  }
  return s;
}

// 句型表 [[中文句型, 英文句型], …] → 按字面最长的一段建索引，匹配时只试原句里含这段的句型
export function compileTemplates(list) {
  const out = [];
  const all = [];
  for (const [zh, en] of list || []) {
    all.push([zh, en]);
    if (/^[，；、]/.test(zh)) all.push([zh.slice(1), en.replace(/^[\s,;]+/, '')]);   // 拼接用的“，影响 {a} 张订单”单独出现时
  }
  for (const [zh, en] of all) {
    const lits = zh.split(/\{[a-z]\}/);
    const names = [...zh.matchAll(/\{([a-z])\}/g)].map((m) => m[1]);
    if (!names.length) continue;
    const esc = lits.map((l) => l.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    let src = esc[0];
    for (let i = 0; i < names.length; i++) src += '([\\s\\S]*?)' + esc[i + 1];
    out.push({ rx: new RegExp('^' + src + '$'), rx2: new RegExp('^' + src.split('*?)').join('*)') + '$'), rx3: new RegExp('^' + src.replace('*?)', '\u0000').split('*?)').join('*)').replace('\u0000', '*?)') + '$'), names, en, key: lits.reduce((a, b) => (b.length > a.length ? b : a), ''), weight: lits.join('').length });
  }
  return out.sort((a, b) => b.weight - a.weight);
}

const MEMO = new Map();
function applyTemplates(s, dict, phrases, tpls, depth) {
  if (depth === 0 && MEMO.has(s)) return MEMO.get(s);
  let res = null;
  for (const t of tpls) {
    if (t.key && !s.includes(t.key)) continue;
    for (const rx of [t.rx, t.rx3, t.rx2]) {   // 先最短、再“第一个最短其余最长”、再最长地分占位（“（C 区）”这类括号在中间时）
      const m = rx.exec(s);
      if (!m) continue;
      const vals = {};
      let ok = true;
      t.names.forEach((n, i) => {
        const v = m[i + 1];
        const e = hasCjk(v) ? translate(v, dict, phrases, tpls, depth + 1) : v;
        if (hasCjk(e)) ok = false;
        vals[n] = e;
      });
      if (ok) { res = fill(t.en, vals); break; }
    }
    if (res != null) break;
  }
  if (depth === 0) { if (MEMO.size > 5000) MEMO.clear(); MEMO.set(s, res); }
  return res;
}

export function sortPhrases(list) {
  return [...list].sort((a, b) => b[0].length - a[0].length);
}

// 中英合写的名字（工厂清单里常见：“驱动板光板 4 层（外协） Drive board bare PCB”、“示例·传感器厂 Sensor Maker (Demo)”）取英文部分：
// 最后一个含中文的词之后的部分；开头的非字母词（规格、编号）在后面又出现过的去掉（“贴片电阻 0402 Chip resistor 0402” → “Chip resistor 0402”）
export function enPart(name) {
  const s = String(name ?? '').trim();
  if (!hasCjk(s)) return s;
  const toks = s.split(/\s+/);
  let last = -1;
  toks.forEach((t, i) => { if (hasCjk(t)) last = i; });
  let rest = toks.slice(last + 1);
  while (rest.length > 1 && rest.slice(1).includes(rest[0])) rest = rest.slice(1);
  return rest.join(' ');
}
