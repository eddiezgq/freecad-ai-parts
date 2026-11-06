/* STM32G431 寄存器——只列本固件用到的。地址、偏移、位都按 RM0440《STM32G4 参考手册》，注释里写的是手册中的寄存器名。
 * 第 100 轮：驱动板 B 版固件（示例）。不用厂商库，学生能逐行对照手册。 */
#ifndef REGS_H
#define REGS_H
#include <stdint.h>

#define REG(addr) (*(volatile uint32_t *)(addr))
#define REG8(addr) (*(volatile uint8_t *)(addr))

/* RCC 复位与时钟控制，基址 0x4002 1000（手册“存储器映射”表）。上电系统时钟为 HSI16 = 16 MHz（RCC 章“时钟”节） */
#define RCC_BASE 0x40021000u
#define RCC_AHB2ENR REG(RCC_BASE + 0x4C)     /* RCC_AHB2ENR：位 0 GPIOAEN、位 1 GPIOBEN */
#define RCC_APB2ENR REG(RCC_BASE + 0x60)     /* RCC_APB2ENR：位 12 SPI1EN */
#define RCC_GPIOAEN (1u << 0)
#define RCC_GPIOBEN (1u << 1)
#define RCC_SPI1EN (1u << 12)

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
#define SPI_CR1_BR_DIV4 (1u << 3)            /* BR[2:0] = 001：fPCLK/4 */
#define SPI_CR1_SPE (1u << 6)
#define SPI_CR1_SSI (1u << 8)
#define SPI_CR1_SSM (1u << 9)
#define SPI_CR2_DS_8BIT (7u << 8)            /* DS[3:0] = 0111：8 位 */
#define SPI_CR2_FRXTH (1u << 12)             /* 收满 8 位即 RXNE */
#define SPI_SR_RXNE (1u << 0)
#define SPI_SR_TXE (1u << 1)
#define SPI_SR_BSY (1u << 7)

/* SysTick（Cortex-M4 内核，PM0214《Cortex-M4 编程手册》SysTick 节） */
#define SYST_CSR REG(0xE000E010u)
#define SYST_RVR REG(0xE000E014u)
#define SYST_CVR REG(0xE000E018u)

#define SYSCLK_HZ 16000000u

#endif
