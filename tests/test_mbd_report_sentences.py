"""AI 解释的逐句核对：比较、倍数、最大、阶段、成因、正负、核查结论、效应、判定词、占位符后的单位；隐去不通过的核查。

《多体动力学》书第 45 章线索第 83 条（问渠 CAD 0.3.9 细则）：名字不带数字时，54 句应拦的错误原来只拦下 12 句。
这里用书里的 R1（竖直两杆臂，五次多项式各转 90° 与 −45°，1 s，运动学）和它的错误句、正确句；四份结果全部的核对
（54 句全拦、37 句正确全放行、4 句无依据因果交人看）在 PR 里另报。
"""
import pytest

from analysis.mbd.dae.run import run_model
from assist import mbd_report as R

Q5 = "(10*time**3-15*time**4+6*time**5)"
I1, I2 = 4 * 0.4 ** 2 / 12, 2 * 0.3 ** 2 / 12
ARM = {"format": "mbd-model/1", "name": "竖直两杆臂", "gravity_mm_s2": [0, -9810.0, 0],
       "bodies": [{"id": "l1", "mass_kg": 4.0, "cm_mm": [200, 0, 0], "inertia_kg_m2": {"ixx": 1e-9, "iyy": I1, "izz": I1}},
                  {"id": "l2", "mass_kg": 2.0, "cm_mm": [550, 0, 0], "inertia_kg_m2": {"ixx": 1e-9, "iyy": I2, "izz": I2}}],
       "joints": [{"id": "j1", "type": "revolute", "body_i": "ground", "body_j": "l1", "point_mm": [0, 0, 0], "axis": [0, 0, 1]},
                  {"id": "j2", "type": "revolute", "body_i": "l1", "body_j": "l2", "point_mm": [400, 0, 0], "axis": [0, 0, 1]}],
       "motions": [{"id": "d1", "joint": "j1", "dof": "rotation", "function": f"90*{Q5}"},
                   {"id": "d2", "joint": "j2", "dof": "rotation", "function": f"-45*{Q5}"}],
       "analysis": {"type": "kinematic", "end_time_s": 1.0, "output_steps": 200}}
WRONG = ["驱动 d1 的力矩峰值为 25.3 N·m。", "驱动 d1 的峰值约为驱动 d2 的两倍。", "驱动 d9 的力矩峰值为 {{drive_d9_peak}}。",
         "j2 的最大反力为 {{joint_j1_force}}。", "驱动 d1 的力矩峰值为 {{drive_d1_peak}} N·m。", "{{joint_j2_force}} 大于 {{joint_j1_force}}。",
         "j2 的反力是所有运动副中最大的。", "驱动 d1 的力矩峰值出现在减速段。", "驱动 d1 的峰值主要来自惯性。", "驱动 d1 的力矩始终为负。",
         "约束残差（全部约束，含删掉的冗余约束）没有通过。", "所以驱动力矩满足要求。", "所以电机够用。", "计算考虑了关节摩擦。"]
RIGHT = ["驱动 d1 的力矩峰值为 {{drive_d1_peak}}，出现在加速段。", "驱动 d1 的力矩有正有负。", "驱动 d1 的峰值主要来自重力。",
         "驱动 d2 的力矩峰值为 {{drive_d2_peak}}，出现在加速段。", "驱动 d2 的力矩始终为正。", "驱动 d2 的峰值主要来自重力。",
         "j1 的反力是所有运动副中最大的，为 {{joint_j1_force}}。", "{{joint_j1_force}} 大于 {{joint_j2_force}}。",
         "驱动 d1 的峰值约为驱动 d2 的六倍。", "各项核查都通过。", "计算没有考虑摩擦。", "计算没有考虑阻尼。"]
HUMAN = "峰值偏大是因为连杆太长。"


@pytest.fixture(scope="module")
def ctx():
    data, _ = run_model(ARM)
    return data, R.facts(data), R.insight(ARM, data), R.model_names(data)


def _judge(ctx, text):
    _, F, I, names = ctx
    why = R.check_paragraph(text, F, names)
    if why:
        return "拦下", why
    return R.check_sentence(text, F, I, names)


@pytest.mark.parametrize("text", WRONG)
def test_wrong_blocked(ctx, text):
    assert _judge(ctx, text)[0] == "拦下", text


@pytest.mark.parametrize("text", RIGHT)
def test_right_passes(ctx, text):
    assert _judge(ctx, text)[0] == "通过", (text, _judge(ctx, text))


def test_causal_goes_to_human(ctx):
    assert _judge(ctx, HUMAN)[0] == "交人看"


class _Client:
    def __init__(self, paras):
        self.paras = paras

    def complete(self, req):
        return {"tool_input": {"paragraphs": self.paras}, "model": "test", "id": "t1"}


def test_explain_hides_failed_check():
    data, _ = run_model(ARM)
    data["verification"][0]["status"] = "fail"                # 假设约束残差不通过：解释里一句都没提，整份不用
    F = R.facts(data)
    ex = R.explain(data, F, _Client(["驱动 d1 的力矩峰值为 {{drive_d1_peak}}，出现在加速段。"]), mbd_model=ARM)
    assert ex["paragraphs"] == [] and "没写到" in ex["rejected"][0]["why"]
    name = data["verification"][0]["name"]
    ex = R.explain(data, F, _Client([f"驱动 d1 的力矩峰值为 {{{{drive_d1_peak}}}}，出现在加速段。{name}没有通过，须工程师复查。"]),
                   mbd_model=ARM)
    assert len(ex["paragraphs"]) == 1
