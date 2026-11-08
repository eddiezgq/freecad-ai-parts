/* 抱闸（第 110 轮）。电路（B 版原理图第 1 页）：PB6 → U16 UCC27511 → Q7 低边 MOSFET，线圈接 J6（母线 + / Q7 漏极），D5 续流；
 * R38 100 kΩ 下拉：MCU 复位、程序跑飞、没配置时 PB6 没输出 → 线圈断电 → 抱住（失效安全）。
 * PWM：TIM4 向上计数 170 MHz / 8500 = 20 kHz；松闸先 100% 过励 BRK_OVER_MS，再保持占空比 = 24 V ÷ 母线电压（平均 24 V）。
 * 线圈电感大（时间常数几十毫秒，示例 25 ms），20 kHz 下电流基本是直流。示例固件，仿真验证。
 * 第 114 轮：R39 采样线圈电流（低边，只在导通时有电流：滤波后 = 电流 × 占空比 × 0.5 Ω），查断线、过流、抱不住。 */
#include "brake.h"
#include "regs.h"

#define BRK_ARR 8499u          /* 170 MHz / (8499 + 1) = 20 kHz */

static uint32_t cmd_release, ms_since;
static float sense_v, i_est = -1.0f;
static uint32_t n_open, n_over, n_stuck, n_low, fault_sub;
#define BRK_R_SENSE 0.5f
#define BRK_V_LOW (0.3f * BRK_I_RATED * BRK_R_SENSE)          /* 0.063 V：额定 30% 电流在采样电阻上的电压（示例） */

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
    n_open = n_over = n_stuck = 0;
    if (r) {
        fault_sub = 0;                                     /* 重新松闸（清故障后）重新判断 */
    }
    TIM4_CCR1 = r ? BRK_ARR + 1u : 0u;                     /* 松闸：先 100%（CCR > ARR 输出一直为高）；抱闸：立即 0 */
}

void brake_adc_init(void)
{
    GPIO_MODER(GPIOB_BASE) |= 3u << 0;                     /* PB0 模拟 */
    ADC1_SMPR2 = (ADC1_SMPR2 & ~(7u << 15)) | (4u << 15);  /* IN15 采样 47.5 个时钟 */
    ADC1_SQR1 = (15u << 6) | 0u;                           /* 规则组 1 路：IN15 */
    ADC1_CR |= ADC_CR_ADSTART;
}

static void sense(void)
{
    if (ADC1_ISR & ADC_ISR_EOC) {
        sense_v = (float)ADC1_DR * (3.3f / 4095.0f);       /* 读 DR 清 EOC */
    }
    ADC1_CR |= ADC_CR_ADSTART;                             /* 下一次（注入组照旧由 TIM1 触发，优先） */
    float duty = (float)TIM4_CCR1 / (float)(BRK_ARR + 1u);
    if (duty > 1.0f) {
        duty = 1.0f;
    }
    i_est = duty >= 0.2f ? sense_v / (BRK_R_SENSE * duty) : -1.0f;
    n_low = sense_v < BRK_V_LOW ? n_low + 1u : 0u;
    /* 断线：松闸、过了过励，电流 < 额定 30%，连续 20 ms */
    n_open = (cmd_release && ms_since >= BRK_OVER_MS && i_est >= 0 && i_est < 0.3f * BRK_I_RATED) ? n_open + 1u : 0u;
    /* 过流（线圈短路）：电流 > 额定 200%，连续 5 ms（过励时最多约 175%） */
    n_over = (cmd_release && i_est > 2.0f * BRK_I_RATED) ? n_over + 1u : 0u;
    /* 抱不住：发了抱闸、占空比 0，采样电阻上还有电流（开关管常通），连续 20 ms */
    n_stuck = (!cmd_release && ms_since >= BRK_ENGAGE_MS && sense_v >= BRK_V_LOW) ? n_stuck + 1u : 0u;
    if (!fault_sub) {
        fault_sub = n_over >= 5u ? 2u : n_open >= 20u ? 1u : n_stuck >= 20u ? 3u : 0u;
    } else if (fault_sub == 2u && n_stuck >= 20u) {
        fault_sub = 3u;                                    /* “过流”后撤了驱动还有电流：是开关管常通，抱闸抱不住 */
    }
}

void brake_tick(float vbus)
{
    if (ms_since < 0x7FFFFFFFu) {
        ms_since++;
    }
    sense();
    if (cmd_release && ms_since >= BRK_OVER_MS) {          /* 过励完了：保持平均 24 V */
        float d = vbus > BRK_V_COIL ? BRK_V_COIL / vbus : 1.0f;
        TIM4_CCR1 = (uint32_t)(d * (float)(BRK_ARR + 1u));
    }
}

int brake_released(void) { return cmd_release && ms_since >= BRK_RELEASE_MS; }
int brake_engaged(void)
{
    /* 过流后线圈电流大，降到释放值要更久：按 120 ms 算（示例） */
    return !cmd_release && ms_since >= (fault_sub == 2u ? 2u * BRK_ENGAGE_MS : BRK_ENGAGE_MS);
}
int brake_cmd(void) { return (int)cmd_release; }
float brake_current(void) { return i_est; }
float brake_sense_v(void) { return sense_v; }
int brake_fault(void) { return (int)fault_sub; }
int brake_verified(void) { return brake_engaged() && n_low >= 20u; }
