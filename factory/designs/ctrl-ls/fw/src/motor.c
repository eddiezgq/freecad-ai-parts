/* 主轴电机控制（第 159 轮 159f）。一次 ADC 注入组转换完成中断 = 一个 16 kHz 电流环周期：
 *   读三相电流、母线、脚踏 → 过流保护 → 读编码器（TIM4）、看 Z 相（PA6）→ 电角度 → Clarke / Park → d、q 两个 PI → 反 Park → SVPWM
 *   每 8 次（2 kHz）速度环，每 16 次（1 kHz）位置环、爬坡、保护、缝纫状态机节拍。
 * 磁场定向控制的写法沿用驱动板 B 版 motor.c（第 102 轮）；速度环、停针的参数取 159c 的主轴伺服复算（第 138 轮 gc_sim.py 的模型）：
 *   速度环带宽 40 Hz（Kp = J·ωs / Kt，积分时间 4 / ωs）、按给定的加速度加前馈 J·a、不加负载前馈；
 *   停针：位置环 Kp = ωs / 4，限速 300 r/min，目标是前面最近的那个转角。
 * 引脚（按原理图 U10）：TIM1 CH1–3 = PA8–PA10、CH1N–3N = PB13–PB15（AF6）；PB12 = IPM_SD（高 = 工作，拉低关断功率模块）；
 *   U / V / W 相电流 PA1 / PA7 / PB0 → 片内运放 OPAMP1 / 2 / 3（PGA 8 倍）→ ADC1_IN13 / ADC2_IN16 / ADC2_IN18；
 *   母线 PA0 = ADC1_IN1（3 MΩ / 22 kΩ）；脚踏 PB1 = ADC1_IN12（10 k / 20 k）；编码器 A / B = PB6 / PB7（TIM4 编码器模式，AF2）、Z = PA6。
 * 编码器信号经 SN74LVC14 反相：A、B 同时反相不改变计数方向；Z 相在主控引脚上是低电平有效。
 * 电流换算（设计描述 low_side_sense）：V_运放 = 8 × (V_采样 · 15/16 + 3.3/16)，下桥采样 V_采样 = −i × 25 mΩ（电流流向电机为正）
 *   → V = 1.65 − 0.1875 × i；零点开机时实测。 */
#include "motor.h"
#include "regs.h"

volatile mc_t mc;

#define TS (1.0f / PWM_HZ)
#define PI_F 3.14159265f
#define TWO_PI 6.28318531f
#define A_PER_CODE (3.3f / 4095.0f / 0.1875f)
#define V_PER_CODE (3.3f / 4095.0f * (3022.0f / 22.0f))
#define PEDAL_PER_CODE (3.3f / 4095.0f * 1.5f)

/* 电流环：带宽 1 kHz，Kp = L·ωc，Ki = R·ωc（零极点对消，同 B 版） */
#define KP_I (L_PHASE * TWO_PI * 1000.0f)
#define KI_I (R_PHASE * TWO_PI * 1000.0f)
/* 速度环：带宽 40 Hz（159c 推荐值），Kp = J·ωs / Kt，Ki = Kp·ωs / 4 */
#define WS (TWO_PI * 40.0f)
#define KP_W (J_TOTAL * WS / KT)
#define KI_W (KP_W * WS / 4.0f)
#define KP_P (WS / 4.0f)

#define ISR_PER_MS (PWM_HZ / 1000)
#define ALIGN_DAMP (0.09f / KT)       /* 对零阻尼 A / (rad/s) */
#define FINDZ_RPM 120.0f             /* 开机找 Z 相的转速（示例；Z 相宽 4 个计数，16 kHz 采样看得到） */
#define UP_X100 7000                 /* 上针位 70°（第 138 轮） */

static float off_a = 2047.5f, off_b = 2047.5f, off_c = 2047.5f;
static uint32_t cal_n;
static float cal_a, cal_b, cal_c;
static float int_d, int_q, int_w;
/* 速度观测器（三阶：位置、转速、负载）：电机力矩 Kt·iq / J 作前馈，负载那一项由观测器自己估；极点都放在 ωo = 2π·100 Hz：
 * K1 = 3ωo、K2 = 3ωo²、K3 = ωo³。位置用浮点小数 + 整数基点，避免大计数时浮点精度不够 */
#define OBS_WO (TWO_PI * 100.0f)
#define OBS_K1 (3.0f * OBS_WO)
#define OBS_K2 (3.0f * OBS_WO * OBS_WO)
#define OBS_K3 (OBS_WO * OBS_WO * OBS_WO)
static int32_t obs_base;
static float obs_th, obs_w, obs_d;
static uint16_t cnt_prev16;
static uint32_t align_t, settle_ms, uv_ms;
static int z_prev = 1;
static int32_t stop_cnt;             /* 停针目标（展开的计数） */

/* ---------------------------------------------------------------- 数学（同 B 版：不用数学库） */
static float wrap_pi(float x)
{
    while (x > PI_F) {
        x -= TWO_PI;
    }
    while (x < -PI_F) {
        x += TWO_PI;
    }
    return x;
}

static void sincos(float x, float *s, float *c)
{
    x = wrap_pi(x);
    float sg = 1.0f;
    if (x > PI_F / 2) {
        x = PI_F - x;
        sg = -1.0f;
    } else if (x < -PI_F / 2) {
        x = -PI_F - x;
        sg = -1.0f;
    }
    float x2 = x * x;
    *s = x * (1.0f - x2 / 6.0f * (1.0f - x2 / 20.0f * (1.0f - x2 / 42.0f * (1.0f - x2 / 72.0f))));
    *c = sg * (1.0f - x2 / 2.0f * (1.0f - x2 / 12.0f * (1.0f - x2 / 30.0f * (1.0f - x2 / 56.0f * (1.0f - x2 / 90.0f)))));
}

static float clampf(float x, float lo, float hi) { return x < lo ? lo : (x > hi ? hi : x); }
static float absf(float x) { return x < 0 ? -x : x; }
static float sqrtf_(float x)
{
    if (x <= 0) {
        return 0;
    }
    float r = x > 1.0f ? x : 1.0f;
    for (int i = 0; i < 12; i++) {
        r = 0.5f * (r + x / r);
    }
    return r;
}

/* ---------------------------------------------------------------- 外设 */
void motor_init(void)
{
    mc.magic = 0x534C434Du;                                                       /* "MCLS" */
    RCC_APB2ENR |= RCC_TIM1EN | RCC_SYSCFGEN;
    RCC_APB1ENR1 |= RCC_TIM4EN;
    RCC_AHB2ENR |= RCC_ADC12EN | RCC_GPIOAEN | RCC_GPIOBEN | RCC_GPIOCEN;

    /* PB12 = IPM_SD：先输出低（功率模块关着），再设成输出 */
    GPIO_BSRR(GPIOB_BASE) = 1u << (12 + 16);
    GPIO_MODER(GPIOB_BASE) = (GPIO_MODER(GPIOB_BASE) & ~(3u << 24)) | (1u << 24);
    /* PA8–PA10、PB13–PB15 复用 AF6（TIM1） */
    GPIO_MODER(GPIOA_BASE) = (GPIO_MODER(GPIOA_BASE) & ~(0x3Fu << 16)) | (0x2Au << 16);
    GPIO_AFRH(GPIOA_BASE) = (GPIO_AFRH(GPIOA_BASE) & ~0xFFFu) | 0x666u;
    GPIO_MODER(GPIOB_BASE) = (GPIO_MODER(GPIOB_BASE) & ~(0x3Fu << 26)) | (0x2Au << 26);
    GPIO_AFRH(GPIOB_BASE) = (GPIO_AFRH(GPIOB_BASE) & ~(0xFFFu << 20)) | (0x666u << 20);
    /* PA0、PA1、PA7、PB0、PB1 模拟；PA6（Z 相）输入 */
    GPIO_MODER(GPIOA_BASE) |= (3u << 0) | (3u << 2) | (3u << 14);
    GPIO_MODER(GPIOA_BASE) &= ~(3u << 12);
    GPIO_MODER(GPIOB_BASE) |= (3u << 0) | (3u << 2);
    /* PB6 / PB7 复用 AF2（TIM4_CH1 / CH2） */
    GPIO_MODER(GPIOB_BASE) = (GPIO_MODER(GPIOB_BASE) & ~(0xFu << 12)) | (0xAu << 12);
    GPIO_AFRL(GPIOB_BASE) = (GPIO_AFRL(GPIOB_BASE) & ~(0xFFu << 24)) | (0x22u << 24);

    /* TIM4 编码器模式 3（A、B 两路边沿都计 = 4 倍频），输入滤波 N = 4，不分频，满量程 16 位 */
    TIM4_CCMR1 = 1u | (1u << 8) | (2u << 4) | (2u << 12);
    TIM4_CCER = 0;
    TIM4_SMCR = 3u;
    TIM4_ARR = 0xFFFFu;
    TIM4_CR1 = 1u;

    /* 片内运放 1–3：PGA 8 倍、同相输入 VINP0、输出接 ADC 内部通道、高速 */
    for (int n = 0; n < 3; n++) {
        OPAMP_CSR(n) = OPAMP_CSR_EN | OPAMP_CSR_VMSEL_PGA | OPAMP_CSR_HIGHSPEED | OPAMP_CSR_INTEN | OPAMP_CSR_GAIN8;
    }

    /* TIM1：中心对齐 1、16 kHz；PWM 模式 1 + 预装载；六路输出高有效（功率模块 HIN、LIN 高有效）；死区 1 µs；更新事件作 TRGO；RCR = 1 */
    TIM1_PSC = 0;
    TIM1_ARR = PWM_ARR;
    TIM1_RCR = 1;
    TIM1_CCMR1 = (6u << 4) | (1u << 3) | (6u << 12) | (1u << 11);
    TIM1_CCMR2 = (6u << 4) | (1u << 3);
    TIM1_CCER = (1u << 0) | (1u << 2) | (1u << 4) | (1u << 6) | (1u << 8) | (1u << 10);
    TIM1_CCR1 = TIM1_CCR2 = TIM1_CCR3 = PWM_ARR / 2;
    TIM1_BDTR = DTG_1US;                                                          /* MOE 先关 */
    TIM1_CR2 = 2u << 4;
    TIM1_EGR = 1u;

    /* ADC1、ADC2：时钟 HCLK/4、退出深度掉电、开稳压器、校准、使能；注入组由 TIM1_TRGO 上升沿触发 */
    ADC12_CCR = (ADC12_CCR & ~(3u << 16)) | (3u << 16);
    uint32_t adc[2] = {ADC1_BASE, ADC2_BASE};
    for (int k = 0; k < 2; k++) {
        ADC_CR(adc[k]) &= ~(1u << 29);
        ADC_CR(adc[k]) |= 1u << 28;
    }
    for (volatile int i = 0; i < 4000; i++) {                                     /* 稳压器启动 ≥ 20 µs */
    }
    for (int k = 0; k < 2; k++) {
        ADC_CR(adc[k]) |= 1u << 31;
        while (ADC_CR(adc[k]) & (1u << 31)) {
        }
        ADC_CR(adc[k]) |= 1u;
        while (!(ADC_ISR(adc[k]) & ADC_ISR_ADRDY)) {
        }
    }
    /* ADC1：3 路（U 相电流、母线、脚踏）；ADC2：2 路（V、W 相电流） */
    ADC_JSQR(ADC1_BASE) = 2u | (0u << 2) | (1u << 7) | (ADC_CH_VOPAMP1 << 9) | (ADC_CH_VBUS << 15) | (ADC_CH_PEDAL << 21);
    ADC_JSQR(ADC2_BASE) = 1u | (0u << 2) | (1u << 7) | (ADC_CH_VOPAMP2 << 9) | (ADC_CH_VOPAMP3 << 15);
    ADC_IER(ADC1_BASE) = 1u << 6;                                                 /* JEOSIE：ADC1 转完进中断（两个 ADC 同一个触发） */
    ADC_CR(ADC1_BASE) |= 1u << 3;
    ADC_CR(ADC2_BASE) |= 1u << 3;

    NVIC_IPR8(IRQ_ADC1_2) = 0x00;
    NVIC_ISER(IRQ_ADC1_2 / 32) = 1u << (IRQ_ADC1_2 % 32);
    TIM1_CR1 = (1u << 5) | (1u << 7) | 1u;                                        /* CMS = 01、ARPE、CEN */
}

static void outputs(int on)
{
    if (on) {
        int_d = int_q = int_w = 0;
        GPIO_BSRR(GPIOB_BASE) = 1u << 12;                                         /* IPM_SD 高：功率模块工作 */
        TIM1_BDTR |= TIM_BDTR_MOE;
    } else {
        TIM1_BDTR &= ~TIM_BDTR_MOE;
        GPIO_BSRR(GPIOB_BASE) = 1u << (12 + 16);
    }
    mc.moe = on ? 1u : 0u;
}

void motor_off(void)
{
    outputs(0);
    mc.mode = MM_OFF;
    mc.id_ref = mc.iq_ref = 0;
}

void motor_fault(uint32_t code, float val)
{
    motor_off();
    if (mc.state != MS_FAULT) {
        mc.fault = code;
        mc.fault_val = val;
    }
    mc.state = MS_FAULT;
}

void motor_start(void)
{
    align_t = 0;
    mc.state = MS_ALIGN;
    mc.mode = MM_OFF;
    outputs(1);
}

void motor_speed(float rpm)
{
    if (mc.mode != MM_SPEED) {
        if (mc.mode == MM_OFF) {
            int_w = 0;
            mc.speed_ref = mc.speed_rpm;
        }
        if (!mc.moe && mc.state != MS_FAULT) {
            outputs(1);
        }
        mc.mode = MM_SPEED;
    }
    mc.speed_tgt = clampf(rpm, 0, RPM_MAX);
}

static int32_t angle_of(int32_t cnt)
{
    int32_t a = (cnt - mc.z_cnt) % CNT_PER_REV;
    return a < 0 ? a + CNT_PER_REV : a;
}

void motor_stop_at(int32_t angle_x100)
{
    /* 目标：前面最近的这个转角（同 159c：刚过了不到 1° 就往回退，不再转一圈） */
    int32_t tgt = angle_x100 * (CNT_PER_REV / 2000) / 18;                       /* 0.01° → 计数（10000 / 36000 = 5 / 18） */
    int32_t ahead = (tgt - angle_of(mc.pos_cnt)) % CNT_PER_REV;
    if (ahead < 0) {
        ahead += CNT_PER_REV;
    }
    if (ahead > CNT_PER_REV - CNT_PER_REV / 360) {
        ahead -= CNT_PER_REV;
    }
    stop_cnt = mc.pos_cnt + ahead;
    mc.stop_x100 = angle_x100;
    settle_ms = 0;
    if (mc.mode != MM_POS && mc.mode != MM_SPEED) {
        int_w = 0;
        if (!mc.moe && mc.state != MS_FAULT) {
            outputs(1);
        }
    }
    mc.mode = MM_POS;
}

int motor_stopped(void) { return mc.mode == MM_POS && settle_ms >= 20u; }
int motor_ramp_done(void) { return mc.mode == MM_SPEED && mc.speed_ref == mc.speed_tgt; }

/* ---------------------------------------------------------------- 1 kHz：对零、找 Z 相、爬坡、位置环、保护 */
static void tick_ms(int32_t cnt)
{
    mc.ms++;
    /* 对零：d 轴通电至少 300 ms，并且转子停稳（转速 < 1 r/min 连续 50 ms）才记偏移，最多等 1 s。
     * 直驱主轴没有减速器，静止时几乎没有摩擦：只给 d 轴电流，转子会在零位两边摆很久（试跑：300 ms 时还在 ±200 r/min 摆，
     * 偏移记错约 45° 电角度，力矩只剩七成），所以对零时加阻尼（下面 iq = −转速 × 系数）、并等停稳。 */
    if (mc.state == MS_ALIGN) {
        align_t++;
        settle_ms = absf(mc.speed_rpm) < 1.0f ? settle_ms + 1u : 0u;
    }
    if (mc.state == MS_ALIGN && ((align_t >= 300u && settle_ms >= 50u) || align_t >= 1000u)) {
        int32_t o = cnt % CNT_PER_EREV;
        mc.align_off = o < 0 ? o + CNT_PER_EREV : o;
        mc.state = MS_FINDZ;
        settle_ms = 0;
        int_w = 0;
        mc.speed_ref = 0;
        mc.mode = MM_SPEED;
        mc.speed_tgt = FINDZ_RPM;
    }
    if (mc.state == MS_FINDZ && mc.z_seen && mc.mode == MM_SPEED) {
        motor_stop_at(UP_X100);
    }
    if (mc.state == MS_FINDZ && motor_stopped()) {
        mc.state = MS_READY;
    }

    /* 速度给定爬坡（加速、减速按 159c 的工作周期） */
    if (mc.mode == MM_SPEED) {
        float d = mc.speed_tgt - mc.speed_ref, up = ACC_UP * 0.001f, dn = ACC_DN * 0.001f;
        float step = d > 0 ? (d < up ? d : up) : (-d < dn ? d : -dn);
        mc.speed_ref += step;
        mc.acc_ref = step * 1000.0f / 60.0f * TWO_PI;
    } else {
        mc.acc_ref = 0;
    }
    /* 停针：位置环 P、限速 300 r/min */
    if (mc.mode == MM_POS) {
        int32_t ec = stop_cnt - cnt;
        float e = (float)(ec >= -1 && ec <= 1 ? 0 : ec) * (TWO_PI / CNT_PER_REV);   /* ±1 个计数（0.036°）以内不再修 */
        mc.pos_err_deg = (float)ec * (360.0f / CNT_PER_REV);
        mc.speed_ref = clampf(KP_P * e / TWO_PI * 60.0f, -STOP_RPM_MAX, STOP_RPM_MAX);
        if (absf(mc.pos_err_deg) <= 0.5f && absf(mc.speed_rpm) < 5.0f) {         /* 停稳：离目标 ≤ 0.5°、转速 < 5 r/min，连续 20 ms */
            settle_ms++;
        } else {
            settle_ms = 0;
        }
    }
    /* 保护：欠压（连续 5 ms）、堵转（电流顶到上限、转速 < 30 r/min，连续 200 ms；示例值） */
    if (mc.moe && mc.vbus < VBUS_MIN) {
        if (++uv_ms >= 5u) {
            motor_fault(MF_UV, mc.vbus);
        }
    } else {
        uv_ms = 0;
    }
    if (mc.moe && mc.mode == MM_SPEED && mc.speed_tgt > 0 && absf(mc.iq_ref) >= 0.95f * IQ_MAX && absf(mc.speed_rpm) < 30.0f) {
        if (++mc.stall_ms >= 200u) {
            motor_fault(MF_STALL, mc.iq_ref);
        }
    } else {
        mc.stall_ms = 0;
    }
    motor_ms_hook();
    mc.imax = 0;
}

/* ---------------------------------------------------------------- 16 kHz 电流环 */
void ADC1_2_IRQHandler(void)
{
    ADC_ISR(ADC1_BASE) = (1u << 5) | (1u << 6);                                   /* 清 JEOC、JEOS */
    ADC_ISR(ADC2_BASE) = (1u << 5) | (1u << 6);
    float ca = (float)ADC_JDR(ADC1_BASE, 0), cb = (float)ADC_JDR(ADC2_BASE, 0), cc = (float)ADC_JDR(ADC2_BASE, 1);
    mc.vbus = (float)ADC_JDR(ADC1_BASE, 1) * V_PER_CODE;
    mc.pedal_v = (float)ADC_JDR(ADC1_BASE, 2) * PEDAL_PER_CODE;
    mc.isr++;

    /* 开机前 64 个周期：输出关着，量电流零点 */
    if (cal_n < 64) {
        cal_a += ca; cal_b += cb; cal_c += cc;
        if (++cal_n == 64) {
            off_a = cal_a / 64; off_b = cal_b / 64; off_c = cal_c / 64;
        }
    }
    float ia = (off_a - ca) * A_PER_CODE, ib = (off_b - cb) * A_PER_CODE, ic = (off_c - cc) * A_PER_CODE;
    float am = absf(ia) > absf(ib) ? absf(ia) : absf(ib);
    am = am > absf(ic) ? am : absf(ic);
    if (am > mc.imax) {
        mc.imax = am;
    }
    if (am > I_TRIP && mc.moe) {                                                  /* 过流：本周期就关 */
        motor_fault(MF_OC, am);
    }

    /* 编码器：TIM4 的 16 位计数展开成 32 位 */
    uint16_t c16 = (uint16_t)TIM4_CNT;
    int32_t cnt = mc.pos_cnt + (int16_t)(uint16_t)(c16 - cnt_prev16);
    cnt_prev16 = c16;
    mc.pos_cnt = cnt;
    /* Z 相（PA6 低有效）：第一次见到下降沿记下计数 = 主轴 0°（针杆最高点） */
    int z = (int)((GPIO_IDR(GPIOA_BASE) >> 6) & 1u);
    if (!z && z_prev && !mc.z_seen && mc.state == MS_FINDZ) {
        mc.z_cnt = cnt;
        mc.z_seen = 1;
    }
    z_prev = z;
    if (mc.z_seen) {
        int32_t a_prev = mc.angle_x100;
        mc.angle_x100 = angle_of(cnt) * 18 / (CNT_PER_REV / 2000);                 /* 计数 → 0.01° */
        if (a_prev > 27000 && mc.angle_x100 < 9000) {                            /* 正转过 0°：一针 */
            motor_z_hook();
        }
    }
    /* 转速：观测器（见上）。B 版的“1 ms 差分 + 滤波”在 10000 计数/转时分辨率 6 r/min，停针保持时速度环把量化当真，
     * 主轴在目标附近来回抖（试跑看到 ±5 r/min）；只用二阶跟踪观测器、拿 Kt·iq / J 当前馈，有负载时估出的转速偏几百 r/min
     * （堵转时主轴不动、估出来还在转），所以用带负载估计的三阶观测器。 */
    {
        float e = (float)(cnt - obs_base) - obs_th;
        obs_th += (obs_w + OBS_K1 * e) * TS;
        if (obs_th > 1000.0f || obs_th < -1000.0f) {
            int32_t m = (int32_t)obs_th;
            obs_base += m;
            obs_th -= (float)m;
        }
        float a_iq = mc.moe ? mc.iq * (KT / J_TOTAL) * (CNT_PER_REV / TWO_PI) : 0.0f;
        obs_w += (a_iq - obs_d + OBS_K2 * e) * TS;
        obs_d += (-OBS_K3 * e) * TS;
        mc.speed_rpm = obs_w * (60.0f / CNT_PER_REV);
    }
    int32_t e = (cnt - mc.align_off) % CNT_PER_EREV;
    if (e < 0) {
        e += CNT_PER_EREV;
    }
    float th = (float)e * (TWO_PI / CNT_PER_EREV);
    if (mc.state == MS_ALIGN) {
        th = 0;                                                                   /* 对零：电流加在 d 轴 θe = 0 方向 */
    }
    float s, c;
    sincos(th, &s, &c);

    /* Clarke（幅值不变）、Park */
    float al = ia, be = (ia + 2.0f * ib) * 0.57735027f;
    mc.id = al * c + be * s;
    mc.iq = -al * s + be * c;

    /* 指令 */
    uint32_t k = mc.isr % ISR_PER_MS;
    if (mc.state == MS_ALIGN && mc.moe) {
        mc.id_ref = ALIGN_A;
        /* 阻尼：转子到零位附近时这一轴就是力矩轴；临界阻尼 c = 2√(K·J)，K = Kt·I·p ≈ 4 N·m/rad → c ≈ 0.09 N·m·s/rad */
        mc.iq_ref = clampf(-ALIGN_DAMP * mc.speed_rpm * (TWO_PI / 60.0f), -ALIGN_A, ALIGN_A);
    } else if (mc.moe && mc.mode != MM_OFF) {
        if (k % 8u == 0) {
            /* 2 kHz 速度环：PI + 加速度前馈 J·a / Kt（159c 同一做法） */
            float w = mc.speed_rpm / 60.0f * TWO_PI, wr = mc.speed_ref / 60.0f * TWO_PI;
            float ew = wr - w;
            float out = KP_W * ew + int_w + J_TOTAL * mc.acc_ref / KT;
            if (absf(out) < IQ_MAX) {
                int_w += KI_W * ew * 0.0005f;
            }
            mc.iq_ref = clampf(out, -IQ_MAX, IQ_MAX);
        }
        mc.id_ref = 0;
    } else {
        mc.id_ref = mc.iq_ref = 0;
    }

    /* d/q 电流 PI，电压限幅 Vbus/√3，抗积分饱和 */
    float vmax = mc.vbus * 0.57735027f;
    float ed = mc.id_ref - mc.id, eq = mc.iq_ref - mc.iq;
    float vd = KP_I * ed + int_d, vq = KP_I * eq + int_q;
    float mag = sqrtf_(vd * vd + vq * vq);
    if (mag < vmax) {
        int_d += KI_I * ed * TS;
        int_q += KI_I * eq * TS;
    } else if (mag > 0) {
        vd *= vmax / mag;
        vq *= vmax / mag;
    }
    mc.vd = vd;
    mc.vq = vq;

    /* 反 Park、反 Clarke、SVPWM（中点注入） */
    float va = vd * c - vq * s, vbt = vd * s + vq * c;
    float pa = va, pb = -0.5f * va + 0.8660254f * vbt, pc = -0.5f * va - 0.8660254f * vbt;
    /* 死区补偿：功率模块死区 1 µs × 16 kHz = 1.6 % 母线（390 V 时 6.2 V），按相电流方向补回去（电流小时线性过渡，±0.1 A）。
     * 不补的话低速保持时这几伏的误差让主轴在停针位附近慢慢来回晃（试跑看到 ±0.3°）。 */
    if (mc.moe) {
        float dv = mc.vbus * (1e-6f * PWM_HZ);
        pa += dv * clampf(ia * 10.0f, -1, 1);
        pb += dv * clampf(ib * 10.0f, -1, 1);
        pc += dv * clampf(ic * 10.0f, -1, 1);
    }
    float mx = pa > pb ? pa : pb, mn = pa < pb ? pa : pb;
    mx = mx > pc ? mx : pc;
    mn = mn < pc ? mn : pc;
    float z0 = -(mx + mn) * 0.5f, inv = mc.vbus > 1.0f ? 1.0f / mc.vbus : 0;
    TIM1_CCR1 = (uint32_t)(PWM_ARR * clampf(0.5f + (pa + z0) * inv, 0, 1));
    TIM1_CCR2 = (uint32_t)(PWM_ARR * clampf(0.5f + (pb + z0) * inv, 0, 1));
    TIM1_CCR3 = (uint32_t)(PWM_ARR * clampf(0.5f + (pc + z0) * inv, 0, 1));

    if (k == 0) {
        tick_ms(cnt);
    }
}
