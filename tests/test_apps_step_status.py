"""演练报告每一步的状态取本步全部判据的最差值；“跑完了没有”另记 completed。

《多体动力学》书第 36 章线索第 56 条（问渠 CAD 0.3.9 细则）：五份报告 89 步里 13 步状态“完成”而摘要是“总体 unknown”“待确认”。
"""
import pytest

from examples.apps import common as C


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path)
    return C.Run("t", "测试", [], [])


def test_ok_with_unknown_content_is_downgraded(run):
    run.add("布局", "ok", "按布局复核：总体 unknown")
    run.add("选型", "ok", "C1 通过", report={"overall": "fail", "checks": []})
    run.add("热分析", "ok", "温升 30 K", items=[{"verdict": "warn"}])
    run.add("正常", "ok", "C1–C9 通过", report={"overall": "pass"})
    run.add("说明", "ok", "C3 在厂商确认前按规定记“待确认”", mentions_ok=True)
    st = {s["step"]: s for s in run.steps}
    assert st["布局"]["status"] == "unknown"
    assert st["选型"]["status"] == "fail" and st["选型"]["completed"] is True
    assert st["热分析"]["status"] == "unknown"
    assert st["正常"]["status"] == "ok"
    assert st["说明"]["status"] == "ok"            # 摘要只是在解释别处的规定


def test_crash_is_not_completed(run):
    run.guard("坏", lambda: 1 / 0)
    assert run.steps[0]["status"] == "fail" and run.steps[0]["completed"] is False
