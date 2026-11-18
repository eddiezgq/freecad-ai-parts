"""积分器建议（ADR-0098 E3）"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from analysis.mbd.dae import advise
from tests.test_mbd_hht_jac import beam_chain, crank_flex

FIX = Path(__file__).parent / "fixtures" / "mbd-model" / "valid"


def _load(name):
    doc = json.loads((FIX / name).read_text(encoding="utf-8"))
    return doc.get("instance", doc)


def test_plain_mechanism_gets_explicit():
    s = advise.suggest(_load("pendulum.json"))
    assert s["integrator"] == "DOP853" and "不硬" in s["reason"]


def test_flex_and_beams_get_hht_with_tolerances():
    s = advise.suggest(crank_flex(0.01, 10))
    assert s["integrator"] == "HHT" and s["rtol"] == 1e-6 and "柔性构件 rod" in s["reason"]
    s = advise.suggest(beam_chain(5))
    assert s["integrator"] == "HHT" and s["rtol"] == 1e-7 and "梁元件" in s["reason"]
    m = beam_chain(5)
    m["contacts"] = [{"id": "c"}]
    assert advise.suggest(m)["rtol"] == 1e-8


def test_not_dynamic_no_advice_and_apply_respects_user_choice():
    m = _load("pendulum.json")
    m2 = copy.deepcopy(m)
    m2["analysis"] = {"type": "kinematic", "end_time_s": 1}
    assert advise.suggest(m2) == {} and advise.apply(m2) is None
    m3 = beam_chain(5)
    del m3["analysis"]["integrator"]
    why = advise.apply(m3)
    assert m3["analysis"]["integrator"] == "HHT" and m3["analysis"]["rtol"] == 1e-7 and why
    m4 = beam_chain(5)
    m4["analysis"]["integrator"] = "DOP853"
    assert advise.apply(m4) is None and m4["analysis"]["integrator"] == "DOP853"


def test_nonlinear_beam_counts_as_beam():
    from tests.test_mbd_nlbeam import cantilever

    m = cantilever([])
    m["analysis"] = {"type": "dynamic", "end_time_s": 0.01}
    s = advise.suggest(m)
    assert s["integrator"] == "HHT" and s["rtol"] == 1e-7 and "大变形梁" in s["reason"]
