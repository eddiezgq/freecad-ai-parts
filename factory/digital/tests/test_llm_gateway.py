# -*- coding: utf-8 -*-
"""模型网关（本仓库 ADR-0063）：Claude / DeepSeek 按地区自动选、手动覆盖、出错换另一家、都不可用走规则。
不联网：httpx 换成本地假传输，两家的回答是录好的样子。"""
import httpx
import pytest

from hub import llm as L

KEYS = {"WQ_CLAUDE_KEY": "c", "WQ_DEEPSEEK_KEY": "d"}


def _fake(monkeypatch, fail=()):
    """假的两家接口：fail 里的那家回 500。返回调用记录。"""
    calls = []

    def handler(req):
        who = "claude" if "anthropic" in str(req.url) else "deepseek"
        calls.append(who)
        if who in fail:
            return httpx.Response(500, json={"error": "boom"})
        if who == "claude":
            return httpx.Response(200, json={"content": [{"type": "text", "text": "Claude 答"}]})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "DeepSeek 答"}}]})

    real = httpx.Client
    monkeypatch.setattr(L.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return calls


def _ask(g):
    return g.run("系统", [{"role": "user", "content": "你好"}], [], lambda n, a: None)[0]


@pytest.mark.parametrize("env,first", [
    ({**KEYS, "WQ_AI_REGION": "cn"}, "deepseek"),
    ({**KEYS, "WQ_AI_REGION": "intl"}, "claude"),
    ({**KEYS, "WQ_TZ": "Asia/Shanghai"}, "deepseek"),          # 没设地区：按时区推断
    ({**KEYS, "WQ_TZ": "America/New_York"}, "claude"),
    ({**KEYS, "WQ_AI_REGION": "cn", "WQ_AI_PROVIDER": "claude"}, "claude"),   # 环境变量指定
    ({"WQ_DEEPSEEK_KEY": "d", "WQ_AI_REGION": "intl"}, "deepseek"),        # 只配了一家
])
def test_auto_by_region(monkeypatch, env, first):
    calls = _fake(monkeypatch)
    g = L.LLM(env)
    assert g.order()[0] == first and g.name.startswith(first)
    assert _ask(g) == ("Claude 答" if first == "claude" else "DeepSeek 答") and calls == [first]
    assert g.last["provider"] == first and g.last["ok"]


def test_override_and_fallback(monkeypatch):
    calls = _fake(monkeypatch, fail=("deepseek",))
    g = L.LLM({**KEYS, "WQ_AI_REGION": "cn"})
    assert _ask(g) == "Claude 答" and calls == ["deepseek", "claude"]          # 国内首选出错 → 换 Claude
    assert g.last == {**g.last, "provider": "claude", "ok": True, "fallback_from": "deepseek"}
    g.override = "claude"                                                       # 管理员选 Claude，优先于地区
    assert g.order() == ["claude", "deepseek"] and g.status()["setting"] == "claude"
    assert g.status()["configured"] == {"claude": True, "deepseek": True}


def test_all_fail_and_none(monkeypatch):
    _fake(monkeypatch, fail=("claude", "deepseek"))
    g = L.LLM(KEYS)
    with pytest.raises(httpx.HTTPError):
        _ask(g)
    assert g.last["ok"] is False
    none = L.LLM({})
    assert not none.available() and none.name == "rules" and none.order() == []
    assert "WQ_CLAUDE_KEY" not in str(none.status())                              # 状态里没有密钥
