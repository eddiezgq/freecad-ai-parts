/* 抱闸（第 110 轮）。电路（B 版原理图第 1 页）：PB6 → U16 UCC27511 → Q7 低边 MOSFET，线圈接 J6（母线 + / Q7 漏极），D5 续流；
 * R38 100 kΩ 下拉：MCU 复位、程序跑飞、没配置时 PB6 没输出 → 线圈断电 → 抱住（失效安全）。
 * PWM：TIM4 向上计数 170 MHz / 8500 = 20 kHz；松闸先 100% 过励 BRK_OVER_MS，再保持占空比 = 24 V ÷ 母线电压（平均 24 V）。
 * 线圈电感大（时间常数几十毫秒，示例 25 ms），20 kHz 下电流基本是直流。示例固件，仿真验证。 */
#include "brake.h"
#include "regs.h"

#define BRK_ARR 8499u          /* 170 MHz / (8499 + 1) = 20 kHz */

static uint32_t cmd_release, ms_since;

void brake_init(void)
{
    RCC_APB1ENR1 |= RCC_TIM4EN;
    RCC_AHB2ENR |= RCC_GPIOBEN;
    TIM4_PSC = 0;
    TIM4_ARR = BRK_ARR;
    TIM4_CCR1 = 0;                                         /* 占空比 0：抱住 */
    TIM4_CCMR1 = (6u << 4) | (1u << 3);                    /* OC1M = 0110 PWM 模式 1，OC1PE 预装载 */
    TIM4_CCER = 1u;                                        /* CC1E */
    TIM4_EGR = 1u;                                         /* UG：装入预装载值 */
    TIM4_CR1 = (1u << 7) | 1u;                             /* ARPE、CEN */
    /* PB6 复用 AF2 = TIM4_CH1（引脚复用对照 ST 引脚数据） */
    GPIO_AFRL(GPIOB_BASE) = (GPIO_AFRL(GPIOB_BASE) & ~(0xFu << 24)) | (2u << 24);
    GPIO_MODER(GPIOB_BASE) = (GPIO_MODER(GPIOB_BASE) & ~(3u << 12)) | (2u << 12);
    cmd_release = 0;
    ms_since = BRK_ENGAGE_MS;                              /* 上电就是抱着的 */
}

void brake_set(int release)
{
    uint32_t r = release ? 1u : 0u;
    if (r == cmd_release) {
        return;
    }
    cmd_release = r;
    ms_since = 0;
    TIM4_CCR1 = r ? BRK_ARR + 1u : 0u;                     /* 松闸：先 100%（CCR > ARR 输出一直为高）；抱闸：立即 0 */
}

void brake_tick(float vbus)
{
    if (ms_since < 0x7FFFFFFFu) {
        ms_since++;
    }
    if (cmd_release && ms_since >= BRK_OVER_MS) {          /* 过励完了：保持平均 24 V */
        float d = vbus > BRK_V_COIL ? BRK_V_COIL / vbus : 1.0f;
        TIM4_CCR1 = (uint32_t)(d * (float)(BRK_ARR + 1u));
    }
}

int brake_released(void) { return cmd_release && ms_since >= BRK_RELEASE_MS; }
int brake_engaged(void) { return !cmd_release && ms_since >= BRK_ENGAGE_MS; }
int brake_cmd(void) { return (int)cmd_release; }
