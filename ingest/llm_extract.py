"""LLM 结构化抽取（issue #29，ADR-0021）。

流程：PDF 提取结果（#28）+ 品类字段清单 → LLM 通过强制工具调用提议抽取项 → 代码逐项核对 → 抽取结果
（符合 schema/extraction.schema.json）。LLM 只报规格书上印出的内容；单位换算、枚举与范围校验、原文引用核对
全部由本模块的确定性代码完成。核对函数是纯函数，不联网。

LLM 客户端：
- RecordedClient：按请求哈希回放 tests/recordings/llm/ 中的录制，测试只用它
- AnthropicClient：真实调用；密钥只从环境变量 ANTHROPIC_API_KEY 或本地 .env 读取；可同时写录制
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Protocol

from ingest.pdf_extract import Document, ExtractError, extract
from ingest.units import UnitError, standard_unit, to_standard
from kb.validation import ID_BASE, SCHEMA_DIR, errors, validator_for_ref

PROMPT_VERSION = "extract/2"
DEFAULT_MODEL = "claude-sonnet-5-5"
TOOL_NAME = "record_extraction"
ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = ROOT / "tests" / "recordings" / "llm"
CATEGORIES = ("servo_motor", "reducer", "drive", "bearing", "adapter")

DIMS = {
    "overall_length_mm": "总长（沿轴向）",
    "body_length_mm": "机身长度，不含轴伸（电机）",
    "outer_diameter_mm": "外径",
    "square_mm": "方形法兰或方形壳体的边长",
    "width_mm": "宽度",
    "height_mm": "高度",
    "depth_mm": "深度",
}
# 各品类可抽取的整体尺寸（用于生成包络，ADR-0021 第 4 条）
CATEGORY_DIMS = {
    "servo_motor": ("body_length_mm", "overall_length_mm", "square_mm", "outer_diameter_mm"),
    "reducer": ("overall_length_mm", "outer_diameter_mm", "square_mm"),
    "drive": ("width_mm", "height_mm", "depth_mm"),
    "bearing": ("outer_diameter_mm",),
    "adapter": ("overall_length_mm", "outer_diameter_mm", "square_mm", "width_mm", "height_mm"),
}

# ---------------------------------------------------------------- 字段清单


@dataclass(frozen=True)
class Target:
    target: str
    kind: str  # number / integer / string / boolean / string_or_list / number_pair
    unit: str | None  # 标准单位（pint 写法）；无单位为 None
    enum: tuple | None
    description: str
    key: bool  # 是否关键字段（x-key-fields）

    @property
    def field(self) -> str:
        return self.target.rsplit("/", 1)[-1]


def _load_schema(relative: str) -> dict:
    return json.loads((SCHEMA_DIR / relative).read_text(encoding="utf-8"))


def _kind_and_enum(sub: dict) -> tuple[str, tuple | None, str]:
    """从参数值子 schema 中读出类型、枚举与说明。"""
    parts = sub.get("allOf", [sub])
    kind, enum = "number", None
    for p in parts:
        ref = p.get("$ref", "")
        if "#/$defs/" in ref:
            kind = ref.rsplit("/", 1)[-1]
        value = p.get("properties", {}).get("value", {})
        if "enum" in value:
            enum = tuple(value["enum"])
        elif "const" in value:
            enum = (value["const"],)
        elif "anyOf" in value and "enum" in value["anyOf"][0]:
            enum = tuple(value["anyOf"][0]["enum"])
    return kind, enum, sub.get("description", "")


def _unit_for(field: str) -> str | None:
    try:
        return standard_unit(field)[1]
    except UnitError:
        return None


@cache
def targets(category: str) -> dict[str, tuple[Target, tuple[str, ...]]]:
    """品类的全部抽取目标：target → (Target, 校验用的 schema 引用；有多个时符合任一即可)。"""
    cat = _load_schema(f"categories/{category}.schema.json")
    key_fields = set(cat.get("x-key-fields", []))
    out: dict[str, tuple[Target, tuple[str, ...]]] = {}
    cat_id = f"{ID_BASE}categories/{category}.schema.json"
    for name, sub in cat["properties"]["params"]["properties"].items():
        kind, enum, desc = _kind_and_enum(sub)
        t = Target(f"params/{name}", kind, _unit_for(name), enum, desc, name in key_fields)
        out[t.target] = (t, (f"{cat_id}#/properties/params/properties/{name}",))
    for rule in cat["properties"].get("ports", {}).get("allOf", []):
        props = rule["contains"]["properties"]
        pid = props["id"]["const"]
        types = props["type"].get("enum") or [props["type"]["const"]]
        port_desc = rule.get("description", "")
        for ptype in types:
            spec = _load_schema(f"port-types/{ptype}.schema.json")["properties"]["spec"]["properties"]
            for name, sub in spec.items():
                tgt = f"ports/{pid}/{name}"
                ref = f"{ID_BASE}port-types/{ptype}.schema.json#/properties/spec/properties/{name}"
                if tgt in out:  # 端口允许多种类型时，同名字段符合任一类型即可
                    out[tgt] = (out[tgt][0], (*out[tgt][1], ref))
                    continue
                kind, enum, desc = _kind_and_enum(sub)
                desc = "；".join(x for x in (port_desc, desc) if x)
                out[tgt] = (Target(tgt, kind, _unit_for(name), enum, desc, False), (ref,))
    for name in CATEGORY_DIMS[category]:
        t = Target(f"dims/{name}", "number", _unit_for(name), None, DIMS[name], False)
        out[t.target] = (t, (f"{ID_BASE}common/param-value.schema.json#/$defs/number",))
    return out


def field_catalog(category: str) -> str:
    """给 LLM 的字段清单（每行一个 target）。"""
    lines = []
    for t, _ in targets(category).values():
        bits = [t.target, t.kind]
        if t.unit:
            bits.append(f"标准单位 {t.unit}")
        if t.enum:
            bits.append("可选值 " + " | ".join(map(str, t.enum)))
        if t.description:
            bits.append(t.description)
        if t.key:
            bits.append("关键字段")
        lines.append(" ; ".join(bits))
    return "\n".join(lines)


# ---------------------------------------------------------------- 提示词与工具

SYSTEM_PROMPT = """你是机电零件规格书的抽取助手。只报告规格书上实际印出的内容，不推测、不补全、不换算单位。

规则：
1. 只使用字段清单中的 target。清单里没有的参数不要报告。
2. 数值按印出的数字写（含正负号），单位按印出的写法写在 printed_unit（如 kgf·cm、×10⁻⁴ kg·m²、r/min、A(0-p)）；不要换算。
   没有标准单位的字段（孔数、位数、相数、减速比等）printed_unit 留空。
3. printed_text 是数值所在的那一个单元格（或正文中的那段文字）的原文。范围写 min/max，公差写 nominal/tol_upper/tol_lower
   （±a 写成 tol_upper=a、tol_lower=-a），单值写 value；printed_text 中的每个数字都要对应到这些键之一，不多不少。
4. 枚举字段（有可选值的）把原文映射到可选值之一写进 value；printed_text 仍写原文。布尔字段写 true/false。
5. quote 逐字摘自该页的同一行（表格的一行或正文的一行），须包含叫法 printed_label、printed_text 和印出的单位。
6. 有工况（如“输入转速 2000 r/min 时”）就把同一行里的原文写进 condition。
7. 同一数值适用于多个 target（如方法兰边长既是 ports/mount_flange/square_size_mm 又是 dims/square_mm）时，分别报告。
8. confidence 是你对这一项读得对的把握（0–1）。读不清或拿不准的宁可不报。
9. vendor、model 按原文写；读不到就不写。"""

TOOL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "vendor": {"type": "string"},
        "model": {"type": "string"},
        "series": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "value": {"description": "单值：印出的数字、映射后的枚举值、布尔值或字符串列表"},
                    "min": {"type": "number"},
                    "max": {"type": "number"},
                    "nominal": {"type": "number"},
                    "tol_upper": {"type": "number"},
                    "tol_lower": {"type": "number"},
                    "printed_label": {"type": "string"},
                    "printed_text": {"type": "string"},
                    "printed_unit": {"type": "string"},
                    "page": {"type": "integer"},
                    "quote": {"type": "string"},
                    "condition": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["target", "printed_label", "printed_text", "printed_unit", "page", "quote", "confidence"],
            },
        },
    },
    "required": ["items"],
}


def build_request(document: Document, category: str, *, model: str = DEFAULT_MODEL,
                  prompt_version: str = PROMPT_VERSION) -> dict:
    if category not in CATEGORIES:
        raise ValueError(f"不支持的品类 {category}")
    user = (
        f"品类：{category}\n\n字段清单（target ; 类型 ; 标准单位 ; 可选值 ; 说明）：\n{field_catalog(category)}\n\n"
        f"规格书（共 {len(document.pages)} 页）：\n{document.to_prompt_text()}"
    )
    return {
        "model": model,
        "prompt_version": prompt_version,
        "system": SYSTEM_PROMPT,
        "user": user,
        "tool": {"name": TOOL_NAME, "description": "记录从规格书抽取的参数", "input_schema": TOOL_SCHEMA},
    }


def request_key(request: dict) -> str:
    canonical = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 客户端


class LLMClient(Protocol):
    def complete(self, request: dict) -> dict:
        """返回 {"id": 响应 id, "tool_input": 工具输入, "simulated": bool}。"""


class RecordingMissing(LookupError):
    pass


class RecordedClient:
    """回放录制的响应；找不到即报错，不联网。"""

    def __init__(self, directory: Path = RECORDINGS_DIR):
        self.directory = Path(directory)

    def complete(self, request: dict) -> dict:
        key = request_key(request)
        path = self.directory / f"{key}.json"
        if not path.is_file():
            raise RecordingMissing(f"没有录制 {key}（提示词版本 {request['prompt_version']}）；请在本地用 --record 录制")
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec.get("request_key") != key:
            raise RecordingMissing(f"录制文件 {path.name} 的请求哈希不符")
        return rec["response"]


def write_recording(directory: Path, request: dict, response: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    key = request_key(request)
    path = directory / f"{key}.json"
    rec = {
        "request_key": key,
        "model": request["model"],
        "prompt_version": request["prompt_version"],
        "response": response,
    }
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """读取本地 .env（不入 git）；已有的环境变量不覆盖。"""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(name, value)


class AnthropicClient:
    """真实调用 Anthropic Messages API；record_dir 不为空时同时写录制。"""

    def __init__(self, record_dir: Path | None = None):
        load_dotenv()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("未设置 ANTHROPIC_API_KEY（放在环境变量或本地 .env 中）")
        import anthropic  # 可选依赖：pip install -e ".[llm]"

        self._client = anthropic.Anthropic()
        self.record_dir = record_dir

    def complete(self, request: dict) -> dict:
        msg = self._client.messages.create(
            model=request["model"],
            max_tokens=16000,
            temperature=0,
            system=request["system"],
            tools=[request["tool"]],
            tool_choice={"type": "tool", "name": request["tool"]["name"]},
            messages=[{"role": "user", "content": request["user"]}],
        )
        if getattr(msg, "stop_reason", None) != "tool_use":
            raise RuntimeError(f"LLM 没有正常完成工具调用（stop_reason={getattr(msg, 'stop_reason', None)}），不写录制")
        blocks = [b for b in msg.content if getattr(b, "type", "") == "tool_use"]
        if len(blocks) != 1:
            raise RuntimeError(f"LLM 响应中有 {len(blocks)} 个工具调用，应为 1 个")
        response = {"id": msg.id, "tool_input": blocks[0].input, "simulated": False}
        if self.record_dir is not None:
            write_recording(self.record_dir, request, response)
        return response


# ---------------------------------------------------------------- 核对（纯函数）

_WS = re.compile(r"\s+")
_NUMERIC_KEYS = ("value", "min", "max", "nominal", "tol_upper", "tol_lower")
# 数字（可带符号）；是否算一个“完整的数字”由 _tokens 按前后字符判断
_TOKEN = re.compile(r"([±+\-−]?)(\d+(?:[.,]\d+)*)")
_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
_SCI = re.compile(r"\s*[×x]\s*10([⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+)")
_THOUSANDS = re.compile(r"^\d{1,3}(?:,\d{3})+$")
_RATIO = re.compile(r"^(?:i\s*=\s*)?(\d+(?:\.\d+)?)(?:\s*:\s*1)?$|^1\s*[:/]\s*(\d+(?:\.\d+)?)$")
# 无标准单位的字段（孔数、位数、相数等）允许印出的计数单位
_UNITLESS = {"", "-", "—", "pcs", "pc", "个", "bit", "bits", "位", "相", "phase", "phases"}
_LIST_SEP = re.compile(r"\s*(?:,|，|、|;|；|\s/\s)\s*")
_BOOL_WORDS = {"true", "false"}
_WORD = re.compile(r"[0-9A-Za-z]+(?:[.][0-9A-Za-z]+)*")
# 单位两侧不能紧挨的字符：避免 N·m 匹配到 kN·m、A 匹配到 A(0-p)、g 匹配到 kg
_UNIT_BEFORE = r"(?<![A-Za-z0-9·/^⁻\-])"
_UNIT_AFTER = r"(?![A-Za-z0-9·/^²³⁰¹⁴⁵⁶⁷⁸⁹⁻(])"
_UNIT_TOKEN = re.compile(r"[^\s|\[\]（）,，;；:：]+")


def _squash(text: str) -> str:
    return _WS.sub("", text or "")


def _spaced(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def _loose(text: str) -> str:
    """宽松比较：忽略大小写、空白与分隔符（CiA 402 与 cia402 视为相同）。"""
    return re.sub(r"[\W_]+", "", (text or "").casefold())


def _is_number(x: Any) -> bool:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(float(x))
    except OverflowError:
        return False


@dataclass(frozen=True)
class _Line:
    cells: tuple[str, ...]  # 去空白后的单元格；正文行只有一个“单元格”
    spaced: str  # 空白规范化后的整行
    is_row: bool
    header: str = ""  # 表格行：所在表格首行（表头）去空白后的文字

    @property
    def joined(self) -> str:
        return "".join(self.cells)


@dataclass(frozen=True)
class _Ctx:
    lines: dict[int, list[_Line]]
    page_spaced: dict[int, str]
    comma_thousands: bool | None  # 全文逗号是千分位（True）、小数点（False），判断不了为 None


def _context(document: Document) -> _Ctx:
    lines: dict[int, list[_Line]] = {}
    spaced: dict[int, str] = {}
    for p in document.pages:
        ls = []
        for t in p.tables:
            header = _squash(" ".join(c or "" for c in t.rows[0])) if t.rows else ""
            ls += [_Line(tuple(_squash(c or "") for c in row), _spaced(" ".join(c or "" for c in row)), True, header)
                   for row in t.rows]
        ls += [_Line((_squash(ln),), _spaced(ln), False) for ln in p.text.splitlines() if ln.strip()]
        lines[p.page] = ls
        spaced[p.page] = "\n".join(ln.spaced for ln in ls)
    text = "\n".join(spaced.values())
    dot = re.search(r"(?<![\d.,])\d+\.\d+(?![\d.,])", text) is not None
    comma_dec = re.search(r"(?<![\d.,])\d+,\d{1,2}(?![\d.,])", text) is not None
    comma_k = re.search(r"(?<![\d.,])\d{1,3}(?:,\d{3})+\.\d+(?![\d,])", text) is not None
    comma = True if (dot or comma_k) and not comma_dec else False if comma_dec and not dot else None
    return _Ctx(lines, spaced, comma)


def _tokens(text: str, comma_thousands: bool | None = None) -> tuple[list[float], str | None]:
    """印出文字中完整的数字（± 展开为正负两个；a×10⁻ⁿ 合成一个数），返回（数字表, 歧义原因）。

    紧挨在字母后面的数字不算（M5、IP65、h7、x0.8）；数字之间的“-”是范围连接号，不是负号。
    """
    slots: list[float] = []
    skip_until = 0
    for m in _TOKEN.finditer(text):
        if m.start() < skip_until:  # a×10⁻ⁿ 中的 10 已并入前一个数
            continue
        sign, digits = m.group(1), m.group(2)
        start = m.start(2) if not sign else m.start(1)
        before = text[start - 1] if start > 0 else ""
        if sign in ("-", "−") and before.isdigit():  # 200-240：范围连接号
            sign, before = "", sign
        if before and (before.isascii() and before.isalnum() or before in ".,") and sign != "±":
            continue
        end = m.end(2)
        if end < len(text) and (text[end].isdigit() or text[end] in ".,"):
            continue
        if "," in digits:
            if comma_thousands is True and _THOUSANDS.match(digits):
                digits = digits.replace(",", "")
            elif comma_thousands is False and digits.count(",") == 1 and "." not in digits:
                digits = digits.replace(",", ".")
            else:
                return [], f"数字 {digits!r} 中的逗号无法判断是千分位还是小数点"
        v = float(digits)
        sci = _SCI.match(text, end)
        if sci:
            v *= 10 ** int(sci.group(1).translate(_SUP))
            skip_until = sci.end()
        if sign == "±":
            slots += [v, -v]
        else:
            slots.append(-v if sign in ("-", "−") else v)
    return slots, None


def _split_sci_unit(text: str, unit: str) -> tuple[str, str]:
    """“1.2×10⁻⁴” 配 “×10⁻⁴ kg·m²”：指数只算一次。返回（取数用的文字, 在原文中核对的单位）。"""
    m = re.match(r"\s*([×x]\s*10[⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+)\s*(.*)$", unit)
    tail = re.search(r"\s*[×x]\s*10[⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+\s*$", text)
    if m and tail and _squash(tail.group()) == _squash(m.group(1)):
        return text[: tail.start()], m.group(2)
    return text, unit


def _check_numbers(p: dict, keys: list[str], text: str, target: str, comma: bool | None) -> str | None:
    """给出的每个数都对应印出文字中的一个完整数字，不多不少（符号也要一致）。"""
    if target == "params/ratio":
        m = _RATIO.match(text.strip())
        if not m or keys != ["value"]:
            return f"减速比写法无法核对：{text!r}"
        n = float(m.group(1) or m.group(2))
        return None if math.isclose(p["value"], n, rel_tol=1e-9) else f"value={p['value']} 与印出的减速比 {n} 不符"
    slots, why = _tokens(text, comma)
    if why:
        return why
    if len(slots) != len(keys):
        return f"印出的文字 {text!r} 中的数字与给出的 {keys} 不一一对应"
    for k in keys:
        hit = next((i for i, v in enumerate(slots) if math.isclose(p[k], v, rel_tol=1e-9, abs_tol=1e-12)), None)
        if hit is None:
            return f"{k}={p[k]} 不在印出的文字 {text!r} 中"
        slots.pop(hit)
    return None


def _bounded(text: str) -> str:
    """把印出文字变成有边界的正则：开头是字母或数字时前面不能紧挨字母、数字、小数点，结尾同理。"""
    t = re.escape(_spaced(text))
    before = r"(?<![A-Za-z0-9.,])" if text[:1].isascii() and text[:1].isalnum() else ""
    after = r"(?![A-Za-z0-9.,])" if text[-1:].isascii() and text[-1:].isalnum() else ""
    return before + t + after


def _unit_in(spaced: str, unit: str) -> bool:
    return re.search(_UNIT_BEFORE + re.escape(_spaced(unit)) + _UNIT_AFTER, spaced) is not None


def _value_in_line(line: _Line, text: str, label: str, unit: str) -> bool:
    t, u = _squash(text), _squash(unit)
    if line.is_row:
        return any(c == t or (u and c in (t + u, u + t)) for c in line.cells)
    # 正文行：数值紧跟在叫法之后，中间不夹其他数字（防止借用同一句里另一个参数的值）
    low = line.spaced.casefold()
    i = low.find(_spaced(label).casefold())
    if i < 0:
        return False
    rest = line.spaced[i + len(_spaced(label)):]
    m = re.search(_bounded(text), rest)
    return m is not None and not _tokens(rest[: m.start()])[0]


def _unit_candidates(ctx: _Ctx, page: int) -> set[str]:
    """本页上看起来是单位的写法：单独成格的、紧跟在数字后面的、写在括号里的。"""
    out: set[str] = set()
    for ln in ctx.lines[page]:
        if ln.is_row:
            out |= {c for c in ln.cells if c and len(c) <= 16 and not any(ch.isdigit() for ch in c.split("×")[0])}
        out |= {m.group(1) for m in re.finditer(r"\d\s*([^\s\d|,;，；()（）\[\]]{1,12})", ln.spaced)}
        out |= {m.group(1).strip() for m in re.finditer(r"[\[(（]([^\])）]{1,16})[\])）]", ln.spaced)}
    return out


def _other_units(ctx: _Ctx, page: int, unit: str, field: str) -> list[str]:
    """本页上与该字段量纲相同、但换算系数不同的其他单位写法。"""
    try:
        mine = to_standard(1.0, unit, field)
    except UnitError:
        return []
    out = set()
    for tok in _unit_candidates(ctx, page):
        try:
            f = to_standard(1.0, tok, field)
        except (UnitError, ValueError):
            continue
        if not math.isclose(f, mine, rel_tol=1e-9):
            out.add(tok)
    return sorted(out)


def _locate(ctx: _Ctx, p: dict, unit: str, field: str) -> tuple[str | None, list[str]]:
    """在引用所在的那一行核对叫法、数值、单位、工况；返回（拒绝原因, 注意事项）。"""
    page = p["page"]
    quote = _squash(p["quote"].replace("|", ""))
    text, label = p["printed_text"], p["printed_label"]
    cond = p.get("condition") if isinstance(p.get("condition"), str) else ""
    if _squash(text) not in quote:
        return "原文引用中没有印出的文字", []
    candidates = [ln for ln in ctx.lines[page] if quote and quote in ln.joined]
    if not candidates:
        return f"原文引用在第 {page} 页的任何一行中都找不到", []
    best = "引用所在行中找不到与印出文字完全一致的数值"
    page_squashed = _squash(ctx.page_spaced[page])
    for ln in candidates:
        notes: list[str] = []
        if not _value_in_line(ln, text, label, unit):
            continue
        if _loose(label) not in _loose(ln.joined):
            if ln.is_row and _loose(label) in _loose(ln.header):
                notes.append(f"叫法 {label!r} 在表头，须核对所在列")
            else:
                best = "叫法不在引用所在的行中"
                continue
        if cond.strip() and _squash(cond) not in ln.joined:
            if _squash(cond) not in page_squashed:
                best = f"工况 {cond!r} 在第 {page} 页找不到"
                continue
            notes.append(f"工况 {cond!r} 不在同一行，取自本页其他位置（表头或脚注），须核对")
        if unit and not _unit_in(ln.spaced, unit):
            if not _unit_in(ctx.page_spaced[page], unit):
                best = f"单位 {unit!r} 不在引用所在的行中，本页也找不到"
                continue
            others = _other_units(ctx, page, unit, field)
            if others:
                best = f"单位 {unit!r} 不在同一行，而本页还有其他同类单位 {others}，无法判断"
                continue
            notes.append(f"单位 {unit} 不在同一行，取自本页其他位置")
        if ln.is_row:
            numeric_cells = [c for c in ln.cells if c != _squash(text) and _tokens(c)[0] and not _loose(c).isalpha()]
            if len(numeric_cells) >= 1 and len(ln.cells) > 3:
                notes.append("该行有多个数值，须核对型号列")
        return None, notes
    return best, []


def _printed(p: dict) -> dict:
    out = {"text": p["printed_text"].strip() if isinstance(p.get("printed_text"), str) and p["printed_text"].strip()
           else "?", "unit": p["printed_unit"] if isinstance(p.get("printed_unit"), str) else ""}
    for src, dst in (("printed_label", "label"), ("quote", "quote")):
        if isinstance(p.get(src), str) and p[src].strip():
            out[dst] = p[src]
    return out


def _unit_factor(spec: Target, unit: str, text: str) -> tuple[float | None, str | None]:
    """返回（换算到标准单位的乘数, 需要注意的说明）；单位不对时乘数为 None，说明为拒绝原因。"""
    if spec.unit is None:
        if unit.casefold() not in _UNITLESS:
            return None, f"字段 {spec.target} 无单位，但印有单位 {unit!r}"
        return 1.0, None
    if not unit and not spec.field.endswith("_ratio"):
        return None, f"字段 {spec.target} 有单位，须写印出的单位"
    try:
        factor = to_standard(1.0, unit, spec.field)
    except UnitError as exc:
        return None, f"单位：{exc}"
    return factor, (f"单位换算：{text} {unit} → 标准单位 {spec.unit}" if factor != 1 else None)


def _check_text_value(spec: Target, value: Any, text: str) -> tuple[str | None, list[str]]:
    """非数值字段：自由文字须与印出的一致；枚举与布尔是 LLM 的映射，核不了时标注复核。"""
    items = value if isinstance(value, list) else [value]
    parts = [x for x in _LIST_SEP.split(text) if x.strip()]
    if spec.kind == "boolean":
        if not isinstance(value, bool):
            return "布尔字段须写 true/false", []
        return None, ([] if _loose(text) in _BOOL_WORDS and _loose(text) == str(value).lower()
                      else [f"布尔映射：{text!r} → {value}，未自动核对"])
    if spec.enum is not None:
        if spec.kind == "integer":
            slots, why = _tokens(text)
            if why:
                return why, []
            if slots:
                return (None, []) if slots == [value] else (f"value={value} 与印出的数字 {slots} 不符", [])
        if sorted(_loose(str(x)) for x in items) == sorted(_loose(x) for x in parts):
            return None, []
        return None, [f"枚举映射：{text!r} → {value}，未自动核对"]
    if not all(isinstance(x, str) and _loose(x) for x in items):
        return f"值 {value!r} 不是非空文字", []
    if sorted(_loose(x) for x in items) == sorted(_loose(x) for x in parts):
        return None, []
    # 值是印出文字中完整的一个词（如“P5 级”中的 P5）：接受，但标注复核；截断的词（M5x0.8 中的 M5）不接受
    words = set(re.findall(r"[0-9a-z]+(?:[.][0-9a-z]+)*", text.casefold()))
    if not isinstance(value, list) and _WORD.fullmatch(value.strip()) and value.strip().casefold() in words:
        return None, [f"文字取自原文的一部分：{text!r} → {value!r}，需复核"]
    return f"值 {value!r} 与印出的文字 {text!r} 不一致", []


def check_proposal(p: Any, category: str, doc_id: str, ctx: _Ctx) -> tuple[dict | None, str | None]:
    """核对一条提议：通过返回（抽取项, None），否则返回（None, 原因）。"""
    if not isinstance(p, dict):
        return None, "提议不是对象"
    tgt = p.get("target")
    if not isinstance(tgt, str):
        return None, "target 不是字符串"
    tmap = targets(category)
    if tgt not in tmap:
        return None, f"target {tgt!r} 不属于品类 {category}"
    spec, refs = tmap[tgt]
    page = p.get("page")
    if not isinstance(page, int) or isinstance(page, bool) or page not in ctx.lines:
        return None, f"页码 {page!r} 不存在"
    for k in ("printed_label", "printed_text", "quote"):
        if not isinstance(p.get(k), str) or not p[k].strip():
            return None, f"缺少 {k}"
    if not isinstance(p.get("printed_unit", ""), str):
        return None, "printed_unit 须为字符串"
    if "condition" in p and p["condition"] is not None and not isinstance(p["condition"], str):
        return None, "condition 须为字符串"
    conf = p.get("confidence")
    if not _is_number(conf) or not 0 <= conf <= 1:
        return None, "置信度须在 0–1 之间"
    text = p["printed_text"].strip()
    unit = p.get("printed_unit", "").strip()
    unit_for_line = "" if spec.unit is None and unit.casefold() in _UNITLESS else unit
    text, unit_on_page = _split_sci_unit(text, unit)
    if unit_for_line and unit_on_page != unit:
        unit_for_line = unit_on_page
    why, issues = _locate(ctx, p, unit_for_line, spec.field)
    if why:
        return None, why

    keys = [k for k in _NUMERIC_KEYS if k in p and p[k] is not None]
    pv: dict = {}
    if spec.kind in ("number", "integer") and spec.enum is None:
        shape = set(keys)
        if not (keys == ["value"] or shape and shape <= {"min", "max"}
                or "nominal" in shape and shape <= {"nominal", "tol_upper", "tol_lower"}):
            return None, f"数值写法不合法：{sorted(shape) or '无数值'}"
        if not all(_is_number(p[k]) for k in keys):
            return None, "数值须为有限数字"
        why = _check_numbers(p, keys, text, tgt, ctx.comma_thousands)
        if why:
            return None, why
        factor, note = _unit_factor(spec, unit, text)
        if factor is None:
            return None, note
        issues += [note] if note else []
        pv.update({k: p[k] * factor for k in keys})
        if not all(math.isfinite(v) for v in pv.values()):
            return None, "换算后超出数值范围"
        if spec.kind == "integer":
            pv.update({k: int(pv[k]) for k in keys if float(pv[k]).is_integer()})
        if "min" in pv and "max" in pv and pv["min"] > pv["max"]:
            return None, "下限大于上限"
        if "tol_upper" in pv and "tol_lower" in pv and pv["tol_lower"] > pv["tol_upper"]:
            return None, "公差须满足 下偏差 ≤ 上偏差（ADR-0022）"
        if tgt.startswith("dims/") and any(pv[k] <= 0 for k in keys if k in ("value", "min", "max", "nominal")):
            return None, "尺寸须为正数"
    elif spec.kind == "number_pair":
        value = p.get("value")
        if keys != ["value"] or not isinstance(value, list) or len(value) != 2 or not all(map(_is_number, value)):
            return None, "成对尺寸须写成 value: [数, 数]"
        slots, why = _tokens(text, ctx.comma_thousands)
        if why or sorted(slots) != sorted(value):
            return None, why or f"value={value} 与印出的文字 {text!r} 不一致"
        factor, note = _unit_factor(spec, unit, text)
        if factor is None:
            return None, note
        issues += [note] if note else []
        pv["value"] = [v * factor for v in value]
    else:
        if keys != ["value"]:
            return None, "非数值字段只能写 value"
        if spec.unit is None and unit.casefold() not in _UNITLESS:
            return None, f"字段 {tgt} 无单位，但印有单位 {unit!r}"
        why, notes = _check_text_value(spec, p["value"], text)
        if why:
            return None, why
        issues += notes
        pv["value"] = p["value"]
    if isinstance(p.get("condition"), str) and p["condition"].strip():
        pv["condition"] = p["condition"].strip()
    pv.update({"source": {"doc": doc_id, "page": page}, "method": "extracted",
               "confidence": float(conf), "reviewed": False})
    schema_errors = [[e.message for e in validator_for_ref(r).iter_errors(pv)] for r in refs]
    if all(schema_errors):
        return None, "不符合字段 schema：" + "；".join(schema_errors[0][:3])
    item = {"target": tgt, "value": pv, "printed": _printed(p)}
    if issues:
        item["issues"] = issues
    return item, None


def _same_value(a: dict, b: dict) -> bool:
    for k in (*_NUMERIC_KEYS, "condition"):
        x, y = a.get(k), b.get(k)
        if _is_number(x) and _is_number(y):
            if not math.isclose(x, y, rel_tol=1e-9):
                return False
        elif x != y:
            return False
    return True


def verify(tool_input: Any, document: Document, category: str, doc_id: str) -> dict:
    """核对 LLM 的全部提议，返回抽取结果中的 vendor/model/series/items/rejected/missing_key_fields。"""
    ctx = _context(document)
    proposals = tool_input.get("items") if isinstance(tool_input, dict) else None
    if not isinstance(proposals, list):
        proposals = []
    accepted: dict[str, list[dict]] = {}
    rejected: list[dict] = []
    for p in proposals:
        item, reason = check_proposal(p, category, doc_id, ctx)
        if item is None:
            r: dict = {"reason": reason}
            if isinstance(p, dict):
                if isinstance(p.get("target"), str):
                    r["target"] = p["target"]
                if isinstance(p.get("page"), int) and not isinstance(p.get("page"), bool):
                    r["page"] = p["page"]
                if isinstance(p.get("printed_text"), str) and p["printed_text"].strip():
                    r["printed"] = _printed(p)
            rejected.append(r)
            continue
        accepted.setdefault(item["target"], []).append(item)
    items = []
    for tgt, group in accepted.items():
        first = group[0]
        if all(_same_value(first["value"], g["value"]) for g in group[1:]):
            items.append(max(group, key=lambda g: g["value"]["confidence"]))
        else:
            rejected += [{"target": tgt, "page": g["value"]["source"]["page"], "printed": g["printed"],
                          "reason": "同一 target 有互相矛盾的值"} for g in group]
    found = {i["target"] for i in items}
    missing = [t.target for t, _ in targets(category).values() if t.key and t.target not in found]
    out: dict = {"items": items, "rejected": rejected, "missing_key_fields": missing}
    all_text = "\n".join(ctx.page_spaced.values())
    for k in ("vendor", "model", "series"):
        v = tool_input.get(k) if isinstance(tool_input, dict) else None
        if not isinstance(v, str) or not v.strip():
            continue
        if re.search(r"(?<![A-Za-z0-9-])" + re.escape(_spaced(v)) + r"(?![A-Za-z0-9-])", all_text):
            out[k] = v.strip()
        else:
            rejected.append({"target": k, "printed": {"text": v.strip()}, "reason": f"{k} 在规格书中找不到"})
    return out


# ---------------------------------------------------------------- 入口


class ExtractionInvalid(RuntimeError):
    """抽取结果不符合 schema：属于代码缺陷。"""


def extract_document(document: Document, category: str, doc_id: str, client: LLMClient, *,
                     model: str | None = None, prompt_version: str = PROMPT_VERSION) -> dict:
    if not document.pages:
        raise ValueError("文档没有任何页面")
    if not re.fullmatch(r"src-[a-z0-9]+(-[a-z0-9]+)*", doc_id or ""):
        raise ValueError(f"来源文档 id 格式不对：{doc_id!r}")
    model = model or os.environ.get("FAP_LLM_MODEL") or DEFAULT_MODEL
    request = build_request(document, category, model=model, prompt_version=prompt_version)
    response = client.complete(request)
    checked = verify(response.get("tool_input") or {}, document, category, doc_id)
    extractor = {"model": model, "prompt_version": prompt_version}
    if response.get("id"):
        extractor["response_id"] = str(response["id"])
    if response.get("simulated"):
        extractor["simulated"] = True
    result = {
        "format": "extraction/1",
        "document": {"doc": doc_id, "sha256": document.sha256, "pages": len(document.pages)},
        "category": category,
        **{k: checked[k] for k in ("vendor", "model", "series") if k in checked},
        "extractor": extractor,
        "items": checked["items"],
        "rejected": checked["rejected"],
        "missing_key_fields": checked["missing_key_fields"],
    }
    errs = errors("extraction.schema.json", result)
    if errs:
        raise ExtractionInvalid("；".join(errs[:5]))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用 LLM 从规格书 PDF 抽取参数（ADR-0021）")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--category", required=True, choices=CATEGORIES)
    parser.add_argument("--doc", required=True, help="data/sources.yaml 中登记的来源文档 id")
    parser.add_argument("--out", type=Path, help="抽取结果写到此文件（默认打印）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path, default=None, help="只回放此目录中的录制（默认 tests/recordings/llm）")
    mode.add_argument("--record", type=Path, nargs="?", const=RECORDINGS_DIR, default=None,
                      help="真实调用并把响应写入录制目录（需要 ANTHROPIC_API_KEY）")
    mode.add_argument("--live", action="store_true", help="真实调用但不录制")
    args = parser.parse_args(argv)

    # 未登记或未核实条款的来源文档不处理（CLAUDE.md；测试专用文档只用于模拟规格书）
    from kb.sources import SourceRegistry

    why = SourceRegistry.load().check_document(args.doc, allow_test=True)
    if why:
        print(why, file=sys.stderr)
        return 2
    try:
        document = extract(args.pdf)
        if args.record is not None or args.live:
            client: LLMClient = AnthropicClient(record_dir=args.record)
        else:
            client = RecordedClient(args.replay or RECORDINGS_DIR)
        result = extract_document(document, args.category, args.doc, client)
    except (RecordingMissing, ExtractError, ValueError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
