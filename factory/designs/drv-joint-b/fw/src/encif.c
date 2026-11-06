/* WQ-ENCIF 驱动。引脚（第 98 轮 B 版原理图）：PA4 片选（软件控制）、PA5 SCK、PA6 MISO、PA7 MOSI（AF5 = SPI1），PB1 芯片复位。 */
#include "encif.h"
#include "regs.h"

static void delay_cycles(volatile uint32_t n)
{
    while (n--) {
    }
}

void encif_init_bus(void)
{
    RCC_AHB2ENR |= RCC_GPIOAEN | RCC_GPIOBEN;
    RCC_APB2ENR |= RCC_SPI1EN;

    /* PA4 推挽输出（片选，先拉高）；PA5/6/7 复用 AF5（STM32G431 数据手册 DS12589 复用功能表：PA5/PA6/PA7 的 SPI1 为 AF5） */
    GPIO_BSRR(GPIOA_BASE) = 1u << 4;
    GPIO_MODER(GPIOA_BASE) = (GPIO_MODER(GPIOA_BASE) & ~(0xFFu << 8)) | (1u << 8) | (2u << 10) | (2u << 12) | (2u << 14);
    GPIO_OSPEEDR(GPIOA_BASE) |= 0xFFu << 8;
    GPIO_AFRL(GPIOA_BASE) = (GPIO_AFRL(GPIOA_BASE) & ~(0xFFFu << 20)) | (5u << 20) | (5u << 24) | (5u << 28);
    /* PB1 推挽输出（芯片复位，低有效，先拉低） */
    GPIO_BSRR(GPIOB_BASE) = 1u << (16 + 1);
    GPIO_MODER(GPIOB_BASE) = (GPIO_MODER(GPIOB_BASE) & ~(3u << 2)) | (1u << 2);

    /* SPI1：主机、模式 0（CPOL=0 CPHA=0）、170 MHz/64 = 2.66 MHz（芯片要求 SCLK ≤ 50 MHz/10）、软件片选、8 位 */
    SPI1_CR1 = SPI_CR1_MSTR | SPI_CR1_BR_DIV64 | SPI_CR1_SSM | SPI_CR1_SSI;
    SPI1_CR2 = SPI_CR2_DS_8BIT | SPI_CR2_FRXTH;
    SPI1_CR1 |= SPI_CR1_SPE;
}

void encif_reset(void)
{
    GPIO_BSRR(GPIOB_BASE) = 1u << (16 + 1);
    delay_cycles(1000);
    GPIO_BSRR(GPIOB_BASE) = 1u << 1;
    delay_cycles(1000);  /* 芯片同步器与上电对齐要几拍（50 MHz 下 < 1 µs） */
}

static uint8_t xfer(uint8_t b)
{
    while (!(SPI1_SR & SPI_SR_TXE)) {
    }
    SPI1_DR8 = b;
    while (!(SPI1_SR & SPI_SR_RXNE)) {
    }
    return SPI1_DR8;
}

static uint32_t frame(uint8_t cmd, uint32_t data)
{
    uint32_t r = 0;
    GPIO_BSRR(GPIOA_BASE) = 1u << (16 + 4);   /* 片选拉低 */
    xfer(cmd);
    for (int i = 3; i >= 0; i--) {
        r = (r << 8) | xfer((uint8_t)(data >> (8 * i)));
    }
    while (SPI1_SR & SPI_SR_BSY) {
    }
    GPIO_BSRR(GPIOA_BASE) = 1u << 4;          /* 片选拉高：一帧结束 */
    return r;
}

uint32_t encif_read(uint8_t addr) { return frame(addr & 0x7F, 0); }

void encif_write(uint8_t addr, uint32_t data) { (void)frame(0x80 | (addr & 0x7F), data); }
