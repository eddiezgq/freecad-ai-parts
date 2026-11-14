// 平缝机控制器 CTRL-LS 的“功率级 + 被控对象”仿真外设（Renode，运行时编译）。第 159 轮 159f；写法照驱动板 B 版 WqDrive.cs（第 102 轮）。
//   WqSewMotor：TIM1 子集（三相中心对齐 PWM、MOE）+ 功率模块逆变平均模型（死区 1 µs，SD 脚 PB12 拉低关断）+ 三相永磁同步电机 d/q 模型
//               + 主轴负载：第 138 轮 G2 一转负载表（gen_load.py 生成，与 159c 的伺服复算同一张表、同一个算法）
//               + 编码器 Z 相（针杆最高点，主轴 0°；经 SN74LVC14 反相，低有效，宽 4 个计数）→ PA6
//               + 四个电磁铁（剪线 PA5、拨线 PA11、倒缝 PA12、抬压脚 PA15，引脚低 = 吸合）：记下每次吸合 / 释放的时刻和主轴转角；
//                 剪线电磁铁吸合、主轴在 200°–330° 时动刀切线，负载另加 0.15 N·m（与 gc_sim.py 相同，示例）
//               + 脚踏板霍尔电压（监视器命令 Pedal 给）；注入：针卡住（Jam，主轴瞬间卡死）、阻力太大（ExtraLoad，干摩擦）
//   WqTim4Enc ：TIM4 编码器模式子集（2500 线 ×4 = 10000 计数/转，16 位计数器）
//   WqAdc12   ：ADC1、ADC2 注入组子集（TIM1 更新时刻同时转换）：片内运放输出（三相电流，V = 1.65 − 0.1875 × i）、母线（22 k / 3.022 M）、脚踏（20 k / 30 k）
//   WqRcc     ：时钟就绪位（同 B 版）
// 寄存器偏移、位对照 ST 官方 CMSIS 头文件 stm32g431xx.h；运放接 ADC 的内部通道号对照 ST 官方 LL 驱动 stm32g4xx_ll_adc.h。
// 电机：力矩常数 0.496 N·m/A、惯量（转子 4×10⁻⁴ + 负载 1.24×10⁻⁴ kg·m²）取 159c；极对数、电阻、电感是示例值（第 138 轮电机未选型）。示例，不是某个型号。
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using Antmicro.Renode.Core;
using Antmicro.Renode.Peripherals.Bus;
using Antmicro.Renode.Peripherals.Timers;
using Antmicro.Renode.Time;

namespace Antmicro.Renode.Peripherals.Miscellaneous
{
    public class WqSewMotor : IDoubleWordPeripheral, IKnownSize, IGPIOReceiver
    {
        // ---------------------------------------------------------------- 参数
        public const double Vbus0 = 390.0;           // 母线（159b 计算书：校正输出 390 V）
        public const double Kt = 0.496;              // N·m/A（159c）
        public const int P = 4;                      // 极对数（示例）
        public const double Psi = Kt / (1.5 * P);    // 永磁磁链 Wb：Kt = 1.5·p·ψ
        public const double Rs = 1.2;                // 相电阻 Ω（示例）
        public const double Ls = 0.004;              // 相电感 H（示例，Ld = Lq）
        public const double J = 4e-4 + 1.24e-4;      // 转子 + 机头负载 kg·m²（第 138 轮 G2、159c）
        public const double Dead = 1e-6;             // 死区 s（设计描述 ipm_inverter.t_dead）
        public const double Fpwm = 16000;            // 设计描述 ipm_inverter.f_pwm
        public const int Cpr = 10000;                // 2500 线 ×4
        public const double TrimT = 0.15, TrimOn = 200, TrimOff = 330;   // 剪线动刀（gc_sim.py，示例）

        public WqSewMotor(IMachine machine, IGPIOReceiver zPort = null)
        {
            this.machine = machine;
            this.zPort = zPort;
            pwm = new LimitTimer(machine.ClockSource, 170000000, this, "pwm", 5312, Direction.Ascending, false, WorkMode.Periodic, true);
            pwm.LimitReached += OnUpdate;
            Reset();
        }

        public long Size => 0x400;
        public WqAdc12 Adc { get; set; }

        // ---------------------------------------------------------------- 监视器命令
        public void LoadTable(string path)
        {
            var w = new List<double>(); var a = new List<double>(); var b = new List<double>();
            foreach(var ln in File.ReadAllLines(path))
            {
                if(ln.StartsWith("#") || ln.Trim() == "") continue;
                var f = ln.Split(' ');
                if(f[0] == "w5000") { w5 = double.Parse(f[1], CultureInfo.InvariantCulture); continue; }
                a.Add(double.Parse(f[1], CultureInfo.InvariantCulture));
                b.Add(double.Parse(f[2], CultureInfo.InvariantCulture));
            }
            tIn = a.ToArray(); tRs = b.ToArray();
        }
        public void StartAngle(double deg) { th = deg / 180 * Math.PI; }
        public void Pedal(double v) { Advance(); pedal = v; }
        public void Jam(bool v) { Advance(); jam = v; if(v) w = 0; }
        // 阻力太大（布太厚、线卡住）：另加一个干摩擦力矩 N·m，转着时阻碍转动，停着时电机力矩不超过它就转不动
        public void ExtraLoad(double nm) { Advance(); extra = nm; }
        public void SetVbus(double v) { Advance(); vbus = v; }
        public double PedalV => pedal;
        public double Vbus => vbus;

        public string Truth()
        {
            Advance();
            // 时刻 s、转速 r/min、主轴转角 °（0 = 针杆最高点）、id、iq、ia、ib、ic A、输出开着（MOE 且 SD 高）、母线 V、电机力矩 N·m、负载力矩 N·m、
            // 电磁铁（位 0 剪线、1 拨线、2 倒缝、3 抬压脚）、脚踏 V、累计转过的圈数
            return string.Format(CultureInfo.InvariantCulture, "M {0:F6} {1:F3} {2:F4} {3:F4} {4:F4} {5:F4} {6:F4} {7:F4} {8} {9:F2} {10:F4} {11:F4} {12} {13:F3} {14:F5}",
                Now(), w * 30 / Math.PI, Deg(), id, iq, Ia(), Ib(), Ic(), On() ? 1 : 0, vbus, 1.5 * P * Psi * iq, lastTl,
                SolBits(), pedal, th / (2 * Math.PI));
        }

        // 电磁铁动作记录：一行一次，“S 时刻 号 1/0 转角°”
        public string SolLog()
        {
            var s = new System.Text.StringBuilder();
            foreach(var e in log) s.AppendLine(e);
            return s.ToString();
        }

        public double EncoderCounts(double t) { return (th + w * Math.Max(0, t - tLast)) / (2 * Math.PI) * Cpr; }

        // ---------------------------------------------------------------- GPIO：0 剪线 PA5、1 拨线 PA11、2 倒缝 PA12、3 抬压脚 PA15、4 IPM_SD PB12
        public void OnGPIO(int number, bool value)
        {
            Advance();
            if(number == 4) { sd = value; return; }
            if(number < 0 || number > 3) return;
            // 复位时引脚是输入、外部上拉（电磁铁不动作）；GPIO 口模型复位时把连线置低，固件第一次把引脚置高以前的低电平不算吸合
            if(value) armed[number] = true;
            if(!armed[number]) return;
            bool on = !value;                                  // 引脚低 = 吸合
            if(sol[number] == on) return;
            sol[number] = on;
            log.Add(string.Format(CultureInfo.InvariantCulture, "S {0:F6} {1} {2} {3:F3}", Now(), number, on ? 1 : 0, Deg()));
        }

        // ---------------------------------------------------------------- 寄存器（偏移按 TIM_TypeDef）
        public uint ReadDoubleWord(long off)
        {
            switch(off)
            {
            case 0x00: return cr1;
            case 0x04: return cr2;
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
            case 0x14: if((v & 1) != 0) { LoadShadow(); } break;
            case 0x18: ccmr1 = v; break;
            case 0x1C: ccmr2 = v; break;
            case 0x20: ccer = v; break;
            case 0x28: psc = v & 0xFFFF; Apply(); break;
            case 0x2C: arr = v & 0xFFFF; Apply(); break;
            case 0x30: rcr = v & 0xFFFF; Apply(); break;
            case 0x34: ccrP[0] = v & 0xFFFF; break;
            case 0x38: ccrP[1] = v & 0xFFFF; break;
            case 0x3C: ccrP[2] = v & 0xFFFF; break;
            case 0x44: Advance(); bdtr = v; moe = (v & (1u << 15)) != 0; break;
            }
        }

        public void Reset()
        {
            cr1 = cr2 = ccmr1 = ccmr2 = ccer = psc = rcr = bdtr = 0;
            arr = 0xFFFF;
            ccrP = new uint[3]; ccrA = new uint[3];
            moe = false; sd = false; jam = false; extra = 0;
            sol = new bool[4]; armed = new bool[4]; log = new List<string>();
            id = iq = w = th = 0; vbus = Vbus0; pedal = 1.2; lastTl = 0;
            tLast = 0; zLevel = -1;
            pwm.Enabled = false;
        }

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
            Advance();
            LoadShadow();
            if(Adc != null) Adc.Convert(Ia(), Ib(), Ic(), vbus, pedal);
        }

        // ---------------------------------------------------------------- 物理
        private double Now() { return machine.LocalTimeSource.ElapsedVirtualTime.TotalSeconds; }
        private bool On() { return moe && sd; }
        private double Deg() { var d = th % (2 * Math.PI); if(d < 0) d += 2 * Math.PI; return d * 180 / Math.PI; }
        private int SolBits() { int b = 0; for(int k = 0; k < 4; k++) if(sol[k]) b |= 1 << k; return b; }

        private void Advance()
        {
            double t = Now();
            double dt = t - tLast;
            if(dt > 0)
            {
                int n = Math.Max(1, (int)Math.Ceiling(dt / 2e-6));
                double h = dt / n;
                for(int k = 0; k < n; k++) Step(h);
                tLast = t;
            }
            // Z 相：主轴在 0°–0.144°（4 个计数）时引脚低
            double c = th / (2 * Math.PI) * Cpr % Cpr;
            if(c < 0) c += Cpr;
            int z = c < 4 ? 0 : 1;
            // 直接给 GPIOA 第 6 脚输入；每次都写（GPIO 口复位会清掉输入状态，只在变化时写会漏掉）
            if(zPort != null) { zLevel = z; zPort.OnGPIO(6, z == 1); }
        }

        private double Duty(int k) { return arr == 0 ? 0 : Math.Min(1.0, (double)ccrA[k] / arr); }

        private double Load(double ww)
        {
            if(tIn == null) return 0;
            double d = Deg();
            int i = (int)Math.Round(d / 0.5) % tIn.Length;
            double r = ww / w5;
            double t = tIn[i] * r * r + (ww > 1 ? tRs[i] : 0.0);
            if(sol[0] && d >= TrimOn && d <= TrimOff) t += TrimT;
            return t;
        }

        private void Step(double h)
        {
            double te = P * th;
            double c = Math.Cos(te), s = Math.Sin(te);
            double vd, vq;
            if(On())
            {
                double da = Duty(0), db = Duty(1), dc = Duty(2), m = (da + db + dc) / 3;
                double[] cur = { Ia(), Ib(), Ic() };
                double dv = vbus * Dead * Fpwm;
                double sm = (Math.Sign(cur[0]) + Math.Sign(cur[1]) + Math.Sign(cur[2])) / 3.0;
                double va = vbus * (da - m) - dv * (Math.Sign(cur[0]) - sm);
                double vb = vbus * (db - m) - dv * (Math.Sign(cur[1]) - sm);
                double vc = -va - vb;
                double al = va, be = (vb - vc) / Math.Sqrt(3);
                vd = al * c + be * s;
                vq = -al * s + be * c;
            }
            else
            {
                vd = -vbus * Math.Sign(id) * 0.5;               // 关断：续流回母线（同 B 版）
                vq = -vbus * Math.Sign(iq) * 0.5;
            }
            double we = P * w;
            double nid = id + (vd - Rs * id + we * Ls * iq) / Ls * h;
            double niq = iq + (vq - Rs * iq - we * Ls * id - we * Psi) / Ls * h;
            if(!On()) { if(Math.Sign(nid) != Math.Sign(id)) nid = 0; if(Math.Sign(niq) != Math.Sign(iq)) niq = 0; }
            id = nid; iq = niq;
            double tm = 1.5 * P * Psi * iq;
            double tl = Load(w);
            lastTl = tl;
            if(jam) { w = 0; return; }
            if(extra > 0)
            {
                if(Math.Abs(w) < 1e-3 && Math.Abs(tm - tl) <= extra) { w = 0; return; }   // 卡着不动
                double w2 = w + (tm - tl - extra * Math.Sign(w == 0 ? tm - tl : w)) / J * h;
                if(w != 0 && Math.Sign(w2) != Math.Sign(w)) { w = 0; return; }
                w = w2;
                th += w * h;
                return;
            }
            w += (tm - tl) / J * h;
            th += w * h;
        }

        private double Ia() { var te = P * th; return id * Math.Cos(te) - iq * Math.Sin(te); }
        private double Ib() { var te = P * th - 2 * Math.PI / 3; return id * Math.Cos(te) - iq * Math.Sin(te); }
        private double Ic() { var te = P * th + 2 * Math.PI / 3; return id * Math.Cos(te) - iq * Math.Sin(te); }

        private readonly IMachine machine;
        private readonly LimitTimer pwm;
        private uint cr1, cr2, ccmr1, ccmr2, ccer, psc, arr, rcr, bdtr;
        private uint[] ccrP, ccrA;
        private bool moe, sd, jam;
        private bool[] sol, armed;
        private List<string> log;
        private double id, iq, w, th, vbus, tLast, pedal, lastTl, extra, w5 = 523.598776;
        private double[] tIn, tRs;
        private int zLevel;
        private readonly IGPIOReceiver zPort;
    }

    // ==================================================================== TIM4 编码器模式
    // 只做编码器模式 3（SMCR.SMS = 0011，A、B 两路边沿都计）：CNT = 开计数器以来电机转过的计数（16 位回绕）。其余模式读 0。
    public class WqTim4Enc : IDoubleWordPeripheral, IKnownSize
    {
        public WqTim4Enc(IMachine machine, WqSewMotor motor) { this.machine = machine; this.motor = motor; Reset(); }
        public long Size => 0x400;

        public uint ReadDoubleWord(long off)
        {
            switch(off)
            {
            case 0x00: return cr1;
            case 0x08: return smcr;
            case 0x18: return ccmr1;
            case 0x20: return ccer;
            case 0x24: return Cnt();
            case 0x2C: return arr;
            default: return 0;
            }
        }

        public void WriteDoubleWord(long off, uint v)
        {
            switch(off)
            {
            case 0x00:
                if((v & 1) != 0 && (cr1 & 1) == 0) base0 = Math.Floor(motor.EncoderCounts(T()));
                cr1 = v; break;
            case 0x08: smcr = v; break;
            case 0x18: ccmr1 = v; break;
            case 0x20: ccer = v; break;
            case 0x2C: arr = v & 0xFFFF; break;
            }
        }

        public void Reset() { cr1 = smcr = ccmr1 = ccer = 0; arr = 0xFFFF; base0 = 0; }

        private uint Cnt()
        {
            uint sms = (smcr & 7) | (((smcr >> 16) & 1) << 3);
            if((cr1 & 1) == 0 || sms != 3) return 0;
            double c = Math.Floor(motor.EncoderCounts(T())) - base0;
            long n = (long)c % ((long)arr + 1);
            if(n < 0) n += (long)arr + 1;
            return (uint)n;
        }

        private double T() { return machine.LocalTimeSource.ElapsedVirtualTime.TotalSeconds; }
        private readonly IMachine machine;
        private readonly WqSewMotor motor;
        private uint cr1, smcr, ccmr1, ccer, arr;
        private double base0;
    }

    // ==================================================================== ADC1 + ADC2 注入组（0x5000 0000，ADC2 在 +0x100，公共寄存器 +0x300）
    public class WqAdc12 : IDoubleWordPeripheral, IKnownSize
    {
        public WqAdc12(IMachine machine, WqSewMotor motor) { this.motor = motor; motor.Adc = this; Reset(); }
        public long Size => 0x400;
        public GPIO IRQ { get; } = new GPIO();      // ADC1_2（中断 18）

        public void Convert(double ia, double ib, double ic, double vbus, double pedal)
        {
            for(int k = 0; k < 2; k++)
            {
                if((cr[k] & 1) == 0 || (cr[k] & (1u << 3)) == 0 || ((jsqr[k] >> 7) & 3) == 0) continue;   // ADEN、JADSTART、JEXTEN
                int n = (int)(jsqr[k] & 3) + 1;
                for(int j = 0; j < n; j++)
                {
                    uint ch = (jsqr[k] >> (9 + 6 * j)) & 0x1F;
                    double v = 0;
                    if(k == 0 && ch == 13) v = 1.65 - 0.1875 * ia;          // OPAMP1：U 相
                    else if(k == 0 && ch == 1) v = vbus * 22.0 / 3022.0;     // PA0：母线
                    else if(k == 0 && ch == 12) v = pedal * 20.0 / 30.0;     // PB1：脚踏
                    else if(k == 1 && ch == 16) v = 1.65 - 0.1875 * ib;      // OPAMP2：V 相
                    else if(k == 1 && ch == 18) v = 1.65 - 0.1875 * ic;      // OPAMP3：W 相
                    jdr[k, j] = Code(v);
                }
                isr[k] |= (1u << 5) | (1u << 6);
            }
            Update();
        }

        public uint ReadDoubleWord(long off)
        {
            int k = (int)(off >> 8);
            long o = off & 0xFF;
            if(k > 1) return k == 3 && o == 0x08 ? ccr : 0;
            switch(o)
            {
            case 0x00: return isr[k];
            case 0x04: return ier[k];
            case 0x08: return cr[k];
            case 0x4C: return jsqr[k];
            case 0x80: return jdr[k, 0];
            case 0x84: return jdr[k, 1];
            case 0x88: return jdr[k, 2];
            case 0x8C: return jdr[k, 3];
            default: return 0;
            }
        }

        public void WriteDoubleWord(long off, uint v)
        {
            int k = (int)(off >> 8);
            long o = off & 0xFF;
            if(k > 1) { if(k == 3 && o == 0x08) ccr = v; return; }
            switch(o)
            {
            case 0x00: isr[k] &= ~v; Update(); break;
            case 0x04: ier[k] = v; Update(); break;
            case 0x08:
                cr[k] = v & ~(1u << 31);                    // ADCAL 立即完成
                if((v & 1) != 0) isr[k] |= 1;               // ADRDY
                break;
            case 0x4C: jsqr[k] = v; break;
            }
        }

        public void Reset() { isr = new uint[2]; ier = new uint[2]; cr = new uint[2]; jsqr = new uint[2]; jdr = new uint[2, 4]; ccr = 0; IRQ.Unset(); }

        private void Update() { IRQ.Set((((isr[0] & ier[0]) | (isr[1] & ier[1])) & (1u << 6)) != 0); }   // JEOS 中断（两个 ADC 共用中断 18）
        private static uint Code(double v) { return (uint)Math.Max(0, Math.Min(4095, Math.Round(v / 3.3 * 4095))); }

        private readonly WqSewMotor motor;
        private uint[] isr, ier, cr, jsqr;
        private uint[,] jdr;
        private uint ccr;
    }

    // ==================================================================== RCC：固件等待的就绪位（同 B 版）
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
        public void Reset() { mem = new Dictionary<long, uint> { { 0x00, 1u << 8 }, { 0x08, 1 } }; }

        private Dictionary<long, uint> mem;
    }
}
