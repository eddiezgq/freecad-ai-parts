"""典型应用演练的公共部分（ADR-0061，M13 第二步）：步骤记录、零件几何、选型、布局、发布到工厂。

FreeCAD 一侧不开界面也能跑：直接调零件库、引擎（选型与校验——凡“能不能用”的判断都由 engine 做）和分析模块；
布局与干涉检查要 FreeCAD（FAP_FREECAD=headless），没有时这一步记“跳过”。
"""

from __future__ import annotations

import json
import math
import os
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
STATUS_TEXT = {"ok": "完成", "unknown": "待确认", "skip": "跳过", "fail": "失败", "na": "不适用"}


def library():
    from kb.library import JsonLibrary

    return JsonLibrary(ROOT / "data" / "library")


_RANK = {"ok": 0, "unknown": 1, "fail": 2}
_MAP = {"pass": "ok", "ok": "ok", "not_applicable": "ok", "na": "ok", "warn": "unknown", "unknown": "unknown", "fail": "fail",
        "severe": "fail"}
_TEXT_UNKNOWN = ("待确认", "unknown", "不通过")


def content_status(summary: str, data) -> str:
    """一步的内容里最差的判定：数据里各处 overall / verdict / status 字段（pass、warn、unknown、fail），和摘要里的“待确认、unknown、
    不通过”字样（按待确认计，不直接判失败——摘要可能是在说原来的状态）"""
    worst = "ok"

    def take(v):
        nonlocal worst
        m = _MAP.get(v) if isinstance(v, str) else None
        if m and _RANK[m] > _RANK[worst]:
            worst = m

    def walk(x, depth=0):
        if depth > 6:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("overall", "verdict") or (k == "status" and isinstance(v, str)):
                    take(v)
                elif k not in ("trace",):
                    walk(v, depth + 1)
        elif isinstance(x, list | tuple):
            for v in x[:200]:
                walk(v, depth + 1)

    walk(data)
    if worst == "ok" and any(w in (summary or "") for w in _TEXT_UNKNOWN):
        worst = "unknown"
    return worst


class Run:
    """一个应用的演练记录：每一步的结论、摘要与关键数据，最后写 report.json 与 README.md。"""

    def __init__(self, key: str, title: str, sources: list[dict], assumptions: list[str]):
        self.key, self.title, self.sources, self.assumptions = key, title, sources, assumptions
        self.steps: list[dict] = []
        self.out = OUT / key
        self.out.mkdir(parents=True, exist_ok=True)
        self.t0 = time.time()

    def add(self, step: str, status: str, summary: str, *, completed: bool = True, mentions_ok: bool = False, **data):
        """status 取本步全部判据的最差值（《多体动力学》书第 36 章线索第 56 条：原来 89 步里 13 步写“完成”而内容是“待确认 / unknown”）：
        给的是 ok 而数据里有 unknown / warn / fail 的判定、或摘要写了待确认，就降下来；“跑完了没有”另记 completed。
        mentions_ok：摘要里的“待确认”只是在解释别处的规定（不是本步的结论），只看数据里的判定"""
        worst = content_status("" if mentions_ok else summary, data)
        if status == "ok" and worst != "ok":
            status = worst
        self.steps.append({"step": step, "status": status, "completed": completed, "summary": summary,
                           **({"data": data} if data else {})})
        print(f"[{self.key}] {step}：{STATUS_TEXT.get(status, status)}——{summary}", flush=True)

    def guard(self, step: str, fn, *a, **kw):
        """跑一步；出错记“失败”与原因，不中断后面的步骤。"""
        try:
            return fn(*a, **kw)
        except Exception as exc:  # noqa: BLE001
            self.add(step, "fail", f"{type(exc).__name__}：{exc}", completed=False, trace=traceback.format_exc()[-1500:])
            return None

    def save(self, extra: dict | None = None) -> dict:
        rep = {"app": self.key, "title": self.title, "sources": self.sources, "assumptions": self.assumptions,
               "steps": self.steps, "elapsed_s": round(time.time() - self.t0, 1), **(extra or {})}
        (self.out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        lines = [f"# {self.title}", "", "## 依据", ""]
        lines += [f"- [{s['title']}]({s['url']})" + (f"：{s['note']}" if s.get("note") else "") for s in self.sources]
        lines += ["", "## 假设（不是零件库数据，按需改）", ""] + [f"- {a}" for a in self.assumptions]
        lines += ["", "## 各步结果", "", "| 步骤 | 结论 | 摘要 |", "| --- | --- | --- |"]
        lines += [f"| {s['step']} | {STATUS_TEXT.get(s['status'], s['status'])} | {s['summary'].replace('|', '／')} |"
                  for s in self.steps]
        (self.out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return rep


# ---------------------------------------------------------------- 几何（gmsh，与有限元共用会话）
def _occ(name: str, path: Path, build) -> str:
    from analysis.fea.geometry import _LOCK, _gmsh

    with _LOCK:
        gmsh = _gmsh()
        gmsh.clear()
        gmsh.model.add(name)
        build(gmsh.model.occ)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
        gmsh.clear()
    return str(path)


def shaft_step(path: Path, segments: list[tuple[float, float]], bore: float | None = None) -> str:
    """阶梯轴（沿 z，左端在 z = 0）：segments = [(直径, 长度)]；bore：贯通内孔直径。"""

    def build(occ):
        z, vols = 0.0, []
        for d, length in segments:
            vols.append((3, occ.addCylinder(0, 0, z, 0, 0, length, d / 2)))
            z += length
        shaft = occ.fuse([vols[0]], vols[1:])[0] if len(vols) > 1 else vols
        if bore:
            occ.cut(shaft, [(3, occ.addCylinder(0, 0, -1, 0, 0, z + 2, bore / 2))])

    return _occ("shaft", path, build)


def housing_step(path: Path, size: tuple[float, float, float], bore_d: float) -> str:
    """关节壳体（简化）：长方体，中心沿 z 一个贯通的减速器安装孔；底面 z = 0 为安装面。"""
    a, b, h = size

    def build(occ):
        box = occ.addBox(-a / 2, -b / 2, 0, a, b, h)
        occ.cut([(3, box)], [(3, occ.addCylinder(0, 0, -1, 0, 0, h + 2, bore_d / 2))])

    return _occ("housing", path, build)


def heatsink_step(path: Path, base: tuple[float, float, float], fins: int, fin_h: float, fin_t: float) -> str:
    """平板翅片散热器：底板 a×b×t（z 向上），沿 x 方向的直翅。"""
    a, b, t = base

    def build(occ):
        parts = [(3, occ.addBox(0, 0, 0, a, b, t))]
        pitch = b / fins
        for k in range(fins):
            parts.append((3, occ.addBox(0, k * pitch + (pitch - fin_t) / 2, t, a, fin_t, fin_h)))
        occ.fuse(parts[:1], parts[1:])

    return _occ("heatsink", path, build)


def faces(step: str) -> list[dict]:
    import analysis

    return analysis.run("fea", {"analysis": "faces", "step_path": step})["data"]["faces"]


def face_ids(fs: list[dict], pred) -> list[int]:
    return [f["id"] for f in fs if pred(f)]


def plane_at(axis: int, value: float, tol: float = 1e-3):
    return lambda f: f["kind"] == "plane" and abs(f["center"][axis] - value) < tol


def cyl_d(d: float, z0: float | None = None, z1: float | None = None, tol: float = 0.05):
    """直径为 d 的圆柱面（按包围盒的半径判断），可限定 z 范围。"""

    def ok(f):
        if f["kind"] != "cylinder":
            return False
        bb = f["bbox"]
        r = max(bb[3] - bb[0], bb[4] - bb[1]) / 2
        zc = f["center"][2]
        return abs(r - d / 2) < tol and (z0 is None or zc >= z0) and (z1 is None or zc <= z1)

    return ok


# ---------------------------------------------------------------- 选型与布局
def envelope(reqs: dict) -> dict:
    """几个工况的选型需求取包络（《多体动力学》书第 40 章线索第 5 条：协作臂原来只算“往下放”，“往上抬”峰值大 34 %）。
    reqs：{工况名: 需求}；扭矩、转速、惯量逐项取最大，statement 写明各工况的值"""
    keys = ("output_torque_cont_nm", "output_torque_peak_nm", "output_speed_rpm", "load_inertia_kgm2")
    first = next(iter(reqs.values()))
    out = {k: v for k, v in first.items() if k not in keys and k != "statement"}
    for k in keys:
        out[k] = max(r[k] for r in reqs.values())
    out["statement"] = "两个方向取包络：" + "；".join(
        f"{n} 连续 {r['output_torque_cont_nm']:.1f} / 峰值 {r['output_torque_peak_nm']:.1f} N·m" for n, r in reqs.items())
    return out


def compose(requirement: dict, top: int = 3) -> list:
    from engine.compose import compose_chain

    return compose_chain(requirement, list(library().all()), top_n=top, include_unknown=True)


def verify(system: dict) -> dict:
    from engine import validate

    return validate.validate(system, library().get)


def layout(requirement: dict, out_dir: Path) -> dict | None:
    """FreeCAD 布局、干涉检查、按布局复核、BOM、URDF、截图（mcp_server.e2e）；没有 FreeCAD 时返回 None。"""
    if (os.environ.get("FAP_FREECAD") or "none").lower() != "headless":
        return None
    from mcp_server import e2e

    os.environ.setdefault("FAP_LIBRARY", str(ROOT / "data" / "library"))  # 真实组件库（不给时 e2e 用虚构测试组件）
    code = e2e.run(requirement=requirement, out_dir=out_dir, include_unknown=True)
    sysj = json.loads((out_dir / "system.json").read_text(encoding="utf-8")) if (out_dir / "system.json").exists() else None
    return {"code": code, "system": sysj, "png": (out_dir / "layout-iso.png").exists()}


def mech_layout(system: dict) -> dict:
    """系统 → 发布用的布局（实例 + 机械连接；电机—驱动器的电气连接由 BOM 按惯例补）。"""
    conns = [c for c in system["connections"] if not (c["a"].startswith("drive.") or c["b"].startswith("drive."))]
    return {"instances": [{"instance": c["instance"], "component": c["component"]} for c in system["components"]],
            "connections": conns}


def checks_text(report: dict) -> str:
    bad = [f"{c['check']} {c['status']}：{c.get('message', '')[:40]}" for c in report["checks"]
           if c["status"] not in ("pass", "not_applicable")]
    return f"总体 {report['overall']}" + (f"（{'；'.join(bad)}）" if bad else "")


def publish(hub: str | None, *, code: str, name: str, system: dict, requirement: dict, report: dict, made_parts: list,
            assembly_routing: list, note: str = "", step_files: tuple = ()) -> dict | None:
    """发布到工厂（FreeCAD“发布到工厂”的同一段代码，ADR-0058）；没给工厂地址时返回 None。"""
    if not hub:
        return None
    from freecad_addon.core import factory_link

    lib = library()
    data = factory_link.payload(mech_layout(system), lib.get, code=code, name=name, requirement=requirement,
                                checks=report, note=note, made_parts=made_parts, assembly_routing=assembly_routing)
    client = factory_link.HubClient(hub)
    # 企业版工厂（ADR-0063）：用户名、密码从环境变量 FAP_FACTORY_USER、FAP_FACTORY_PASSWORD 读；自签证书给 FAP_FACTORY_CAFILE
    user = os.environ.get("FAP_FACTORY_USER") or "典型应用演练"
    out = factory_link.publish(client, user, "teach", data, step_files[0] if step_files else None,
                               password=os.environ.get("FAP_FACTORY_PASSWORD") or None)
    return out


def r3(x, n=3):
    return None if x is None else round(float(x), n)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else math.nan
