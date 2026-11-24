"""Ratio couplings (lead screw, worm, gear train, belt) hold under load — MuJoCo route of analysis.mbd.

Source of the finding: the multibody dynamics book (mbd-ai-textbook), chapter 24, clue 37: the joint equality used for
ratio couplings let the nut of the library lead screw drift 954 mm under 200 N (worm wheel 15.3 deg behind under 30 N·m)
while the result still said "ok". WenQuest CAD 0.3.6 plan, item C2.

Reference: with an ideal coupling the follower position equals ratio × driver position (library parameters of
C-SCN-LEAD and C-WRM-WORM); the book measured 0.13 mm and 0.51 deg with a tendon equality at the same solref/solimp.
No network, no LLM.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import analysis
from analysis import mbd
from analysis.mbd import core, mechanisms

pytest.importorskip("mujoco")


def _sim(mid, drives, T):
    setup = {"model": {"kind": "mechanism", "id": mid}, "duration_s": T, "sample_hz": 2000, "drives": drives}
    spec = mbd._spec(setup["model"])[0]
    internal = mechanisms.prepare_setup(mid, None, mbd._internal(setup, mbd._slide_joints(spec)))
    _s, ch, _ = core.simulate(spec, internal)
    return ch


def _dev(mid, ch):
    (out, inp, k), = mechanisms.ratio_couplings(mid, mechanisms.params(mid))
    return float(np.max(np.abs(ch["q." + out] - k * ch["q." + inp])))


def test_lead_screw_under_200_n():
    ch = _sim("C-SCN-LEAD", [{"joint": "screw", "kind": "speed", "value": 120}, {"joint": "nut", "kind": "torque", "value": -200}], 0.6)
    assert _dev("C-SCN-LEAD", ch) * 1000 < 0.2          # mm; the joint equality gave 954 mm


def test_worm_under_30_nm():
    ch = _sim("C-WRM-WORM", [{"joint": "worm", "kind": "speed", "value": 120}, {"joint": "wheel", "kind": "torque", "value": -30}], 0.6)
    assert math.degrees(_dev("C-WRM-WORM", ch)) < 1.0    # deg; the joint equality gave 15.3 deg


def test_gear_train_ratios_hold():
    p = mechanisms.params("C-GER-TRAIN")
    ch = _sim("C-GER-TRAIN", [{"joint": "shaft1", "kind": "speed", "value": 300}, {"joint": "shaft3", "kind": "torque", "value": -5}], 0.4)
    for out, inp, k in mechanisms.ratio_couplings("C-GER-TRAIN", p):
        assert math.degrees(np.max(np.abs(ch["q." + out] - k * ch["q." + inp]))) < 1.0


def test_public_result_reports_deviation():
    res = analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-SCN-LEAD"}, "duration_s": 0.3, "sample_hz": 1000,
                               "drives": [{"joint": "screw", "kind": "speed", "value": 120}, {"joint": "nut", "kind": "torque", "value": -200}]})
    assert res["status"] == "ok", res["messages"]
    d, = res["data"]["coupling_max_dev"]
    assert d["unit"] == "mm" and d["max_dev"] < 0.2 and d["limit"] == mbd.COUPLING_DEV_MM


def test_deviation_over_limit_is_not_ok(monkeypatch):
    monkeypatch.setattr(mbd, "COUPLING_DEV_MM", 1e-9)
    res = analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-SCN-LEAD"}, "duration_s": 0.1, "sample_hz": 1000,
                               "drives": [{"joint": "screw", "kind": "speed", "value": 120}, {"joint": "nut", "kind": "torque", "value": -200}]})
    assert res["status"] == "failed" and "传动比约束没守住" in res["messages"][0]
