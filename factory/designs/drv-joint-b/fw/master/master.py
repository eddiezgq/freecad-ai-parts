"""问渠两关节水平机械臂的 CAN 主站（第 115 轮，示例程序）。

一个主站同时带两块关节驱动板（B 版，节点 1、2），做一台水平两关节机械臂（SCARA 的前两轴）：
  上电等两个关节都“就绪” → 原地稳住 → 末端沿直线从 P0 走到 P1（梯形速度）→ 原地稳住 → 发“停”（驱动板停住、抱闸、关输出）。

每 10 ms 一拍（step）：
  1. 收这一拍里各关节发来的帧：状态 0x180+n、报警 0x080+n、心跳 0x700+n；
  2. 监督：任何一个关节报警、任何一个关节心跳 300 ms 没来、跟踪误差超过 2°——让所有关节一起停（“一个停、全停”）；
  3. 没出事就算下一拍末端该在哪（直线上的一点）→ 逆运动学换成两个关节角 → 给每个关节发位置指令 0x200+n。

协议与驱动板固件 `src/can_proto.h` 一致（第 102 轮起），本程序只用 Python 标准库；
它不知道自己是在仿真里还是接在真 CAN 上：输入是收到的帧，输出是要发的帧。
机械臂尺寸、速度、阈值都是示例值。两关节之间的动力学耦合不考虑（每个关节的驱动板自己管自己的电机）。
"""

import math
import struct

L1, L2 = 0.30, 0.25            # 大臂、小臂长 m（示例）
PERIOD = 0.01                  # 主站周期 s
ID_CMD, ID_STATUS, ID_EMCY, ID_HEART = 0x200, 0x180, 0x080, 0x700
MODE_STOP, MODE_POS = 0, 2
ST_READY, ST_RUN, ST_FAULT = 1, 2, 3
HEART_TIMEOUT = 0.30           # 心跳多久没来算掉线 s（示例；驱动板 10 Hz 发心跳）
TRACK_MAX = 2.0                # 跟踪误差上限 °（示例）
FAULTS = {1: "过流", 2: "欠压", 3: "编码器", 4: "通信超时", 5: "输出端编码器", 6: "减速器 / 编码器不一致", 7: "抱闸"}


# ---------------------------------------------------------------- 运动学
def ik(x, y):
    """末端 (x, y) m → 关节角 (θ1, θ2) °；取“肘向一侧”（θ2 > 0）的解。"""
    c2 = (x * x + y * y - L1 * L1 - L2 * L2) / (2 * L1 * L2)
    if not -1.0 <= c2 <= 1.0:
        raise ValueError("够不着：({:.3f}, {:.3f})".format(x, y))
    t2 = math.acos(c2)
    t1 = math.atan2(y, x) - math.atan2(L2 * math.sin(t2), L1 + L2 * math.cos(t2))
    return math.degrees(t1), math.degrees(t2)


def fk(t1, t2):
    """关节角 ° → 末端 (x, y) m。"""
    a, b = math.radians(t1), math.radians(t1 + t2)
    return L1 * math.cos(a) + L2 * math.cos(b), L1 * math.sin(a) + L2 * math.sin(b)


def trapezoid(u, ta=0.2):
    """归一化梯形速度：u ∈ [0, 1] 是时间比例，返回走过的路程比例 s ∈ [0, 1]；加速、减速各占 ta。"""
    u = min(max(u, 0.0), 1.0)
    v = 1.0 / (1.0 - ta)                      # 匀速段速度（使总路程为 1）
    if u < ta:
        return 0.5 * v / ta * u * u
    if u > 1 - ta:
        return 1.0 - 0.5 * v / ta * (1 - u) ** 2
    return 0.5 * v * ta + v * (u - ta)


def cmd(mode, target=0):
    return bytes([mode]) + struct.pack("<i", int(target))


# ---------------------------------------------------------------- 主站
class Joint:
    def __init__(self, node):
        self.node = node
        self.state = None          # 最近一次心跳 / 状态帧里的状态
        self.fault = 0
        self.angle = None          # 驱动板报的关节角 °
        self.heart = None          # 最近一次心跳时刻
        self.cmd = None            # 最近一次发给它的目标 °


class Master:
    def __init__(self, p0, p1, t_move=1.5, nodes=(1, 2), hold=0.3, settle=0.3):
        self.p0, self.p1, self.t_move = p0, p1, t_move
        self.hold, self.settle = hold, settle
        self.j = {n: Joint(n) for n in nodes}
        self.phase = "等就绪"
        self.t_start = None          # 开始“原地稳住”的时刻
        self.events = []             # (时刻, 说明)：主站做的决定
        self.target = None           # 当前末端目标 (x, y)

    def log(self, t, text):
        self.events.append((round(t, 4), text))

    # 1. 收帧
    def receive(self, frames):
        for t, fid, data in frames:
            n = fid & 0x7F
            if n not in self.j:
                continue
            jt, base = self.j[n], fid & 0x780
            if base == ID_HEART and len(data) >= 1:
                jt.heart, jt.state = t, data[0]
            elif base == ID_STATUS and len(data) == 8:
                jt.state, jt.fault = data[0], data[1]
                jt.angle = struct.unpack_from("<h", data, 2)[0] / 100.0
            elif base == ID_EMCY and len(data) >= 1:
                jt.fault = data[0]
                self.estop(t, "关节 {} 报警：{}".format(n, FAULTS.get(data[0], data[0])))

    # 2. 监督
    def supervise(self, t):
        if self.phase in ("等就绪", "全停", "完成"):
            return
        for jt in self.j.values():
            if jt.heart is not None and t - jt.heart > HEART_TIMEOUT:
                self.estop(t, "关节 {} 心跳 {:.0f} ms 没来（掉线）".format(jt.node, (t - jt.heart) * 1000))
                return
            if jt.angle is not None and jt.cmd is not None and abs(jt.angle - jt.cmd) > TRACK_MAX:
                self.estop(t, "关节 {} 跟踪误差 {:.2f}°".format(jt.node, jt.angle - jt.cmd))
                return

    def estop(self, t, why):
        if self.phase != "全停":
            self.phase = "全停"
            self.log(t, why + " → 所有关节一起停")
            self._stop_now = True

    # 3. 算这一拍要发的帧
    def step(self, t, frames):
        """t：这一拍的时刻 s；frames：这一拍收到的帧 [(时刻, ID, 数据 bytes)]。返回要发的帧 [(ID, 数据)]。"""
        self._stop_now = False
        self.receive(frames)
        self.supervise(t)
        out = []
        if self._stop_now:                                   # 刚触发“全停”：给每个关节发一次“停”
            return [(ID_CMD + n, cmd(MODE_STOP)) for n in self.j]
        if self.phase == "等就绪":
            if all(jt.state == ST_READY and jt.heart is not None for jt in self.j.values()):
                self.phase, self.t_start = "稳住", t
                self.log(t, "两个关节都就绪 → 原地稳住（驱动板先稳住再松闸）")
            else:
                return out
        if self.phase in ("全停", "完成"):
            return out
        tau = t - self.t_start
        if tau < self.hold:
            u = 0.0
        else:
            if self.phase == "稳住":
                self.phase = "走直线"
                self.log(t, "末端走直线 ({:.2f}, {:.2f}) → ({:.2f}, {:.2f}) m，{:.1f} s".format(*self.p0, *self.p1, self.t_move))
            u = (tau - self.hold) / self.t_move
            if u >= 1.0 and self.phase == "走直线":
                self.phase = "到位稳住"
                self.log(t, "到终点 → 原地稳住")
        if tau >= self.hold + self.t_move + self.settle:
            self.phase = "完成"
            self.log(t, "完成 → 所有关节发“停”（停住、抱闸、关输出）")
            return [(ID_CMD + n, cmd(MODE_STOP)) for n in self.j]
        s = trapezoid(u)
        x = self.p0[0] + (self.p1[0] - self.p0[0]) * s
        y = self.p0[1] + (self.p1[1] - self.p0[1]) * s
        self.target = (x, y)
        th = ik(x, y)
        for jt, a in zip(self.j.values(), th):
            jt.cmd = a
            out.append((ID_CMD + jt.node, cmd(MODE_POS, round(a * 1000))))
        return out
