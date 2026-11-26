"""控制器（ADR-0097 D7a，补充十七）：连续 PID、连续状态空间（状态随积分器一起积）、FMU 联合仿真（采样、零阶保持）。

测量量用对外单位（sysm.measures），执行器输出 N 或 N·m。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from analysis.mbd.dae.expr import ExprError, compile_expr

PID_TRACKING_S = 0.05      # 反算法抗积分饱和的跟踪时间常数 T_t（s）的缺省值；模型里用 antiwindup_tracking_s 改（ADR-0130）


class ControlError(ValueError):
    pass


def _sig(spec, measures, where):
    if "measure" in spec:
        if spec["measure"] not in measures:
            raise ControlError(f"{where}：没有测量量 {spec['measure']}")
        return ("m", spec["measure"])
    try:
        return ("e", compile_expr(spec["expression"]))
    except ExprError as exc:
        raise ControlError(f"{where}：表达式 {spec['expression']}：{exc}") from exc


def _sigval(sig, t, meas):
    return meas[sig[1]] if sig[0] == "m" else sig[1](t)


class _Fmu:
    """fmpy 的薄包装：FMI 2.0 / 3.0 Co-Simulation，变量按名字（数组用 index）"""

    def __init__(self, c, base_dir, measures, actuators):
        try:
            from fmpy import extract, read_model_description
        except ImportError as exc:
            raise ControlError("FMU 联合仿真要装 fmpy：pip install fmpy") from exc
        p = Path(c["path"])
        if not p.is_absolute():
            p = Path(base_dir or ".") / p
        if not p.is_file():
            raise ControlError(f"控制器 {c['id']}：找不到 FMU 文件 {p}")
        self.id, self.h = c["id"], float(c["sample_time_s"])
        self.md = read_model_description(str(p))
        if self.md.coSimulation is None:
            raise ControlError(f"控制器 {c['id']}：FMU 不支持 Co-Simulation")
        self.v3 = self.md.fmiVersion.startswith("3")
        self.vars = {v.name: v for v in self.md.modelVariables}
        self.dir = extract(str(p))
        self.c = c
        self.inputs = []
        for s in c.get("inputs") or []:
            self._var(s["variable"])
            self.inputs.append((s["variable"], s.get("index", 0), _sig(s, measures, f"控制器 {c['id']}")))
        self.outputs = []
        for s in c["outputs"]:
            self._var(s["variable"])
            if s["actuator"] not in actuators:
                raise ControlError(f"控制器 {c['id']}：没有执行器 {s['actuator']}")
            self.outputs.append((s["variable"], s.get("index", 0), s["actuator"]))
        self.held = {a: 0.0 for _, _, a in self.outputs}
        self.f = None

    def _var(self, name):
        if name not in self.vars:
            raise ControlError(f"控制器 {self.id}：FMU 里没有变量 {name}")
        return self.vars[name]

    def _size(self, name):
        v = self.vars[name]
        dims = getattr(v, "dimensions", None) or []
        n = 1
        for d in dims:
            if d.start is not None:
                n *= int(d.start)
            else:
                ref = next(x for x in self.md.modelVariables if x.valueReference == d.valueReference)
                n *= int(self.c.get("structural_parameters", {}).get(ref.name, ref.start))
        return n

    def start(self, t0):
        from fmpy.fmi2 import FMU2Slave
        from fmpy.fmi3 import FMU3Slave

        kw = {"guid": self.md.guid, "unzipDirectory": self.dir, "modelIdentifier": self.md.coSimulation.modelIdentifier,
              "instanceName": self.id}
        self.f = (FMU3Slave if self.v3 else FMU2Slave)(**kw)
        self.f.instantiate()
        sp = self.c.get("structural_parameters") or {}
        if self.v3:
            if sp:
                self.f.enterConfigurationMode()
                for k, v in sp.items():
                    self.f.setUInt64([self._var(k).valueReference], [int(v)])
                self.f.exitConfigurationMode()
            for k, v in (self.c.get("parameters") or {}).items():
                vals = [float(x) for x in np.ravel(v)]
                self.f.setFloat64([self._var(k).valueReference], vals)
            self.f.enterInitializationMode(startTime=t0)
            self.f.exitInitializationMode()
        else:
            if sp:
                raise ControlError(f"控制器 {self.id}：FMI 2.0 没有结构参数")
            self.f.setupExperiment(startTime=t0)
            for k, v in (self.c.get("parameters") or {}).items():
                self.f.setReal([self._var(k).valueReference], [float(v)])
            self.f.enterInitializationMode()
            self.f.exitInitializationMode()

    def _set(self, name, idx, val, buf):
        buf.setdefault(name, np.zeros(self._size(name)))[idx] = val

    def step(self, t, meas):
        """在采样时刻 t 送入输入、走一拍 h、取输出并保持"""
        buf = {}
        for name, idx, sig in self.inputs:
            self._set(name, idx, float(_sigval(sig, t, meas)), buf)
        for name, vals in buf.items():
            vr = [self.vars[name].valueReference]
            (self.f.setFloat64 if self.v3 else self.f.setReal)(vr, list(vals))
        self.f.doStep(t, self.h) if self.v3 else self.f.doStep(currentCommunicationPoint=t, communicationStepSize=self.h)
        for name, idx, act in self.outputs:
            vr = self.vars[name].valueReference
            if self.v3:
                vals = self.f.getFloat64([vr], nValues=self._size(name))
            else:
                vals = self.f.getReal([vr])
            self.held[act] = float(vals[idx])

    def close(self):
        if self.f is not None:
            import contextlib

            with contextlib.suppress(Exception):          # 关不掉也不影响结果
                self.f.terminate()
                self.f.freeInstance()
            self.f = None


class Controllers:
    def __init__(self, defs, measures, actuators, base_dir=None):
        self.items, self.fmus = [], []
        self.nx = 0
        x0 = []
        acts = set(actuators)
        for c in defs:
            cid = c["id"]
            if c["type"] == "fmu":
                self.fmus.append(_Fmu(c, base_dir, measures, acts))
                continue
            if c["type"] == "pid":
                for k in ("sensor", "rate_sensor"):
                    if c.get(k) and c[k] not in measures:
                        raise ControlError(f"控制器 {cid}：没有测量量 {c[k]}")
                if c["actuator"] not in acts:
                    raise ControlError(f"控制器 {cid}：没有执行器 {c['actuator']}")
                try:
                    sp = compile_expr(c["setpoint"])
                except ExprError as exc:
                    raise ControlError(f"控制器 {cid}：设定值 {c['setpoint']}：{exc}") from exc
                lo, hi = c.get("output_min", -np.inf), c.get("output_max", np.inf)
                if lo >= hi:
                    raise ControlError(f"控制器 {cid}：output_min 要小于 output_max")
                it = {"c": c, "sp": sp, "o": self.nx, "lo": lo, "hi": hi, "filt": not c.get("rate_sensor")}
                n = 1 + (1 if it["filt"] else 0)
                x0 += [0.0] * n
                self.nx += n
                self.items.append(it)
            else:  # state_space
                D = np.atleast_2d(np.asarray(c["D"], float))
                A = np.asarray(c.get("A") or [], float)
                A = np.zeros((0, 0)) if A.size == 0 else np.atleast_2d(A)
                nxs = A.shape[0]
                if A.shape != (nxs, nxs):
                    raise ControlError(f"控制器 {cid}：A 要是方阵")
                B = np.asarray(c.get("B", np.zeros((nxs, D.shape[1]))), float).reshape(nxs, D.shape[1])
                C = np.asarray(c.get("C", np.zeros((D.shape[0], nxs))), float).reshape(D.shape[0], nxs)
                ins = [_sig(s, measures, f"控制器 {cid}") for s in c["inputs"]]
                if D.shape != (len(c["outputs"]), len(ins)):
                    raise ControlError(f"控制器 {cid}：D 应为 {len(c['outputs'])}×{len(ins)}")
                for a in c["outputs"]:
                    if a not in acts:
                        raise ControlError(f"控制器 {cid}：没有执行器 {a}")
                xs0 = np.asarray(c.get("x0", np.zeros(nxs)), float)
                if xs0.shape != (nxs,):
                    raise ControlError(f"控制器 {cid}：x0 长度应为 {nxs}")
                self.items.append({"c": c, "ss": (A, B, C, D), "ins": ins, "o": self.nx, "n": nxs})
                x0 += xs0.tolist()
                self.nx += nxs
        self.x0 = np.array(x0)
        self.sample = min((f.h for f in self.fmus), default=None)

    @property
    def any(self):
        return bool(self.items or self.fmus)

    def _pid(self, it, t, meas, xc):
        c = it["c"]
        rv, rd, _ = it["sp"].jet(t)
        e = rv - meas[c["sensor"]]
        kp, ki, kd = c["kp"], c.get("ki", 0.0), c.get("kd", 0.0)
        integ = xc[it["o"]]
        if it["filt"]:
            tf = c.get("derivative_filter_s", 1e-3)
            xf = xc[it["o"] + 1]
            de = (e - xf) / tf
        else:
            de = rd - meas[c["rate_sensor"]]
        raw = kp * e + ki * integ + kd * de
        u = min(max(raw, it["lo"]), it["hi"])
        return e, de, raw, u

    def outputs(self, t, meas, xc):
        out = {}
        for it in self.items:
            if "sp" in it:
                _, _, _, u = self._pid(it, t, meas, xc)
                a = it["c"]["actuator"]
                out[a] = out.get(a, 0.0) + u
            else:
                _, _, C, D = it["ss"]
                u = np.array([_sigval(s, t, meas) for s in it["ins"]])
                y = C @ xc[it["o"]:it["o"] + it["n"]] + D @ u
                for a, v in zip(it["c"]["outputs"], y, strict=True):
                    out[a] = out.get(a, 0.0) + float(v)
        for f in self.fmus:
            for a, v in f.held.items():
                out[a] = out.get(a, 0.0) + v
        return out

    def deriv(self, t, meas, xc):
        d = np.zeros(self.nx)
        for it in self.items:
            if "sp" in it:
                e, _, raw, u = self._pid(it, t, meas, xc)
                # 抗积分饱和用反算法：ż = e + (u − u_raw)/(ki·T_t)。《多体动力学》书第 31 章线索第 46 条（问渠 CAD 0.3.8 细则）：
                # 原来“饱和且误差同向就停积分”是开关，停积分后 u_raw 回落到限幅以下、积分恢复、又越过限幅，解贴着限幅来回切换，
                # 变步长积分卡住（书里转台 2 s 算不完）。反算法连续，没有切换
                ki = it["c"].get("ki", 0.0)
                tt = float(it["c"].get("antiwindup_tracking_s", PID_TRACKING_S))
                d[it["o"]] = e + ((u - raw) / (ki * tt) if ki else 0.0)
                if it["filt"]:
                    tf = it["c"].get("derivative_filter_s", 1e-3)
                    d[it["o"] + 1] = (e - xc[it["o"] + 1]) / tf
            elif it["n"]:
                A, B, _, _ = it["ss"]
                u = np.array([_sigval(s, t, meas) for s in it["ins"]])
                d[it["o"]:it["o"] + it["n"]] = A @ xc[it["o"]:it["o"] + it["n"]] + B @ u
        return d

    def start(self, t0, meas):
        """FMU 初始化，并在 t0 走第一拍（输出从 t0 起保持一拍）"""
        for f in self.fmus:
            f.start(t0)
            f.step(t0, meas)

    def sample_at(self, t, meas):
        for f in self.fmus:
            f.step(t, meas)

    def close(self):
        for f in self.fmus:
            f.close()
