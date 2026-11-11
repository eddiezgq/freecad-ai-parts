"""第 130 轮第三批：列出枢纽、仿真写给页面的中文句子（句型），供英文句型表 src/locales/en_templates.json 对照。
做法：读 Python 源码（不运行），取含中文的字符串常量、f 字符串和 .format 模板；占位统一写成 {a} {b} …；
跳过：文档字符串、日志（log.* / print）、SQL、发给大模型的提示词、写进 ERPNext 的字段由各模块自己的英文名管。
用法：python3 factory/digital/web/tools/backend_texts.py [--json]   测试 tests/test_i18n.py 用它检查句型表没有缺口。"""
import ast
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIG = os.path.normpath(os.path.join(HERE, "..", ".."))
CJK = re.compile(r"[㐀-鿿]")
VARS = "abcdefghijklmnopqrstuvwxyz"
# 第三批：后端提示与记录（细则第八节）。工程软件、帮助与实验指导的模块不在这里（第四批）
MODULES = ["hub/ont/rules/*.py", "hub/ont/situation.py", "hub/ont/anomaly.py", "hub/ont/chain.py", "hub/ont/report.py",
           "hub/ont/actions.py", "hub/ont/plan.py", "hub/ont/notify.py", "hub/ont/mappers.py", "hub/ai.py", "hub/story.py", "hub/ehs.py", "hub/people.py", "hub/maint.py",
           "hub/energy.py", "hub/finance.py", "hub/supply.py", "hub/service.py", "hub/kpi.py", "hub/park.py",
           "hub/teach.py", "hub/lab[0-9]*.py", "sim/errors.py", "sim/engine.py", "sim/scenario.py", "hub/configurator.py",
           "twin/diagnose.py", "twin/field.py", "twin/models.py", "hub/rfield.py"]
# 第四批：工程软件（仿真与分析、运动与动力、数控编程、设计优化、流体、数字孪生、虚拟 PLC）给页面的提示与报错；生成 Word 文档的模块（labdoc、*report）属于第四批 b
MODULES += ["cae/__init__.py", "cae/cam.py", "cae/cam_geom.py", "cae/cam_job.py", "cae/cam_post.py", "cae/cam_power.py", "cae/cam_sim.py", "cae/cfd.py", "cae/cfd_bench.py", "cae/cfd_heat.py", "cae/cfd_natural.py", "cae/circuit.py", "cae/fatigue.py", "cae/foam.py", "cae/geometry.py", "cae/instruments.py", "cae/materials.py", "cae/mbd.py", "cae/mbd_models.py", "cae/mech_mjcf.py", "cae/modal.py", "cae/motors.py", "cae/optimize.py", "cae/service.py", "cae/solve.py", "cae/struct_parts.py", "cae/thermal.py", "cae/thermal_parts.py", "cae/topo.py", "cae/wqcr5.py", "cae/wqh1.py", "hub/accuracy.py", "hub/cae_ai.py", "hub/cae_api.py", "hub/cam_ai.py", "hub/cam_api.py", "hub/cfd_ai.py", "hub/cfd_api.py", "hub/design.py", "hub/design_sw_api.py", "hub/eto_design.py", "hub/fe2d.py", "hub/fixture.py", "hub/mbd_ai.py", "hub/opt_ai.py", "hub/opt_api.py", "hub/select.py", "hub/thermal_ai.py", "hub/twin.py", "hub/twin_ai.py", "hub/twin_api.py", "hub/vplc.py", "twin/__init__.py", "twin/diagnose.py", "twin/engine.py", "twin/field.py", "twin/models.py", "twin/robot.py", "twin/whatif.py", "vplc/__init__.py", "vplc/openplc_st.py", "vplc/runner.py"]
SKIP_CALL = re.compile(r"^(log|logger|logging|LOG)\b|\bprint$|\.(debug|info|warning|error|exception)$")
SQL = re.compile(r"\b(create table|select |insert into|alter table|update |delete from|on conflict)\b", re.I)
PROMPT = re.compile(r"^(你是|请把|把下面|现在是(教学|生产)模式，对方|工厂数据：)|只输出|JSON|<[a-z/]")
REGEX = re.compile(r"\\[dsSwW]|\|.*\|")      # 正则表达式（认中文问句用的），不是给人看的
FMT = re.compile(r"\{[^{}]*\}")


def _fmt_template(s):
    """'.format' / '%' 模板：{} {:.0%} {name} → {a} {b} …"""
    n = [0]

    def rep(m):
        v = VARS[min(n[0], 25)]
        n[0] += 1
        return "{" + v + "}"
    return FMT.sub(rep, s)


def _joined(node):
    out, n = [], 0
    for v in node.values:
        if isinstance(v, ast.Constant):
            out.append(str(v.value))
        else:
            out.append("{" + VARS[min(n, 25)] + "}")
            n += 1
    return "".join(out)


def _callname(f):
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return _callname(f.value) + "." + f.attr
    return ""


def texts(files=None):
    files = files or sorted({f for p in MODULES for f in glob.glob(os.path.join(DIG, p))})
    out = {}
    for f in files:
        tree = ast.parse(open(f, encoding="utf-8").read())
        skip = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body \
                    and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                skip.add(id(node.body[0].value))
            if isinstance(node, ast.Call) and SKIP_CALL.search(_callname(node.func)):
                for a in node.args:
                    for x in ast.walk(a):
                        skip.add(id(x))
            if isinstance(node, ast.JoinedStr):
                for x in node.values:
                    skip.add(id(x))
        for node in ast.walk(tree):
            if id(node) in skip:
                continue
            if isinstance(node, ast.JoinedStr):
                s = _joined(node)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                s = _fmt_template(node.value) if FMT.search(node.value) else node.value
            else:
                continue
            s = s.strip()
            if not CJK.search(s) or SQL.search(s) or PROMPT.search(s) or REGEX.search(s) or "\n" in s and len(s) > 300:
                continue
            out.setdefault(s, os.path.relpath(f, DIG))
    return out


YAMLS = ["ontology/*.yaml", "ontology/rules/*.yaml", "ontology/scenarios/*.yaml", "../plants/wenquest-*.yaml"]
YAML_SKIP_KEYS = {"fn", "sources", "key", "title", "do", "expect", "note", "workstation", "operation"}


def yaml_texts():
    """工厂本体（领域、对象、属性、关系、规则目录与预案）、情景剧本、各厂清单里给页面看的中文（清单里的名字归名字表）"""
    import yaml
    out = {}

    def walk(o, f, key=None):
        if isinstance(o, str):
            if CJK.search(o) and key not in YAML_SKIP_KEYS:
                out.setdefault(o.strip(), f)
        elif isinstance(o, dict):
            for k, v in o.items():
                if k in ("do", "expect"):
                    continue
                walk(v, f, k)
        elif isinstance(o, list):
            for v in o:
                walk(v, f, key)
    for p in YAMLS:
        for f in sorted(glob.glob(os.path.join(DIG, p))):
            rel = os.path.relpath(f, DIG)
            d = yaml.safe_load(open(f, encoding="utf-8")) or {}
            if rel.startswith(".."):     # 工厂清单：只取质量特性、检验与问题情景这类目录，名字归名字表
                d = {k: d[k] for k in ("measurements",) if k in d}
            walk(d, rel)
    return out


def errors():
    """各接口的报错（HTTPException 的 detail）：中文原文 → 文件。英文在 hub/i18n_en.json（细则 D-9）"""
    out = {}
    for f in sorted(glob.glob(os.path.join(DIG, "hub", "**", "*.py"), recursive=True)):
        tree = ast.parse(open(f, encoding="utf-8").read())
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "HTTPException"):
                continue
            for a in list(n.args[1:2]) + [k.value for k in n.keywords if k.arg == "detail"]:
                s = None
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    s = a.value
                elif isinstance(a, ast.JoinedStr):
                    s = _joined(a)
                elif isinstance(a, ast.Call) and isinstance(getattr(a.func, "value", None), ast.Constant) and getattr(a.func, "attr", "") == "format":
                    s = _fmt_template(a.func.value.value)
                if s and CJK.search(s):
                    out.setdefault(s.strip(), os.path.relpath(f, DIG))
    return out


if __name__ == "__main__":
    t = texts()
    if "--json" in sys.argv:
        print(json.dumps(t, ensure_ascii=False, indent=0))
    else:
        from collections import Counter
        c = Counter(t.values())
        print(len(t))
        for k, v in c.most_common():
            print(v, k)
