/* 电机控制（第 102 轮；第 107 轮加原点、受控停车；第 110 轮加抱闸时序）。一次 ADC 注入组转换完成中断 = 一个 20 kHz 电流环周期：
 *   读三相电流与母线 → 过流保护 → 读编码器（SPI1 → WQ-ENCIF）→ 电角度 → Clarke / Park → d、q 两个 PI → 反 Park → SVPWM → 写比较值
 *   每 10 次（2 kHz）速度环，每 20 次（1 kHz）位置环与轨迹、编码器状态、主程序节拍。
 * PWM：TIM1 中心对齐 20 kHz，CH1–3 PA8–PA10、CH1N–3N PB13–PB15（AF6，第 88 轮原理图第 27–32 脚）；死区 200 ns。
 * 电流：PA0–PA2 = ADC1_IN1–IN3，40 mV/A、零点 1.65 V（开机时实测零点）；母线 PA3 = ADC1_IN4，分压 6.8 / 108.8。 */
#include "motor.h"
#include "brake.h"
#include "can_proto.h"
#include "encif.h"
#include "regs.h"

volatile mc_t mc;

#define TS (1.0f / PWM_HZ)
#define PI_F 3.14159265f
#define TWO_PI 6.28318531f
#define A_PER_CODE (3.3f / 4095.0f / 0.04f)
#define V_PER_CODE (3.3f / 4095.0f * 108.8f / 6.8f)

/* 电流环：带宽 1 kHz（ωc = 2π·1000），Kp = L·ωc，Ki = R·ωc（零极点对消） */
#define KP_I (L_PHASE * TWO_PI * 1000.0f)
#define KI_I (R_PHASE * TWO_PI * 1000.0f)
/* 速度环：带宽 100 Hz，Kp = J·ωs / Kt，Ki = Kp·ωs / 4 */
#define WS (TWO_PI * 100.0f)
#define KP_W (J_TOTAL * WS / KT)
#define KI_W (KP_W * WS / 4.0f)
#define IQ_MAX 20.0f
/* 位置环：Kp = ωs / 4（rad/s 每 rad）；轨迹：电机 1500 rpm、加速度 3000 rad/s² */
#define KP_P (WS / 4.0f)
#define V_MAX (1500.0f / 60.0f * TWO_PI)
#define A_MAX 3000.0f

static float off_a = 2047.5f, off_b = 2047.5f, off_c = 2047.5f;
static uint32_t cal_n;
static float cal_a, cal_b, cal_c;
static float int_d, int_q, int_w;
static int32_t ring[20];            /* 最近 20 个周期（1 ms）的计数 */
static uint32_t ms;
static uint32_t align_t;
static int aligned;
static int32_t align_pending;      /* 对零记下的偏移，抱住以后才生效（第 110 轮） */
/* 轨迹（电机侧，单位：计数，浮点） */
static float trj_pos, trj_vel, trj_goal;

/* ---------------------------------------------------------------- 数学（不用数学库：多项式，误差 < 1e-6） */
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
    if (x > PI_F / 2) {                 /* 折到 [-π/2, π/2] */
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
    mc.magic = 0x3230434Du;
    RCC_APB2ENR |= RCC_TIM1EN;
    RCC_AHB2ENR |= RCC_ADC12EN | RCC_GPIOAEN | RCC_GPIOBEN;

    /* PA8–PA10、PB13–PB15 复用 AF6；PA0–PA3 模拟 */
    GPIO_MODER(GPIOA_BASE) = (GPIO_MODER(GPIOA_BASE) & ~(0x3Fu << 16)) | (0x2Au << 16);
    REG(GPIOA_BASE + 0x24) = (REG(GPIOA_BASE + 0x24) & ~0xFFFu) | 0x666u;          /* GPIOA_AFRH */
    GPIO_MODER(GPIOB_BASE) = (GPIO_MODER(GPIOB_BASE) & ~(0x3Fu << 26)) | (0x2Au << 26);
    REG(GPIOB_BASE + 0x24) = (REG(GPIOB_BASE + 0x24) & ~(0xFFFu << 20)) | (0x666u << 20);
    GPIO_MODER(GPIOA_BASE) |= 0xFFu;

    /* TIM1：中心对齐 1、ARR 预装载；PWM 模式 1 + 比较值预装载；互补输出；死区 200 ns（34 × 5.88 ns）；更新事件作 TRGO；RCR = 1 */
    TIM1_PSC = 0;
    TIM1_ARR = PWM_ARR;
    TIM1_RCR = 1;
    TIM1_CCMR1 = (6u << 4) | (1u << 3) | (6u << 12) | (1u << 11);
    TIM1_CCMR2 = (6u << 4) | (1u << 3);
    TIM1_CCER = (1u << 0) | (1u << 2) | (1u << 4) | (1u << 6) | (1u << 8) | (1u << 10);
    TIM1_CCR1 = TIM1_CCR2 = TIM1_CCR3 = PWM_ARR / 2;
    TIM1_BDTR = 34u;                                   /* MOE 先关 */
    TIM1_CR2 = 2u << 4;
    TIM1_EGR = 1u;

    /* ADC1：时钟 HCLK/4、退出深度掉电、开稳压器、校准、使能；注入组 4 路由 TIM1_TRGO 上升沿触发 */
    ADC12_CCR = (ADC12_CCR & ~(3u << 16)) | (3u << 16);
    ADC1_CR &= ~(1u << 29);
    ADC1_CR |= 1u << 28;
    for (volatile int i = 0; i < 4000; i++) {          /* 稳压器启动 ≥ 20 µs */
    }
    ADC1_CR |= 1u << 31;
    while (ADC1_CR & (1u << 31)) {
    }
    ADC1_CR |= 1u;
    while (!(ADC1_ISR & ADC_ISR_ADRDY)) {
    }
    ADC1_JSQR = 3u | (0u << 2) | (1u << 7) | (1u << 9) | (2u << 15) | (3u << 21) | (4u << 27);
    ADC1_IER = 1u << 6;                                /* JEOSIE */
    ADC1_CR |= 1u << 3;                                /* JADSTART：等触发 */

    NVIC_IPR8(IRQ_ADC1_2) = 0x00;
    NVIC_ISER(IRQ_ADC1_2 / 32) = 1u << (IRQ_ADC1_2 % 32);
    TIM1_CR1 = (1u << 5) | (1u << 7) | 1u;             /* CMS = 01、ARPE、CEN */
}

void motor_enable(int on)
{
    if (on) {
        int_d = int_q = int_w = 0;
        TIM1_BDTR |= TIM_BDTR_MOE;
    } else {
        TIM1_BDTR &= ~TIM_BDTR_MOE;
    }
    mc.moe = on ? 1u : 0u;
}

void motor_fault(uint32_t code, float val)
{
    motor_enable(0);
    brake_set(0);                                    /* 第 110 轮：立即关输出的同时抱闸（抱住要几十毫秒） */
    if (mc.state != STATE_FAULT || mc.hold) {        /* 受控停车中又来危险故障：改记这一个，立即关输出 */
        mc.fault = code;
        mc.fault_val = val;
    }
    mc.hold = 0;
    mc.state = STATE_FAULT;
    mc.mode = MODE_STOP;
    mc.id_ref = mc.iq_ref = 0;
}

int motor_aligned(void) { return aligned; }

/* ---------------------------------------------------------------- 第 107 轮：原点、受控停车 */
void motor_set_home(int32_t abs_mdeg)
{
    mc.home_cnt = mc.pos_cnt;
    mc.home_mdeg = abs_mdeg;
    mc.homed = 1;
}

int32_t motor_joint_mdeg(int32_t cnt)
{
    return mc.home_mdeg + (int32_t)((float)(cnt - mc.home_cnt) * (360000.0f / ((float)CNT_PER_REV * GEAR)));
}

void motor_quickstop(uint32_t code, float val, int keep)
{
    if (mc.state == STATE_FAULT) {
        return;
    }
    mc.fault = code;
    mc.fault_val = val;
    mc.state = STATE_FAULT;
    if (!mc.moe) {                                   /* 输出本来就关着：没什么可停的 */
        mc.hold = 0;
        mc.mode = MODE_STOP;
        return;
    }
    const float amax = A_MAX / TWO_PI * CNT_PER_REV;
    trj_pos = (float)mc.pos_cnt;
    trj_vel = mc.speed_rpm / 60.0f * CNT_PER_REV;
    trj_goal = trj_pos + (trj_vel >= 0 ? 1.0f : -1.0f) * trj_vel * trj_vel / (2.0f * amax);   /* 按最大减速度停下的位置 */
    mc.mode = MODE_POS;
    mc.hold = 1;
    mc.hold_keep = keep ? 1u : 0u;
}

void motor_resume_hold(void)
{
    brake_set(1);                                    /* 第 110 轮：若已在抱闸（关输出类停车），重新松开 */
    mc.hold = 0;
    mc.fault = FAULT_NONE;
    mc.fault_sub = 0;
    mc.fault_val = 0;
    mc.state = STATE_RUN;
    mc.mode = MODE_POS;
    trj_goal = trj_pos;
}

void motor_start_align(void)
{
    aligned = 0;
    align_t = 0;
    mc.state = STATE_INIT;
    mc.mode = MODE_STOP;
    motor_enable(1);
    brake_set(1);                                    /* 第 110 轮：对零要转子能动；d 轴电流把转子定住 */
}

/* ---------------------------------------------------------------- 第 110 轮：抱闸时序 */
void motor_hold_here(void)
{
    trj_pos = trj_goal = (float)mc.pos_cnt;
    trj_vel = 0;
    mc.speed_ref = 0;
    mc.iq_ref = 0;
    mc.mode = MODE_POS;
    motor_enable(1);                                 /* 先有力矩（位置环停在这里），调用方再松闸 */
}

void motor_park(void)
{
    mc.state = STATE_READY;
    if (!mc.moe) {
        brake_set(0);
        mc.hold = 0;
        mc.mode = MODE_STOP;
        return;
    }
    const float amax = A_MAX / TWO_PI * CNT_PER_REV;
    trj_pos = (float)mc.pos_cnt;
    trj_vel = mc.speed_rpm / 60.0f * CNT_PER_REV;
    trj_goal = trj_pos + (trj_vel >= 0 ? 1.0f : -1.0f) * trj_vel * trj_vel / (2.0f * amax);
    if (mc.mode != MODE_SPEED && mc.mode != MODE_POS) {
        int_w = mc.iq_ref;                           /* 从力矩模式切过来：速度环积分接上当前电流，不跳 */
    }
    mc.mode = MODE_POS;
    mc.hold = 1;                                     /* 借用受控停车的“停住后关输出”：停住 → 抱闸 → 抱住后关输出 */
    mc.hold_keep = 0;
}

void motor_set(uint32_t mode, int32_t target)
{
    if (mode == MODE_SPEED) {
        mc.speed_ref = (float)target;
    } else if (mode == MODE_POS) {
        /* 关节角 0.001° → 电机计数：按原点换算，× 减速比 × 每转计数 / 360000（第 107 轮起按输出端编码器的原点） */
        trj_goal = (float)mc.home_cnt + (float)(target - mc.home_mdeg) * (float)GEAR * (float)CNT_PER_REV / 360000.0f;
        if (mc.mode != MODE_POS) {
            trj_pos = (float)mc.pos_cnt;
            trj_vel = mc.speed_rpm / 60.0f * CNT_PER_REV;
        }
    } else if (mode == MODE_TORQUE) {
        mc.iq_ref = (float)target / 1000.0f;
    }
    if (mc.mode != mode && (mode == MODE_SPEED || mode == MODE_POS)) {
        int_w = 0;                                     /* 切模式时速度环积分清零 */
    }
    mc.mode = mode;
}

/* ---------------------------------------------------------------- 轨迹（梯形速度，1 kHz，单位：计数） */
static void trajectory(void)
{
    const float dt = 0.001f;
    const float vmax = V_MAX / TWO_PI * CNT_PER_REV, amax = A_MAX / TWO_PI * CNT_PER_REV;
    float e = trj_goal - trj_pos;
    if (trj_vel == 0.0f && absf(e) < 0.5f) {           /* 停着、已到目标：不动（第 110 轮：原来会在 ±几个计数间来回） */
        trj_pos = trj_goal;
        mc.pos_ref_cnt = (int32_t)trj_pos;
        return;
    }
    float dir = e >= 0 ? 1.0f : -1.0f;
    float stop = trj_vel * trj_vel / (2.0f * amax);    /* 现在开始减速要走的距离 */
    float v;
    if (absf(e) <= stop + absf(trj_vel) * dt && trj_vel * dir > 0) {
        v = trj_vel - dir * amax * dt;                 /* 减速 */
        if (v * dir < 0) {
            v = 0;
        }
    } else {
        v = clampf(trj_vel + dir * amax * dt, -vmax, vmax);
    }
    trj_pos += 0.5f * (trj_vel + v) * dt;
    trj_vel = v;
    if (absf(trj_goal - trj_pos) < 0.5f && absf(trj_vel) < amax * dt) {
        trj_pos = trj_goal;
        trj_vel = 0;
    }
    mc.pos_ref_cnt = (int32_t)trj_pos;
}

/* ---------------------------------------------------------------- 20 kHz 电流环 */
void ADC1_2_IRQHandler(void)
{
    ADC1_ISR = (1u << 5) | (1u << 6);                  /* 清 JEOC、JEOS */
    float ca = (float)ADC1_JDR(0), cb = (float)ADC1_JDR(1), cc = (float)ADC1_JDR(2);
    mc.vbus = (float)ADC1_JDR(3) * V_PER_CODE;
    mc.isr++;

    /* 开机前 64 个周期：输出关着，量电流零点 */
    if (cal_n < 64) {
        cal_a += ca; cal_b += cb; cal_c += cc;
        if (++cal_n == 64) {
            off_a = cal_a / 64; off_b = cal_b / 64; off_c = cal_c / 64;
        }
    }
    float ia = (ca - off_a) * A_PER_CODE, ib = (cb - off_b) * A_PER_CODE, ic = (cc - off_c) * A_PER_CODE;
    float am = absf(ia) > absf(ib) ? absf(ia) : absf(ib);
    am = am > absf(ic) ? am : absf(ic);
    if (am > mc.imax) {
        mc.imax = am;
    }
    if (am > I_TRIP && mc.moe) {                       /* 过流：本周期就关管 */
        motor_fault(FAULT_OC, am);
    }

    /* 编码器：读计数（第 100 轮的芯片状态在 1 kHz 节拍里处理） */
    int32_t cnt = (int32_t)encif_read(ENCIF_R_CNT);
    mc.pos_cnt = cnt;
    /* 转速：与 1 ms 前的计数差分（1500 rpm 时 250 计数/ms，分辨率 6 rpm），再一阶滤波（时间常数约 1 ms：
     * 停着时编码器只在 ±1 计数间跳，滤得太轻速度环会把量化当真，电流来回抖） */
    uint32_t ri = mc.isr % 20u;
    if (mc.isr > 20u) {
        float rpm = (float)(cnt - ring[ri]) * (60000.0f / CNT_PER_REV);
        mc.speed_rpm += 0.05f * (rpm - mc.speed_rpm);
    }
    ring[ri] = cnt;
    int32_t e = (cnt - mc.align_off) % CNT_PER_EREV;
    if (e < 0) {
        e += CNT_PER_EREV;
    }
    float th = (float)e * (TWO_PI / CNT_PER_EREV);
    if (!aligned && mc.state == STATE_INIT && mc.moe) {
        th = 0;                                        /* 对零：电流加在 d 轴 θe = 0 方向，转子被拉过去 */
    }
    float s, c;
    sincos(th, &s, &c);

    /* Clarke（幅值不变）、Park */
    float al = ia, be = (ia + 2.0f * ib) * 0.57735027f;
    mc.id = al * c + be * s;
    mc.iq = -al * s + be * c;

    /* 指令 */
    uint32_t k = mc.isr % 20u;
    if (mc.state == STATE_INIT && mc.moe) {
        mc.id_ref = ALIGN_A;
        mc.iq_ref = 0;
    } else if (mc.state == STATE_RUN || mc.hold) {
        if (k % 10u == 0 && (mc.mode == MODE_SPEED || mc.mode == MODE_POS)) {
            /* 2 kHz 速度环 */
            float w = mc.speed_rpm / 60.0f * TWO_PI, wr = mc.speed_ref / 60.0f * TWO_PI;
            float ew = wr - w;
            float out = KP_W * ew + int_w;
            if (absf(out) < IQ_MAX) {
                int_w += KI_W * ew * 0.0005f;
            }
            mc.iq_ref = clampf(out, -IQ_MAX, IQ_MAX);
        }
        mc.id_ref = 0;
    } else {
        mc.id_ref = mc.iq_ref = 0;
    }

    /* d/q 电流 PI，电压限幅 Vbus/√3（SVPWM 线性区），抗积分饱和 */
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

    /* 反 Park、反 Clarke、SVPWM（中点注入：三相减去 (max + min) / 2） */
    float va = vd * c - vq * s, vbt = vd * s + vq * c;
    float pa = va, pb = -0.5f * va + 0.8660254f * vbt, pc = -0.5f * va - 0.8660254f * vbt;
    float mx = pa > pb ? pa : pb, mn = pa < pb ? pa : pb;
    mx = mx > pc ? mx : pc;
    mn = mn < pc ? mn : pc;
    float z = -(mx + mn) * 0.5f, inv = mc.vbus > 1.0f ? 1.0f / mc.vbus : 0;
    TIM1_CCR1 = (uint32_t)(PWM_ARR * clampf(0.5f + (pa + z) * inv, 0, 1));
    TIM1_CCR2 = (uint32_t)(PWM_ARR * clampf(0.5f + (pb + z) * inv, 0, 1));
    TIM1_CCR3 = (uint32_t)(PWM_ARR * clampf(0.5f + (pc + z) * inv, 0, 1));

    /* 1 kHz：对零、位置环与轨迹、主程序节拍 */
    if (k == 0) {
        ms++;

        brake_tick(mc.vbus);
        mc.brake_cmd = (uint32_t)brake_cmd();
        mc.brake_i = brake_current();
        mc.brake_v = brake_sense_v();
        mc.brake_ok = (uint32_t)(mc.brake_cmd ? brake_released() : brake_engaged());
        if (mc.state == STATE_INIT && mc.moe && ++align_t == 300) {      /* 通电 300 ms 后记偏移；第 110 轮：先抱闸 */
            int32_t o = cnt % CNT_PER_EREV;
            align_pending = o < 0 ? o + CNT_PER_EREV : o;
            brake_set(0);
        }
        if (mc.state == STATE_INIT && mc.moe && align_t >= 300u + BRK_ENGAGE_MS && brake_verified()) {   /* 抱住了才撤对零电流、关输出（第 114 轮：按测到的电流） */
            mc.align_off = align_pending;
            aligned = 1;
            motor_enable(0);
            mc.state = STATE_READY;
        }
        if ((mc.state == STATE_RUN || mc.hold) && mc.mode == MODE_POS) {
            trajectory();
            if (mc.hold && !mc.hold_keep && trj_vel == 0.0f && trj_pos == trj_goal) {   /* 受控停车（关输出类）：停住了再关 */
                brake_set(0);                                                         /* 第 110 轮：先抱闸，抱住了再关 */
                if (brake_verified()) {                                               /* 第 114 轮：时间到且测到线圈电流降下来 */
                    mc.hold = 0;
                    motor_enable(0);
                    mc.mode = MODE_STOP;
                }
            }
            float ep = (trj_pos - (float)cnt) * (TWO_PI / CNT_PER_REV);           /* rad */
            float wff = trj_vel / CNT_PER_REV * 60.0f;                            /* 前馈 rpm */
            mc.speed_ref = wff + KP_P * ep / TWO_PI * 60.0f;
        }
        motor_ms_hook(ms);
        mc.imax = 0;
    }
}
