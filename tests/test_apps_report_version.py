"""演练报告记录程序、零件库版本和生成时间；重跑时和上一份比，标出可能过时和结论变了的步骤。

《多体动力学》书第 36 章线索第 54 条（问渠 CAD 0.3.9 细则）：cobot_joint 存档报告 j2 的 C8 是 unknown（缺减速器输入侧惯量），
当前代码和零件库重跑为 warn，报告没有版本，认不出过时。
"""
import json

from examples.apps import common as C


def test_version_and_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path)
    (tmp_path / "cobot_joint").mkdir()
    old = {"app": "cobot_joint", "steps": [{"step": "选型 j2", "status": "unknown", "summary": "C8 unknown 惯量比：缺少减速器输入侧惯量"}]}
    (tmp_path / "cobot_joint" / "report.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    run = C.Run("cobot_joint", "测试", [], [])
    run.add("选型 j2", "ok", "C8 warn 惯量比 16.9 > 阈值 10", report={"overall": "warn"})
    rep = run.save()
    v = rep["version"]
    assert v["code_commit"] and len(v["library_sha256"]) == 16 and v["generated_at"]
    ch = rep["changes_since_previous"]
    assert any("没有记录" in r for r in ch["stale_reasons"])
    assert ch["changed_steps"][0]["step"] == "选型 j2" and "16.9" in ch["changed_steps"][0]["summary_after"]
    assert C.stale_reasons(rep) == []
    assert "结论变了的步骤：选型 j2" in (tmp_path / "cobot_joint" / "README.md").read_text(encoding="utf-8")
