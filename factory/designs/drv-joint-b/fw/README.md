# 关节驱动板 DRV-JOINT B 版 · 示例固件（第 100 轮；第 102 轮加电机控制与 CAN；第 107 轮输出端编码器；第 110 轮抱闸）

MCU（STM32G431）经 SPI1 读编码器接口芯片 WQ-ENCIF：每 1 ms 读计数和状态，算角度、转速、圈数；
Z 相锁存后给出绝对角度；芯片报错时记数并清除；芯片不响应时停在“芯片缺失”，每 100 ms 重试。
第 102 轮加：系统时钟 170 MHz；磁场定向控制（电流环 20 kHz、速度环 2 kHz、位置环 1 kHz，上电对零）；
CAN（1 Mbit/s，协议见 `src/can_proto.h`）收指令、发状态 / 心跳 / 报警；过流、欠压、编码器故障、通信超时四种保护。
第 107 轮加：输出端绝对值编码器（SSI，SPI3）开机取绝对角度、双编码器互检、受控停车。
第 110 轮加：抱闸（TIM4 CH1 = PB6，PWM 20 kHz 从母线给 24 V 线圈）——上电抱住；运动前先在原地稳住再松闸，60 ms 后执行指令；“停”和欠压：停住 → 抱闸 → 抱住后关输出；过流、编码器类故障关输出同时抱闸；通信超时保持、不抱闸。
第 114 轮加：抱闸线圈电流检测（R39 0.5 Ω → PB0）——断线、过流、抱不住都报故障 7；先在原地保持，测到线圈电流降下来（确实抱住）才关输出，抱不住就一直保持。
板上没有调试串口，结果放在内存里的遥测区 `tlm`（编码器）和 `mc`（电机控制）（调试器经 SWD 看；仿真里由 Renode 读内存）。

示例固件，仿真验证；芯片 WQ-ENCIF 未流片、B 版不投产。

## 文件

| 文件 | 内容 |
|---|---|
| `src/regs.h` | 用到的寄存器（地址按 RM0440《STM32G4 参考手册》） |
| `src/encif.c`、`encif.h` | WQ-ENCIF 驱动：40 位一帧，SPI 模式 0，PA4 软件片选，PB1 复位 |
| `src/main.c` | 编码器管理（Z 相、错误、芯片缺失重试）、状态机、CAN 指令、保护、CAN 发送；遥测区 tlm |
| `src/motor.c`、`motor.h` | FOC：20 kHz 电流环（Clarke/Park、PI、SVPWM）、速度环、位置环与梯形轨迹、对零；遥测区 mc |
| `src/can.c`、`can.h`、`can_proto.h` | FDCAN1 驱动与协议 |
| `src/ssi.c`、`ssi.h` | 输出端绝对值编码器 SSI（SPI3，第 107 轮） |
| `src/brake.c`、`brake.h` | 抱闸：TIM4 PWM、过励 50 ms 后保持平均 24 V（第 110 轮）；线圈电流检测（PB0 = ADC1_IN15）查断线、过流、抱不住（第 114 轮） |
| `src/clock.c` | HSI16 → PLL 170 MHz |
| `src/startup.c`、`stm32g431.ld` | 启动代码、链接脚本 |
| `renode/stm32g431.repl` | Renode 平台描述（Renode 自带的没有 STM32G4） |
| `renode/WqEncif.cs` | WQ-ENCIF 寄存器级模型 + 虚拟电机（Renode 外设，运行时编译） |
| `renode/WqDrive.cs` | TIM1 + 逆变桥 + 三相永磁同步电机 + 减速器 1:100 + 摆臂；ADC1 注入组；FDCAN1 与仿真 CAN 主站；SSI 编码器（第 107 轮）；TIM4 + 抱闸线圈与摩擦（第 110 轮） |
| `run.py` | 编码器六个场景（第 100 轮），写 `out/sim.json` |
| `run_motor.py` | 电机控制与 CAN 十七个场景（第 102、107、110、114 轮），写 `out/sim_motor.json` |
| `master/master.py` | 多关节 CAN 主站（第 115 轮）：两关节水平臂末端走直线，任一关节报警或掉线全部一起停；只用 Python 标准库 |
| `run_master.py` | 主站在环仿真：Renode 里两台驱动板（`make build/fw-node1.elf build/fw-node2.elf`）、每 10 ms 一拍，写 `out/sim_master.json` |

寄存器地址、偏移、位、中断号对照 ST 官方 CMSIS 头文件 `stm32g431xx.h`、CAN 消息 RAM 布局对照 HAL `stm32g4xx_hal_fdcan.c` 核对。
电机参数：力矩常数、额定力矩取第 88 轮示例电机，减速比 100 取零件库 Harmonic Drive CSF-17-100，其余是示例值（见 `run_motor.py` 的 PARAMS）。

## 自己跑

需要 `arm-none-eabi-gcc`（Ubuntu：`apt install gcc-arm-none-eabi`）和 Renode 1.15（https://github.com/renode/renode/releases ，Linux 便携版解压即可）。

```
make                          # 编译 build/fw.elf
python3 run.py --renode <Renode 目录>/renode
python3 run_motor.py --renode <Renode 目录>/renode
```

只想看固件在仿真器里跑：照 `run.py` 里 `resc()` 生成的脚本，在 Renode 里 `include` 即可，
然后 `sysbus ReadBytes <tlm 地址> 64` 看遥测区（地址用 `arm-none-eabi-nm build/fw.elf | grep tlm` 查）。
