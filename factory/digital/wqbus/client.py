# -*- coding: utf-8 -*-
"""MQTT 客户端封装：连接、发布（自动决定 QoS 与保留）、按通配符订阅并自动校验。"""
import json
import logging
import os
import threading

import paho.mqtt.client as mqtt

from .envelope import ValidationError, make, parse
from .topics import is_retained, qos_for

log = logging.getLogger("wqbus")


class Bus:
    def __init__(self, client_id, host=None, port=None, mode=None):
        self.host = host or os.environ.get("WQ_MQTT_HOST", "localhost")
        self.port = int(port or os.environ.get("WQ_MQTT_PORT", 1883))
        self.mode = mode or os.environ.get("WQ_MODE", "teach")
        self._subs = []          # (pattern, handler)
        self._connected = threading.Event()
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True)
        user = os.environ.get("WQ_MQTT_USER")
        if user:
            self.c.username_pw_set(user, os.environ.get("WQ_MQTT_PASSWORD", ""))
        self.c.on_connect = self._on_connect
        self.c.on_message = self._on_message
        self.c.reconnect_delay_set(1, 10)

    # ------------------------------------------------------------ 连接
    def start(self, timeout=15):
        self.c.connect_async(self.host, self.port, keepalive=30)
        self.c.loop_start()
        if not self._connected.wait(timeout):
            raise ConnectionError("连不上总线 {}:{}".format(self.host, self.port))
        return self

    def stop(self):
        self.c.loop_stop()
        self.c.disconnect()

    def _on_connect(self, c, userdata, flags, rc, props=None):
        if rc == 0:
            for pattern, _ in self._subs:
                c.subscribe(pattern, qos=1)
            self._connected.set()
        else:
            log.error("总线拒绝连接：%s", rc)

    # ------------------------------------------------------------ 收发
    def subscribe(self, pattern, handler, raw=False):
        """handler(topic, msg)；raw=True 时 msg 是原始 bytes（历史库用，坏消息也要记下来）。"""
        self._subs.append((pattern, (handler, raw)))
        if self._connected.is_set():
            self.c.subscribe(pattern, qos=1)

    def _on_message(self, c, userdata, m):
        for pattern, (handler, raw) in self._subs:
            if not mqtt.topic_matches_sub(pattern, m.topic):
                continue
            try:
                if raw:
                    handler(m.topic, m.payload, m.retain)
                else:
                    handler(m.topic, parse(m.payload))
            except ValidationError as e:
                log.warning("丢弃不合规范的消息 %s：%s", m.topic, e)
            except Exception:  # noqa: BLE001 — 一个处理函数出错不能拖垮整个连接
                log.exception("处理 %s 出错", m.topic)

    def publish_msg(self, topic, msg, retain=None):
        retain = is_retained(topic) if retain is None else retain
        info = self.c.publish(topic, json.dumps(msg, ensure_ascii=False), qos=qos_for(topic), retain=retain)
        return info

    def publish(self, topic, type_, source, data, corr=None, mode=None, retain=None, ts=None):
        msg = make(type_, source, data, mode=mode or self.mode, corr=corr, ts=ts)
        self.publish_msg(topic, msg, retain)
        return msg
