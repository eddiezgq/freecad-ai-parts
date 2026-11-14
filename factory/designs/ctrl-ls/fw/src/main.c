/* 平缝机控制器 CTRL-LS 示例固件（第 159 轮 159f）。
 * 时间基准是 16 kHz 电流环中断（motor.c）；它每 1 ms 调一次缝纫状态机（sew.c 的 motor_ms_hook）。主循环只等中断。
 * 开机：量电流零点 → d 轴通电对零 → 低速转找编码器 Z 相（针杆最高点 = 主轴 0°）→ 停上针位 → 就绪。
 * 板上的调试口只有 SWD：遥测区 mc（电机）、sw（缝纫）、设置 cfg 给调试器看、改（仿真里由 Renode 读写内存）。
 * 没做的（留接口）：针距步进电机（TIM3 → PB4 / PB5）、操作面板串口（USART2 → PA2 / PA3）、联网、校正关断（PB9）。
 * 示例固件，仿真验证；电机未选型，参数见 README；不能直接用于产品。 */
#include <stdint.h>
#include "clock.h"
#include "motor.h"
#include "regs.h"
#include "sew.h"

int main(void)
{
    clock_init();
    sew_init();                 /* 电磁铁引脚先置成“不吸合” */
    motor_init();
    for (volatile uint32_t i = 0; i < 170000u; i++) {   /* 约 5 ms：电流零点（中断里量 64 个周期，4 ms） */
    }
    motor_start();
    for (;;) {
        __asm volatile("wfi");
    }
}
