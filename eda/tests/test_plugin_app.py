# -*- coding: utf-8 -*-
"""第 113 轮：KiCad 插件的本机结果页（不要 KiCad）：只认一次性口令；定位、重新检查走 POST；出错写在页面上。"""

import json
import os
import sys
import urllib.error
import urllib.request
from types import SimpleNamespace

from conftest import EDA, EXAMPLE_CAP

sys.path.insert(0, os.path.join(EDA, "kicad-plugin"))

from wq_kicad import app  # noqa: E402


def _session():
    from wqeda import model_io
    from conftest import DESIGNS

    model = model_io.load(os.path.join(DESIGNS, "drv-joint", "report", "board-model.json.gz"))
    res = app.run_checks(model, os.path.join(DESIGNS, "drv-joint", "design.yaml"), EXAMPLE_CAP)
    calls = []

    def jump(i):
        calls.append(i)
        return "已在 KiCad 里选中 " + "、".join(app.refs_in(res["rows"][i]))

    def boom():
        raise RuntimeError("KiCad 没响应")

    s = SimpleNamespace(result=res, design="design.yaml", token="tok", last=0, jump=jump, check=lambda: res,
                        readback=boom, report=lambda: "ok")
    return s, calls


def _post(url):
    req = urllib.request.Request(url, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def test_page_and_actions():
    s, calls = _session()
    srv, url = app.serve(s, open_browser=False)
    try:
        base = url.split("/?")[0]
        page = urllib.request.urlopen(url, timeout=10).read().decode("utf-8")
        assert "L-near-C27" in page and "定位" in page and "示例贴片厂" in page
        for bad in (base + "/", base + "/?t=wrong"):
            try:
                urllib.request.urlopen(bad, timeout=10)
                raise AssertionError("口令不对也能打开")
            except urllib.error.HTTPError as e:
                assert e.code == 404
        i = next(i for i, r in enumerate(s.result["rows"]) if r["key"] == "L-near-C27")
        assert "C27" in _post(base + "/jump?i={}&t=tok".format(i))["msg"] and calls == [i]
        assert _post(base + "/recheck?t=tok")["reload"] is True
        assert "出错了" in _post(base + "/readback?t=tok")["msg"]
        try:
            _post(base + "/jump?i=0&t=nope")
            raise AssertionError("口令不对也能定位")
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        srv.shutdown()


def test_find_design_and_factory(tmp_path):
    (tmp_path / "kicad").mkdir()
    assert app.find_design(str(tmp_path / "kicad")) is None
    (tmp_path / "design.yaml").write_text("x")
    assert app.find_design(str(tmp_path / "kicad")) == str(tmp_path / "design.yaml")
    here = os.path.join(EDA, "kicad-plugin")
    assert app.find_factory(str(tmp_path), here) is None  # 插件源码目录里没有 factories/（打包时才放进去）
    (tmp_path / "wqeda-factory.yaml").write_text("x")
    assert app.find_factory(str(tmp_path), here).endswith("wqeda-factory.yaml")
