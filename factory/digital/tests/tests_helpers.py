# -*- coding: utf-8 -*-
import wqbus
from sim.engine import Engine


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t


def make_engine(auto=True, mode="teach", seed=1):
    out = []

    def pub(topic, type_, source, data, corr):
        out.append((topic, wqbus.make(type_, source, data, mode=mode, corr=corr)))   # 每条都按规范校验
    clock = FakeClock()
    eng = Engine(pub, clock, mode=mode, auto_start=auto, seed=seed, status_every_s=1e9)
    return eng, clock, out


