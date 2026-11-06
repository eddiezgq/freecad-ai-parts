# 关节驱动板 DRV-JOINT B 版 · 示例固件（第 100 轮）

MCU（STM32G431）经 SPI1 读编码器接口芯片 WQ-ENCIF：每 1 ms 读计数和状态，算角度、转速、圈数；
Z 相锁存后给出绝对角度；芯片报错时记数并清除；芯片不响应时停在“芯片缺失”，每 100 ms 重试。
板上没有调试串口，结果放在内存里的遥测区 `tlm`（调试器经 SWD 看；仿真里由 Renode 读内存）。

示例固件，仿真验证；芯片 WQ-ENCIF 未流片、B 版不投产。

## 文件

| 文件 | 内容 |
|---|---|
| `src/regs.h` | 用到的寄存器（地址按 RM0440《STM32G4 参考手册》） |
| `src/encif.c`、`encif.h` | WQ-ENCIF 驱动：40 位一帧，SPI 模式 0，PA4 软件片选，PB1 复位 |
| `src/main.c` | 1 kHz 节拍：读数、算转速、Z 相、错误、芯片缺失重试；遥测区 |
| `src/startup.c`、`stm32g431.ld` | 启动代码、链接脚本 |
| `renode/stm32g431.repl` | Renode 平台描述（Renode 自带的没有 STM32G4） |
| `renode/WqEncif.cs` | WQ-ENCIF 寄存器级模型 + 虚拟电机（Renode 外设，运行时编译） |
| `run.py` | 六个场景：起仿真、每 10 ms 读遥测区和真值、逐项核对，写 `out/sim.json` |

## 自己跑

需要 `arm-none-eabi-gcc`（Ubuntu：`apt install gcc-arm-none-eabi`）和 Renode 1.15（https://github.com/renode/renode/releases ，Linux 便携版解压即可）。

```
make                          # 编译 build/fw.elf
python3 run.py --renode <Renode 目录>/renode
```

只想看固件在仿真器里跑：照 `run.py` 里 `resc()` 生成的脚本，在 Renode 里 `include` 即可，
然后 `sysbus ReadBytes <tlm 地址> 64` 看遥测区（地址用 `arm-none-eabi-nm build/fw.elf | grep tlm` 查）。
