/* 输出端绝对值编码器（SSI，第 107 轮）。帧格式见 ssi.c。 */
#ifndef SSI_H
#define SSI_H
#include <stdint.h>

#define SSI_BITS 17
#define SSI_COUNTS (1u << SSI_BITS)   /* 131 072 计数/圈 */

void ssi_init(void);
/* 读一帧：返回 1 = 帧有效（起始位为 1、错误位为 0、不是全 1），*pos 为 0..SSI_COUNTS-1 */
int ssi_read(uint32_t *pos);

#endif
