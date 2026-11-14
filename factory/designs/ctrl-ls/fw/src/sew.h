/* 缝纫状态机（第 159 轮 159f）：脚踏 → 起缝加固 → 缝纫 → 停针 → 剪线 → 拨线 → 抬压脚。 */
#ifndef SEW_H
#define SEW_H
#include <stdint.h>

enum {
    SW_BOOT = 0,      /* 等电机就绪（对零、找 Z 相、停上针位） */
    SW_IDLE = 1,      /* 一条缝开始前：停在上针位、压脚放下 */
    SW_BT_FWD = 2,    /* 起缝加固：先正缝 bt_fwd 针 */
    SW_BT_REV = 3,    /* 起缝加固：再倒缝 bt_rev 针（倒缝电磁铁吸合） */
    SW_SEW = 4,       /* 缝纫：转速跟脚踏 */
    SW_STOP_DN = 5,   /* 脚踏回中：减速、停下针位 */
    SW_DOWN = 6,      /* 停在下针位（针在布里），可接着缝或剪线 */
    SW_TRIM = 7,      /* 脚踏后踩：减到剪线转速、转一针剪线（剪线电磁铁在剪线角度窗口内吸合）、停上针位 */
    SW_WIPE = 8,      /* 拨线电磁铁吸合一下 */
    SW_FOOT = 9,      /* 抬压脚（后踩不松就一直抬着） */
    SW_FAULT = 10
};

/* 操作面板能改的设置（示例默认值；仿真里由 Renode 写内存，相当于面板改设置） */
typedef struct {
    uint32_t magic;           /* "CFG1" */
    uint32_t bt_fwd;          /* 起缝加固正缝针数（0 = 不加固） */
    uint32_t bt_rev;          /* 起缝加固倒缝针数 */
    float bt_rpm;             /* 起缝加固转速 r/min */
    float trim_rpm;           /* 剪线转速 r/min（159c：300） */
    int32_t up_x100;          /* 上针位 0.01°（第 138 轮：70°） */
    int32_t down_x100;        /* 下针位 0.01°（针杆最低点 180°，第 138 轮 G2 机构） */
    int32_t trim_on_x100;     /* 剪线电磁铁吸合角度窗口 200°–330°（159c / 第 138 轮剪线动刀） */
    int32_t trim_off_x100;
    uint32_t wipe_ms;         /* 拨线电磁铁吸合时间 */
    uint32_t foot_max_ms;     /* 抬压脚最长时间（线圈 3 A 不能一直通电；示例） */
} cfg_t;

typedef struct {
    uint32_t magic;           /* "SEW1" */
    uint32_t state;           /* SW_* */
    uint32_t stitches;        /* 开机以来的针数（过针杆最高点计一针） */
    uint32_t seam_stitches;   /* 这条缝的针数 */
    uint32_t sol;             /* 电磁铁：位 0 剪线、1 拨线、2 倒缝、3 抬压脚（1 = 吸合） */
    uint32_t pedal;           /* 0 后踩、1 回中、2 前踩 */
    float pedal_rpm;          /* 脚踏给的转速 */
    uint32_t trims;           /* 剪线次数 */
    uint32_t t_state_ms;      /* 进当前状态时的时刻 */
} sew_t;

extern volatile cfg_t cfg;
extern volatile sew_t sw;

void sew_init(void);

#endif
