/* 输出端绝对值编码器（SSI）驱动，第 107 轮。板上 J4 经两片 RS-485 收发（MAX3485，第 88 轮）：PB3 = SPI3_SCK 出时钟、PB4 = SPI3_MISO 收数据（AF6，第 98 轮）。
 * 帧（示例格式）：24 个时钟，第 1 位起始位恒 1，接着 17 位单圈位置（二进制、高位先出），再 1 位错误位（0 正常），其余补 0。
 * SPI3 主机、模式 3（时钟空闲为高、第二个边沿采样）、170 MHz / 128 ≈ 1.33 MHz；两帧之间时钟停的时间远大于编码器的单稳态时间（约 15 µs）。 */
#include "ssi.h"
#include "regs.h"

void ssi_init(void)
{
    RCC_APB1ENR1 |= RCC_SPI3EN;
    RCC_AHB2ENR |= RCC_GPIOBEN;
    GPIO_MODER(GPIOB_BASE) = (GPIO_MODER(GPIOB_BASE) & ~(0xFu << 6)) | (2u << 6) | (2u << 8);       /* PB3、PB4 复用 */
    GPIO_AFRL(GPIOB_BASE) = (GPIO_AFRL(GPIOB_BASE) & ~(0xFFu << 12)) | (6u << 12) | (6u << 16);      /* AF6 = SPI3 */
    SPI3_CR1 = SPI_CR1_MSTR | SPI_CR1_BR_DIV128 | SPI_CR1_SSM | SPI_CR1_SSI | SPI_CR1_CPOL | SPI_CR1_CPHA;
    SPI3_CR2 = SPI_CR2_DS_8BIT | SPI_CR2_FRXTH;
    SPI3_CR1 |= SPI_CR1_SPE;
}

static uint8_t xfer(void)
{
    while (!(SPI3_SR & SPI_SR_TXE)) {
    }
    SPI3_DR8 = 0xFF;
    while (!(SPI3_SR & SPI_SR_RXNE)) {
    }
    return SPI3_DR8;
}

int ssi_read(uint32_t *pos)
{
    uint32_t f = 0;
    for (int i = 0; i < 3; i++) {
        f = (f << 8) | xfer();
    }
    while (SPI3_SR & SPI_SR_BSY) {
    }
    if (f == 0xFFFFFFu || !(f & (1u << 23)) || (f & (1u << 5))) {   /* 线断（全 1）、没有起始位、错误位 */
        return 0;
    }
    *pos = (f >> 6) & (SSI_COUNTS - 1u);
    return 1;
}
