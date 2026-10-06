# -*- coding: utf-8 -*-
"""零件库文件（第 2 轮 L14、约定 R6）：https://factory.<域名>/library/… 由枢纽提供。

文件在服务器 /opt/wenquest/factory/library（只读挂到容器 WQ_LIBRARY_DIR），由发布工作流 library.yml 解包进去：
    library/latest.json                 不缓存（指向当前版本）
    library/<版本>/…                    带版本号，内容不变，长期缓存
跨域：GET、HEAD，来源为 WQ_LIBRARY_ORIGINS（逗号分隔）和本机开发地址（http://localhost:*、http://127.0.0.1:*）。
"""
import os
import re

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response

LOCAL = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")
TYPES = {".glb": "model/gltf-binary", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
         ".csv": "text/csv; charset=utf-8", ".zip": "application/zip", ".step": "model/step", ".stl": "model/stl"}


def _dir():
    return os.environ.get("WQ_LIBRARY_DIR", "/library")


def _origins():
    return {o.strip().rstrip("/") for o in os.environ.get("WQ_LIBRARY_ORIGINS", "").split(",") if o.strip()}


def _cors(request, headers):
    origin = request.headers.get("origin")
    if origin and (origin in _origins() or LOCAL.match(origin)):
        headers.update({"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                        "Access-Control-Allow-Methods": "GET, HEAD", "Access-Control-Max-Age": "86400"})
    return headers


def resolve(path):
    """library/ 下的相对路径 → 磁盘文件；越界、隐藏文件、不存在都返回 None"""
    root = os.path.realpath(_dir())
    if not path or any(p.startswith(".") for p in path.split("/")):
        return None
    f = os.path.realpath(os.path.join(root, path))
    if not f.startswith(root + os.sep) or not os.path.isfile(f):
        return None
    return f


def mount(app):
    @app.options("/library/{path:path}", include_in_schema=False)
    def library_preflight(path: str, request: Request):
        return Response(status_code=204, headers=_cors(request, {}))

    @app.api_route("/library/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def library_file(path: str, request: Request):
        f = resolve(path)
        if not f:
            raise HTTPException(404, "零件库里没有这个文件" if os.path.isdir(_dir()) else "零件库还没有发布")
        cache = "no-cache" if path.endswith("latest.json") else "public, max-age=31536000, immutable"
        ext = os.path.splitext(f)[1].lower()
        return FileResponse(f, media_type=TYPES.get(ext), headers=_cors(request, {"Cache-Control": cache}))
