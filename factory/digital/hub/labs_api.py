# -*- coding: utf-8 -*-
"""第 19 轮 J-8：“实验与任务”一个入口——实验 7、15–23 的列表，每个写领域、学时、我的得分；进去还是原来的实验页（地址不变）。"""
import importlib

from fastapi import Depends

LABS = [
    {"no": 7, "title": "数字工厂闭环", "path": "/teach", "module": "teach", "domain": "订单到交付", "hours": 4},
    {"no": 15, "title": "车间异常的追因、推演与决策", "path": "/lab15", "module": "lab15", "domain": "厂情中枢", "hours": 4},
    {"no": 16, "title": "客户投诉的追溯、召回与服务决策", "path": "/lab16", "module": "lab16", "domain": "客户与服务", "hours": 4},
    {"no": 17, "title": "安全隐患的识别、评估与停机决策", "path": "/lab17", "module": "lab17", "domain": "安全环保", "hours": 4},
    {"no": 18, "title": "设备维护策略：保养时机的决策", "path": "/lab18", "module": "lab18", "domain": "设备维护", "hours": 4},
    {"no": 19, "title": "排班与技能：缺人时的决策", "path": "/lab19", "module": "lab19", "domain": "人员", "hours": 4},
    {"no": 20, "title": "供应链：来料不合格与供应商选择", "path": "/lab20", "module": "lab20", "domain": "采购与来料", "hours": 4},
    {"no": 21, "title": "能源：空转、错峰与单件碳足迹", "path": "/lab21", "module": "lab21", "domain": "能源与环境", "hours": 4},
    {"no": 22, "title": "经营：订单毛利、应收与现金", "path": "/lab22", "module": "lab22", "domain": "经营与财务", "hours": 4},
    {"no": 23, "title": "两周情景：一张急单的全厂决策", "path": "/lab23", "module": "lab23", "domain": "全厂（七个领域）", "hours": "2 周课程设计",
     "team": True},
    # 第 47 轮：机器人厂（清单 wenquest-robot）的实验；上面的只在演示工厂（减速器厂）
    {"no": 24, "title": "一台协作机器人从订单到交付", "path": "/lab24", "module": "lab24", "domain": "订单到交付（多层 BOM）", "hours": 4,
     "plant": "wenquest-robot"},
    {"no": 25, "title": "关节背隙异常的追因与 8D", "path": "/lab25", "module": "lab25", "domain": "质量（分层、8D）", "hours": 4,
     "plant": "wenquest-robot"},
]


def plant_id():
    from factory import plant as PLANT
    act = PLANT.active()
    return act["ID"] if act else None


def labs_here():
    """本厂的实验：演示工厂是实验 7、15–23；按清单起的厂只有写了 plant 的那几个"""
    pid = plant_id()
    return [lab for lab in LABS if lab.get("plant") == (pid if pid != "wenquest-gearbox" else None)]


def has_labs():
    return bool(labs_here())


def catalogue(db, user):
    rows = {r["task_id"]: r["score"] for r in db.q("select task_id, score from task_result where user_name=%s", (user,))}
    out = []
    for lab in labs_here():
        try:
            m = importlib.import_module("hub." + lab["module"])
            tasks = m.TASKS
            report = getattr(m, "REPORT_POINTS", 0)
        except (ImportError, AttributeError):
            continue
        ids = [t["id"] for t in tasks]
        got = [rows[i] for i in ids if i in rows]
        out.append(dict(lab, tasks=len(tasks), of=sum(t["points"] for t in tasks), report_points=report,
                        score=sum(got), started=bool(got) or ("l{}_start".format(lab["no"]) in rows),
                        done=sum(1 for t in tasks if rows.get(t["id"], 0) >= t["points"]),
                        guide="/api/cae/lab{}/guide.docx".format(lab["no"]) if lab["no"] >= 15 else None,
                        template="/api/cae/lab{}/report-template.docx".format(lab["no"]) if lab["no"] >= 15 else None))
    return out


def mount(app, H, user_of):
    @app.get("/api/labs")
    def labs(u=Depends(user_of)):
        return {"labs": catalogue(H.db, u["name"]), "teacher": bool(u.get("teacher")), "mode": u["mode"]}
