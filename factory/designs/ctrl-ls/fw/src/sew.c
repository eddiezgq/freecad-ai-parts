/* 缝纫状态机（第 159 轮 159f），1 kHz（电流环中断里经 motor_ms_hook 调）。
 * 脚踏板：霍尔 0.5–4.5 V（设计描述 sensor_inputs.pedal_v_max），经 10 k / 20 k 分压进 PB1；motor.c 换回霍尔电压。
 *   后踩 < 0.9 V、回中 0.9–1.4 V、前踩 > 1.4 V；前踩 1.4 → 4.2 V 对应 200 → 5000 r/min（分界和满量程是示例值，按脚踏板标定改）。
 * 电磁铁（按原理图 U10）：剪线 PA5、拨线 PA11、倒缝 PA12、抬压脚 PA15。经 2N7002 反相驱动 80 V 管：
 *   引脚低 = 吸合；复位时引脚上拉、电磁铁不动作——所以先把输出置高、再把引脚设成输出。 */
#include "sew.h"
#include "motor.h"
#include "regs.h"

volatile cfg_t cfg = {
    0x31474643u,      /* "CFG1" */
    4, 4, 1800.0f,    /* 起缝加固：正 4 针、倒 4 针、1800 r/min（示例） */
    300.0f,           /* 剪线转速（159c） */
    7000, 18000,      /* 上针位 70°、下针位 180° */
    20000, 33000,     /* 剪线窗口 200°–330° */
    50,               /* 拨线 50 ms（示例） */
    10000,            /* 抬压脚最长 10 s（示例） */
};
volatile sew_t sw;

#define SOL_TRIM 0
#define SOL_WIPE 1
#define SOL_REV 2
#define SOL_FOOT 3
static const uint32_t SOL_PIN[4] = {5, 11, 12, 15};

static uint32_t trim_phase, trim_win, trim_prev_out;
static int32_t trim_start;

static void sol(int k, int on)
{
    if (on) {
        GPIO_BSRR(GPIOA_BASE) = 1u << (SOL_PIN[k] + 16);                          /* 拉低 = 吸合 */
        sw.sol |= 1u << k;
    } else {
        GPIO_BSRR(GPIOA_BASE) = 1u << SOL_PIN[k];
        sw.sol &= ~(1u << k);
    }
}

void sew_init(void)
{
    sw.magic = 0x31574553u;                                                       /* "SEW1" */
    RCC_AHB2ENR |= RCC_GPIOAEN;
    for (int k = 0; k < 4; k++) {
        GPIO_BSRR(GPIOA_BASE) = 1u << SOL_PIN[k];                                 /* 先置高（不吸合） */
        GPIO_MODER(GPIOA_BASE) = (GPIO_MODER(GPIOA_BASE) & ~(3u << (2 * SOL_PIN[k]))) | (1u << (2 * SOL_PIN[k]));
    }
    sw.sol = 0;
    sw.state = SW_BOOT;
}

static void go(uint32_t s)
{
    sw.state = s;
    sw.t_state_ms = mc.ms;
}

static void all_off(void)
{
    for (int k = 0; k < 4; k++) {
        sol(k, 0);
    }
}

void motor_z_hook(void)
{
    sw.stitches++;
    sw.seam_stitches++;
}

static int in_win(int32_t a) { return a >= cfg.trim_on_x100 && a < cfg.trim_off_x100; }

void motor_ms_hook(void)
{
    /* 脚踏 */
    float v = mc.pedal_v;
    sw.pedal = v < 0.9f ? 0u : (v < 1.4f ? 1u : 2u);
    float r = 200.0f + (v - 1.4f) / (4.2f - 1.4f) * (RPM_MAX - 200.0f);
    sw.pedal_rpm = r < 200.0f ? 200.0f : (r > RPM_MAX ? RPM_MAX : r);

    if (mc.state == MS_FAULT && sw.state != SW_FAULT) {
        all_off();                                                                /* 故障：电磁铁全部释放 */
        go(SW_FAULT);
    }
    uint32_t dt = mc.ms - sw.t_state_ms;
    switch (sw.state) {
    case SW_BOOT:
        if (mc.state == MS_READY) {
            go(SW_IDLE);
        }
        break;
    case SW_IDLE:
        if (sw.pedal == 2) {
            sw.seam_stitches = 0;
            if (cfg.bt_fwd + cfg.bt_rev > 0) {
                motor_speed(cfg.bt_rpm);
                go(SW_BT_FWD);
            } else {
                motor_speed(sw.pedal_rpm);
                go(SW_SEW);
            }
        } else if (sw.pedal == 0) {
            sol(SOL_FOOT, 1);
            go(SW_FOOT);
        }
        break;
    case SW_BT_FWD:                                                               /* 加固走完才看脚踏（中途松脚也缝完） */
        if (sw.seam_stitches >= cfg.bt_fwd) {
            sol(SOL_REV, 1);
            go(SW_BT_REV);
        }
        break;
    case SW_BT_REV:
        if (sw.seam_stitches >= cfg.bt_fwd + cfg.bt_rev) {
            sol(SOL_REV, 0);
            go(SW_SEW);
        }
        break;
    case SW_SEW:
        if (sw.pedal == 2) {
            motor_speed(sw.pedal_rpm);
        } else if (sw.pedal == 1) {
            motor_speed(cfg.trim_rpm);
            go(SW_STOP_DN);
        } else {
            trim_phase = 0;
            motor_speed(cfg.trim_rpm);
            go(SW_TRIM);
        }
        break;
    case SW_STOP_DN:
        if (sw.pedal == 2) {
            go(SW_SEW);
        } else if (sw.pedal == 0) {
            trim_phase = 0;
            motor_speed(cfg.trim_rpm);
            go(SW_TRIM);
        } else if (mc.mode == MM_SPEED && mc.speed_ref <= cfg.trim_rpm) {
            motor_stop_at(cfg.down_x100);
        } else if (motor_stopped()) {
            go(SW_DOWN);
        }
        break;
    case SW_DOWN:
        if (sw.pedal == 2) {
            motor_speed(sw.pedal_rpm);
            go(SW_SEW);
        } else if (sw.pedal == 0) {
            trim_phase = 0;
            motor_speed(cfg.trim_rpm);
            go(SW_TRIM);
        }
        break;
    case SW_TRIM:
        /* 0：减（或加）到剪线转速；1：在剪线转速下至少转一整圈、并且剪完（剪线电磁铁在窗口里吸合、释放过一次）；2：停上针位 */
        if (trim_phase == 0 && motor_ramp_done()) {
            trim_phase = 1;
            trim_win = 0;
            trim_prev_out = 0;
            trim_start = mc.pos_cnt;
        } else if (trim_phase == 1 && mc.pos_cnt - trim_start >= CNT_PER_REV && trim_win == 2) {
            trim_phase = 2;
            motor_stop_at(cfg.up_x100);
        }
        if (trim_phase >= 1 && trim_win < 2) {
            /* 从窗口外转进来（过 200°）才吸合：剪线转速到了的时候主轴若已在窗口里，等下一圈，不半路吸合 */
            int w = in_win(mc.angle_x100);
            if (w && trim_win == 0 && trim_prev_out) {
                sol(SOL_TRIM, 1);
                trim_win = 1;
            } else if (!w && trim_win == 0) {
                trim_prev_out = 1;
            } else if (!w && trim_win == 1) {
                sol(SOL_TRIM, 0);
                trim_win = 2;
                sw.trims++;
            }
        }
        if (trim_phase == 2 && motor_stopped()) {
            sol(SOL_TRIM, 0);
            sol(SOL_WIPE, 1);
            go(SW_WIPE);
        }
        break;
    case SW_WIPE:
        if (dt >= cfg.wipe_ms) {
            sol(SOL_WIPE, 0);
            sol(SOL_FOOT, 1);
            go(SW_FOOT);
        }
        break;
    case SW_FOOT:
        if (sw.pedal != 0 || dt >= cfg.foot_max_ms) {                             /* 松开后踩（或到时间）：压脚放下，等下一条缝 */
            sol(SOL_FOOT, 0);
            go(SW_IDLE);
        }
        break;
    default:
        break;
    }
}
