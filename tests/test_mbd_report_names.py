"""AI 解释段落的检查：查数字前先去掉模型里的名字（j1、R2、d1 常带数字）。

《多体动力学》书第 45 章线索第 82 条（问渠 CAD 0.3.9 细则）：下面两句被当成“写了数字”退回；第 45 章 37 句正确解释退回 17 句。
"""
from assist.mbd_report import check_paragraph, model_names

DATA = {"motions": {"d1": {}}, "joints": {"j1": {}, "R2": {}}, "bodies": {"link1": {}},
        "verification": [{"key": "energy_drift", "name": "能量漂移"}]}
F = {"drive_d1_peak": {}, "joint_j1_force": {}}


def test_names_with_digits_pass():
    names = model_names(DATA)
    assert check_paragraph("驱动 d1 的力矩峰值为 {{drive_d1_peak}}，出现在加速段。", F, names) is None
    assert check_paragraph("j1 的反力是所有运动副中最大的，为 {{joint_j1_force}}。", F, names) is None


def test_real_digits_still_rejected():
    names = model_names(DATA)
    assert check_paragraph("j1 的反力约为 3 kN。", F, names) == "段落里直接写了数字"
    assert check_paragraph("link12 的质量很大。", F, names) == "段落里直接写了数字"   # 不是模型里的名字
