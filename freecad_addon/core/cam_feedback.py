"""问渠CAM 问题反馈包（ADR-0106 Q7a）：试用的人写几句话，生成一个 zip，自己发给我们（不自动上传）。

zip 里：description.txt（写的话、时间、界面语言）、environment.json（版本、FreeCAD、操作系统、授权档位名称）、当前文档副本（.FCStd）、
用户自己的刀具库 / 机床 / 后处理配置（tools、machines、posts 下的 .json）、FreeCAD 报告视图里的文字。
不收授权文件、密钥、其他文档。本模块不依赖界面，FreeCAD 里的部分（文档副本、报告视图）由调用方给。
"""

from __future__ import annotations

import json
import platform
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from analysis.cam import machines, postcfg, tools

MAX_LOG = 200_000          # 报告视图文字最多收这么多字（最后的部分）
_SECRET = re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*\S+")


class FeedbackError(ValueError):
    pass


def _user_configs(env=None) -> list[tuple[str, Path]]:
    from licensing import runtime

    lic = runtime.license_path(env).resolve()
    out = []
    for name, d in (("tools", tools.user_dir(env)), ("machines", machines.user_dir(env)), ("posts", postcfg.user_dir(env))):
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.json")):
            if p.resolve() == lic or "license" in p.name.lower():
                continue
            out.append((f"config/{name}/{p.relative_to(d).as_posix()}", p))
    return out


def build(out_dir, description: str, *, document=None, environment: dict | None = None, log: str = "", lang: str = "zh",
          env=None, now=None) -> Path:
    """生成反馈包，返回 zip 路径。document：当前文档副本（.FCStd）的路径，可没有；environment：版本等；log：报告视图文字"""
    if not description.strip():
        raise FeedbackError("请先写几句：做了什么、哪里不对")
    now = now or datetime.now(UTC)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    zp = out / f"wenquest-cam-feedback-{now.strftime('%Y%m%d-%H%M%S')}.zip"
    envinfo = {"time_utc": now.isoformat(timespec="seconds"), "language": lang, "os": platform.platform(),
               "python": platform.python_version(), **(environment or {})}
    with zipfile.ZipFile(zp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("description.txt", f"{description.strip()}\n\n-- {envinfo['time_utc']} ({lang})\n")
        z.writestr("environment.json", json.dumps(envinfo, ensure_ascii=False, indent=1))
        if document:
            p = Path(document)
            if not p.is_file():
                raise FeedbackError(f"文档副本没找到：{p}")
            z.write(p, "document/" + p.name)
        for arc, p in _user_configs(env):
            z.write(p, arc)
        if log:
            z.writestr("report-view.txt", _SECRET.sub(r"\1=***", log[-MAX_LOG:]))
    return zp


def contents(zp) -> list[str]:
    with zipfile.ZipFile(zp) as z:
        return z.namelist()
