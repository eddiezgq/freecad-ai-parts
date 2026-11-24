"""问渠CAM E1 独立解释器核对（ADR-0106 E1）：正式程序交给 LinuxCNC 的 RS274NGC 解释器 rs274，走出来的刀路与问渠CAM 整机仿真用的程序逐点一致。
后处理的每个开关、FANUC / 华中 / 广数，车（粗精车、切槽、车螺纹、端面）与铣（开槽、钻孔、啄钻循环）都过。没装 rs274 的环境跳过
（`scripts/fetch_rs274.sh`，CI 装）。"""

from __future__ import annotations

import pytest

from analysis import cam
from analysis.cam import machines, postproc, rs274
from tests import test_cam_post_q5 as Q5
from tests.test_cam_post_q5 import posts_dir  # noqa: F401
from tests.verification import record_verdict

pytestmark = pytest.mark.skipif(rs274.find() is None, reason="没有 rs274（scripts/fetch_rs274.sh）")

POSTS = {"fanuc": None, "hnc": None, "gsk": None, **{f"t-{k}": v for k, v in Q5.SWITCHES.items()}}


def _mill(post):
    prog = Q5._mill_prog()
    prog["ops"] = prog["ops"][:2]                 # 刚性攻丝 G84（M29）rs274 没有，不比（ADR-0106 E1）
    r = cam.run({"mode": "program", "machine": "EX-VMC", "program": prog, "stock": {"box": [0, 0, 100, 60], "height": 40},
                 "machine_sim": Q5.MSIM_MILL, "post": post})
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"]


def _turn(post):
    r = cam.run({**Q5.TURN, "cycles": False, "post": post})     # G71 / G76 两家写法不同（LinuxCNC 的 G71 另一套参数），不比
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"]


@pytest.mark.parametrize("post", list(POSTS))
def test_release_programs_match_rs274(post, posts_dir):  # noqa: F811
    """正式程序（换回 FANUC 写法）给 rs274 解释 → 刀路与整机仿真用的程序一致（偏差 < 0.001 mm；G83 退回深度按数控系统参数，只差空走）"""
    cid = post if POSTS[post] is None else posts_dir(post, **POSTS[post])
    cases = [("turn", p) for p in _turn(cid)] + ([] if post == "gsk" else [("mill", p) for p in _mill(cid)])
    for kind, p in cases:
        assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
        lathe = kind == "turn"
        text = postproc.to_fanuc(p["release"]["text"], cid, lathe)
        res = rs274.compare(text, lathe, machines.get("EX-LATHE" if lathe else "EX-VMC"), own_text=p["gcode"])
        assert res["ok"], (kind, p.get("title"), res)
        assert res["n_ref"] > 10
    record_verdict((f"独立解释器 rs274：{post} 正式程序的刀路与仿真一致", f"independent interpreter rs274: {post} release toolpath matches simulation"),
                   "pass", "pass")


def test_rs274_notices_a_misread():
    """正式程序里改一个数（X48.0 → X48.5）：rs274 走的与仿真对不上，报出来——核对不是走过场"""
    p = _turn("fanuc")[0]
    text = postproc.to_fanuc(p["release"]["text"], "fanuc", True)
    res = rs274.compare(text, True, machines.get("EX-LATHE"), own_text=p["gcode"])
    assert res["ok"]
    bad = rs274.compare(text.replace("X48.0", "X48.5", 1), True, machines.get("EX-LATHE"), own_text=p["gcode"])
    assert not bad["ok"] and bad["why"], bad
    record_verdict(("独立解释器 rs274：程序改一个数就报不一致", "independent interpreter rs274: one changed number is reported"), "error", "error")
