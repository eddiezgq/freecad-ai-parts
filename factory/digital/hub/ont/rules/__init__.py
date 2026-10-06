# -*- coding: utf-8 -*-
"""规则库的检测函数（第 17 轮 B 期）。

每个函数 f(c, p, r) → [Finding]：c 是这一轮的共享数据（anomaly.Ctx），p 是阈值参数，r 是规则目录里的这一条。
函数只读、不写库；用 @rule("名字") 登记，名字写在 digital/ontology/rules/<领域>.yaml 的 fn 里。"""
REG = {}


def rule(name):
    def deco(f):
        if name in REG:
            raise ValueError("检测函数重名：" + name)
        REG[name] = f
        return f
    return deco


from hub.ont.rules import production, quality, sales, supply, service, maintenance, finance, product  # noqa: E402,F401
