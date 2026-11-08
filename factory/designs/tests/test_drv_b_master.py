"""第 115 轮：多关节 CAN 主站（master/master.py）——仿真结果全过、运动学对、协议与固件一致、只用标准库。"""
import ast
import json
import os
import re
import sys

FW = os.path.join(os.path.dirname(__file__), "..", "drv-joint-b", "fw")
sys.path.insert(0, os.path.join(FW, "master"))
import master as M  # noqa: E402


def test_sim_master_all_pass():
    d = json.load(open(os.path.join(FW, "out", "sim_master.json"), encoding="utf-8"))
    assert d["round"] == 115 and [s["id"] for s in d["scenarios"]] == ["line", "fault", "lost"]
    assert all(s["ok"] and all(c["ok"] for c in s["checks"]) for s in d["scenarios"])
    ev = {s["id"]: " ".join(e[1] for e in s["events"]) for s in d["scenarios"]}
    assert "报警" in ev["fault"] and "掉线" in ev["lost"] and "完成" in ev["line"]


def test_kinematics_roundtrip():
    for x, y in ((0.40, 0.15), (0.20, 0.35), (0.30, 0.25)):
        t1, t2 = M.ik(x, y)
        x2, y2 = M.fk(t1, t2)
        assert abs(x2 - x) < 1e-12 and abs(y2 - y) < 1e-12 and t2 > 0
    assert M.trapezoid(0) == 0 and abs(M.trapezoid(1) - 1) < 1e-12 and abs(M.trapezoid(0.5) - 0.5) < 1e-12


def test_protocol_matches_firmware():
    h = open(os.path.join(FW, "src", "can_proto.h"), encoding="utf-8").read()
    for name, base in (("CMD", M.ID_CMD), ("STATUS", M.ID_STATUS), ("EMCY", M.ID_EMCY), ("HEART", M.ID_HEART)):
        assert re.search(r"#define CAN_ID_{} \(0x{:03X} \+ NODE\)".format(name, base), h)
    assert "#ifndef NODE" in h
    for code in M.FAULTS:
        assert "= {}".format(code) in h


def test_master_uses_stdlib_only():
    tree = ast.parse(open(os.path.join(FW, "master", "master.py"), encoding="utf-8").read())
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert mods <= {"math", "struct"}
