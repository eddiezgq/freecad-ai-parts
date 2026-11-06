// 关节驱动板 B 版的“功率级 + 被控对象”仿真外设（Renode，运行时编译）。第 102 轮。
//   WqTim1Motor：TIM1 子集（三相中心对齐 PWM）+ 逆变桥平均模型 + 三相永磁同步电机 d/q 模型 + 减速器 + 摆臂负载
//   WqAdc1    ：ADC1 注入组子集（TIM1 更新时刻采三相电流和母线电压，INA240 40 mV/A、零点 1.65 V；分压 6.8/108.8）
//   WqSsiEncoder：输出端绝对值编码器（SSI，挂在 SPI3；第 107 轮）：17 位单圈，从电机模型取输出轴角度（含注入的“减速器打滑”）
//   WqFdcan1  ：FDCAN1 子集（经典 CAN；消息 RAM 按 G4 布局：Rx FIFO0 0xB0 起、Tx 缓冲 0x278 起，每个元素 18 字）+ 仿真 CAN 主站
// 寄存器地址、偏移、位、中断号对照 ST 官方 CMSIS 头文件 stm32g431xx.h 与 HAL stm32g4xx_hal_fdcan.c 核对（见 test_drv_b_motor.py）。
// 电机参数：力矩常数 0.15 N·m/A、额定 1.27 N·m 取第 88 轮示例电机；减速比 100 取零件库 Harmonic Drive CSF-17-100；
// 其余（电阻、电感、极对数、惯量、摩擦、摆臂）是示例值。示例，不是某个型号。
using System;
using System.Collections.Generic;
using System.Globalization;
using Antmicro.Renode.Core;
using Antmicro.Renode.Logging;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class WqTim1Motor : IDoubleWordPeripheral, IKnownSize
    {
        // ---------------------------------------------------------------- 参数
        public const double Vbus0 = 48.0;            // 母线（第 88 轮）
        public const double Kt = 0.15;               // N·m/A（第 88 轮示例电机）
        public const int P = 5;                      // 极对数（示例）
        public const double Psi = Kt / (1.5 * P);    // 永磁磁链 Wb：Kt = 1.5·p·ψ（幅值不变变换）
        public const double Rs = 0.12;               // 相电阻 Ω（示例）
        public const double Ls = 0.0002;             // 相电感 H（示例，Ld = Lq）
        public const double Jm = 4.86e-5;            // 转子惯量 kg·m²（示例：取零件库同功率等级 SGM7J-04A 的值）
        public const double N = 100.0;               // 减速比（零件库 CSF-17-100）
        public const double Bv = 1e-5;               // 粘滞摩擦 N·m·s/rad（电机侧，示例）
        public const double Tc = 0.01;               // 库仑摩擦 N·m（电机侧，示例）
        public const double Mass = 1.0, Arm = 0.3;   // 摆臂：1 kg 集中质量在 0.3 m（示例）
        public const double Dead = 200e-9;           // 死区 s（第 88 轮：约 200 ns）
        public const double G = 9.80665;
        public const double Rshort = 0.02, Lshort = 2e-6;   // 注入的 A–B 相间短路（示例）

        public WqTim1Motor(IMachine machine)
        {
            this.machine = machine;
            pwm = new LimitTimer(machine.ClockSource, 170000000, this, "pwm", 4250, Direction.Ascending, false, WorkMode.Periodic, true);
            pwm.LimitReached += OnUpdate;
            Reset();
        }

        public long Size => 0x400;
        public GPIO IRQ { get; } = new GPIO();      // TIM1_UP（中断 25），本固件不用
        public WqAdc1 Adc { get; set; }

        // ---------------------------------------------------------------- 监视器命令
        public void LockRotor(bool v) { Advance(); locked = v; if(v) w = 0; }
        public void ExtraMass(double kg) { Advance(); extra = kg; }
        public void SetVbus(double v) { Advance(); vbus = v; }
        public void ShortAB(bool v) { Advance(); shortOn = v; if(!v) isc = 0; }
        public void StartJoint(double deg) { th = deg / 180 * Math.PI * N; }
        // 第 107 轮：减速器打滑——输出轴相对电机轴突然错开 deg 度（输出端编码器看得到，电机侧编码器看不到）
        public void Slip(double deg) { Advance(); slip += deg / 180 * Math.PI; }

        // 输出轴角度（rad，含打滑）：给输出端绝对值编码器
        public double OutputAngle(double t)
        {
            return (th + w * Math.Max(0, t - tLast)) / N + slip;
        }
        public string Truth()
        {
            Advance();
            var ia = Ia(); var ib = Ib();
            // 时刻 s、id A、iq A、电机转速 rpm、关节角 °、ia、ib、MOE、母线 V、电机轴计数、最近一次关管时刻、电角度 °、∫iq dt（A·s）
            return string.Format(CultureInfo.InvariantCulture, "M {0:F6} {1:F5} {2:F5} {3:F4} {4:F6} {5:F4} {6:F4} {7} {8:F4} {9:F2} {10:F7} {11:F3} {12:F9}",
                Now(), id, iq, w * 60 / (2 * Math.PI), (th / N + slip) * 180 / Math.PI, ia, ib, moe ? 1 : 0, vbus,
                th / (2 * Math.PI) * 10000.0, offTime, ((P * th) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) * 180 / Math.PI, iqInt);
        }

        // 编码器（WQ-ENCIF 经反射取）：电机轴走过的计数，2500 线 ×4
        public double EncoderCounts(double t)
        {
            return (th + w * Math.Max(0, t - tLast)) / (2 * Math.PI) * 10000.0;
        }

        // ---------------------------------------------------------------- 寄存器（偏移按 TIM_TypeDef）
        public uint ReadDoubleWord(long off)
        {
            switch(off)
            {
            case 0x00: return cr1;
            case 0x04: return cr2;
            case 0x0C: return dier;
            case 0x10: return sr;
            case 0x18: return ccmr1;
            case 0x1C: return ccmr2;
            case 0x20: return ccer;
            case 0x28: return psc;
            case 0x2C: return arr;
            case 0x30: return rcr;
            case 0x34: return ccrP[0];
            case 0x38: return ccrP[1];
            case 0x3C: return ccrP[2];
            case 0x44: return bdtr;
            default: return 0;
            }
        }

        public void WriteDoubleWord(long off, uint v)
        {
            switch(off)
            {
            case 0x00: cr1 = v; Apply(); break;
            case 0x04: cr2 = v; break;
            case 0x0C: dier = v; break;
            case 0x10: sr &= v; break;                       // 写 0 清
            case 0x14: if((v & 1) != 0) { LoadShadow(); } break;   // EGR.UG
            case 0x18: ccmr1 = v; break;
            case 0x1C: ccmr2 = v; break;
            case 0x20: ccer = v; break;
            case 0x28: psc = v & 0xFFFF; Apply(); break;
            case 0x2C: arr = v & 0xFFFF; Apply(); break;
            case 0x30: rcr = v & 0xFFFF; Apply(); break;
            case 0x34: ccrP[0] = v & 0xFFFF; break;
            case 0x38: ccrP[1] = v & 0xFFFF; break;
            case 0x3C: ccrP[2] = v & 0xFFFF; break;
            case 0x44:
                Advance();
                bdtr = v;
                moe = (v & (1u << 15)) != 0;                   // BDTR.MOE
                if(!moe) { offTime = Now(); }
                break;
            }
        }

        public void Reset()
        {
            cr1 = cr2 = dier = sr = ccmr1 = ccmr2 = ccer = psc = rcr = bdtr = 0;
            arr = 0xFFFF;
            ccrP = new uint[3]; ccrA = new uint[3];
            moe = false; locked = false; shortOn = false;
            id = iq = w = th = isc = iqInt = slip = 0; extra = 0; vbus = Vbus0;
            tLast = 0; offTime = -1;
            pwm.Enabled = false;
        }

        public double MoeOffTime => offTime;

        // ---------------------------------------------------------------- PWM 与更新事件
        // 中心对齐、RCR = 1：每个 PWM 周期一次更新事件，周期 = ARR·(PSC+1)·(RCR+1) / 170 MHz
        private void Apply()
        {
            bool cen = (cr1 & 1) != 0;
            ulong lim = (ulong)arr * (psc + 1) * (rcr + 1);
            if(lim == 0) lim = 1;
            pwm.Limit = lim;
            if(cen && !pwm.Enabled) { tLast = Now(); }
            pwm.Enabled = cen;
        }

        private void LoadShadow() { for(int k = 0; k < 3; k++) ccrA[k] = ccrP[k]; }

        private void OnUpdate()
        {
            Advance();                // 用这一周期生效的占空比积分到现在
            LoadShadow();             // 预装载：新的比较值从下个周期起生效
            sr |= 1;
            if(Adc != null) Adc.Convert(Ia(), Ib(), Ic(), vbus);
        }

        // ---------------------------------------------------------------- 物理
        private double Now() { return machine.LocalTimeSource.ElapsedVirtualTime.TotalSeconds; }

        private void Advance()
        {
            double t = Now();
            double dt = t - tLast;
            if(dt <= 0) return;
            int n = Math.Max(1, (int)Math.Ceiling(dt / 2e-6));
            double h = dt / n;
            for(int k = 0; k < n; k++) Step(h);
            tLast = t;
        }

        private double Duty(int k) { return arr == 0 ? 0 : Math.Min(1.0, (double)ccrA[k] / arr); }

        private void Step(double h)
        {
            double te = P * th;
            double c = Math.Cos(te), s = Math.Sin(te);
            double vd = 0, vq = 0, vab = 0;
            if(moe)
            {
                double da = Duty(0), db = Duty(1), dc = Duty(2), m = (da + db + dc) / 3;
                double[] cur = { Ia(), Ib(), Ic() };
                double dv = vbus * Dead * 20000.0;                 // 死区折算的电压误差（随电流方向）
                double va = vbus * (da - m) - dv * Math.Sign(cur[0]) + dv * (Math.Sign(cur[0]) + Math.Sign(cur[1]) + Math.Sign(cur[2])) / 3;
                double vb = vbus * (db - m) - dv * Math.Sign(cur[1]) + dv * (Math.Sign(cur[0]) + Math.Sign(cur[1]) + Math.Sign(cur[2])) / 3;
                double vc = -va - vb;
                double al = va, be = (vb - vc) / Math.Sqrt(3);
                vd = al * c + be * s;
                vq = -al * s + be * c;
                vab = vbus * (da - db);
            }
            else
            {
                // 关管：续流二极管把电流迅速回馈到母线，按反压 −Vbus·sign(i) 近似
                vd = -vbus * Math.Sign(id) * 0.5;
                vq = -vbus * Math.Sign(iq) * 0.5;
            }
            double we = P * w;
            double did = (vd - Rs * id + we * Ls * iq) / Ls;
            double diq = (vq - Rs * iq - we * Ls * id - we * Psi) / Ls;
            double nid = id + did * h, niq = iq + diq * h;
            if(!moe) { if(Math.Sign(nid) != Math.Sign(id)) nid = 0; if(Math.Sign(niq) != Math.Sign(iq)) niq = 0; }
            id = nid; iq = niq;
            iqInt += iq * h;
            // 相间短路电流（A→B），关管后按自身时间常数衰减
            if(shortOn || isc != 0)
            {
                double dis = ((shortOn && moe ? vab : 0) - Rshort * isc) / Lshort;
                isc += dis * h;
                if(!shortOn && Math.Abs(isc) < 1e-3) isc = 0;
            }
            // 机械：J·dω/dt = Te − 负载（重力经减速器折算 + 摩擦）
            double teM = 1.5 * P * Psi * iq;
            double thJ = th / N + slip;
            double tg = (Mass + extra) * G * Arm * Math.Sin(thJ) / N;
            double jl = Jm + (Mass + extra) * Arm * Arm / (N * N);
            double tf = Bv * w + Tc * Math.Tanh(w / 0.5);
            if(locked) { w = 0; return; }
            w += (teM - tg - tf) / jl * h;
            th += w * h;
        }

        private double Ia() { var te = P * th; return id * Math.Cos(te) - iq * Math.Sin(te) + isc; }
        private double Ib() { var te = P * th - 2 * Math.PI / 3; return id * Math.Cos(te) - iq * Math.Sin(te) - isc; }
        private double Ic() { var te = P * th + 2 * Math.PI / 3; return id * Math.Cos(te) - iq * Math.Sin(te); }

        private readonly IMachine machine;
        private readonly LimitTimer pwm;
        private uint cr1, cr2, dier, sr, ccmr1, ccmr2, ccer, psc, arr, rcr, bdtr;
        private uint[] ccrP, ccrA;
        private bool moe, locked, shortOn;
        private double id, iq, w, th, isc, extra, vbus, tLast, offTime, iqInt, slip;
    }

    // ==================================================================== ADC1 注入组
    public class WqAdc1 : IDoubleWordPeripheral, IKnownSize
    {
        public WqAdc1(IMachine machine, WqTim1Motor motor)
        {
            this.motor = motor;
            motor.Adc = this;
            Reset();
        }

        public long Size => 0x400;
        public GPIO IRQ { get; } = new GPIO();      // ADC1_2（中断 18）

        public void Convert(double ia, double ib, double ic, double vbus)
        {
            if((cr & 1) == 0 || (cr & (1u << 3)) == 0 || ((jsqr >> 7) & 3) == 0) return;   // ADEN、JADSTART、JEXTEN
            jdr[0] = Code(1.65 + 0.04 * ia);
            jdr[1] = Code(1.65 + 0.04 * ib);
            jdr[2] = Code(1.65 + 0.04 * ic);
            jdr[3] = Code(vbus * 6.8 / 108.8);
            isr |= (1u << 5) | (1u << 6);                  // JEOC、JEOS
            Update();
        }

        public uint ReadDoubleWord(long off)
        {
            switch(off)
            {
            case 0x00: return isr;
            case 0x04: return ier;
            case 0x08: return cr;
            case 0x4C: return jsqr;
            case 0x80: return jdr[0];
            case 0x84: return jdr[1];
            case 0x88: return jdr[2];
            case 0x8C: return jdr[3];
            default: return 0;
            }
        }

        public void WriteDoubleWord(long off, uint v)
        {
            switch(off)
            {
            case 0x00: isr &= ~v; Update(); break;          // 写 1 清
            case 0x04: ier = v; Update(); break;
            case 0x08:
                cr = v & ~(1u << 31);                        // ADCAL 立即完成
                if((v & 1) != 0) isr |= 1;                   // ADRDY
                break;
            case 0x4C: jsqr = v; break;
            }
        }

        public void Reset() { isr = ier = cr = jsqr = 0; jdr = new uint[4]; IRQ.Unset(); }

        private void Update() { IRQ.Set((isr & ier & (1u << 6)) != 0); }   // JEOS 中断
        private static uint Code(double v) { return (uint)Math.Max(0, Math.Min(4095, Math.Round(v / 3.3 * 4095))); }

        private readonly WqTim1Motor motor;
        private uint isr, ier, cr, jsqr;
        private uint[] jdr;
    }

    // ==================================================================== 输出端绝对值编码器（SSI，第 107 轮）
    // 帧（示例格式）：24 个时钟，第 1 位起始位恒 1，接着 17 位单圈位置（二进制、高位先出，131 072 计数/圈），再 1 位错误位（0 正常），其余补 0。
    // 两帧之间时钟停 ≥ 15 µs（SSI 的单稳态时间）编码器重新锁存位置；“线断”时 RS-485 接收端读回全 1。
    public class WqSsiEncoder : Antmicro.Renode.Peripherals.SPI.ISPIPeripheral
    {
        public const int BITS = 17;

        public WqSsiEncoder(IMachine machine, WqTim1Motor motor)
        {
            this.machine = machine;
            this.motor = motor;
            Reset();
        }

        public void Broken(bool v) { broken = v; }

        public byte Transmit(byte b)
        {
            double t = machine.LocalTimeSource.ElapsedVirtualTime.TotalSeconds;
            if(t - last > 15e-6 || nbyte >= 3)
            {
                double a = motor.OutputAngle(t) % (2 * Math.PI);
                if(a < 0) a += 2 * Math.PI;
                uint pos = (uint)Math.Floor(a / (2 * Math.PI) * (1 << BITS)) & ((1u << BITS) - 1);
                frame = (1u << 23) | (pos << 6);          // 起始位、17 位位置、错误位 0
                nbyte = 0;
            }
            last = t;
            byte r = broken ? (byte)0xFF : (byte)(frame >> (8 * (2 - nbyte)));
            nbyte++;
            return r;
        }

        public void FinishTransmission() { }
        public void Reset() { nbyte = 3; last = -1; frame = 0; }

        private readonly IMachine machine;
        private readonly WqTim1Motor motor;
        private bool broken;
        private int nbyte;
        private double last;
        private uint frame;
    }

    // ==================================================================== FDCAN1 + 仿真主站
    public class WqFdcan1 : IDoubleWordPeripheral, IKnownSize
    {
        public const ulong Ram = 0x4000A400;         // SRAMCAN_BASE
        public const uint RF0SA = 0xB0, TBSA = 0x278, ESIZE = 72;

        public WqFdcan1(IMachine machine)
        {
            this.machine = machine;
            Reset();
        }

        public long Size => 0x400;
        public GPIO IRQ { get; } = new GPIO();      // FDCAN1_IT0（中断 21）

        // 主站发一帧（标准 ID，数据十六进制）
        public void HostSend(int id, string hex)
        {
            var data = new List<byte>();
            for(int i = 0; i + 1 < hex.Length; i += 2) data.Add(byte.Parse(hex.Substring(i, 2), NumberStyles.HexNumber));
            log.Add(Line("rx", id, data.ToArray()));
            if((cccr & 1) != 0) return;                  // 还在初始化，收不到
            int fill = (int)(rxf0s & 0xF);
            if(fill >= 3) { return; }                    // FIFO 满，丢
            ulong a = Ram + RF0SA + (ulong)(putIdx * ESIZE);
            Bus.WriteDoubleWord(a, (uint)(id & 0x7FF) << 18);
            Bus.WriteDoubleWord(a + 4, (uint)data.Count << 16);
            for(int k = 0; k < 16; k++)
            {
                uint wv = 0;
                for(int b = 0; b < 4; b++) { int j = k * 4 + b; if(j < data.Count) wv |= (uint)data[j] << (8 * b); }
                if(k < 2) Bus.WriteDoubleWord(a + 8 + (ulong)(4 * k), wv);
            }
            putIdx = (putIdx + 1) % 3;
            fill++;
            rxf0s = (uint)fill | ((uint)getIdx << 8) | ((uint)putIdx << 16);
            ir |= 1;                                     // RF0N
            Update();
        }

        // 取出记录（每行：时刻 方向 ID 数据）；取后清空
        public string HostLog()
        {
            var s = string.Join("\n", log);
            log.Clear();
            return "CAN<<\n" + s + "\nCAN>>";
        }

        public uint ReadDoubleWord(long off)
        {
            switch(off)
            {
            case 0x018: return cccr;
            case 0x01C: return nbtp;
            case 0x050: return ir;
            case 0x054: return ie;
            case 0x058: return ils;
            case 0x05C: return ile;
            case 0x080: return rxgfc;
            case 0x090: return rxf0s;
            case 0x0C4: return (uint)3 | ((uint)tPut << 16);   // TXFQS：总有空位，放入索引轮转
            case 0x0C8: return 0;                              // TXBRP：立即发完
            default: return 0;
            }
        }

        public void WriteDoubleWord(long off, uint v)
        {
            switch(off)
            {
            case 0x018: cccr = v; break;
            case 0x01C: nbtp = v; break;
            case 0x050: ir &= ~v; Update(); break;
            case 0x054: ie = v; Update(); break;
            case 0x058: ils = v; break;
            case 0x05C: ile = v; Update(); break;
            case 0x080: rxgfc = v; break;
            case 0x094:                                        // RXF0A：确认读完
                {
                    int fill = (int)(rxf0s & 0xF);
                    if(fill > 0) { fill--; getIdx = ((int)v + 1) % 3; }
                    rxf0s = (uint)fill | ((uint)getIdx << 8) | ((uint)putIdx << 16);
                    break;
                }
            case 0x0CC:                                        // TXBAR：发送请求
                for(int k = 0; k < 3; k++)
                {
                    if((v & (1u << k)) == 0) continue;
                    ulong a = Ram + TBSA + (ulong)(k * ESIZE);
                    uint t0 = Bus.ReadDoubleWord(a), t1 = Bus.ReadDoubleWord(a + 4);
                    int dlc = (int)((t1 >> 16) & 0xF);
                    var d = new byte[Math.Min(8, dlc)];
                    for(int j = 0; j < d.Length; j++) d[j] = (byte)(Bus.ReadDoubleWord(a + 8 + (ulong)(j / 4 * 4)) >> (8 * (j % 4)));
                    if((cccr & 1) == 0) log.Add(Line("tx", (int)((t0 >> 18) & 0x7FF), d));
                    tPut = (k + 1) % 3;
                }
                break;
            }
        }

        public void Reset()
        {
            cccr = 1; nbtp = ir = ie = ils = ile = rxgfc = rxf0s = 0;
            putIdx = getIdx = tPut = 0;
            log = new List<string>();
            IRQ.Unset();
        }

        private IBusController Bus => machine.SystemBus;
        private void Update() { IRQ.Set((ir & ie & 1) != 0 && (ile & 1) != 0); }
        private string Line(string dir, int id, byte[] d)
        {
            return string.Format(CultureInfo.InvariantCulture, "F {0:F6} {1} {2:X3} {3}",
                machine.LocalTimeSource.ElapsedVirtualTime.TotalSeconds, dir, id, BitConverter.ToString(d).Replace("-", ""));
        }

        private readonly IMachine machine;
        private uint cccr, nbtp, ir, ie, ils, ile, rxgfc, rxf0s;
        private int putIdx, getIdx, tPut;
        private List<string> log;
    }

    // ==================================================================== RCC（只做固件等待的几个就绪位）
    public class WqRcc : IDoubleWordPeripheral, IKnownSize
    {
        public WqRcc() { Reset(); }
        public long Size => 0x400;

        public uint ReadDoubleWord(long off)
        {
            uint v;
            mem.TryGetValue(off, out v);
            if(off == 0x00)
            {
                if((v & (1u << 8)) != 0) v |= 1u << 10;       // HSION → HSIRDY
                if((v & (1u << 24)) != 0) v |= 1u << 25;      // PLLON → PLLRDY
            }
            if(off == 0x08) v = (v & ~0xCu) | ((v & 3) << 2);  // SWS 跟随 SW
            return v;
        }

        public void WriteDoubleWord(long off, uint v) { mem[off] = v; }
        public void Reset() { mem = new Dictionary<long, uint> { { 0x00, 1u << 8 }, { 0x08, 1 } }; }   // 上电：HSI16 开、系统时钟 HSI16

        private Dictionary<long, uint> mem;
    }
}
