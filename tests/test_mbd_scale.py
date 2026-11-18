"""多体动力学 D8a（ADR-0097 补充二十一）：成批计算与原逐行计算完全一致；50 个构件的链条跑通。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

from analysis.mbd.dae import model as M
from analysis.mbd.dae import run as R

FIX = Path(__file__).resolve().parent / "fixtures" / "mbd-model" / "valid"


@pytest.mark.parametrize("name", sorted(p.name for p in FIX.glob("*.json")))
def test_batched_constraints_equal_row_by_row(name):
    sysm = M.build(json.loads((FIX / name).read_text())["instance"])
    rng = np.random.default_rng(1)
    q = sysm.q0() + 1e-2 * rng.standard_normal(sysm.n)
    qd = rng.standard_normal(sysm.n)
    for k in range(sysm.nb):
        q[7 * k + 3:7 * k + 7] /= np.linalg.norm(q[7 * k + 3:7 * k + 7])
    t = 0.1
    z = np.zeros(sysm.n)
    assert np.allclose(sysm.jac(q, t), sysm._jac_rows(q, t, sysm.rows), atol=1e-12)
    assert np.allclose(sysm.phi(q, t), [j.v for j in sysm.phi_jets(q, z, t, 0.0)], atol=1e-12)
    assert np.allclose(sysm.nu(q, t), [-j.d for j in sysm.phi_jets(q, z, t, 1.0)], atol=1e-12)
    assert np.allclose(sysm.gamma(q, qd, t), [-j.dd for j in sysm.phi_jets(q, qd, t, 1.0)], atol=1e-10)


def chain(n, L=20.0):
    bodies, joints = [], []
    for k in range(n):
        bodies.append({"id": f"b{k}", "mass_kg": 0.1, "cm_mm": [L * (k + 0.5), 0, 0],
                       "inertia_kg_m2": {"ixx": 1e-6, "iyy": 4e-6, "izz": 4e-6}})
        joints.append({"id": f"j{k}", "type": "revolute", "body_i": "ground" if k == 0 else f"b{k - 1}", "body_j": f"b{k}",
                       "point_mm": [L * k, 0, 0], "axis": [0, 1, 0]})
    return {"format": "mbd-model/1", "name": f"{n} 节链", "bodies": bodies, "joints": joints, "gravity_mm_s2": [0, 0, -9810],
            "analysis": {"type": "dynamic", "end_time_s": 0.1, "output_steps": 10, "rtol": 1e-6, "atol": 1e-9}}


def test_fifty_link_chain_runs_and_conserves_energy():
    t0 = time.time()
    data, _ = R.run_model(chain(50))
    took = time.time() - t0
    v = {x["key"]: x for x in data["verification"]}
    assert v["constraint_residual"]["status"] == "pass"
    assert v["energy_drift"]["status"] == "pass"
    assert v["dof"]["status"] == "pass" and data["dof"] == 50
    assert took < 120                                   # 本机约 5 s（ADR-0097 补充二十一记录）
