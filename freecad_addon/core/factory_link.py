"""发布到工厂（ADR-0058 第 4 条，M10 第 6c 项）：把当前方案（BOM、需求、校验结论、布局概要、STEP）发到本地工厂枢纽。

- payload()：由当前布局与零件库组成发布内容（纯函数）；BOM 与 BOM 窗口同一份（core/bom_view）
- HubClient：登录、上传附件、发布；只连企业自己指定的工厂地址（缺省本机 http://localhost:8100），不连外网
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path

from freecad_addon.core import bom_view

DEFAULT_URL = "http://localhost:8100"


class FactoryError(RuntimeError):
    """发布失败；消息说明原因。"""


def payload(layout: Mapping, lookup: Callable[[str], dict | None], *, code: str, name: str,
            origin: Callable[[str], str | None] | None = None, requirement: Mapping | None = None,
            checks: Mapping | None = None, note: str = "", files: list[dict] | None = None,
            made_parts: list[dict] | None = None, assembly_routing: list | None = None) -> dict:
    """made_parts：自制件（定制件）清单 [{code, name, qty, material, raw: {item_code, …}, raw_qty, routing: [[工序, 分钟]],
    datum?, clamping?}]（datum、clamping：第一道机加工工序的粗基准与装夹，可选，ADR-0062）；
    assembly_routing：总装工艺 [[工序, 分钟]]。两者是工厂“转为生产物料”要用的（ADR-0061），工序须是工厂现有的。"""
    b = bom_view.bom(layout, lookup)
    if not b["rows"]:
        raise FactoryError("场景里没有零件，先放入方案")
    rows = []
    for r in b["rows"]:
        row = {k: r[k] for k in ("component_id", "category", "vendor", "model", "quantity", "instances", "unit_mass_kg",
                                  "source_docs", "all_params_reviewed")}
        row["library"] = (origin(r["component_id"]) if origin else None) or "public"
        rows.append(row)
    out = {"code": code.strip(), "name": name.strip(), "bom": rows, "note": note.strip(), "tool": "FreeCAD AI Parts",
           "layout": {"instances": len(layout.get("instances", [])), "connections": len(layout.get("connections", []))},
           "files": list(files or [])}
    if made_parts:
        out["made_parts"] = [dict(m) for m in made_parts]
    if assembly_routing:
        out["assembly_routing"] = [list(r) for r in assembly_routing]
    if requirement:
        out["requirement"] = dict(requirement)
    if checks:
        out["checks"] = {"overall": checks.get("overall"),
                         "items": [{"check": c.get("check"), "status": c.get("status")} for c in checks.get("checks", [])]}
    if b["custom_requirements"]:
        out["note"] = (out["note"] + "\n\n" if out["note"] else "") + bom_view.custom_text(b)
    return out


class HubClient:
    def __init__(self, url: str = DEFAULT_URL, timeout: float = 30, cafile: str | None = None):
        """cafile：企业内网用自签证书时，工厂的根证书（也可用环境变量 FAP_FACTORY_CAFILE）；公网证书不用给。"""
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.token = ""
        self.cafile = cafile or os.environ.get("FAP_FACTORY_CAFILE") or None
        self._auth = None

    def _req(self, path: str, data: bytes | None = None, headers: dict | None = None) -> dict:
        h = dict(headers or {})
        if self.token:
            h["x-wq-token"] = self.token
        req = urllib.request.Request(self.url + path, data=data, headers=h, method="POST" if data is not None else "GET")
        try:
            ctx = ssl.create_default_context(cafile=self.cafile) if self.cafile and self.url.startswith("https") else None
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as r:  # 企业自己指定的工厂地址
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("detail")
            except Exception:  # noqa: BLE001
                detail = None
            raise FactoryError(f"工厂返回 {exc.code}：{detail or exc.reason}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise FactoryError(f"连不上工厂 {self.url}（本地工厂启动了吗？factory/local/start）：{exc}") from exc

    def auth(self) -> str:
        """工厂的登录方式：local（填名字）、wenquest（问渠账号）、enterprise（企业账号，ADR-0063）。"""
        if self._auth is None:
            try:
                self._auth = self._req("/api/login/info").get("auth", "local")
            except FactoryError as exc:
                if "连不上" in str(exc):
                    raise
                self._auth = "local"                       # 旧版工厂没有这个接口
        return self._auth

    def login(self, name: str, mode: str = "teach", password: str | None = None) -> str:
        if self.auth() == "enterprise":
            if not password:
                raise FactoryError("这座工厂用企业账号登录：请填用户名和密码")
            body = json.dumps({"username": name, "password": password, "role": "engineer", "mode": "prod"}).encode()
            self.token = self._req("/api/login", body, {"Content-Type": "application/json"})["token"]
            return self.token
        body = json.dumps({"name": name, "role": "engineer", "mode": mode}).encode()
        self.token = self._req("/api/login", body, {"Content-Type": "application/json"})["token"]
        return self.token

    def upload(self, path: str | Path, kind: str = "step") -> dict:
        p = Path(path)
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{p.name}"\r\n'
                f"Content-Type: application/step\r\n\r\n").encode() + p.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        r = self._req("/api/files", body, {"Content-Type": "multipart/form-data; boundary=" + boundary})
        return {"kind": kind, "name": p.name, "url": r["url"], "sha256": r["sha256"], "size": r["size"]}

    def release(self, data: Mapping) -> dict:
        return self._req("/api/cad/release", json.dumps(data, ensure_ascii=False).encode("utf-8"),
                         {"Content-Type": "application/json"})


def publish(client: HubClient, author: str, mode: str, data: dict, step_path: str | Path | None = None,
            password: str | None = None) -> dict:
    """登录 → 上传 STEP（有的话）→ 发布。返回 {code, revision, name}。企业版工厂：author 是用户名，要给 password。"""
    if not author.strip():
        raise FactoryError("请写发布人")
    client.login(author.strip(), mode, password)
    if step_path:
        data = {**data, "files": [*data.get("files", []), client.upload(step_path)]}
    return client.release(data)
