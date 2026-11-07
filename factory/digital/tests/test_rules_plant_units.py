# -*- coding: utf-8 -*-
"""第 106 轮：质量规则 Q1/Q3 的证据主题不再写死演示工厂的检验站 qc-01——别的厂没有这台设备时不出错（原来 Q3 在有不合格品时 KeyError）。"""
import os
import sys

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [DIG, os.path.dirname(DIG)]


def test_meas_topic_without_qc01(monkeypatch):
    from hub.ont.rules import quality as Q
    import wqbus.topics as T
    assert Q._meas_topic() and "qc-01" in Q._meas_topic()                 # 演示工厂：照旧
    monkeypatch.delitem(T.UNIT_AREA, "qc-01")
    assert Q._meas_topic() is None                                      # 机器人厂这类没有 qc-01 的厂：不出错
    assert Q._meas_topic({"_topic": "wq/x/y/measurement"}) == "wq/x/y/measurement"
