# -*- coding: utf-8 -*-
"""把 functions/*.js 装配成 Node-RED 的 flows.json（改了函数代码后运行一次：python3 build_flows.py）。

一个流程页“ERPNext ↔ 统一数据总线”，分六行，每行：总线输入（或定时器） → 函数 → 总线输出。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TAB = "wq-bridge-tab"
BROKER = "wq-broker"

ROWS = [
    # (id, 标签, 输入, 函数文件, 说明)
    ("proposal", "执行已确认的提议", {"topic": "wq/gearbox/ai/proposal"}, "proposal.js",
     "AI 或计划员起草、人确认后的提议 → 销售订单、工单、请购单"),
    ("shop", "车间报工 → 作业卡、完工入库", {"topic": "wq/gearbox/+/+/event"}, "shopfloor.js",
     "每件完工记工时；工序做完提交作业卡；最后一道做完按合格数入库"),
    ("qc", "测量值 → 质量检验单", {"topic": "wq/gearbox/quality/qc-01/measurement"}, "measurement.js",
     "一件零件的全部特性到齐后建检验单"),
    ("design", "设计发布 → 物料版本、BOM、附件", {"topic": "wq/gearbox/design/+/+"}, "design.js",
     "FreeCAD 发布宏和 CAM 发出的消息"),
    ("poll", "ERPNext 单据变化 → 总线", {"every": 30}, "poll.js", "每 30 秒轮询订单、工单、请购单、采购单"),
    ("bins", "库存快照 → 总线", {"every": 60}, "bins.js", "每 60 秒取一次库存"),
]


def build():
    nodes = [
        {"id": TAB, "type": "tab", "label": "ERPNext ↔ 统一数据总线", "disabled": False,
         "info": "问渠数字工厂桥接。所有组件只经总线交换数据（附录 A.4）；ERPNext 的读写全部在这里完成，"
                 "结果以 erp.doc 发回总线。业务逻辑在 lib/erp.js，函数节点只负责调用。"},
        {"id": BROKER, "type": "mqtt-broker", "name": "统一数据总线", "broker": "${WQ_MQTT_HOST}",
         "port": "${WQ_MQTT_PORT}", "clientid": "wq-bridge", "autoConnect": True, "usetls": False,
         "protocolVersion": "4", "keepalive": "30", "cleansession": True, "autoUnsubscribe": True,
         "birthTopic": "", "closeTopic": "", "willTopic": ""},
        {"id": "out-bus", "type": "mqtt out", "z": TAB, "name": "发到总线（erp.doc）", "topic": "", "qos": "1",
         "retain": "false", "broker": BROKER, "x": 900, "y": 280, "wires": []},
        {"id": "out-debug", "type": "debug", "z": TAB, "name": "最近发出的单据", "active": True, "tosidebar": True,
         "console": False, "complete": "payload.data", "targetType": "msg", "statusVal": "payload.data.name",
         "statusType": "msg", "x": 910, "y": 360, "wires": []},
    ]
    for i, (rid, label, src, fn, info) in enumerate(ROWS):
        y = 60 + i * 80
        code = open(os.path.join(HERE, "functions", fn), encoding="utf-8").read()
        if "topic" in src:
            nodes.append({"id": "in-" + rid, "type": "mqtt in", "z": TAB, "name": src["topic"], "topic": src["topic"],
                          "qos": "1", "datatype": "json", "broker": BROKER, "nl": False, "rap": True, "rh": 0,
                          "inputs": 0, "x": 190, "y": y, "wires": [["fn-" + rid]]})
        else:
            nodes.append({"id": "in-" + rid, "type": "inject", "z": TAB, "name": "每 {} 秒".format(src["every"]),
                          "props": [], "repeat": str(src["every"]), "crontab": "", "once": True, "onceDelay": "5",
                          "topic": "", "x": 190, "y": y, "wires": [["fn-" + rid]]})
        nodes.append({"id": "fn-" + rid, "type": "function", "z": TAB, "name": label, "func": code, "outputs": 1,
                      "timeout": 0, "noerr": 0, "initialize": "", "finalize": "", "libs": [], "info": info,
                      "x": 500, "y": y, "wires": [["out-bus", "out-debug"]]})
    with open(os.path.join(HERE, "flows.json"), "w", encoding="utf-8") as f:
        json.dump(nodes, f, ensure_ascii=False, indent=2)
    return nodes


if __name__ == "__main__":
    print("flows.json：{} 个节点".format(len(build())))
