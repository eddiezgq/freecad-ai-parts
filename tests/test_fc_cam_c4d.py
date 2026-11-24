"""问渠CAM C4d 界面（ADR-0106 C4d）：加工树里的双主轴（装夹名、背面刀号 +10 → back_tools）、两个刀架（装夹带通道、两条程序、节拍摘要）、
换回普通机床还原；B 轴车削算完工序上记 B 角。"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.freecad

TWIN = {"sync_on": ["M210"], "sync_off": ["M211"], "sub_clamp": ["M220"], "sub_unclamp": ["M221"],
        "sub_select": ["G14"], "main_select": ["G15"], "sub_offset": ["G55"]}


def _post(tmp_path, monkeypatch):
    d = tmp_path / "posts"
    d.mkdir()
    (d / "tw.json").write_text(json.dumps({"format": "cam-post/1", "id": "tw", "name": "twin", "family": "fanuc", "kinds": ["lathe"],
                                           "source": "测试", "twin": TWIN, "channels": {"wait": "M{n}", "wait_first": 100}}), encoding="utf-8")
    monkeypatch.setenv("FAP_POSTS", str(d))


def _revolved(doc, name, pts):
    """(z 从左端起, 直径) 的轮廓绕 Z 转一圈；右端在 Z0"""
    import FreeCAD as App
    import Part

    L = pts[-1][0]
    poly = [App.Vector(0, 0, -L)] + [App.Vector(d / 2.0, 0, z - L) for z, d in pts] + [App.Vector(0, 0, 0), App.Vector(0, 0, -L)]
    face = Part.Face(Part.makePolygon(poly))
    m = doc.addObject("Part::Feature", name)
    m.Shape = face.revolve(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 360).removeSplitter()
    doc.recompute()
    return m


def _confirm_all(CO, job):
    for s in CO.setups(job):
        for o in CO.ops(s):
            CO.confirm(o)


def test_twin_and_two_turrets_in_tree(tmp_path, monkeypatch):
    import FreeCAD as App

    from freecad_addon.core import cam_study as S
    from freecad_addon.fc import cam_objects as CO

    _post(tmp_path, monkeypatch)
    doc = App.newDocument("c4d")
    try:
        # Ø30×30、Ø44×20、Ø36×30（右端圆柱 30 mm，副主轴夹 30）
        m = _revolved(doc, "Shaft", [[0, 30], [30, 30], [30, 44], [50, 44], [50, 36], [80, 36]])
        job = CO.new_job(doc, m, "turn", machine="EX-MT-TS", post="tw")
        d = json.loads(job.PartData)
        d["parting"] = {"tool_w": 3.0}
        job.PartData = json.dumps(d)
        CO.draft(job)
        right, left = CO.setups(job)
        assert left.Label == CO.T("左端（副主轴背面加工）") and right.Label == CO.T("右端（第一次装夹）")
        nl = {o.OpKind: o.ToolNumber for o in CO.ops(left)}
        assert nl["rough"] == 11 and nl["finish"] == 12, nl
        assert CO._back_tools(job) == {"1": 11, "2": 12}
        _confirm_all(CO, job)
        r = CO.calculate(job)
        p0 = r["data"]["programs"][0]
        assert p0["release"] is not None, [c["text"] for c in p0["checks"] if c["level"] == "error"]
        assert "T1111" in p0["release"]["text"] and list(json.loads(job.Programs)) == ["O1001_tw.nc"]
        assert any(x.startswith("副主轴接料：夹 Ø36 段 30 mm") for x in S.summary(r)), S.summary(r)

        # 两个刀架：装夹名带通道、Channel、两条程序、摘要有节拍
        job.Machine = "EX-MT-TT"
        CO.sync_machine(job)
        assert (right.Label, left.Label) == (CO.T("右端（主主轴，通道 1）"), CO.T("左端（副主轴背面加工，通道 2）"))
        assert (right.Channel, left.Channel) == (1, 2)
        assert {o.OpKind: o.ToolNumber for o in CO.ops(left)} == nl          # 干法没变（还是双主轴），刀号不动
        r = CO.calculate(job)
        assert sorted(json.loads(job.Programs)) == ["O1001_tw.nc", "O1002_tw.nc"], [
            c["text"] for p in r["data"]["programs"] for c in p["checks"] if c["level"] == "error"]
        assert any(x.startswith("两个刀架：通道 1 车右端") and "节拍" in x for x in S.summary(r)), S.summary(r)

        # 左端刀号改成与右端同号：报错点名
        rough_l = next(o for o in CO.ops(left) if o.OpKind == "rough")
        rough_l.ToolNumber = 1
        with pytest.raises(CO.CamObjError, match="与右端的刀重了"):
            CO.calculate(job)
        rough_l.ToolNumber = 11

        # 换回普通车铣中心：名字、刀号还原
        job.Machine = "EX-MT-CY"
        CO.sync_machine(job)
        assert (right.Label, left.Label) == (CO.T("右端（第一次装夹）"), CO.T("左端（调头装夹）"))
        assert (right.Channel, left.Channel) == (0, 0)
        assert {o.OpKind: o.ToolNumber for o in CO.ops(left)}["rough"] == 1
    finally:
        App.closeDocument(doc.Name)


def test_b_angle_on_ops():
    """EX-MT-B 车 15° 下坡（PCLNR + CNMG，刀长 180）：粗、精车工序记 B −13°"""
    import FreeCAD as App

    from freecad_addon.core import cam_study as S
    from freecad_addon.fc import cam_objects as CO

    doc = App.newDocument("c4db")
    try:
        m = _revolved(doc, "Neck", [[0, 50], [20, 50], [27, 36], [37, 36], [51.928, 44], [80, 44]])
        job = CO.new_job(doc, m, "turn", machine="EX-MT-B")
        CO.draft(job)
        right = CO.setups(job)[0]
        for s in CO.setups(job):
            for o in CO.ops(s):
                if o.OpKind in ("rough", "finish"):
                    o.ToolId = "TR-CNMG"
        job.ToolLengths = json.dumps({"TR-CNMG": 180})
        job.Fixture = ""
        r = CO.calculate(job)
        b = {o.OpKind: o.BAngle for o in CO.ops(right)}
        assert b["rough"] == b["finish"] == -13.0, (b, [c["text"] for p in r["data"]["programs"] for c in p["checks"] if c["level"] == "error"])
        assert any("B 轴车削 T1 B-13°" in x for x in S.summary(r)), S.summary(r)
    finally:
        App.closeDocument(doc.Name)
