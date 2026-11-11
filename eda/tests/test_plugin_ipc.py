# -*- coding: utf-8 -*-
"""第 113 轮：KiCad 插件对真 KiCad 9（CI 任务 eda-plugin.yml 用无界面的 pcbnew 打开驱动板 A，打开进程间接口）。
本机没有 KiCad 9 时跳过（设 WQ_KICAD_IPC=1 才跑）。核对：进程间接口读出的板子模型，检查结论和 KiCad 7 那条入口一样；
读回“无变化”；插件的“定位”能在 KiCad 里选中器件。"""

import os
import sys

import pytest
from conftest import DESIGNS, EDA, EXAMPLE_CAP

pytestmark = pytest.mark.skipif(os.environ.get("WQ_KICAD_IPC") != "1", reason="要正在运行的 KiCad 9（CI 的插件任务）")

A = os.path.join(DESIGNS, "drv-joint", "design.yaml")
MODEL = os.path.join(DESIGNS, "drv-joint", "report", "board-model.json.gz")


@pytest.fixture(scope="module")
def kb():
    from kipy import KiCad

    k = KiCad(timeout_ms=60000)
    return k, k.get_board()


def test_version(kb):
    k, _ = kb
    v = k.get_version()
    print("KiCad", v)
    assert v.major >= 9


def test_ipc_model_gives_the_same_checks(kb):
    from wqeda import model_io
    from wqeda.checks import basic, layout, process
    from wqeda.readers import kicad_ipc
    from wqeda.schema import capability
    from wqeda.schema import design as D

    _, board = kb
    ipc = kicad_ipc.read(board)
    ref = model_io.load(MODEL)
    cap = capability.load(EXAMPLE_CAP)
    x = D.expand(D.load_design(A))

    def run(m):
        return {
            r["key"]: (r["status"], r["value"])
            for r in basic.run(m, cap)["checks"] + process.run(m, cap, x) + layout.run(m, x)
        }

    a, b = run(ipc), run(ref)
    diff = {k: (a.get(k), b[k]) for k in b if a.get(k, (None,))[0] != b[k][0]}
    assert not diff, diff
    assert sorted(c.ref for c in ipc.components) == sorted(c.ref for c in ref.components)
    assert sorted(ipc.courtyards) == sorted(ref.courtyards)


def test_readback_and_jump(kb):
    sys.path.insert(0, os.path.join(EDA, "kicad-plugin"))
    from wq_kicad.app import Session

    from wqeda import readback as R
    from wqeda.schema import design as D

    k, board = kb
    ch = R.compare(R.read_ipc(board), D.read_yaml(A))
    assert ch["none"], R.describe(ch)
    s = Session(k, board, os.path.join(DESIGNS, "drv-joint", "kicad"), os.path.join(EDA, "kicad-plugin"))
    s.factory = EXAMPLE_CAP
    # 第 129 轮以后 A 版布局约束全部通过：在 KiCad 里把 C27 挪远 10 mm 造一条“不通过”，测完挪回去
    from kipy.geometry import Vector2

    fp = next(f for f in board.get_footprints() if f.reference_field.text.value == "C27")
    x0, y0 = fp.position.x, fp.position.y
    fp.position = Vector2.from_xy(x0 - 10_000_000, y0)
    board.update_items(fp)
    try:
        s.check()
        row = next(r for r in s.result["rows"] if r["key"] == "L-near-C27")
        assert row["status"] == "fail"
        assert "C27" in s.jump(s.result["rows"].index(row))
        picked = [x.reference_field.text.value for x in board.get_selection() if hasattr(x, "reference_field")]
        assert "C27" in picked
    finally:
        fp.position = Vector2.from_xy(x0, y0)
        board.update_items(fp)
    assert R.compare(R.read_ipc(board), D.read_yaml(A))["none"]


def test_move_then_readback(kb):
    """细则第四节第 4 步：在 KiCad 里挪一个器件 → 读回 → 设计描述里的摆放跟着变（测完挪回去）"""
    from kipy.geometry import Vector2

    from wqeda import readback as R
    from wqeda.schema import design as D

    _, board = kb
    fp = next(f for f in board.get_footprints() if f.reference_field.text.value == "C27")
    x0, y0 = fp.position.x, fp.position.y
    fp.position = Vector2.from_xy(x0 + 1_000_000, y0)  # 往右挪 1 mm（KiCad 内部单位 nm）
    board.update_items(fp)
    try:
        raw = D.read_yaml(A)
        ch = R.compare(R.read_ipc(board), raw)
        moved = [m for m in ch["moved"] if m["ref"] == "C27"]
        assert moved and not ch["none"], R.describe(ch)
        with open(A, encoding="utf-8") as f:
            text = R.patch(f.read(), ch)
        D.validate_design(D.read_yaml_text(text))
        assert R.compare(R.read_ipc(board), D.read_yaml_text(text))["none"]
    finally:
        fp.position = Vector2.from_xy(x0, y0)
        board.update_items(fp)
    assert R.compare(R.read_ipc(board), D.read_yaml(A))["none"]
