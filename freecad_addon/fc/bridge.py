"""FreeCAD 界面桥接（ADR-0036）：在用户打开的 FreeCAD 中监听本机端口，供 FAP_FREECAD=gui 的 MCP 服务端连接。

协议同 worker（JSON 行，回复加前缀，ADR-0033），每个请求须带令牌 token。端口与令牌写入桥接文件
（缺省 ~/.freecad-ai-parts/bridge.json，可由 FAP_BRIDGE_FILE 指定，仅本人可读写），停止时删除。
请求在主线程执行（MainThreadExecutor）。须在 FreeCAD 主线程中启动。
"""

from __future__ import annotations

import json
import os
import secrets
import socketserver
import threading
from pathlib import Path

from freecad_addon.fc.client import PREFIX, bridge_file
from freecad_addon.fc.mainthread import MainThreadExecutor, MainThreadTimeout


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        from freecad_addon.fc.worker import handle as dispatch

        bridge: Bridge = self.server.bridge  # type: ignore[attr-defined]
        while True:
            raw = self.rfile.readline(MAX_LINE + 1)
            if not raw:
                return
            if len(raw) > MAX_LINE:
                self._reply({"id": None, "error": {"kind": "input", "message": f"请求超过 {MAX_LINE} 字节，连接关闭"}})
                return
            try:
                line = raw.decode("utf-8").strip()
                req = json.loads(line) if line else None
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._reply({"id": None, "error": {"kind": "input", "message": f"请求不是合法的 UTF-8 JSON：{exc}"}})
                continue
            if req is None:
                continue
            if not isinstance(req, dict) or not _token_ok(req.get("token"), bridge.token):
                resp = {"id": req.get("id") if isinstance(req, dict) else None,
                        "error": {"kind": "auth", "message": "令牌不正确"}}
            else:
                try:
                    resp = bridge.executor.run(dispatch, req, timeout_s=bridge.timeout_s)
                except MainThreadTimeout as exc:
                    resp = {"id": req.get("id"), "error": {"kind": "timeout", "message": str(exc)}}
            self._reply(resp)

    def _reply(self, resp: dict) -> None:
        self.wfile.write((PREFIX + json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()


MAX_LINE = 16 * 1024 * 1024  # 单个请求的上限（场景 JSON 远小于此）


def _token_ok(given, expected: str) -> bool:
    """按字节比较令牌（compare_digest 对非 ASCII 字符串会抛出异常）。"""
    if not isinstance(given, str):
        return False
    return secrets.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class Bridge:
    def __init__(self, path: Path | None = None, timeout_s: float = 180.0):
        self.path = Path(path) if path else bridge_file()
        self.timeout_s = timeout_s
        self.token = secrets.token_hex(16)
        self.executor = MainThreadExecutor()
        self._server: _Server | None = None

    @property
    def port(self) -> int | None:
        return self._server.server_address[1] if self._server else None

    def start(self) -> int:
        if self._server is not None:
            return self.port  # type: ignore[return-value]
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.bridge = self  # type: ignore[attr-defined]
        threading.Thread(target=self._server.serve_forever, name="fap-bridge", daemon=True).start()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"host": "127.0.0.1", "port": self.port, "token": self.token, "pid": os.getpid()}, f)
        os.replace(tmp, self.path)
        return self.port  # type: ignore[return-value]

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("token") == self.token:
                self.path.unlink()
        except (OSError, ValueError):
            pass
