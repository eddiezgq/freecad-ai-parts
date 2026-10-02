"""相似会话检索（ADR-0042 第 4 条第 2 步，issue #149）：对话助手收到需求时，找出相似的历史录制会话作为参考。

纯函数、只用标准库、结果确定：
- 相似度：需求原话的词项（英文单词、数字带单位、中文二字组）与历史会话需求的 Jaccard 相似度，
  加上两者用到的相同组件（工具调用中的 component_id）
- 只用正常结束的会话；评价为“未采纳”的也收录，作为反例提示
- 参考文字里只有需求、评价、说明、用户对 AI 的修改与最后的结论；会话包在写盘时已去掉密钥
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from freecad_addon.core.session_log import RecorderError, read_session

MIN_SCORE = 0.15
TOP_K = 3
MAX_CHARS = 1800
_RATING = {"accepted": "采纳", "modified": "修改后采纳", "rejected": "未采纳", None: "未评价"}
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_\-]*|\d+(?:\.\d+)?\s*(?:n·m|nm|rpm|mm|kg|v|w|a)?", re.IGNORECASE)
_CJK = re.compile(r"[一-鿿]+")


def terms(text: str) -> set[str]:
    text = (text or "").casefold()
    out = {re.sub(r"\s+", "", m.group()) for m in _WORD.finditer(text)}
    for run in _CJK.findall(text):
        out |= {run[i:i + 2] for i in range(len(run) - 1)} if len(run) > 1 else {run}
    return out


def _components(events: list[dict]) -> set[str]:
    out = set()
    for e in events:
        data = e.get("data") if e.get("kind") == "chat" and e.get("role") == "tool_call" else None
        if isinstance(data, dict) and isinstance(data.get("component_id"), str):
            out.add(data["component_id"])
    return out


def load(root: Path) -> list[dict]:
    """读出可用作参考的会话（按目录名排序）。"""
    from freecad_addon.sessions import to_record

    out = []
    for meta in sorted(Path(root).glob("*/meta.json")):
        try:
            s = read_session(meta.parent)
        except (RecorderError, ValueError, OSError):
            continue
        if s["outcome"] is None:
            continue
        rec = to_record(meta.parent.name, s)
        if not rec["request"]:
            continue
        rec["_terms"], rec["_components"] = terms(rec["request"]), _components(s["events"])
        out.append(rec)
    return out


def score(query: set[str], rec: dict, components: set[str] = frozenset()) -> float:
    t = rec["_terms"]
    base = len(query & t) / len(query | t) if query and t else 0.0
    bonus = 0.1 * len(components & rec["_components"])
    return round(base + bonus, 6)


def similar(request: str, sessions: list[dict], *, components: set[str] = frozenset(), k: int = TOP_K,
            min_score: float = MIN_SCORE) -> list[tuple[float, dict]]:
    q = terms(request)
    ranked = sorted(((score(q, r, components), r) for r in sessions), key=lambda x: (-x[0], x[1]["session"]))
    return [(s, r) for s, r in ranked if s >= min_score][:k]


def reference_text(hits: list[tuple[float, dict]], max_chars: int = MAX_CHARS) -> str:
    """给对话助手的参考说明；没有命中时为空字符串。"""
    if not hits:
        return ""
    lines = [("以下是用户以前录制的相似会话，仅供参考（尤其注意用户对 AI 结果做过的修改与未采纳的原因）；"
              "能不能用仍以本次工具的校验结果为准：")]
    for n, (s, r) in enumerate(hits, 1):
        lines.append(f"{n}. 需求：{r['request']}（相似度 {s:.2f}）")
        lines.append(f"   评价：{_RATING.get(r['rating'], r['rating'])}" + (f"；说明：{r['note']}" if r["note"] else ""))
        edits = r.get("user_edits_after_ai") or []
        if edits:
            shown = "；".join(f"{e['object']}.{e['property']} → {e['value']}" for e in edits[:5])
            lines.append(f"   用户在 AI 之后的修改：{shown}")
        for tool, result in sorted((r.get("results") or {}).items()):
            lines.append(f"   {tool} 最后的结论：{result}")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


class SessionHints:
    """对话面板用：按需求检索历史会话，返回参考文字；会话目录在每次调用时重新读取（新录的会话立即可用）。"""

    def __init__(self, root: Path, *, k: int = TOP_K, min_score: float = MIN_SCORE):
        self.root, self.k, self.min_score = Path(root), k, min_score
        self.last_hits: list[str] = []

    def __call__(self, request: str) -> str:
        hits = similar(request, load(self.root), k=self.k, min_score=self.min_score) if self.root.is_dir() else []
        self.last_hits = [r["session"] for _, r in hits]
        return reference_text(hits)


def default_hints() -> SessionHints | None:
    """对话面板用的检索：读 FAP_SESSIONS_DIR（缺省 ~/.freecad-ai-parts/sessions/）；FAP_SESSION_HINTS=0 时关闭。"""
    if os.environ.get("FAP_SESSION_HINTS", "1") == "0":
        return None
    from freecad_addon.core.session_log import DEFAULT_ROOT

    return SessionHints(Path(os.environ.get("FAP_SESSIONS_DIR") or DEFAULT_ROOT))
