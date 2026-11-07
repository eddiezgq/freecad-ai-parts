/* 关节驱动板 DRV-JOINT B 版 示例固件。第 100 轮：经 SPI1 读编码器接口芯片 WQ-ENCIF；第 102 轮：电机控制（FOC）与 CAN；
 * 第 107 轮：输出端绝对值编码器（SSI，SPI3）——开机取绝对角度、双编码器互检、受控停车。
 * 第 110 轮：抱闸（TIM4 CH1 = PB6）——上电抱住；运动前先稳住再松闸；停、欠压先抱住再关输出；危险故障关输出同时抱闸。
 *
 * 时间基准是 20 kHz 电流环中断（motor.c）；它每 1 ms 调一次 motor_ms_hook()：
 *   第 100 轮那套编码器管理（状态、Z 相、错误计数、芯片缺失每 100 ms 重试）、状态机、指令、保护、排 CAN 发送。
 * 主循环只管把排好的 CAN 帧发出去。所有 SPI 访问都在电流环中断里，不会互相打断。
 * 板上没有调试串口：遥测区 tlm（编码器，第 100 轮）和 mc（电机控制，motor.h）给调试器经 SWD 看（仿真里由 Renode 读内存）。
 * 示例固件，仿真验证；芯片未流片、B 版不投产。 */
#include <stdint.h>
#include "brake.h"
#include "can.h"
#include "can_proto.h"
#include "clock.h"
#include "encif.h"
#include "motor.h"
#include "regs.h"
#include "ssi.h"

#define CPR 10000          /* 2500 线编码器 ×4（第 88 轮的示例编码器） */
#define WIN_MS 10          /* 转速取 10 ms 窗口 */
#define RETRY_MS 100

enum { ST_BOOT = 0, ST_RUN = 1, ST_MISSING = 2 };

typedef struct {
    uint32_t magic;        /* "TLM1" */
    uint32_t state;        /* 0 启动、1 运行、2 芯片缺失 */
    uint32_t id;           /* 读到的芯片 ID */
    uint32_t ctrl;         /* 回读的控制寄存器 */
    uint32_t tick_ms;
    int32_t cnt;           /* 芯片计数（补码，可为负） */
    int32_t turns;         /* 开机以来的圈数（向下取整） */
    int32_t angle_cnt;     /* 本圈内位置 0..CPR-1（相对开机位置） */
    int32_t rpm_x10;       /* 转速 ×10 */
    int32_t idx;           /* Z 相锁存的计数 */
    uint32_t idx_valid;
    int32_t abs_cnt;       /* 绝对位置 0..CPR-1（相对 Z 相）；未见 Z 时 -1 */
    uint32_t err_count;    /* 芯片报的错误（A/B 同跳）次数 */
    uint32_t status;       /* 最近一次状态寄存器 */
    uint32_t frames;       /* SPI 帧数 */
    uint32_t retries;      /* 芯片缺失时的重试次数 */
} telemetry_t;

volatile telemetry_t tlm;
static int32_t hist[WIN_MS];

/* CAN 收到的指令（FDCAN 中断写，1 kHz 节拍读） */
static volatile uint32_t cmd_mode, cmd_new;
static volatile int32_t cmd_target;
static uint32_t pend_mode;          /* 第 110 轮：运动指令等松闸（mc.pend） */
static int32_t pend_target;
static uint32_t last_cmd_ms, uv_ms, prev_state, mis_ms;

#define ABS_ZERO_MDEG 0      /* 输出端编码器的安装零点（编码器读 0 时关节在 0°；示例） */
#define MISMATCH_MDEG 500    /* 两个编码器差超过 0.5°（示例）…… */
#define MISMATCH_MS 10       /* ……连续 10 ms 判“减速器 / 编码器不一致” */
#define SSI_BAD_MAX 5        /* 连续 5 帧读坏判“输出端编码器”故障 */

/* 第 107 轮：读输出端绝对值编码器（1 kHz）；开机回原点；电机侧换算的关节角与它互检 */
static void abs_encoder(void)
{
    uint32_t pos;
    if (!ssi_read(&pos)) {
        if (++mc.ssi_bad >= SSI_BAD_MAX && mc.state != STATE_FAULT) {
            motor_fault(FAULT_ABS, 0);
        }
        return;
    }
    mc.ssi_bad = 0;
    int32_t a = (int32_t)((uint64_t)pos * 360000u / SSI_COUNTS) - ABS_ZERO_MDEG;
    if (a > 180000) {
        a -= 360000;
    }
    mc.abs_mdeg = a;
    if (!mc.homed && motor_aligned() && mc.state == STATE_READY) {
        motor_set_home(a);                       /* 对零做完：这时的电机计数对应输出端编码器读到的角度 */
    }
    if (mc.homed) {
        int32_t d = motor_joint_mdeg(mc.pos_cnt) - a;
        d = d > 180000 ? d - 360000 : (d < -180000 ? d + 360000 : d);
        mc.mismatch_mdeg = d;
        if ((d > MISMATCH_MDEG || d < -MISMATCH_MDEG) && (mc.state == STATE_RUN || mc.state == STATE_READY || mc.hold)) {
            if (++mis_ms >= MISMATCH_MS) {
                motor_fault(FAULT_SLIP, (float)d / 1000.0f);
            }
        } else {
            mis_ms = 0;
        }
    }
}
/* 待发的 CAN 帧（1 kHz 节拍排，主循环发） */
static volatile uint32_t due_status, due_heart, due_emcy;

static int32_t mod_cpr(int32_t x) { int32_t r = x % CPR; return r < 0 ? r + CPR : r; }
static int32_t div_cpr(int32_t x) { return (x - mod_cpr(x)) / CPR; }

/* ---------------------------------------------------------------- 编码器芯片（第 100 轮） */
static int chip_start(void)
{
    encif_reset();
    tlm.id = encif_read(ENCIF_R_ID);
    tlm.frames++;
    if (tlm.id != ENCIF_ID) {
        return 0;
    }
    encif_write(ENCIF_R_CTRL, 0x31);          /* 使能、不反向、Z 不清零、滤波长度 3 */
    tlm.ctrl = encif_read(ENCIF_R_CTRL);
    encif_write(ENCIF_R_STATUS, ENCIF_ST_ERR | ENCIF_ST_IVLD);
    tlm.frames += 3;
    for (int i = 0; i < WIN_MS; i++) {
        hist[i] = 0;
    }
    tlm.idx_valid = 0;
    tlm.abs_cnt = -1;
    return 1;
}

/* 1 ms：计数用电流环本周期读到的；再读 ID（芯片还在不在）和状态 */
static void enc_sample(uint32_t now)
{
    int32_t c = mc.pos_cnt;
    uint32_t id = encif_read(ENCIF_R_ID);
    uint32_t st = encif_read(ENCIF_R_STATUS);
    tlm.frames += 2;
    if (id != ENCIF_ID) {                     /* 芯片不响应 */
        tlm.state = ST_MISSING;
        return;
    }
    tlm.cnt = c;
    tlm.status = st;
    tlm.turns = div_cpr(c);
    tlm.angle_cnt = mod_cpr(c);

    int k = (int)(now % WIN_MS);
    if (now >= WIN_MS) {
        tlm.rpm_x10 = (c - hist[k]) * 6;      /* 计数/10 ms → rpm×10：d / CPR / 0.01 s × 60 × 10 = d × 6 */
    }
    hist[k] = c;

    if (st & ENCIF_ST_IVLD) {                 /* 过了 Z：取锁存值，清标志等下一次 */
        tlm.idx = (int32_t)encif_read(ENCIF_R_IDX);
        tlm.idx_valid = 1;
        encif_write(ENCIF_R_STATUS, ENCIF_ST_IVLD);
        tlm.frames += 2;
    }
    if (tlm.idx_valid) {
        tlm.abs_cnt = mod_cpr(c - tlm.idx);
    }
    if (st & ENCIF_ST_ERR) {                  /* A/B 同时跳：丢步风险，记一次并清除；电机在转就停机 */
        tlm.err_count++;
        encif_write(ENCIF_R_STATUS, ENCIF_ST_ERR);
        tlm.frames++;
        if (mc.state == STATE_RUN) {
            motor_fault(FAULT_ENC, 0);
        }
    }
}

/* ---------------------------------------------------------------- CAN 收 */
void can_rx_handler(uint16_t id, const uint8_t *d, uint8_t len)
{
    mc.can_rx++;
    if (id != CAN_ID_CMD || len < 5) {
        return;
    }
    cmd_target = (int32_t)((uint32_t)d[1] | (uint32_t)d[2] << 8 | (uint32_t)d[3] << 16 | (uint32_t)d[4] << 24);
    cmd_mode = d[0];
    cmd_new = 1;
}

/* ---------------------------------------------------------------- 1 kHz 节拍（在电流环中断里） */
void motor_ms_hook(uint32_t now)
{
    tlm.tick_ms = now;
    if (tlm.state == ST_RUN) {
        enc_sample(now);
    } else if (now % RETRY_MS == 0) {
        tlm.retries++;
        if (chip_start()) {
            tlm.state = ST_RUN;
        }
    }

    /* 编码器丢了：转着就停机报警；没对零就等着 */
    if (tlm.state != ST_RUN && (mc.state == STATE_RUN || mc.state == STATE_INIT) && mc.moe) {
        motor_fault(FAULT_ENC, 0);
    }
    abs_encoder();

    /* 对零：编码器正常、电流零点量好（开机 64 个周期）之后 */
    if (mc.state == STATE_INIT && !mc.moe && !motor_aligned() && tlm.state == ST_RUN && mc.isr > 64u) {
        motor_start_align();
    }

    /* 指令 */
    if (cmd_new) {
        cmd_new = 0;
        last_cmd_ms = now;
        uint32_t m = cmd_mode;
        if (m == MODE_CLEAR) {
            if (mc.state == STATE_FAULT && mc.hold) {   /* 受控停车保持中：接着运行，保持在当前位置 */
                motor_resume_hold();
            } else if (mc.state == STATE_FAULT && tlm.state == ST_RUN && mc.ssi_bad < SSI_BAD_MAX) {
                uint32_t f = mc.fault;
                mc.fault = FAULT_NONE;
                mc.fault_val = 0;
                if (f == FAULT_ENC || f == FAULT_SLIP) {   /* 编码器芯片可能复位过 / 两个编码器对不上：重新对零、回原点 */
                    mc.state = STATE_INIT;
                    mc.homed = 0;
                    motor_start_align();
                } else {
                    mc.state = STATE_READY;
                }
            }
        } else if (m == MODE_STOP) {
            if (mc.state == STATE_RUN) {               /* 第 110 轮：减速停住 → 抱闸 → 抱住后关输出（原来立即关输出） */
                mc.pend = 0;
                motor_park();
            }
        } else if ((m == MODE_SPEED || m == MODE_POS || m == MODE_TORQUE) &&
                   (mc.state == STATE_READY || mc.state == STATE_RUN)) {
            if (mc.state == STATE_READY) {             /* 第 110 轮：先在当前位置稳住、松闸，松开了再执行指令 */
                if (mc.hold) {                         /* 正在“停”的抱闸过程中：不关输出了，重新松闸 */
                    mc.hold = 0;
                    brake_set(1);
                } else {
                    motor_hold_here();
                }
                mc.state = STATE_RUN;
                mc.pend = 1;
            }
            if (mc.pend) {
                pend_mode = m;
                pend_target = cmd_target;
            } else {
                motor_set(m, cmd_target);
            }
        }
    }

    /* 第 110 轮：松开了才执行等着的运动指令 */
    if (mc.pend && mc.state != STATE_RUN) {
        mc.pend = 0;
    }
    if (mc.pend && brake_released()) {
        mc.pend = 0;
        motor_set(pend_mode, pend_target);
    }

    /* 保护：通信超时、欠压（连续 5 ms）——第 107 轮起受控停车：通信超时减速停住、保持位置不断电；欠压减速停住后关输出 */
    if (mc.state == STATE_RUN && now - last_cmd_ms > 100u) {
        motor_quickstop(FAULT_COMM, 0, 1);
    }
    if ((mc.state == STATE_READY || mc.state == STATE_RUN || mc.hold) && mc.vbus < VBUS_MIN) {
        if (++uv_ms >= 5u) {
            if (mc.hold && mc.hold_keep) {            /* 保持中又欠压：保持不住，停住后关输出；故障改记欠压，再报一次警 */
                mc.hold_keep = 0;
                mc.fault = FAULT_UV;
                mc.fault_val = mc.vbus;
                due_emcy = 1;
            } else if (mc.hold) {
                /* 已经在“停住后关输出”的受控停车里：不用再做什么 */
            } else {
                motor_quickstop(FAULT_UV, mc.vbus, 0);
            }
        }
    } else {
        uv_ms = 0;
    }

    /* 排 CAN 发送 */
    if (mc.state == STATE_FAULT && prev_state != STATE_FAULT) {
        due_emcy = 1;
    }
    prev_state = mc.state;
    if (now % 10u == 0) {
        due_status = 1;
    }
    if (now % 100u == 0) {
        due_heart = 1;
    }
}

static void put16(uint8_t *p, int32_t v)
{
    if (v > 32767) {
        v = 32767;
    }
    if (v < -32768) {
        v = -32768;
    }
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)((uint32_t)v >> 8);
}

static int32_t rnd(float x) { return (int32_t)(x >= 0 ? x + 0.5f : x - 0.5f); }

int main(void)
{
    clock_init();
    tlm.magic = 0x314D4C54u;
    tlm.state = ST_BOOT;
    tlm.abs_cnt = -1;

    encif_init_bus();
    tlm.state = chip_start() ? ST_RUN : ST_MISSING;
    ssi_init();
    brake_init();
    motor_init();
    can_init();

    for (;;) {
        __asm volatile("wfi");
        uint8_t d[8];
        if (due_emcy) {
            due_emcy = 0;
            d[0] = (uint8_t)mc.fault;
            put16(d + 1, rnd(mc.fault_val * 100.0f));
            can_send(CAN_ID_EMCY, d, 3);
            mc.can_tx++;
        }
        if (due_status) {
            due_status = 0;
            /* 关节角：回原点后按输出端绝对值编码器的原点换算电机计数（第 107 轮；原来开机位置当 0°） */
            float joint = (float)motor_joint_mdeg(mc.pos_cnt) / 1000.0f;
            d[0] = (uint8_t)mc.state;
            d[1] = (uint8_t)mc.fault;
            put16(d + 2, rnd(joint * 100.0f));
            put16(d + 4, rnd(mc.speed_rpm));
            put16(d + 6, rnd(mc.iq * 100.0f));
            can_send(CAN_ID_STATUS, d, 8);
            mc.can_tx++;
        }
        if (due_heart) {
            due_heart = 0;
            d[0] = (uint8_t)mc.state;
            put16(d + 1, rnd(mc.vbus * 10.0f));
            d[3] = (uint8_t)mc.brake_cmd;               /* 第 110 轮：抱闸 0 抱住、1 松开 */
            can_send(CAN_ID_HEART, d, 4);
            mc.can_tx++;
        }
    }
}
