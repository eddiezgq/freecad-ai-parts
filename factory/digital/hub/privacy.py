# -*- coding: utf-8 -*-
"""总线上不出现姓名（第 4 轮 C5）。

浏览器可以匿名只读总线（第 3 轮 D5），所以线上版（问渠账号登录）发到总线的消息里，操作人一律写成
“角色·匿名编号”，如 planner·a7f3。匿名编号由姓名（含账号编号）经 HMAC 算出：同一个人始终相同，
从编号看不出是谁；评分时用同一函数算出本人的编号来对。本地版（填名字登录）照旧写姓名。
"""
import hashlib
import hmac
import os

_KEY = (os.environ.get("WQ_SECRET") or "wq-local").encode()


def anonymous():
    return os.environ.get("WQ_AUTH", "local") == "wenquest"


def pseudo(name):
    return hmac.new(_KEY, str(name).encode(), hashlib.sha256).hexdigest()[:4]


def actor(name, role=None):
    """总线上代表这个人的写法。"""
    if not anonymous() or not name or name in ("system", "ai"):
        return name
    return "{}·{}".format(role or "user", pseudo(name))


def is_me(value, name):
    """总线上的一个操作人字段是否就是这个人（本地版比姓名，线上版比匿名编号）。"""
    if not value:
        return False
    return value == name or str(value).endswith("·" + pseudo(name))
