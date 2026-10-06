# -*- coding: utf-8 -*-
"""模型网关（精简版，与问渠网关同样的约定）：美国用 Claude，国内用 DeepSeek 等 OpenAI 兼容接口。

环境变量：WQ_CLAUDE_KEY（或 ANTHROPIC_API_KEY）、WQ_CLAUDE_MODEL（默认 claude-sonnet-5）；
WQ_DEEPSEEK_KEY、WQ_DEEPSEEK_MODEL（默认 deepseek-chat）、WQ_DEEPSEEK_BASE。
都没配时 available() 为 False，AI 助手改用规则回答（仍能简报、提醒、起草提议）。
"""
import json
import logging
import os

import httpx

log = logging.getLogger("llm")


class LLM:
    def __init__(self):
        self.claude_key = os.environ.get("WQ_CLAUDE_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
        self.claude_model = os.environ.get("WQ_CLAUDE_MODEL", "claude-sonnet-5")
        self.ds_key = os.environ.get("WQ_DEEPSEEK_KEY", "")
        self.ds_model = os.environ.get("WQ_DEEPSEEK_MODEL", "deepseek-chat")
        self.ds_base = os.environ.get("WQ_DEEPSEEK_BASE", "https://api.deepseek.com")
        self.timeout = float(os.environ.get("WQ_AI_TIMEOUT", "90"))

    def available(self):
        return bool(self.claude_key or self.ds_key)

    @property
    def name(self):
        return "claude:" + self.claude_model if self.claude_key else ("deepseek:" + self.ds_model if self.ds_key else "rules")

    def run(self, system, messages, tools, call_tool, max_turns=6):
        """tools: [{name, description, input_schema}]；call_tool(name, args) → 可 JSON 化的结果。
        返回 (最终文字, 调用记录)。"""
        if self.claude_key:
            return self._claude(system, messages, tools, call_tool, max_turns)
        return self._openai(system, messages, tools, call_tool, max_turns)

    def _claude(self, system, messages, tools, call_tool, max_turns):
        msgs = [{"role": m["role"], "content": m["content"]} for m in messages]
        trace = []
        with httpx.Client(timeout=self.timeout) as c:
            for _ in range(max_turns):
                r = c.post("https://api.anthropic.com/v1/messages",
                           headers={"x-api-key": self.claude_key, "anthropic-version": "2023-06-01"},
                           json={"model": self.claude_model, "max_tokens": 1500, "system": system,
                                 "messages": msgs, "tools": tools})
                r.raise_for_status()
                body = r.json()
                msgs.append({"role": "assistant", "content": body["content"]})
                uses = [b for b in body["content"] if b.get("type") == "tool_use"]
                if not uses:
                    return "".join(b.get("text", "") for b in body["content"] if b.get("type") == "text"), trace
                results = []
                for u in uses:
                    out = call_tool(u["name"], u.get("input") or {})
                    trace.append({"tool": u["name"], "input": u.get("input"), "output": out})
                    results.append({"type": "tool_result", "tool_use_id": u["id"],
                                    "content": json.dumps(out, ensure_ascii=False, default=str)[:12000]})
                msgs.append({"role": "user", "content": results})
        return "（AI 助手查询次数过多，已停止。）", trace

    def _openai(self, system, messages, tools, call_tool, max_turns):
        msgs = [{"role": "system", "content": system}] + [{"role": m["role"], "content": m["content"]} for m in messages]
        fns = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                 "parameters": t["input_schema"]}} for t in tools]
        trace = []
        with httpx.Client(timeout=self.timeout) as c:
            for _ in range(max_turns):
                r = c.post(self.ds_base.rstrip("/") + "/chat/completions",
                           headers={"Authorization": "Bearer " + self.ds_key},
                           json={"model": self.ds_model, "messages": msgs, "tools": fns})
                r.raise_for_status()
                m = r.json()["choices"][0]["message"]
                msgs.append(m)
                calls = m.get("tool_calls") or []
                if not calls:
                    return m.get("content") or "", trace
                for tc in calls:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                    out = call_tool(tc["function"]["name"], args)
                    trace.append({"tool": tc["function"]["name"], "input": args, "output": out})
                    msgs.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": json.dumps(out, ensure_ascii=False, default=str)[:12000]})
        return "（AI 助手查询次数过多，已停止。）", trace
