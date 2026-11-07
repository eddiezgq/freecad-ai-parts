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

#endif
