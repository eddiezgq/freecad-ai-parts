# -*- coding: utf-8 -*-
"""第 159 轮 159d1、159d2b：平缝机控制器 CTRL-LS 原理图与板子产物（tools/ctrl_ls_build.py 生成；CI 重新生成后核对一字不差）。"""
import csv
import json
import os

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(os.path.dirname(HERE), "ctrl-ls")


def test_netlist_matches_design():
    """KiCad 从原理图导出的网表与设计描述逐网络、逐引脚一致（KiCad 7 命令行没有电气规则检查，用它代替）"""
    with open(os.path.join(P, "out", "netcheck.json"), encoding="utf-8") as f:
        nc = json.load(f)
    assert nc["pass"] and nc["problems"] == [] and nc["missing_parts"] == [] and nc["extra_parts"] == []
    assert nc["nets_design"] == nc["nets_schematic"] and nc["parts_design"] == nc["parts_schematic"]


def test_every_sheet_rendered():
    with open(os.path.join(P, "out", "design.json"), encoding="utf-8") as f:
        d = json.load(f)
    assert len(d["sheets"]) == 8 and all(s["svg"] for s in d["sheets"])
    for s in d["sheets"]:
        assert os.path.exists(os.path.join(P, "out", "schematic", s["svg"]))
    assert d["disclaimer"].startswith("示例设计")


def test_bom_carries_catalog_parts():
    """器件表里每个外购件（有立创编号的）都进了物料清单，型号、立创编号对得上"""
    with open(os.path.join(P, "parts.yaml"), encoding="utf-8") as f:
        cat = yaml.safe_load(f)["parts"]
    with open(os.path.join(P, "out", "bom.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_item = {r["物料编号"]: r for r in rows}
    for q in cat:
        assert q["item"] in by_item, q["item"]
        if q.get("lcsc"):
            assert by_item[q["item"]]["立创编号"] == q["lcsc"] and by_item[q["item"]]["型号"] == q["mpn"]


def test_board_routed_and_checked():
    """159d2b：板子全部布通、KiCad 设计规则检查 0 错误；安全距离四条规则都过，规则是示例值且如实标出"""
    with open(os.path.join(P, "out", "drc.json"), encoding="utf-8") as f:
        dr = json.load(f)
    assert dr["errors"] == 0 and dr["unconnected"] == 0
    with open(os.path.join(P, "out", "safety.json"), encoding="utf-8") as f:
        res = json.load(f)
    assert {r["key"] for r in res} == {"S-iso", "S-pe", "S-ln", "S-bus"}
    for r in res:
        assert r["status"] == "pass" and r["value"] >= r["limit"] and r["example"] is True, r["key"]
    with open(os.path.join(P, "out", "design.json"), encoding="utf-8") as f:
        d = json.load(f)
    assert len(d["pcb_layers"]) == 6
    for k in ("gerber.zip", "pos.csv", "kicad-project.zip"):
        assert os.path.exists(os.path.join(P, "out", k)), k


def test_report_trace_width_and_board_thermal():
    """159d2c：统一报告里没有“不通过”；大电流线宽 21 条都过；板上按计算书损耗算的发热件板温都在允许温度以内"""
    with open(os.path.join(P, "report", "report.json"), encoding="utf-8") as f:
        rep = json.load(f)
    assert rep["count"]["fail"] == 0
    c1 = next(r for r in rep["process"] if r["key"] == "C1")
    assert c1["status"] == "pass" and c1["value"] == c1["limit"] == 21
    th = rep["thermal"]
    assert th["status"] == "pass"
    rows = {r["ref"]: r for r in th["rows"]}
    assert {"R203", "R303", "R310", "R411", "R412", "R413", "Q501"} <= set(rows)
    for r in rows.values():
        assert r["model"] == "calc" and r["status"] == "pass" and r["t_board_c"] <= r["t_limit_c"], r["ref"]
