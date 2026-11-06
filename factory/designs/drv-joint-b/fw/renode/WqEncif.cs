// WQ-ENCIF 寄存器级模型 + 虚拟电机（Renode 外设，挂在 spi1 上）。第 100 轮：驱动板 B 版固件仿真。
// 规则同第 92 轮规格（factory/designs/wq-encif/rtl/wq_encif.v 文件头、model/encif.py）：
//   一帧 40 位 = 8 位命令（位 7：1 写 0 读；低 7 位地址）+ 32 位数据，高位先出；读在命令字节收完时取快照；写在第 40 位生效。
//   寄存器 0 ID "ENC1"；1 CTRL（位 0 使能、1 反向、2 Z 清零、4–7 滤波）；2 STATUS（位 0 方向、1 错误、2 Z 已锁存、3–5 A/B/Z 电平；
//   写 1 清位 1、位 2）；3 CNT（可写）；4 IDX（Z 上升沿时的计数）。
// 芯片 RTL 已在第 92/93 轮与 Python 模型逐拍比对；这里只做寄存器级，跑得快。示例，芯片未流片。
//
// 虚拟电机：转速曲线（时刻 s : 转速 rpm，分段线性）积分成位置（计数，2500 线 ×4 = 10000 计数/转）；
// Z 在绝对位置为 10000 的整数倍处；芯片计数 = 复位释放后走过的计数。
using System;
using System.Collections.Generic;
using System.Globalization;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.SPI;

namespace Antmicro.Renode.Peripherals.SPI
{
    public class WqEncif : ISPIPeripheral, IGPIOReceiver
    {
        public const int CPR = 10000;
        public const uint ID = 0x454E4331;

        public WqEncif(IMachine machine)
        {
            this.machine = machine;
            prof = new List<double[]> { new double[] { 0, 0 } };
            Reset();
        }

        // ---------------------------------------------------------------- 监视器命令（仿真脚本用）
        // 转速曲线，如 "0:0,0.1:600,0.5:600"
        public void Profile(string spec)
        {
            var l = new List<double[]>();
            foreach(var seg in spec.Split(','))
            {
                var kv = seg.Split(':');
                l.Add(new double[] { double.Parse(kv[0], CultureInfo.InvariantCulture), double.Parse(kv[1], CultureInfo.InvariantCulture) });
            }
            prof = l;
        }

        public void StartPos(int counts) { pos0 = counts; plast = Floor(PosAt(Now())); }
        public void InjectError() { Update(); err = 1; errInjected++; }
        public void Absent(bool v) { absent = v; }
        public string Truth()
        {
            var t = Now();
            var p = PosAt(t);
            return string.Format(CultureInfo.InvariantCulture, "T {0:F6} {1:F3} {2:F3} {3} {4}", t, p - pos0, RpmAt(t), Floor(p), relBase);
        }

        // ---------------------------------------------------------------- SPI
        public byte Transmit(byte b)
        {
            if(absent || !selected || !rstn)
            {
                return 0;
            }
            byte ret = 0;
            if(nbyte == 0)
            {
                cmd = b;
                if((cmd & 0x80) == 0)
                {
                    Update();
                    snap = Reg(cmd & 0x7F);
                }
            }
            else if(nbyte <= 4)
            {
                if((cmd & 0x80) == 0)
                {
                    ret = (byte)(snap >> (8 * (4 - nbyte)));
                }
                else
                {
                    wdata = (wdata << 8) | b;
                    if(nbyte == 4)
                    {
                        Update();
                        Write(cmd & 0x7F, wdata);
                    }
                }
            }
            nbyte++;
            frames += nbyte == 5 ? 1 : 0;
            return ret;
        }

        public void FinishTransmission() { }

        // GPIO 0：片选（低有效，PA4）；GPIO 1：复位（低有效，PB1）
        public void OnGPIO(int number, bool value)
        {
            if(number == 0)
            {
                selected = !value;
                nbyte = 0;
                wdata = 0;
            }
            else if(number == 1)
            {
                if(!value)
                {
                    ResetRegs();
                }
                else if(!rstn)
                {
                    plast = Floor(PosAt(Now()));
                    relBase = plast;
                }
                rstn = value;
            }
        }

        public void Reset()
        {
            ResetRegs();
            selected = false;
            rstn = true;
            nbyte = 0;
            plast = Floor(PosAt(Now()));
            relBase = plast;
        }

        public int Frames => frames;

        // ---------------------------------------------------------------- 寄存器
        private void ResetRegs()
        {
            en = 1; inv = 0; zclr = 0; flen = 3;
            dir = 1; err = 0; ivld = 0;
            cnt = 0; idx = 0;
        }

        private uint Reg(int a)
        {
            switch(a)
            {
            case 0: return ID;
            case 1: return (uint)(en | inv << 1 | zclr << 2 | flen << 4);
            case 2:
                var ph = ((plast % 4) + 4) % 4;               // 正交相位 0..3：A 领先 B
                int ra = (ph == 1 || ph == 2) ? 1 : 0, rb = (ph == 2 || ph == 3) ? 1 : 0;
                int rz = (((plast % CPR) + CPR) % CPR) == 0 ? 1 : 0;
                return (uint)(dir | err << 1 | ivld << 2 | ra << 3 | rb << 4 | rz << 5);
            case 3: return cnt;
            case 4: return idx;
            default: return 0;
            }
        }

        private void Write(int a, uint v)
        {
            if(a == 1) { en = (int)(v & 1); inv = (int)(v >> 1 & 1); zclr = (int)(v >> 2 & 1); flen = (int)(v >> 4 & 0xF); }
            else if(a == 2) { if((v & 2) != 0) err = 0; if((v & 4) != 0) ivld = 0; }
            else if(a == 3) { cnt = v; }
        }

        // 把虚拟电机推进到当前时刻：逐个处理途中的 Z
        private void Update()
        {
            if(!rstn)
            {
                return;
            }
            long p = Floor(PosAt(Now()));
            while(p != plast)
            {
                int s = p > plast ? 1 : -1;
                // 下一个 Z（10000 的整数倍）：正转取 (plast, p]，反转取 [p, plast)
                long z = s > 0 ? FloorDiv(plast, CPR) * CPR + CPR : FloorDiv(plast - 1, CPR) * CPR;
                bool hit = s > 0 ? z <= p : z >= p;
                long to = hit ? z : p;
                Step(to - plast, s);
                plast = to;
                if(hit)
                {
                    idx = cnt; ivld = 1;
                    if(zclr == 1 && en == 1)
                    {
                        cnt = 0;
                    }
                }
            }
        }

        private void Step(long d, int s)
        {
            if(d == 0 || en == 0)
            {
                return;
            }
            cnt = (uint)(cnt + (inv == 1 ? -d : d));
            dir = (s > 0) ^ (inv == 1) ? 1 : 0;
        }

        // ---------------------------------------------------------------- 虚拟电机
        private double Now() { return machine.LocalTimeSource.ElapsedVirtualTime.TotalSeconds; }

        private double RpmAt(double t)
        {
            if(t <= prof[0][0]) return prof[0][1];
            for(int i = 1; i < prof.Count; i++)
            {
                if(t <= prof[i][0])
                {
                    var a = prof[i - 1]; var b = prof[i];
                    return a[1] + (b[1] - a[1]) * (t - a[0]) / (b[0] - a[0]);
                }
            }
            return prof[prof.Count - 1][1];
        }

        // 绝对位置（计数）= 起始位置 + ∫ rpm/60·CPR dt（分段线性，梯形精确积分）
        private double PosAt(double t)
        {
            double acc = 0, k = CPR / 60.0;
            double t0 = 0, r0 = RpmAt(0);
            var pts = new List<double>();
            foreach(var q in prof) if(q[0] > 0 && q[0] < t) pts.Add(q[0]);
            pts.Add(t);
            foreach(var t1 in pts)
            {
                var r1 = RpmAt(t1);
                acc += (r0 + r1) / 2 * (t1 - t0) * k;
                t0 = t1; r0 = r1;
            }
            return pos0 + acc;
        }

        private static long Floor(double x) { return (long)Math.Floor(x + 1e-9); }
        private static long FloorDiv(long a, long b) { return (long)Math.Floor((double)a / b); }

        private readonly IMachine machine;
        private List<double[]> prof;
        private double pos0;
        private long plast, relBase;
        private bool selected, rstn, absent;
        private int nbyte, frames, errInjected;
        private byte cmd;
        private uint snap, wdata, cnt, idx;
        private int en, inv, zclr, flen, dir, err, ivld;
    }
}
