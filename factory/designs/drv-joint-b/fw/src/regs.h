/* STM32G431 寄存器——只列本固件用到的。地址、偏移、位都按 RM0440《STM32G4 参考手册》，注释里写的是手册中的寄存器名；
 * 第 102 轮起逐个对照 ST 官方 CMSIS 头文件 stm32g431xx.h 核对（测试 test_drv_b_motor.py 里记着核对过的数）。
 * 第 100 轮：驱动板 B 版固件（示例）；第 102 轮加时钟、TIM1、ADC1、FDCAN1、NVIC、FPU。不用厂商库，学生能逐行对照手册。 */
#ifndef REGS_H
#define REGS_H
#include <stdint.h>

#define REG(addr) (*(volatile uint32_t *)(addr))
#define REG8(addr) (*(volatile uint8_t *)(addr))

/* RCC 复位与时钟控制，基址 0x4002 1000（手册“存储器映射”表）。上电系统时钟为 HSI16 = 16 MHz（RCC 章“时钟”节） */
#define RCC_BASE 0x40021000u
#define RCC_CR REG(RCC_BASE + 0x00)          /* RCC_CR：位 24 PLLON、位 25 PLLRDY */
#define RCC_CFGR REG(RCC_BASE + 0x08)        /* RCC_CFGR：位 1:0 SW、位 3:2 SWS（11 = PLL） */
#define RCC_PLLCFGR REG(RCC_BASE + 0x0C)     /* RCC_PLLCFGR：PLLSRC 位 1:0、PLLM 位 7:4、PLLN 位 14:8、PLLREN 位 24、PLLR 位 26:25 */
#define RCC_AHB2ENR REG(RCC_BASE + 0x4C)     /* RCC_AHB2ENR：位 0 GPIOAEN、位 1 GPIOBEN、位 13 ADC12EN */
#define RCC_APB1ENR1 REG(RCC_BASE + 0x58)    /* RCC_APB1ENR1：位 25 FDCANEN、位 28 PWREN */
#define RCC_APB2ENR REG(RCC_BASE + 0x60)     /* RCC_APB2ENR：位 11 TIM1EN、位 12 SPI1EN */
#define RCC_CCIPR REG(RCC_BASE + 0x88)       /* RCC_CCIPR：FDCANSEL 位 25:24（10 = PCLK1）、ADC12SEL 位 29:28（10 = 系统时钟） */
#define RCC_GPIOAEN (1u << 0)
#define RCC_GPIOBEN (1u << 1)
#define RCC_ADC12EN (1u << 13)
#define RCC_FDCANEN (1u << 25)
#define RCC_PWREN (1u << 28)
#define RCC_SPI3EN (1u << 15)                /* RCC_APB1ENR1：位 15 SPI3EN（第 107 轮） */
#define RCC_TIM4EN (1u << 2)                 /* RCC_APB1ENR1：位 2 TIM4EN（第 110 轮） */
#define RCC_TIM1EN (1u << 11)
#define RCC_SPI1EN (1u << 12)

/* FLASH 接口 0x4002 2000、PWR 0x4000 7000 */
#define FLASH_ACR REG(0x40022000u)           /* FLASH_ACR：LATENCY 位 3:0、PRFTEN 位 8、ICEN 位 9、DCEN 位 10 */
#define PWR_CR5 REG(0x40007000u + 0x80)      /* PWR_CR5：位 8 R1MODE（0 = 主调节器提升模式，170 MHz 需要） */

/* GPIO，基址 GPIOA 0x4800 0000、GPIOB 0x4800 0400（手册“存储器映射”表） */
#define GPIOA_BASE 0x48000000u
#define GPIOB_BASE 0x48000400u
#define GPIO_MODER(b) REG((b) + 0x00)        /* GPIOx_MODER：每脚 2 位，00 输入 01 输出 10 复用 11 模拟 */
#define GPIO_OSPEEDR(b) REG((b) + 0x08)      /* GPIOx_OSPEEDR */
#define GPIO_BSRR(b) REG((b) + 0x18)         /* GPIOx_BSRR：低 16 位置 1，高 16 位清 0 */
#define GPIO_AFRL(b) REG((b) + 0x20)         /* GPIOx_AFRL：每脚 4 位复用功能号 */

/* SPI1，基址 0x4001 3000（手册“存储器映射”表） */
#define SPI1_BASE 0x40013000u
#define SPI1_CR1 REG(SPI1_BASE + 0x00)       /* SPI_CR1 */
#define SPI1_CR2 REG(SPI1_BASE + 0x04)       /* SPI_CR2 */
#define SPI1_SR REG(SPI1_BASE + 0x08)        /* SPI_SR */
#define SPI1_DR8 REG8(SPI1_BASE + 0x0C)      /* SPI_DR：8 位访问，每次进出一个字节 */
#define SPI_CR1_CPHA (1u << 0)
#define SPI_CR1_CPOL (1u << 1)
#define SPI_CR1_MSTR (1u << 2)
#define SPI_CR1_BR_DIV4 (1u << 3)            /* BR[2:0] = 001：fPCLK/4（第 100 轮，16 MHz 时用） */
#define SPI_CR1_BR_DIV64 (5u << 3)           /* BR[2:0] = 101：fPCLK/64（第 102 轮，170 MHz / 64 = 2.66 MHz） */
#define SPI_CR1_SPE (1u << 6)
#define SPI_CR1_SSI (1u << 8)
#define SPI_CR1_SSM (1u << 9)
/* SPI3，基址 0x4000 3C00（APB1；第 107 轮读输出端绝对值编码器 SSI），寄存器偏移同 SPI1 */
#define SPI3_BASE 0x40003C00u
#define SPI3_CR1 REG(SPI3_BASE + 0x00)
#define SPI3_CR2 REG(SPI3_BASE + 0x04)
#define SPI3_SR REG(SPI3_BASE + 0x08)
#define SPI3_DR8 REG8(SPI3_BASE + 0x0C)
#define SPI_CR1_BR_DIV128 (6u << 3)          /* BR[2:0] = 110：fPCLK/128（170 MHz / 128 ≈ 1.33 MHz） */
#define SPI_CR2_DS_8BIT (7u << 8)            /* DS[3:0] = 0111：8 位 */
#define SPI_CR2_FRXTH (1u << 12)             /* 收满 8 位即 RXNE */
#define SPI_SR_RXNE (1u << 0)
#define SPI_SR_TXE (1u << 1)
#define SPI_SR_BSY (1u << 7)

/* SysTick（Cortex-M4 内核，PM0214《Cortex-M4 编程手册》SysTick 节） */
#define SYST_CSR REG(0xE000E010u)
#define SYST_RVR REG(0xE000E014u)
#define SYST_CVR REG(0xE000E018u)

/* TIM1 高级定时器，0x4001 2C00（偏移按 TIM_TypeDef） */
#define TIM1_BASE 0x40012C00u
#define TIM1_CR1 REG(TIM1_BASE + 0x00)       /* 位 0 CEN、位 6:5 CMS（01 中心对齐 1）、位 7 ARPE */
#define TIM1_CR2 REG(TIM1_BASE + 0x04)       /* MMS 位 6:4（010 = 更新事件作 TRGO） */
#define TIM1_EGR REG(TIM1_BASE + 0x14)       /* 位 0 UG */
#define TIM1_CCMR1 REG(TIM1_BASE + 0x18)     /* OC1PE 位 3、OC1M 位 6:4；OC2PE 位 11、OC2M 位 14:12 */
#define TIM1_CCMR2 REG(TIM1_BASE + 0x1C)     /* OC3PE 位 3、OC3M 位 6:4 */
#define TIM1_CCER REG(TIM1_BASE + 0x20)      /* CC1E 0、CC1NE 2、CC2E 4、CC2NE 6、CC3E 8、CC3NE 10 */
#define TIM1_PSC REG(TIM1_BASE + 0x28)
#define TIM1_ARR REG(TIM1_BASE + 0x2C)
#define TIM1_RCR REG(TIM1_BASE + 0x30)
#define TIM1_CCR1 REG(TIM1_BASE + 0x34)
#define TIM1_CCR2 REG(TIM1_BASE + 0x38)
#define TIM1_CCR3 REG(TIM1_BASE + 0x3C)
#define TIM1_BDTR REG(TIM1_BASE + 0x44)      /* DTG 位 7:0（死区）、位 15 MOE（主输出使能） */
#define TIM_BDTR_MOE (1u << 15)

/* ADC1，0x5000 0000（偏移按 ADC_TypeDef）；ADC12 公共寄存器 0x5000 0300 */
#define ADC1_BASE 0x50000000u
#define ADC1_ISR REG(ADC1_BASE + 0x00)       /* 位 0 ADRDY、位 5 JEOC、位 6 JEOS */
#define ADC1_IER REG(ADC1_BASE + 0x04)       /* 位 6 JEOSIE */
#define ADC1_CR REG(ADC1_BASE + 0x08)        /* 位 0 ADEN、位 3 JADSTART、位 28 ADVREGEN、位 29 DEEPPWD、位 31 ADCAL */
#define ADC1_SMPR2 REG(ADC1_BASE + 0x18)     /* 第 114 轮：SMP15 位 17:15 */
#define ADC1_SQR1 REG(ADC1_BASE + 0x30)      /* 第 114 轮：L 位 3:0、SQ1 位 10:6 */
#define ADC1_DR REG(ADC1_BASE + 0x40)        /* 第 114 轮：规则组结果，读后清 EOC */
#define ADC1_JSQR REG(ADC1_BASE + 0x4C)      /* JL 位 1:0、JEXTSEL 位 6:2（0 = TIM1_TRGO）、JEXTEN 位 8:7、JSQ1–4 位 9/15/21/27 起 */
#define ADC1_JDR(n) REG(ADC1_BASE + 0x80 + 4 * (n))
#define ADC12_CCR REG(0x50000300u + 0x08)    /* ADC_CCR：CKMODE 位 17:16 */
#define ADC_ISR_ADRDY (1u << 0)
#define ADC_ISR_JEOS (1u << 6)
#define ADC_ISR_EOC (1u << 2)                /* 第 114 轮：规则组转换完成 */
#define ADC_CR_ADSTART (1u << 2)             /* 第 114 轮：规则组软件启动 */

/* FDCAN1，0x4000 6400（偏移按 FDCAN_GlobalTypeDef）；消息 RAM SRAMCAN 0x4000 A400（布局按 HAL stm32g4xx_hal_fdcan.c） */
#define FDCAN1_BASE 0x40006400u
#define FDCAN1_CCCR REG(FDCAN1_BASE + 0x018) /* 位 0 INIT、位 1 CCE */
#define FDCAN1_NBTP REG(FDCAN1_BASE + 0x01C) /* NTSEG2 位 6:0、NTSEG1 位 15:8、NBRP 位 24:16、NSJW 位 31:25 */
#define FDCAN1_IR REG(FDCAN1_BASE + 0x050)   /* 位 0 RF0N（Rx FIFO0 有新帧），写 1 清 */
#define FDCAN1_IE REG(FDCAN1_BASE + 0x054)   /* 位 0 RF0NE */
#define FDCAN1_ILE REG(FDCAN1_BASE + 0x05C)  /* 位 0 EINT0 */
#define FDCAN1_RXGFC REG(FDCAN1_BASE + 0x080)/* ANFS 位 5:4 = 00：不匹配的标准帧收进 FIFO0 */
#define FDCAN1_RXF0S REG(FDCAN1_BASE + 0x090)/* F0FL 位 3:0（帧数）、F0GI 位 9:8（取出索引） */
#define FDCAN1_RXF0A REG(FDCAN1_BASE + 0x094)
#define FDCAN1_TXFQS REG(FDCAN1_BASE + 0x0C4)/* TFQPI 位 17:16（放入索引）、TFQF 位 21（满） */
#define FDCAN1_TXBAR REG(FDCAN1_BASE + 0x0CC)
#define SRAMCAN_BASE 0x4000A400u
#define SRAMCAN_RF0SA 0x0B0u                  /* 28 个标准滤波 ×4 + 8 个扩展滤波 ×8 之后 */
#define SRAMCAN_TFQSA 0x278u                  /* Rx FIFO0/1、Tx 事件之后 */
#define SRAMCAN_ESIZE 72u                     /* 每个元素 18 字 */

/* Cortex-M4 内核：NVIC、SCB（PM0214《Cortex-M4 编程手册》） */
#define NVIC_ISER(n) REG(0xE000E100u + 4 * (n))
#define NVIC_IPR8(n) REG8(0xE000E400u + (n))
#define SCB_CPACR REG(0xE000ED88u)            /* 位 23:20 = 1111：打开 FPU（CP10、CP11） */
#define IRQ_ADC1_2 18
#define IRQ_FDCAN1_IT0 21

#define SYSCLK_HZ 170000000u

/* TIM4，基址 0x4000 0800（APB1；第 110 轮抱闸 PWM，CH1 = PB6 AF2）。偏移同 TIM_TypeDef；对照 ST 官方 CMSIS 头文件 */
#define TIM4_BASE 0x40000800u
#define TIM4_CR1 REG(TIM4_BASE + 0x00)       /* TIM_CR1：位 0 CEN、位 7 ARPE */
#define TIM4_EGR REG(TIM4_BASE + 0x14)       /* TIM_EGR：位 0 UG */
#define TIM4_CCMR1 REG(TIM4_BASE + 0x18)     /* TIM_CCMR1：位 3 OC1PE、OC1M 位 6:4 + 位 16（0110 = PWM 模式 1） */
#define TIM4_CCER REG(TIM4_BASE + 0x20)      /* TIM_CCER：位 0 CC1E */
#define TIM4_PSC REG(TIM4_BASE + 0x28)
#define TIM4_ARR REG(TIM4_BASE + 0x2C)
#define TIM4_CCR1 REG(TIM4_BASE + 0x34)

#endif
