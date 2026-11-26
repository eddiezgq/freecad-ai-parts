"""有限元 AI（起草、解释）用的模型客户端（ADR-0096 第 2 步）：经模型网关（ADR-0063），国内用 DeepSeek、其他地方用 Claude。

接口与 `ingest.llm_extract` 的客户端一致：`complete(request) -> {"id", "tool_input", "simulated", "provider", "model"}`，
request 是 `assist.fea_draft.build_request` / `assist.fea_report.build_request` 生成的（model、prompt_version、system、user、tool）。
- 不指定 provider：按网关的规则（FAP_AI_PROVIDER / 地区）选，出错换另一家；
- 指定 provider（验收、录制用）：只用这一家，不换——量的是这一家的本事。
返回里写明实际回答的是哪家、哪个模型；录制只在实际回答的就是请求里那个模型时才写（录制按请求哈希存，请求里有模型名）。
"""

from __future__ import annotations

from pathlib import Path

from llm_gateway import ClaudeMessages, DeepSeekMessages, Gateway, GatewayError, load_dotenv

MAX_TOKENS = {"claude": 16000, "deepseek": 8000}      # deepseek-chat 一次最多输出 8K


class GatewayClient:
    def __init__(self, provider: str | None = None, record_dir: Path | None = None, gateway: Gateway | None = None):
        if gateway is None:
            load_dotenv()
            if provider is None:
                gateway = Gateway()
            elif provider in ("claude", "deepseek"):
                gateway = Gateway([ClaudeMessages() if provider == "claude" else DeepSeekMessages()])
            else:
                raise GatewayError(f"不认识的模型提供方 {provider}（claude / deepseek）")
        self.gateway = gateway
        self.record_dir = record_dir

    @property
    def provider(self) -> str:
        return self.gateway.backends[0].name

    @property
    def model(self) -> str:
        """首选那一家的模型名：起草、解释的请求里写它（录制按请求哈希存，两家各录各的）"""
        return self.gateway.backends[0].model

    def complete(self, request: dict) -> dict:
        r = self.gateway.create(system=request["system"], messages=[{"role": "user", "content": request["user"]}],
                                tools=[request["tool"]], max_tokens=MAX_TOKENS.get(self.provider, 8000))
        uses = [b for b in r["content"] if b.get("type") == "tool_use"]
        if len(uses) != 1:
            text = "".join(b.get("text", "") for b in r["content"] if b.get("type") == "text")
            raise GatewayError(f"模型没有按要求调用一次工具（{len(uses)} 次，停在 {r.get('stop_reason')}，文字 {len(text)} 字：{text[:300]}）；可重试")
        last = self.gateway.last or {}
        actual = last.get("provider", self.provider)
        model = next((b.model for b in self.gateway.backends if b.name == actual), request["model"])
        resp = {"id": r.get("id") or "", "tool_input": uses[0].get("input") or {}, "simulated": False,
                "provider": actual, "model": model, **({"fallback_from": last["fallback_from"]} if "fallback_from" in last else {})}
        if self.record_dir is not None and model == request["model"]:
            from ingest.llm_extract import write_recording

            write_recording(Path(self.record_dir), request, {k: resp[k] for k in ("id", "tool_input", "simulated", "provider", "model")})
        return resp
