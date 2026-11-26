"""有限元 AI 的模型客户端（ADR-0096 第 2 步）：经网关用 Claude 或 DeepSeek；记实际回答的是哪家；录制只记请求里那个模型的。
不联网：DeepSeek 用 httpx 的模拟传输，走真实的格式转换。"""

from __future__ import annotations

import json

import pytest

from assist import fea_draft as D
from assist import fea_report as R
from assist.llm import GatewayClient
from llm_gateway import ClaudeMessages, DeepSeekMessages, Gateway, GatewayError
from tests.test_assist_fea_draft import GOOD, SAMPLES, _need_fea


class Fake:
    """假后端：Anthropic 格式进出"""

    def __init__(self, name, model, tool_input=None, fail=False, n_tools=1):
        self.name, self.model, self.tool_input, self.fail, self.n_tools = name, model, tool_input, fail, n_tools
        self.calls = []

    def create(self, *, system, messages, tools, max_tokens=4096):
        self.calls.append(max_tokens)
        if self.fail:
            raise RuntimeError("额度用完")
        return {"id": f"{self.name}-1", "stop_reason": "tool_use",
                "content": [{"type": "tool_use", "id": f"t{i}", "name": tools[0]["name"], "input": self.tool_input}
                            for i in range(self.n_tools)]}


def _req(model):
    return {"model": model, "prompt_version": "x/1", "system": "s", "user": "u",
            "tool": {"name": "t", "description": "d", "input_schema": {"type": "object"}}}


def test_forced_provider_records_and_reports_itself(tmp_path):
    ds = Fake("deepseek", "deepseek-chat", {"a": 1})
    c = GatewayClient(gateway=Gateway([ds]), record_dir=tmp_path)
    assert (c.provider, c.model) == ("deepseek", "deepseek-chat")
    r = c.complete(_req("deepseek-chat"))
    assert r["provider"] == "deepseek" and r["model"] == "deepseek-chat" and r["tool_input"] == {"a": 1}
    assert ds.calls == [8000]                                     # deepseek-chat 一次最多输出 8K
    rec = [json.loads(f.read_text(encoding="utf-8")) for f in tmp_path.glob("*.json")]
    assert len(rec) == 1 and rec[0]["model"] == "deepseek-chat" and rec[0]["response"]["provider"] == "deepseek"


def test_fallback_is_reported_and_not_recorded_as_first_choice(tmp_path):
    """DeepSeek 出错换 Claude：返回里写明实际是 Claude、从 DeepSeek 换来的；不按 DeepSeek 的请求录制"""
    c = GatewayClient(gateway=Gateway([Fake("deepseek", "deepseek-chat", fail=True), Fake("claude", "claude-x", {"a": 2})]),
                      record_dir=tmp_path)
    r = c.complete(_req("deepseek-chat"))
    assert (r["provider"], r["model"], r["fallback_from"]) == ("claude", "claude-x", "deepseek")
    assert not list(tmp_path.glob("*.json"))


def test_must_call_the_tool_exactly_once():
    with pytest.raises(GatewayError, match="一次工具"):
        GatewayClient(gateway=Gateway([Fake("claude", "claude-x", {}, n_tools=2)])).complete(_req("claude-x"))
    with pytest.raises(GatewayError, match="不认识"):
        GatewayClient("gpt")


def test_a_truncated_answer_is_not_used(tmp_path):
    """真实运行里见过：回答写到一半被截断，工具参数整个是空的（案例 B2 构型，ADR-0115 44.5.6.1）——不当答案、不录制"""
    cut = Fake("claude", "claude-x", {})
    cut.create = lambda **kw: {"id": "m", "stop_reason": "max_tokens",
                               "content": [{"type": "tool_use", "id": "t", "name": "t", "input": {}}]}
    with pytest.raises(GatewayError, match="截断"):
        GatewayClient(gateway=Gateway([cut]), record_dir=tmp_path).complete(_req("claude-x"))
    assert not list(tmp_path.glob("*.json"))
    big = Fake("claude", "claude-x", {"a": 1})
    GatewayClient(gateway=Gateway([big])).complete(_req("claude-x"))
    assert big.calls == [32000]


def test_draft_and_explanation_record_the_model_that_answered():
    """起草的依据说明、报告解释里写实际回答的模型（换了另一家也如实写）"""
    _need_fea()
    s = SAMPLES["S1-RJ201-torque"]
    c = GatewayClient(gateway=Gateway([Fake("deepseek", "deepseek-chat", fail=True),
                                       Fake("claude", "claude-x", GOOD["S1-RJ201-torque"])]))
    r = D.draft(s["statement"], [str(D.ROOT / p) for p in s["parts"]], c, model=c.model)
    assert r["provider"] == "claude" and "模型 claude-x" in r["study"]["provenance"]["note"]
    _s, res = R.load_fixture("rj201-torque")
    e = R.explain(res, GatewayClient(gateway=Gateway([Fake("deepseek", "deepseek-chat", {"paragraphs": [], "suggestions": []})])),
                  model="deepseek-chat")
    assert e["model"] == "deepseek-chat"


def test_deepseek_wire_format_round_trip(monkeypatch):
    """DeepSeek（OpenAI 兼容接口）：起草的工具定义原样送出，回答里的工具调用转回来，程序核对照常（不联网）"""
    _need_fea()
    import httpx

    s = SAMPLES["S10-CANT-rect"]
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.update(body)
        assert request.headers["authorization"] == "Bearer test-key"
        call = {"id": "c1", "type": "function",
                "function": {"name": body["tools"][0]["function"]["name"],
                             "arguments": json.dumps(GOOD["S10-CANT-rect"], ensure_ascii=False)}}
        return httpx.Response(200, json={"id": "ds-1", "choices": [{"finish_reason": "tool_calls",
                                                                     "message": {"content": None, "tool_calls": [call]}}]})

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    c = GatewayClient(gateway=Gateway([DeepSeekMessages(transport=httpx.MockTransport(handler))]))
    r = D.draft(s["statement"], [str(D.ROOT / p) for p in s["parts"]], c, model=c.model)
    assert sent["model"] == "deepseek-chat" and sent["max_tokens"] == 8000
    assert sent["tools"][0]["function"]["parameters"] == D.TOOL_SCHEMA
    assert sent["messages"][0]["role"] == "system" and "CANT-500" in sent["messages"][1]["content"]
    assert r["provider"] == "deepseek" and not r["rejected"] and not r["questions"]
    assert D.score(r, s["answer"])["wrong_face"] == 0


@pytest.mark.freecad
def test_fem_flow_client_follows_region(monkeypatch, tmp_path):
    """FreeCAD 里的起草、解释：国内（FAP_AI_REGION=cn）首选 DeepSeek、其他地方首选 Claude；回放时模型名与录制对得上"""
    import sys
    import types

    pytest.importorskip("FreeCAD")
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=lambda: object()))   # 不联网、不必装 SDK
    monkeypatch.setattr("llm_gateway.load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr("assist.llm.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("FAP_LLM_REPLAY", raising=False)
    monkeypatch.delenv("FAP_AI_PROVIDER", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    from freecad_addon.fc import fem_flow as F

    monkeypatch.setenv("FAP_AI_REGION", "cn")
    c = F.llm_client()
    assert [b.name for b in c.gateway.backends] == ["deepseek", "claude"] and c.model == "deepseek-chat"
    monkeypatch.setenv("FAP_AI_REGION", "intl")
    c = F.llm_client()
    assert isinstance(c.gateway.backends[0], ClaudeMessages)
    monkeypatch.setenv("FAP_LLM_REPLAY", str(tmp_path))
    monkeypatch.setenv("FAP_AI_PROVIDER", "deepseek")
    assert F.llm_client().model == "deepseek-chat"
