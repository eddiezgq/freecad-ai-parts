/* WQ-ENCIF 驱动：40 位一帧（8 位命令 + 32 位数据，高位先出），SPI 模式 0。寄存器见第 92 轮规格。 */
#ifndef ENCIF_H
#define ENCIF_H
#include <stdint.h>

#define ENCIF_ID 0x454E4331u      /* "ENC1" */
#define ENCIF_R_ID 0
#define ENCIF_R_CTRL 1            /* 位 0 使能、1 反向、2 Z 清零、4–7 滤波长度 */
#define ENCIF_R_STATUS 2          /* 位 0 方向、1 错误、2 Z 已锁存；写 1 清位 1、位 2 */
#define ENCIF_R_CNT 3
#define ENCIF_R_IDX 4
#define ENCIF_ST_ERR (1u << 1)
#define ENCIF_ST_IVLD (1u << 2)

void encif_init_bus(void);
void encif_reset(void);
uint32_t encif_read(uint8_t addr);
void encif_write(uint8_t addr, uint32_t data);

#endif
