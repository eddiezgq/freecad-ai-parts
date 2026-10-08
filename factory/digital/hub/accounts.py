# -*- coding: utf-8 -*-
"""企业账号（本仓库 ADR-0063）：WQ_AUTH=enterprise 时用户名 + 密码登录，与问渠学习平台无关。

- 密码加盐慢哈希（scrypt），库里不存明文；连续输错 5 次锁 10 分钟
- 管理员（admin）可用全部角色和生产模式，在工作台“账号与角色”加人、分配角色、重置密码、停用；
  普通账号只能用分给他的角色（生产模式），教学模式按学生岗位
- 改密码、停用后旧凭证立即失效（凭证里带密码版本号，每次请求核对，结果缓存 30 秒）
- 第一个管理员：安装脚本运行 `python -m hub.accounts create-admin 用户名`（密码从标准输入读），
  或启动时环境变量 WQ_ADMIN_USER / WQ_ADMIN_PASSWORD（只在还没有任何账号时用）
"""
import hashlib
import hmac
import os
import re
import secrets
import time

SCHEMA = """
create table if not exists fap_account (
  username text primary key, name text not null, pw_hash text not null, roles text[] not null default '{}',
  admin boolean not null default false, active boolean not null default true, pw_ver int not null default 1,
  failed int not null default 0, locked_until timestamptz, created_at timestamptz default now(),
  created_by text, last_login timestamptz)
"""
ROLES = ("planner", "engineer", "operator", "quality", "manager", "approver", "sales")
USER_RE = re.compile(r"^[A-Za-z0-9_.@-]{2,40}$")
MAX_FAILED, LOCK_S = 5, 600
_CACHE = {}          # username → (到期时间, active, pw_ver)


class AccountError(ValueError):
    pass


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1${}${}".format(salt.hex(), h.hex())


def check_pw(pw, stored):
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(h) // 2)
        return hmac.compare_digest(got.hex(), h)
    except (ValueError, TypeError):
        return False


def _valid_pw(pw):
    if not isinstance(pw, str) or len(pw) < 10:
        raise AccountError("密码至少 10 位")
    if pw.isdigit() or pw.isalpha():
        raise AccountError("密码要同时有字母和数字（或符号）")


def init(db):
    db.x(SCHEMA)
    u, p = os.environ.get("WQ_ADMIN_USER", "").strip(), os.environ.get("WQ_ADMIN_PASSWORD", "")
    if u and p and not db.one("select 1 as x from fap_account limit 1"):
        create(db, u, p, name=u, admin=True, by="安装")


def create(db, username, password, name=None, roles=(), admin=False, by=None):
    username = str(username or "").strip()
    if not USER_RE.match(username):
        raise AccountError("用户名 2–40 位，只能用字母、数字和 _ . @ -")
    _valid_pw(password)
    roles = [r for r in roles or [] if r in ROLES]
    if not admin and not roles:
        raise AccountError("普通账号至少分一个角色")
    if db.one("select 1 as x from fap_account where username=%s", (username,)):
        raise AccountError("用户名已存在")
    db.x("insert into fap_account (username, name, pw_hash, roles, admin, created_by) values (%s,%s,%s,%s,%s,%s)",
         (username, (name or username)[:40], hash_pw(password), roles, bool(admin), by))
    return get(db, username)


def get(db, username):
    r = db.one("select username, name, roles, admin, active, pw_ver, last_login, created_at, created_by, "
               "locked_until from fap_account where username=%s", (username,))
    return dict(r) if r else None


def listing(db):
    return [dict(r) for r in db.q("select username, name, roles, admin, active, last_login, created_at, created_by "
                                  "from fap_account order by admin desc, username")]


def update(db, username, *, name=None, roles=None, admin=None, active=None, by=None):
    a = get(db, username)
    if not a:
        raise AccountError("没有这个账号")
    if roles is not None:
        roles = [r for r in roles if r in ROLES]
    new_admin = a["admin"] if admin is None else bool(admin)
    new_active = a["active"] if active is None else bool(active)
    if a["admin"] and (not new_admin or not new_active) and _admins(db) <= 1:
        raise AccountError("至少要留一个能用的管理员")
    if not new_admin and not (roles if roles is not None else a["roles"]):
        raise AccountError("普通账号至少分一个角色")
    db.x("update fap_account set name=coalesce(%s, name), roles=coalesce(%s, roles), admin=%s, active=%s, "
         "pw_ver = pw_ver + case when %s then 1 else 0 end where username=%s",
         (name[:40] if name else None, roles, new_admin, new_active, not new_active and a["active"], username))
    _CACHE.pop(username, None)
    return get(db, username)


def set_password(db, username, new, old=None):
    """old 给了就核对（本人改）；管理员重置不给 old。改完旧凭证失效、解锁。"""
    r = db.one("select pw_hash from fap_account where username=%s", (username,))
    if not r:
        raise AccountError("没有这个账号")
    if old is not None and not check_pw(old, r["pw_hash"]):
        raise AccountError("原密码不对")
    _valid_pw(new)
    db.x("update fap_account set pw_hash=%s, pw_ver=pw_ver+1, failed=0, locked_until=null where username=%s",
         (hash_pw(new), username))
    _CACHE.pop(username, None)


def _admins(db):
    return db.one("select count(*) as n from fap_account where admin and active")["n"]


def authenticate(db, username, password):
    """成功返回账号；失败抛 AccountError（不区分“没有这个人”与“密码错”）。"""
    a = db.one("select username, name, pw_hash, roles, admin, active, pw_ver, failed, locked_until "
               "from fap_account where username=%s", (str(username or "").strip(),))
    if a and a["locked_until"] and a["locked_until"].timestamp() > time.time():
        raise AccountError("密码输错太多次，{} 分钟后再试".format(int((a["locked_until"].timestamp() - time.time()) // 60) + 1))
    if not a or not a["active"] or not check_pw(password or "", a["pw_hash"]):
        if a:
            db.x("update fap_account set failed=failed+1, locked_until = case when failed+1 >= %s "
                 "then now() + make_interval(secs => %s) else locked_until end where username=%s",
                 (MAX_FAILED, LOCK_S, a["username"]))
        raise AccountError("用户名或密码不对" if not a or a["active"] else "账号已停用，请找管理员")
    db.x("update fap_account set failed=0, locked_until=null, last_login=now() where username=%s", (a["username"],))
    return {k: a[k] for k in ("username", "name", "roles", "admin", "pw_ver")}


def still_valid(db, username, pw_ver):
    """凭证是否仍有效（账号在用、密码没改过）；结果缓存 30 秒。"""
    now = time.time()
    c = _CACHE.get(username)
    if not c or c[0] < now:
        r = db.one("select active, pw_ver from fap_account where username=%s", (username,))
        c = (now + 30, bool(r and r["active"]), r["pw_ver"] if r else -1)
        _CACHE[username] = c
    return c[1] and c[2] == pw_ver


def main(argv=None):
    """安装脚本用：python -m hub.accounts create-admin 用户名 [姓名]（密码从标准输入读一行）"""
    import argparse
    import sys

    from hub.db import DB

    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["create-admin", "reset-password"])
    ap.add_argument("username")
    ap.add_argument("name", nargs="?")
    a = ap.parse_args(argv)
    pw = sys.stdin.readline().rstrip("\n")
    db = DB()
    db.init()
    db.x(SCHEMA)
    try:
        if a.cmd == "create-admin":
            create(db, a.username, pw, name=a.name or a.username, admin=True, by="安装")
        else:
            set_password(db, a.username, pw)
    except AccountError as e:
        print("没有完成：", e, file=sys.stderr)
        return 1
    print("完成：", a.cmd, a.username)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
