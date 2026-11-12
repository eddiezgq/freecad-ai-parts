# -*- coding: utf-8 -*-
"""设计案例（第 161 轮）：每座厂三个“任务书 → 方案 → 计算 → 仿真 → 三维与图纸 → 工艺 → 制造 → 总结”全过程案例。

案例资料在 factory/cases/<工厂>/<案例号>/（case.json + 每步的 md、图、模型、程序），由 tools/cases/<工厂>_<案例号>.py 生成，随镜像发布。
本模块只读：列出本厂的案例、给一个案例的 case.json、给文件。
"""
import json
import os

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "cases")
LEVELS = ("A", "B", "C")


def plant_key(plant_id):
    """清单编号 → 案例目录名：wenquest-gearbox → gearbox；企业工厂没有案例"""
    return plant_id[len("wenquest-"):] if plant_id.startswith("wenquest-") else plant_id


def _load(plant, cid):
    p = os.path.join(ROOT, plant, cid, "case.json")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def listing(plant):
    out = []
    for cid in LEVELS:
        c = _load(plant, cid)
        if c:
            out.append({k: c[k] for k in ("id", "level", "title", "title_en", "item", "summary", "summary_en", "all_ok", "generated")}
                       | {"n_checks": len(c["checks"]), "n_ok": sum(1 for x in c["checks"] if x["ok"])})
    return out


def case(plant, cid):
    if cid not in LEVELS:
        return None
    return _load(plant, cid)


def file_path(plant, cid, name):
    """案例里的文件；不在案例目录里（../ 之类）返回 None"""
    if cid not in LEVELS or "/" in plant or plant.startswith("."):
        return None
    base = os.path.realpath(os.path.join(ROOT, plant, cid))
    f = os.path.realpath(os.path.join(base, name))
    return f if f.startswith(base + os.sep) and os.path.isfile(f) and os.path.basename(f) != "case.json" else None


def mount(app, user_of, plant_id):
    from fastapi import Depends, HTTPException
    from fastapi.responses import FileResponse

    @app.get("/api/cases")
    def cases_list(u=Depends(user_of)):
        plant = plant_key(plant_id())
        return {"plant": plant, "cases": listing(plant)}

    @app.get("/api/cases/{cid}")
    def cases_one(cid: str, u=Depends(user_of)):
        c = case(plant_key(plant_id()), cid)
        if not c:
            raise HTTPException(404, "本厂没有这个案例")
        return c

    @app.get("/api/cases/{plant}/{cid}/f/{name}")
    def cases_file(plant: str, cid: str, name: str):
        f = file_path(plant, cid, name)
        if not f:
            raise HTTPException(404, "没有这个文件")
        media = {".md": "text/markdown; charset=utf-8", ".nc": "text/plain; charset=utf-8", ".svg": "image/svg+xml",
                 ".step": "application/step"}.get(os.path.splitext(f)[1].lower())
        return FileResponse(f, media_type=media, filename=os.path.basename(f) if media in ("application/step",) else None)
