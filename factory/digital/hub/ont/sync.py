# -*- coding: utf-8 -*-
"""同步器：总线历史 → 本体（增量，按 bus_message.seq 游标），加不在总线上的来源定时对账；可从头重放。

一致性：游标、上下文（当前刀具序号、未闭合停机……）和对象写入在同一个事务里提交；
只读 2 秒前入库的消息，避免并发写入时序号“先大后小”漏读。"""
import logging
import threading
import time

from hub.ont import mappers as MP
from hub.ont import sources as SRC
from hub.ont.store import Store

log = logging.getLogger("hub.ont")
BATCH = 3000


class Sync:
    def __init__(self, db, store=None, factory_id="", cae_call=None, modes=("teach",)):
        self.db = db
        self.store = store or Store(db)
        self.factory_id = factory_id
        self.cae_call = cae_call
        self.modes = set(modes)
        self.ctx = MP.Ctx()
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.errors = 0
        self.last_error = None
        self.lag_s = 0
        self.stats = {"messages": 0, "batches": 0, "last_run": None, "replaying": False}
        self._last_reconcile = 0.0

    # ------------------------------------------------------------ 启动
    def init(self):
        self.store.init()
        c = self.store.state("ctx")
        if c:
            self.ctx = ctx_load(c)
        if self.store.state("cursor") is None:
            with self.lock:
                self._seed()

    def _seed(self):
        B = self.store.batch()
        for m in sorted(self.modes):
            SRC.master(B, m)
        B.flush({"cursor": 0, "ctx": ctx_dump(self.ctx)})

    def cursor(self):
        return int(self.store.state("cursor", 0) or 0)

    # ------------------------------------------------------------ 增量
    def step(self, lag="2 seconds", until=None):
        """处理一批；返回处理的消息数"""
        with self.lock:
            cur = self.cursor()
            sql = ("select seq, ts, topic, type, mode, payload from bus_message where valid and seq > %s and type = any(%s) "
                   + ("and seq <= %s " if until is not None else "and received_at < now() - interval '{}' ".format(lag))
                   + "order by seq limit %s")
            args = [cur, list(MP.HANDLERS)] + ([until] if until is not None else []) + [BATCH]
            rows = self.db.q(sql, args)
            if not rows:
                return 0
            B = self.store.batch()
            for r in rows:
                mode = r["mode"] or "teach"
                self.modes.add(mode)
                msg = dict(r["payload"], _topic=r["topic"])
                try:
                    MP.HANDLERS[r["type"]](B, mode, r["seq"], r["ts"].isoformat(), msg, self.ctx)
                except Exception as e:  # noqa: BLE001  —— 一条坏消息不挡后面的
                    self.errors += 1
                    self.last_error = "seq {}（{}）：{}".format(r["seq"], r["type"], e)
                    log.warning("本体同步跳过消息 %s", self.last_error)
            B.flush({"cursor": rows[-1]["seq"], "ctx": ctx_dump(self.ctx)})
            self.stats["messages"] += len(rows)
            self.stats["batches"] += 1
            self.stats["last_run"] = time.time()
            self.lag_s = max(0.0, time.time() - rows[-1]["ts"].timestamp())
            return len(rows)

    def reconcile(self):
        with self.lock:
            B = self.store.batch()
            for m in sorted(self.modes):
                SRC.master(B, m)
                SRC.tables(B, self.db, m)
                if self.cae_call:
                    SRC.jobs(B, m, self.factory_id, self.cae_call)
                SRC.metrics(B, self.db, m)
                SRC.costs(B, self.db, m)
            B.flush()
            self._last_reconcile = time.time()

    def catch_up(self, until=None):
        n = 0
        while True:
            k = self.step(lag="0 seconds", until=until)
            n += k
            if k < BATCH:
                return n

    # ------------------------------------------------------------ 重放与清空
    def replay(self, mode=None):
        """清空本体后从头重放（mode=None 为全部）。返回处理的消息数"""
        with self.lock:
            self.stats["replaying"] = True
            try:
                self.store.reset(mode)
                self.ctx.reset(mode)
                top = self.db.one("select coalesce(max(seq), 0) as m from bus_message")["m"]
                if mode is None:
                    B = self.store.batch()
                    for m in sorted(self.modes):
                        SRC.master(B, m)
                    B.flush({"cursor": 0, "ctx": ctx_dump(self.ctx)})
                    n = self.catch_up(until=top)
                else:
                    # 只重放一个模式：其他模式的对象不动，临时用独立游标跑完再恢复
                    keep = self.cursor()
                    B = self.store.batch()
                    SRC.master(B, mode)
                    B.flush({"cursor": 0})
                    n = 0
                    while True:
                        k = self._step_mode(mode, top)
                        n += k
                        if k < BATCH:
                            break
                    self.store.set_state("cursor", max(keep, top))
                    self.store.set_state("ctx", ctx_dump(self.ctx))
                self.reconcile()
                return n
            finally:
                self.stats["replaying"] = False

    def _step_mode(self, mode, top):
        cur = self.cursor()
        rows = self.db.q("select seq, ts, topic, type, mode, payload from bus_message where valid and seq > %s and seq <= %s "
                         "and type = any(%s) and coalesce(mode, 'teach') = %s order by seq limit %s",
                         (cur, top, list(MP.HANDLERS), mode, BATCH))
        if not rows:
            return 0
        B = self.store.batch()
        for r in rows:
            try:
                MP.HANDLERS[r["type"]](B, mode, r["seq"], r["ts"].isoformat(), dict(r["payload"], _topic=r["topic"]), self.ctx)
            except Exception as e:  # noqa: BLE001
                self.errors += 1
                self.last_error = "seq {}：{}".format(r["seq"], e)
        B.flush({"cursor": rows[-1]["seq"]})
        return len(rows)

    def reset_mode(self, mode):
        """教学情景重置时：清掉这个模式的本体，从主数据重新开始（游标不动，新情景的消息接着同步）"""
        with self.lock:
            self.store.reset(mode)
            self.ctx.reset(mode)
            B = self.store.batch()
            SRC.master(B, mode)
            B.flush({"ctx": ctx_dump(self.ctx)})

    # ------------------------------------------------------------ 后台线程
    def run(self, every_s=2.0, reconcile_s=60.0):
        while not self.stop.is_set():
            try:
                while self.step() >= BATCH and not self.stop.is_set():
                    pass
                if time.time() - self._last_reconcile > reconcile_s:
                    self.reconcile()
            except Exception:  # noqa: BLE001
                self.errors += 1
                log.exception("本体同步出错")
            self.stop.wait(every_s)

    def health(self):
        cur = self.cursor()
        # 落后 = 游标之后、本体要处理的消息条数（其他类型的消息——提醒、遥测、PLC——不算，否则总线一直有流量时永远不为 0）
        behind = self.db.one("select count(*) as n from bus_message where seq > %s and valid and type = any(%s)",
                             (cur, list(MP.HANDLERS)))["n"]
        return {"cursor": cur, "behind": behind, "lag_s": round(self.lag_s, 1), "errors": self.errors,
                "last_error": self.last_error, "last_reconcile": self._last_reconcile, **self.stats}


# ------------------------------------------------------------------ 上下文的保存与恢复（键是元组）
def ctx_dump(ctx):
    out = {}
    for name in ("tool", "tool_life", "downtime", "start", "op_index", "agv_task", "last_state"):
        out[name] = [[list(k), v] for k, v in getattr(ctx, name).items()]
    return out


def ctx_load(d):
    ctx = MP.Ctx()
    for name, rows in (d or {}).items():
        if hasattr(ctx, name):
            setattr(ctx, name, {tuple(k): (tuple(v) if isinstance(v, list) and name == "agv_task" else v) for k, v in rows})
    return ctx
