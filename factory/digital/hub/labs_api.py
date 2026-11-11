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
    # 第 139 轮 139h：按单设计（ETO）全流程——估算、报价接单、设计计划、车间质量、分期开票
    {"no": 33, "title": "一张非标订单：从询价到收款", "path": "/lab33", "module": "lab33", "domain": "订单与计划（按单设计）", "hours": 4},
    # 第 152 轮：演示工厂的质量追因与 8D（通用实现 hub/labq.py）
    {"no": 41, "title": "输出轴质量异常的追因与 8D", "path": "/labq/41", "module": "lab41", "domain": "质量（分层、8D）", "hours": 4},
    # 第 47 轮：机器人厂（清单 wenquest-robot）的实验；上面的只在演示工厂（减速器厂）
    {"no": 24, "title": "一台协作机器人从订单到交付", "path": "/lab24", "module": "lab24", "domain": "订单到交付（多层 BOM）", "hours": 4,
     "plant": "wenquest-robot"},
    {"no": 25, "title": "关节背隙异常的追因与 8D", "path": "/lab25", "module": "lab25", "domain": "质量（分层、8D）", "hours": 4,
     "plant": "wenquest-robot"},
    # 第 55 轮：整机运动学标定（《机器人学》第 13 章 DH、26.3 节最小二乘辨识）
    {"no": 26, "title": "一台协作机器人的运动学标定", "path": "/lab26", "module": "lab26", "domain": "质量（整机标定）", "hours": 4,
     "plant": "wenquest-robot"},
    # 第 57 轮：两厂之间的一张订单（工业园：机器人厂向问渠减速器厂采购 WQR-105）
    {"no": 27, "title": "两厂之间的一张订单", "path": "/lab27", "module": "lab27", "domain": "采购与来料（跨厂供应链）", "hours": 4,
     "plant": "wenquest-robot"},
    # 第 58 轮：负载跑合台上的仿真与实测对比（《机器人学》29.4 节仿真与现实、26.4 节摩擦辨识）
    {"no": 28, "title": "负载跑合台上的仿真与实测对比", "path": "/lab28", "module": "lab28", "domain": "质量（负载跑合）", "hours": 4,
     "plant": "wenquest-robot"},
    # 第 68 轮：一台机器人的售后追溯（现场报警 → 出厂档案 → 减速器批次 → 召回范围 → 派工 → 算账）
    {"no": 29, "title": "一台机器人的售后追溯", "path": "/lab29", "module": "lab29", "domain": "客户与服务（质量追溯）", "hours": 4,
     "plant": "wenquest-robot"},
    # 第 74 轮：一台轮式人形从订单到交付（整机里套整机、两种整机抢一个标定工位）
    {"no": 30, "title": "一台轮式人形从订单到交付", "path": "/lab30", "module": "lab30", "domain": "订单与计划（多层计划、产能）", "hours": 4,
     "plant": "wenquest-robot"},
    # 第 123 轮：关节终检抱闸报警的排查（驱动板 B 版故障 7：报警帧 → 线圈电流 → 坏件 → 处置 → 复测）
    {"no": 31, "title": "关节终检抱闸报警的排查", "path": "/lab31", "module": "lab31", "domain": "质量（终检与返修）", "hours": 4,
     "plant": "wenquest-robot"},
    # 第 141 轮：缝纫机厂（清单 wenquest-sewing）——铸件、机壳、轴的五种隐藏问题，照实验 25
    {"no": 32, "title": "机壳与关键零件质量异常的追因与 8D", "path": "/lab32", "module": "lab32", "domain": "质量（分层、8D）", "hours": 4,
     "plant": "wenquest-sewing"},
    # 第 147 轮：电机厂、传感器厂的质量追因与 8D（通用实现 hub/labq.py）
    {"no": 35, "title": "电机质量异常的追因与 8D", "path": "/labq/35", "module": "lab35", "domain": "质量（分层、8D）", "hours": 4,
     "plant": "wenquest-motor"},
    {"no": 36, "title": "编码器与扭矩传感器质量异常的追因与 8D", "path": "/labq/36", "module": "lab36", "domain": "质量（分层、8D）", "hours": 4,
     "plant": "wenquest-sensor"},
    # 第 148 轮：电路板厂、芯片封测厂的质量追因与 8D（同一个通用实现）
    {"no": 37, "title": "驱动板质量异常的追因与 8D", "path": "/labq/37", "module": "lab37", "domain": "质量（分层、8D）", "hours": 4,
     "plant": "wenquest-pcb"},
    {"no": 38, "title": "芯片封测质量异常的追因与 8D", "path": "/labq/38", "module": "lab38", "domain": "质量（分层、8D）", "hours": 4,
     "plant": "wenquest-chip"},
    # 第 149 轮：电路板厂、芯片封测厂的“从订单到交付”（通用实现 hub/labo.py，照实验 24、34）
    {"no": 39, "title": "一块驱动板从订单到交付", "path": "/labo/39", "module": "lab39", "domain": "订单到交付（多层 BOM）", "hours": 4,
     "plant": "wenquest-pcb"},
    {"no": 40, "title": "一批芯片从订单到交付", "path": "/labo/40", "module": "lab40", "domain": "订单到交付（多层 BOM）", "hours": 4,
     "plant": "wenquest-chip"},
    # 第 153 轮：电机厂、传感器厂的“从订单到交付”（物料清单一层，任务 2 看工艺路线）
    {"no": 42, "title": "一台伺服电机从订单到交付", "path": "/labo/42", "module": "lab42", "domain": "订单到交付（工艺路线）", "hours": 4,
     "plant": "wenquest-motor"},
    {"no": 43, "title": "一只扭矩传感器从订单到交付", "path": "/labo/43", "module": "lab43", "domain": "订单到交付（工艺路线）", "hours": 4,
     "plant": "wenquest-sensor"},
    # 第 145 轮：缝纫机厂一台平缝机从订单到交付，照实验 24
    {"no": 34, "title": "一台平缝机从订单到交付", "path": "/lab34", "module": "lab34", "domain": "订单到交付（多层 BOM）", "hours": 4,
     "plant": "wenquest-sewing"},
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
