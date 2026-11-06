/* FDCAN1 驱动（经典 CAN 1 Mbit/s）。引脚 PA11 RX、PA12 TX（AF9，第 88 轮原理图第 33、34 脚）。
 * 消息 RAM 按 STM32G4 固定布局：Rx FIFO0 从 0xB0 起、Tx FIFO 从 0x278 起，每个元素 18 字（头 2 字 + 64 字节数据）。 */
#include "can.h"
#include "regs.h"

#define RAM(off) REG(SRAMCAN_BASE + (off))

void can_init(void)
{
    RCC_APB1ENR1 |= RCC_FDCANEN;
    RCC_CCIPR = (RCC_CCIPR & ~(3u << 24)) | (2u << 24);       /* FDCAN 时钟 = PCLK1 = 170 MHz */
    GPIO_MODER(GPIOA_BASE) = (GPIO_MODER(GPIOA_BASE) & ~(0xFu << 22)) | (2u << 22) | (2u << 24);
    REG(GPIOA_BASE + 0x24) = (REG(GPIOA_BASE + 0x24) & ~(0xFFu << 12)) | (9u << 12) | (9u << 16);   /* GPIOA_AFRH：PA11、PA12 = AF9 */

    FDCAN1_CCCR |= 1u;                                         /* INIT */
    while (!(FDCAN1_CCCR & 1u)) {
    }
    FDCAN1_CCCR |= 2u;                                         /* CCE：允许改配置 */
    /* 1 Mbit/s：170 MHz / 10 = 17 MHz 时间份额；1 + 13 + 3 = 17 份额/位，采样点 82 % */
    FDCAN1_NBTP = (1u << 25) | (9u << 16) | (12u << 8) | 2u;
    FDCAN1_RXGFC = 0;                                          /* 不匹配的标准帧收进 FIFO0 */
    for (uint32_t i = 0; i < 0x350u; i += 4) {
        RAM(i) = 0;
    }
    FDCAN1_IE = 1u;                                            /* RF0NE */
    FDCAN1_ILE = 1u;                                           /* EINT0 */
    FDCAN1_CCCR &= ~1u;                                        /* 退出初始化，上总线 */
    NVIC_IPR8(IRQ_FDCAN1_IT0) = 0x40;                          /* 比电流环（0x00）低 */
    NVIC_ISER(IRQ_FDCAN1_IT0 / 32) = 1u << (IRQ_FDCAN1_IT0 % 32);
}

void can_send(uint16_t id, const uint8_t *data, uint8_t len)
{
    uint32_t q = FDCAN1_TXFQS;
    if (q & (1u << 21)) {                                      /* TFQF：发送队列满，丢 */
        return;
    }
    uint32_t idx = (q >> 16) & 3u;
    uint32_t a = SRAMCAN_TFQSA + idx * SRAMCAN_ESIZE;
    uint32_t w[2] = {0, 0};
    for (uint8_t i = 0; i < len && i < 8; i++) {
        w[i / 4] |= (uint32_t)data[i] << (8 * (i % 4));
    }
    RAM(a) = (uint32_t)(id & 0x7FF) << 18;                     /* T0：标准 ID 在位 28:18 */
    RAM(a + 4) = (uint32_t)len << 16;                          /* T1：DLC 在位 19:16 */
    RAM(a + 8) = w[0];
    RAM(a + 12) = w[1];
    FDCAN1_TXBAR = 1u << idx;
}

void FDCAN1_IT0_IRQHandler(void)
{
    while (FDCAN1_RXF0S & 0xFu) {
        uint32_t gi = (FDCAN1_RXF0S >> 8) & 3u;
        uint32_t a = SRAMCAN_RF0SA + gi * SRAMCAN_ESIZE;
        uint32_t r0 = RAM(a), r1 = RAM(a + 4);
        uint8_t d[8];
        uint32_t w0 = RAM(a + 8), w1 = RAM(a + 12);
        for (int i = 0; i < 4; i++) {
            d[i] = (uint8_t)(w0 >> (8 * i));
            d[i + 4] = (uint8_t)(w1 >> (8 * i));
        }
        uint8_t len = (uint8_t)((r1 >> 16) & 0xF);
        FDCAN1_RXF0A = gi;
        can_rx_handler((uint16_t)((r0 >> 18) & 0x7FF), d, len > 8 ? 8 : len);
    }
    FDCAN1_IR = 1u;                                            /* 清 RF0N */
}
