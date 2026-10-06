// WenQuest PLC engine (第 18 轮，《PLC 原理及实践》): an IEC 61131-3 subset that runs in the browser and in Node.
//
//   ST    PROGRAM / FUNCTION_BLOCK / FUNCTION / TYPE (STRUCT, enum), VAR sections with AT %IX0.0, RETAIN, CONSTANT;
//         IF / CASE / FOR / WHILE / REPEAT / EXIT / RETURN, FB calls with := and =>, arrays, structs, strings, TIME.
//   LD    rungs on a grid: contacts (NO, NC, P, N, compare), coils (normal, negated, set, reset), FB boxes
//         (TON, TOF, TP, CTU, CTD, R_TRIG, F_TRIG) and assignment boxes; vertical links make parallel branches.
//   Runtime  cyclic scan: input image → program → output image, scan time, watchdog, forcing, trace, edge-exact timers.
//   Tests    a test case drives a plant model and checks outputs in simulated time (〔TST〕).
//   XML      PLCopen TC6 v2.01 export of ST POUs and the I/O table.
//
// The same file is loaded by the lab page (window.WQPLC) and by the Node tests (module.exports).
(function (root) {
"use strict";

// ---------------------------------------------------------------- errors
class PlcError extends Error {
  constructor(code, msg, line) { super(msg); this.code = code; this.line = line || 0; }
}
const E = (code, msg, line) => new PlcError(code, msg, line);

// ---------------------------------------------------------------- types
const INT_TYPES = {
  SINT: [-128, 127], INT: [-32768, 32767], DINT: [-2147483648, 2147483647], LINT: [-9007199254740991, 9007199254740991],
  USINT: [0, 255], UINT: [0, 65535], UDINT: [0, 4294967295], ULINT: [0, 9007199254740991],
  BYTE: [0, 255], WORD: [0, 65535], DWORD: [0, 4294967295], LWORD: [0, 9007199254740991],
};
const REAL_TYPES = new Set(["REAL", "LREAL"]);
const ELEMENTARY = new Set(["BOOL", "TIME", "STRING", "WSTRING", "DATE", "TOD", "DT", ...Object.keys(INT_TYPES), ...REAL_TYPES]);

function wrapInt(v, t) {
  const r = INT_TYPES[t];
  if (!r) return v;
  v = Math.trunc(v);
  if (!isFinite(v)) return 0;
  const span = r[1] - r[0] + 1;
  if (v < r[0] || v > r[1]) {
    if (span > 2 ** 53) return Math.max(r[0], Math.min(r[1], v));
    v = ((v - r[0]) % span + span) % span + r[0];
  }
  return v;
}
function coerce(v, t) {
  if (t === "BOOL") return !!v;
  if (INT_TYPES[t]) return typeof v === "boolean" ? (v ? 1 : 0) : wrapInt(v, t);
  if (REAL_TYPES.has(t)) { const x = typeof v === "boolean" ? (v ? 1 : 0) : +v; return t === "REAL" ? Math.fround(x) : x; }
  if (t === "TIME") return +v || 0;
  if (t === "STRING" || t === "WSTRING") return String(v);
  return v;
}

// ---------------------------------------------------------------- lexer
const KEYWORDS = new Set(("PROGRAM END_PROGRAM FUNCTION_BLOCK END_FUNCTION_BLOCK FUNCTION END_FUNCTION TYPE END_TYPE STRUCT END_STRUCT " +
  "VAR VAR_INPUT VAR_OUTPUT VAR_IN_OUT VAR_GLOBAL VAR_EXTERNAL VAR_TEMP END_VAR RETAIN NON_RETAIN CONSTANT AT " +
  "IF THEN ELSIF ELSE END_IF CASE OF END_CASE FOR TO BY DO END_FOR WHILE END_WHILE REPEAT UNTIL END_REPEAT EXIT RETURN " +
  "AND OR XOR NOT MOD TRUE FALSE ARRAY").split(" "));

function lex(src) {
  const out = [];
  let i = 0, line = 1;
  const n = src.length;
  const push = (t, v, extra) => out.push(Object.assign({ t, v, line }, extra || {}));
  while (i < n) {
    const c = src[i];
    if (c === "\n") { line++; i++; continue; }
    if (/\s/.test(c)) { i++; continue; }
    if (c === "(" && src[i + 1] === "*") {
      const j = src.indexOf("*)", i + 2);
      if (j < 0) throw E("syntax", "注释没有结束 (* … *) / unterminated comment", line);
      line += (src.slice(i, j).match(/\n/g) || []).length; i = j + 2; continue;
    }
    if (c === "/" && src[i + 1] === "/") { while (i < n && src[i] !== "\n") i++; continue; }
    if (c === "%") {
      const m = /^%([IQM])([XBWDL]?)(\d+)(?:\.(\d+))?/i.exec(src.slice(i));
      if (!m) throw E("syntax", "地址写法不对，例：%IX0.0、%QW2 / bad address, e.g. %IX0.0", line);
      push("addr", normAddr(m[0]), { line }); i += m[0].length; continue;
    }
    if (c === "'" || c === '"') {
      let j = i + 1, s = "";
      while (j < n && src[j] !== c) { if (src[j] === "$" && j + 1 < n) { const e = src[j + 1]; s += e === "N" || e === "n" ? "\n" : e === "T" || e === "t" ? "\t" : e; j += 2; } else s += src[j++]; }
      if (j >= n) throw E("syntax", "字符串没有结束 / unterminated string", line);
      push("str", s); i = j + 1; continue;
    }
    const rest = src.slice(i);
    let m = /^(?:T|TIME|LT|LTIME)#(-?[\d_.]+(?:d|h|ms|m|s|us|ns)(?:_?[\d_.]+(?:d|h|ms|m|s|us|ns))*)/i.exec(rest);
    if (m) { push("time", parseTime(m[1], line)); i += m[0].length; continue; }
    m = /^(\d+)#([0-9A-Fa-f_]+)/.exec(rest);
    if (m) { push("num", parseInt(m[2].replace(/_/g, ""), +m[1])); i += m[0].length; continue; }
    m = /^([A-Za-z]+)#(-?[\d_.]+(?:[eE][-+]?\d+)?|TRUE|FALSE)/i.exec(rest);
    if (m && (INT_TYPES[m[1].toUpperCase()] || REAL_TYPES.has(m[1].toUpperCase()) || m[1].toUpperCase() === "BOOL")) {
      const v = m[2].toUpperCase() === "TRUE" ? 1 : m[2].toUpperCase() === "FALSE" ? 0 : +m[2].replace(/_/g, "");
      push("num", v, { typed: m[1].toUpperCase() }); i += m[0].length; continue;
    }
    m = /^\d[\d_]*(\.\d[\d_]*)?([eE][-+]?\d+)?/.exec(rest);
    if (m) { push("num", +m[0].replace(/_/g, ""), { real: !!(m[1] || m[2]) }); i += m[0].length; continue; }
    m = /^[A-Za-z_][A-Za-z0-9_]*/.exec(rest);
    if (m) {
      const up = m[0].toUpperCase();
      if (KEYWORDS.has(up)) push("kw", up); else push("id", m[0]);
      i += m[0].length; continue;
    }
    m = /^(:=|=>|<>|<=|>=|\*\*|\.\.|[-+*/=<>()[\],;:.&#^])/.exec(rest);
    if (m) { push("op", m[0]); i += m[0].length; continue; }
    throw E("syntax", `不认识的字符 “${c}” / unexpected character '${c}'`, line);
  }
  push("eof", null);
  return out;
}

function normAddr(a) {
  const m = /^%([IQM])([XBWDL]?)(\d+)(?:\.(\d+))?$/i.exec(a);
  let size = (m[2] || "").toUpperCase();
  if (!size) size = m[4] != null ? "X" : "X";
  return "%" + m[1].toUpperCase() + size + m[3] + (m[4] != null ? "." + m[4] : "");
}

function parseTime(s, line) {
  let ms = 0;
  const neg = s.startsWith("-");
  const re = /([\d.]+)(d|h|ms|m|s|us|ns)/gi;
  let m, any = false;
  s = s.replace(/_/g, "");
  while ((m = re.exec(s))) {
    any = true;
    const v = +m[1], u = m[2].toLowerCase();
    ms += v * { d: 86400000, h: 3600000, m: 60000, s: 1000, ms: 1, us: 0.001, ns: 1e-6 }[u];
  }
  if (!any) throw E("syntax", "时间常量写法：T#2s、T#1m30s、T#500ms / time literal like T#2s", line);
  return neg ? -ms : ms;
}

function fmtTime(ms) {
  if (ms === 0) return "T#0ms";
  const neg = ms < 0; ms = Math.abs(ms);
  const parts = [];
  const units = [["d", 86400000], ["h", 3600000], ["m", 60000], ["s", 1000]];
  for (const [u, k] of units) { const q = Math.floor(ms / k + 1e-9); if (q) { parts.push(q + u); ms -= q * k; } }
  if (ms > 1e-6) parts.push((Math.round(ms * 1000) / 1000) + "ms");
  return (neg ? "T#-" : "T#") + parts.join("");
}

// ---------------------------------------------------------------- parser
function Parser(src) {
  const toks = lex(src);
  let p = 0;
  const peek = (k = 0) => toks[p + k];
  const next = () => toks[p++];
  const is = (t, v) => { const k = toks[p]; return k.t === t && (v == null || k.v === v); };
  const isKw = (...vs) => toks[p].t === "kw" && vs.includes(toks[p].v);
  const accept = (t, v) => (is(t, v) ? next() : null);
  const expect = (t, v, what) => {
    if (is(t, v)) return next();
    const k = toks[p];
    throw E("syntax", `这里应该是 ${what || v || t}，实际是 “${k.v == null ? "文件结尾" : k.v}” / expected ${what || v || t}, found '${k.v == null ? "end of file" : k.v}'`, k.line);
  };
  const ident = (what) => {
    const k = toks[p];
    if (k.t === "id") { p++; return k.v; }
    throw E("syntax", `这里应该是名字（${what || "标识符"}），实际是 “${k.v}” / expected a name`, k.line);
  };

  function typeSpec() {
    if (accept("kw", "ARRAY")) {
      expect("op", "[");
      const dims = [];
      do {
        const lo = constInt(); expect("op", ".."); const hi = constInt();
        dims.push([lo, hi]);
      } while (accept("op", ","));
      expect("op", "]"); expect("kw", "OF");
      return { array: dims, of: typeSpec() };
    }
    const name = ident("类型 type").toUpperCase();
    if ((name === "STRING" || name === "WSTRING") && accept("op", "[")) { constInt(); expect("op", "]"); }
    return { name };
  }
  function constInt() {
    const neg = !!accept("op", "-");
    const k = expect("num", null, "整数 integer");
    return neg ? -k.v : k.v;
  }

  function varSection(kind) {
    const vars = [];
    const flags = {};
    while (isKw("RETAIN", "NON_RETAIN", "CONSTANT")) flags[next().v] = true;
    while (!is("kw", "END_VAR")) {
      const line = peek().line;
      const names = [ident("变量名 variable")];
      while (accept("op", ",")) names.push(ident("变量名 variable"));
      let addr = null;
      if (accept("kw", "AT")) addr = expect("addr", null, "地址 address").v;
      expect("op", ":");
      const type = typeSpec();
      let init = null;
      if (accept("op", ":=")) init = initValue();
      expect("op", ";");
      names.forEach((nm) => vars.push({ name: nm, type, init, addr, kind, retain: !!flags.RETAIN, constant: !!flags.CONSTANT, line }));
    }
    expect("kw", "END_VAR");
    return vars;
  }
  function initValue() {
    if (accept("op", "[")) {
      const items = [];
      if (!is("op", "]")) do {
        // n(value) repetition
        if (is("num") && peek(1).t === "op" && peek(1).v === "(") {
          const cnt = next().v; next(); const v = expr(); expect("op", ")");
          for (let k = 0; k < cnt; k++) items.push(v);
        } else items.push(initValue());
      } while (accept("op", ","));
      expect("op", "]");
      return { k: "arr", items };
    }
    if (is("op", "(") && peek(1).t === "id" && peek(2).t === "op" && peek(2).v === ":=") {
      next();
      const fields = {};
      do { const f = ident(); expect("op", ":="); fields[f] = initValue(); } while (accept("op", ","));
      expect("op", ")");
      return { k: "struct", fields };
    }
    return expr();
  }

  function typeDecl() {
    const types = {};
    while (!is("kw", "END_TYPE")) {
      const name = ident("类型名 type name");
      expect("op", ":");
      if (accept("kw", "STRUCT")) {
        const fields = [];
        while (!is("kw", "END_STRUCT")) {
          const fl = [ident("成员 field")];
          while (accept("op", ",")) fl.push(ident());
          expect("op", ":");
          const t = typeSpec();
          let init = null;
          if (accept("op", ":=")) init = initValue();
          expect("op", ";");
          fl.forEach((f) => fields.push({ name: f, type: t, init }));
        }
        expect("kw", "END_STRUCT"); accept("op", ";");
        types[name.toUpperCase()] = { struct: fields, name };
      } else if (accept("op", "(")) {
        const vals = [];
        let k = 0;
        do {
          const v = ident("枚举值 enum value");
          if (accept("op", ":=")) k = constInt();
          vals.push([v, k++]);
        } while (accept("op", ","));
        expect("op", ")");
        let init = null;
        if (accept("op", ":=")) init = ident();
        accept("op", ";");
        types[name.toUpperCase()] = { enumeration: vals, name, init };
      } else {
        const t = typeSpec();
        accept("op", ";");
        types[name.toUpperCase()] = { alias: t, name };
      }
    }
    expect("kw", "END_TYPE");
    return types;
  }

  // statements
  const atEnder = (enders) => (toks[p].t === "kw" && enders.includes(toks[p].v)) || (toks[p].t === "id" && enders.includes(toks[p].v.toUpperCase()));
  function stmts(...enders) {
    const out = [];
    while (!atEnder(enders) && !is("eof")) {
      if (accept("op", ";")) continue;
      out.push(stmt());
    }
    return out;
  }
  function stmt() {
    const k = peek(), line = k.line;
    if (accept("kw", "IF")) {
      const arms = [[expr(), (expect("kw", "THEN"), stmts("ELSIF", "ELSE", "END_IF"))]];
      while (accept("kw", "ELSIF")) { const c = expr(); expect("kw", "THEN"); arms.push([c, stmts("ELSIF", "ELSE", "END_IF")]); }
      let other = [];
      if (accept("kw", "ELSE")) other = stmts("END_IF");
      expect("kw", "END_IF"); accept("op", ";");
      return { s: "if", arms, other, line };
    }
    if (accept("kw", "CASE")) {
      const sel = expr(); expect("kw", "OF");
      const arms = [];
      let other = [];
      while (!isKw("ELSE", "END_CASE")) {
        const labels = [];
        do {
          const a = caseLabel();
          if (accept("op", "..")) labels.push([a, caseLabel()]); else labels.push([a, a]);
        } while (accept("op", ","));
        expect("op", ":");
        // statements until next label "x:" / "x..y:" / ELSE / END_CASE
        const body = [];
        while (!isKw("ELSE", "END_CASE") && !atCaseLabel()) { if (accept("op", ";")) continue; body.push(stmt()); }
        arms.push({ labels, body });
      }
      if (accept("kw", "ELSE")) other = stmts("END_CASE");
      expect("kw", "END_CASE"); accept("op", ";");
      return { s: "case", sel, arms, other, line };
    }
    if (accept("kw", "FOR")) {
      const v = ident("循环变量 loop variable"); expect("op", ":=");
      const from = expr(); expect("kw", "TO"); const to = expr();
      let by = null;
      if (accept("kw", "BY")) by = expr();
      expect("kw", "DO");
      const body = stmts("END_FOR"); expect("kw", "END_FOR"); accept("op", ";");
      return { s: "for", v, from, to, by, body, line };
    }
    if (accept("kw", "WHILE")) {
      const c = expr(); expect("kw", "DO");
      const body = stmts("END_WHILE"); expect("kw", "END_WHILE"); accept("op", ";");
      return { s: "while", c, body, line };
    }
    if (accept("kw", "REPEAT")) {
      const body = stmts("UNTIL"); expect("kw", "UNTIL"); const c = expr(); expect("kw", "END_REPEAT"); accept("op", ";");
      return { s: "repeat", c, body, line };
    }
    if (accept("kw", "EXIT")) { accept("op", ";"); return { s: "exit", line }; }
    if (accept("kw", "RETURN")) { accept("op", ";"); return { s: "return", line }; }
    // assignment or call
    const target = postfix(primaryName());
    if (accept("op", ":=")) {
      const v = expr(); expect("op", ";", "“;”");
      return { s: "assign", target, v, line };
    }
    if (target.e === "call") { expect("op", ";", "“;”"); return { s: "call", call: target, line }; }
    throw E("syntax", "语句应该是赋值（x := …;）或调用（fb(…);） / a statement is an assignment or a call", line);
  }
  function caseLabel() {
    if (is("id")) { const a = next().v; if (accept("op", "#")) return { e: "enumref", t: a, v: ident() }; return { e: "name", n: a, line: peek().line }; }
    const neg = !!accept("op", "-");
    const k = expect("num", null, "CASE 标号 label");
    return { e: "num", v: neg ? -k.v : k.v };
  }
  function atCaseLabel() {
    // label: number or name, optionally ..range, list separated by commas, then ':' (not ':=')
    let q = p;
    for (;;) {
      if (toks[q].t === "op" && toks[q].v === "-") q++;
      if (!(toks[q].t === "num" || toks[q].t === "id")) return false;
      q++;
      if (toks[q].t === "op" && toks[q].v === "#") { q += 2; }
      if (toks[q].t === "op" && toks[q].v === "..") { q++; if (toks[q].t === "op" && toks[q].v === "-") q++; q++; }
      if (toks[q].t === "op" && toks[q].v === ",") { q++; continue; }
      return toks[q].t === "op" && toks[q].v === ":";
    }
  }

  // expressions
  const BIN = [["OR"], ["XOR"], ["AND", "&"], ["=", "<>"], ["<", ">", "<=", ">="], ["+", "-"], ["*", "/", "MOD"], ["**"]];
  function expr(level = 0) {
    if (level === BIN.length) return unary();
    let a = expr(level + 1);
    for (;;) {
      const k = peek();
      const op = (k.t === "kw" || k.t === "op") && BIN[level].includes(k.v) ? k.v : null;
      if (!op) return a;
      next();
      const b = expr(level + 1);
      a = { e: "bin", op: op === "&" ? "AND" : op, a, b, line: k.line };
    }
  }
  function unary() {
    if (accept("kw", "NOT")) return { e: "not", a: unary() };
    if (accept("op", "-")) return { e: "neg", a: unary() };
    if (accept("op", "+")) return unary();
    return postfix(primary());
  }
  function primary() {
    const k = peek();
    if (k.t === "num") { next(); return { e: "num", v: k.v, real: k.real, typed: k.typed }; }
    if (k.t === "time") { next(); return { e: "time", v: k.v }; }
    if (k.t === "str") { next(); return { e: "str", v: k.v }; }
    if (accept("kw", "TRUE")) return { e: "bool", v: true };
    if (accept("kw", "FALSE")) return { e: "bool", v: false };
    if (k.t === "addr") { next(); return { e: "addr", a: k.v, line: k.line }; }
    if (accept("op", "(")) { const x = expr(); expect("op", ")"); return x; }
    if (k.t === "id") return primaryName();
    throw E("syntax", `表达式里不能出现 “${k.v == null ? "文件结尾" : k.v}” / unexpected '${k.v}' in an expression`, k.line);
  }
  function primaryName() {
    const k = peek();
    if (k.t === "addr") { next(); return { e: "addr", a: k.v, line: k.line }; }
    const n = ident();
    if (accept("op", "#")) return { e: "enumref", t: n, v: ident() };
    return { e: "name", n, line: k.line };
  }
  function postfix(x) {
    for (;;) {
      if (accept("op", ".")) {
        // bit access x.3
        if (is("num")) { x = { e: "bit", a: x, b: next().v }; continue; }
        x = { e: "field", a: x, f: ident("成员 member") };
        continue;
      }
      if (accept("op", "[")) {
        const idx = [expr()];
        while (accept("op", ",")) idx.push(expr());
        expect("op", "]");
        x = { e: "index", a: x, idx };
        continue;
      }
      if (is("op", "(") && (x.e === "name" || x.e === "field")) {
        next();
        const args = [];
        if (!is("op", ")")) do {
          if (is("id") && peek(1).t === "op" && (peek(1).v === ":=" || peek(1).v === "=>")) {
            const nm = next().v; const how = next().v;
            if (how === ":=") args.push({ name: nm, v: expr() });
            else args.push({ name: nm, out: postfix(primaryName()) });
          } else args.push({ v: expr() });
        } while (accept("op", ","));
        expect("op", ")");
        x = { e: "call", f: x, args, line: x.line };
        continue;
      }
      return x;
    }
  }

  // ---- textual SFC (IEC 61131-3 §6.7): INITIAL_STEP / STEP … END_STEP, TRANSITION FROM … TO … := cond; END_TRANSITION,
  // ACTION name: … END_ACTION. The words are not reserved (a variable may be called "step"): they count only here.
  const word = (k = 0) => (toks[p + k].t === "id" ? toks[p + k].v.toUpperCase() : null);
  function atSfc() {
    const w = word();
    if ((w === "STEP" || w === "INITIAL_STEP") && toks[p + 1].t === "id") return true;
    if (w === "TRANSITION" && (word(1) === "FROM" || (toks[p + 1].t === "id" && word(2) === "FROM"))) return true;
    if (w === "ACTION" && toks[p + 1].t === "id" && toks[p + 2].t === "op" && toks[p + 2].v === ":") return true;
    return false;
  }
  function expectWord(w) {
    if (word() === w) return next();
    const k = toks[p];
    throw E("syntax", `这里应该是 ${w}，实际是 “${k.v == null ? "文件结尾" : k.v}” / expected ${w}`, k.line);
  }
  function stepList() {
    if (accept("op", "(")) { const l = [ident("步 step")]; while (accept("op", ",")) l.push(ident("步 step")); expect("op", ")"); return l; }
    return [ident("步 step")];
  }
  function pouBody(end) {
    const body = [];
    let sfc = null;
    const S = () => sfc || (sfc = { steps: [], transitions: [], actions: {} });
    while (!is("kw", end) && !is("eof")) {
      if (accept("op", ";")) continue;
      if (!atSfc()) { body.push(stmt()); continue; }
      const line = peek().line, w = word();
      if (w === "STEP" || w === "INITIAL_STEP") {
        next();
        const name = ident("步名 step name"); expect("op", ":");
        const acts = [];
        while (word() !== "END_STEP") {
          if (is("eof")) throw E("syntax", "STEP 没有 END_STEP / STEP without END_STEP", line);
          const an = ident("动作名 action name"); expect("op", "(");
          const q = ident("限定符 qualifier").toUpperCase();
          if (!["N", "S", "R", "P", "L", "D", "P0", "P1"].includes(q)) throw E("syntax", `不支持的动作限定符 ${q}（N、S、R、P、L、D） / unsupported qualifier ${q}`, line);
          let t = null;
          if (accept("op", ",")) t = expr();
          expect("op", ")"); accept("op", ";");
          if ((q === "L" || q === "D") && !t) throw E("syntax", `限定符 ${q} 要给时间，如 ${an}(${q}, T#2s) / ${q} needs a time`, line);
          acts.push({ name: an, q, t });
        }
        next();
        S().steps.push({ name, initial: w === "INITIAL_STEP", acts, line });
      } else if (w === "TRANSITION") {
        next();
        let tname = null;
        if (word() !== "FROM") tname = ident();
        expectWord("FROM"); const from = stepList();
        expect("kw", "TO"); const to = stepList();
        expect("op", ":="); const cond = expr(); accept("op", ";");
        expectWord("END_TRANSITION");
        S().transitions.push({ name: tname, from, to, cond, line });
      } else {
        next();
        const name = ident(); expect("op", ":");
        const b = stmts("END_ACTION"); expectWord("END_ACTION");
        S().actions[name.toUpperCase()] = { name, body: b, line };
      }
    }
    return { body, sfc };
  }
  function pous() {
    const out = { pous: [], types: {}, globals: [] };
    while (!is("eof")) {
      if (accept("kw", "TYPE")) { Object.assign(out.types, typeDecl()); continue; }
      if (isKw("VAR_GLOBAL")) { next(); out.globals.push(...varSection("global")); continue; }
      const k = peek();
      let kind = null, end = null;
      if (accept("kw", "PROGRAM")) { kind = "program"; end = "END_PROGRAM"; }
      else if (accept("kw", "FUNCTION_BLOCK")) { kind = "fb"; end = "END_FUNCTION_BLOCK"; }
      else if (accept("kw", "FUNCTION")) { kind = "function"; end = "END_FUNCTION"; }
      else throw E("syntax", "程序应以 PROGRAM、FUNCTION_BLOCK、FUNCTION 或 TYPE 开头 / expected PROGRAM, FUNCTION_BLOCK, FUNCTION or TYPE", k.line);
      const name = ident("名字 name");
      let ret = null;
      if (kind === "function") { expect("op", ":"); ret = typeSpec(); }
      const vars = [];
      const SECTIONS = { VAR: "var", VAR_INPUT: "input", VAR_OUTPUT: "output", VAR_IN_OUT: "inout", VAR_EXTERNAL: "external", VAR_TEMP: "temp", VAR_GLOBAL: "global" };
      while (isKw(...Object.keys(SECTIONS))) { const s = next().v; vars.push(...varSection(SECTIONS[s])); }
      const { body, sfc } = pouBody(end);
      expect("kw", end);
      out.pous.push({ kind, name, ret, vars, body, sfc, line: k.line });
    }
    return out;
  }
  return { pous, expr, stmts: () => stmts() };
}

function parse(src) { return Parser(src).pous(); }

// an expression back to ST text (for SFC transition labels and the FBD view)
const PREC = { OR: 1, XOR: 2, AND: 3, "=": 4, "<>": 4, "<": 5, ">": 5, "<=": 5, ">=": 5, "+": 6, "-": 6, "*": 7, "/": 7, MOD: 7, "**": 8 };
function exprText(x, outer = 0) {
  switch (x.e) {
    case "num": return x.typed ? `${x.typed}#${x.v}` : String(x.v);
    case "time": return fmtTime(x.v);
    case "str": return `'${x.v}'`;
    case "bool": return x.v ? "TRUE" : "FALSE";
    case "name": return x.n;
    case "addr": return x.a;
    case "enumref": return `${x.t}#${x.v}`;
    case "field": return `${exprText(x.a, 9)}.${x.f}`;
    case "bit": return `${exprText(x.a, 9)}.${x.b}`;
    case "index": return `${exprText(x.a, 9)}[${x.idx.map((i) => exprText(i)).join(", ")}]`;
    case "not": return `NOT ${exprText(x.a, 9)}`;
    case "neg": return `-${exprText(x.a, 9)}`;
    case "call": return `${exprText(x.f, 9)}(${x.args.map((a) => (a.name ? `${a.name} ${a.out ? "=>" : ":="} ${exprText(a.out || a.v)}` : exprText(a.v))).join(", ")})`;
    case "bin": { const p = PREC[x.op]; const t = `${exprText(x.a, p)} ${x.op} ${exprText(x.b, p + 1)}`; return p < outer ? `(${t})` : t; }
  }
  return "?";
}
function parseExpr(src) { const P = Parser(src); const x = P.expr(); return x; }

// ---------------------------------------------------------------- standard function blocks
// Each standard FB: inputs, outputs and a step(self, now) that runs once per call (time in ms).
const STD_FB = {
  TON: { in: { IN: "BOOL", PT: "TIME" }, out: { Q: "BOOL", ET: "TIME" },
    step(s, now) {
      if (!s.IN) { s.Q = false; s.ET = 0; s._t0 = null; return; }
      if (s._t0 == null) s._t0 = now;
      s.ET = Math.min(now - s._t0, s.PT); s.Q = now - s._t0 >= s.PT;
    } },
  TOF: { in: { IN: "BOOL", PT: "TIME" }, out: { Q: "BOOL", ET: "TIME" },
    step(s, now) {
      if (s.IN) { s.Q = true; s.ET = 0; s._t0 = null; return; }
      if (!s.Q) { s.ET = 0; return; }
      if (s._t0 == null) s._t0 = now;
      s.ET = Math.min(now - s._t0, s.PT);
      if (now - s._t0 >= s.PT) { s.Q = false; }
    } },
  TP: { in: { IN: "BOOL", PT: "TIME" }, out: { Q: "BOOL", ET: "TIME" },
    step(s, now) {
      if (s._t0 == null && s.IN && !s._last) { s._t0 = now; s.Q = true; }
      if (s._t0 != null) {
        s.ET = Math.min(now - s._t0, s.PT);
        if (now - s._t0 >= s.PT) { s.Q = false; if (!s.IN) { s._t0 = null; s.ET = 0; } }
      } else s.ET = 0;
      s._last = s.IN;
    } },
  CTU: { in: { CU: "BOOL", R: "BOOL", PV: "INT" }, out: { Q: "BOOL", CV: "INT" },
    step(s) {
      if (s.R) s.CV = 0; else if (s.CU && !s._last && s.CV < 32767) s.CV++;
      s._last = s.CU; s.Q = s.CV >= s.PV;
    } },
  CTD: { in: { CD: "BOOL", LD: "BOOL", PV: "INT" }, out: { Q: "BOOL", CV: "INT" },
    step(s) {
      if (s.LD) s.CV = s.PV; else if (s.CD && !s._last && s.CV > -32768) s.CV--;
      s._last = s.CD; s.Q = s.CV <= 0;
    } },
  CTUD: { in: { CU: "BOOL", CD: "BOOL", R: "BOOL", LD: "BOOL", PV: "INT" }, out: { QU: "BOOL", QD: "BOOL", CV: "INT" },
    step(s) {
      if (s.R) s.CV = 0;
      else if (s.LD) s.CV = s.PV;
      else {
        const up = s.CU && !s._lu, dn = s.CD && !s._ld;
        if (up && !dn && s.CV < 32767) s.CV++;
        else if (dn && !up && s.CV > -32768) s.CV--;
      }
      s._lu = s.CU; s._ld = s.CD; s.QU = s.CV >= s.PV; s.QD = s.CV <= 0;
    } },
  R_TRIG: { in: { CLK: "BOOL" }, out: { Q: "BOOL" }, step(s) { s.Q = s.CLK && !s._m; s._m = s.CLK; } },
  F_TRIG: { in: { CLK: "BOOL" }, out: { Q: "BOOL" }, step(s) { s.Q = !s.CLK && !!s._m; s._m = s.CLK; } },
  SR: { in: { S1: "BOOL", R: "BOOL" }, out: { Q1: "BOOL" }, step(s) { s.Q1 = s.S1 || (!s.R && s.Q1); } },
  RS: { in: { S: "BOOL", R1: "BOOL" }, out: { Q1: "BOOL" }, step(s) { s.Q1 = !s.R1 && (s.S || s.Q1); } },
};
// the 'CTU_DINT' style names of some vendors map to the same blocks
["CTU_DINT", "CTU_UDINT", "CTU_LINT"].forEach((k) => { STD_FB[k] = STD_FB.CTU; });

// standard functions: (args array, types) -> value
const num = (x) => (typeof x === "boolean" ? (x ? 1 : 0) : +x);
const STD_FN = {
  ABS: (a) => Math.abs(num(a[0])), SQRT: (a) => Math.sqrt(num(a[0])), LN: (a) => Math.log(num(a[0])), LOG: (a) => Math.log10(num(a[0])),
  EXP: (a) => Math.exp(num(a[0])), SIN: (a) => Math.sin(num(a[0])), COS: (a) => Math.cos(num(a[0])), TAN: (a) => Math.tan(num(a[0])),
  ASIN: (a) => Math.asin(num(a[0])), ACOS: (a) => Math.acos(num(a[0])), ATAN: (a) => Math.atan(num(a[0])),
  EXPT: (a) => Math.pow(num(a[0]), num(a[1])),
  MIN: (a) => Math.min(...a.map(num)), MAX: (a) => Math.max(...a.map(num)),
  LIMIT: (a) => Math.min(Math.max(num(a[1]), num(a[0])), num(a[2])),
  SEL: (a) => (a[0] ? a[2] : a[1]), MUX: (a) => a[1 + Math.max(0, Math.min(a.length - 2, num(a[0])))],
  MOVE: (a) => a[0], TRUNC: (a) => Math.trunc(num(a[0])),
  SHL: (a) => num(a[0]) * 2 ** num(a[1]), SHR: (a) => Math.floor(num(a[0]) / 2 ** num(a[1])),
  LEN: (a) => String(a[0]).length, CONCAT: (a) => a.map(String).join(""),
  LEFT: (a) => String(a[0]).slice(0, num(a[1])), RIGHT: (a) => (num(a[1]) ? String(a[0]).slice(-num(a[1])) : ""),
  MID: (a) => String(a[0]).substr(num(a[2]) - 1, num(a[1])), FIND: (a) => String(a[0]).indexOf(String(a[1])) + 1,
};
// conversions: X_TO_Y and TO_Y
const CONV_TARGETS = ["BOOL", "TIME", "STRING", ...Object.keys(INT_TYPES), ...REAL_TYPES];
function conversion(name) {
  const m = /^(?:([A-Z]+)_)?TO_([A-Z]+)$/.exec(name);
  if (!m || !CONV_TARGETS.includes(m[2])) return null;
  const to = m[2];
  return (a) => {
    let v = a[0];
    if (to === "STRING") return typeof v === "boolean" ? (v ? "TRUE" : "FALSE") : m[1] === "TIME" ? fmtTime(v) : String(v);
    if (typeof v === "string") v = /^T#/i.test(v) ? parseTime(v.slice(2)) : v.toUpperCase() === "TRUE" ? 1 : +v;
    if (INT_TYPES[to]) { const x = m[1] && REAL_TYPES.has(m[1]) ? Math.round(num(v)) : Math.trunc(num(v)); return wrapInt(x, to); }
    return coerce(v, to);
  };
}

// ---------------------------------------------------------------- compiler
// A compiled project: { programs: [names], run(env) per scan }. Values live in plain objects; FB instances are objects
// with their inputs/outputs/locals as fields; arrays are JS arrays with an offset (lower bound) recorded in the type.

class Ctx {
  constructor(project, env) { this.project = project; this.env = env; }
}

function compile(src, opts = {}) {
  const ast = typeof src === "string" ? parse(src) : src;
  const types = Object.assign({}, ast.types);
  // SFC steps are variables of a built-in structure: S1.X (active) and S1.T (time since activation)
  types.__SFCSTEP = { name: "__SFCSTEP", struct: [{ name: "X", type: { name: "BOOL" } }, { name: "T", type: { name: "TIME" } }] };
  for (const u of ast.pous) {
    if (!u.sfc) continue;
    const sf = u.sfc;
    if (!sf.steps.some((x) => x.initial)) throw E("semantic", `${u.name}：顺序功能图要有一个 INITIAL_STEP（初始步） / the SFC needs an INITIAL_STEP`, u.line);
    const names = new Set();
    for (const st of sf.steps) {
      const k = st.name.toUpperCase();
      if (names.has(k)) throw E("semantic", `步 ${st.name} 重复了 / step ${st.name} is defined twice`, st.line);
      names.add(k);
      if (u.vars.some((v) => v.name.toUpperCase() === k)) throw E("semantic", `步名 ${st.name} 与变量重名 / step ${st.name} has the name of a variable`, st.line);
      u.vars.push({ name: st.name, type: { name: "__SFCSTEP" }, kind: "var", line: st.line, step: true, initial: st.initial });
    }
    for (const t of sf.transitions) for (const n of t.from.concat(t.to))
      if (!names.has(n.toUpperCase())) throw E("semantic", `转移引用了不存在的步 ${n} / the transition names an unknown step ${n}`, t.line);
    for (const st of sf.steps) for (const a of st.acts)
      if (!sf.actions[a.name.toUpperCase()] && !u.vars.some((v) => v.name.toUpperCase() === a.name.toUpperCase()) &&
          !(ast.globals.some((g) => g.name.toUpperCase() === a.name.toUpperCase()) || (opts.io || []).some((x) => x.name.toUpperCase() === a.name.toUpperCase())))
        throw E("semantic", `动作 ${a.name} 既不是 ACTION，也不是布尔变量 / action ${a.name} is neither an ACTION nor a BOOL variable`, st.line);
  }
  const pous = {};
  for (const u of ast.pous) {
    const k = u.name.toUpperCase();
    if (pous[k] || STD_FB[k] || STD_FN[k]) throw E("semantic", `名字 ${u.name} 重复了 / ${u.name} is defined twice`, u.line);
    pous[k] = u;
  }
  const enumOf = {};
  for (const [tn, t] of Object.entries(types)) if (t.enumeration) for (const [v, k] of t.enumeration) enumOf[v.toUpperCase()] = { t: tn, k };

  const resolve = (t) => {
    if (t.array) return t;
    let n = t.name;
    while (types[n] && types[n].alias) { t = types[n].alias; if (t.array) return t; n = t.name; }
    return { name: n };
  };
  const typeName = (t) => (t.array ? "ARRAY" : resolve(t).name);

  // default value for a type
  function defaultValue(t, init, scope) {
    t = resolve(t);
    if (t.array) {
      const [lo, hi] = t.array[0];
      const rest = t.array.length > 1 ? { array: t.array.slice(1), of: t.of } : t.of;
      const items = init && init.k === "arr" ? init.items : null;
      const arr = [];
      for (let i = lo; i <= hi; i++) arr.push(defaultValue(rest, items ? items[i - lo] : null, scope));
      arr._lo = lo;
      return arr;
    }
    const n = t.name;
    if (ELEMENTARY.has(n)) {
      if (init && init.k == null) return coerce(constEval(init, scope), n);
      return n === "BOOL" ? false : n === "STRING" || n === "WSTRING" ? "" : 0;
    }
    if (types[n] && types[n].struct) {
      const o = {};
      for (const f of types[n].struct) {
        const fi = init && init.k === "struct" ? init.fields[f.name] : f.init;
        o[f.name.toUpperCase()] = defaultValue(f.type, fi, scope);
      }
      o._type = n;
      return o;
    }
    if (types[n] && types[n].enumeration) {
      if (init && init.e === "name") { const r = enumOf[init.n.toUpperCase()]; if (r) return r.k; }
      if (init && init.e === "enumref") return enumValue(init.t, init.v);
      if (types[n].init) return enumOf[types[n].init.toUpperCase()].k;
      return types[n].enumeration[0][1];
    }
    if (STD_FB[n]) return newStdFb(n);
    if (pous[n] && pous[n].kind === "fb") return newFb(pous[n], init);
    throw E("semantic", `不认识的类型 ${n} / unknown type ${n}`);
  }
  function enumValue(t, v) {
    const T = types[t.toUpperCase()];
    if (!T || !T.enumeration) throw E("semantic", `没有枚举类型 ${t} / no enum type ${t}`);
    const f = T.enumeration.find(([x]) => x.toUpperCase() === v.toUpperCase());
    if (!f) throw E("semantic", `${t} 里没有 ${v} / ${t} has no value ${v}`);
    return f[1];
  }
  function constEval(x, scope) {
    switch (x.e) {
      case "num": return x.v;
      case "time": return x.v;
      case "str": return x.v;
      case "bool": return x.v;
      case "neg": return -constEval(x.a, scope);
      case "enumref": return enumValue(x.t, x.v);
      case "name": {
        const r = enumOf[x.n.toUpperCase()];
        if (r) return r.k;
        const c = scope && scope.consts && scope.consts[x.n.toUpperCase()];
        if (c != null) return c;
        if (x.n.toUpperCase() === "TRUE") return true;
        throw E("semantic", `初值里不能用变量 ${x.n} / initial values must be constants`, x.line);
      }
      case "bin": {
        const a = constEval(x.a, scope), b = constEval(x.b, scope);
        return { "+": a + b, "-": a - b, "*": a * b, "/": a / b }[x.op];
      }
      default: throw E("semantic", "初值必须是常量 / initial values must be constants");
    }
  }
  function newStdFb(n) {
    const d = STD_FB[n];
    const o = { _std: n };
    for (const [k, t] of Object.entries(d.in)) o[k] = t === "BOOL" ? false : 0;
    for (const [k, t] of Object.entries(d.out)) o[k] = t === "BOOL" ? false : 0;
    return o;
  }
  function newFb(u, init) {
    const o = { _fb: u.name.toUpperCase() };
    for (const v of u.vars) {
      if (v.kind === "external" || v.kind === "temp") continue;
      const fi = init && init.k === "struct" ? init.fields[v.name] : v.init;
      o[v.name.toUpperCase()] = defaultValue(v.type, fi, null);
      if (v.step) Object.assign(o[v.name.toUpperCase()], { X: !!v.initial, T: 0, _t0: 0, _new: !!v.initial });
    }
    return o;
  }

  // ---- code generation: closures
  // scope: { vars: {NAME: {where: 'local'|'global'|'io', type, addr, kind}}, pou }
  const compiled = {};
  function compilePou(u) {
    const key = u.name.toUpperCase();
    if (compiled[key]) return compiled[key];
    const scope = { pou: u, vars: {}, consts: {} };
    for (const v of u.vars) {
      const nm = v.name.toUpperCase();
      if (scope.vars[nm]) throw E("semantic", `变量 ${v.name} 声明了两次 / ${v.name} declared twice`, v.line);
      scope.vars[nm] = v;
      if (v.constant && v.init) try { scope.consts[nm] = constEval(v.init, scope); } catch (e) { /* not constant */ }
    }
    if (u.kind === "function") scope.vars[key] = { name: u.name, type: u.ret, kind: "var", line: u.line };
    const c = { pou: u, scope, body: null };
    compiled[key] = c;
    c.body = block(u.body, scope);
    if (u.sfc) { const st = block([], scope); const run = sfcRunner(u, scope); const b0 = c.body; c.body = (f) => { const r = b0(f); run(f); return r; }; void st; }
    return c;
  }

  // the runtime frame: frame.self (instance object of this POU), env (globals, image, time, budget)
  function lookupVar(name, scope, line) {
    const nm = name.toUpperCase();
    const v = scope.vars[nm];
    if ((v || globalsByName[nm]) && enumOf[nm])
      throw E("semantic", `${name} 既是变量又是枚举值，会混淆；把变量改名，或写成 ${types[enumOf[nm].t].name}#${name} / ${name} is both a variable and an enum value: rename the variable or write ${types[enumOf[nm].t].name}#${name}`, line);
    if (v && v.kind !== "external") return { kind: "local", v };
    if (globalsByName[nm]) return { kind: "global", v: globalsByName[nm] };
    if (v && v.kind === "external") throw E("semantic", `VAR_EXTERNAL ${name} 没有对应的全局变量 / no global ${name}`, line);
    if (enumOf[nm]) return { kind: "enum", k: enumOf[nm].k };
    throw E("semantic", `变量 ${name} 没有声明 / ${name} is not declared`, line);
  }

  // A reference compiles to {get(f), set(f, v), type}
  function ref(x, scope) {
    switch (x.e) {
      case "name": {
        const r = lookupVar(x.n, scope, x.line);
        if (r.kind === "enum") return { get: () => r.k, set: () => { throw E("runtime", "枚举值不能赋值 / cannot assign an enum value", x.line); }, type: { name: "INT" } };
        const v = r.v, nm = v.name.toUpperCase(), t = v.type;
        if (v.addr) {
          const a = v.addr;
          return { get: (f) => f.env.read(a), set: (f, val) => f.env.write(a, coerce(val, typeName(t))), type: t, v };
        }
        if (r.kind === "global") return { get: (f) => f.env.globals[nm], set: (f, val) => { f.env.globals[nm] = store(val, t); }, type: t, v };
        if (v.kind === "inout") return { get: (f) => f.self[nm].get(), set: (f, val) => f.self[nm].set(store(val, t)), type: t, v };
        return { get: (f) => f.self[nm], set: (f, val) => { f.self[nm] = store(val, t); }, type: t, v };
      }
      case "addr": {
        const a = x.a;
        const t = { name: { X: "BOOL", B: "BYTE", W: "WORD", D: "DWORD", L: "LWORD" }[a[2]] };
        return { get: (f) => f.env.read(a), set: (f, val) => f.env.write(a, coerce(val, t.name)), type: t };
      }
      case "field": {
        const base = ref(x.a, scope);
        const F = x.f.toUpperCase();
        const bt = base.type ? resolve(base.type) : null;
        let ft = null;
        if (bt && bt.name) {
          if (STD_FB[bt.name]) { const d = STD_FB[bt.name]; const ty = d.in[F] || d.out[F]; if (!ty) throw E("semantic", `${bt.name} 没有 ${x.f} / ${bt.name} has no ${x.f}`, x.a.line); ft = { name: ty }; }
          else if (types[bt.name] && types[bt.name].struct) { const fd = types[bt.name].struct.find((q) => q.name.toUpperCase() === F); if (!fd) throw E("semantic", `结构 ${bt.name} 没有成员 ${x.f}`, x.a.line); ft = fd.type; }
          else if (pous[bt.name] && pous[bt.name].kind === "fb") { const vd = pous[bt.name].vars.find((q) => q.name.toUpperCase() === F); if (!vd) throw E("semantic", `功能块 ${bt.name} 没有 ${x.f} / FB ${bt.name} has no ${x.f}`, x.a.line); ft = vd.type; }
        }
        return { get: (f) => base.get(f)[F], set: (f, val) => { base.get(f)[F] = ft ? store(val, ft) : val; }, type: ft };
      }
      case "index": {
        const base = ref(x.a, scope);
        const idx = x.idx.map((i) => expr(i, scope));
        let t = base.type ? resolve(base.type) : null;
        let et = null;
        if (t && t.array) et = t.array.length > x.idx.length ? { array: t.array.slice(x.idx.length), of: t.of } : t.of;
        const at = (f) => {
          let a = base.get(f);
          for (let k = 0; k < idx.length - 1; k++) a = a[ix(a, idx[k](f), x)];
          return a;
        };
        return { get: (f) => { const a = at(f); return a[ix(a, idx[idx.length - 1](f), x)]; },
          set: (f, val) => { const a = at(f); a[ix(a, idx[idx.length - 1](f), x)] = et ? store(val, et) : val; }, type: et };
      }
      case "bit": {
        const base = ref(x.a, scope);
        const b = x.b;
        return { get: (f) => !!((num(base.get(f)) >> b) & 1),
          set: (f, val) => { const w = num(base.get(f)); base.set(f, val ? (w | (1 << b)) : (w & ~(1 << b))); }, type: { name: "BOOL" } };
      }
      default:
        throw E("semantic", "只能给变量赋值 / only variables can be assigned", x.line);
    }
  }
  function ix(a, i, x) {
    const k = i - (a._lo || 0);
    if (!(k >= 0 && k < a.length)) throw E("runtime", `数组下标越界：${i} / array index ${i} out of range`, x.line || (x.a && x.a.line));
    return k;
  }
  function store(val, t) {
    const r = resolve(t);
    if (r.array) return val;
    if (ELEMENTARY.has(r.name)) return coerce(val, r.name);
    if (types[r.name] && types[r.name].enumeration) return num(val);
    return val;
  }

  function isRealType(t) { const r = t && resolve(t); return !!(r && r.name && REAL_TYPES.has(r.name)); }
  function exprType(x, scope) {
    try {
      if (x.e === "num") return x.typed ? { name: x.typed } : x.real ? { name: "LREAL" } : { name: "DINT" };
      if (x.e === "time") return { name: "TIME" };
      if (x.e === "bool" || x.e === "not") return { name: "BOOL" };
      if (["name", "field", "index", "addr", "bit"].includes(x.e)) return ref(x, scope).type;
      if (x.e === "bin") {
        if (["=", "<>", "<", ">", "<=", ">=", "AND", "OR", "XOR"].includes(x.op)) {
          if (["AND", "OR", "XOR"].includes(x.op)) return exprType(x.a, scope);
          return { name: "BOOL" };
        }
        const a = exprType(x.a, scope), b = exprType(x.b, scope);
        if (isRealType(a) || isRealType(b) || x.op === "**") return { name: "LREAL" };
        if (a && resolve(a).name === "TIME") return { name: "TIME" };
        return a || b;
      }
      if (x.e === "neg") return exprType(x.a, scope);
    } catch (e) { return null; }
    return null;
  }

  function expr(x, scope) {
    switch (x.e) {
      case "num": { const v = x.v; return () => v; }
      case "time": { const v = x.v; return () => v; }
      case "str": { const v = x.v; return () => v; }
      case "bool": { const v = x.v; return () => v; }
      case "enumref": { const v = enumValue(x.t, x.v); return () => v; }
      case "not": {
        const a = expr(x.a, scope);
        const t = exprType(x.a, scope);
        const tn = t && resolve(t).name;
        if (tn && INT_TYPES[tn]) return (f) => wrapInt(~num(a(f)) >>> 0, tn);
        return (f) => !a(f);
      }
      case "neg": { const a = expr(x.a, scope); return (f) => -num(a(f)); }
      case "bin": {
        const a = expr(x.a, scope), b = expr(x.b, scope);
        const ta = exprType(x.a, scope), tb = exprType(x.b, scope);
        const realDiv = isRealType(ta) || isRealType(tb);
        const intType = (t) => { const r = t && resolve(t); return r && r.name && INT_TYPES[r.name] ? r.name : null; };
        const bitwise = intType(ta) && intType(tb);
        switch (x.op) {
          case "AND": return bitwise ? (f) => num(a(f)) & num(b(f)) : (f) => !!a(f) && !!b(f);
          case "OR": return bitwise ? (f) => num(a(f)) | num(b(f)) : (f) => !!a(f) || !!b(f);
          case "XOR": return bitwise ? (f) => num(a(f)) ^ num(b(f)) : (f) => !!a(f) !== !!b(f);
          case "=": return (f) => a(f) === b(f) || (typeof a(f) !== "string" && num(a(f)) === num(b(f)));
          case "<>": return (f) => !(a(f) === b(f) || (typeof a(f) !== "string" && num(a(f)) === num(b(f))));
          case "<": return (f) => num(a(f)) < num(b(f));
          case ">": return (f) => num(a(f)) > num(b(f));
          case "<=": return (f) => num(a(f)) <= num(b(f));
          case ">=": return (f) => num(a(f)) >= num(b(f));
          case "+": return (f) => { const p = a(f), q = b(f); return typeof p === "string" ? p + q : num(p) + num(q); };
          case "-": return (f) => num(a(f)) - num(b(f));
          case "*": return (f) => num(a(f)) * num(b(f));
          case "/": return realDiv ? (f) => num(a(f)) / num(b(f)) : (f) => {
            const q = num(b(f));
            if (q === 0) throw E("runtime", "除以零 / division by zero", x.line);
            const r = num(a(f)) / q;
            return (ta && resolve(ta).name === "TIME") ? r : Math.trunc(r);
          };
          case "MOD": return (f) => { const q = num(b(f)); if (q === 0) throw E("runtime", "MOD 除以零 / MOD by zero", x.line); return num(a(f)) % q; };
          case "**": return (f) => Math.pow(num(a(f)), num(b(f)));
        }
        throw E("semantic", "不支持的运算 " + x.op);
      }
      case "call": return callExpr(x, scope, true);
      default: { const r = ref(x, scope); return r.get; }
    }
  }

  function callExpr(x, scope, asValue) {
    const fname = x.f.e === "name" ? x.f.n.toUpperCase() : null;
    // function?
    if (fname && (STD_FN[fname] || conversion(fname))) {
      const fn = STD_FN[fname] || conversion(fname);
      const args = x.args.map((a) => expr(a.v, scope));
      return (f) => fn(args.map((g) => g(f)));
    }
    if (fname && pous[fname] && pous[fname].kind === "function") {
      const u = pous[fname];
      const c = () => compilePou(u);
      const ins = u.vars.filter((v) => v.kind === "input" || v.kind === "inout");
      const binds = bindArgs(x, ins, u.name, scope);
      return (f) => {
        const cp = c();
        const self = {};
        for (const v of u.vars) self[v.name.toUpperCase()] = defaultValue(v.type, v.init, cp.scope);
        self[u.name.toUpperCase()] = defaultValue(u.ret, null, cp.scope);
        for (const [v, g] of binds) self[v.name.toUpperCase()] = store(g(f), v.type);
        runBody(cp.body, { self, env: f.env });
        return self[u.name.toUpperCase()];
      };
    }
    // FB instance call: x.f is a variable (or field) holding an instance
    if (asValue) throw E("semantic", `${fname || "这个调用"} 是功能块，要先调用、再读输出（如 t1(IN:=x); y := t1.Q;） / call a function block as a statement, then read its outputs`, x.line);
    const inst = ref(x.f, scope);
    const it = inst.type ? resolve(inst.type).name : null;
    if (it && STD_FB[it]) {
      const d = STD_FB[it];
      const ins = [], outs = [];
      for (const a of x.args) {
        if (!a.name) throw E("semantic", `调用 ${it} 要写参数名，如 IN := x / name the inputs of ${it}`, x.line);
        const nm = a.name.toUpperCase();
        if (a.v) { if (!d.in[nm]) throw E("semantic", `${it} 没有输入 ${a.name} / ${it} has no input ${a.name}`, x.line); ins.push([nm, expr(a.v, scope), d.in[nm]]); }
        else { if (!d.out[nm]) throw E("semantic", `${it} 没有输出 ${a.name} / ${it} has no output ${a.name}`, x.line); outs.push([nm, ref(a.out, scope)]); }
      }
      return (f) => {
        const s = inst.get(f);
        for (const [k, g, t] of ins) s[k] = coerce(g(f), t);
        d.step(s, f.env.now);
        for (const [k, r] of outs) r.set(f, s[k]);
      };
    }
    if (it && pous[it] && pous[it].kind === "fb") {
      const u = pous[it];
      const ins = u.vars.filter((v) => v.kind === "input" || v.kind === "inout");
      const binds = bindArgs(x, ins, u.name, scope, true);
      const outs = x.args.filter((a) => a.out).map((a) => {
        const v = u.vars.find((q) => q.name.toUpperCase() === a.name.toUpperCase() && q.kind === "output");
        if (!v) throw E("semantic", `${u.name} 没有输出 ${a.name}`, x.line);
        return [v.name.toUpperCase(), ref(a.out, scope)];
      });
      const inouts = x.args.filter((a) => a.v && ins.find((v) => v.kind === "inout" && v.name.toUpperCase() === a.name.toUpperCase()))
        .map((a) => [a.name.toUpperCase(), ref(a.v, scope)]);
      return (f) => {
        const cp = compilePou(u);
        const s = inst.get(f);
        for (const [v, g] of binds) if (v.kind === "input") s[v.name.toUpperCase()] = store(g(f), v.type);
        for (const [k, r] of inouts) s[k] = { get: () => r.get(f), set: (val) => r.set(f, val) };
        for (const v of u.vars) if (v.kind === "temp") s[v.name.toUpperCase()] = defaultValue(v.type, v.init, cp.scope);
        runBody(cp.body, { self: s, env: f.env });
        for (const [k, r] of outs) r.set(f, s[k]);
      };
    }
    throw E("semantic", `${fname || "这个名字"} 不是函数，也不是功能块实例 / not a function or a function block instance`, x.line);
  }
  function bindArgs(x, ins, name, scope, named) {
    const out = [];
    x.args.forEach((a, k) => {
      if (a.out) return;
      let v;
      if (a.name) v = ins.find((q) => q.name.toUpperCase() === a.name.toUpperCase());
      else if (!named) v = ins[k];
      if (!v) throw E("semantic", `${name} 没有输入 ${a.name || "#" + (k + 1)}`, x.line);
      out.push([v, expr(a.v, scope)]);
    });
    return out;
  }

  // one SFC evolution per scan, as CODESYS does it: actions of the active steps, then the transitions that can fire
  // (all preceding steps active and the condition true; a step leaves by the first such transition in source order)
  function sfcRunner(u, scope) {
    const sf = u.sfc;
    const steps = sf.steps.map((st) => ({ k: st.name.toUpperCase(), acts: st.acts.map((a) => ({ an: a.name.toUpperCase(), q: a.q, t: a.t ? expr(a.t, scope) : null })) }));
    const trans = sf.transitions.map((t) => ({ from: t.from.map((n) => n.toUpperCase()), to: t.to.map((n) => n.toUpperCase()), cond: expr(t.cond, scope) }));
    const bodies = {};
    for (const [k, a] of Object.entries(sf.actions)) bodies[k] = block(a.body, scope);
    const names = [...new Set(steps.flatMap((s) => s.acts.map((a) => a.an)))];
    const refs = {};
    for (const n of names) if (!bodies[n]) refs[n] = ref({ e: "name", n, line: u.line }, scope);
    return (f) => {
      const now = f.env.now, self = f.self;
      const stored = self._sfcStored || (self._sfcStored = {});
      for (const st of steps) { const x = self[st.k]; if (x.X) x.T = now - x._t0; }
      const on = {};
      for (const st of steps) {
        const x = self[st.k];
        if (!x.X) continue;
        for (const a of st.acts) {
          const dt = now - x._t0;
          if (a.q === "N") on[a.an] = true;
          else if (a.q === "P" || a.q === "P1") { if (x._new) on[a.an] = true; }
          else if (a.q === "S") stored[a.an] = true;
          else if (a.q === "R") stored[a.an] = false;
          else if (a.q === "L") { if (dt < num(a.t(f))) on[a.an] = true; }
          else if (a.q === "D") { if (dt >= num(a.t(f))) on[a.an] = true; }
        }
      }
      for (const n of names) {
        const active = !!(on[n] || stored[n]);
        if (bodies[n]) { if (active) bodies[n](f); } else refs[n].set(f, active);
      }
      for (const st of steps) self[st.k]._new = false;
      const X0 = {};
      for (const st of steps) X0[st.k] = self[st.k].X;
      const taken = new Set(), fire = [];
      for (const t of trans) {
        if (t.from.every((n) => X0[n] && !taken.has(n)) && t.cond(f)) { t.from.forEach((n) => taken.add(n)); fire.push(t); }
      }
      for (const t of fire) for (const n of t.from) self[n].X = false;
      for (const t of fire) for (const n of t.to) Object.assign(self[n], { X: true, _t0: now, _new: true, T: 0 });
    };
  }

  const BREAK = { exit: true }, RET = { ret: true };
  function block(list, scope) {
    const fs = list.map((s) => stmt(s, scope));
    return (f) => { for (let k = 0; k < fs.length; k++) { const r = fs[k](f); if (r) return r; } return null; };
  }
  function tick(f, line) {
    if (++f.env.steps > f.env.budget) throw E("watchdog", `看门狗：一次扫描执行了太多步（第 ${line} 行附近的循环没有结束？） / watchdog: the scan did not finish (loop near line ${line})`, line);
  }
  function stmt(s, scope) {
    const line = s.line;
    switch (s.s) {
      case "assign": {
        const r = ref(s.target, scope), v = expr(s.v, scope);
        return (f) => { tick(f, line); r.set(f, v(f)); return null; };
      }
      case "call": { const c = callExpr(s.call, scope, false); return (f) => { tick(f, line); c(f); return null; }; }
      case "if": {
        const arms = s.arms.map(([c, b]) => [expr(c, scope), block(b, scope)]);
        const other = block(s.other, scope);
        return (f) => { tick(f, line); for (const [c, b] of arms) if (c(f)) return b(f); return other(f); };
      }
      case "case": {
        const sel = expr(s.sel, scope);
        const val = (l) => (l.e === "num" ? l.v : l.e === "enumref" ? enumValue(l.t, l.v) : constEval(l, scope));
        const arms = s.arms.map((a) => [a.labels.map(([lo, hi]) => [val(lo), val(hi)]), block(a.body, scope)]);
        const other = block(s.other, scope);
        return (f) => {
          tick(f, line);
          const v = num(sel(f));
          for (const [ls, b] of arms) if (ls.some(([lo, hi]) => v >= lo && v <= hi)) return b(f);
          return other(f);
        };
      }
      case "for": {
        const r = ref({ e: "name", n: s.v, line }, scope);
        const from = expr(s.from, scope), to = expr(s.to, scope), by = s.by ? expr(s.by, scope) : () => 1;
        const body = block(s.body, scope);
        return (f) => {
          const end = num(to(f)), step = num(by(f));
          if (step === 0) throw E("runtime", "FOR 的步长不能为 0 / FOR step is 0", line);
          r.set(f, from(f));
          for (;;) {
            tick(f, line);
            const i = num(r.get(f));
            if (step > 0 ? i > end : i < end) break;
            const res = body(f);
            if (res === BREAK) break;
            if (res === RET) return RET;
            r.set(f, num(r.get(f)) + step);
          }
          return null;
        };
      }
      case "while": {
        const c = expr(s.c, scope), body = block(s.body, scope);
        return (f) => { for (;;) { tick(f, line); if (!c(f)) break; const r = body(f); if (r === BREAK) break; if (r === RET) return RET; } return null; };
      }
      case "repeat": {
        const c = expr(s.c, scope), body = block(s.body, scope);
        return (f) => { for (;;) { tick(f, line); const r = body(f); if (r === BREAK) break; if (r === RET) return RET; if (c(f)) break; } return null; };
      }
      case "exit": return () => BREAK;
      case "return": return () => RET;
    }
    throw E("semantic", "不支持的语句");
  }
  function runBody(body, f) { body(f); }

  // globals: VAR_GLOBAL in the source plus the I/O table of the lab (symbol, address, type)
  const globalsByName = {};
  for (const g of ast.globals) globalsByName[g.name.toUpperCase()] = g;
  for (const io of opts.io || []) {
    const nm = io.name.toUpperCase();
    if (globalsByName[nm]) continue;
    globalsByName[nm] = { name: io.name, type: { name: io.type || (io.addr[2] === "X" ? "BOOL" : "INT") }, addr: normAddr(io.addr), kind: "global", io: true };
  }

  const programs = ast.pous.filter((u) => u.kind === "program");
  if (!programs.length && !opts.library) throw E("semantic", "至少要有一个 PROGRAM / the project needs a PROGRAM");
  // compile everything now so that errors show at once
  for (const u of ast.pous) compilePou(u);

  return {
    ast, types, pous, globals: globalsByName,
    programs: programs.map((u) => u.name),
    newState() {
      const st = { globals: {}, instances: {} };
      for (const [nm, g] of Object.entries(globalsByName)) if (!g.addr) st.globals[nm] = defaultValue(g.type, g.init, null);
      for (const u of programs) st.instances[u.name.toUpperCase()] = newFb(u, null);
      return st;
    },
    // one execution of every program (the scan's "execute" phase)
    execute(st, env) {
      env.globals = st.globals;
      for (const u of programs) {
        const c = compilePou(u);
        const self = st.instances[u.name.toUpperCase()];
        for (const v of u.vars) if (v.kind === "temp") self[v.name.toUpperCase()] = defaultValue(v.type, v.init, c.scope);
        c.body({ self, env });
      }
    },
    // read a variable by a dotted path, for the monitor: "Main.state", "motor", "Main.t1.ET"
    watch(st, env, path) { return watchPath(this, st, env, path); },
    compileExpr: (src, programName) => {
      const u = programName ? pous[programName.toUpperCase()] : programs[0];
      const c = compilePou(u);
      return expr(parseExpr(src), c.scope);
    },
    compileRef: (src, programName) => {
      const u = programName ? pous[programName.toUpperCase()] : programs[0];
      const c = compilePou(u);
      return ref(parseExpr(src), c.scope);
    },
    compileStmts: (list, programName) => {
      const u = programName ? pous[programName.toUpperCase()] : programs[0];
      const c = compilePou(u);
      return block(list, c.scope);
    },
    fbStep: (it) => STD_FB[it],
  };
}

function watchPath(proj, st, env, path) {
  const parts = path.split(".");
  let cur;
  const first = parts[0].toUpperCase();
  if (st.instances[first]) { cur = st.instances[first]; parts.shift(); }
  else if (proj.globals[first]) {
    const g = proj.globals[first];
    cur = g.addr ? env.read(g.addr) : st.globals[first];
    parts.shift();
  } else {
    const p0 = proj.programs[0].toUpperCase();
    cur = st.instances[p0];
  }
  for (const k of parts) {
    if (cur == null) return undefined;
    const m = /^(\w+)\[(\-?\d+)\]$/.exec(k);
    if (m) { cur = cur[m[1].toUpperCase()]; cur = cur && cur[+m[2] - (cur._lo || 0)]; }
    else cur = cur[k.toUpperCase()];
  }
  return cur;
}

// ---------------------------------------------------------------- ladder diagram
// A rung: { comment, cells: [[cell or null] per column] per row, links: [[row, col], ...] }.
// links: a vertical link between row r and row r+1 at the left edge of column c (c = 1 … cols; c = cols is the right end).
// Cells: {k:"NO"|"NC"|"P"|"N", v:"name"} contacts; {k:"CMP", x:"expr"} compare contact; {k:"WIRE"};
//        {k:"COIL"|"NCOIL"|"SET"|"RST", v:"name"}; {k:"FB", fb:"TON", inst:"t1", p:{PT:"T#2s"}} (IN or CU/CD/CLK from power,
//        output Q); {k:"ASSIGN", v:"target", x:"expr"} (executes when powered, passes power).
// Edge contacts P/N keep their previous value in the program instance (hidden variable per cell).
function compileLadder(proj, rungs, programName) {
  const prog = programName || proj.programs[0];
  const compiled = rungs.map((r, ri) => {
    const rows = r.cells.length, cols = Math.max(...r.cells.map((row) => row.length));
    const link = new Set((r.links || []).map(([a, c]) => a + ":" + c));
    const cellFns = r.cells.map((row, i) => row.map((cell, j) => cellFn(cell, ri, i, j)));
    return (f) => {
      // power at the left edge of each column; f.env.probe (the editor's live view) records it per rung
      const pr = f.env.probe ? (f.env.probe[ri] = { edge: Array.from({ length: rows }, () => new Array(cols + 1).fill(false)) }) : null;
      let edge = new Array(rows).fill(true);
      for (let c = 0; c <= cols; c++) {
        // merge vertical links at this edge (c ≥ 1): a linked group shares one node
        if (c >= 1) {
          let r0 = 0;
          while (r0 < rows) {
            let r1 = r0;
            while (r1 < rows - 1 && link.has(r1 + ":" + c)) r1++;
            if (r1 > r0) { let any = false; for (let k = r0; k <= r1; k++) any = any || edge[k]; for (let k = r0; k <= r1; k++) edge[k] = any; }
            r0 = r1 + 1;
          }
        }
        if (pr) for (let i = 0; i < rows; i++) pr.edge[i][c] = edge[i];
        if (c === cols) break;
        const nx = new Array(rows).fill(false);
        for (let i = 0; i < rows; i++) {
          const fn = cellFns[i][c];
          nx[i] = fn ? fn(f, edge[i]) : false;
        }
        edge = nx;
      }
    };
  });
  function cellFn(cell, ri, i, j) {
    if (!cell) return null;
    const key = `_ld${ri}_${i}_${j}`;
    switch (cell.k) {
      case "WIRE": return (f, p) => p;
      case "NO": { const g = proj.compileExpr(cell.v, prog); return (f, p) => p && !!g(f); }
      case "NC": { const g = proj.compileExpr(cell.v, prog); return (f, p) => p && !g(f); }
      case "P": { const g = proj.compileExpr(cell.v, prog); return (f, p) => { const v = !!g(f); const old = !!f.self[key]; f.self[key] = v; return p && v && !old; }; }
      case "N": { const g = proj.compileExpr(cell.v, prog); return (f, p) => { const v = !!g(f); const old = !!f.self[key]; f.self[key] = v; return p && !v && old; }; }
      case "CMP": { const g = proj.compileExpr(cell.x, prog); return (f, p) => p && !!g(f); }
      case "COIL": { const r = proj.compileRef(cell.v, prog); return (f, p) => { r.set(f, p); return p; }; }
      case "NCOIL": { const r = proj.compileRef(cell.v, prog); return (f, p) => { r.set(f, !p); return p; }; }
      case "SET": { const r = proj.compileRef(cell.v, prog); return (f, p) => { if (p) r.set(f, true); return p; }; }
      case "RST": { const r = proj.compileRef(cell.v, prog); return (f, p) => { if (p) r.set(f, false); return p; }; }
      case "ASSIGN": { const r = proj.compileRef(cell.v, prog); const g = proj.compileExpr(cell.x, prog); return (f, p) => { if (p) r.set(f, g(f)); return p; }; }
      case "FB": {
        const inst = proj.compileRef(cell.inst, prog);
        const d = STD_FB[cell.fb];
        if (!d) throw E("semantic", `梯形图里不支持的功能块 ${cell.fb} / unsupported block ${cell.fb}`);
        const powerIn = { TON: "IN", TOF: "IN", TP: "IN", CTU: "CU", CTD: "CD", R_TRIG: "CLK", F_TRIG: "CLK" }[cell.fb];
        const outName = { CTU: "Q", CTD: "Q" }[cell.fb] || "Q";
        const params = Object.entries(cell.p || {}).map(([k, src]) => [k.toUpperCase(), proj.compileExpr(String(src), prog), d.in[k.toUpperCase()]]);
        return (f, p) => {
          const s = inst.get(f);
          s[powerIn] = p;
          for (const [k, g, t] of params) s[k] = coerce(g(f), t);
          d.step(s, f.env.now);
          return !!s[outName];
        };
      }
    }
    throw E("semantic", `不认识的梯形图元件 ${cell.k} / unknown ladder element ${cell.k}`);
  }
  return compiled;
}

// ---------------------------------------------------------------- the runtime (a PLC)
// io: [{name, addr: "%IX0.0", type, dir: "in"|"out", comment}]. The plant (optional) reads outputs and writes inputs.
class Runtime {
  constructor(opts) {
    this.cycle = opts.cycle || 10;            // scan time setting, ms (the time one scan takes in the simulation)
    this.filter = opts.filter || 0;           // input filter, ms
    this.budget = opts.budget || 200000;      // statements per scan before the watchdog trips
    // scan time model (Ch. 4): a scan takes base ms + perStep µs per statement executed; "free" cycling starts the next scan at
    // once, "fixed" waits for the cycle time (a longer scan is an overrun). watchdog: ms per scan before the PLC stops.
    this.scanModel = opts.scanModel || null;
    this.cycleMode = opts.cycleMode || "fixed";
    this.watchdog = opts.watchdog || 0;
    this.lastScan = 0; this.minScan = Infinity; this.maxScan = 0; this.overruns = 0;
    this.io = (opts.io || []).map((x) => Object.assign({}, x, { addr: normAddr(x.addr) }));
    this.image = {};                          // the process image: "%IX0.0" -> value
    this.phys = {};                           // the physical inputs (before filtering)
    this.filt = {};                           // filter state per input: {v, since}
    this.forces = {};
    this.now = 0;
    this.scans = 0;
    this.trace = null;
    this.error = null;
    this.load(opts);
  }
  load(opts) {
    const src = opts.st || opts.decls || "";
    let text = src;
    if (opts.ladder && !/\bPROGRAM\b/i.test(text)) text = `PROGRAM Main\n${src}\nEND_PROGRAM`;
    this.project = compile(text, { io: this.io });
    this.state = this.project.newState();
    this.ladder = opts.ladder ? compileLadder(this.project, opts.ladder, this.project.programs[0]) : null;
    this.ladderCells = opts.ladder ? opts.ladder.reduce((n, r) => n + r.cells.reduce((m, row) => m + row.filter(Boolean).length, 0), 0) : 0;
    this.error = null;
  }
  read(a) {
    if (a in this.forces) return this.forces[a];
    if (a in this.image) return this.image[a];
    const m = /^%([IQM])([XBWDL])(\d+)(?:\.(\d+))?$/.exec(a);
    // a bit read of a word that was written as a word (e.g. %IX0.3 inside %IW0) is not modelled: separate cells
    return m && m[2] === "X" ? false : 0;
  }
  write(a, v) { this.image[a] = v; }
  setInput(name, v) {
    const io = this.io.find((x) => x.name === name || x.addr === name);
    if (!io) throw E("runtime", `没有输入 ${name}`);
    this.phys[io.addr] = v;
  }
  output(name) {
    const io = this.io.find((x) => x.name === name || x.addr === name);
    if (!io) throw E("runtime", `没有输出 ${name}`);
    return this.read(io.addr);
  }
  force(name, v) {
    const io = this.io.find((x) => x.name === name || x.addr === name);
    const a = io ? io.addr : normAddr(name);
    if (v === undefined || v === null) delete this.forces[a]; else this.forces[a] = v;
  }
  // one scan: input phase (with the filter), execute, output phase; time advances by one cycle
  scan() {
    if (this.error) return false;
    // input phase: the filter passes a change only after it has been stable for `filter` ms
    for (const io of this.io) {
      if (io.dir !== "in") continue;
      const a = io.addr;
      const v = this.phys[a] !== undefined ? this.phys[a] : (a[2] === "X" ? false : 0);
      if (this.filter > 0 && a[2] === "X") {
        const d0 = this.image[a] !== undefined ? this.image[a] : false;
        const f = this.filt[a] || (this.filt[a] = { v: d0, since: this.now, out: d0 });
        if (f.v !== v) { f.v = v; f.since = this.now; }
        if (this.now - f.since >= this.filter) f.out = v;
        this.image[a] = f.out;
      } else this.image[a] = v;
    }
    const env = { now: this.now, steps: 0, budget: this.budget, read: (a) => this.read(a), write: (a, v) => this.write(a, v), globals: null,
      probe: this.ladder ? (this.probe = []) : null };
    try {
      if (this.ladder) {
        const self = this.state.instances[this.project.programs[0].toUpperCase()];
        env.globals = this.state.globals;
        this.ladder.forEach((r) => r({ self, env }));
        env.steps += this.ladderCells || 0;
      } else this.project.execute(this.state, env);
      if (this.scanModel) {
        const t = (this.scanModel.base || 0) + env.steps * (this.scanModel.perStep || 0) / 1000;
        this.lastScan = t; this.minScan = Math.min(this.minScan, t); this.maxScan = Math.max(this.maxScan, t);
        if (this.watchdog && t > this.watchdog)
          throw E("watchdog", `看门狗：扫描时间 ${t.toFixed(1)} ms 超过了 ${this.watchdog} ms / watchdog: scan time ${t.toFixed(1)} ms exceeds ${this.watchdog} ms`, 0);
      }
    } catch (e) {
      this.error = e instanceof PlcError ? e : E("runtime", String(e.message || e));
      // a tripped watchdog (or any runtime error) puts the PLC in STOP: all outputs off
      for (const io of this.io) if (io.dir === "out") this.image[io.addr] = io.addr[2] === "X" ? false : 0;
      return false;
    }
    this.scans++;
    if (this.scanModel) {
      const t = this.lastScan;
      if (this.cycleMode === "free") this.now += t;
      else { if (t > this.cycle) this.overruns++; this.now += Math.max(this.cycle, t); }
    } else this.now += this.cycle;
    if (this.trace) this.recordTrace();
    return true;
  }
  outputs() {
    const o = {};
    for (const io of this.io) if (io.dir === "out") o[io.name] = this.read(io.addr);
    return o;
  }
  inputs() {
    const o = {};
    for (const io of this.io) if (io.dir === "in") o[io.name] = this.read(io.addr);
    return o;
  }
  watch(path) { return this.project.watch(this.state, { read: (a) => this.read(a) }, path); }
  // power off and on (Chapter 15.7): outputs drop, the program starts again; RETAIN variables keep their values
  restart() {
    const old = this.state;
    this.state = this.project.newState();
    for (const [pn, inst] of Object.entries(this.state.instances)) {
      const u = this.project.pous[pn];
      for (const v of u.vars) if (v.retain && old.instances[pn]) inst[v.name.toUpperCase()] = old.instances[pn][v.name.toUpperCase()];
    }
    for (const [n, g] of Object.entries(this.project.globals)) if (g.retain && n in old.globals) this.state.globals[n] = old.globals[n];
    for (const io of this.io) if (io.dir === "out") this.image[io.addr] = io.addr[2] === "X" ? false : 0;
    this.error = null; this.restarts = (this.restarts || 0) + 1;
  }
  startTrace(names, max = 2000) { this.trace = { names, t: [], v: names.map(() => []), max }; }
  recordTrace() {
    const tr = this.trace;
    tr.t.push(this.now);
    tr.names.forEach((n, k) => tr.v[k].push(this.watchAny(n)));
    if (tr.t.length > tr.max) { tr.t.shift(); tr.v.forEach((a) => a.shift()); }
  }
  watchAny(n) {
    const io = this.io.find((x) => x.name === n);
    if (io) return this.read(io.addr);
    try { return this.watch(n); } catch (e) { return undefined; }
  }
}

// ---------------------------------------------------------------- plant coupling and tests (〔TST〕)
// plant: { inputs(state) -> {name: value}, step(dt_ms, outputs, state), reset(state, opts) , faults: {...} }
// A test: { id, name, faults: {...}, steps: [ {set: {name: v}} | {wait: ms} | {expect: {name: v}} |
//            {until: {name: v}, within: ms} | {never: {name: v}, during: ms} | {plant: {...}} ] }
function runTest(rtOpts, plant, test, opts = {}) {
  const rt = new Runtime(rtOpts);
  const ps = {};
  if (plant && plant.reset) plant.reset(ps, { faults: test.faults || {}, seed: test.seed || 1 });
  const manual = {};
  const log = [];
  const result = { id: test.id, ok: true, failures: [], log, time: 0 };
  const trace = opts.trace ? { names: opts.trace, t: [], v: opts.trace.map(() => []) } : null;   // signals recorded every scan (book figures)
  if (trace) result.trace = trace;
  const dt = rt.cycle;
  const advance = (ms, check) => {
    const end = rt.now + ms;
    while (rt.now < end - 1e-9) {
      const fromPlant = plant && plant.inputs ? plant.inputs(ps) : {};
      const ins = {};
      for (const io of rt.io) if (io.dir === "in") {
        const v = io.name in manual ? manual[io.name] : io.name in fromPlant ? fromPlant[io.name] : undefined;
        if (v !== undefined) { rt.phys[io.addr] = v; ins[io.name] = v; }
      }
      // operator actions on the machine that are not PLC inputs (e.g. "put a part") go to the machine only
      for (const k in manual) if (!(k in ins) && !rt.io.some((x) => x.name === k)) ins[k] = manual[k];
      const t0 = rt.now;
      if (!rt.scan()) return false;
      if (plant && plant.step) plant.step(rt.now - t0, rt.outputs(), ps, ins);
      if (trace && (!opts.every || rt.now - (trace.last ?? -1e9) >= opts.every - 1e-9)) { trace.last = rt.now; trace.t.push(rt.now); trace.names.forEach((n, k) => trace.v[k].push(val(n))); }
      if (check && check()) return true;
    }
    return null;
  };
  const same = (a, b) => (typeof b === "number" && typeof a === "number" ? Math.abs(a - b) <= (opts.tol || 1e-6) : a === b);
  const fail = (msg) => { result.ok = false; result.failures.push({ at: rt.now, msg }); };
  const val = (n) => {
    if (n === "$scan") return rt.lastScan;
    if (n === "$maxScan") return rt.maxScan;
    if (n === "$minScan") return rt.minScan === Infinity ? 0 : rt.minScan;
    if (n === "$overruns") return rt.overruns;
    if (n === "$scans") return rt.scans;
    const io = rt.io.find((x) => x.name === n);
    if (io) return rt.read(io.addr);
    if (plant && plant.read) { const v = plant.read(ps, n); if (v !== undefined) return v; }
    return rt.watchAny(n);
  };
  for (const s of test.steps) {
    if (rt.error) break;
    if (s.set) { Object.assign(manual, s.set); log.push([rt.now, "set", s.set]); }
    if (s.release) { s.release.forEach((n) => delete manual[n]); }
    if (s.plant && plant && plant.command) plant.command(ps, s.plant);
    if (s.power) {   // {power: ms}: the PLC is off for that long (outputs off, the machine coasts), then starts again
      const offEnd = rt.now + s.power;
      for (const io of rt.io) if (io.dir === "out") rt.image[io.addr] = io.addr[2] === "X" ? false : 0;   // outputs drop at once
      while (rt.now < offEnd - 1e-9) {
        if (plant && plant.step) plant.step(dt, Object.fromEntries(rt.io.filter((x) => x.dir === "out").map((x) => [x.name, x.addr[2] === "X" ? false : 0])), ps, manual);
        rt.now += dt;
        if (trace) { trace.t.push(rt.now); trace.names.forEach((n, k) => trace.v[k].push(val(n))); }
      }
      rt.restart();
      log.push([rt.now, "power", s.power]);
    }
    if (s.wait) { if (advance(s.wait) === false) break; }
    if (s.expect) {
      for (const [n, v] of Object.entries(s.expect)) {
        const got = val(n);
        if (!same(got, v)) fail(`${fmtTime(rt.now)}：${n} 应为 ${v}，实为 ${got} / ${n} should be ${v}, is ${got}`);
      }
    }
    if (s.until) {
      const ok = advance(s.within || 1000, () => Object.entries(s.until).every(([n, v]) => same(val(n), v)));
      if (ok === false) break;
      if (!ok) fail(`${fmtTime(s.within || 1000)} 内没有等到 ${JSON.stringify(s.until)} / did not reach ${JSON.stringify(s.until)} within ${s.within || 1000} ms`);
    }
    if (s.never) {
      const hit = advance(s.during || 1000, () => Object.entries(s.never).some(([n, v]) => same(val(n), v)));
      if (hit === false) break;
      if (hit) fail(`${fmtTime(rt.now)}：不应出现 ${JSON.stringify(s.never)} / must never see ${JSON.stringify(s.never)}`);
    }
  }
  if (rt.error) fail(`PLC 停机：${rt.error.message} / PLC stopped: ${rt.error.message}`);
  result.time = rt.now;
  result.scans = rt.scans;
  if (opts.final) result.final = Object.fromEntries(opts.final.map((n) => [n, val(n)]));   // values at the end (book figures)
  if (trace) delete trace.last;
  return result;
}

// ---------------------------------------------------------------- PLCopen XML (TC6 v2.01)
function xmlEsc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function typeXml(t) {
  if (t.array) return `<array>${t.array.map(([lo, hi]) => `<dimension lower="${lo}" upper="${hi}"/>`).join("")}<baseType>${typeXml(t.of)}</baseType></array>`;
  const n = t.name.toUpperCase();
  if (ELEMENTARY.has(n)) return n === "STRING" ? "<string/>" : `<${n}/>`;
  return `<derived name="${xmlEsc(t.name)}"/>`;
}
// an initial value as PLCopen XML: simpleValue holds the ST literal text; arrays and structures nest
function valueXml(init) {
  if (init.k === "arr") return `<arrayValue>${init.items.map((x) => `<value>${valueXml(x)}</value>`).join("")}</arrayValue>`;
  if (init.k === "struct") return `<structValue>${Object.entries(init.fields).map(([f, x]) => `<value member="${xmlEsc(f)}">${valueXml(x)}</value>`).join("")}</structValue>`;
  return `<simpleValue value="${xmlEsc(exprText(init))}"/>`;
}

// ---------------------------------------------------------------- PLCopen XML import (the files exportXml writes, and ST bodies from other tools)
// importXml(xml) -> ST source text the engine runs: TYPE … END_TYPE, then each POU with its VAR sections and ST body.
function xmlTree(xml) {
  const root = { tag: "#root", attrs: {}, kids: [], text: "" };
  const stack = [root];
  const re = /<!\[CDATA\[([\s\S]*?)\]\]>|<!--[\s\S]*?-->|<\?[\s\S]*?\?>|<\/([\w:.-]+)\s*>|<([\w:.-]+)((?:\s+[\w:.-]+\s*=\s*(?:"[^"]*"|'[^']*'))*)\s*(\/?)>|([^<]+)/g;
  const unesc = (t) => t.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&#(\d+);/g, (_, n) => String.fromCharCode(+n)).replace(/&amp;/g, "&");
  let m;
  while ((m = re.exec(xml))) {
    const top = stack[stack.length - 1];
    if (m[1] != null) top.text += m[1];
    else if (m[2]) { if (stack.length > 1) stack.pop(); }
    else if (m[3]) {
      const attrs = {};
      (m[4] || "").replace(/([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g, (_, k, a, b) => { attrs[k.replace(/^.*:/, "")] = unesc(a != null ? a : b); });
      const el = { tag: m[3].replace(/^.*:/, ""), attrs, kids: [], text: "" };
      top.kids.push(el);
      if (!m[5]) stack.push(el);
    } else if (m[6]) top.text += unesc(m[6]);
  }
  return root;
}
function importXml(xml, opts = {}) {
  const root = xmlTree(xml);
  const find = (el, tag) => el.kids.find((k) => k.tag === tag);
  const all = (el, tag, out = []) => { el.kids.forEach((k) => { if (k.tag === tag) out.push(k); all(k, tag, out); }); return out; };
  const textOf = (el) => (el.text || "") + el.kids.map(textOf).join("");
  const project = all(root, "project")[0];
  if (!project) throw E("xml", "不是 PLCopen XML 文件（没有 project 元素） / Not a PLCopen XML file (no project element)");
  const typeText = (t) => {
    const k = t && t.kids[0];
    if (!k) throw E("xml", "类型缺失 / Missing type");
    if (k.tag === "derived") return k.attrs.name;
    if (k.tag === "string") return "STRING";
    if (k.tag === "wstring") return "WSTRING";
    if (k.tag === "array") {
      const dims = k.kids.filter((d) => d.tag === "dimension").map((d) => `${d.attrs.lower}..${d.attrs.upper}`);
      return `ARRAY[${dims.join(", ")}] OF ${typeText(find(k, "baseType"))}`;
    }
    return k.tag.toUpperCase();
  };
  const valueText = (v) => {
    const k = v && v.kids[0];
    if (!k) return "";
    if (k.tag === "simpleValue") return k.attrs.value;
    if (k.tag === "arrayValue") return "[" + k.kids.filter((x) => x.tag === "value").map((x) => (x.attrs.repetitionValue ? `${x.attrs.repetitionValue}(${valueText(x)})` : valueText(x))).join(", ") + "]";
    if (k.tag === "structValue") return "(" + k.kids.filter((x) => x.tag === "value").map((x) => `${x.attrs.member} := ${valueText(x)}`).join(", ") + ")";
    return "";
  };
  const varLine = (v) => `    ${v.attrs.name}${v.attrs.address ? " AT " + v.attrs.address : ""} : ${typeText(find(v, "type"))}` +
    (find(v, "initialValue") ? " := " + valueText(find(v, "initialValue")) : "") + ";";
  const SECTION = { inputVars: "VAR_INPUT", outputVars: "VAR_OUTPUT", inOutVars: "VAR_IN_OUT", localVars: "VAR", tempVars: "VAR_TEMP", externalVars: "VAR_EXTERNAL" };
  const out = [];
  const types = all(project, "dataType");
  if (types.length) {
    out.push("TYPE");
    for (const t of types) {
      const b = find(t, "baseType"), k = b && b.kids[0];
      if (k && k.tag === "struct") out.push(`  ${t.attrs.name} : STRUCT\n${k.kids.filter((x) => x.tag === "variable").map((v) => "  " + varLine(v)).join("\n")}\n  END_STRUCT;`);
      else if (k && k.tag === "enum") {
        const vals = all(k, "value");
        const explicit = vals.some((x, i) => x.attrs.value != null && +x.attrs.value !== i);
        const init = find(t, "initialValue");
        out.push(`  ${t.attrs.name} : (${vals.map((x) => x.attrs.name + (explicit && x.attrs.value != null ? " := " + x.attrs.value : "")).join(", ")})${init ? " := " + valueText(init) : ""};`);
      } else out.push(`  ${t.attrs.name} : ${typeText(b)};`);
    }
    out.push("END_TYPE", "");
  }
  const ioNames = new Set((opts.io || []).map((x) => x.name.toUpperCase()));
  const globals = all(project, "globalVars").flatMap((g) => g.kids.filter((v) => v.tag === "variable" && !ioNames.has(v.attrs.name.toUpperCase())));
  if (globals.length) out.push("VAR_GLOBAL", ...globals.map(varLine), "END_VAR", "");
  const KW = { program: "PROGRAM", functionBlock: "FUNCTION_BLOCK", function: "FUNCTION" };
  const pous = all(project, "pou");
  if (!pous.length) throw E("xml", "XML 里没有程序（pou） / The XML has no program (pou)");
  for (const u of pous) {
    const kw = KW[u.attrs.pouType];
    if (!kw) throw E("xml", `不认识的程序组织单元类型 ${u.attrs.pouType} / Unknown POU type ${u.attrs.pouType}`);
    const itf = find(u, "interface") || { kids: [] };
    const ret = find(itf, "returnType");
    out.push(`${kw} ${u.attrs.name}${ret ? " : " + typeText(ret) : ""}`);
    for (const sec of itf.kids) {
      if (!SECTION[sec.tag]) continue;
      out.push(`  ${SECTION[sec.tag]}${sec.attrs.retain === "true" ? " RETAIN" : ""}${sec.attrs.constant === "true" ? " CONSTANT" : ""}`);
      sec.kids.filter((v) => v.tag === "variable").forEach((v) => out.push(varLine(v)));
      out.push("  END_VAR");
    }
    const body = find(u, "body");
    const st = body && find(body, "ST");
    if (!st) throw E("xml", `${u.attrs.name} 的程序体不是结构化文本：问渠目前只导入 ST 程序体（梯形图、SFC 图形请先在原软件里转成 ST） / ` +
      `The body of ${u.attrs.name} is not Structured Text: only ST bodies are imported for now (convert LD / graphical SFC to ST first)`);
    out.push(textOf(st).replace(/^\n+|\s+$/g, ""), `END_${kw}`, "");
  }
  return out.join("\n");
}

function exportXml(src, opts = {}) {
  const ast = parse(src);
  const kindOf = { program: "program", fb: "functionBlock", function: "function" };
  const SECTION = { input: "inputVars", output: "outputVars", inout: "inOutVars", var: "localVars", temp: "tempVars", external: "externalVars", global: "globalVars" };
  const lines = src.split(/\n/);
  const bodyText = (u) => {
    // the source text between the last END_VAR of the POU and its END_ keyword
    const end = { program: "END_PROGRAM", fb: "END_FUNCTION_BLOCK", function: "END_FUNCTION" }[u.kind];
    const start = u.line - 1;
    let k = start, lastVar = start;
    while (k < lines.length && !new RegExp("^\\s*" + end + "\\b", "i").test(lines[k])) { if (/\bEND_VAR\b/i.test(lines[k])) lastVar = k; k++; }
    return lines.slice(lastVar + 1, k).join("\n").replace(/^\n+|\s+$/g, "");
  };
  const varsXml = (vars) => {
    // one section per kind and RETAIN / CONSTANT flags, in declaration order
    const groups = [];
    vars.forEach((v) => {
      const key = v.kind + (v.retain ? "R" : "") + (v.constant ? "C" : "");
      const g = groups.length && groups[groups.length - 1].key === key ? groups[groups.length - 1] : null;
      if (g) g.vs.push(v); else groups.push({ key, k: v.kind, vs: [v] });
    });
    return groups.map(({ k, vs }) => `<${SECTION[k]}${vs[0].retain ? ' retain="true"' : ""}${vs[0].constant ? ' constant="true"' : ""}>` +
      vs.map((v) => `<variable name="${xmlEsc(v.name)}"${v.addr ? ` address="${v.addr}"` : ""}><type>${typeXml(v.type)}</type>` +
        (v.init ? `<initialValue>${valueXml(v.init)}</initialValue>` : "") + "</variable>").join("") + `</${SECTION[k]}>`).join("");
  };
  const typesXml = Object.values(ast.types).map((t) => {
    if (t.struct) return `<dataType name="${xmlEsc(t.name)}"><baseType><struct>${t.struct.map((f) => `<variable name="${xmlEsc(f.name)}"><type>${typeXml(f.type)}</type></variable>`).join("")}</struct></baseType></dataType>`;
    if (t.enumeration) return `<dataType name="${xmlEsc(t.name)}"><baseType><enum><values>${t.enumeration.map(([v, n]) => `<value name="${xmlEsc(v)}" value="${n}"/>`).join("")}</values></enum></baseType>` +
      (t.init ? `<initialValue><simpleValue value="${xmlEsc(t.init)}"/></initialValue>` : "") + "</dataType>";
    return `<dataType name="${xmlEsc(t.name)}"><baseType>${typeXml(t.alias)}</baseType></dataType>`;
  }).join("");
  const pousXml = ast.pous.map((u) => `<pou name="${xmlEsc(u.name)}" pouType="${kindOf[u.kind]}"><interface>` +
    (u.ret ? `<returnType>${typeXml(u.ret)}</returnType>` : "") + varsXml(u.vars) + `</interface><body><ST><xhtml:p xmlns:xhtml="http://www.w3.org/1999/xhtml"><![CDATA[${bodyText(u)}]]></xhtml:p></ST></body></pou>`).join("");
  const io = opts.io || [];
  const globals = ast.globals.concat(io.map((x) => ({ name: x.name, type: { name: x.type || "BOOL" }, addr: normAddr(x.addr), kind: "global" })));
  const now = (opts.date || new Date()).toISOString().replace(/\.\d+Z$/, "");
  const prog = ast.pous.find((u) => u.kind === "program");
  return `<?xml version="1.0" encoding="utf-8"?>
<project xmlns="http://www.plcopen.org/xml/tc6_0201" xmlns:xhtml="http://www.w3.org/1999/xhtml" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
<fileHeader companyName="WenQuest" productName="WenQuest PLC lab" productVersion="1" creationDateTime="${now}"/>
<contentHeader name="${xmlEsc(opts.name || "WenQuest project")}" modificationDateTime="${now}"><coordinateInfo><fbd><scaling x="1" y="1"/></fbd><ld><scaling x="1" y="1"/></ld><sfc><scaling x="1" y="1"/></sfc></coordinateInfo></contentHeader>
<types><dataTypes>${typesXml}</dataTypes><pous>${pousXml}</pous></types>
<instances><configurations><configuration name="Config0"><resource name="Res0">` +
  `<task name="MainTask" priority="0" interval="${fmtTime(opts.cycle || 10)}">${prog ? `<pouInstance name="${xmlEsc(prog.name)}Inst" typeName="${xmlEsc(prog.name)}"/>` : ""}</task>` +
  (globals.length ? `<globalVars>${globals.map((v) => `<variable name="${xmlEsc(v.name)}"${v.addr ? ` address="${v.addr}"` : ""}><type>${typeXml(v.type)}</type></variable>`).join("")}</globalVars>` : "") +
  `</resource></configuration></configurations></instances>
</project>
`;
}

// ladder to ST (for export and for the "show me the same thing in ST" view): series = AND, parallel = OR.
function ladderToSt(rungs) {
  const out = [];
  rungs.forEach((r, ri) => {
    const rows = r.cells.length, cols = Math.max(...r.cells.map((row) => row.length));
    const link = new Set((r.links || []).map(([a, c]) => a + ":" + c));
    let edge = new Array(rows).fill("TRUE");
    const lines = [];
    if (r.comment) lines.push(`(* ${Array.isArray(r.comment) ? r.comment[0] : r.comment} *)`);
    const and = (a, b) => (a === "TRUE" ? b : b === "TRUE" ? a : a === "FALSE" || b === "FALSE" ? "FALSE" : `${a} AND ${b}`);
    for (let c = 0; c <= cols; c++) {
      if (c >= 1) {
        let r0 = 0;
        while (r0 < rows) {
          let r1 = r0;
          while (r1 < rows - 1 && link.has(r1 + ":" + c)) r1++;
          if (r1 > r0) {
            const terms = [...new Set(edge.slice(r0, r1 + 1).filter((x) => x !== "FALSE"))];
            const e = terms.includes("TRUE") ? "TRUE" : terms.length ? (terms.length > 1 ? `(${terms.join(" OR ")})` : terms[0]) : "FALSE";
            for (let k = r0; k <= r1; k++) edge[k] = e;
          }
          r0 = r1 + 1;
        }
      }
      if (c === cols) break;
      for (let i = 0; i < rows; i++) {
        const cell = (r.cells[i] || [])[c];
        const p = edge[i];
        if (!cell) { edge[i] = "FALSE"; continue; }
        switch (cell.k) {
          case "WIRE": break;
          case "NO": edge[i] = and(p, cell.v); break;
          case "NC": edge[i] = and(p, `NOT ${cell.v}`); break;
          case "CMP": edge[i] = and(p, `(${cell.x})`); break;
          case "P": lines.push(`_rt${ri}_${i}_${c}(CLK := ${cell.v});`); edge[i] = and(p, `_rt${ri}_${i}_${c}.Q`); break;
          case "N": lines.push(`_ft${ri}_${i}_${c}(CLK := ${cell.v});`); edge[i] = and(p, `_ft${ri}_${i}_${c}.Q`); break;
          case "COIL": lines.push(`${cell.v} := ${p};`); break;
          case "NCOIL": lines.push(`${cell.v} := NOT (${p});`); break;
          case "SET": lines.push(`IF ${p} THEN ${cell.v} := TRUE; END_IF;`); break;
          case "RST": lines.push(`IF ${p} THEN ${cell.v} := FALSE; END_IF;`); break;
          case "ASSIGN": lines.push(`IF ${p} THEN ${cell.v} := ${cell.x}; END_IF;`); break;
          case "FB": {
            const pin = { TON: "IN", TOF: "IN", TP: "IN", CTU: "CU", CTD: "CD", R_TRIG: "CLK", F_TRIG: "CLK" }[cell.fb];
            const ps = Object.entries(cell.p || {}).map(([k, v]) => `, ${k} := ${v}`).join("");
            lines.push(`${cell.inst}(${pin} := ${p}${ps});`);
            edge[i] = `${cell.inst}.Q`;
            break;
          }
        }
      }
    }
    out.push(lines.join("\n"));
  });
  return out.join("\n\n");
}

// ---------------------------------------------------------------- program review (the rule part of the AI program reviewer)
// review({st} | {decls, ladder}, io) -> [{level: "error"|"warning"|"info", rule, line, msg: [zh, en]}]
// The rules catch what PLC engineers check in a code review; a language model may later word the findings, never add them.
function review(prog, io = []) {
  const out = [];
  const add = (level, rule, line, zh, en) => out.push({ level, rule, line: line || 0, msg: [zh, en] });
  const ioBy = {};
  io.forEach((x) => { ioBy[x.name.toUpperCase()] = x; });
  const isLadder = !!prog.ladder;
  let ast;
  try {
    const text = isLadder ? `PROGRAM Main\n${prog.decls || ""}\n${ladderToSt(prog.ladder)}\nEND_PROGRAM` : prog.st;
    ast = parse(text);
  } catch (e) { add("error", "syntax", e.line, e.message, e.message); return out; }

  // walk all statements, collecting reads, writes and calls
  const reads = new Map(), writes = new Map(), topWrites = new Map(), calls = new Map(), trueWrites = new Set(), falseWrites = new Set();
  const note = (m, n, line) => { const k = n.toUpperCase(); if (!m.has(k)) m.set(k, []); m.get(k).push(line); };
  const rootName = (x) => (x.e === "name" ? x.n : x.e === "field" || x.e === "index" || x.e === "bit" ? rootName(x.a) : null);
  function walkExpr(x, line) {
    if (!x || typeof x !== "object") return;
    if (x.e === "name") note(reads, x.n, line);
    if (x.e === "call") { (x.args || []).forEach((a) => { if (a.v) walkExpr(a.v, line); if (a.out) { const r = rootName(a.out); if (r) note(writes, r, line); } }); if (x.f.e !== "name" || !STD_FN[x.f.n.toUpperCase()]) { const r = rootName(x.f); if (r) note(calls, r, line); } return; }
    for (const k of ["a", "b", "v"]) if (x[k] && typeof x[k] === "object") walkExpr(x[k], line);
    if (x.idx) x.idx.forEach((i) => walkExpr(i, line));
  }
  function walk(list, depth, loops) {
    for (const s of list) {
      const line = s.line;
      if (s.s === "assign") {
        const r = rootName(s.target);
        if (r) { note(writes, r, line); if (depth === 0 && s.target.e === "name") note(topWrites, r, line); }
        if (s.target.e !== "name") walkExpr(s.target, line);
        if (s.v.e === "bool" && r) (s.v.v ? trueWrites : falseWrites).add(r.toUpperCase());
        else if (r) { trueWrites.add(r.toUpperCase()); falseWrites.add(r.toUpperCase()); }
        walkExpr(s.v, line);
      } else if (s.s === "call") walkExpr(s.call, line);
      else if (s.s === "if") { s.arms.forEach(([c, b]) => { walkExpr(c, line); walk(b, depth + 1, loops); }); walk(s.other, depth + 1, loops); }
      else if (s.s === "case") { walkExpr(s.sel, line); s.arms.forEach((a) => walk(a.body, depth + 1, loops)); walk(s.other, depth + 1, loops); }
      else if (s.s === "for") { note(writes, s.v, line); walkExpr(s.from, line); walkExpr(s.to, line); walk(s.body, depth + 1, loops + 1); }
      else if (s.s === "while" || s.s === "repeat") {
        walkExpr(s.c, line);
        // a loop that waits for an input never ends inside one scan (Chapter 10.7)
        const condNames = new Set(); (function names(x) { if (!x || typeof x !== "object") return; if (x.e === "name") condNames.add(x.n.toUpperCase()); for (const k of ["a", "b"]) names(x[k]); })(s.c);
        const bodyWrites = new Map(); const saveW = new Map(writes);
        walk(s.body, depth + 1, loops + 1);
        const changed = [...condNames].some((n) => (writes.get(n) || []).length > (saveW.get(n) || []).length);
        const waitsForInput = [...condNames].some((n) => ioBy[n] && ioBy[n].dir === "in");
        if (waitsForInput) add("error", "loop-input", line, "这个循环在等输入变化：一次扫描里输入不会变，循环停不下来，看门狗会让 PLC 停机。改成每次扫描检查一次（IF）。",
          "This loop waits for an input to change: inputs do not change within a scan, so it never ends and the watchdog stops the PLC. Check it once per scan with IF instead.");
        else if (!changed) add("warning", "loop-static", line, "循环条件里的变量在循环体里没有改变，循环可能停不下来。", "Nothing in the loop body changes the loop condition: the loop may never end.");
      }
    }
  }
  const declared = new Map();
  for (const u of ast.pous) {
    walk(u.body, 0, 0);
    if (u.sfc) {
      u.sfc.transitions.forEach((t) => walkExpr(t.cond, t.line));
      Object.values(u.sfc.actions).forEach((a) => walk(a.body, 1, 0));
      u.sfc.steps.forEach((st) => { note(reads, st.name, st.line); st.acts.forEach((a) => { if (!u.sfc.actions[a.name.toUpperCase()]) { note(writes, a.name, st.line); trueWrites.add(a.name.toUpperCase()); falseWrites.add(a.name.toUpperCase()); } if (a.t) walkExpr(a.t, st.line); }); });
    }
    if (u.kind === "program") u.vars.forEach((v) => declared.set(v.name.toUpperCase(), v));
  }
  const nameOf = (n) => (ioBy[n] && ioBy[n].name) || (declared.get(n) && declared.get(n).name) || n;
  // R1 double coil: an output written unconditionally in two places (the last one wins, Chapter 4.6 and 8.5)
  for (const [n, lines] of topWrites) if (lines.length > 1) add("error", "double-coil", lines[1], `双线圈：${nameOf(n)} 在第 ${lines.join("、")} 行都被无条件赋值，只有最后一处起作用。合并成一个表达式。`,
    `Double coil: ${nameOf(n)} is assigned unconditionally on lines ${lines.join(", ")}; only the last one counts. Merge them into one expression.`);
  if (isLadder) {
    const coils = {};
    prog.ladder.forEach((r, ri) => r.cells.forEach((row) => row.forEach((c) => { if (c && (c.k === "COIL" || c.k === "NCOIL")) (coils[c.v.toUpperCase()] = coils[c.v.toUpperCase()] || []).push(ri + 1); })));
    for (const [n, rs] of Object.entries(coils)) if (rs.length > 1) add("error", "double-coil", 0, `双线圈：${nameOf(n)} 的线圈出现在网络 ${rs.join("、")}，只有最后一个起作用。`, `Double coil: ${nameOf(n)} has coils in rungs ${rs.join(", ")}; only the last one counts.`);
  }
  // R2 latched but never released: set TRUE somewhere and never FALSE (SET without RESET)
  for (const n of trueWrites) if (!falseWrites.has(n) && ioBy[n] && ioBy[n].dir === "out")
    add("warning", "latch", 0, `${nameOf(n)} 只被置为 TRUE，没有任何地方把它复位：一旦置位就一直保持（直到断电）。`, `${nameOf(n)} is only ever set TRUE and never reset: once set, it stays on.`);
  // R3 stop / e-stop inputs must be used
  for (const x of io) {
    const nm = x.name.toUpperCase();
    if (x.dir === "in" && /STOP|ESTOP|EMERG|急停|停止|LC|CURTAIN|LIM/.test(nm + JSON.stringify(x.comment || "")) && !reads.has(nm))
      add("error", "stop-unused", 0, `停止或安全输入 ${x.name} 在程序里没有用到。`, `Stop or safety input ${x.name} is not used by the program.`);
    else if (x.dir === "in" && !reads.has(nm)) add("info", "input-unused", 0, `输入 ${x.name} 没有用到。`, `Input ${x.name} is not used.`);
    if (x.dir === "out" && !writes.has(nm)) add("info", "output-unused", 0, `输出 ${x.name} 从来没有被写。`, `Output ${x.name} is never written.`);
  }
  // R4 writing an input
  for (const [n, lines] of writes) if (ioBy[n] && ioBy[n].dir === "in") add("error", "write-input", lines[0], `第 ${lines[0]} 行给输入 ${nameOf(n)} 赋值：输入映像在下一次扫描开始时会被现场信号覆盖。`,
    `Line ${lines[0]} writes input ${nameOf(n)}: the input image is overwritten by the field signal at the next scan.`);
  // R5 unused or never-written variables; vague names
  for (const [n, v] of declared) {
    // IEC 61131-3: a variable may not have the name of a standard function or function block (LIMIT, MAX, TON …):
    // the WenQuest engine tells them apart, real compilers (MatIEC in OpenPLC, CODESYS) refuse the program
    if (STD_FN[n] || STD_FB[n]) add("error", "std-name", v.line, `变量 ${v.name} 与标准函数或功能块 ${n} 同名：换到真的 PLC 上编译不过，换个名字。`,
      `Variable ${v.name} has the name of the standard function or function block ${n}: real PLC compilers reject it. Rename it.`);
    if (v.kind !== "var" || v.addr) continue;
    const used = reads.has(n) || calls.has(n);
    if (!used && !writes.has(n)) add("info", "var-unused", v.line, `变量 ${v.name} 声明了但没有用。`, `Variable ${v.name} is declared but not used.`);
    if (/^[a-z]\d*$|^(tmp|temp|aa|bb|xx)\d*$/i.test(v.name) && !/^[ijk]$/i.test(v.name)) add("info", "naming", v.line, `变量名 ${v.name} 看不出含义，按符号约定第二节命名。`, `The name ${v.name} says nothing; name it as in the conventions, section 2.`);
  }
  // R6 a timer or counter instance called in more than one place with different inputs is a classic source of bugs
  for (const [n, lines] of calls) {
    const v = declared.get(n);
    if (v && v.type && STD_FB[(v.type.name || "").toUpperCase()] && lines.length > 2)
      add("warning", "fb-multi-call", lines[0], `${nameOf(n)} 在 ${lines.length} 处被调用：同一个定时器或计数器每次扫描最好只调用一次。`, `${nameOf(n)} is called in ${lines.length} places: call a timer or counter once per scan.`);
  }
  // R7 an output with an interlock partner (…Fwd/…Rev, Up/Down, Open/Close) whose logic never mentions the partner
  const pairs = [[/(FWD|FORWARD)$/, "REV"], [/UP$/, "DOWN"], [/OPEN$/, "CLOSE"]];
  for (const x of io) {
    if (x.dir !== "out") continue;
    const nm = x.name.toUpperCase();
    for (const [re, other] of pairs) {
      if (!re.test(nm)) continue;
      const partner = io.find((y) => y.dir === "out" && y.name.toUpperCase() === nm.replace(re, other));
      if (partner && reads.has(nm) === false && reads.has(partner.name.toUpperCase()) === false && writes.has(nm) && writes.has(partner.name.toUpperCase()))
        add("warning", "interlock", 0, `${x.name} 与 ${partner.name} 不能同时得电，但程序里两者互相没有联锁（都没有读对方）。`,
          `${x.name} and ${partner.name} must never be on together, but neither one's logic reads the other: no interlock.`);
    }
  }
  const order = { error: 0, warning: 1, info: 2 };
  return out.sort((a, b) => order[a.level] - order[b.level] || a.line - b.line);
}

const API = { exprText, review, lex, parse, parseExpr, compile, compileLadder, ladderToSt, Runtime, runTest, exportXml, importXml, parseTime, fmtTime, normAddr, PlcError, STD_FB, STD_FN };
if (typeof module !== "undefined" && module.exports) module.exports = API;
else root.WQPLC = API;
})(typeof window !== "undefined" ? window : globalThis);
