"""有限元报告（ADR-0093 补充十一第 5 步）：事实清单、AI 解释（数字用占位符）、Word / PDF 报告、审核清单、可追溯信息。

报告里的每一个数字都由程序从文件里取：算例、结果、材料库、零件库、STEP 文件指纹、改版记录。程序写一份“出处账”（报告旁的
`*.ledger.json`），每个印出来的数字或带数字的文字都记着来自哪个文件的哪一处；测试把 Word 里的全部数字逐个对回这些文件。
AI 只写解释和建议的文字，数字一律用 `{{键}}` 占位、由程序从事实清单填；AI 的段落里出现数字、说“合格”、在核查没通过时说
“收敛 / 可信”，那一段就退回不用。AI 不判定合格；报告页眉写“草稿，须工程师审核”，编制 / 审核 / 批准三栏只留栏位，不代签。
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PROMPT_VERSION = "fea-explain/1"
DEFAULT_MODEL = "claude-sonnet-5-5"
TOOL_NAME = "write_fea_explanation"
RECORDINGS_DIR = ROOT / "tests" / "recordings" / "fea_report"
FIXTURES = ROOT / "tests" / "fixtures" / "fea-report"
DRAFT_MARK = "草稿，须工程师审核"
VERDICT = {"pass": "通过", "fail": "不通过", "unknown": "未知", None: "未知"}
LABELS = ("SHA-256",)          # 模板里固定带数字的字样（不是数据）
TYPE_ZH = {"fixed": "固定", "cyl_support": "圆柱面支承", "symmetry": "对称面", "displacement": "强制位移", "elastic_support": "弹性支承",
           "force": "力", "pressure": "压力", "torque": "扭矩", "moment": "力矩", "bearing_load": "轴承载荷", "gravity": "重力",
           "centrifugal": "离心", "remote_load": "远端载荷", "temperature": "温度变化", "mass": "附加质量", "bonded": "绑定",
           "contact": "接触", "bolt_preload": "螺栓预紧", "static": "静力", "modal": "模态", "buckling": "线性屈曲",
           "harmonic": "谐响应", "random": "随机振动", "transient": "瞬态"}
SOURCE_ZH = {"statement": "原话", "feature": "零件特征", "default": "缺省", "human": "人工"}


# ---------------------------------------------------------------- 指纹、版本


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _round(x: Any) -> Any:
    if isinstance(x, float):
        return float(f"{x:.6g}") if math.isfinite(x) else str(x)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in sorted(x.items()) if k not in ("seconds", "elapsed_s")}
    if isinstance(x, list):
        return [_round(v) for v in x]
    return x


def fingerprint(obj: Any) -> str:
    """结果指纹：浮点按 6 位有效数字、去掉计算用时后的 SHA-256。同一算例重算，指纹相同即可复现"""
    s = json.dumps(_round(obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def code_version() -> str:
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10,
                             check=False).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True,
                               text=True, timeout=10, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "未知（不在 git 仓库里）"
    return (rev or "未知") + ("（有未提交的改动）" if dirty else "")


def gmsh_version() -> str:
    try:
        import gmsh

        return str(gmsh.__version__)
    except ImportError:
        return "未知"


# ---------------------------------------------------------------- 出处账


def _ptr_get(doc: Any, ptr: str) -> Any:
    cur = doc
    for part in [p.replace("~1", "/").replace("~0", "~") for p in ptr.split("/")[1:]]:
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    return cur


def fmt(v: float) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if v == 0:
        return "0"
    s = f"{v:.4g}"
    return s.replace("e-0", "e-").replace("e+0", "e+")


class Ledger:
    """每个印出来的数字（或带数字的文字）都记一笔：印的字样、来自哪个文件的哪一处"""

    def __init__(self, sources: dict[str, Any]):
        self.sources = sources          # 名字 → 文档（study、result、materials、record、input、env、files、library）
        self.entries: list[dict] = []

    def num(self, src: str, ptr: str, unit: str = "") -> str:
        v = _ptr_get(self.sources[src], ptr)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise TypeError(f"{src}{ptr} 不是数：{v!r}")
        s = fmt(v)
        self.entries.append({"text": s, "source": src, "pointer": ptr, "kind": "number"})
        return s + (f" {unit}" if unit else "")

    def txt(self, src: str, ptr: str) -> str:
        v = _ptr_get(self.sources[src], ptr)
        s = str(v)
        if re.search(r"[0-9]", s):
            self.entries.append({"text": s, "source": src, "pointer": ptr, "kind": "text"})
        return s

    def vec(self, src: str, ptr: str, unit: str = "") -> str:
        v = _ptr_get(self.sources[src], ptr)
        return "(" + ", ".join(self.num(src, f"{ptr}/{i}") for i in range(len(v))) + ")" + (f" {unit}" if unit else "")

    def ints(self, src: str, ptr: str) -> str:
        v = _ptr_get(self.sources[src], ptr)
        return "、".join(self.num(src, f"{ptr}/{i}") for i in range(len(v)))


# ---------------------------------------------------------------- 事实清单（给 AI 与摘要用）


def facts(result: dict) -> dict[str, dict]:
    """键 → {path, desc, unit}。值都在结果文件里（path 是 JSON Pointer）"""
    out: dict[str, dict] = {}
    d = result["data"]

    def put(key, ptr, desc, unit=""):
        v = _ptr_get(result, ptr)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v is not None:
            out[key] = {"pointer": ptr, "desc": desc, "unit": unit, "value": v}

    for i, s in enumerate(d.get("steps") or []):
        base, sid = f"/data/steps/{i}", s["id"]
        if s["type"] == "static":
            put(f"{sid}.vm_max_mpa", f"{base}/vm_max_mpa", "最大 von Mises 应力（避开约束面）", "MPa")
            put(f"{sid}.u_max_mm", f"{base}/u_max_mm", "最大位移", "mm")
            put(f"{sid}.strength_mpa", f"{base}/strength_mpa", f"材料{s.get('strength_kind', '强度')}", "MPa")
            if s.get("safety_factor") is not None:
                put(f"{sid}.safety_factor", f"{base}/safety_factor", "安全系数")
            for k, it in enumerate(s.get("trust", {}).get("items") or []):
                if it.get("name", "").startswith("网格收敛") and it.get("values"):
                    for j in range(len(it["values"])):
                        put(f"{sid}.conv{k}.level{j}", f"{base}/trust/items/{k}/values/{j}", f"{it['name']}，第 {j + 1} 层网格",
                            "MPa" if "应力" in it["name"] else "mm")
        elif s["type"] == "modal":
            for j, f in enumerate(s.get("freqs") or []):
                put(f"{sid}.f{f['mode']}_hz", f"{base}/freqs/{j}/hz", f"第 {f['mode']} 阶固有频率", "Hz")
                put(f"{sid}.f{f['mode']}_rpm", f"{base}/freqs/{j}/rpm", f"第 {f['mode']} 阶固有频率对应转速", "rpm")
    return out


def fact_lines(result: dict) -> list[str]:
    """给 AI 看的事实：数值项（带键）与结论项（文字，不带键）"""
    d = result["data"]
    lines = [f"整体可信度结论：{VERDICT.get(d.get('trust_verdict'))}"]
    for s in d.get("steps") or []:
        lines.append(f"分析步 {s['id']}（{TYPE_ZH.get(s['type'], s['type'])}）")
        if s.get("combination"):
            lines.append(f"  按组合 {s['combination']} 计算")
        if s["type"] == "static":
            tr = s.get("trust") or {}
            lines.append(f"  可信度：{VERDICT.get(tr.get('verdict'))}")
            for it in tr.get("items") or []:
                lines.append(f"  核查“{it['name']}”：{VERDICT.get(it['verdict'])}——{it['text']}")
            if s.get("safety_factor") is None:
                lines.append(f"  安全系数：不给（{s.get('safety_factor_withheld', '没有算出')}）")
    for k, f in facts(result).items():
        lines.append(f"  {{{{{k}}}}} = {fmt(f['value'])} {f['unit']}：{f['desc']}")
    lines += [f"局限：{x}" for x in result.get("limitations") or []]
    return lines


# ---------------------------------------------------------------- AI 解释：请求与核对

SYSTEM_PROMPT = """你是结构分析工程师的助手，为一份有限元分析报告写“解释与建议”。你只解释，不判定合格；报告由工程师审核。

规则：
1. 只用下面“事实”里的内容，不要补充事实里没有的结果或结论。
2. 文字里不许出现任何数字（包括阿拉伯数字和带单位的汉字数字）。要引用数值，就写事实里给出的占位符，例如 {{s1.vm_max_mpa}}，
   程序会填上数值和单位；没有占位符的数值就不要提。
3. 不写“合格”“满足要求”“安全”一类判定。可信度核查没通过或未知时，要如实说明，并且不得说结果已收敛、可信。
4. 安全系数没给时，说明没给的原因（照事实里的原因），不要估计。
5. 建议要具体、可操作（例如在哪里改网格、补什么数据、哪个结构细节要人核对），每条一句。
6. 中文，书面、简洁。
"""
TOOL_INSTRUCTION = "\n必须调用一次工具 {name} 提交。"
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "paragraphs": {"type": "array", "items": {"type": "string"}, "description": "解释，每段一条（数值只用占位符）"},
        "suggestions": {"type": "array", "items": {"type": "string"}, "description": "建议，每条一句（数值只用占位符）"},
    },
    "required": ["paragraphs", "suggestions"],
}


def build_request(result: dict, *, model: str = DEFAULT_MODEL) -> dict:
    user = "事实（程序从结果文件整理）：\n" + "\n".join(fact_lines(result))
    return {"model": model, "prompt_version": PROMPT_VERSION,
            "system": SYSTEM_PROMPT + TOOL_INSTRUCTION.format(name=TOOL_NAME), "user": user,
            "tool": {"name": TOOL_NAME, "description": "提交解释与建议", "input_schema": TOOL_SCHEMA}}


PLACE = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")
_CN_NUM = re.compile(r"[零〇一二两三四五六七八九十百千万亿]+\s*(?:兆帕|千帕|帕|牛|千牛|毫米|厘米|米|赫兹|赫|转|倍|个百分点|摄氏度|度|公斤|千克)")
_NEG = r"(?<!不)(?<!未)(?<!没有)(?<!无法)(?<!不能)(?<!尚未)"
# 判定合格与否是人的事：说“合格”“不合格”“满足要求”“不满足要求”都退回；只说“不作合格判定”“是否合格由审核人定”可以
ACCEPT = re.compile(r"合格|满足(?:强度|刚度|设计|使用)?要求|安全可靠|足够安全|可以放心|可以使用|可放心使用|approved|acceptable"
                    r"|safe to use|meets? the requirements?", re.IGNORECASE)
ACCEPT_OK = re.compile(r"合格判定|判定合格|是否合格|合格与否")
TRUSTED = re.compile(r"(已收敛|收敛良好|结果可信|结果可靠|可信度(?:核查)?(?:已|均|全部)?通过|核查(?:均|全部)?通过|converged|reliable)",
                     re.IGNORECASE)


_HEDGE = re.compile(r"不|未|没有|无法|不能|尚未|若|如果|一旦|直到|待|before|until|unless|not|cannot", re.IGNORECASE)
_HEDGE_AFTER = re.compile(r"^\s*(之前|以前|前|为止)")
_CLAUSE = re.compile(r"[，。；;,.!?！？\n]")


def _item_words(name: str) -> list[str]:
    """核查项在文字里可能的叫法：“网格收敛（最大位移）”→ 最大位移 / 位移"""
    m = re.match(r"网格收敛（(.+)）", name)
    if m:
        w = m.group(1)
        return [w, w.removeprefix("最大")]
    return [name]


def _context(result: dict) -> tuple[list[str], list[str], list[str]]:
    """（分析步、组合、工况的 id——是名字不是数值；通过的核查项叫法；没通过的核查项叫法）"""
    d = result.get("data") or {}
    ids, ok, bad = [], [], []
    for st in d.get("steps") or []:
        ids += [str(st.get("id", "")), str(st.get("combination") or "")]
        for it in (st.get("trust") or {}).get("items") or []:
            (ok if it.get("verdict") == "pass" else bad).extend(_item_words(it.get("name", "")))
    setup = result.get("setup") or {}
    ids += [str(x.get("id", "")) for x in (setup.get("load_cases") or []) + (setup.get("combinations") or [])]
    return [x for x in ids if x], ok, bad


def check_text(text: str, facts_: dict, all_pass: bool, result: dict | None = None) -> str | None:
    """一段 AI 文字不合规的原因；合规返回 None。
    分析步、组合、工况的 id（如 s1、s_combo1）是名字，不算数字；说某一项“核查通过”而那一项确实通过、或在否定 / 条件句里
    （“不能视为已收敛”“在核查通过之前不使用”）都不算违规——这两条是真实 LLM 录制里查出的误判（11-16）"""
    if not isinstance(text, str) or not text.strip():
        return "空段落"
    for k in PLACE.findall(text):
        if k not in facts_:
            return f"占位符 {{{{{k}}}}} 不在事实清单里"
    bare = PLACE.sub("", text)
    ids, ok_words, bad_words = _context(result or {})
    named = bare
    for x in sorted(ids, key=len, reverse=True):
        named = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(x)}(?![A-Za-z0-9_])", "", named)
    if re.search(r"[0-9０-９]", named):
        return "文字里有数字（数值必须用占位符）"
    if _CN_NUM.search(bare) or "百分之" in bare:
        return "文字里有汉字写的数值"
    if "{" in bare or "}" in bare:
        return "占位符格式不对"
    m = ACCEPT.search(ACCEPT_OK.sub("", bare))
    if m:
        return f"做了合格判定（“{m.group(0)}”）：AI 不判定合格"
    if not all_pass:
        for clause in _CLAUSE.split(bare):
            m = TRUSTED.search(clause)
            if not m or _HEDGE.search(clause[:m.start()]) or _HEDGE_AFTER.search(clause[m.end():]):
                continue
            if any(w in clause for w in ok_words) and not any(w in clause for w in bad_words):
                continue
            return f"可信度核查没有全部通过，却说“{m.group(0)}”"
    return None


def verify_explanation(tool_input: Any, result: dict) -> dict:
    """核对 AI 的解释：逐段核对，不合规的整段退回。返回 {"paragraphs", "suggestions", "rejected"}"""
    fx = facts(result)
    all_pass = result["data"].get("trust_verdict") == "pass"
    out: dict[str, list] = {"paragraphs": [], "suggestions": [], "rejected": []}
    if not isinstance(tool_input, dict):
        out["rejected"].append({"part": "全部", "reason": "AI 的输出不是一个对象"})
        return out
    for part in ("paragraphs", "suggestions"):
        for i, t in enumerate(tool_input.get(part) or []):
            why = check_text(t, fx, all_pass, result)
            if why:
                out["rejected"].append({"part": f"{'解释' if part == 'paragraphs' else '建议'}第 {i + 1} 段", "reason": why})
            else:
                out[part].append(str(t)[:1500])
    return out


def explain(result: dict, client, *, model: str = DEFAULT_MODEL) -> dict:
    resp = client.complete(build_request(result, model=model))
    out = verify_explanation(resp.get("tool_input"), result)
    out.update(model=model, response_id=resp.get("id", ""), prompt_version=PROMPT_VERSION, simulated=bool(resp.get("simulated")))
    return out


class FakeClient:
    def __init__(self, tool_input: dict):
        self.tool_input = tool_input

    def complete(self, request: dict) -> dict:
        return {"id": "fake", "tool_input": copy.deepcopy(self.tool_input), "simulated": True}


# ---------------------------------------------------------------- 审核清单


def checklist(study: dict, result: dict) -> list[dict]:
    """每项：项目、程序核查结论（通过 / 不通过 / 未知 / 须人工判断）、依据。参考 NAFEMS 有限元质量管理做法列项"""
    from analysis.common import materials

    d = result["data"]
    statics = [s for s in d.get("steps") or [] if s["type"] == "static"]
    rows = []

    def row(item, verdict, basis):
        rows.append({"item": item, "verdict": verdict, "basis": basis})

    row("几何与简化", "须人工判断", "按 STEP 原样划分网格，程序没有删除圆角、孔、倒角；STEP 与图纸是否一致、是否做过简化，由人核对")
    srcs = [bool((materials._table().get(b.get("material", "")) or {}).get("sources")) for b in study["bodies"]]
    row("材料", "通过" if all(srcs) else "未知", "各实体的材料都在材料库里、带标准或手册出处" if all(srcs) else "有实体的材料没有出处")
    row("支承（是否过约束、是否符合实际安装）", "须人工判断",
        "程序只核对反力平衡；固定面是否过约束、与实际安装是否相符，由人判断")
    basis = (study.get("provenance") or {}).get("basis") or []
    load_ok = all(any(b["target"] == f"/loads/{i}" and b.get("source") in ("statement", "human") for b in basis)
                  for i in range(len(study.get("loads") or [])))
    if not study.get("provenance"):
        row("载荷来源", "须人工判断", "算例没有记依据（人工建的算例），载荷出处由人核对")
    else:
        row("载荷来源", "通过" if load_ok else "须人工判断",
            "每个载荷都有原话引用或人工依据" if load_ok else "有载荷没有原话或人工依据")
    row("单位", "通过", "程序内部一律用标准单位（mm、N、MPa、N·m），字段名带单位，单位换算只在入口做")
    for s in statics:
        tr = s.get("trust") or {}
        for it in tr.get("items") or []:
            if it["name"].startswith(("网格收敛", "网格质量", "反力平衡", "载荷加完", "最大应力的位置")):
                row(f"{it['name']}（{s['id']}）", VERDICT.get(it["verdict"]), it["text"])
        singular = any("奇异" in (it.get("text") or "") and it["verdict"] != "pass" for it in tr.get("items") or [])
        row(f"奇异点处理（{s['id']}）", "须人工判断" if singular else "通过",
            "疑似奇异点：该处应力不能直接作设计依据，须人判断是改几何（加圆角）、换评定方法还是避开该处"
            if singular else "最大应力处没有发现随网格加密而增大的趋势")
    row("与手算或经验对照", "须人工判断", "由审核人用手算（材料力学公式）或类似零件的经验对照主要结果")
    if (study.get("provenance") or {}).get("drafted_by") == "ai":
        pv = study["provenance"]
        row("AI 起草的算例", "通过" if pv.get("confirmed_by_human") and pv.get("confirmed_by") else "不通过",
            "AI 起草，已由工程师确认" if pv.get("confirmed_by") else "AI 起草，没有确认人")
    return rows


# ---------------------------------------------------------------- 图


def _plot(surface: dict, field: str, label: str, path: Path, mark: list | None = None) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    except ImportError:
        return False
    P = np.asarray(surface["positions"], float)
    T = np.asarray(surface["triangles"], int)
    v = np.asarray(surface[field], float)
    if v.ndim == 2:                                   # 位移是矢量：画大小
        v = np.linalg.norm(v, axis=1)
    if not len(T):
        return False
    tv = v[T].mean(axis=1)
    fig = plt.figure(figsize=(6.4, 4.8), dpi=150)
    ax = fig.add_subplot(111, projection="3d")
    norm = matplotlib.colors.Normalize(vmin=float(v.min()), vmax=float(v.max()))
    cmap = matplotlib.colormaps["jet"]
    pc = Poly3DCollection(P[T], facecolors=cmap(norm(tv)), edgecolors="none", linewidths=0)
    ax.add_collection3d(pc)
    lo, hi = P.min(axis=0), P.max(axis=0)
    c, r = (lo + hi) / 2, float((hi - lo).max()) / 2 or 1.0
    ax.set_xlim(c[0] - r, c[0] + r)
    ax.set_ylim(c[1] - r, c[1] + r)
    ax.set_zlim(c[2] - r, c[2] + r)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=25, azim=-60)
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    ax.set_zlabel("z (mm)")
    if mark is not None:
        ax.scatter([mark[0]], [mark[1]], [mark[2]], marker="x", s=80, c="k", depthshade=False)
        ax.text(mark[0], mark[1], mark[2], "  max", color="k")
    sm = matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap)
    fig.colorbar(sm, ax=ax, shrink=0.7, label=label)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return True


# ---------------------------------------------------------------- Word


def _resolve(p: str, base: Path) -> Path:
    q = Path(p)
    return q if q.is_absolute() else (base / q)


def build(study: dict, result: dict, out: Path, *, number: str | None = None, revision: str = "草稿",
          reason: str = "首次出稿", explanation: dict | None = None, base_dir: Path | None = None,
          study_path: Path | None = None, today: date | None = None) -> dict:
    """出 Word 报告（与出处账、改版记录）。返回 {"docx", "ledger", "record"}"""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    from analysis.common import materials

    if result.get("status") != "ok":
        raise ValueError("结果不是算成的（status ≠ ok），不出报告：" + "；".join(result.get("messages") or []))
    if fingerprint(result.get("setup")) != fingerprint(study):
        raise ValueError("结果文件不是用这份算例算的（算例与结果里的设置不一致）")
    base = base_dir or Path.cwd()
    out = Path(out)
    today = today or datetime.now(UTC).date()

    # 改版记录（报告旁的 *.record.json）：同一版次重出就替换那一条
    out.parent.mkdir(parents=True, exist_ok=True)
    rec_path = out.with_suffix(".record.json")
    record = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.is_file() else {"history": []}
    record["number"] = number or record.get("number") or "未编号（由质量体系分配）"
    files = {"study": sha256_file(study_path) if study_path else fingerprint(study)}
    for i, b in enumerate(study["bodies"]):
        sp = _resolve(b["step_path"], base)
        if not sp.is_file() and study_path:
            sp = _resolve(b["step_path"], Path(study_path).parent)
        files[f"step{i}"] = sha256_file(sp)
    files["result"] = fingerprint(result["data"])
    entry = {"revision": revision, "date": today.isoformat(), "reason": reason, "result_fingerprint": files["result"],
             "study_sha256": files["study"]}
    record["history"] = [h for h in record["history"] if h["revision"] != revision] + [entry]
    rec_path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    mats = {}
    for b in study["bodies"]:
        m = materials._table().get(b.get("material", ""))
        if m:
            mats[m["id"]] = m
    env = {"code": code_version(), "gmsh": gmsh_version(), "solver": f"{result.get('solver', {}).get('name', '')} "
                                                                     f"{result.get('solver', {}).get('version', '未知')}",
           "module": f"fea {result.get('module_version', '')}"}
    lib = library_sources(study)
    L = Ledger({"study": study, "result": result, "materials": {"materials": mats}, "record": record,
                "files": files, "env": env, "library": lib, "explain": explanation or {}})
    fx = facts(result)

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Noto Sans CJK SC"
    st.font.size = Pt(10)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Noto Sans CJK SC")
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2)
        hp = s.header.paragraphs[0]
        rev_ptr = f"/history/{len(record['history']) - 1}/revision"
        hp.text = f"{DRAFT_MARK}　报告编号 {L.txt('record', '/number')}　版次 {L.txt('record', rev_ptr)}"
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    def h(text, lvl=1):
        doc.add_heading(text, level=lvl)

    def p(text):
        return doc.add_paragraph(text)

    def table(head, rows, widths=None):
        t = doc.add_table(rows=1, cols=len(head))
        t.style = "Table Grid"
        for c, x in zip(t.rows[0].cells, head, strict=True):
            c.text = x
            for r in c.paragraphs[0].runs:
                r.bold = True
        for row in rows:
            cells = t.add_row().cells
            for c, x in zip(cells, row, strict=True):
                c.text = x
        return t

    doc.add_heading(f"有限元分析报告：{L.txt('study', '/name')}", 0)
    last = len(record["history"]) - 1
    table(["项目", "内容"], [
        ["报告编号", L.txt("record", "/number")],
        ["版次", L.txt("record", f"/history/{last}/revision")],
        ["出稿日期", L.txt("record", f"/history/{last}/date")],
        ["状态", DRAFT_MARK],
        ["编制（签字 / 日期）", ""], ["审核（签字 / 日期）", ""], ["批准（签字 / 日期）", ""],
    ])
    p("编制、审核、批准三栏由人签字，程序不代签。")

    # 一、结论摘要
    h("一、结论摘要")
    d = result["data"]
    p(f"整体可信度结论：{VERDICT.get(d.get('trust_verdict'))}。本报告不作合格判定，由审核人按审核清单判断。")
    for i, s in enumerate(d.get("steps") or []):
        b = f"/data/steps/{i}"
        if s["type"] == "static":
            comb = f"（按组合 {L.txt('result', b + '/combination')}）" if s.get("combination") else ""
            p(f"分析步 {L.txt('result', b + '/id')}，静力{comb}：最大 von Mises 应力 {L.num('result', b + '/vm_max_mpa', 'MPa')}"
              f"（位置 {L.vec('result', b + '/vm_max_at', 'mm')}），最大位移 {L.num('result', b + '/u_max_mm', 'mm')}；"
              f"可信度 {VERDICT.get(s['trust']['verdict'])}。")
            if s.get("safety_factor") is not None:
                p(f"安全系数 {L.num('result', b + '/safety_factor')}（按{L.txt('result', b + '/strength_kind')} "
                  f"{L.num('result', b + '/strength_mpa', 'MPa')}）。")
            elif s.get("safety_factor_withheld"):
                p(f"安全系数：不给。原因：{L.txt('result', b + '/safety_factor_withheld')}")
        elif s["type"] == "modal":
            fr = "；".join(f"第 {L.num('result', f'{b}/freqs/{j}/mode')} 阶 {L.num('result', f'{b}/freqs/{j}/hz', 'Hz')}"
                          f"（{L.num('result', f'{b}/freqs/{j}/rpm', 'rpm')}）" for j in range(len(s.get("freqs") or [])))
            p(f"分析步 {L.txt('result', b + '/id')}，模态：{fr}。")

    # 二、算例
    h("二、算例")
    pv = study.get("provenance") or {}
    rows = []
    for i, bd in enumerate(study["bodies"]):
        m = mats.get(bd.get("material"))
        mid = bd.get("material")
        if m:
            src = "；".join(L.txt("materials", f"/materials/{_esc(mid)}/sources/{j}") for j in range(len(m.get("sources") or [])))
            mat = (f"{L.txt('materials', f'/materials/{_esc(mid)}/id')}（{L.txt('materials', f'/materials/{_esc(mid)}/name')}）；"
                   f"E = {L.num('materials', f'/materials/{_esc(mid)}/elastic_modulus_mpa', 'MPa')}，"
                   f"ν = {L.num('materials', f'/materials/{_esc(mid)}/poisson_ratio')}"
                   + (f"，屈服强度 {L.num('materials', f'/materials/{_esc(mid)}/yield_strength_mpa', 'MPa')}"
                      if "yield_strength_mpa" in m else ""))
        else:
            src, mat = "—", "未给"
        rows.append([L.txt("study", f"/bodies/{i}/id"), L.txt("study", f"/bodies/{i}/step_path"), mat, src or "—"])
    h("零件与材料", 2)
    table(["实体", "STEP 文件", "材料与性能", "材料数据出处"], rows)

    def basis_of(target):
        for k, bb in enumerate(pv.get("basis") or []):
            if bb["target"] == target:
                q = f"“{L.txt('study', f'/provenance/basis/{k}/quote')}”" if bb.get("quote") else ""
                n = L.txt("study", f"/provenance/basis/{k}/note") if bb.get("note") else ""
                return f"{SOURCE_ZH.get(bb.get('source'), bb.get('source'))}{q}{('；' + n) if n else ''}"
        return "—"

    def params(key, i, x):
        ptr = f"/{key}/{i}"
        out_ = []
        for k, unit in (("value_nm", "N·m"), ("value_mpa", "MPa")):
            if k in x:
                out_.append(L.num("study", f"{ptr}/{k}", unit))
        for k, unit in (("vector_n", "N"), ("force_n", "N"), ("vector_nm", "N·m"), ("acceleration_m_s2", "m/s²")):
            if k in x:
                out_.append(L.vec("study", f"{ptr}/{k}", unit))
        if "axis" in x:
            out_.append(f"轴线过 {L.vec('study', ptr + '/axis/origin_mm', 'mm')}、方向 {L.vec('study', ptr + '/axis/dir')}")
        if "dofs" in x:
            out_.append("限制 " + "、".join({"radial": "径向", "tangential": "切向", "axial": "轴向"}.get(t, t) for t in x["dofs"]))
        if x.get("case"):
            out_.append(f"工况 {L.txt('study', ptr + '/case')}")
        return "；".join(out_) or "—"

    for key, title in (("supports", "支承"), ("loads", "载荷")):
        h(title, 2)
        rows = []
        for i, x in enumerate(study.get(key) or []):
            faces = L.ints("study", f"/{key}/{i}/faces") if x.get("faces") else "—"
            rows.append([TYPE_ZH.get(x["type"], x["type"]), L.txt("study", f"/{key}/{i}/body"), faces, params(key, i, x),
                         basis_of(f"/{key}/{i}")])
        table(["类型", "实体", "面", "参数", "依据"], rows) if rows else p("无。")
    if study.get("connections"):
        h("连接", 2)
        table(["类型", "一侧", "另一侧", "依据"], [
            [TYPE_ZH.get(c["type"], c["type"]),
             f"{L.txt('study', f'/connections/{i}/a/body')} 面 {L.ints('study', f'/connections/{i}/a/faces')}",
             f"{L.txt('study', f'/connections/{i}/b/body')} 面 {L.ints('study', f'/connections/{i}/b/faces')}",
             basis_of(f"/connections/{i}")] for i, c in enumerate(study["connections"])])
    if study.get("load_cases"):
        h("工况与组合", 2)
        table(["工况", "名称", "类别"], [[L.txt("study", f"/load_cases/{i}/id"), L.txt("study", f"/load_cases/{i}/name"), c["kind"]]
                                     for i, c in enumerate(study["load_cases"])])
        table(["组合", "系数", "系数出处"], [
            [L.txt("study", f"/combinations/{i}/id"),
             "；".join(f"{k} × {L.num('study', f'/combinations/{i}/factors/{_esc(k)}')}" for k in c["factors"]),
             L.txt("study", f"/combinations/{i}/basis") if c.get("basis") else "—"] for i, c in enumerate(study.get("combinations") or [])])
    h("分析步", 2)
    table(["分析步", "类型", "说明"], [[L.txt("study", f"/steps/{i}/id"), TYPE_ZH.get(s["type"], s["type"]),
                                   (f"组合 {L.txt('study', f'/steps/{i}/combination')}" if s.get("combination") else "")
                                   + (f"前 {L.num('study', f'/steps/{i}/n_modes')} 阶" if "n_modes" in s else "")]
                                  for i, s in enumerate(study["steps"])])

    # 三、网格与可信度核查
    h("三、网格与可信度核查")
    for i, s in enumerate(d.get("steps") or []):
        b = f"/data/steps/{i}"
        if s["type"] == "static":
            h(f"分析步 {L.txt('result', b + '/id')}", 2)
            lv = s["trust"].get("levels") or []
            if lv:
                table(["网格层", "整体网格尺寸（mm）", "核查点局部尺寸（mm）", "单元数", "核查点应力（MPa）", "最大位移（mm）"], [
                    [f"第{_cn(j)}层", L.num("result", f"{b}/trust/levels/{j}/mesh_size_mm"),
                     L.num("result", f"{b}/trust/levels/{j}/local_h_mm"), L.num("result", f"{b}/trust/levels/{j}/elements"),
                     L.num("result", f"{b}/trust/levels/{j}/vm_checked_mpa"), L.num("result", f"{b}/trust/levels/{j}/u_max_mm")]
                    for j in range(len(lv))])
            table(["核查项", "结论", "说明"], [[L.txt("result", f"{b}/trust/items/{k}/name"), VERDICT.get(it["verdict"]),
                                           L.txt("result", f"{b}/trust/items/{k}/text")] for k, it in enumerate(s["trust"]["items"])])
        elif s["type"] == "modal":
            h(f"分析步 {L.txt('result', b + '/id')}", 2)
            p(f"节点 {L.num('result', b + '/nodes')}，单元 {L.num('result', b + '/elements')}。")

    # 四、结果
    h("四、结果")
    tmp = Path(tempfile.mkdtemp(prefix="fea-report-"))
    for i, s in enumerate(d.get("steps") or []):
        b = f"/data/steps/{i}"
        if s["type"] == "static" and s.get("surface"):
            h(f"分析步 {L.txt('result', b + '/id')}：应力与位移", 2)
            for field, label, cap in (("vm", "von Mises (MPa)", "von Mises 应力云图，× 为评估用的最大应力处"), ("u", "displacement (mm)", "位移云图，× 为最大位移处")):
                img = tmp / f"{s['id']}-{field}.png"
                if _plot(s["surface"], field, label, img, s.get("vm_max_at") if field == "vm" else s.get("u_max_at")):
                    doc.add_picture(str(img), width=Cm(14))
                    p(f"图：{cap}（分析步 {L.txt('result', b + '/id')}，按结果文件的表面数据画）")
            if s.get("support_reactions"):
                table(["支承", "面", "反力（N）", "反力矩（N·mm）"], [
                    [TYPE_ZH.get(r["type"], r["type"]), L.ints("result", f"{b}/support_reactions/{k}/faces"),
                     L.vec("result", f"{b}/support_reactions/{k}/force_n"), L.vec("result", f"{b}/support_reactions/{k}/moment_nmm")]
                    for k, r in enumerate(s["support_reactions"])])
        elif s["type"] == "modal":
            h(f"分析步 {L.txt('result', b + '/id')}：固有频率", 2)
            table(["阶次", "频率（Hz）", "转速（rpm）"], [[L.num("result", f"{b}/freqs/{j}/mode"), L.num("result", f"{b}/freqs/{j}/hz"),
                                                    L.num("result", f"{b}/freqs/{j}/rpm")] for j in range(len(s.get("freqs") or []))])
    if d.get("envelope"):
        h("多组合包络（各组合取最不利值）", 2)
        rows = []
        for k, v in d["envelope"].items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                rows.append([k, L.num("result", f"/data/envelope/{_esc(k)}")])
            elif isinstance(v, str):
                rows.append([k, L.txt("result", f"/data/envelope/{_esc(k)}")])
        table(["项目", "值"], rows)
    shutil.rmtree(tmp, ignore_errors=True)

    # 五、解释与建议
    h("五、解释与建议（AI 起草，须工程师判断）")
    if explanation is None:
        p("没有生成 AI 解释（本次出稿没有调用 AI）。")
    else:
        p("下面的文字由 AI 起草；文字里的数值由程序从结果文件填入，AI 不判定合格。")
        for k, t in enumerate(explanation.get("paragraphs") or []):
            p(_fill(t, fx, L))
        if explanation.get("suggestions"):
            p("建议：")
            for t in explanation["suggestions"]:
                doc.add_paragraph(_fill(t, fx, L), style="List Bullet")
        if explanation.get("rejected"):
            p("退回不用的 AI 段落：" + "；".join(f"{r['part']}（{r['reason']}）" for r in explanation["rejected"]))

    # 六、局限
    h("六、局限")
    for k in range(len(result.get("limitations") or [])):
        doc.add_paragraph(L.txt("result", f"/limitations/{k}"), style="List Bullet")

    # 七、审核清单
    h("七、审核清单")
    p("程序给出能确定核查的项的结论，其余标“须人工判断”；审核人逐项勾选并签字。清单项参考 NAFEMS 的有限元质量管理做法。")
    rows = checklist(study, result)
    table(["项目", "程序结论", "依据", "审核人勾选", "备注"], [[r["item"], r["verdict"], _ltxt(L, r["basis"]), "☐", ""] for r in rows])

    # 八、可追溯信息
    h("八、可追溯信息")
    trace = [["算例文件 SHA-256" if study_path else "算例内容指纹（SHA-256）", L.txt("files", "/study")]]
    for i, _b in enumerate(study["bodies"]):
        trace.append([f"STEP 文件 SHA-256（{L.txt('study', f'/bodies/{i}/step_path')}）", L.txt("files", f"/step{i}")])
    trace += [["结果指纹（SHA-256，同一算例重算应相同）", L.txt("files", "/result")],
              ["求解器", L.txt("env", "/solver")], ["网格程序", "gmsh " + L.txt("env", "/gmsh")],
              ["分析模块", L.txt("env", "/module")], ["本项目代码版本（git 提交）", L.txt("env", "/code")]]
    if lib:
        for k, x in enumerate(lib):
            trace.append([f"外购件数据出处（{L.txt('library', f'/{k}/model')}）",
                          f"{L.txt('library', f'/{k}/doc')}，第 {L.num('library', f'/{k}/page')} 页（{L.txt('library', f'/{k}/what')}）"])
    table(["项目", "内容"], trace)
    h("改版记录", 2)
    table(["版次", "日期", "原因", "结果指纹"], [[L.txt("record", f"/history/{k}/revision"), L.txt("record", f"/history/{k}/date"),
                                         L.txt("record", f"/history/{k}/reason"), L.txt("record", f"/history/{k}/result_fingerprint")]
                                        for k in range(len(record["history"]))])

    # 九、AI 起草说明
    h("九、AI 起草说明")
    if pv.get("drafted_by") == "ai":
        p(f"算例由 AI 起草，{L.txt('study', '/provenance/confirmed_by') if pv.get('confirmed_by') else '（没有确认人）'} 于 "
          f"{L.txt('study', '/provenance/confirmed_at') if pv.get('confirmed_at') else '（未记时间）'} 确认。"
          + (L.txt("study", "/provenance/note") if pv.get("note") else ""))
        table(["位置", "来源", "原话引用", "用到的零件特征", "说明"], [
            [L.txt("study", f"/provenance/basis/{k}/target"), SOURCE_ZH.get(bb.get("source"), bb.get("source", "")),
             L.txt("study", f"/provenance/basis/{k}/quote") if bb.get("quote") else "",
             "；".join(L.txt("study", f"/provenance/basis/{k}/features/{j}") for j in range(len(bb.get("features") or []))),
             L.txt("study", f"/provenance/basis/{k}/note") if bb.get("note") else ""]
            for k, bb in enumerate(pv.get("basis") or [])])
    else:
        p("算例由人建立。")
    if explanation is not None:
        p(f"解释与建议由 AI 起草（提示词 {L.txt('explain', '/prompt_version')}，模型 {L.txt('explain', '/model')}，"
          f"响应 {L.txt('explain', '/response_id') or '未记录'}）。")

    doc.save(out)
    ledger = {"report": out.name, "files": files, "entries": L.entries, "labels": list(LABELS)}
    led_path = out.with_suffix(".ledger.json")
    led_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"docx": out, "ledger": led_path, "record": rec_path}


def _esc(k: str) -> str:
    return str(k).replace("~", "~0").replace("/", "~1")


def _cn(j: int) -> str:
    return "一二三四五六七八九十"[j] if j < 10 else "十" + "一二三四五六七八九"[j - 11]


def _ltxt(L: Ledger, s: str) -> str:
    """清单依据里带数字的文字来自结果（核查说明）：按值在结果里找到出处后记账"""
    if not re.search(r"[0-9]", s):
        return s
    for i, st in enumerate(L.sources["result"]["data"].get("steps") or []):
        for k, it in enumerate((st.get("trust") or {}).get("items") or []):
            if it.get("text") == s:
                return L.txt("result", f"/data/steps/{i}/trust/items/{k}/text")
    raise ValueError(f"审核清单里有来路不明的数字：{s}")


def _fill(text: str, fx: dict, L: Ledger) -> str:
    def rep(m):
        f = fx[m.group(1)]
        return L.num("result", f["pointer"], f["unit"])
    return PLACE.sub(rep, text)


def library_sources(study: dict) -> list[dict]:
    """算例依据里提到的外购件（特征识别时配上的减速器、轴承……）：其外形直径的规格书与页码"""
    from kb.library import JsonLibrary

    text = json.dumps(study.get("provenance") or {}, ensure_ascii=False)
    out = []
    for c in JsonLibrary(ROOT / "data" / "library").all():
        model = c.get("model") if isinstance(c, dict) else getattr(c, "model", None)
        if not model or model not in text:
            continue
        d = c if isinstance(c, dict) else c.__dict__
        for part in (d.get("envelope") or {}).get("parts") or []:
            dm = part.get("diameter_mm") or {}
            src = dm.get("source") or {}
            if src.get("doc") and src.get("page") is not None:
                out.append({"model": model, "doc": src["doc"], "page": src["page"], "what": f"外形 {part.get('label', '')} 直径"})
                break
    return out


# ---------------------------------------------------------------- PDF


def to_pdf(docx: Path) -> Path | None:
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None
    subprocess.run([exe, "--headless", "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)],
                   check=True, capture_output=True, timeout=300)
    pdf = docx.with_suffix(".pdf")
    return pdf if pdf.is_file() else None


# ---------------------------------------------------------------- 夹具与验收


def load_fixture(name: str) -> tuple[dict, dict]:
    study = json.loads((FIXTURES / f"{name}.study.json").read_text(encoding="utf-8"))
    with gzip.open(FIXTURES / f"{name}.result.json.gz", "rt", encoding="utf-8") as f:
        result = json.load(f)
    return study, result


def fixture_names() -> list[str]:
    return sorted(p.name.removesuffix(".study.json") for p in FIXTURES.glob("*.study.json"))


def evaluate(client) -> dict:
    """在真实零件的结果上让 AI 写解释：退回的段落数、占位符用了没有"""
    rows = []
    for n in fixture_names():
        _s, r = load_fixture(n)
        e = explain(r, client)
        used = sum(len(PLACE.findall(t)) for t in e["paragraphs"] + e["suggestions"])
        rows.append({"id": n, "kept": len(e["paragraphs"]) + len(e["suggestions"]), "rejected": e["rejected"],
                     "placeholders": used, "simulated": e["simulated"]})
    return {"samples": rows, "passed": all(not x["rejected"] and x["kept"] and x["placeholders"] for x in rows)}


# ---------------------------------------------------------------- 命令行


def _client(args):
    from ingest.llm_extract import AnthropicClient, RecordedClient

    if args.record is not None:
        return AnthropicClient(record_dir=args.record)
    if args.live:
        return AnthropicClient()
    return RecordedClient(args.replay or RECORDINGS_DIR)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m assist.fea report", description="有限元报告（ADR-0093 补充十一）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="算（或用已有结果）并出 Word / PDF 报告")
    r.add_argument("study", type=Path)
    r.add_argument("-o", "--out", type=Path, default=None)
    r.add_argument("--result", type=Path, default=None, help="用已算好的结果文件（须是这份算例算的）")
    r.add_argument("--number", default=None, help="报告编号（质量体系分配）")
    r.add_argument("--revision", default="草稿")
    r.add_argument("--reason", default="首次出稿")
    r.add_argument("--explain", action="store_true", help="让 AI 写解释与建议（数字由程序填）")
    r.add_argument("--no-pdf", action="store_true")
    e = sub.add_parser("eval", help="在真实零件结果上核对 AI 解释")
    for p_ in (r, e):
        mode = p_.add_mutually_exclusive_group()
        mode.add_argument("--replay", type=Path, default=None)
        mode.add_argument("--record", type=Path, nargs="?", const=RECORDINGS_DIR, default=None)
        mode.add_argument("--live", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "eval":
        res = evaluate(_client(a))
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["passed"] else 1
    study = json.loads(a.study.read_text(encoding="utf-8"))
    if a.result:
        result = json.loads(a.result.read_text(encoding="utf-8"))
    else:
        from analysis.fea import run_study

        result = run_study(study)
        if result["status"] != "ok":
            print("没有算出：" + "；".join(result["messages"]), file=sys.stderr)
            return 2
        a.study.with_suffix(".result.json").write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    expl = explain(result, _client(a)) if a.explain else None
    out = a.out or a.study.with_suffix(".docx")
    try:
        got = build(study, result, out, number=a.number, revision=a.revision, reason=a.reason, explanation=expl,
                    study_path=a.study)
    except ValueError as ex:
        print(f"没有出报告：{ex}", file=sys.stderr)
        return 2
    print(f"报告：{got['docx']}（出处账 {got['ledger'].name}，改版记录 {got['record'].name}）")
    if not a.no_pdf:
        pdf = to_pdf(Path(got["docx"]))
        print(f"PDF：{pdf}" if pdf else "本机没有 LibreOffice，只出了 Word")
    return 0


if __name__ == "__main__":
    sys.exit(main())
