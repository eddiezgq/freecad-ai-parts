# -*- coding: utf-8 -*-
"""第 159 轮 159d2b：安全距离检查（checks/safety.py）——用手搭的板子模型，距离手算"""

from shapely.geometry import box

from wqeda.checks import safety
from wqeda.checks.basic import FAIL, PASS, UNKNOWN
from wqeda.model import Board, Feature

RULES = {
    "groups": {"hv": ["VBUS"], "iso": ["GND_ISO"], "low": "rest"},
    "rules": [
        {
            "key": "iso",
            "name": "隔离",
            "a": ["iso"],
            "b": ["hv", "low"],
            "clearance_mm": 3.0,
            "creepage_mm": 4.0,
            "example": True,
        },
        {"key": "bus", "name": "母线", "a": ["hv"], "b": ["low"], "clearance_mm": 2.0, "creepage_mm": 2.0},
    ],
}


def board(gap_iso, gap_bus):
    b = Board("kicad", (0, 0, 100, 100), 2, has_nets=True)
    b.features = [
        Feature("F", box(0, 0, 10, 10), "track", "VBUS"),
        Feature("F", box(10 + gap_bus, 0, 20 + gap_bus, 10), "pad", "GND", "R1", "1"),
        Feature("F", box(20 + gap_bus + gap_iso, 0, 30 + gap_bus + gap_iso, 10), "zone", "GND_ISO"),
        # 同一器件自己的两个焊盘贴得很近：不算
        Feature("F", box(0, 20, 1, 21), "pad", "VBUS", "U1", "1"),
        Feature("F", box(1.2, 20, 2, 21), "pad", "GND", "U1", "2"),
    ]
    return b


def test_distances_and_limits_by_hand():
    r = {x["key"]: x for x in safety.run(board(4.5, 2.5), RULES)}
    assert r["S-iso"]["status"] == PASS and r["S-iso"]["value"] == 4.5 and r["S-iso"]["limit"] == 4.0
    assert r["S-bus"]["status"] == PASS and r["S-bus"]["value"] == 2.5  # U1 自己的焊盘间距 0.2 mm 不算
    assert r["S-iso"]["example"] is True
    r = {x["key"]: x for x in safety.run(board(3.5, 1.5), RULES)}
    assert r["S-iso"]["status"] == FAIL and r["S-bus"]["status"] == FAIL


def test_no_nets_is_unknown():
    b = board(5, 5)
    b.has_nets = False
    assert safety.run(b, RULES)[0]["status"] == UNKNOWN


def test_bridge_component_courtyard_is_exempt():
    """隔离电源 2、3 脚之间（器件自己的外框里）不算；外框以外照算"""
    b = Board("kicad", (0, 0, 100, 100), 2, has_nets=True)
    b.features = [
        Feature("F", box(0, 0, 1, 1), "pth", "GND", "U2", "2"),
        Feature("F", box(2, 0, 3, 1), "pth", "GND_ISO", "U2", "3"),
        Feature("F", box(2.2, 0.2, 6, 0.6), "track", "GND_ISO"),  # 从 3 脚引出的线，离 2 脚 1.2 mm，但在外框里
        Feature("F", box(0, 10, 1, 11), "track", "GND"),
        Feature("F", box(3, 10, 4, 11), "track", "GND_ISO"),  # 外框外 2 mm：不够 4 mm
    ]
    b.courtyards = {"U2": ("F", box(-0.5, -1, 3.5, 2))}
    r = {x["key"]: x for x in safety.run(b, RULES)}
    assert r["S-iso"]["status"] == FAIL and r["S-iso"]["value"] == 2.0
    b.features = b.features[:3]
    assert {x["key"]: x for x in safety.run(b, RULES)}["S-iso"]["status"] == PASS
