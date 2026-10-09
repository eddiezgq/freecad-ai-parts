# -*- coding: utf-8 -*-
"""模型网关（精简版，与问渠网关同样的约定）：Claude 与 DeepSeek 等 OpenAI 兼容接口，可切换
（第 30 轮 H-6；freecad-ai-parts ADR-0063）。

选哪家：管理员在“系统设置”里选的（override）> WQ_AI_PROVIDER（claude / deepseek / auto，缺省 auto）；
auto 时看 WQ_AI_REGION：cn 用 DeepSeek，其他用 Claude；没设 WQ_AI_REGION 时按 WQ_TZ（中国时区算 cn）。
**国内部署（地区 cn）只用 DeepSeek**（合规：国内只用已备案模型）：不论设置、环境变量怎么选，都不调用 Claude，
DeepSeek 出错也不换到 Claude，而是报错、AI 助手改用规则回答。
其他地区：选中的一家没配密钥、调用出错或超时，换另一家；两家都不可用时 available() 为 False，AI 助手改用规则回答。
每次调用记下实际用的哪家（last）。

环境变量：WQ_CLAUDE_KEY（或 ANTHROPIC_API_KEY）、WQ_CLAUDE_MODEL（默认 claude-sonnet-5）；
WQ_DEEPSEEK_KEY（或 DEEPSEEK_API_KEY）、WQ_DEEPSEEK_MODEL（默认 deepseek-chat）、WQ_DEEPSEEK_BASE。
"""
import json
import logging
import os
import time

import httpx

log = logging.getLogger("llm")

PROVIDERS = ("claude", "deepseek")
CN_TZ = ("Asia/Shanghai", "Asia/Chongqing", "Asia/Harbin", "Asia/Urumqi", "PRC")


def region_of(env=None):
    """部署地区：WQ_AI_REGION（cn / intl）；没设时按 WQ_TZ 推断。"""
    env = os.environ if env is None else env
    r = (env.get("WQ_AI_REGION") or "").strip().lower()
    if r in ("cn", "intl"):
        return r
    return "cn" if (env.get("WQ_TZ") or env.get("TZ") or "") in CN_TZ else "intl"


class LLM:
    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.claude_key = env.get("WQ_CLAUDE_KEY") or env.get("ANTHROPIC_API_KEY", "")
        self.claude_model = env.get("WQ_CLAUDE_MODEL", "claude-sonnet-5")
        self.ds_key = env.get("WQ_DEEPSEEK_KEY") or env.get("DEEPSEEK_API_KEY", "")
        self.ds_model = env.get("WQ_DEEPSEEK_MODEL", "deepseek-chat")
        self.ds_base = env.get("WQ_DEEPSEEK_BASE", "https://api.deepseek.com")
        self.timeout = float(env.get("WQ_AI_TIMEOUT", "90"))
        self.provider = (env.get("WQ_AI_PROVIDER") or "auto").strip().lower()
        self.region = region_of(env)
        self.override = None            # 管理员在系统设置里选的（claude / deepseek / auto），优先于环境变量
        self.last = None                # 最近一次调用：{provider, ok, error?, fallback_from?, ts}

    def configured(self, p):
        return bool(self.claude_key if p == "claude" else self.ds_key)

    def allowed(self):
        """这个地区能用哪几家：国内只用 DeepSeek（已备案）。"""
        return ("deepseek",) if self.region == "cn" else PROVIDERS

    def preferred(self):
        """首选哪家：设置 > 环境变量 > 按地区；国内一律 DeepSeek。"""
        if self.region == "cn":
            return "deepseek"
        p = self.override if self.override in PROVIDERS + ("auto",) else self.provider
        if p in PROVIDERS:
            return p
        return "deepseek" if self.region == "cn" else "claude"

    def order(self):
        """依次尝试的顺序（只含配了密钥、本地区允许的）。"""
        first = self.preferred()
        ok = self.allowed()
        return [p for p in (first, next(x for x in PROVIDERS if x != first)) if p in ok and self.configured(p)]

    def available(self):
        return bool(self.order())

    def label(self, p):
        return "claude:" + self.claude_model if p == "claude" else "deepseek:" + self.ds_model

    @property
    def name(self):
        o = self.order()
        return self.label(o[0]) if o else "rules"

    def status(self):
        """系统设置页要看的：选择、地区、两家是否配好、最近一次调用。不含密钥。"""
        return {"setting": self.override or self.provider, "env_provider": self.provider, "region": self.region,
                "preferred": self.preferred(), "order": self.order(), "name": self.name, "allowed": list(self.allowed()),
                "configured": {p: self.configured(p) for p in PROVIDERS},
                "models": {"claude": self.claude_model, "deepseek": self.ds_model}, "last": self.last}

    def run(self, system, messages, tools, call_tool, max_turns=6):
        """tools: [{name, description, input_schema}]；call_tool(name, args) → 可 JSON 化的结果。
        返回 (最终文字, 调用记录)。首选的一家出错就换另一家；都出错时抛出最后一个错误。"""
        err, tried = None, []
        for p in self.order():
            try:
                fn = self._claude if p == "claude" else self._openai
                out = fn(system, messages, tools, call_tool, max_turns)
                self.last = {"provider": p, "ok": True, "ts": time.time(), **({"fallback_from": tried[0]} if tried else {})}
                return out
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
                log.warning("%s 调用失败，换另一家：%s", p, e)
                err = e
                tried.append(p)
                self.last = {"provider": p, "ok": False, "error": str(e)[:300], "ts": time.time()}
        if err is None:
            raise RuntimeError("没有可用的 AI 模型（两家都没配密钥）")
        raise err

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
