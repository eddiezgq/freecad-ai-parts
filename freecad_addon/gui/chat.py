"""对话面板的对话循环（ADR-0036）：LLM 工具调用循环，与界面、FreeCAD 无关，可单独测试。

- LLM 只经 LLM 协议访问：真实调用用 AnthropicChat（密钥只从环境变量 ANTHROPIC_API_KEY 或本地 .env 读取），
  测试用 ScriptedLLM 按脚本回放，不联网
- 工具经 call_tool 回调执行（面板中为进程内 MCP 服务端），结果转换为 Anthropic 的 tool_result 内容
- 每轮用户消息最多调用 max_tool_calls 次工具，超过时停止并说明
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_TOOL_CALLS = 20

SYSTEM_PROMPT = (
    "你是 FreeCAD 中的机电零件选型与布局助手。组件是“端口 + 参数 + 包络”的黑箱；"
    "凡影响能不能用的判断都以工具的确定性校验结果为准，不要自行改判，也不要编造参数。"
    "参数一律用标准单位（N·m、rpm、kg·m²、mm、V）。\n"
    "选型：把用户的需求转成结构化需求（输出连续扭矩与输出转速必填，缺少或含义不清时先问用户；"
    "没说安全系数时用 1.2），调用 compose_chain，展示候选方案的组成、整体结论与告警原因。\n"
    "布局：用户选定方案后，place_component 放置各实例，connect_ports 只连机械端口（先法兰与安装面，再轴与孔），"
    "check_interference 检查干涉；不同刚性组的干涉件按 bbox_mm 沿 x 移开约 20 mm，同组干涉报告给用户；"
    "pass_through 中的零件提醒用户核对通孔；snapshot 截图自查；最后 verify_system 与 export_system 带 use_layout=true。\n"
    "回答用中文，简洁，先给结论。"
)


class LLM(Protocol):
    def create(self, *, system: str, messages: list[dict], tools: list[dict]) -> dict:
        """返回 {"stop_reason": ..., "content": [块（dict）]}。"""
        ...


class ScriptedLLM:
    """按脚本依次返回响应（测试用，不联网）；同时记录收到的请求。"""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def create(self, *, system: str, messages: list[dict], tools: list[dict]) -> dict:
        import copy

        self.requests.append({"system": system, "messages": copy.deepcopy(messages), "tools": tools})
        if not self.responses:
            raise RuntimeError("脚本中没有更多响应")
        return self.responses.pop(0)


def _load_dotenv() -> None:
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / ".env"
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


class AnthropicChat:
    """真实调用 Anthropic Messages API。密钥只从环境变量（或本地 .env）读取，不写入任何文件。"""

    def __init__(self, model: str | None = None, max_tokens: int = 4096):
        _load_dotenv()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("未设置 ANTHROPIC_API_KEY：请在启动 FreeCAD 前设置环境变量，或写在本仓库的 .env 中")
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("FreeCAD 的 Python 中没有 anthropic：请运行 <FreeCAD 的 python> -m pip install -e "
                               "\".[llm]\"") from exc
        self._client = anthropic.Anthropic()
        self.model = model or os.environ.get("FAP_CHAT_MODEL") or DEFAULT_MODEL
        self.max_tokens = max_tokens

    def create(self, *, system: str, messages: list[dict], tools: list[dict]) -> dict:
        msg = self._client.messages.create(model=self.model, max_tokens=self.max_tokens, system=system,
                                           tools=tools, messages=messages)
        return {"stop_reason": msg.stop_reason,
                "content": [b.model_dump(exclude_none=True) for b in msg.content]}


# ---------------------------------------------------------------- 工具结果


@dataclass
class ToolOutcome:
    """一次工具调用的结果：文字与图像（PNG 字节），是否出错。"""

    texts: list[str] = field(default_factory=list)
    images: list[bytes] = field(default_factory=list)
    is_error: bool = False

    def to_content(self) -> list[dict]:
        import base64

        out: list[dict] = [{"type": "text", "text": t} for t in self.texts]
        out += [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.b64encode(img).decode()}} for img in self.images]
        return out or [{"type": "text", "text": "（无输出）"}]


def mcp_tools_to_anthropic(tools: list[Any]) -> list[dict]:
    """MCP 工具清单（name、description、inputSchema）转为 Anthropic 的 tools 参数。"""
    def schema(t: Any) -> dict:
        return t.input_schema if hasattr(type(t), "input_schema") or "input_schema" in vars(t) else t.inputSchema

    return [{"name": t.name, "description": t.description or "", "input_schema": schema(t)} for t in tools]


def summarize(name: str, text: str, is_error: bool = False) -> str:
    """面板中显示的工具结果摘要（完整结果照样交给 LLM）。"""
    if is_error:
        return text.strip() or "出错"
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        data = None
    if not isinstance(data, dict):
        return text if len(text) <= 160 else text[:159] + "…"
    view = f"；{data['view']}" if isinstance(data.get("view"), str) and name != "snapshot" else ""
    if name == "place_component":
        if "removed" in data:
            return f"已删除 {data['removed']}{view}"
        return f"已放置 {data.get('instance')}（随之移动：{'、'.join(data.get('moved', []))}）{view}"
    if name == "connect_ports":
        moved = "、".join(data.get("moved", [])) or "无（只核对对齐）"
        note = f"；{data['note']}" if data.get("note") else ""
        return f"已配合 {data.get('a')} ↔ {data.get('b')}（{data.get('kind')}，移动：{moved}）{note}{view}"
    if name == "check_interference":
        hits = data.get("interferences", [])
        out = "无干涉" if not hits else "干涉 " + "、".join(
            f"{h['a']}–{h['b']} {h['volume_mm3']:g} mm³" for h in hits)
        if data.get("pass_through"):
            out += "；需有通孔：" + "、".join(p["instance"] for p in data["pass_through"])
        return out
    if name == "snapshot":
        return f"截图（{data.get('view')}，{data.get('width')}×{data.get('height')}）"
    if name == "compose_chain" and isinstance(data.get("candidates"), list):
        cands = data["candidates"]
        if not cands:
            return "没有找到满足需求的方案"
        first = cands[0]
        comps = "、".join(c.get("component", "") for c in first.get("system", {}).get("components", []))
        return f"{len(cands)} 个候选方案；方案 1（{first.get('overall')}）：{comps}"
    if name in ("verify_system", "export_system") and data.get("explanation"):
        first = str(data["explanation"]).strip().splitlines()[0]
        return first if len(first) <= 160 else first[:159] + "…"
    if name == "export_system" and data.get("filename"):
        return f"已导出 {data['filename']}"
    compact = json.dumps(data, ensure_ascii=False)
    return compact if len(compact) <= 160 else compact[:159] + "…"


# ---------------------------------------------------------------- 对话循环


@dataclass
class Event:
    kind: str  # user / tool_call / tool_result / assistant / error / info
    text: str = ""
    name: str | None = None
    data: Any = None
    images: list[bytes] = field(default_factory=list)


class ChatEngine:
    def __init__(self, llm: LLM, tools: list[dict], call_tool: Callable[[str, dict], ToolOutcome], *,
                 system: str = SYSTEM_PROMPT, max_tool_calls: int = MAX_TOOL_CALLS,
                 context: Callable[[str], str] | None = None):
        """context：按用户这句话给出补充参考（如相似的历史录制会话，ADR-0042），附在本轮的系统提示之后。"""
        self.llm = llm
        self.tools = tools
        self.call_tool = call_tool
        self.system = system
        self.max_tool_calls = max_tool_calls
        self.context = context
        self.messages: list[dict] = []

    def send(self, text: str, on_event: Callable[[Event], None] | None = None) -> list[Event]:
        events: list[Event] = []

        def emit(e: Event) -> None:
            events.append(e)
            if on_event:
                on_event(e)

        emit(Event("user", text))
        system = self.system
        if self.context is not None:
            try:
                extra = self.context(text)
            except Exception as exc:  # noqa: BLE001 — 参考检索出错不影响对话
                extra = ""
                emit(Event("info", f"历史会话检索出错，已跳过：{exc}"))
            if extra:
                system = f"{self.system}\n\n{extra}"
                emit(Event("info", "参考了相似的历史录制会话", data=extra))
        start = len(self.messages)
        last = self.messages[-1] if self.messages else None
        if last and last["role"] == "user" and isinstance(last["content"], list):
            # 上一轮停在工具结果（达到调用上限）：并入同一条用户消息，保持角色交替
            start -= 1
            self.messages[-1] = {"role": "user", "content": [*last["content"], {"type": "text", "text": text}]}
            saved_last = last
        else:
            self.messages.append({"role": "user", "content": text})
            saved_last = None
        calls = 0
        while True:
            try:
                resp = self.llm.create(system=system, messages=self.messages, tools=self.tools)
            except Exception as exc:  # noqa: BLE001 — 网络、密钥等错误交给界面显示
                emit(Event("error", f"调用 LLM 失败：{exc}"
                                    + ("；本轮已执行的工具改动（如布局）保留在场景中" if calls else "")))
                # 撤回本轮的消息，对话历史保持一致，便于重试
                del self.messages[start:]
                if saved_last is not None:
                    self.messages.append(saved_last)
                return events
            content = [b for b in resp.get("content", []) if isinstance(b, dict)]
            for block in content:
                if block.get("type") == "text" and block.get("text"):
                    emit(Event("assistant", block["text"]))
            uses = [b for b in content if b.get("type") == "tool_use"]
            if uses and resp.get("stop_reason") != "tool_use":
                # 响应被截断（如 max_tokens）却带着工具调用：不执行，也不留下没有结果的 tool_use，
                # 否则之后每次请求都会被 API 拒绝（#104 评审）
                content = [b for b in content if b.get("type") != "tool_use"]
                emit(Event("error", f"LLM 响应被截断（{resp.get('stop_reason')}），未执行其中的工具调用；可以让助手继续"))
                uses = []
            if content:
                self.messages.append({"role": "assistant", "content": content})
            if not uses:
                if not content:  # 空响应：撤回本轮用户消息，保持角色交替
                    del self.messages[start:]
                    if saved_last is not None:
                        self.messages.append(saved_last)
                return events
            results = []
            for use in uses:
                calls += 1
                if calls > self.max_tool_calls:
                    outcome = ToolOutcome([f"本轮工具调用已达上限 {self.max_tool_calls} 次，未执行"], is_error=True)
                else:
                    emit(Event("tool_call", name=use["name"], data=use.get("input", {})))
                    try:
                        outcome = self.call_tool(use["name"], use.get("input", {}))
                    except Exception as exc:  # noqa: BLE001
                        outcome = ToolOutcome([f"工具执行出错：{exc}"], is_error=True)
                    emit(Event("tool_result", "\n".join(outcome.texts), name=use["name"], data=outcome.is_error,
                               images=outcome.images))
                results.append({"type": "tool_result", "tool_use_id": use["id"], "content": outcome.to_content(),
                                **({"is_error": True} if outcome.is_error else {})})
            self.messages.append({"role": "user", "content": results})
            if calls > self.max_tool_calls:
                emit(Event("error", f"本轮工具调用超过 {self.max_tool_calls} 次，已停止；可以继续对话让助手接着做"))
                return events
