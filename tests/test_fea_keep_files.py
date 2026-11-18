"""留下求解器文件（ADR-0093 补充十二第 2 步）：给 keep_dir 时各静力 / 模态步最终那次求解的 job.frd 留下来，结果与不留时完全一样。"""

from __future__ import annotations

from assist.fea_report import fingerprint
from tests.test_fea_bench import _need_fea, _write


def test_keep_dir_leaves_frd_and_does_not_change_results(tmp_path):
    _need_fea()
    from analysis.fea import run_study
    from analysis.fea.geometry import faces

    step = _write(tmp_path / "bar.step", lambda o: o.addBox(0, 0, 0, 100, 10, 10))
    fs = faces(step)[0]
    x0 = next(f["id"] for f in fs if abs(f["center"][0]) < 1e-6)
    x1 = next(f["id"] for f in fs if abs(f["center"][0] - 100) < 1e-6)
    study = {"format": "fea-study/1", "name": "bar", "bodies": [{"id": "b1", "step_path": step, "material": "45-QT"}],
             "supports": [{"type": "fixed", "body": "b1", "faces": [x0]}],
             "loads": [{"type": "force", "body": "b1", "faces": [x1], "vector_n": [0, 0, -100]}],
             "steps": [{"id": "s1", "type": "static"}, {"id": "m1", "type": "modal", "n_modes": 2}],
             "mesh": {"size_mm": 5}}
    a = run_study(study)
    b = run_study(study, keep_dir=str(tmp_path / "keep"))
    assert a["status"] == b["status"] == "ok"
    assert fingerprint(a["data"]) == fingerprint(b["data"])
    for sid in ("s1", "m1"):
        frd = tmp_path / "keep" / sid / "job.frd"
        assert frd.is_file() and frd.stat().st_size > 1000
        assert (tmp_path / "keep" / sid / "job.inp").is_file()


def test_ccx_runs_single_threaded_by_default():
    """issue #543：CalculiX 多线程时结果不可复现，缺省单线程；FAP_CCX_THREADS 可另指定；BLAS 一律单线程"""
    from analysis.fea.solve import ccx_env

    env = ccx_env({"PATH": "/usr/bin"})
    assert env["OMP_NUM_THREADS"] == "1" and env["OPENBLAS_NUM_THREADS"] == "1"
    assert ccx_env({"FAP_CCX_THREADS": "4"})["OMP_NUM_THREADS"] == "4"
