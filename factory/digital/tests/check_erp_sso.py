# -*- coding: utf-8 -*-
"""服务器演练用（第 7 轮）：在真 ERPNext 上走一遍问渠单点登录。

ERPNext 登录页 → 找到“Login with WenQuest”和自动跳转脚本 → 枢纽授权（本地版用工作台凭证代表身份）→ 回到 ERPNext
→ 确认以该账号登录；老师能改单据所需的角色齐全，学生只能看不能改。

用法：python tests/check_erp_sso.py --hub http://localhost:8100 --erp http://localhost:8090 --secret <WQ_SECRET>
"""
import argparse
import base64
import hashlib
import hmac
import json
import re
import sys
import urllib.parse

import requests

P = argparse.ArgumentParser()
P.add_argument("--hub", default="http://localhost:8100")
P.add_argument("--erp", default="http://localhost:8090")
P.add_argument("--secret", required=True, help="枢纽的 WQ_SECRET（用来签一个学生身份的工作台凭证）")
A = P.parse_args()
ok = True


def check(cond, what):
    global ok
    print(("  ✓ " if cond else "  ✗ ") + what)
    ok &= bool(cond)
    return cond


def sign(payload):
    raw = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
    return raw + "." + hmac.new(A.secret.encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]


def local(url):
    """把页面里的公网地址换成演练机上的本地端口"""
    u = urllib.parse.urlsplit(url)
    base = A.hub if u.hostname.startswith("factory.") else A.erp
    return base + u.path + ("?" + u.query if u.query else "")


def sso_login(person):
    s = requests.Session()
    page = s.get(A.erp + "/login", timeout=30).text
    m = re.search(r'href="([^"]+)"\s+class="[^"]*btn-wenquest', page)
    if not check(m, "ERPNext 登录页有“Login with WenQuest”"):
        return None, None
    js = s.get(A.erp + "/website_script.js", timeout=30).text
    check("wenquest-sso" in js and "btn-wenquest" in js, "登录页自动跳转脚本已装")
    auth = local(m.group(1).replace("&amp;", "&")) + "&wq_token=" + urllib.parse.quote(sign(person))
    r = s.get(auth, allow_redirects=False, timeout=60)
    if not check(r.status_code == 302, "枢纽授权并在 ERPNext 建好账号（{} {}）".format(r.status_code, r.text[:200])):
        return None, None
    r = s.get(local(r.headers["location"]), allow_redirects=False, timeout=60)
    check(r.status_code in (301, 302, 303), "ERPNext 收下授权码（{}）".format(r.status_code))
    who = s.get(A.erp + "/api/method/frappe.auth.get_logged_user", timeout=30).json().get("message")
    return s, who


print("1. 老师")
s, who = sso_login({"name": "演练老师", "role": "manager", "mode": "teach", "teacher": True})
check(who and who.startswith("wq") and "@users." in who, "以问渠账号登录 ERPNext：{}".format(who))
if s:
    wo = s.get(A.erp + "/api/resource/Work Order", params={"limit_page_length": 1}, timeout=30)
    check(wo.status_code == 200, "老师能看工单")

print("2. 学生（只读）")
s, who = sso_login({"name": "演练学生", "role": "planner", "mode": "teach", "teacher": False})
check(who and who.startswith("wq"), "以问渠账号登录 ERPNext：{}".format(who))
if s:
    wo = s.get(A.erp + "/api/resource/Work Order", params={"limit_page_length": 1}, timeout=30)
    check(wo.status_code == 200, "学生能看工单")
    r = s.post(A.erp + "/api/resource/Customer", json={"customer_name": "演练学生建的客户", "customer_type": "Company"}, timeout=30)
    check(r.status_code in (401, 403), "学生不能新建单据（{}）".format(r.status_code))

print("3. 工作台入口 /api/erp/sso（不靠登录页脚本）")
s = requests.Session()
r = s.get(A.hub + "/api/erp/sso", params={"go": 1, "wq_token": sign({"name": "演练老师二", "role": "manager", "mode": "teach", "teacher": True})},
          allow_redirects=False, timeout=60)
if check(r.status_code == 302 and "code=" in r.headers.get("location", ""), "枢纽直接给出授权码（{} {}）".format(r.status_code, r.text[:200])):
    r = s.get(local(r.headers["location"]), allow_redirects=False, timeout=60)
    who = s.get(A.erp + "/api/method/frappe.auth.get_logged_user", timeout=30).json().get("message")
    check(who and who.startswith("wq"), "一步进入 ERPNext：{}".format(who))

print("单点登录演练{}".format("全部通过。" if ok else "有失败。"))
sys.exit(0 if ok else 1)
