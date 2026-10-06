# -*- coding: utf-8 -*-
"""消息信封与各类型 data 的校验（附录 A.2、A.3）。

规则：只增加字段不改版本号；删改字段或改含义时 SPEC_VERSION 加一。
校验只检查“必须有”的字段和取值范围，允许额外字段，这样加字段不会让旧组件报错。
"""
import datetime as _dt
import json
import uuid

import jsonschema

SPEC_VERSION = 1
MODES = ("teach", "prod")


class ValidationError(ValueError):
    pass


def now_iso(t=None):
    t = t or _dt.datetime.now(_dt.timezone.utc)
    return t.astimezone(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _obj(required, props=None):
    return {"type": "object", "required": list(required), "properties": props or {}}


NUM = {"type": "number"}
STR = {"type": "string"}
FRAC = {"type": "number", "minimum": 0, "maximum": 1}
EVIDENCE = {"type": "array", "items": {"type": "object"}}

DATA_SCHEMAS = {
    "machine.status": _obj(["state"], {
        "state": {"enum": ["run", "idle", "setup", "down", "fault"]},
        "progress": FRAC, "tool_life_left": FRAC, "spindle_rpm": NUM, "feed_mm_min": NUM}),
    "machine.event": _obj(["event"], {
        "event": {"enum": ["cycle_start", "cycle_end", "alarm", "tool_change", "fault", "recover",
                           "op_complete"]},
        "cycle_time_s": NUM}),
    "machine.cmd": _obj(["command"], {
        "command": {"enum": ["dispatch", "start", "pause", "reset", "inject_fault",
                                "load_scenario", "set_speed", "set_problem", "clear_problems", "apply_fix",
                                # 第 17 轮 C 期：班次日历、快照，以及动作执行器用的改派、调序、维修加急
                                "set_calendar", "snapshot", "reassign", "reorder", "expedite_repair", "outsource"]},
        "qty": {"type": "integer", "minimum": 1}}),
    "machine.ack": _obj(["accepted"], {"accepted": {"type": "boolean"}}),
    # 第 17 轮 C 期：仿真车间的完整状态快照（推演用），主题 wq/gearbox/machining/sim/snapshot
    "sim.snapshot": _obj(["snapshot"], {"snapshot": _obj(["t", "epoch", "wos", "machines"]), "request": STR}),
    "quality.measurement": _obj(
        ["part_serial", "item", "characteristic", "nominal_mm", "lower_tol_mm", "upper_tol_mm",
         "value_mm", "result"],
        {"nominal_mm": NUM, "lower_tol_mm": NUM, "upper_tol_mm": NUM, "value_mm": NUM,
         "result": {"enum": ["pass", "fail"]}}),
    "quality.ncr": _obj(["ncr_id", "part_serial", "status"], {
        "status": {"enum": ["open", "rework", "scrap", "use_as_is"]}}),
    "erp.doc": _obj(["doctype", "name", "action"], {
        "action": {"enum": ["created", "submitted", "updated", "cancelled", "snapshot", "failed"]}}),
    "design.release": _obj(["item", "revision"], {"revision": {"type": "integer", "minimum": 1},
                                                  "bom": {"type": "array"}, "files": {"type": "array"}}),
    "design.submit": _obj(["item", "submission"], {}),                        # 企业版：提交待审（第 8 轮）
    "design.review": _obj(["item", "submission", "decision"], {"decision": {"enum": ["approved", "rejected", "withdrawn"]}}),
    "design.gcode": _obj(["item", "revision", "operation", "machine", "gcode_ref"], {"est_time_s": NUM}),
    # 工艺规程（第 13 轮《机械制造技术》）：提交待审、生效（ERPNext 的 BOM 工序与工时、MES 派工跟着变）、退回
    "process.submit": _obj(["item", "submission"], {}),
    "process.release": _obj(["item", "revision", "operations"], {"revision": {"type": "integer", "minimum": 1},
                            "operations": {"type": "array", "minItems": 1, "items": _obj(["operation", "workstation", "minutes"],
                                                                                        {"minutes": {"type": "number", "exclusiveMinimum": 0}})}}),
    "process.review": _obj(["item", "submission", "decision"], {"decision": {"enum": ["rejected"]}}),
    # 跑合试验台的输出轴转矩记录（第 11 轮：疲劳寿命用）
    "test.torque": _obj(["item", "part_serial", "rate_hz", "samples_nm"], {
        "rate_hz": {"type": "number", "exclusiveMinimum": 0},
        "samples_nm": {"type": "array", "items": NUM, "minItems": 2, "maxItems": 20000}}),
    # 第 15 轮：现场运行摘要（客户现场模拟器和真设备都发这个），主题 wq/gearbox/field/<序列号>/telemetry
    "twin.telemetry": _obj(["serial", "day", "period_h", "run_h"], {
        "serial": STR, "day": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"}, "period_h": {"type": "number", "exclusiveMinimum": 0},
        "run_h": {"type": "number", "minimum": 0}, "starts": {"type": "integer", "minimum": 0}, "n_in_rpm": NUM,
        "torque_mean_nm": NUM, "torque_max_nm": NUM, "t_amb_c": NUM, "oil_t_c": NUM, "oil_t_max_c": NUM,
        "vib_mm_s": {"type": "number", "minimum": 0},
        "rainflow": {"type": "array", "items": {"type": "array", "minItems": 3, "maxItems": 3, "items": NUM}},
        "load_hist": {"type": "array", "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": NUM}}}),
    # 第 18 轮第 8 步《PLC 原理及实践》：虚拟 PLC。枢纽下发程序，虚拟 PLC 跑一个班次并上报每个工件和班次结果
    "plc.download": _obj(["run_id", "program"], {
        "run_id": STR, "program": {"type": "string", "minLength": 1, "maxLength": 200000},
        "hours": {"type": "number", "exclusiveMinimum": 0, "maximum": 12}, "seed": {"type": "integer"},
        "speed": {"type": "number", "minimum": 0}}),
    "plc.cycle": _obj(["run_id", "good", "n"], {"run_id": STR, "good": {"type": "boolean"}, "n": {"type": "integer", "minimum": 1},
                                                 "cycle_s": NUM, "peak_kN": NUM, "progress": FRAC}),
    "plc.shift": _obj(["run_id", "phase"], {"run_id": STR, "phase": {"enum": ["started", "done", "failed", "cancelled", "compat"]},
                                             "summary": {"type": "object"}, "error": STR, "compat": {"type": "object"}}),
    "logistics.status": _obj(["x_m", "y_m"], {"x_m": NUM, "y_m": NUM, "battery": FRAC}),
    "ai.alert": _obj(["level", "title"], {"level": {"enum": ["info", "warn", "critical"]},
                                          "evidence": EVIDENCE}),
    "ai.briefing": _obj(["summary", "items"], {"items": {"type": "array", "items": _obj(
        ["text", "evidence"], {"evidence": EVIDENCE})}}),
    "ai.proposal": _obj(["proposal_id", "action", "preview", "requires_confirm"], {
        "requires_confirm": {"const": True}}),
}

ENVELOPE = {
    "type": "object",
    "required": ["v", "id", "ts", "type", "source", "mode", "data"],
    "properties": {
        "v": {"type": "integer", "minimum": 1},
        "id": STR, "ts": STR, "source": STR, "corr": {"type": ["string", "null"]},
        "type": {"enum": sorted(DATA_SCHEMAS)},
        "mode": {"enum": list(MODES)},
        "data": {"type": "object"},
    },
}


_V = jsonschema.Draft202012Validator
_ENV_V = _V(ENVELOPE)
_DATA_V = {k: _V(v) for k, v in DATA_SCHEMAS.items()}


def validate(msg):
    """校验一条消息（dict），不合格抛 ValidationError，合格返回原消息。"""
    try:
        _ENV_V.validate(msg)
        _DATA_V[msg["type"]].validate(msg["data"])
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "(根)"
        raise ValidationError("{}：{} 处 {}".format(msg.get("type", "?"), where, e.message)) from None
    if msg["v"] > SPEC_VERSION:
        raise ValidationError("消息版本 v{} 比本组件支持的 v{} 新".format(msg["v"], SPEC_VERSION))
    return msg


def make(type_, source, data, mode="teach", corr=None, ts=None, id_=None):
    msg = {"v": SPEC_VERSION, "id": id_ or str(uuid.uuid4()), "ts": ts or now_iso(),
           "type": type_, "source": source, "mode": mode, "corr": corr, "data": data}
    return validate(msg)


def parse(payload):
    """bytes / str → 校验过的 dict。"""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    return validate(json.loads(payload))
