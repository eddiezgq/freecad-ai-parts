"""AI 模型网关（ADR-0063）：Claude 与 DeepSeek 可切换，国内自动选 DeepSeek、其他地方选 Claude，出错换另一家。

FreeCAD 一侧的对话面板与需求解析用它；工厂一侧在 `factory/digital/hub/llm.py`，规则相同。
对外是 Anthropic Messages 的格式（content 块、tool_use、tool_result）：DeepSeek（OpenAI 兼容接口）在这里来回转换，
调用方不用管是哪家。规格书抽取（ingest/）要把页图交给模型看，不经这里，仍只用 Claude。

选择：FAP_AI_PROVIDER = auto（缺省）| claude | deepseek；auto 时看 FAP_AI_REGION（cn / intl），没设时按时区推断
（TZ 是中国时区，或本机 UTC+8 且语言是简体中文，算 cn）。
密钥：ANTHROPIC_API_KEY、DEEPSEEK_API_KEY（只从环境变量或本仓库 .env 读，不写入任何文件）。
模型：FAP_CLAUDE_MODEL（缺省 claude-sonnet-5-5）、FAP_DEEPSEEK_MODEL（缺省 deepseek-chat）、FAP_DEEPSEEK_BASE。
"""

from __future__ import annotations

import datetime as _dt
import json
import locale
import os
import time
from collections.abc import Mapping
from typing import Any

PROVIDERS = ("claude", "deepseek")
CN_TZ = ("Asia/Shanghai", "Asia/Chongqing", "Asia/Harbin", "Asia/Urumqi", "PRC")
CLAUDE_MODEL = "claude-sonnet-5-5"
DEEPSEEK_MODEL = "deepseek-chat"


class GatewayError(RuntimeError):
    """两家都不可用（没配密钥或都出错）。"""


def load_dotenv() -> None:
    """本仓库根目录的 .env（只补没设的变量）。"""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
            value = value[1:-1]
        os.environ.setdefault(name, value)


def region_of(env: Mapping[str, str] | None = None) -> str:
    """cn 或 intl。"""
    env = os.environ if env is None else env
    r = (env.get("FAP_AI_REGION") or "").strip().lower()
    if r in ("cn", "intl"):
        return r
    if (env.get("TZ") or "") in CN_TZ:
        return "cn"
    if env is os.environ:              # 只在真实环境里看本机时区与语言（测试传入的 env 不看）
        off = _dt.datetime.now().astimezone().utcoffset()
        lang = (locale.getlocale()[0] or os.environ.get("LANG", "") or "").lower()
        if off == _dt.timedelta(hours=8) and lang.startswith(("zh_cn", "chinese (simplified)", "zh-cn")):
            return "cn"
    return "intl"


def preferred(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    p = (env.get("FAP_AI_PROVIDER") or "auto").strip().lower()
    if p in PROVIDERS:
        return p
    return "deepseek" if region_of(env) == "cn" else "claude"


def order(env: Mapping[str, str] | None = None) -> list[str]:
    """依次尝试的顺序，只含配了密钥的。"""
    env = os.environ if env is None else env
    first = preferred(env)
    keys = {"claude": env.get("ANTHROPIC_API_KEY"), "deepseek": env.get("DEEPSEEK_API_KEY")}
    return [p for p in (first, next(x for x in PROVIDERS if x != first)) if keys[p]]


# ---------------------------------------------------------------- 两家的实现（同一个接口：Anthropic 格式进、Anthropic 格式出）


class ClaudeMessages:
    name = "claude"

    def __init__(self, model: str | None = None):
        try:
            import anthropic
        except ImportError as exc:
            raise GatewayError("没有安装 anthropic：pip install -e \".[llm]\"") from exc
        self._client = anthropic.Anthropic()
        self.model = model or os.environ.get("FAP_CLAUDE_MODEL") or CLAUDE_MODEL

    def create(self, *, system: str, messages: list[dict], tools: list[dict], max_tokens: int = 4096) -> dict:
        msg = self._client.messages.create(model=self.model, max_tokens=max_tokens, system=system, tools=tools,
                                           messages=messages)
        return {"id": msg.id, "stop_reason": msg.stop_reason,
                "content": [b.model_dump(exclude_none=True) for b in msg.content]}


def to_openai(system: str, messages: list[dict], tools: list[dict]) -> tuple[list[dict], list[dict]]:
    """Anthropic 格式的对话 → OpenAI 兼容格式。工具结果里的图像 DeepSeek 看不了，换成一句说明。"""
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            out.append({"role": m["role"], "content": c})
            continue
        if m["role"] == "assistant":
            text = "".join(b.get("text", "") for b in c if b.get("type") == "text")
            calls = [{"id": b["id"], "type": "function",
                      "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}}
                     for b in c if b.get("type") == "tool_use"]
            out.append({"role": "assistant", "content": text or None, **({"tool_calls": calls} if calls else {})})
            continue
        texts = []
        for b in c:
            if b.get("type") == "tool_result":
                parts = b.get("content")
                if isinstance(parts, str):
                    body = parts
                else:
                    body = "\n".join(p.get("text", "") if p.get("type") == "text" else "（截图略：当前模型不看图）"
                                     for p in parts or [])
                out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": body or "（无输出）"})
            elif b.get("type") == "text":
                texts.append(b["text"])
        if texts:
            out.append({"role": "user", "content": "\n".join(texts)})
    fns = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                             "parameters": t["input_schema"]}} for t in tools]
    return out, fns


def from_openai(body: dict) -> dict:
    """OpenAI 兼容格式的回答 → Anthropic 格式。"""
    ch = body["choices"][0]
    m = ch["message"]
    blocks: list[dict] = [{"type": "text", "text": m["content"]}] if m.get("content") else []
    for tc in m.get("tool_calls") or []:
        blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                       "input": json.loads(tc["function"].get("arguments") or "{}")})
    stop = "tool_use" if m.get("tool_calls") else ("max_tokens" if ch.get("finish_reason") == "length" else "end_turn")
    return {"id": body.get("id"), "stop_reason": stop, "content": blocks}


class DeepSeekMessages:
    name = "deepseek"

    def __init__(self, model: str | None = None, base: str | None = None, transport: Any = None):
        self.key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.key:
            raise GatewayError("未设置 DEEPSEEK_API_KEY")
        self.model = model or os.environ.get("FAP_DEEPSEEK_MODEL") or DEEPSEEK_MODEL
        self.base = (base or os.environ.get("FAP_DEEPSEEK_BASE") or "https://api.deepseek.com").rstrip("/")
        self.transport = transport

    def create(self, *, system: str, messages: list[dict], tools: list[dict], max_tokens: int = 4096) -> dict:
        import httpx

        msgs, fns = to_openai(system, messages, tools)
        payload = {"model": self.model, "messages": msgs, "max_tokens": max_tokens, **({"tools": fns} if fns else {})}
        with httpx.Client(timeout=120, transport=self.transport) as c:
            r = c.post(self.base + "/chat/completions", headers={"Authorization": "Bearer " + self.key}, json=payload)
            r.raise_for_status()
            return from_openai(r.json())


# ---------------------------------------------------------------- 网关：按顺序试，出错换另一家


class Gateway:
    """create(system=, messages=, tools=) 与 FreeCAD 对话面板的 LLM 协议一致；complete(request) 与需求解析的客户端一致。"""

    def __init__(self, backends: list[Any] | None = None):
        if backends is None:
            load_dotenv()
            backends = []
            for p in order():
                try:
                    backends.append(ClaudeMessages() if p == "claude" else DeepSeekMessages())
                except GatewayError:
                    continue
        if not backends:
            raise GatewayError("没有可用的 AI 模型：请设置 ANTHROPIC_API_KEY 或 DEEPSEEK_API_KEY（国内建议 DeepSeek）")
        self.backends = backends
        self.last: dict | None = None

    @property
    def name(self) -> str:
        return self.backends[0].name

    def create(self, *, system: str, messages: list[dict], tools: list[dict], max_tokens: int = 4096) -> dict:
        err: Exception | None = None
        tried: list[str] = []
        for b in self.backends:
            try:
                out = b.create(system=system, messages=messages, tools=tools, max_tokens=max_tokens)
                self.last = {"provider": b.name, "ok": True, "ts": time.time(), **({"fallback_from": tried[0]} if tried else {})}
                return out
            except Exception as e:  # noqa: BLE001 —— 网络、额度、格式错误都换另一家
                err = e
                tried.append(b.name)
                self.last = {"provider": b.name, "ok": False, "error": str(e)[:300], "ts": time.time()}
        raise GatewayError(f"两家模型都调用失败：{err}") from err

    def complete(self, request: dict) -> dict:
        """需求解析（engine/requirement_parse 的 build_request）：强制一次工具调用，返回 {id, tool_input, simulated}。"""
        r = self.create(system=request["system"], messages=[{"role": "user", "content": request["user"]}],
                        tools=[request["tool"]], max_tokens=16000)
        uses = [b for b in r["content"] if b.get("type") == "tool_use"]
        if len(uses) != 1:
            raise GatewayError(f"模型没有按要求调用一次工具（{len(uses)} 次）")
        return {"id": r.get("id"), "tool_input": uses[0].get("input") or {}, "simulated": False,
                "provider": (self.last or {}).get("provider")}
