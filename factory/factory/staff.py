# -*- coding: utf-8 -*-
"""员工、技能矩阵、固定岗位（第 61 轮）：清单写了产品的厂（机器人厂等）打开“安全环保、人员排班”时，按车间设备生成一套**示例**人员
（全部虚构人名），只排白班。演示工厂（减速器厂）不走这里：它的 30 人在 hub/ehs.py、hub/people.py 里原样不动。

规则（确定性，同一份清单每次一样）：
- 设备按类别分三个班组：机加（锯、车、加工中心、磨、通用）、装配、测试标定（测量、测试台、标定、跑合台、调试场地）；
- 每台“要有人”的设备（自动测试台、跑合台除外）一名主操，熟练（2 级），固定在这台的白班岗位上；
- 每个班组一名班组长：本组第一台可带徒（3 级），本组其余设备熟练（2 级）——**标定工位除外**（教学点：标定只有主操一个人会，第 61 轮 H-4）；
- 机加、装配各一名学徒（1 级，本组前两台）；设备组 2 名维修工、安环部 1 名安全员、计划物流 1 名计划员、1 名仓管员。
只做查表，不联网、不读数据库。"""
from factory import equip

NAMES = ["林涛", "苏婉", "方毅", "谢晨", "程远", "江月", "邹凯", "白雪", "龚明", "严霜", "史航", "陶然", "温岚", "贺川", "姜禾",
         "范悦", "汤铭", "尹航", "金露", "段鹏", "雷蕾", "侯斌", "秦朗", "薛琪", "傅强", "崔颖", "施亮", "卢璐"]
FEMALE_NAMES = {"苏婉", "江月", "白雪", "严霜", "温岚", "姜禾", "范悦", "金露", "雷蕾", "薛琪", "崔颖", "卢璐"}
GROUP = {"saw": "机加班", "lathe": "机加班", "mc": "机加班", "grinder": "机加班", "general": "机加班", "assembly": "装配班",
         "cmm": "测试标定", "bench": "测试标定", "calib": "测试标定", "runin": "测试标定", "agvtest": "测试标定"}
GROUP_EN = {"机加班": "Machining crew", "装配班": "Assembly crew", "测试标定": "Test & calibration", "设备组": "Maintenance",
            "安环部": "EHS", "计划物流": "Planning & logistics"}
OPERATOR_POST = {"机加班": "操作工", "装配班": "装配工", "测试标定": "操作工"}


def plan(eq):
    """eq：factory.equip.profiles() 的结果。返回 {people: [(工号, 姓名, 岗位, 部门)], skills: {工号: {设备: 等级}},
    posts: {("day", 设备): 工号}, needs: (要有人的设备…), depts: [(部门, 英文)], female: {工号}, single: 设备或 None}"""
    groups = {}
    for u, d in eq.items():
        groups.setdefault(GROUP.get(d["kind"], "机加班"), []).append(u)
    needs = tuple(u for u, d in eq.items() if d["kind"] not in equip.STAFFED_EXCEPT)
    people, skills, posts = [], {}, {}
    names = iter(NAMES)

    def add(post, dept):
        pid = "R{:02d}".format(len(people) + 1)
        people.append((pid, next(names), post, dept))
        return pid

    order = [g for g in ("机加班", "装配班", "测试标定") if g in groups]
    for g in order:
        us = groups[g]
        lead = add("班组长", g)
        skills[lead] = {}
        for i, u in enumerate(us):
            if eq[u]["kind"] == "calib":
                continue
            skills[lead][u] = 3 if i == 0 else 2
        for u in us:
            if u not in needs:
                continue
            pid = add(OPERATOR_POST[g], g)
            skills[pid] = {u: 2}
            posts[("day", u)] = pid
        if g in ("机加班", "装配班") and us:
            pid = add("学徒", g)
            skills[pid] = {u: 1 for u in [x for x in us if x in needs][:2]}
    for _ in range(2):
        add("维修工", "设备组")
    add("安全员", "安环部")
    add("计划员", "计划物流")
    add("仓管员", "计划物流")
    depts = [(g, GROUP_EN[g]) for g in order] + [(g, GROUP_EN[g]) for g in ("设备组", "安环部", "计划物流")]
    single = next((u for u in needs if eq[u]["kind"] == "calib"), None)
    return {"people": people, "skills": {k: v for k, v in skills.items() if v}, "posts": posts, "needs": needs, "depts": depts,
            "female": {p[0] for p in people if p[1] in FEMALE_NAMES}, "single": single}


def active():
    eq = equip.active()
    return plan(eq) if eq else None
