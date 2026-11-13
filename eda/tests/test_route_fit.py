# -*- coding: utf-8 -*-
"""第 159 轮 159d2b：分类之间的布线间距（class_pairs）、布线时的细线宽（route_mm）、给布线器的 DSN 改写、
器件自己引脚比布线间距近时的引出线（route_fit）。要 KiCad（pcbnew）的用例在没有 KiCad 时跳过。"""

import copy
import os

import pytest
from conftest import DESIGNS

from wqeda.schema import design as D

CTRL = os.path.join(DESIGNS, "ctrl-ls", "design.yaml")
CTRL_PCB = os.path.join(DESIGNS, "ctrl-ls", "kicad", "ctrl-ls.kicad_pcb")

DSN = """(pcb x
  (network
    (net A (pins R1-1))
    (class kicad_default "" A B C D
      (circuit (use_via Via[0-3]_600:300_um))
      (rule (width 250) (clearance 200))
    )
    (class OLD C D
      (circuit (use_via Via[0-3]_600:300_um))
      (rule (width 2500) (clearance 2600))
    )
  )
)
"""


def test_class_pairs_expand_once_each():
    from wqeda.gen.board import pairs_of

    x = {"class_pairs": [{"a": ["P", "Q"], "b": ["Q", "R"], "clearance_mm": 2.0},
                         {"a": ["R"], "b": ["P"], "clearance_mm": 9.0}]}
    # P-Q、P-R、Q-R 各一次；Q-Q 不算；后面的 R-P 与前面的 P-R 是同一对，按先写的
    assert pairs_of(x) == [("P", "Q", 2.0), ("P", "R", 2.0), ("Q", "R", 2.0)]


def test_dsn_rules_drop_kicad_classes_and_add_pairs():
    """KiCad 自己导出的旧分类（OLD）去掉、网络放回缺省类，再按新分类拿出去；分类之间写 class_class"""
    import re

    from wqeda.gen.board import dsn_rules

    pairs = [("HV", "LV", 2.2), ("HV", "Default", 1.5)]
    out = dsn_rules(DSN, {"HV": (2.0, 0.5, ["C"]), "LV": (0.3, 0.2, ["D"])}, pairs)
    assert "(class OLD" not in out
    assert re.findall(r"\(class (\S+)", out) == ["HV", "LV", "kicad_default"]
    head = out[out.index("(class kicad_default") :].split("(circuit")[0]
    assert "C" not in head.split() and "D" not in head.split() and "A" in head.split()
    assert "(class_class (classes HV LV) (rule (clearance 2200)))" in out
    assert "(class_class (classes HV kicad_default) (rule (clearance 1500)))" in out


def test_ctrl_ls_board_fields_valid_and_bad_ones_caught():
    doc = D.load_design(CTRL)
    assert D.validate_design(doc) == []
    bad = copy.deepcopy(doc)
    bad["board"]["class_pairs"].append({"a": ["NoSuchClass"], "b": ["Default"], "clearance_mm": 1.0})
    bad["board"]["class_pairs"].append({"a": ["HV"], "b": ["Default"], "clearance_mm": 0})
    bad["board"]["net_classes"][0]["route_mm"] = 9.0  # 比 track_mm 粗
    p = D.validate_design(bad)
    assert any("NoSuchClass" in m for m in p)
    assert any("clearance_mm" in m for m in p)
    assert any("route_mm" in m for m in p)


def test_route_widths_go_to_router():
    from wqeda.gen.board import classes_of

    x = D.expand(D.load_design(CTRL))
    cls = classes_of(x)
    assert cls["AC_L"][0] == 1.2  # 布线先用 1.2 mm，布完加宽到 2.5
    assert cls["Boot"][0] == 0.5  # 没写 route_mm 的按 track_mm


def test_ctrl_ls_pin_conflicts_and_finished_board():
    """CTRL-LS：比布线间距近的同器件引脚（整流桥交流脚、功率模块相邻脚、分压电阻）都找得出来；仓库里的板子已全部接通"""
    pcbnew = pytest.importorskip("pcbnew")
    from wqeda.gen import board as gb
    from wqeda.gen import route_fit as RF

    x = D.expand(D.load_design(CTRL))
    cls = {n: c["name"] for c in x["net_classes"] for n in c["nets"]}
    own = {c["name"]: c["clearance_mm"] for c in x["net_classes"]}
    want = {frozenset((a, b)): c for a, b, c in gb.pairs_of(x)}

    def class_of(n):
        return cls.get(n, "Default")

    def clearance(a, b):
        ca, cb = class_of(a), class_of(b)
        return want.get(frozenset((ca, cb)), max(own.get(ca, 0.2), own.get(cb, 0.2)))

    brd = pcbnew.LoadBoard(CTRL_PCB)
    refs = {c[0] for c in RF.conflicts(brd, class_of, clearance)}
    assert {"BR101", "U401", "R422"} <= refs
    for ref, _p, _q, gap, need in RF.conflicts(brd, class_of, clearance):
        assert gap < need, ref
    # 布好的板子：补线这一步没有要补的
    assert RF.finish(brd, class_of, clearance, lambda n: 0.3, lambda n: ["F.Cu", "In2.Cu", "B.Cu"],
                     skip=("GND", "GND_ISO", "VBUS")) == []
