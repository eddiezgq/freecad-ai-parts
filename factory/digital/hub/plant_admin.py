"""第 160 轮：网页上维护工厂清单（第一期）——下载在用清单的 Excel、上传改好的 Excel、校验、和在用清单比、存为待上线。
不改在用的清单，不碰 ERPNext（第二期“上线”另做）。"""
import json
import os
import tempfile

import yaml

from factory import plant as P
from factory import plant_diff as D
from factory import plant_xlsx as X

SCHEMA = """
create table if not exists plant_pending (
    id          serial primary key,
    plant_id    text not null,
    uploaded_by text,
    filename    text,
    body        text not null,
    summary     jsonb not null,
    created_at  timestamptz not null default now()
);
"""


def current_raw():
    """在用清单的原始 dict（yaml 的样子）：企业工厂读清单文件；演示工厂用代码里的清单"""
    a = P.active()
    if a and a.get("SOURCE") and os.path.exists(a["SOURCE"]):
        with open(a["SOURCE"], encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    return P.export_demo()


def workbook_bytes():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "plant.xlsx")
        X.write_template(path, current_raw())
        with open(path, "rb") as fh:
            return fh.read()


def check_upload(data: bytes):
    """上传的 Excel → {"ok": False, "errors": [...]} 或 {"ok": True, "plant": dict, "diff": {...}}"""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "upload.xlsx")
        with open(path, "wb") as fh:
            fh.write(data)
        try:
            new = X.import_workbook(path)
        except P.PlantError as e:
            return {"ok": False, "errors": list(e.errors)}
        except Exception as e:  # noqa: BLE001 —— 不是 Excel、表被删了等
            return {"ok": False, "errors": [f"读不了这个文件：{e}"]}
    return {"ok": True, "plant": new, "diff": D.diff(current_raw(), new)}


def save_pending(db, plant, diff, user, filename):
    db.x(SCHEMA)
    body = yaml.safe_dump(plant, allow_unicode=True, sort_keys=False)
    r = db.one("insert into plant_pending (plant_id, uploaded_by, filename, body, summary) values (%s,%s,%s,%s,%s) returning id, created_at",
               (P.plant_id(), user, filename, body, json.dumps(diff, ensure_ascii=False, default=str)))
    return r


def pending(db, limit=10):
    db.x(SCHEMA)
    return db.q("select id, uploaded_by, filename, created_at, summary from plant_pending where plant_id=%s order by id desc limit %s",
                (P.plant_id(), limit))


def pending_body(db, pid):
    db.x(SCHEMA)
    r = db.one("select body from plant_pending where id=%s and plant_id=%s", (pid, P.plant_id()))
    return r["body"] if r else None
