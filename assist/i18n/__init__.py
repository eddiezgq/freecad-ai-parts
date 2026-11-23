"""问渠有限元的中英两种语言（ADR-0096 决策 4、第 3 步）。

代码里的提示、核查说明、报告文字都照旧用中文写；要英文时，在显示或出报告的那一刻用 `t(text, "en")` 翻成英文。
对照表 `en.json`：键是中文原文的模板（f-string 里的 {…} 照写 `{}`，与代码一致，测试会逐条核对代码里的文字都有英文），
值是英文模板（`{}` 按顺序、`{name}` 按名字填回）。填回的每一段也再翻一次（例如“屈服强度”）。
用户写的话（原话引用、零件名、工况名）和文献出处不翻，原样保留。

语言：`lang()`——环境变量 FAP_LANG（zh / en）→ 本插件设置 → FreeCAD 的界面语言（中文以外一律英文）→ 中文。
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

LANGS = ("zh", "en")
CJK = re.compile(r"[　-〿一-鿿＀-￯]")
_FIELD = re.compile(r"\{\{|\}\}|\{[^{}]*\}")
PARAM = "User parameter:BaseApp/Preferences/Mod/FreecadAiParts"
MISSES: set[str] = set()          # 没翻出来的（诊断、测试用）


def has_cjk(s: str) -> bool:
    return bool(s) and bool(CJK.search(str(s)))


def _parse(tmpl: str) -> tuple[list[str], list[str]]:
    """模板 → (各段字面文字, 各个字段名)；{{ }} 是字面的花括号"""
    lits, names, buf, pos = [], [], "", 0
    for m in _FIELD.finditer(tmpl):
        buf += tmpl[pos:m.start()]
        tok = m.group()
        if tok in ("{{", "}}"):
            buf += tok[0]
        else:
            lits.append(buf)
            buf = ""
            names.append(tok[1:-1].split(":")[0].split("!")[0])
        pos = m.end()
    lits.append(buf + tmpl[pos:])
    return lits, names


@lru_cache(maxsize=1)
def _table() -> tuple[dict[str, str], list[tuple[re.Pattern, re.Pattern, str, list[str]]]]:
    data = json.loads((Path(__file__).with_name("en.json")).read_text(encoding="utf-8"))
    data.update(json.loads((Path(__file__).with_name("data_en.json")).read_text(encoding="utf-8"))["names"])
    tails = {"{}" + zh: "{}" + en for zh, en in data.items() if zh[:1] in "，；：（" and len(zh) >= 3}
    exact, pats = {}, []                       # 代码里拼在别的句子后面的半句（以“，；：（”开头）：前面再接一段，先试
    for zh, en in [*data.items(), *tails.items()]:
        lits, names = _parse(zh)
        if not names:
            exact["".join(lits)] = en
            continue
        lazy = "".join(re.escape(lit) + ("(.*?)" if i < len(names) else "") for i, lit in enumerate(lits))
        greedy = "".join(re.escape(lit) + ("(.*)" if i < len(names) else "") for i, lit in enumerate(lits))
        pats.append((zh not in tails, -len("".join(lits)), re.compile("^" + lazy + "$", re.DOTALL), re.compile("^" + greedy + "$", re.DOTALL),
                     en, names))
    pats.sort(key=lambda x: x[:2])
    return exact, [x[2:] for x in pats]


def _fill(en: str, names: list[str], groups: tuple[str, ...]) -> str:
    by_name = {n: g for n, g in zip(names, groups, strict=True) if n}
    lits, fields = _parse(en)
    it = iter(groups)
    out = ""
    for i, lit in enumerate(lits):
        out += lit
        if i < len(fields):
            f = fields[i]
            out += _tr(by_name[f] if f and f in by_name else next(it))
    return out


def _ncjk(s: str) -> int:
    return len(CJK.findall(s))


_PIECE = re.compile(r"(?<=[；。\n])")
_END = {"；": "; ", "。": ". ", "\n": "\n"}


@lru_cache(maxsize=50000)
def _tr(text: str) -> str:
    """翻一段：先查整句；再试各个模板（长的在前；字段先按最短、再按最长匹配），也试按“；”“。”断句逐句翻，取剩下中文最少的"""
    if not has_cjk(text):
        return text
    exact, pats = _table()
    if text in exact:
        return exact[text]
    s = text.strip()
    if s != text and s in exact:
        return text.replace(s, exact[s])
    best, score = text, _ncjk(text)
    for lazy, greedy, en, names in pats:
        for rx in (lazy, greedy):
            m = rx.match(text)
            if not m:
                continue
            out = _fill(en, names, m.groups())
            n = _ncjk(out)
            if n < score:
                best, score = out, n
                if n == 0:
                    return best
    pieces = [x for x in _PIECE.split(text) if x]
    if len(pieces) > 1:
        out = ""
        for x in pieces:
            y = _tr(x)
            if y == x and x[-1:] in _END:
                y = _tr(x[:-1]) + _END[x[-1]]
            out += y
        out = re.sub(r"(; )([A-Z])(?=[a-z])", lambda m: m.group(1) + m.group(2).lower(), out).rstrip(" ") \
            if text == text.rstrip() else out
        if _ncjk(out) < score:
            best, score = out, _ncjk(out)
    if score == _ncjk(text):
        MISSES.add(text)
    return best


def t(text, lang: str = "en"):
    """翻成 lang（zh 原样返回）。整句对不上表时按模板拆开、按句断开逐段翻；仍对不上的原样保留（记进 MISSES）"""
    if lang != "en" or not isinstance(text, str) or not has_cjk(text):
        return text
    out = _tr(text)
    if out.count("\n") < text.count("\n"):            # 拆句时把换行丢了（多行的核查结论）：逐行翻
        out = "\n".join(_tr(x) if has_cjk(x) else x for x in text.split("\n"))
    return out


RAW_L, RAW_R = "\ue000", "\ue001"          # 原样保留的一段（用户写的话、文献出处）：翻译时当成一个整体，不动
_RAW = re.compile(RAW_L + "(.*?)" + RAW_R, re.DOTALL)
_TOK = re.compile("\ue002(\\d+)\ue003")


def raw(text) -> str:
    """标一段不翻的文字（显示前由 final 去掉标记）"""
    return f"{RAW_L}{text}{RAW_R}"


def final(text, lang: str) -> str:
    """出报告、显示前的最后一步：英文时翻译（标了原样的段不动），并去掉原样标记"""
    if not isinstance(text, str):
        return text
    spans: list[str] = []

    def keep(m):
        spans.append(m.group(1))
        return f"\ue002{len(spans) - 1}\ue003"

    s = _RAW.sub(keep, text)
    if lang == "en":
        s = t(s, "en")
    return _TOK.sub(lambda m: spans[int(m.group(1))], s)


def lang() -> str:
    """当前界面语言：FAP_LANG → 本插件设置 → FreeCAD 界面语言 → 中文"""
    v = (os.environ.get("FAP_LANG") or "").strip().lower()
    if v in LANGS:
        return v
    try:
        import FreeCAD
    except ImportError:
        return "zh"
    v = FreeCAD.ParamGet(PARAM).GetString("Language", "").strip().lower()
    if v in LANGS:
        return v
    ui = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General").GetString("Language", "")
    if ui:
        return "zh" if ui.lower().startswith("chinese") else "en"
    import locale  # FreeCAD 没设语言时跟随系统

    loc = (locale.getlocale()[0] or os.environ.get("LANG") or "").lower()
    return "zh" if loc.startswith(("zh", "chinese")) else "en"


def tr(text):
    """按当前界面语言翻（界面用）"""
    return t(text, lang())


_BULLET = re.compile(r"^(\s*(?:[-·]\s*)?)(.*)$", re.DOTALL)
_CMP = re.compile(r"^(.*) (-?[\d.]+(?:e[-+]?\d+)?) ([≤≥<>]) (.*) (-?[\d.]+(?:e[-+]?\d+)?)((?: \S+)?)$", re.DOTALL)


def _t_line(line: str) -> str:
    """一行：保留行首的缩进和“- ”“· ”；“甲 1.2 ≤ 乙 3 N·m”这类比较两边各自翻（#679）"""
    pre, s = _BULLET.match(line).groups()
    out = t(s, "en")
    if has_cjk(out):
        m = _CMP.match(s)
        if m:
            out = f"{t(m[1], 'en')} {m[2]} {m[3]} {t(m[4], 'en')} {m[5]}{m[6]}"
    if has_cjk(out) and "；" in s:                      # 规则表里用“；”连起来的几条原因：逐条翻
        out = "; ".join(t(x, "en") for x in s.split("；"))
    return pre + out


def t_block(text, lang: str = "en"):
    """多段、多行的说明（选型方案说明、校验细项）：按空行分段，整段对不上表时逐行翻（#679）"""
    if lang != "en" or not isinstance(text, str) or not has_cjk(text):
        return text
    out = []
    for blk in text.split("\n\n"):
        y = t(blk, "en")
        if has_cjk(y):
            y = "\n".join(_t_line(x) for x in blk.split("\n"))
        out.append(y)
    return "\n\n".join(out)


def tr_block(text):
    """按当前界面语言翻多段说明（界面用）"""
    return t_block(text, lang())
