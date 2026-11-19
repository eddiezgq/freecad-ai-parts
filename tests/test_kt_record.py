"""应力集中系数录制与回放（assist.kt_record）：回放与录制一致，错误照样重现，查不到才现算"""

from __future__ import annotations

import pytest

from assist import kt_record


def fake(d, big, r, bore=0.0):
    if r >= (big - d) / 2:
        raise ValueError("圆角太大")
    return {"kt_bending": 1 + d / big + r, "kt_torsion": 1 + r, "method": "fake"}


def test_replay_returns_recorded_values_and_errors(tmp_path):
    path = tmp_path / "kt.json"
    rec = kt_record.recording(path, kt=fake)
    a = rec(12, 17, 0.5)
    with pytest.raises(ValueError):
        rec(12, 13, 0.5)
    rec(30, 50, 1, 20)                                     # 空心轴多一个参数
    calls = []
    rep = kt_record.replaying(path, kt=lambda *x: calls.append(x) or fake(*x))
    assert rep(12.0, 17.0, 0.5) == a and not calls          # 整数与小数写法同一个键
    with pytest.raises(kt_record.KtReplayError, match="圆角太大"):
        rep(12, 13, 0.5)
    assert rep(30, 50, 1, 20)["kt_bending"] == pytest.approx(fake(30, 50, 1, 20)["kt_bending"]) and not calls
    rep(12, 18, 0.5)                                       # 没录过：现算
    assert calls == [(12, 18, 0.5)]


def test_recording_file_is_stable_json(tmp_path):
    path = tmp_path / "sub" / "kt.json"
    rec = kt_record.recording(path, kt=fake)
    rec(20, 30, 1)
    rec(12, 17, 0.5)
    text = path.read_text(encoding="utf-8")
    assert text.index("12.0") < text.index("20.0")          # 按输入排序，录制提交时差异好看
