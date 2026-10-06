# -*- coding: utf-8 -*-
"""第 6 轮 W2、W3：网页设计台——校核（不合格不能发布、GB/T 1095 推荐提示）、在线发布的消息与桌面宏一致、版本号递增。"""
import pytest

import wqbus
from hub import design as D


class FakeDB:
    def __init__(self):
        self.files, self.msgs = {}, []

    def x(self, sql, args):
        self.files[args[0]] = args

    def messages(self, types, mode=None, order="asc", limit=None, **kw):
        out = [m for m in self.msgs if m["type"] in types and m["mode"] == mode]
        return list(reversed(out)) if order == "desc" else out


def _emit(db):
    def emit(tp, type_, data):
        db.msgs.append(dict(wqbus.make(type_, "web-cad", data, mode="teach"), _topic=tp))   # make() 按总线规范校验
    return emit


def test_check_errors_and_gbt1095():
    p = D.normalize(D.defaults())
    r = D.check(p)
    assert r["ok"] and r["errors"] == [] and r["warnings"] == [] and r["recommended"]["b"] == 12
    assert r["bom"] == [{"item_code": "RM-45-D50", "qty": r["bom"][0]["qty"]}]
    long = D.normalize(dict(D.defaults(), keyway={"segment": 2, "b": 12, "t": 5, "L": 70}))
    assert not D.check(long)["ok"] and "超过该轴段长度" in D.check(long)["errors"][0]
    narrow = D.normalize(dict(D.defaults(), keyway={"segment": 2, "b": 10, "t": 5, "L": 45}))
    c = D.check(narrow)
    assert c["ok"] and "GB/T 1095" in c["warnings"][0]
    fat = D.normalize(dict(D.defaults(), segments=[[60, 40]], keyway=None))
    assert "超出范围" in D.check(fat)["errors"][0]
    with pytest.raises(ValueError):
        D.normalize({"segments": "x"})


def test_publish_matches_desktop_macro_format():
    db = FakeDB()
    p = D.normalize(dict(D.defaults(), keyway={"segment": 2, "b": 12, "t": 5, "L": 42}))
    out = D.publish(db, _emit(db), p, "工艺员·A1", "teach", "键槽长 45 → 42")
    assert out["revision"] == 2                                            # 没发布过：现行算第 1 版
    rel, g = db.msgs
    assert rel["_topic"] == "wq/gearbox/design/sh-301/release" and g["_topic"] == "wq/gearbox/design/sh-301/gcode"
    # 与 freecad/wq_publish.py 发出的字段相同
    assert set(rel["data"]) == {"item", "revision", "params", "bom", "files", "author", "change_note", "total_length_mm", "tool"}
    assert set(g["data"]) == {"item", "revision", "operation", "machine", "gcode_ref", "gcode_url", "sha256", "tools",
                              "est_time_s", "cut_length_mm", "slot"}
    assert rel["data"]["tool"] == "问渠网页设计台" and rel["data"]["params"]["keyway"]["L"] == 42
    kinds = [f["kind"] for f in rel["data"]["files"]]
    assert "drawing" in kinds and len(db.files) == len(kinds) + 1        # 图纸（+STEP）+ G 代码都存了
    if out["step"]:
        assert kinds[0] == "step"
    assert D.publish(db, _emit(db), p, "工艺员·A1", "teach")["revision"] == 3


def test_publish_refuses_bad_params():
    db = FakeDB()
    bad = D.normalize(dict(D.defaults(), keyway={"segment": 2, "b": 12, "t": 5, "L": 70}))
    with pytest.raises(ValueError):
        D.publish(db, _emit(db), bad, "x", "teach")
    assert db.msgs == [] and db.files == {}


def test_step_geometry():
    bd = pytest.importorskip("build123d")
    import os
    import tempfile
    data = D.step_bytes(D.normalize(D.defaults()))
    path = os.path.join(tempfile.mkdtemp(), "s.step")
    open(path, "wb").write(data)
    shape = bd.import_step(path)
    size = shape.bounding_box().size
    assert round(size.Z) == 167 and round(size.X) == 40
    assert 150000 < shape.volume < 160478                                 # 各段圆柱体积和减去键槽、倒角


def test_freecad_pack(monkeypatch):
    """W5：宏包里已填好工作台地址、本人凭证和模式"""
    import importlib
    import io
    import zipfile
    from fastapi.testclient import TestClient
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.setenv("WQ_SECRET", "test-secret")
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    c = TestClient(app_mod.app)
    assert c.get("/api/freecad/pack.zip").status_code == 401
    tok = app_mod._sign({"name": "小李", "role": "engineer", "mode": "teach", "teacher": False, "exp": 4e9})
    r = c.get("/api/freecad/pack.zip", headers={"x-wq-token": tok, "host": "factory.example.com", "x-forwarded-proto": "https"})
    z = zipfile.ZipFile(io.BytesIO(r.content))
    pub = z.read("wenquest-freecad/wq_publish.py").decode("utf-8")
    assert "'https://factory.example.com'" in pub and repr(tok) in pub and "'teach'" in pub
    assert "https://factory.example.com" in z.read("wenquest-freecad/wq_library.py").decode("utf-8")
    assert "7 天内有效" in z.read("wenquest-freecad/使用说明.txt").decode("utf-8")
    assert "addWorkbench" in z.read("wenquest-freecad/Mod/WenQuest/InitGui.py").decode("utf-8")       # 第 8 轮工作台
    assert repr(tok) in z.read("wenquest-freecad/Mod/WenQuest/wq_publish.py").decode("utf-8")
    assert "def submit" in z.read("wenquest-freecad/wq_submit.py").decode("utf-8")
    swb = z.read("wenquest-freecad/SolidWorks/wq_submit_solidworks.swb").decode("ascii")             # 第 10 轮
    assert 'Const WQ_HUB = "https://factory.example.com"' in swb and tok in swb and "__WQ_" not in swb


def test_step_fillets():
    """第 11 轮 F4：台阶过渡圆角——小于台阶高才能做，做出来的模型每个台阶都有圆角面"""
    import pytest
    pytest.importorskip("build123d")
    from hub import design as D, task_review as R
    p = D.normalize({"segments": [[35, 37], [40, 53], [48, 10], [42, 15], [35, 57], [30, 68]], "chamfer": 1, "fillet": 1.0,
                     "keyway": {"segment": 1, "b": 12, "t": 5, "L": 45}})
    assert D.check(p)["ok"]
    g = R.shaft_features(D.step_bytes(p))
    assert len(g["fillets"]) == 5 and all(abs(r - 1.0) < 1e-6 for _, r in g["fillets"])
    bad = D.normalize({"segments": [[35, 37], [37, 10]], "chamfer": 0, "fillet": 1.5, "keyway": None})
    assert "做不出来" in D.check(bad)["errors"][0]
    assert "fillet" not in D.normalize(D.defaults())           # 旧参数不变
