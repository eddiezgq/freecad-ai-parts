"""第 160 轮：网页上维护工厂清单（第一期）——下载在用清单的 Excel、上传、校验、改动预览、存为待上线。"""
import io
import json
import os
import subprocess
import sys

import pytest

from factory import plant_diff as D

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")

ROUND = ("import sys, json; sys.path[:0] = [{dig!r}, {fac!r}]\nfrom hub import plant_admin as A\n"
         "r = A.check_upload(A.workbook_bytes())\nprint(json.dumps({{'ok': r['ok'], 'errors': r.get('errors'), 'total': r.get('diff', {{}}).get('total')}}))")


def _env(plant):
    env = dict(os.environ)
    if plant:
        env["WQ_PLANT_FILE"] = os.path.join(FAC, "plants", "wenquest-{}.yaml".format(plant))
    else:
        env.pop("WQ_PLANT_FILE", None)
    return env


@pytest.mark.parametrize("plant", [None, "robot", "sewing", "motor", "sensor", "pcb", "chip"])
def test_download_then_upload_is_unchanged(plant):
    """在用清单下载成 Excel 原样传回：校验通过、零改动（七座厂都行）"""
    r = subprocess.run([sys.executable, "-c", ROUND.format(dig=DIG, fac=FAC)], capture_output=True, text=True,
                       env=_env(plant), cwd=DIG, timeout=180)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out == {"ok": True, "errors": None, "total": 0}, out


EDIT = ("import sys, json, io; sys.path[:0] = [{dig!r}, {fac!r}]\nfrom hub import plant_admin as A\n"
        "from openpyxl import load_workbook\n"
        "wb = load_workbook(io.BytesIO(A.workbook_bytes()))\n{edit}\n"
        "buf = io.BytesIO(); wb.save(buf)\nr = A.check_upload(buf.getvalue())\n"
        "print(json.dumps({{'ok': r['ok'], 'errors': r.get('errors'), 'diff': r.get('diff')}}, ensure_ascii=False, default=str))")


def _edit(plant, edit):
    r = subprocess.run([sys.executable, "-c", EDIT.format(dig=DIG, fac=FAC, edit=edit)], capture_output=True, text=True,
                       env=_env(plant), cwd=DIG, timeout=180)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_edits_show_in_preview():
    """在 Excel 里改一个单价、一个用量、一个售价：预览逐条说出来"""
    edit = """
def row(ws, col, val):
    for r in ws.iter_rows(min_row=3):
        if r[col].value == val:
            return r
ws = wb['物料']; r = row(ws, 0, 'RM-45-D50'); r[4].value = 1.9
ws = wb['物料清单']; r = row(ws, 2, 'RM-20CR-D60'); r[3].value = 5.5
ws = wb['成品']; r = row(ws, 0, 'WQR-105'); r[1].value = 1700
"""
    out = _edit(None, edit)
    assert out["ok"], out["errors"]
    d = out["diff"]
    assert d["total"] == 3, d
    assert d["items"]["changed"]["rows"] == [{"key": "RM-45-D50", "fields": [{"field": "price", "old": 1.6, "new": 1.9}]}]
    assert d["boms"]["changed"]["rows"] == [{"key": "SH-101", "lines": [{"line": "RM-20CR-D60", "old": 5.2, "new": 5.5}]}]
    assert d["products"]["changed"]["rows"][0]["fields"] == [{"field": "price", "old": 1650, "new": 1700}]


def test_bad_reference_is_reported_by_sheet_and_row():
    """物料清单里写了不存在的子件：不存，错误说清是哪张表、第几行"""
    edit = """
ws = wb['物料清单']
for r in ws.iter_rows(min_row=3):
    if r[2].value == 'RM-20CR-D60':
        r[2].value = 'NO-SUCH-ITEM'
        break
"""
    out = _edit(None, edit)
    assert out["ok"] is False
    assert any(e.startswith("物料清单表第 ") and "NO-SUCH-ITEM" in e for e in out["errors"]), out["errors"]


def test_not_an_excel_file():
    r = subprocess.run([sys.executable, "-c", "import sys, json; sys.path[:0] = [{!r}, {!r}]\nfrom hub import plant_admin as A\n"
                        "print(json.dumps(A.check_upload(b'hello'), ensure_ascii=False))".format(DIG, FAC)],
                       capture_output=True, text=True, env=_env(None), cwd=DIG, timeout=60)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["ok"] is False and "打不开这个 Excel" in out["errors"][0]


def test_diff_pure():
    old = {"items": [{"code": "A", "name": "a", "price": 1}, {"code": "B", "name": "b"}],
           "routings": [{"name": "R", "steps": [["车", 3], ["铣", 4]]}],
           "boms": [{"item": "P", "routing": "R", "components": [["A", 1], ["B", 2]]}],
           "products": [{"item": "P", "price": 10}]}
    new = {"items": [{"code": "A", "name": "a", "price": 2}, {"code": "C", "name": "c"}],
           "routings": [{"name": "R", "steps": [["铣", 4], ["车", 3]]}],
           "boms": [{"item": "P", "routing": "R2", "components": [["A", 1], ["C", 1]]}],
           "products": [{"item": "P", "price": 10}, {"item": "Q"}]}
    d = D.diff(old, new)
    assert d["items"]["added"]["rows"] == ["C"] and d["items"]["removed"]["rows"] == ["B"]
    assert d["items"]["changed"]["rows"][0]["fields"] == [{"field": "price", "old": 1, "new": 2}]
    lines = d["boms"]["changed"]["rows"][0]["lines"]
    assert {"line": "C", "old": None, "new": 1} in lines and {"line": "B", "old": 2, "new": None} in lines
    assert {"line": "（routing）", "old": "R", "new": "R2"} in lines
    assert d["routings"]["changed"]["rows"][0]["lines"][0]["line"] == "（工序顺序）"      # 只换了顺序也算改动
    assert d["products"]["added"]["rows"] == ["Q"]
    assert d["total"] == 6
    assert D.diff(old, old)["total"] == 0


def test_cap_long_lists():
    old = {"items": []}
    new = {"items": [{"code": "X{}".format(i)} for i in range(D.LIMIT + 7)]}
    a = D.diff(old, new)["items"]["added"]
    assert len(a["rows"]) == D.LIMIT and a["more"] == 7


# ---------------------------------------------------------------- 数据库：存为待上线
@pytest.fixture(scope="module")
def db():
    pytest.importorskip("psycopg")
    import psycopg
    from hub.db import DB
    base = DSN.rsplit("/", 1)[0]
    try:
        with psycopg.connect(base + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_plant_admin_test with (force)")
            c.execute("create database wq_plant_admin_test")
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    d = DB(base + "/wq_plant_admin_test")
    d.init()
    yield d


def test_pending_saved_and_listed(db):
    import yaml
    from hub import plant_admin as A
    r = A.check_upload(A.workbook_bytes())
    row = A.save_pending(db, r["plant"], r["diff"], "工艺员甲", "清单.xlsx")
    rows = A.pending(db)
    assert rows[0]["id"] == row["id"] and rows[0]["uploaded_by"] == "工艺员甲" and rows[0]["summary"]["total"] == 0
    body = A.pending_body(db, row["id"])
    assert yaml.safe_load(io.StringIO(body))["company"] == r["plant"]["company"]
    assert A.pending_body(db, row["id"] + 999) is None
