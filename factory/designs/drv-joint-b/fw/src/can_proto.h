/* 驱动板 CAN 协议（示例，第 102 轮）。经典 CAN 1 Mbit/s，标准 ID，节点号 1，小端。
 *
 *   0x201  主站 → 驱动板  指令    [0] 模式：0 停、1 速度、2 位置、3 清故障、4 力矩（q 轴电流）
 *                                 [1..4] 目标（int32）：速度 = 电机 rpm；位置 = 关节角 0.001°；力矩 = q 轴电流 mA
 *   0x181  驱动板 → 主站  状态 100 Hz  [0] 状态 [1] 故障码 [2..3] 关节角 0.01°（int16）[4..5] 电机转速 rpm（int16）[6..7] q 轴电流 0.01 A（int16）
 *   0x081  驱动板 → 主站  报警（出故障时立即发一次）  [0] 故障码 [1..2] 相关值 ×0.01（int16：电流 A 或电压 V）
 *   0x701  驱动板 → 主站  心跳 10 Hz  [0] 状态 [1..2] 母线电压 0.1 V（uint16）
 *
 *   状态：0 初始化（对零）、1 就绪、2 运行、3 故障
 *   故障码：1 过流（任一相 > 25 A）、2 欠压（母线 < 36 V）、3 编码器（芯片报错或不响应）、4 通信超时（运行中 100 ms 收不到指令）
 *   运行中要持续发指令（≥ 10 Hz）；故障锁存，发“清故障”才回到就绪（编码器故障要重新对零）。 */
#ifndef CAN_PROTO_H
#define CAN_PROTO_H

#define NODE 1
#define CAN_ID_CMD (0x200 + NODE)
#define CAN_ID_STATUS (0x180 + NODE)
#define CAN_ID_EMCY (0x080 + NODE)
#define CAN_ID_HEART (0x700 + NODE)

enum { MODE_STOP = 0, MODE_SPEED = 1, MODE_POS = 2, MODE_CLEAR = 3, MODE_TORQUE = 4 };
enum { STATE_INIT = 0, STATE_READY = 1, STATE_RUN = 2, STATE_FAULT = 3 };
enum { FAULT_NONE = 0, FAULT_OC = 1, FAULT_UV = 2, FAULT_ENC = 3, FAULT_COMM = 4 };

#endif
