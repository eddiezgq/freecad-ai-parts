/* STM32G431 寄存器——只列平缝机控制器 CTRL-LS 固件用到的（第 159 轮 159f）。地址、偏移、位按 RM0440《STM32G4 参考手册》，
 * 逐个对照 ST 官方 CMSIS 头文件 stm32g431xx.h 核对（测试 test_ctrl_ls_fw.py 里记着核对过的数）；
 * 片内运放接 ADC 的内部通道号对照 ST 官方 LL 驱动 stm32g4xx_ll_adc.h（LL_ADC_CHANNEL_VOPAMP1 = 13、VOPAMP2 = 16、VOPAMP3_ADC2 = 18）。
 * 和驱动板 B 版的 regs.h 同一写法：不用厂商库，学生能逐行对照手册。 */
#ifndef REGS_H
#define REGS_H
#include <stdint.h>

#define REG(addr) (*(volatile uint32_t *)(addr))
#define REG8(addr) (*(volatile uint8_t *)(addr))

/* RCC，0x4002 1000 */
#define RCC_BASE 0x40021000u
#define RCC_CR REG(RCC_BASE + 0x00)          /* 位 24 PLLON、位 25 PLLRDY */
#define RCC_CFGR REG(RCC_BASE + 0x08)        /* SW 位 1:0、SWS 位 3:2 */
#define RCC_PLLCFGR REG(RCC_BASE + 0x0C)
#define RCC_AHB2ENR REG(RCC_BASE + 0x4C)     /* 位 0 GPIOAEN、位 1 GPIOBEN、位 2 GPIOCEN、位 13 ADC12EN */
#define RCC_APB1ENR1 REG(RCC_BASE + 0x58)    /* 位 2 TIM4EN、位 28 PWREN */
#define RCC_APB2ENR REG(RCC_BASE + 0x60)     /* 位 0 SYSCFGEN（运放在 SYSCFG 时钟下）、位 11 TIM1EN */
#define RCC_GPIOAEN (1u << 0)
#define RCC_GPIOBEN (1u << 1)
#define RCC_GPIOCEN (1u << 2)
#define RCC_ADC12EN (1u << 13)
#define RCC_TIM4EN (1u << 2)
#define RCC_PWREN (1u << 28)
#define RCC_SYSCFGEN (1u << 0)
#define RCC_TIM1EN (1u << 11)

#define FLASH_ACR REG(0x40022000u)
#define PWR_CR5 REG(0x40007000u + 0x80)

/* GPIO：GPIOA 0x4800 0000、GPIOB 0x4800 0400、GPIOC 0x4800 0800 */
#define GPIOA_BASE 0x48000000u
#define GPIOB_BASE 0x48000400u
#define GPIOC_BASE 0x48000800u
#define GPIO_MODER(b) REG((b) + 0x00)        /* 每脚 2 位：00 输入 01 输出 10 复用 11 模拟 */
#define GPIO_PUPDR(b) REG((b) + 0x0C)
#define GPIO_IDR(b) REG((b) + 0x10)
#define GPIO_BSRR(b) REG((b) + 0x18)         /* 低 16 位置 1，高 16 位清 0 */
#define GPIO_AFRL(b) REG((b) + 0x20)
#define GPIO_AFRH(b) REG((b) + 0x24)

/* TIM1 高级定时器，0x4001 2C00 */
#define TIM1_BASE 0x40012C00u
#define TIM1_CR1 REG(TIM1_BASE + 0x00)       /* 位 0 CEN、位 6:5 CMS、位 7 ARPE */
#define TIM1_CR2 REG(TIM1_BASE + 0x04)       /* MMS 位 6:4（010 = 更新事件作 TRGO） */
#define TIM1_EGR REG(TIM1_BASE + 0x14)
#define TIM1_CCMR1 REG(TIM1_BASE + 0x18)
#define TIM1_CCMR2 REG(TIM1_BASE + 0x1C)
#define TIM1_CCER REG(TIM1_BASE + 0x20)
#define TIM1_PSC REG(TIM1_BASE + 0x28)
#define TIM1_ARR REG(TIM1_BASE + 0x2C)
#define TIM1_RCR REG(TIM1_BASE + 0x30)
#define TIM1_CCR1 REG(TIM1_BASE + 0x34)
#define TIM1_CCR2 REG(TIM1_BASE + 0x38)
#define TIM1_CCR3 REG(TIM1_BASE + 0x3C)
#define TIM1_BDTR REG(TIM1_BASE + 0x44)      /* DTG 位 7:0、位 15 MOE */
#define TIM_BDTR_MOE (1u << 15)

/* TIM4 通用定时器，0x4000 0800：编码器模式（CH1 = PB6、CH2 = PB7，AF2） */
#define TIM4_BASE 0x40000800u
#define TIM4_CR1 REG(TIM4_BASE + 0x00)
#define TIM4_SMCR REG(TIM4_BASE + 0x08)      /* SMS 位 2:0 + 位 16（0011 = 编码器模式 3：两路边沿都计） */
#define TIM4_CCMR1 REG(TIM4_BASE + 0x18)     /* CC1S 位 1:0、CC2S 位 9:8（01 = 输入，接 TI1 / TI2）；IC1F 位 7:4、IC2F 位 15:12 */
#define TIM4_CCER REG(TIM4_BASE + 0x20)      /* CC1P 位 1、CC2P 位 5（极性） */
#define TIM4_CNT REG(TIM4_BASE + 0x24)
#define TIM4_ARR REG(TIM4_BASE + 0x2C)

/* 片内运放 OPAMP1–3，基址 0x4001 0300，每个一个 CSR（偏移 0x00 / 0x04 / 0x08） */
#define OPAMP_BASE 0x40010300u
#define OPAMP_CSR(n) REG(OPAMP_BASE + 4 * (n))
#define OPAMP_CSR_EN (1u << 0)               /* OPAMPxEN */
#define OPAMP_CSR_VMSEL_PGA (2u << 5)        /* VMSEL = 10：PGA 模式 */
#define OPAMP_CSR_HIGHSPEED (1u << 7)        /* HIGHSPEEDEN */
#define OPAMP_CSR_INTEN (1u << 8)            /* OPAMPINTEN：输出接 ADC 内部通道 */
#define OPAMP_CSR_GAIN8 (2u << 14)           /* PGGAIN = 00010：增益 8（反相输入不接时） */
/* VPSEL = 00：同相输入 VINP0——OPAMP1 = PA1、OPAMP2 = PA7、OPAMP3 = PB0（数据手册“运放输入”表） */

/* ADC1 0x5000 0000、ADC2 0x5000 0100、公共 0x5000 0300 */
#define ADC1_BASE 0x50000000u
#define ADC2_BASE 0x50000100u
#define ADC_ISR(b) REG((b) + 0x00)           /* 位 0 ADRDY、位 5 JEOC、位 6 JEOS */
#define ADC_IER(b) REG((b) + 0x04)           /* 位 6 JEOSIE */
#define ADC_CR(b) REG((b) + 0x08)            /* 位 0 ADEN、位 3 JADSTART、位 28 ADVREGEN、位 29 DEEPPWD、位 31 ADCAL */
#define ADC_SMPR1(b) REG((b) + 0x14)
#define ADC_SMPR2(b) REG((b) + 0x18)
#define ADC_JSQR(b) REG((b) + 0x4C)          /* JL 位 1:0、JEXTSEL 位 6:2（0 = TIM1_TRGO）、JEXTEN 位 8:7、JSQ1–4 位 9/15/21/27 起 */
#define ADC_JDR(b, n) REG((b) + 0x80 + 4 * (n))
#define ADC12_CCR REG(0x50000300u + 0x08)    /* CKMODE 位 17:16 */
#define ADC_ISR_ADRDY (1u << 0)
#define ADC_CH_VOPAMP1 13u                   /* ADC1：OPAMP1 输出（U 相电流） */
#define ADC_CH_VBUS 1u                       /* ADC1_IN1 = PA0（母线分压） */
#define ADC_CH_PEDAL 12u                     /* ADC1_IN12 = PB1（脚踏） */
#define ADC_CH_VOPAMP2 16u                   /* ADC2：OPAMP2 输出（V 相电流） */
#define ADC_CH_VOPAMP3 18u                   /* ADC2：OPAMP3 输出（W 相电流） */

/* Cortex-M4 内核 */
#define NVIC_ISER(n) REG(0xE000E100u + 4 * (n))
#define NVIC_IPR8(n) REG8(0xE000E400u + (n))
#define IRQ_ADC1_2 18

#define SYSCLK_HZ 170000000u

#endif
