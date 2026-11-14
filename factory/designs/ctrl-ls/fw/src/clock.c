/* 系统时钟：HSI16 → PLL → 170 MHz（第 102 轮）。HSI16 / M=4 = 4 MHz，× N=85 = 340 MHz，/ R=2 = 170 MHz。
 * 170 MHz 要求：主调节器提升模式（PWR_CR5.R1MODE = 0）、Flash 4 个等待周期（RM0440 Flash 章“等待周期与电压”表）。 */
#include "clock.h"
#include "regs.h"

void clock_init(void)
{
    RCC_APB1ENR1 |= RCC_PWREN;
    PWR_CR5 &= ~(1u << 8);                            /* R1MODE = 0：提升模式 */
    FLASH_ACR = (FLASH_ACR & ~0xFu) | 4u | (1u << 8) | (1u << 9) | (1u << 10);   /* 4 等待周期、预取、指令 / 数据缓存 */
    RCC_PLLCFGR = 2u | (3u << 4) | (85u << 8) | (1u << 24);                    /* PLLSRC = HSI16、M = 4、N = 85、R = 2、PLLREN */
    RCC_CR |= 1u << 24;                               /* PLLON */
    while (!(RCC_CR & (1u << 25))) {                  /* 等 PLLRDY */
    }
    RCC_CFGR = (RCC_CFGR & ~3u) | 3u;                 /* SW = PLL */
    while (((RCC_CFGR >> 2) & 3u) != 3u) {            /* 等 SWS = PLL */
    }
}
