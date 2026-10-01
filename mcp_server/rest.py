"""REST 接口（M4a #69）：与 MCP 工具一一对应，供非 MCP 客户端（如机器人学院）使用。

与 MCP 共用 mcp_server.tools 的同一组函数，结果完全一致。挂在同一个 HTTP 服务上：
MCP 在 /mcp，REST 在 /api。

| 方法 | 路径 | 对应工具 |
| --- | --- | --- |
| GET | /api/health | server_info |
| GET | /api/components?category=&vendor=&text=&params=<JSON>&limit= | search_components |
| GET | /api/components/{id} | get_component |
| GET | /api/components/{id}/ports/{port}/compatible?category=&include_unknown=&via_adapters=&limit= | find_compatible |
| POST | /api/compose  {requirement, top_n?, include_unknown?, lang?} | compose_chain |
| POST | /api/verify   {system, lang?} | verify_system |
| POST | /api/export   {system, format?} | export_system |

入参错误返回 400，组件或端口不存在返回 404，响应体为 {"error": 说明}。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server import tools


def _error(exc: Exception) -> JSONResponse:
    msg = str(exc)
    status = 404 if ("不存在" in msg or "没有端口" in msg) else 400
    return JSONResponse({"error": msg}, status_code=status)


def _bool(v: str | None, default: bool) -> bool:
    if v is None:
        return default
    if v.lower() in ("1", "true", "yes"):
        return True
    if v.lower() in ("0", "false", "no"):
        return False
    raise tools.ToolInputError(f"布尔参数只能是 true / false，现为 {v!r}")


def _int(v: str | None, default: int) -> int:
    if v is None:
        return default
    try:
        return int(v)
    except ValueError as exc:
        raise tools.ToolInputError(f"须为整数：{v!r}") from exc


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise tools.ToolInputError("请求体须为 JSON 对象") from exc
    if not isinstance(data, dict):
        raise tools.ToolInputError("请求体须为 JSON 对象")
    return data


def _only(data: dict, allowed: set[str], required: set[str]) -> None:
    extra, missing = set(data) - allowed, required - set(data)
    if extra:
        raise tools.ToolInputError(f"未知字段：{', '.join(sorted(extra))}")
    if missing:
        raise tools.ToolInputError(f"缺少字段：{', '.join(sorted(missing))}")


def register(mcp, lib: Callable[[], Any], info: Callable[[], dict]) -> None:
    """在 FastMCP 服务上注册 REST 路由。"""

    def route(path: str, methods: list[str]):
        def deco(fn):
            async def handler(request: Request):
                try:
                    return JSONResponse(await fn(request))
                except tools.ToolInputError as exc:
                    return _error(exc)
            handler.__name__ = fn.__name__
            return mcp.custom_route(path, methods=methods)(handler)
        return deco

    @route("/api/health", ["GET"])
    async def health(request: Request):
        return info()

    @route("/api/components", ["GET"])
    async def search(request: Request):
        q = request.query_params
        allowed = {"category", "vendor", "text", "params", "limit"}
        if set(q) - allowed:
            raise tools.ToolInputError(f"未知参数：{', '.join(sorted(set(q) - allowed))}")
        params = None
        if q.get("params"):
            try:
                params = json.loads(q["params"])
            except json.JSONDecodeError as exc:
                raise tools.ToolInputError("params 须为 JSON：{参数名: {min, max}}") from exc
        return tools.search_components(lib(), category=q.get("category"), vendor=q.get("vendor"),
                                       text=q.get("text"), params=params, limit=_int(q.get("limit"), 50))

    @route("/api/components/{component_id}", ["GET"])
    async def get(request: Request):
        return tools.get_component(lib(), request.path_params["component_id"])

    @route("/api/components/{component_id}/ports/{port_id}/compatible", ["GET"])
    async def compatible(request: Request):
        q = request.query_params
        allowed = {"category", "include_unknown", "via_adapters", "limit"}
        if set(q) - allowed:
            raise tools.ToolInputError(f"未知参数：{', '.join(sorted(set(q) - allowed))}")
        return tools.find_compatible(lib(), request.path_params["component_id"], request.path_params["port_id"],
                                     category=q.get("category"),
                                     include_unknown=_bool(q.get("include_unknown"), True),
                                     via_adapters=_bool(q.get("via_adapters"), True), limit=_int(q.get("limit"), 50))

    @route("/api/compose", ["POST"])
    async def compose(request: Request):
        data = await _body(request)
        _only(data, {"requirement", "top_n", "include_unknown", "lang"}, {"requirement"})
        return tools.compose_chain(lib(), data["requirement"], top_n=data.get("top_n", 5),
                                   include_unknown=data.get("include_unknown", False), lang=data.get("lang", "zh"))

    @route("/api/verify", ["POST"])
    async def verify(request: Request):
        data = await _body(request)
        _only(data, {"system", "lang"}, {"system"})
        return tools.verify_system(lib(), data["system"], lang=data.get("lang", "zh"))

    @route("/api/export", ["POST"])
    async def export(request: Request):
        data = await _body(request)
        _only(data, {"system", "format"}, {"system"})
        return tools.export_system(lib(), data["system"], format=data.get("format", "bom_csv"))
