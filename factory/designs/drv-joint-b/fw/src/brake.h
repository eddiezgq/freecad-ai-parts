/* 抱闸（第 110 轮）：失电制动电磁抱闸，线圈 24 V（示例），从 48 V 母线经 Q7 低边 PWM 供电。 */
#ifndef BRAKE_H
#define BRAKE_H
#include <stdint.h>

#define BRK_V_COIL 24.0f       /* 线圈额定电压（示例） */
#define BRK_OVER_MS 50u        /* 松闸先 100% 占空比过励 50 ms（示例） */
#define BRK_RELEASE_MS 60u     /* 松闸指令发出 60 ms 后才算松开（吸合时间，示例） */
#define BRK_ENGAGE_MS 60u      /* 抱闸指令发出 60 ms 后才算抱住（释放时间，示例） */

void brake_init(void);         /* TIM4 CH1（PB6）PWM 20 kHz，占空比 0 = 抱住 */
void brake_set(int release);   /* 1 松闸、0 抱闸（立即撤电） */
void brake_tick(float vbus);   /* 1 kHz：过励计时、按母线电压算保持占空比 */
int brake_released(void);      /* 松闸指令已发且过了 BRK_RELEASE_MS */
int brake_engaged(void);       /* 抱闸指令已发且过了 BRK_ENGAGE_MS */
int brake_cmd(void);           /* 当前指令：1 松闸、0 抱闸 */

/* 第 114 轮：线圈电流检测（R39 0.5 Ω 在 Q7 源极，R40 + C63 滤波进 PB0 = ADC1_IN15） */
#define BRK_I_RATED 0.42f      /* 额定电流（示例） */
void brake_adc_init(void);     /* ADC1 已使能后调用：PB0 模拟、规则组 1 路 IN15 */
float brake_current(void);     /* 估算的线圈电流 A（占空比 < 0.2 时为 -1：算不准） */
float brake_sense_v(void);     /* 采样电阻上的平均电压 V */
int brake_fault(void);         /* 0 正常、1 断线、2 过流、3 抱不住（抱闸指令下采样电阻上还有电流） */
int brake_verified(void);      /* 抱住了：抱闸时间已过，且采样电阻上已连续 20 ms 没电流 */

#endif
