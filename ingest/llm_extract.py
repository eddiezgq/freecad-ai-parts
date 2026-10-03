"""LLM 结构化抽取（issue #29，ADR-0021）。

流程：PDF 提取结果（#28）+ 品类字段清单 → LLM 通过工具调用提议抽取项 → 代码逐项核对 → 抽取结果
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

from ingest.pdf_extract import Document, ExtractError, extract, parse_pages
from ingest.units import UnitError, standard_unit, to_standard
from kb.validation import ID_BASE, SCHEMA_DIR, errors, validator_for_ref

PROMPT_VERSION = "extract/3"
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


# 部分模型不支持强制指定工具（tool_choice 为 tool / any），改为 auto，并在提示词中要求调用
TOOL_INSTRUCTION = "\n\n只通过调用工具 {name} 一次提交全部结果，不要只用文字回答。"


TARGET_INSTRUCTION = (
    "目标型号：{model}\n"
    "这份目录含多个型号。只报告目标型号的数值：表格按型号分列时取该型号所在列，按型号分行时取该型号所在行；"
    "对所有型号通用的数值（如整个系列共用的一项）也报告。其他型号的数值一律不报。"
    "model 写目标型号在目录中印出的写法。\n\n"
)


def build_request(document: Document, category: str, *, model: str = DEFAULT_MODEL,
                  prompt_version: str = PROMPT_VERSION, target_model: str | None = None,
                  excerpt: bool = False) -> dict:
    """target_model、excerpt 只在多型号目录中使用（ADR-0040）；不用时请求与以前完全相同，已有录制仍可回放。"""
    if category not in CATEGORIES:
        raise ValueError(f"不支持的品类 {category}")
    if excerpt:
        pages = "、".join(str(p.page) for p in document.pages)
        head = f"规格书节选（第 {pages} 页，页码为原文页码）"
    else:
        head = f"规格书（共 {len(document.pages)} 页）"
    target = TARGET_INSTRUCTION.format(model=target_model.strip()) if target_model else ""
    user = (
        f"品类：{category}\n\n字段清单（target ; 类型 ; 标准单位 ; 可选值 ; 说明）：\n{field_catalog(category)}\n\n"
        f"{target}{head}：\n{document.to_prompt_text()}"
    )
    return {
        "model": model,
        "prompt_version": prompt_version,
        "system": SYSTEM_PROMPT + TOOL_INSTRUCTION.format(name=TOOL_NAME),
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
            system=request["system"],
            tools=[request["tool"]],
            tool_choice={"type": "auto"},  # 部分模型不支持 tool / any；提示词中要求调用工具
            messages=[{"role": "user", "content": request["user"]}],
        )
        if getattr(msg, "stop_reason", None) != "tool_use":
            raise RuntimeError(f"LLM 没有调用工具（stop_reason={getattr(msg, 'stop_reason', None)}），不写录制；可重试")
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


# 排版变体与符号字体的私用区字形：∗ ＊ 视同 *；安川规格书中 U+F09E 是 N·m 里的点，U+F06F 是型号中的占位框（A5A□A2□），
# 模型看到的是缺字，引用时会略去，比较时一并去掉
_LOOKALIKE = str.maketrans({"∗": "*", "＊": "*", "﹡": "*", "⁎": "*", "\uf09e": None, "\uf06f": None})
_FOOTNOTE = re.compile(r"\*\s*\d+(?:\s*,\s*\*\s*\d+)*")


def _squash(text: str) -> str:
    return _WS.sub("", (text or "").translate(_LOOKALIKE))


def _spaced(text: str) -> str:
    return _WS.sub(" ", (text or "").translate(_LOOKALIKE)).strip()


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
    header_cells: tuple[str, ...] = ()  # 表格行：表头各单元格（去空白）
    head_rows: tuple[tuple[str, ...], ...] = ()  # 表格行：表格前三行（多层表头，型号常在第二、三行）

    @property
    def joined(self) -> str:
        return "".join(self.cells)


@dataclass(frozen=True)
class _Ctx:
    lines: dict[int, list[_Line]]
    page_spaced: dict[int, str]
    comma_thousands: bool | None  # 全文逗号是千分位（True）、小数点（False），判断不了为 None
    target_model: str = ""  # 多型号目录的目标型号（_loose 后）；空表示单型号规格书
    target_raw: str = ""  # 目标型号原文（按“-”分段核对尺寸、减速比等键列）
    layout: dict[int, list[_Line]] | None = None  # 按文字对齐切出的行（没有边框的表），引用核对不通过时再试


def _fill_down(rows: list[list[str | None]]) -> list[list[str | None]]:
    """纵向合并的单元格：行首的空格子取上一行同列的文字（如“Mass (kg)”跨 CSG、CSF 两行，“14”跨各减速比）。

    只补行首连续的空格子，表头前两行不补。
    """
    out: list[list[str | None]] = []
    for i, row in enumerate(rows):
        row = list(row)
        if i >= 2 and out:
            prev = out[-1]
            for j, c in enumerate(row):
                if (c or "").strip():
                    break
                if j < len(prev) and (prev[j] or "").strip():
                    row[j] = prev[j]
        out.append(row)
    return out


def _is_label_row(cells: tuple[str, ...]) -> bool:
    filled = [c for c in cells if c]
    return len(filled) >= 2 and sum(bool(re.fullmatch(r"[-+±−()\d.]+", c)) for c in filled) <= len(filled) * 0.3


def _layout_lines(rows: list[list[str]]) -> list[_Line]:
    """按文字对齐切出的行：每行的表头取它上方最近的几行“叫法行”（多数格子不是数字）。"""
    cells = [tuple(_squash(c) for c in r) for r in rows]
    out = []
    for i, (raw, row) in enumerate(zip(rows, cells, strict=True)):
        heads: list[tuple[str, ...]] = []
        for j in range(i - 1, max(-1, i - 13), -1):
            if _is_label_row(cells[j]):
                heads.insert(0, cells[j])
                if len(heads) == 3:
                    break
            elif heads:
                break
        out.append(_Line(row, _spaced(" ".join(raw)), True, "".join(heads[0]) if heads else "",
                         heads[0] if heads else (), tuple(heads)))
    return out


def _context(document: Document, target_model: str | None = None) -> _Ctx:
    lines: dict[int, list[_Line]] = {}
    spaced: dict[int, str] = {}
    for p in document.pages:
        ls = []
        for t in p.tables:
            header = _squash(" ".join(c or "" for c in t.rows[0])) if t.rows else ""
            hcells = tuple(_squash(c or "") for c in t.rows[0]) if t.rows else ()
            heads = tuple(tuple(_squash(c or "") for c in r) for r in t.rows[:3])
            ls += [_Line(tuple(_squash(c or "") for c in row), _spaced(" ".join(c or "" for c in row)), True, header,
                         hcells, heads)
                   for row in _fill_down(t.rows)]
        ls += [_Line((_squash(ln),), _spaced(ln), False) for ln in p.text.splitlines() if ln.strip()]
        lines[p.page] = ls
        spaced[p.page] = "\n".join(ln.spaced for ln in ls)
    text = "\n".join(spaced.values())
    dot = re.search(r"(?<![\d.,])\d+\.\d+(?![\d.,])", text) is not None
    comma_dec = re.search(r"(?<![\d.,])\d+,\d{1,2}(?![\d.,])", text) is not None
    comma_k = re.search(r"(?<![\d.,])\d{1,3}(?:,\d{3})+\.\d+(?![\d,])", text) is not None
    comma = True if (dot or comma_k) and not comma_dec else False if comma_dec and not dot else None
    layout = {p.page: _layout_lines(p.layout_rows) for p in document.pages}
    return _Ctx(lines, spaced, comma, _loose(target_model or ""), (target_model or "").strip(), layout)


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
    """单位印在文字中（空白可有可无：“×10-4 kgm2”与“×10-4kgm2”相同）。"""
    body = r"\s*".join(re.escape(ch) for ch in _squash(unit))
    return bool(body) and re.search(_UNIT_BEFORE + body + _UNIT_AFTER, _spaced(spaced)) is not None


def _value_in_line(line: _Line, text: str, label: str, unit: str) -> bool:
    if line.is_row:
        return any(_cell_is(c, text, unit) for c in line.cells)
    # 正文行：数值紧跟在叫法之后，中间不夹其他数字（防止借用同一句里另一个参数的值）
    low = line.spaced.casefold()
    i = low.find(_spaced(label).casefold())
    if i < 0:
        return False
    rest = _FOOTNOTE.sub(" ", line.spaced[i + len(_spaced(label)):])
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


def _cell_is(cell: str, text: str, unit: str) -> bool:
    """单元格就是印出的数值（可带单位）；或数值后面括号里另有一个值（如“85.5(125.5)”，括号内为带制动器的型号）。"""
    t, u = _squash(text), _squash(unit)
    return cell == t or bool(u) and cell in (t + u, u + t) or bool(t) and _alt_cell(cell, t)


_UNIT_MM = re.compile(r"(?i)\bunits?\s*[:：]?\s*mm\b|单位\s*[:：]?\s*mm\b")
_TOL_TAIL = re.compile(r"(?:\+?0(?:\.\d+)?|\+\d+(?:\.\d+)?)[-−]\d+(?:\.\d+)?")


def _alt_cell(cell: str, t: str) -> bool:
    """“85.5(125.5)”：括号内为另一规格的值；“300-0.021”：名义值 30 后面印着上、下偏差 0 与 -0.021。"""
    if re.fullmatch(re.escape(t) + r"\([^()]+\)", cell):
        return True
    return cell.startswith(t) and "." not in t[-1:] and _TOL_TAIL.fullmatch(cell[len(t):]) is not None


def _word_is_cell(word: str, cell: str) -> bool:
    w = _squash(word)
    return bool(w) and (cell == w or _alt_cell(cell, w))


def _rows_for_text_line(lines: list[_Line], tl: _Line) -> list[_Line]:
    """正文行与表格行是同一行内容的两种抽取：
    - 首词是型号代码、其余与表格行一致（“A5A□A2□ 37.9 25 …”）
    - 全是数字，从表格行第一个非空格起至少两格逐格相同（格中括号内的另一个值不计）
    """
    words = tl.spaced.split(" ")
    out = []
    for ln in lines:
        if not ln.is_row:
            continue
        if len(words) >= 4 and re.search(r"[A-Za-z]", words[0]):
            rest = words[1:]
            if any(all(k + i < len(ln.cells) and _word_is_cell(w, ln.cells[k + i]) for i, w in enumerate(rest))
                   for k in range(len(ln.cells) - len(rest) + 1)):
                out.append(ln)
            continue
        if len(words) < 2 or not all(re.fullmatch(r"[-+±−]?\d+(?:\.\d+)?", w) for w in words):
            continue
        j = next((i for i, c in enumerate(ln.cells) if c), None)
        if j is None:
            continue
        hits = 0
        for i, w in enumerate(words):
            if j + i >= len(ln.cells) or not ln.cells[j + i]:
                break
            if not _word_is_cell(w, ln.cells[j + i]):
                break
            hits += 1
        if hits >= 2:  # 开头至少两格逐格相同；其余的数（如另起一列的质量）不在这一表格行中，按格核对时自然不通过
            out.append(ln)
    return out


def _model_col(row: tuple[str, ...], model: str) -> int | None:
    """表头行中目标型号所在的列：整格就是型号；或前缀写在左侧某格（如“型号 SGM7J-”），本格是后缀（如“02A”）。"""
    cells = [_loose(c) for c in row]
    if model in cells:
        return cells.index(model)
    for j, c in enumerate(cells):
        if c and model.endswith(c) and len(c) < len(model):
            prefix = model[: -len(c)]
            if any(h.endswith(prefix) for h in cells[:j] if h):
                return j
    return None


def _key_segments(raw: str) -> tuple[str, list[str]]:
    """型号的系列前缀（开头的字母）与纯数字的分段：CSF-14-50-2UH → ("csf", ["14", "50"])。"""
    m = re.match(r"[A-Za-z]+", raw)
    return (m.group().casefold() if m else ""), [x for x in re.split(r"[-\s]+", raw) if x.isdigit()]


def _value_col(line: _Line, text: str, unit: str) -> int | None:
    hits = [j for j, c in enumerate(line.cells) if _cell_is(c, text, unit)]
    return hits[0] if len(hits) == 1 else None


def _row_code(line: _Line, text_lines: list[_Line]) -> str | None:
    """表格行的型号格是空的（型号印在表格外）：找一行正文，首词是型号代码、其余与这一表格行的内容相同。"""
    for tl in text_lines:
        words = tl.spaced.split(" ")
        if len(words) >= 4 and re.search(r"[A-Za-z]", words[0]) and line in _rows_for_text_line([line], tl):
            return words[0]
    return None


def _model_suffix(line: _Line, model: str) -> str | None:
    """表头中写的型号前缀（如“Model SGM7J-”）之后的部分，即各行型号代码的开头。"""
    for row in line.head_rows:
        if row == line.cells:
            break
        for c in row:
            lc = _loose(c)
            for cut in range(len(model) - 1, 2, -1):
                if lc and lc.endswith(model[:cut]):
                    return model[cut:]
    return None


def _row_key_is(line: _Line, raw: str) -> bool:
    """按尺寸、减速比分行的表：行首的数字键与型号的数字分段完全一致（CSF-20-100 → 20 ¦ 100）。"""
    _, segs = _key_segments(raw)
    return bool(segs) and len(line.cells) > len(segs) and list(line.cells[:len(segs)]) == segs


def _model_column(line: _Line, model: str, text: str, unit: str, raw: str = "",
                  text_lines: list[_Line] | None = None) -> bool | None:
    """多型号目录：数值是否在目标型号的列（或行）中。True 已确认，False 不在，None 判断不了（交给复核）。"""
    if any(_loose(c) == model for c in line.cells):  # 按型号分行：型号就在这一行
        return True
    if line.cells and not line.cells[0] and text_lines:
        code, suffix = _row_code(line, text_lines), _model_suffix(line, model)
        if code and suffix:
            return _loose(code).startswith(suffix)
    if line.cells and re.fullmatch(r"[0-9A-Z]{3}[0-9A-Z]*", line.cells[0] or "") and re.search(r"[A-Z]", line.cells[0]):
        suffix = _model_suffix(line, model)  # 行首格就是型号代码（“04AA2”，表头写前缀“SGM7J-”）
        if suffix:
            return _loose(line.cells[0]).startswith(suffix)
    series, segs = _key_segments(raw)
    if series and any(_loose(c).endswith("series") and len(_loose(c)) > len("series")
                      and not _loose(c).startswith(series) for c in line.cells):
        return False  # 另一个系列的行（如 CSG Series 与 CSF Series 并列）
    if segs:
        # 按尺寸、减速比分行：行首的数字键须与型号的数字分段一致（CSF-14-50 → 14 ¦ 50）
        lead = []
        for c in line.cells:
            if not c.isdigit() or len(lead) == len(segs):
                break
            lead.append(c)
        if lead and len(lead) < len(line.cells):
            return lead == segs[:len(lead)]
    for row in line.head_rows or (line.header_cells,):
        if row == line.cells:  # 表头行本身
            break
        j = _model_col(row, model)
        if j is not None:
            return j < len(line.cells) and _cell_is(line.cells[j], text, unit)
    if segs:
        # 按尺寸分列：表头某一行以“Size”开头，各列是尺寸
        for row in line.head_rows:
            if row == line.cells:
                break
            first = next((c for c in row if c), "")
            if _loose(first).startswith("size") and segs[0] in row:
                j = row.index(segs[0])
                return j < len(line.cells) and _cell_is(line.cells[j], text, unit)
    return None


def _model_printed_split(ctx: _Ctx, raw: str) -> bool:
    """型号没有整串印出，但按目录的编排分开印出：
    - 表头（表格行或正文行）写前缀、各列写后缀（“Model SGM7J-” ¦ “A5A” ¦ “02A”）
    - 尺寸、减速比作为表格行的键（14 ¦ 50），其余字母分段（CSF、2UH）都印在所选页上
    """
    rows = [ln for lines in ctx.lines.values() for ln in lines if ln.is_row]
    if any(_model_columns(ctx, pg) is not None for pg in ctx.lines):
        return True
    _, segs = _key_segments(raw)
    words = [x for x in re.split(r"[-\s]+", raw) if x and not x.isdigit()]
    if not segs or not words:
        return False
    page_text = _loose("".join(ctx.page_spaced.values()))
    return all(_loose(w) in page_text for w in words) and any(
        list(ln.cells[:len(segs)]) == segs for ln in rows)


def _unit_in_column_head(line: _Line, text: str, unit: str) -> bool:
    """表格行：单位写在数值所在列的表头里（如“I×10−4kgm2”）。"""
    col = _value_col(line, text, unit) if line.is_row else None
    u = _squash(unit)
    return col is not None and bool(u) and any(col < len(r) and u in r[col] for r in line.head_rows
                                               if r != line.cells)


def _model_columns(ctx: _Ctx, page: int) -> tuple[int, int] | None:
    """本页型号的列序（第几列, 共几列）：表头行或正文行写成“Model SGM7J- A5A 01A …”的形式。"""
    model = ctx.target_model
    for ln in ctx.lines[page]:
        if ln.is_row:
            j = _model_col(ln.cells, model)
            if j is None:
                continue
            if _loose(ln.cells[j]) == model:  # 整格就是型号：其他整格型号在同一行
                names = [c for c in ln.cells if c]
            else:
                prefix = model[: -len(_loose(ln.cells[j]))]
                start = next((i for i in range(j) if ln.cells[i] and _loose(ln.cells[i]).endswith(prefix)), -1) + 1
                names = [c for c in ln.cells[start:] if c]
            if ln.cells[j] in names:
                return names.index(ln.cells[j]), len(names)
        else:
            words = ln.spaced.split(" ")
            _, segs = _key_segments(ctx.target_raw)
            if segs and _loose(ln.spaced).startswith("size"):  # “Size Symbol 14 17 20 …”：按尺寸分列
                nums = [w for w in words if re.fullmatch(r"\d+", w)]
                if segs[0] in nums and len(nums) >= 3:
                    return nums.index(segs[0]), len(nums)
            for i, w in enumerate(words):
                lw = _loose(w)
                if len(lw) >= 3 and model.startswith(lw) and model != lw and w.rstrip().endswith("-"):
                    names = [_loose(x) for x in words[i + 1:]]
                    suffix = model[len(lw):]
                    if suffix in names:
                        return names.index(suffix), len(names)
    return None


def _text_row_column(line: _Line, label: str, text: str, unit: str, cols: tuple[int, int]) -> tuple[bool, str]:
    """多型号目录的正文行（“Rated Output*1 W 50 100 … 750”）：去掉脚注标记与单位后，第 k 个数是目标型号的值；
    整行只有一个数时是各型号共用的合并格。返回（是否通过, 说明或拒绝原因）。"""
    i = line.spaced.casefold().find(_spaced(label).casefold())
    if i < 0:
        return False, "叫法不在引用所在的行中"
    rest = _FOOTNOTE.sub(" ", line.spaced[i + len(_spaced(label)):])
    if unit:
        rest = re.sub(_UNIT_BEFORE + re.escape(_spaced(unit)) + _UNIT_AFTER, " ", rest, count=1)
    if not _tokens(text)[0]:  # 文字值（如防护等级）：整行一段文字，各型号共用
        ok = _value_in_line(line, text, label, unit)
        return ok, ("文字值在型号表中各型号共用（合并单元格）" if ok else "引用所在行中找不到与印出文字完全一致的数值")
    words = [w for w in rest.split() if _tokens(w)[0]]
    if len(words) > 1 and any(re.search(r"[A-Za-z]", w) for w in rest.split()):
        # 夹着文字的规格行（“200 VAC to 240 VAC, 50 Hz/60 Hz”）不是逐型号的数值行，按共用的规格行核对
        ok = _value_in_line(line, text, label, unit)
        return ok, ("规格行，各型号共用" if ok else "引用所在行中找不到与印出文字完全一致的数值")
    k, n = cols
    if len(words) == n:
        return (_squash(words[k]) == _squash(text), "" if _squash(words[k]) == _squash(text)
                else "数值不在目标型号所在的列")
    if len(words) == 1 and _squash(words[0]) == _squash(text):
        return True, "该行只有一个数值，按各型号共用（合并单元格）处理"
    return False, f"该行有 {len(words)} 个数值，与 {n} 个型号列对不上"


def _label_prefixes(label: str) -> list[str]:
    """叫法本身，以及去掉末尾几个词后的说法（“Moment of Inertia I”的“I”是下一层表头）。"""
    words = _spaced(label).split(" ")
    return [_spaced(label)] + [" ".join(words[:k]) for k in range(len(words) - 1, 0, -1)
                               if len(_loose(" ".join(words[:k]))) >= 4]


def _label_span(line: _Line, label: str) -> range | None:
    """表格行：叫法在表头中的列（含向右合并的空格子）；找不到或不止一处时为 None。"""
    key = _loose(label)
    if not key:
        return None
    spans = set()
    for row in line.head_rows:
        if row == line.cells:
            break
        for j, c in enumerate(row):
            lc = _loose(c)
            if lc and (key in lc or len(lc) >= 4 and lc in key):
                k = j + 1
                while k < len(row) and not row[k]:
                    k += 1
                spans.add((j, k))
    return range(*spans.pop()) if len(spans) == 1 else None


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
    if ctx.target_model:
        linked = [r for ln in candidates if not ln.is_row for r in _rows_for_text_line(ctx.lines[page], ln)]
        candidates += [r for r in linked if r not in candidates]
    if ctx.target_model and any(ln.is_row for ln in candidates):
        # 多型号目录：正文里重复的表格行没有列信息，以表格行为准（否则能绕过型号列核对）
        candidates = [ln for ln in candidates if ln.is_row]
    reason, notes = _check_lines(ctx, page, candidates, text, label, unit, field, cond, ctx.lines[page])
    if reason is None or not ctx.target_model or not (ctx.layout or {}).get(page):
        return reason, notes
    # 没有边框的表（如安川外形尺寸表的续页）：按文字对齐切出的行再核对一次，须确认型号所在的列
    layout = ctx.layout[page]
    alt = [r for r in layout if quote in r.joined]
    alt += [r for ln in candidates if not ln.is_row for r in _rows_for_text_line(layout, ln) if r not in alt]
    if not alt:
        return reason, notes
    pool = layout + [x for x in ctx.lines[page] if not x.is_row]
    reason2, notes2 = _check_lines(ctx, page, alt, text, label, unit, field, cond, pool, strict=True)
    return (None, [*notes2, "按版面对齐切出的行核对"]) if reason2 is None else (reason, notes)


def _check_lines(ctx: _Ctx, page: int, candidates: list[_Line], text: str, label: str, unit: str, field: str,
                 cond: str, pool: list[_Line], strict: bool = False) -> tuple[str | None, list[str]]:
    """逐个候选行核对；pool 是同页的行（找同表的其他行、表格外的型号代码行）。
    strict 为真时（按版面对齐的行）必须确认型号所在的列或行，判断不了的不收。"""
    best = "引用所在行中找不到与印出文字完全一致的数值"
    page_squashed = _squash(ctx.page_spaced[page])
    cols = _model_columns(ctx, page) if ctx.target_model else None
    for ln in candidates:
        notes: list[str] = []
        if cols and not ln.is_row:
            ok, why = _text_row_column(ln, label, text, unit, cols)
            if not ok:
                best = why
                continue
            if why:
                notes.append(why)
        elif not _value_in_line(ln, text, label, unit):
            continue
        if _loose(label) not in _loose(ln.joined):
            heads = "".join("".join(r) for r in ln.head_rows) or ln.header
            head_label = next((lb for lb in _label_prefixes(label) if _loose(lb) in _loose(heads)), None)
            if ln.is_row and head_label:
                span, col = _label_span(ln, head_label), _value_col(ln, text, unit)
                if span is not None and col is not None and col not in span:
                    best = "数值不在叫法所在的列"
                    continue
                notes.append(f"叫法 {label!r} 在表头，" + ("须核对所在列" if span is None or col is None
                                                           else "数值在该列"))
            else:
                best = "叫法不在引用所在的行中"
                continue
        if cond.strip() and _squash(cond) not in ln.joined:
            if _squash(cond) not in page_squashed:
                best = f"工况 {cond!r} 在第 {page} 页找不到"
                continue
            notes.append(f"工况 {cond!r} 不在同一行，取自本页其他位置（表头或脚注），须核对")
        if unit and not _unit_in(ln.spaced, unit) and not _unit_in_column_head(ln, text, unit):
            if not _unit_in(ctx.page_spaced[page], unit):
                best = f"单位 {unit!r} 不在引用所在的行中，本页也找不到"
                continue
            others = _other_units(ctx, page, unit, field)
            if others and unit.strip().casefold() == "mm" and _UNIT_MM.search(ctx.page_spaced[page]):
                others = []  # 本页写明了“Unit: mm”
            if others:
                best = f"单位 {unit!r} 不在同一行，而本页还有其他同类单位 {others}，无法判断"
                continue
            notes.append(f"单位 {unit} 不在同一行，取自本页其他位置")
        col = _value_col(ln, text, unit) if ln.is_row else None
        if col is not None and _alt_cell(ln.cells[col], _squash(text)):
            notes.append("单元格另印有括号内的值（如带制动器的型号）或公差，取名义值")
        if ln.is_row and ctx.target_model:
            text_lines = [x for x in pool if not x.is_row]
            column = _model_column(ln, ctx.target_model, text, unit, ctx.target_raw, text_lines)
            if column is False:
                # 引用的是同一张表的另一行：目标型号所在的行，同一列印着同一个数时也算（如各减速比的输入转速相同）
                col = _value_col(ln, text, unit)
                twin = col is not None and any(
                    r is not ln and r.is_row and r.head_rows == ln.head_rows and col < len(r.cells)
                    and _cell_is(r.cells[col], text, unit)
                    and _row_key_is(r, ctx.target_raw)
                    for r in pool) and ln.cells[0].isdigit() and not _row_key_is(ln, ctx.target_raw)
                if not twin:
                    best = "数值不在目标型号所在的列"
                    continue
                notes.append("引用的是同表另一行；目标型号所在行的同一列印着同一个数")
                column = True
            if column is True:
                return None, notes
        if strict:
            best = "按版面对齐的行无法确认型号所在的列"
            continue
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


def verify(tool_input: Any, document: Document, category: str, doc_id: str, *,
           target_model: str | None = None) -> dict:
    """核对 LLM 的全部提议，返回抽取结果中的 vendor/model/series/items/rejected/missing_key_fields。

    target_model：多型号目录的目标型号。表头列出各型号时，数值必须在目标型号那一列；型号以目标型号为准。
    """
    ctx = _context(document, target_model)
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
        if k == "model" and target_model:
            if isinstance(v, str) and v.strip() and _loose(v) != _loose(target_model):
                rejected.append({"target": k, "printed": {"text": v.strip()},
                                 "reason": f"报的型号与目标型号 {target_model} 不同"})
            v = target_model
        if not isinstance(v, str) or not v.strip():
            continue
        if re.search(r"(?<![A-Za-z0-9-])" + re.escape(_spaced(v)) + r"(?![A-Za-z0-9-])", all_text) or (
                k == "model" and target_model and _model_printed_split(ctx, target_model)):
            out[k] = v.strip()
        else:
            rejected.append({"target": k, "printed": {"text": v.strip()}, "reason": f"{k} 在规格书中找不到"})
    return out


# ---------------------------------------------------------------- 入口


class ExtractionInvalid(RuntimeError):
    """抽取结果不符合 schema：属于代码缺陷。"""


def extract_document(document: Document, category: str, doc_id: str, client: LLMClient, *,
                     model: str | None = None, prompt_version: str = PROMPT_VERSION,
                     pages: list[int] | None = None, target_model: str | None = None) -> dict:
    """pages：只把这些页交给 LLM；target_model：多型号目录中要抽取的型号（ADR-0040）。"""
    if not document.pages:
        raise ValueError("文档没有任何页面")
    if target_model is not None and not target_model.strip():
        raise ValueError("目标型号不能为空")
    if pages:
        document = document.select(pages)
    if not re.fullmatch(r"src-[a-z0-9]+(-[a-z0-9]+)*", doc_id or ""):
        raise ValueError(f"来源文档 id 格式不对：{doc_id!r}")
    model = model or os.environ.get("FAP_LLM_MODEL") or DEFAULT_MODEL
    request = build_request(document, category, model=model, prompt_version=prompt_version,
                            target_model=target_model, excerpt=bool(pages))
    response = client.complete(request)
    checked = verify(response.get("tool_input") or {}, document, category, doc_id, target_model=target_model)
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
    parser.add_argument("--pages", help="只把这些页交给 LLM，如 12-15,20（多型号目录）")
    parser.add_argument("--target", help="多型号目录中要抽取的型号（按目录中印出的写法）")
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
        pages = parse_pages(args.pages) if args.pages else None
        result = extract_document(document, args.category, args.doc, client, pages=pages, target_model=args.target)
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
