"""AI 模型网关（ADR-0063）：按地区选 Claude / DeepSeek、手动指定、出错换另一家；DeepSeek 的格式来回转换。
不联网：DeepSeek 用 httpx 的本地假传输，Claude 用假的后端。"""

from __future__ import annotations

import json

import httpx
import pytest

import llm_gateway as G

KEYS = {"ANTHROPIC_API_KEY": "a", "DEEPSEEK_API_KEY": "d"}


@pytest.mark.parametrize("env,expect", [
    ({**KEYS, "FAP_AI_REGION": "cn"}, ["deepseek", "claude"]),
    ({**KEYS, "FAP_AI_REGION": "intl"}, ["claude", "deepseek"]),
    ({**KEYS, "TZ": "Asia/Shanghai"}, ["deepseek", "claude"]),
    ({**KEYS, "TZ": "Europe/Berlin"}, ["claude", "deepseek"]),
    ({**KEYS, "FAP_AI_REGION": "cn", "FAP_AI_PROVIDER": "claude"}, ["claude", "deepseek"]),
    ({"DEEPSEEK_API_KEY": "d"}, ["deepseek"]),
    ({}, []),
])
def test_order(env, expect):
    assert G.order(env) == expect


def test_openai_round_trip():
    """对话面板的一轮：用户 → 助手调工具 → 工具结果（含截图）→ 再问。"""
    msgs = [{"role": "user", "content": "选一个关节"},
            {"role": "assistant", "content": [{"type": "text", "text": "我查一下"},
                                              {"type": "tool_use", "id": "t1", "name": "compose_chain", "input": {"a": 1}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                          "content": [{"type": "text", "text": "{\"ok\":1}"},
                                                      {"type": "image", "source": {"type": "base64", "data": "x"}}]}]}]
    out, fns = G.to_openai("系统", msgs, [{"name": "compose_chain", "description": "d", "input_schema": {"type": "object"}}])
    assert [m["role"] for m in out] == ["system", "user", "assistant", "tool"]
    assert out[2]["tool_calls"][0]["function"] == {"name": "compose_chain", "arguments": "{\"a\": 1}"}
    assert out[3]["tool_call_id"] == "t1" and "截图略" in out[3]["content"]
    assert fns[0]["function"]["parameters"] == {"type": "object"}
    back = G.from_openai({"id": "x", "choices": [{"finish_reason": "tool_calls", "message": {
        "content": None, "tool_calls": [{"id": "t2", "function": {"name": "verify_system", "arguments": "{\"b\":2}"}}]}}]})
    assert back == {"id": "x", "stop_reason": "tool_use",
                    "content": [{"type": "tool_use", "id": "t2", "name": "verify_system", "input": {"b": 2}}]}


def _deepseek(monkeypatch, reply):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        assert req.headers["authorization"] == "Bearer d"
        return httpx.Response(200, json=reply)

    return G.DeepSeekMessages(transport=httpx.MockTransport(handler)), seen


class _Broken:
    name = "claude"

    def create(self, **kw):
        raise RuntimeError("额度用完")


def test_fallback_and_requirement_client(monkeypatch):
    """首选 Claude 出错 → 换 DeepSeek；需求解析的 complete() 取出唯一一次工具调用。"""
    from engine import requirement_parse as R

    ds, seen = _deepseek(monkeypatch, {"id": "r1", "choices": [{"finish_reason": "tool_calls", "message": {
        "content": None, "tool_calls": [{"id": "c1", "function": {"name": R.TOOL_NAME,
                                                                  "arguments": json.dumps({"items": []})}}]}}]})
    g = G.Gateway([_Broken(), ds])
    r = g.complete(R.build_request("要一个 20 N·m 的关节"))
    assert r["tool_input"] == {"items": []} and r["provider"] == "deepseek"
    assert g.last["fallback_from"] == "claude" and seen[0]["tools"][0]["function"]["name"] == R.TOOL_NAME
    with pytest.raises(G.GatewayError, match="都调用失败"):
        G.Gateway([_Broken()]).create(system="s", messages=[{"role": "user", "content": "x"}], tools=[])


def test_no_keys(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(G, "load_dotenv", lambda: None)
    with pytest.raises(G.GatewayError, match="DEEPSEEK_API_KEY"):
        G.Gateway()
