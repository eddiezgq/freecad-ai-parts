/* 主轴电机控制（第 159 轮 159f）：磁场定向控制沿用驱动板 B 版 motor.c 的做法（Clarke / Park、d/q 两个 PI、SVPWM、对零），
 * 换成本板：功率模块 STGIPS14K60T、16 kHz（设计描述 ipm_inverter.f_pwm）、三相下桥 25 mΩ 采样 + 片内运放 8 倍、2500 线编码器 ×4。 */
#ifndef MOTOR_H
#define MOTOR_H
#include <stdint.h>

/* 电机与负载——控制器“知道”的标称值（与仿真对象一致；出处见 README 与页面参数表） */
#define POLE_PAIRS 4                 /* 示例（第 138 轮电机未选型） */
#define CNT_PER_REV 10000            /* 2500 线 ×4（设计描述 sensor_inputs.encoder_lines） */
#define CNT_PER_EREV (CNT_PER_REV / POLE_PAIRS)
#define R_PHASE 1.2f                 /* Ω（示例） */
#define L_PHASE 0.004f               /* H（示例） */
#define KT 0.496f                    /* N·m/A（159c：5000 r/min 线反电势峰值 ≤ 300 V 推出） */
#define J_TOTAL 5.24e-4f             /* 转子 4×10⁻⁴ + 机头负载 1.24×10⁻⁴ kg·m²（第 138 轮 G2、159c） */

#define PWM_HZ 16000
#define PWM_ARR 5312                 /* 170 MHz / (2 × 5312) ≈ 16.0 kHz，中心对齐 */
#define DTG_1US 0x95u                /* 死区 1 µs：DTG[7:5] = 10x → (64 + 21) × 2 / 170 MHz（设计描述 t_dead） */
#define I_TRIP 7.5f                  /* 过流阈值 A（设计描述 low_side_sense.i_trip） */
#define IQ_MAX 6.05f                 /* 力矩上限对应的相电流 A（159c：3.0 N·m / 0.496） */
#define VBUS_MIN 300.0f              /* 欠压 V（示例） */
#define ALIGN_A 2.0f                 /* 对零电流 A（示例） */

#define RPM_MAX 5000.0f
#define ACC_UP 50000.0f              /* 加速 r/min/s：0 → 5000 用 0.1 s（159c 工作周期） */
#define ACC_DN 39167.0f              /* 减速 r/min/s：5000 → 300 用 0.12 s（159c 工作周期） */
#define STOP_RPM_MAX 300.0f          /* 停针时位置环限速（159c） */

enum { MS_INIT = 0, MS_ALIGN = 1, MS_FINDZ = 2, MS_READY = 3, MS_FAULT = 4 };
enum { MM_OFF = 0, MM_SPEED = 1, MM_POS = 2 };
enum { MF_NONE = 0, MF_OC = 1, MF_UV = 2, MF_STALL = 3 };

typedef struct {
    uint32_t magic;          /* "MCLS" */
    uint32_t state;          /* MS_* */
    uint32_t mode;           /* MM_* */
    uint32_t fault;          /* MF_* */
    uint32_t isr;            /* 电流环中断次数 */
    uint32_t ms;             /* 1 kHz 节拍 */
    int32_t align_off;       /* 对零得到的编码器偏移 */
    int32_t pos_cnt;         /* 编码器计数（开机以来，32 位展开） */
    int32_t z_cnt;           /* 见到 Z 相时的计数（针杆最高点 = 主轴 0°） */
    uint32_t z_seen;
    int32_t angle_x100;      /* 主轴转角 0.01°（0–35999，按 Z 相） */
    float id, iq, id_ref, iq_ref, vd, vq;
    float speed_rpm;         /* 测得转速 */
    float speed_ref;         /* 速度环给定（爬坡后） */
    float speed_tgt;         /* 目标转速（缝纫状态机给） */
    float acc_ref;           /* 给定的加速度 rad/s²（前馈用） */
    int32_t stop_x100;       /* 停针目标角 0.01° */
    float pos_err_deg;       /* 停针时离目标还差多少度 */
    float vbus;
    float pedal_v;           /* 脚踏板霍尔输出 V（分压前） */
    float imax;              /* 最近 1 ms 三相电流绝对值最大 */
    uint32_t moe;
    float fault_val;
    uint32_t stall_ms;
} mc_t;

extern volatile mc_t mc;

void motor_init(void);
void motor_start(void);                   /* 量零点 → 对零 → 找 Z 相 → 停上针位 → 就绪 */
void motor_speed(float rpm);              /* 速度模式，按加减速度爬到 rpm */
void motor_stop_at(int32_t angle_x100);   /* 位置模式：停在前面最近的这个转角 */
int motor_stopped(void);                  /* 位置模式下已停稳（离目标 ≤ 0.5°、转速 < 5 r/min 连续 20 ms） */
int motor_ramp_done(void);                /* 速度给定已爬到目标 */
void motor_off(void);                     /* 关输出（功率模块 SD 拉低、MOE 关） */
void motor_fault(uint32_t code, float val);
void motor_ms_hook(void);                 /* sew.c 实现：1 kHz（在电流环中断里调） */
void motor_z_hook(void);                  /* sew.c 实现：每过一次针杆最高点（0°）调一次，数针数 */

#endif
