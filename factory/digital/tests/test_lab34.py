# -*- coding: utf-8 -*-
"""第 145 轮：缝纫机厂实验 34（照实验 24）——任务 1 的标准答案按物料清单算出（8 张工单、5 种关键零件），答对答错的得分；
任务 6 选项；任务 2 按层核对（用实验 24 的函数，按 WQ-LS 的物料清单）；指导书和报告模板能生成；示例能力正常 Cpk ≥ 1.6。"""
import json
import os
import subprocess
import sys

import pytest
import yaml

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
SEW = os.path.join(FAC, "plants", "wenquest-sewing.yaml")
BASE = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0]

CODE = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import psycopg
BASE = {base!r}
with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
    c.execute("drop database if exists wq_lab34_test with (force)")
    c.execute("create database wq_lab34_test")
from hub.db import DB
from hub import lab24, lab34
db = DB(BASE + "/wq_lab34_test")
db.init()
out = {{"exp": lab34.expected_counts()}}
out["t1_right"] = lab34.answer(db, "甲", "l34_t1", {{"work_orders": 8, "key_parts": 5}})["score"]
out["t1_half"] = lab34.answer(db, "乙", "l34_t1", {{"work_orders": 8, "key_parts": 6}})["score"]
out["t1_bad"] = lab34.answer(db, "丙", "l34_t1", {{"work_orders": "x", "key_parts": None}})["score"]
out["t6_right"] = lab34.answer(db, "甲", "l34_t6", {{"choices": ["foundry", "age2", "cmm", "runin"]}})["score"]
out["t6_part"] = lab34.answer(db, "乙", "l34_t6", {{"choices": ["foundry"]}})["score"]
out["t6_wrong"] = lab34.answer(db, "丙", "l34_t6", {{"choices": ["foundry", "calib"]}})["score"]
out["t3_no_order"] = lab34.answer(db, "甲", "l34_t3", {{"serial": "x", "verdict": "pass"}})["score"]
# 按层核对：造一张假订单，机壳在铸件完工前就下达了
wos = {{"WQ-LS": "W8", "HSG-LS": "W1", "CAST-LS": "W2", "LS-101": "W3"}}
ts = {{"W2": ("2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z"), "W1": ("2026-01-02T00:00:00Z", "2026-01-05T00:00:00Z"),
      "W3": ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"), "W8": ("2026-01-06T00:00:00Z", None)}}
lab24._release_ts = lambda db, wo: ts[wo][0]
lab24._done_ts = lambda db, wo: ts[wo][1]
rows, bad = lab24.layers(db, {{"work_orders": wos}})
out["bad"] = bad
st = lab34.status(db, "甲")
out["score"] = st["score"]
out["std"] = st["std"]
print(json.dumps(out, ensure_ascii=False, default=str))
"""


def test_lab34_answers_and_layers():
    psycopg = pytest.importorskip("psycopg")
    try:
        psycopg.connect(BASE + "/postgres").close()
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    env = dict(os.environ, WQ_PLANT_FILE=SEW)
    r = subprocess.run([sys.executable, "-c", CODE.format(dig=DIG, fac=FAC, base=BASE)], capture_output=True, text=True, env=env, cwd=DIG,
                       timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    assert out["exp"] == {"work_orders": 8, "key_parts": 5}, out
    assert (out["t1_right"], out["t1_half"], out["t1_bad"]) == (10, 5, 0), out
    assert (out["t6_right"], out["t6_part"], out["t6_wrong"]) == (5, 2, 0), out
    assert out["t3_no_order"] == 0
    assert out["bad"] == ["HSG-LS"], out                      # 机壳在铸件完工前下达；整机等到了机壳和上轴
    assert out["score"] == 15 and out["std"]["total"] > out["std"]["material"] > 0, out


def test_example_capability():
    """第 141、145 轮：缝纫机厂测量特性（不含计数型）正常生产时 Cpk ≥ 1.6，学生 8D 验证不碰运气"""
    p = yaml.safe_load(open(SEW, encoding="utf-8"))
    low = []
    for m in p["measurements"]:
        for c in m["chars"]:
            if not c.get("sigma"):
                continue
            cpk = min(c["hi"] - c["nominal"], c["nominal"] - c["lo"]) / (3 * c["sigma"])
            if c["lo"] == 0 and c["nominal"] > 0 and c["nominal"] - c["lo"] < c["hi"] - c["nominal"]:
                cpk = (c["hi"] - c["nominal"]) / (3 * c["sigma"])        # 形位公差、温升、噪声等只有上限
            if cpk < 1.6:
                low.append((m["item"], c["code"], round(cpk, 2)))
    assert not low, low


def test_lab34_docs():
    sys.path[:0] = [DIG, FAC]
    from cae import labdoc
    assert len(labdoc.guide_docx("lab34")) > 10000 and len(labdoc.report_template_docx("lab34")) > 10000
