"""问渠有限元的中英两种语言（ADR-0096 第 3 步）：代码里每句显示给人的中文都有英文；英文模板的字段个数对得上；翻译规则。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from assist import i18n

ROOT = Path(__file__).resolve().parents[1]
MODULES = sorted([*ROOT.glob("analysis/fea/*.py"), ROOT / "assist/fea_report.py", ROOT / "assist/fea_draft.py",
                  ROOT / "assist/features.py", ROOT / "freecad_addon/fc/fem_flow.py", ROOT / "freecad_addon/fc/fem_bridge.py",
                  ROOT / "freecad_addon/fc/fem_results.py", ROOT / "freecad_addon/gui/fem_commands.py",
                  ROOT / "freecad_addon/gui/fea_panel.py", ROOT / "assist/fea_edition.py",
                  ROOT / "freecad_addon/gui/fea_brand.py", ROOT / "licensing/license.py", ROOT / "licensing/runtime.py",
                  # 问渠多体动力学（ADR-0102 第 2 步）
                  *ROOT.glob("analysis/mbd/dae/*.py"), ROOT / "analysis/mbd/assembly.py", ROOT / "analysis/mbd/mates.py",
                  ROOT / "analysis/mbd/flexsolid.py", ROOT / "analysis/mbd/flexview.py", ROOT / "analysis/mbd/study.py",
                  ROOT / "analysis/mbd/loads.py", ROOT / "assist/mbd_report.py", ROOT / "assist/mbd_mates.py",
                  ROOT / "freecad_addon/core/mbd_study.py", *ROOT.glob("freecad_addon/fc/mbd_*.py"),
                  ROOT / "freecad_addon/gui/mbd_assembly_panel.py", ROOT / "assist/mbd_edition.py",
                  ROOT / "freecad_addon/gui/mbd_brand.py"])
EXTRA = {"零件的温度场、热应力（本机 CalculiX）；按 FEM 分析的计算结果和载荷谱算疲劳寿命。强度、固有频率请在 FEM 工作台里“一句话起草 / 计算并核查 / 出报告”"}
# 工作台其他命令不属于问渠有限元，只收“热分析 · 疲劳”这一条的说明


def _templates(path: Path) -> list[str]:
    """一个文件里所有含中文的字符串常量与 f-string（f-string 的 {…} 写成 {}；文档字符串不算）"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs, parents, out = set(), {}, []
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
            docs.add(id(n.body[0].value))
        for c in ast.iter_child_nodes(n):
            parents[id(c)] = n
    for n in ast.walk(tree):
        if id(n) in docs or (isinstance(n, ast.Constant) and isinstance(parents.get(id(n)), ast.JoinedStr)):
            continue
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            s = n.value
        elif isinstance(n, ast.JoinedStr):
            s = "".join(v.value.replace("{", "{{").replace("}", "}}") if isinstance(v, ast.Constant) else "{}" for v in n.values)
        else:
            continue
        if i18n.has_cjk(s):
            out.append(s)
    return out


def _en() -> dict:
    return json.loads((ROOT / "assist/i18n/en.json").read_text(encoding="utf-8"))


def test_every_displayed_chinese_text_has_english():
    en = _en()
    skip = set(json.loads((ROOT / "assist/i18n/skip.json").read_text(encoding="utf-8"))["skip"])
    missing = sorted({f"{p.relative_to(ROOT)}: {s!r}" for p in MODULES for s in _templates(p) if s not in en and s not in skip})
    assert not missing, "这些中文没有英文（加进 assist/i18n/en.json）：\n" + "\n".join(missing)


def test_english_templates_have_the_same_fields():
    for zh, en in _en().items():
        a, b = i18n._parse(zh)[1], i18n._parse(en)[1]
        assert len(a) == len(b), (zh, en)
        assert not i18n.has_cjk(en), (zh, en)
        assert {x for x in b if x} <= {x for x in a if x}, (zh, en)


def test_no_stale_entries():
    used = {s for p in MODULES for s in _templates(p)} | EXTRA
    stale = [k for k in _en() if k not in used]
    assert not stale, "对照表里有代码中已经没有的条目（删掉）：" + "；".join(stale)


@pytest.mark.parametrize("zh,en", [
    ("网格误差估计 2.1 %（≤ 5 %）", "Estimated mesh error 2.1 % (≤ 5 %)"),
    ("可信度核查没有通过（结论：不通过），不给安全系数", "The trust check did not pass (verdict: fail); no safety factor is given"),
    ("安全系数 2.5（按屈服强度 355 MPa）。", "Safety factor 2.5 (based on yield strength 355 MPa)."),
    ("所取 6 阶在激励方向的有效质量占 92 %，超过 5 %：加阶数",
     "The 6 modes included carry 92 % of the effective mass in the excitation direction, more than 5 %: include more modes"),
    ("外载与支承反力相抵；没有网格质量数据", "External loads are balanced by the support reactions; no mesh quality data"),
])
def test_translation_rules(zh, en):
    assert i18n.t(zh) == en
    assert i18n.t(zh, "zh") == zh


def test_user_text_is_kept():
    """用户写的话（原话引用、零件名）对不上表就原样保留"""
    assert i18n.t("肩部 Ø138 减速器座固定") == "肩部 Ø138 减速器座固定"
    assert i18n.t("Shoulder seat fixed") == "Shoulder seat fixed"


def test_language_setting(monkeypatch):
    monkeypatch.setenv("FAP_LANG", "en")
    assert i18n.lang() == "en" and i18n.tr("网格质量") == "Mesh quality"
    monkeypatch.setenv("FAP_LANG", "zh")
    assert i18n.tr("网格质量") == "网格质量"
