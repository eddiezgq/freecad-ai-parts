"""操作录制的会话包（ADR-0042，issue #146）：只用标准库，不依赖 FreeCAD，可单独测试。

一次录制是 ~/.freecad-ai-parts/sessions/ 下的一个目录：

    meta.json        格式 session/1、开始与结束时间、环境说明、事件与截图数
    events.jsonl     每行一个事件：{seq, t（距开始的秒数）, kind, ...}；按发生顺序
    snapshots/       关键画面截图 0001.png …（限频）
    outcome.json     停止时写：用户评价（accepted / modified / rejected）、说明、最后的方案与校验结论

事件种类（kind）：command（界面命令）、doc_change（文档改动，带 origin：user / ai）、selection、
chat（对话消息、工具调用与结果）、snapshot、note。

写盘前去掉密钥：ANTHROPIC_API_KEY 等环境变量的值、形如 sk-ant-… 的字符串一律替换为 [已隐去]。
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

FORMAT = "session/1"
DEFAULT_ROOT = Path.home() / ".freecad-ai-parts" / "sessions"
REDACTED = "[已隐去]"
MAX_TEXT = 200
RATINGS = ("accepted", "modified", "rejected")
KINDS = ("command", "doc_change", "selection", "chat", "snapshot", "note")
SECRET_ENV = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "FAP_BRIDGE_TOKEN", "DATABASE_URL")
_KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9]{20,}")


class RecorderError(RuntimeError):
    pass


def short(value: Any, limit: int = MAX_TEXT) -> str:
    """属性值等的简短表示：字符串原样，其他用 repr；超长截断。"""
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Redactor:
    def __init__(self, env: Mapping[str, str] | None = None):
        env = os.environ if env is None else env
        self.values = sorted({v for k in SECRET_ENV if len(v := env.get(k, "") or "") >= 8}, key=len, reverse=True)

    def text(self, s: str) -> str:
        for v in self.values:
            s = s.replace(v, REDACTED)
        return _KEY_PATTERN.sub(REDACTED, s)

    def __call__(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.text(obj)
        if isinstance(obj, dict):
            return {self.text(str(k)): self(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self(v) for v in obj]
        return obj


class SessionRecorder:
    """线程安全的录制器：界面线程记文档改动，对话线程记消息与工具调用。"""

    def __init__(self, root: Path | str = DEFAULT_ROOT, *, clock: Callable[[], float] = time.time,
                 env: Mapping[str, str] | None = None, snapshot_interval_s: float = 2.0):
        self.root = Path(root)
        self._clock = clock
        self._redact = Redactor(env)
        self.snapshot_interval_s = snapshot_interval_s
        self._lock = threading.Lock()
        self._dir: Path | None = None
        self._events = None
        self._seq = 0
        self._t0 = 0.0
        self._ai_depth = 0
        self._last_snapshot = -1e18
        self._snapshots = 0
        self._last_values: dict[tuple, str] = {}
        self._meta: dict = {}
        self.last_results: dict[str, Any] = {}

    # ------------------------------------------------------------ 开始与停止

    @property
    def active(self) -> bool:
        return self._dir is not None

    @property
    def directory(self) -> Path | None:
        return self._dir

    def start(self, meta: Mapping[str, Any] | None = None, *, name: str | None = None) -> Path:
        with self._lock:
            if self._dir is not None:
                raise RecorderError("已在录制中")
            now = self._clock()
            stamp = _dt.datetime.fromtimestamp(now, _dt.UTC).astimezone().strftime("%Y%m%d-%H%M%S")  # 本地时间
            d = self.root / (name or f"{stamp}-{secrets.token_hex(3)}")
            (d / "snapshots").mkdir(parents=True, exist_ok=False)
            self._dir, self._t0, self._seq, self._snapshots = d, now, 0, 0
            self._ai_depth, self._last_snapshot = 0, -1e18
            self._last_values.clear()
            self.last_results = {}
            self._events = (d / "events.jsonl").open("w", encoding="utf-8")
            self._meta = {"format": FORMAT, "started_at": _iso(now), **self._redact(dict(meta or {}))}
            _write_json(d / "meta.json", self._meta)
            return d

    def stop(self, *, rating: str | None = None, note: str = "", extra: Mapping[str, Any] | None = None) -> Path:
        """停止录制，写评价与结果；返回会话目录。rating 为 accepted / modified / rejected 或不评。"""
        if rating is not None and rating not in RATINGS:
            raise RecorderError(f"评价须为 {'、'.join(RATINGS)} 之一")
        with self._lock:
            if self._dir is None:
                raise RecorderError("没有在录制")
            d = self._dir
            self._events.close()
            outcome = {"format": FORMAT, "rating": rating, "note": note, **dict(extra or {}),
                       "last_results": self.last_results}
            _write_json(d / "outcome.json", self._redact(outcome))
            self._meta.update(ended_at=_iso(self._clock()), events=self._seq, snapshots=self._snapshots)
            _write_json(d / "meta.json", self._meta)
            self._dir, self._events = None, None
            return d

    # ------------------------------------------------------------ 改动来源

    def begin_ai(self) -> None:
        """AI 助手的工具调用开始：之后的文档改动标为 ai，直到 end_ai。"""
        with self._lock:
            self._ai_depth += 1

    def end_ai(self) -> None:
        with self._lock:
            self._ai_depth = max(0, self._ai_depth - 1)

    @property
    def origin(self) -> str:
        return "ai" if self._ai_depth else "user"

    # ------------------------------------------------------------ 事件

    def event(self, kind: str, **data: Any) -> dict | None:
        """记一个事件；未在录制时什么都不做，返回 None。"""
        if kind not in KINDS:
            raise RecorderError(f"未知事件种类 {kind}")
        with self._lock:
            if self._dir is None:
                return None
            if kind == "doc_change":
                data.setdefault("origin", "ai" if self._ai_depth else "user")
            self._seq += 1
            rec = {"seq": self._seq, "t": round(self._clock() - self._t0, 3), "kind": kind, **self._redact(data)}
            self._events.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
            self._events.flush()
            return rec

    def doc_change(self, doc: str, obj: str, op: str, prop: str | None = None, value: Any = None, *,
                   type_id: str | None = None) -> dict | None:
        """文档改动：op 为 created / changed / deleted。同一属性的值没变时不重复记。"""
        if op not in ("created", "changed", "deleted"):
            raise RecorderError(f"未知改动 {op}")
        data: dict = {"doc": doc, "object": obj, "op": op}
        if type_id:
            data["type"] = type_id
        if op == "changed":
            text = value if isinstance(value, (dict, list)) else short(value)
            key = (doc, obj, prop)
            with self._lock:
                if self._last_values.get(key) == text:
                    return None
                self._last_values[key] = text
            data.update(property=prop, value=text)
            if isinstance(text, (dict, list)):
                data["value"] = text
        elif op == "deleted":
            with self._lock:
                for key in [k for k in self._last_values if k[:2] == (doc, obj)]:
                    del self._last_values[key]
        return self.event("doc_change", **data)

    def next_snapshot(self) -> Path | None:
        """距上次截图已超过限频间隔时，返回这次截图应保存的路径（调用方保存后再调 snapshot_saved）。"""
        with self._lock:
            if self._dir is None or self._clock() - self._last_snapshot < self.snapshot_interval_s:
                return None
            self._last_snapshot = self._clock()
            return self._dir / "snapshots" / f"{self._snapshots + 1:04d}.png"

    def snapshot_saved(self, path: Path, *, view: str = "") -> dict | None:
        with self._lock:
            self._snapshots += 1
        return self.event("snapshot", file=f"snapshots/{Path(path).name}", view=view)

    def chat(self, role: str, *, text: str = "", name: str | None = None, data: Any = None,
             is_error: bool = False) -> dict | None:
        """对话事件：role 为 user / assistant / tool_call / tool_result / error。工具结果只留摘要。"""
        rec: dict = {"role": role}
        if text:
            rec["text"] = short(text, 2000)
        if name:
            rec["name"] = name
        if data is not None:
            rec["data"] = data if isinstance(data, (dict, list)) else short(data)
        if is_error:
            rec["is_error"] = True
        return self.event("chat", **rec)

    def note_result(self, tool: str, result: Any) -> None:
        """记住每个工具最近一次的结果（停止时写进 outcome.json，如最后的方案与校验结论）。"""
        with self._lock:
            if self._dir is not None:
                self.last_results[tool] = result


def _iso(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts, _dt.UTC).isoformat(timespec="seconds")


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_session(directory: Path | str) -> dict:
    """读一个会话包：{meta, events, outcome}；outcome 在录制未正常结束时为 None。"""
    d = Path(directory)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    if meta.get("format") != FORMAT:
        raise RecorderError(f"不支持的会话格式 {meta.get('format')}")
    events = [json.loads(ln) for ln in (d / "events.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    out = d / "outcome.json"
    return {"meta": meta, "events": events,
            "outcome": json.loads(out.read_text(encoding="utf-8")) if out.is_file() else None}
