# -*- coding: utf-8 -*-
"""历史库写入：订阅 wq/#，每条消息原样入库（不合规范的也记下，标记 valid=false），
同时提取设备状态变化点、为不合格零件开不合格品单（NCR）。"""
import json
import logging

from wqbus import ValidationError, parse

log = logging.getLogger("historian")


class Historian:
    def __init__(self, db, on_message=None):
        self.db = db
        self.on_message = on_message          # 新消息回调（AI 规则引擎、网页推送用）
        self._last_state = {}                 # (unit, mode) → state
        self._failed_parts = set()

    def load(self):
        for r in self.db.q("select distinct on (unit, mode) unit, mode, state from machine_state_log "
                           "order by unit, mode, ts desc"):
            self._last_state[(r["unit"], r["mode"])] = r["state"]
        for r in self.db.q("select part_serial from ncr"):
            self._failed_parts.add(r["part_serial"])

    def handle_raw(self, topic, payload, retained=False):
        try:
            msg = parse(payload)
        except (ValidationError, ValueError) as e:
            log.warning("不合规范的消息 %s：%s", topic, e)
            self.db.insert_invalid(topic, payload, str(e))
            return None
        return self.handle(topic, msg)

    def handle(self, topic, msg):
        if not self.db.insert_message(topic, msg):
            return None                        # 重复（保留消息重连后会再收到一次）
        t, d = msg["type"], msg["data"]
        if t == "machine.status":
            unit = topic.split("/")[3]
            key = (unit, msg["mode"])
            if self._last_state.get(key) != d["state"]:
                self._last_state[key] = d["state"]
                self.db.x("insert into machine_state_log (unit, ts, state, mode) values (%s,%s,%s,%s) "
                          "on conflict do nothing", (unit, msg["ts"], d["state"], msg["mode"]))
        elif t == "quality.measurement" and d["result"] == "fail" and d["part_serial"] not in self._failed_parts:
            self._failed_parts.add(d["part_serial"])
            n = self.db.one("select count(*) as n from ncr")["n"] + 1
            self.db.x("insert into ncr (ncr_id, created_at, part_serial, item, work_order, detail, mode) "
                      "values (%s,%s,%s,%s,%s,%s,%s) on conflict do nothing",
                      ("NCR-{:04d}".format(n), msg["ts"], d["part_serial"], d["item"], d.get("work_order"),
                       json.dumps({"characteristic": d["characteristic"], "name": d.get("name"),
                                   "value_mm": d["value_mm"], "lower_tol_mm": d["lower_tol_mm"],
                                   "upper_tol_mm": d["upper_tol_mm"], "message_id": msg["id"]}, ensure_ascii=False),
                       msg["mode"]))
        if self.on_message:
            try:
                self.on_message(topic, msg)
            except Exception:  # noqa: BLE001
                log.exception("消息回调出错")
        return msg
