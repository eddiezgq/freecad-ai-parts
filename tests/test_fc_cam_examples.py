"""问渠CAM 的入门例子（ADR-0104 产品化第 3 步）：重算与样张（results.json）一致。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.freecad
EX = Path(__file__).resolve().parents[1] / "examples" / "wenquest-cam"


def _builder():
    sys.path.insert(0, str(EX))
    import build_examples as B

    return B


@pytest.mark.parametrize("n", [1, 2])
def test_examples_reproduce(n):
    pytest.importorskip("FreeCAD")
    B = _builder()
    _, _d, r = B.example1() if n == 1 else B.example2()
    sample = json.loads((EX / B.DIRS[n] / "results.json").read_text(encoding="utf-8"))
    got = B._summary(r)
    assert got["total_time_s"] == pytest.approx(sample["total_time_s"], abs=0.05)
    for a, b in zip(got["programs"], sample["programs"], strict=True):
        assert a["released"] and b["released"] and not a["errors"]
        assert a["machine_sim"]["fingerprint"] == b["machine_sim"]["fingerprint"]
        nc = EX / B.DIRS[n] / f"O{a['number']:04d}_fanuc.nc"
        assert a["machine_sim"]["fingerprint"] in nc.read_text(encoding="utf-8")
