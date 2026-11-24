"""Seven-point triangle rule used for surface loads (analysis/fea/solve.py, _T6_GAUSS).

Source of the finding: the FEM book (fem-ai-textbook), chapter 10, clue 19 — the two weight groups were swapped, so the
rule was exact only to degree 1 instead of 5. WenQuest CAD 0.3.6 plan, item B1.

Reference values:
- Monomials over the reference triangle: integral of x^a y^b = a! b! / (a + b + 2)! (exact).
- Uniform pressure on a flat 6-node triangle: corner nodes take 0, mid-side nodes 1/3 of the total force each.
- Cube in uniaxial compression, three symmetry planes, 10 MPa on top: stress is 10 MPa everywhere (exact).
  With the swapped weights the peak von Mises was 10.25 MPa (book, ex10_2_tri7.py).
No network, no LLM.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import analysis
from analysis.fea import solve as S
from tests.test_fea_bench import _faces, _need_fea, _plane, _write


def _exact(a, b):
    return math.factorial(a) * math.factorial(b) / math.factorial(a + b + 2)


def _quad(a, b):
    return sum(w * x ** a * y ** b for x, y, w in S._T6_GAUSS)


def test_weights_sum_to_triangle_area():
    assert abs(sum(w for _, _, w in S._T6_GAUSS) - 0.5) < 1e-15


@pytest.mark.parametrize("deg", range(6))
def test_exact_up_to_degree_five(deg):
    for a in range(deg + 1):
        b = deg - a
        assert abs(_quad(a, b) - _exact(a, b)) / _exact(a, b) < 1e-13, (a, b)


def test_not_exact_at_degree_six():
    # A degree-5 rule must miss some degree-6 monomial; this guards against testing a trivially different rule.
    assert max(abs(_quad(a, 6 - a) - _exact(a, 6 - a)) / _exact(a, 6 - a) for a in range(7)) > 1e-6


def test_flat_t6_pressure_split():
    share = sum(w * N for N, _, _, w in S._T6_TAB) / 0.5
    assert np.allclose(share[:3], 0.0, atol=1e-14)            # corners
    assert np.allclose(share[3:], 1 / 3, atol=1e-14)          # mid-side nodes


def test_cube_in_compression_stress_is_uniform(tmp_path):
    _need_fea()
    step = _write(tmp_path / "cube.step", lambda o: o.addBox(0, 0, 0, 20, 20, 20))
    f = _faces(step)
    sym = [{"type": "symmetry", "body": "b1", "faces": [_plane(f, ax, 0)]} for ax in range(3)]
    st = {"format": "fea-study/1", "name": "tri7", "bodies": [{"id": "b1", "step_path": step, "material": "45-QT"}],
          "supports": sym, "loads": [{"type": "pressure", "body": "b1", "faces": [_plane(f, 2, 20)], "value_mpa": 10.0}],
          "steps": [{"id": "s1", "type": "static"}], "mesh": {"size_mm": 5.0}, "checks": {"convergence": False}}
    r = analysis.run("fea", st)
    assert r["status"] == "ok", r["messages"]
    s = r["data"]["steps"][0]
    assert abs(s["vm_peak_all_mpa"] - 10.0) < 0.01, s["vm_peak_all_mpa"]   # swapped weights gave 10.25
