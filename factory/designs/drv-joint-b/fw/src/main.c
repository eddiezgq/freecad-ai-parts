/* 关节驱动板 DRV-JOINT B 版 示例固件：经 SPI1 读编码器接口芯片 WQ-ENCIF。第 100 轮。
 * 每 1 ms：读计数和状态 → 算角度、转速、圈数；Z 相锁存后给出绝对角度；芯片报错时记数并清除；
 * 芯片不响应（ID 不对）时停在“芯片缺失”，每 100 ms 重试一次。
 * 板上没有调试串口：结果放在内存里的遥测区 tlm，调试器经 SWD 看（仿真里由 Renode 读内存）。
 * 示例固件，仿真验证；芯片未流片、B 版不投产。 */
#include <stdint.h>
#include "encif.h"
#include "regs.h"

#define CPR 10000          /* 2500 线编码器 ×4（第 88 轮的示例编码器） */
#define WIN_MS 10          /* 转速取 10 ms 窗口 */
#define RETRY_MS 100

enum { ST_BOOT = 0, ST_RUN = 1, ST_MISSING = 2 };

typedef struct {
    uint32_t magic;        /* "TLM1" */
    uint32_t state;        /* 0 启动、1 运行、2 芯片缺失 */
    uint32_t id;           /* 读到的芯片 ID */
    uint32_t ctrl;         /* 回读的控制寄存器 */
    uint32_t tick_ms;
    int32_t cnt;           /* 芯片计数（补码，可为负） */
    int32_t turns;         /* 开机以来的圈数（向下取整） */
    int32_t angle_cnt;     /* 本圈内位置 0..CPR-1（相对开机位置） */
    int32_t rpm_x10;       /* 转速 ×10 */
    int32_t idx;           /* Z 相锁存的计数 */
    uint32_t idx_valid;
    int32_t abs_cnt;       /* 绝对位置 0..CPR-1（相对 Z 相）；未见 Z 时 -1 */
    uint32_t err_count;    /* 芯片报的错误（A/B 同跳）次数 */
    uint32_t status;       /* 最近一次状态寄存器 */
    uint32_t frames;       /* SPI 帧数 */
    uint32_t retries;      /* 芯片缺失时的重试次数 */
} telemetry_t;

volatile telemetry_t tlm;
static volatile uint32_t ticks;
static int32_t hist[WIN_MS];

void SysTick_Handler(void) { ticks++; }

static int32_t mod_cpr(int32_t x) { int32_t r = x % CPR; return r < 0 ? r + CPR : r; }
static int32_t div_cpr(int32_t x) { return (x - mod_cpr(x)) / CPR; }

static int chip_start(void)
{
    encif_reset();
    tlm.id = encif_read(ENCIF_R_ID);
    tlm.frames++;
    if (tlm.id != ENCIF_ID) {
        return 0;
    }
    encif_write(ENCIF_R_CTRL, 0x31);          /* 使能、不反向、Z 不清零、滤波长度 3 */
    tlm.ctrl = encif_read(ENCIF_R_CTRL);
    encif_write(ENCIF_R_STATUS, ENCIF_ST_ERR | ENCIF_ST_IVLD);
    tlm.frames += 3;
    for (int i = 0; i < WIN_MS; i++) {
        hist[i] = 0;
    }
    tlm.idx_valid = 0;
    tlm.abs_cnt = -1;
    return 1;
}

static void sample(uint32_t now)
{
    int32_t c = (int32_t)encif_read(ENCIF_R_CNT);
    uint32_t st = encif_read(ENCIF_R_STATUS);
    tlm.frames += 2;
    tlm.cnt = c;
    tlm.status = st;
    tlm.turns = div_cpr(c);
    tlm.angle_cnt = mod_cpr(c);

    int k = (int)(now % WIN_MS);
    if (now >= WIN_MS) {
        tlm.rpm_x10 = (c - hist[k]) * 6;      /* 计数/10 ms → rpm×10：d / CPR / 0.01 s × 60 × 10 = d × 6 */
    }
    hist[k] = c;

    if (st & ENCIF_ST_IVLD) {                 /* 过了 Z：取锁存值，清标志等下一次 */
        tlm.idx = (int32_t)encif_read(ENCIF_R_IDX);
        tlm.idx_valid = 1;
        encif_write(ENCIF_R_STATUS, ENCIF_ST_IVLD);
        tlm.frames += 2;
    }
    if (tlm.idx_valid) {
        tlm.abs_cnt = mod_cpr(c - tlm.idx);
    }
    if (st & ENCIF_ST_ERR) {                  /* A/B 同时跳：丢步风险，记一次并清除 */
        tlm.err_count++;
        encif_write(ENCIF_R_STATUS, ENCIF_ST_ERR);
        tlm.frames++;
    }
}

int main(void)
{
    tlm.magic = 0x314D4C54u;
    tlm.state = ST_BOOT;
    tlm.abs_cnt = -1;

    SYST_RVR = SYSCLK_HZ / 1000u - 1u;        /* 1 kHz */
    SYST_CVR = 0;
    SYST_CSR = 7;                             /* 处理器时钟、开中断、使能 */

    encif_init_bus();
    tlm.state = chip_start() ? ST_RUN : ST_MISSING;

    uint32_t last = ticks;
    for (;;) {
        while (ticks == last) {
            __asm volatile("wfi");
        }
        last = ticks;
        tlm.tick_ms = last;
        if (tlm.state == ST_RUN) {
            sample(last);
        } else if (last % RETRY_MS == 0) {
            tlm.retries++;
            if (chip_start()) {
                tlm.state = ST_RUN;
            }
        }
    }
}
