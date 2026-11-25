"""问渠CAM 手册代码表与刚性攻丝（ADR-0125，ADR-0106 E3）：哈斯铣床的 M29 是接继电器——攻丝不写 M29，回读补回；
正式程序里有手册代码表外的 G、M 代码就不出。哈斯铣床配置按 Haas 官网在线《Mill Operator's Manual》写。"""

from __future__ import annotations

import json
import re

import pytest

from analysis.cam import machines, postproc, rs274
from tests import test_cam_post_q5 as Q5
from tests.verification import record_verdict


def test_haas_mill_tapping_without_m29():
    """开槽、钻孔（含啄钻）、攻丝：哈斯铣床程序不写 M29、G84 照写，O 加 5 位；回读一致（M29 补回后与仿真比）；每个 G、M 代码都在手册表里"""
    p = Q5._mill("haas-mill")
    assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
    t = p["release"]["text"]
    assert "M29" not in t and t.count("G84") == 2 and re.search(r"^O\d{5} ", t, re.MULTILINE)
    assert "M29 S400" in postproc.to_fanuc(t, "haas-mill", False)
    record_verdict(("哈斯铣床：攻丝不写 M29（哈斯的 M29 是接继电器），回读一致", "Haas mill: no M29 before tapping (Haas M29 is a relay), read-back matches"),
                   "pass", "pass")


@pytest.mark.skipif(rs274.find() is None, reason="没有 rs274")
def test_haas_mill_matches_rs274():
    prog = Q5._mill_prog()
    prog["ops"] = prog["ops"][:2]
    from analysis import cam

    r = cam.run({"mode": "program", "machine": "EX-VMC", "program": prog, "stock": {"box": [0, 0, 100, 60], "height": 40},
                 "machine_sim": Q5.MSIM_MILL, "post": "haas-mill"})
    p = r["data"]["programs"][0]
    res = rs274.compare(postproc.to_fanuc(p["release"]["text"], "haas-mill", False), False, machines.get("EX-VMC"), own_text=p["gcode"])
    assert res["ok"], res


def test_code_not_in_manual_is_refused(tmp_path, monkeypatch):
    """代码表里去掉 G84：带攻丝的程序不出，写明“手册代码表里没有 G84”"""
    d = tmp_path / "posts"
    d.mkdir()
    cfg = json.loads((postproc.postcfg.BUILTIN / "haas-mill.json").read_text(encoding="utf-8"))
    cfg["id"] = "hm2"
    cfg["dialect"]["codes"]["g"] = [g for g in cfg["dialect"]["codes"]["g"] if g != "84"]
    (d / "hm2.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("FAP_POSTS", str(d))
    p = Q5._mill("hm2")
    assert p["release"] is None and any("手册代码表里没有 G84" in c["text"] for c in p["checks"] if c["level"] == "error"), p["checks"]
    record_verdict(("手册代码表外的代码：程序不出、写明哪个代码", "code not in the manual's table: program withheld, code named"), "error", "error")
