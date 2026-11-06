/* 电机控制（第 102 轮）：磁场定向控制 FOC，电流环 20 kHz、速度环 2 kHz、位置环 1 kHz。 */
#ifndef MOTOR_H
#define MOTOR_H
#include <stdint.h>

/* 电机与关节参数——控制器“知道”的标称值（与仿真对象一致；示例值见 README 与页面参数表） */
#define POLE_PAIRS 5                 /* 示例 */
#define CNT_PER_REV 10000            /* 2500 线 ×4 */
#define CNT_PER_EREV (CNT_PER_REV / POLE_PAIRS)
#define GEAR 100                     /* 减速比（零件库 CSF-17-100） */
#define R_PHASE 0.12f                /* Ω（示例） */
#define L_PHASE 0.0002f              /* H（示例） */
#define KT 0.15f                     /* N·m/A（第 88 轮示例电机） */
#define J_TOTAL 5.76e-5f             /* 电机 + 折算负载 kg·m²（示例） */

#define PWM_HZ 20000
#define PWM_ARR 4250                 /* 170 MHz / (2 × 4250) = 20 kHz，中心对齐 */
#define I_TRIP 25.0f                 /* 过流阈值 A */
#define VBUS_MIN 36.0f
#define ALIGN_A 3.0f                 /* 对零电流 A */

typedef struct {
    uint32_t magic;          /* "MC02" */
    uint32_t state;          /* can_proto.h：0 初始化、1 就绪、2 运行、3 故障 */
    uint32_t mode;           /* 当前模式 */
    uint32_t fault;
    int32_t align_off;       /* 对零得到的编码器偏移（0..CNT_PER_EREV-1） */
    uint32_t isr;            /* 电流环中断次数 */
    float id, iq;            /* 测得的 d/q 电流 A */
    float id_ref, iq_ref;
    float vd, vq;            /* 输出电压 V */
    float speed_rpm;         /* 电机转速（编码器差分 + 滤波） */
    float speed_ref;         /* rpm */
    int32_t pos_cnt;         /* 编码器计数（开机以来） */
    int32_t pos_ref_cnt;     /* 位置指令（轨迹） */
    float vbus;
    float imax;              /* 最近 1 ms 三相电流绝对值最大 */
    uint32_t moe;
    uint32_t can_rx, can_tx;
    float fault_val;
} mc_t;

extern volatile mc_t mc;

void motor_init(void);       /* TIM1、ADC1 配好并启动（输出关着） */
void motor_enable(int on);   /* MOE */
void motor_set(uint32_t mode, int32_t target);   /* 主程序在 1 kHz 节拍里调 */
void motor_fault(uint32_t code, float val);
int motor_aligned(void);
void motor_start_align(void);
void motor_ms_hook(uint32_t ms);                 /* main.c 实现：1 kHz（在电流环中断里调） */

#endif
