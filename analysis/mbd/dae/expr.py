"""函数表达式（ADR-0097 第 3 条）：ADAMS 函数常用子集的受限表达式语言，自写解析器，不用 eval。

求值用二阶泰勒“射流”（值、一阶导、二阶导，对时间）：驱动的速度、加速度方程要位移函数对时间的一、二阶导，射流给的是精确导数。

    f = compile_expr("360*time + 10*sin(2*PI*time)")
    f(0.1)            → 值
    f.jet(0.1)        → (值, 一阶导, 二阶导)

变量：time（s）。运算：+ − * / ^（或 **）、一元负号、括号。
函数：sin cos tan asin acos atan atan2 sqrt exp log abs min max sign，
     STEP(x, x0, h0, x1, h1)（三次过渡，ADAMS 同名函数）、STEP5（五次过渡）、HAVSIN（半正弦过渡）；
     D2 起：IMPACT（单边接触力）、SPLINE(名, x)；力元里可用测量量的 id 当变量。
常数：PI、DTOR（π/180）、RTOD（180/π）。函数名不分大小写。
"""

from __future__ import annotations

import math
import re

import numpy as np


class ExprError(ValueError):
    pass


class Jet:
    """二阶泰勒射流 (v, d, dd)：f(t+ε) ≈ v + d ε + dd ε²/2。"""

    __slots__ = ("d", "dd", "v")

    def __init__(self, v, d=0.0, dd=0.0):
        self.v, self.d, self.dd = float(v), float(d), float(dd)

    @staticmethod
    def of(x):
        return x if isinstance(x, Jet) else Jet(x)

    def __add__(self, o):
        o = Jet.of(o)
        return Jet(self.v + o.v, self.d + o.d, self.dd + o.dd)

    __radd__ = __add__

    def __neg__(self):
        return Jet(-self.v, -self.d, -self.dd)

    def __sub__(self, o):
        return self + (-Jet.of(o))

    def __rsub__(self, o):
        return Jet.of(o) - self

    def __mul__(self, o):
        o = Jet.of(o)
        return Jet(self.v * o.v, self.d * o.v + self.v * o.d, self.dd * o.v + 2 * self.d * o.d + self.v * o.dd)

    __rmul__ = __mul__

    def __truediv__(self, o):
        o = Jet.of(o)
        if o.v == 0:
            raise ExprError("除以 0")
        return self * _chain(o, 1 / o.v, -1 / o.v ** 2, 2 / o.v ** 3)

    def __rtruediv__(self, o):
        return Jet.of(o) / self


def _chain(x: Jet, f0, f1, f2) -> Jet:
    """复合函数 g(x(t))：给 g、g′、g″ 在 x.v 处的值。"""
    return Jet(f0, f1 * x.d, f2 * x.d ** 2 + f1 * x.dd)


def _pow(a: Jet, b: Jet) -> Jet:
    if b.d == 0 and b.dd == 0:                       # 指数是常数
        n = b.v
        if a.v == 0 and n < 2 and (a.d or a.dd):
            raise ExprError("0 的非整数次幂不可导")
        if a.v < 0 and n != int(n):
            raise ExprError("负数的非整数次幂")
        f0 = a.v ** n
        f1 = n * a.v ** (n - 1) if n != 0 else 0.0
        f2 = n * (n - 1) * a.v ** (n - 2) if n not in (0, 1) else 0.0
        return _chain(a, f0, f1, f2)
    if a.v <= 0:
        raise ExprError("底数不是正数时指数不能随时间变化")
    return _exp(b * _log(a))


def _sin(x):
    return _chain(x, math.sin(x.v), math.cos(x.v), -math.sin(x.v))


def _cos(x):
    return _chain(x, math.cos(x.v), -math.sin(x.v), -math.cos(x.v))


def _tan(x):
    c = math.cos(x.v)
    t = math.tan(x.v)
    return _chain(x, t, 1 / c ** 2, 2 * t / c ** 2)


def _exp(x):
    e = math.exp(x.v)
    return _chain(x, e, e, e)


def _log(x):
    if x.v <= 0:
        raise ExprError("log 的参数要大于 0")
    return _chain(x, math.log(x.v), 1 / x.v, -1 / x.v ** 2)


def _sqrt(x):
    if x.v <= 0:
        if x.v == 0 and x.d == 0 and x.dd == 0:
            return Jet(0.0)
        raise ExprError("sqrt 的参数要大于 0")
    s = math.sqrt(x.v)
    return _chain(x, s, 0.5 / s, -0.25 / s ** 3)


def _asin(x):
    if abs(x.v) >= 1:
        raise ExprError("asin 的参数要在 (−1, 1)")
    r = 1 - x.v ** 2
    return _chain(x, math.asin(x.v), r ** -0.5, x.v * r ** -1.5)


def _acos(x):
    a = _asin(x)
    return Jet(math.pi / 2 - a.v, -a.d, -a.dd)


def _atan(x):
    r = 1 + x.v ** 2
    return _chain(x, math.atan(x.v), 1 / r, -2 * x.v / r ** 2)


def _atan2(y, x):
    # θ = atan2(y, x)；θ′ = (x y′ − y x′)/r²；θ″ 由商的求导
    r2 = x.v ** 2 + y.v ** 2
    if r2 == 0:
        raise ExprError("atan2(0, 0)")
    num = x.v * y.d - y.v * x.d
    d1 = num / r2
    dnum = x.d * y.d + x.v * y.dd - y.d * x.d - y.v * x.dd
    dr2 = 2 * (x.v * x.d + y.v * y.d)
    d2 = (dnum * r2 - num * dr2) / r2 ** 2
    return Jet(math.atan2(y.v, x.v), d1, d2)


def _abs(x):
    if x.v > 0:
        return x
    if x.v < 0:
        return -x
    return Jet(0.0, abs(x.d), 0.0)


def _sign(x):
    return Jet(0.0 if x.v == 0 else math.copysign(1.0, x.v))


def _min(a, b):
    return a if a.v <= b.v else b


def _max(a, b):
    return a if a.v >= b.v else b


def _step(x, x0, h0, x1, h1):
    """ADAMS STEP：x ≤ x0 为 h0，x ≥ x1 为 h1，中间三次多项式 h0 + Δh·s²(3 − 2s)。"""
    return _blend(x, x0, h0, x1, h1, lambda s: (s * s * (3 - 2 * s), 6 * s * (1 - s), 6 - 12 * s))


def _step5(x, x0, h0, x1, h1):
    """ADAMS STEP5：五次过渡 h0 + Δh·s³(10 − 15s + 6s²)。"""
    return _blend(x, x0, h0, x1, h1,
                  lambda s: (s ** 3 * (10 - 15 * s + 6 * s * s), 30 * s * s * (1 - s) ** 2, 60 * s * (1 - s) * (1 - 2 * s)))


def _havsin(x, x0, h0, x1, h1):
    """ADAMS HAVSIN：半正弦过渡 h0 + Δh·(1 − cos πs)/2。"""
    return _blend(x, x0, h0, x1, h1,
                  lambda s: ((1 - math.cos(math.pi * s)) / 2, math.pi / 2 * math.sin(math.pi * s),
                             math.pi ** 2 / 2 * math.cos(math.pi * s)))


def _blend(x, x0, h0, x1, h1, shape):
    for a in (x0, h0, x1, h1):
        if a.d or a.dd:
            raise ExprError("STEP 类函数的 x0、h0、x1、h1 要是常数")
    if x1.v <= x0.v:
        raise ExprError("STEP 类函数要 x1 > x0")
    if x.v <= x0.v:
        return Jet(h0.v)
    if x.v >= x1.v:
        return Jet(h1.v)
    w = x1.v - x0.v
    s = (x.v - x0.v) / w
    g, g1, g2 = shape(s)
    dh = h1.v - h0.v
    return _chain(x, h0.v + dh * g, dh * g1 / w, dh * g2 / w ** 2)


def _impact(x, xd, x1, k, e, cmax, d):
    """IMPACT(x, ẋ, x1, k, e, cmax, d)：x < x1 时 max(0, k(x1 − x)^e − STEP(x, x1 − d, cmax, x1, 0)·ẋ)，否则 0（ADR-0097 补充三）"""
    if x.v >= x1.v:
        return Jet(0.0)
    if k.v < 0 or e.v <= 0 or cmax.v < 0 or d.v <= 0:
        raise ExprError("IMPACT 要 k ≥ 0、e > 0、cmax ≥ 0、d > 0")
    f = k * _pow(x1 - x, e) - _step(x, x1 - d, cmax, x1, Jet(0.0)) * xd
    return f if f.v > 0 else Jet(0.0)


FUNCS = {"sin": (1, _sin), "cos": (1, _cos), "tan": (1, _tan), "asin": (1, _asin), "acos": (1, _acos), "atan": (1, _atan),
         "atan2": (2, _atan2), "sqrt": (1, _sqrt), "exp": (1, _exp), "log": (1, _log), "abs": (1, _abs), "sign": (1, _sign),
         "min": (2, _min), "max": (2, _max), "step": (5, _step), "step5": (5, _step5), "havsin": (5, _havsin),
         "impact": (7, _impact)}
CONSTS = {"pi": math.pi, "dtor": math.pi / 180, "rtod": 180 / math.pi}
TOKEN = re.compile(r"\s*(?:(\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|(\*\*|[-+*/^(),]))")


def _tokens(src: str):
    pos, out = 0, []
    src = src.rstrip()
    while pos < len(src):
        m = TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise ExprError(f"看不懂的字符：{src[pos:pos + 10]!r}")
        num, name, op = m.groups()
        out.append(("num", float(num)) if num is not None else ("name", name.lower()) if name else ("op", "^" if op == "**" else op))
        pos = m.end()
    out.append(("end", None))
    return out


class _Parser:
    """递归下降：expr = term {(+|−) term}；term = unary {(*|/) unary}；unary = [−|+] power；power = atom [^ unary]"""

    def __init__(self, src, variables=(), splines=None):
        self.t, self.i = _tokens(src), 0
        self.vars = {v.lower() for v in variables}
        self.splines = {k.lower(): v for k, v in (splines or {}).items()}

    def peek(self):
        return self.t[self.i]

    def take(self, kind=None, val=None):
        k, v = self.t[self.i]
        if (kind and k != kind) or (val and v != val):
            raise ExprError(f"这里要 {val or kind}，看到的是 {v!r}")
        self.i += 1
        return v

    def parse(self):
        node = self.expr()
        if self.peek()[0] != "end":
            raise ExprError(f"多余的内容：{self.peek()[1]!r}")
        return node

    def expr(self):
        node = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()
            node = (op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()
            node = (op, node, self.unary())
        return node

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            return ("neg", self.unary())
        if self.peek() == ("op", "+"):
            self.take()
            return self.unary()
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() == ("op", "^"):
            self.take()
            return ("^", base, self.unary())
        return base

    def atom(self):
        k, v = self.peek()
        if k == "num":
            self.take()
            return ("num", v)
        if k == "op" and v == "(":
            self.take()
            node = self.expr()
            self.take("op", ")")
            return node
        if k == "name":
            self.take()
            if v == "time":
                return ("time",)
            if v in CONSTS:
                return ("num", CONSTS[v])
            if v == "spline":
                self.take("op", "(")
                name = self.take("name")
                if name not in self.splines:
                    raise ExprError(f"没有样条 {name}")
                self.take("op", ",")
                arg = self.expr()
                self.take("op", ")")
                return ("spline", self.splines[name], arg)
            if v in self.vars:
                return ("var", v)
            if v in FUNCS:
                n, _ = FUNCS[v]
                self.take("op", "(")
                args = [self.expr()]
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
                self.take("op", ")")
                if len(args) != n:
                    raise ExprError(f"{v} 要 {n} 个参数，给了 {len(args)} 个")
                return ("call", v, args)
            raise ExprError(f"不认识的名字：{v}")
        raise ExprError(f"这里不该出现 {v!r}")


def _eval(node, t: Jet, env=None) -> Jet:
    k = node[0]
    if k == "num":
        return Jet(node[1])
    if k == "time":
        return t
    if k == "var":
        if env is None or node[1] not in env:
            raise ExprError(f"测量量 {node[1]} 在这里不能用")
        return Jet.of(env[node[1]])
    if k == "neg":
        return -_eval(node[1], t, env)
    if k == "call":
        return FUNCS[node[1]][1](*[_eval(a, t, env) for a in node[2]])
    if k == "spline":
        return node[1].jet(_eval(node[2], t, env))
    a, b = _eval(node[1], t, env), _eval(node[2], t, env)
    if k == "+":
        return a + b
    if k == "-":
        return a - b
    if k == "*":
        return a * b
    if k == "/":
        return a / b
    return _pow(a, b)


class Expr:
    def __init__(self, src: str, variables=(), splines=None):
        self.src = src
        self.tree = _Parser(src, variables, splines).parse()
        self.uses_vars = _uses(self.tree, "var")
        self.constant = not _uses(self.tree, "time") and not self.uses_vars

    def jet(self, t: float, env=None):
        j = _eval(self.tree, Jet(t, 1.0, 0.0), env)
        return j.v, j.d, j.dd

    def __call__(self, t: float, env=None) -> float:
        return _eval(self.tree, Jet(t, 1.0, 0.0), env).v


def _uses(node, kind) -> bool:
    if node[0] == kind:
        return True
    if node[0] == "call":
        return any(_uses(a, kind) for a in node[2])
    if node[0] == "spline":
        return _uses(node[2], kind)
    return any(_uses(x, kind) for x in node[1:] if isinstance(x, tuple))


class Spline:
    """样条（三次非扭结 / Akima / 线性），射流用它的一、二阶导数"""

    def __init__(self, x, y, method="cubic"):
        from scipy.interpolate import Akima1DInterpolator, CubicSpline, make_interp_spline

        x, y = np.asarray(x, float), np.asarray(y, float)
        if x.shape != y.shape or x.size < 2 or np.any(np.diff(x) <= 0):
            raise ExprError("样条的 x 要严格递增、与 y 一样多、至少 2 个点")
        if method == "linear" or x.size < 4:
            self.f = make_interp_spline(x, y, k=1)
        elif method == "akima":
            self.f = Akima1DInterpolator(x, y, extrapolate=True)
        else:
            self.f = CubicSpline(x, y, bc_type="not-a-knot")
        self.d1, self.d2 = self.f.derivative(1), self.f.derivative(2)

    def jet(self, x: Jet) -> Jet:
        return _chain(x, float(self.f(x.v)), float(self.d1(x.v)), float(self.d2(x.v)))


def compile_expr(src, variables=(), splines=None) -> Expr:
    """数或表达式文字 → Expr（数也包成常数表达式）；variables：可用的测量量名；splines：名 → Spline"""
    if isinstance(src, (int, float)):
        return Expr(repr(float(src)))
    if not isinstance(src, str):
        raise ExprError("表达式要是文字或数")
    return Expr(src, variables, splines)
