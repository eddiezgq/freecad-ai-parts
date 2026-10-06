# -*- coding: utf-8 -*-
"""ERPNext 单点登录（数字工厂第 7 轮）：枢纽当 OAuth2 授权方，ERPNext 用自带的“社交登录”（自定义提供方 wenquest）接入。

流程：ERPNext 登录页（网站脚本自动点“Login with WenQuest”）→ 枢纽 /api/oauth/authorize 核对问渠账号、
在 ERPNext 里建好/更新账号与角色 → 带一次性授权码回到 ERPNext → ERPNext 服务器用授权码和密钥换令牌
（/api/oauth/token）→ 取用户信息（/api/oauth/userinfo）→ 以该账号登录。
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.parse

CLIENT_ID = "wenquest-erp"
PROVIDER = "wenquest"                         # ERPNext 里 Social Login Key 的名字（provider_name WenQuest → wenquest）
CALLBACK_PATH = "/api/method/frappe.integrations.oauth2_logins.custom/" + PROVIDER
CODE_TTL = 120
TOKEN_TTL = 300

STUDENT_ROLE = "WQ Student (Read Only)"
TEACHER_ROLES = ["Manufacturing Manager", "Manufacturing User", "Stock Manager", "Stock User", "Purchase Manager",
                 "Purchase User", "Sales Manager", "Sales User", "Quality Manager", "Item Manager", "Accounts User"]
# 学生只读角色能查看的单据（seed.py 给这些单据加“只读”权限）
STUDENT_READ_DOCTYPES = ["Item", "Item Group", "BOM", "Routing", "Operation", "Workstation", "Work Order", "Job Card",
                         "Sales Order", "Customer", "Supplier", "Material Request", "Purchase Order", "Stock Entry",
                         "Stock Ledger Entry", "Bin", "Warehouse", "Quality Inspection", "Quality Inspection Template",
                         "Delivery Note", "Purchase Receipt", "UOM", "Company"]


def config():
    erp_public = os.environ.get("WQ_ERPNEXT_URL", "http://localhost:8090").rstrip("/")
    host = urllib.parse.urlsplit(erp_public).hostname or "localhost"
    return {
        "secret": os.environ.get("WQ_ERP_OAUTH_SECRET", ""),
        "erp_public": erp_public,
        "erp_api": os.environ.get("WQ_ERPNEXT_API", "").rstrip("/"),
        "api_key": os.environ.get("WQ_ERP_API_KEY", ""),
        "api_secret": os.environ.get("WQ_ERP_API_SECRET", ""),
        "user_domain": os.environ.get("WQ_ERP_USER_DOMAIN") or "users." + (host[4:] if host.startswith("erp.") else host),
    }


def enabled():
    c = config()
    return bool(c["secret"] and c["erp_api"] and c["api_key"])


# ---------------------------------------------------------------- 身份 → ERPNext 账号
def erp_identity(person, user_domain):
    """person: {uid, name, teacher} → ERPNext 账号信息"""
    uid = str(person["uid"])
    return {"sub": "wq-" + uid, "email": "wq{}@{}".format(uid, user_domain).lower(), "email_verified": True,
            "name": person["name"], "given_name": person["name"], "teacher": bool(person["teacher"]),
            "roles": list(TEACHER_ROLES) if person["teacher"] else [STUDENT_ROLE]}


def local_uid(name):
    """本地登录（没有问渠账号）时，按姓名得到稳定的编号"""
    return "local-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:10]


def provision(ident, session=None):
    """在 ERPNext 里建好或更新这个人的账号：系统用户、启用、按身份重设角色"""
    import requests
    c = config()
    s = session or requests.Session()
    h = {"Authorization": "token {}:{}".format(c["api_key"], c["api_secret"]), "Accept": "application/json"}
    url = "{}/api/resource/User/{}".format(c["erp_api"], urllib.parse.quote(ident["email"], safe=""))
    r = s.get("{}/api/resource/Role".format(c["erp_api"]), headers=h, timeout=20,
              params={"filters": json.dumps([["name", "in", ident["roles"]]]), "limit_page_length": 0})
    r.raise_for_status()
    have = {x["name"] for x in r.json().get("data", [])}
    roles = [x for x in ident["roles"] if x in have]          # 只给 ERPNext 里确实有的角色（版本不同，角色名可能有出入）
    doc = {"first_name": ident["name"][:60], "user_type": "System User", "enabled": 1,
           "roles": [{"role": x} for x in roles]}
    r = s.get(url, headers=h, timeout=20)
    if r.status_code == 404:
        doc.update({"email": ident["email"], "send_welcome_email": 0})
        r = s.post("{}/api/resource/User".format(c["erp_api"]), headers=h, json=doc, timeout=30)
    else:
        r.raise_for_status()
        r = s.put(url, headers=h, json=doc, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError("ERPNext 建账号失败（{}）：{}".format(r.status_code, r.text[:300]))


# ---------------------------------------------------------------- 授权码与令牌
class Codes:
    """一次性授权码（内存里，2 分钟有效）"""

    def __init__(self):
        self._d, self._lock = {}, threading.Lock()

    def issue(self, ident, redirect_uri, now=None):
        now = time.time() if now is None else now
        code = secrets.token_urlsafe(32)
        with self._lock:
            self._d = {k: v for k, v in self._d.items() if v[2] > now}
            self._d[code] = (ident, redirect_uri, now + CODE_TTL)
        return code

    def take(self, code, redirect_uri, now=None):
        now = time.time() if now is None else now
        with self._lock:
            v = self._d.pop(code, None)
        if not v or v[2] < now or v[1] != redirect_uri:
            return None
        return v[0]


def _b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def sign_token(ident, key, now=None):
    body = dict(ident, exp=int((time.time() if now is None else now) + TOKEN_TTL))
    raw = _b64(json.dumps(body, ensure_ascii=False).encode("utf-8"))
    return raw + "." + hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()


def read_token(tok, key, now=None):
    try:
        raw, sig = tok.split(".")
        if not hmac.compare_digest(sig, hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()):
            return None
        body = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        return body if body.get("exp", 0) > (time.time() if now is None else now) else None
    except Exception:  # noqa: BLE001
        return None


def valid_redirect(uri):
    return uri == config()["erp_public"] + CALLBACK_PATH


def check_client(client_id, client_secret):
    c = config()
    return client_id == CLIENT_ID and bool(c["secret"]) and hmac.compare_digest(client_secret or "", c["secret"])


def login_request(redirect_to="", session=None):
    """向 ERPNext 登录页（内部地址）要“用问渠账号登录”的链接，取出其中的 state 和回调地址。
    ERPNext 只按 state 在缓存里认这次登录请求，不绑浏览器，所以枢纽可以替浏览器要。"""
    import re
    import requests
    c = config()
    s = session or requests.Session()
    r = s.get(c["erp_api"] + "/login", params={"redirect-to": redirect_to} if redirect_to else None, timeout=20)
    r.raise_for_status()
    m = re.search(r'href="([^"]+)"\s+class="[^"]*btn-' + PROVIDER, r.text)
    if not m:
        raise RuntimeError("ERPNext 登录页上没有“用问渠账号登录”（单点登录还没配置好）")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(m.group(1).replace("&amp;", "&")).query))
    if not valid_redirect(q.get("redirect_uri", "")) or not q.get("state"):
        raise RuntimeError("ERPNext 登录链接不合规范：{}".format(q.get("redirect_uri")))
    return {"state": q["state"], "redirect_uri": q["redirect_uri"]}


# ---------------------------------------------------------------- ERPNext 登录页上的自动跳转脚本（seed.py 写入 Website Script）
AUTO_LOGIN_JS = """// 问渠单点登录（数字工厂第 7 轮）：登录页自动点“Login with WenQuest”；管理员用密码登录请打开 /login?manual=1
(function () {
  if (location.pathname !== '/login' || /[?&]manual=1/.test(location.search)) return;
  function go() {
    var a = document.querySelector('a.btn-wenquest');
    if (!a) return;
    var last = 0;
    try { last = +sessionStorage.getItem('wq_sso_try') || 0; sessionStorage.setItem('wq_sso_try', String(Date.now())); } catch (e) {}
    if (Date.now() - last < 15000) return;          // 15 秒内已经自动跳过一次：不再循环，留在登录页
    location.href = a.href;
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go); else go();
})();"""
