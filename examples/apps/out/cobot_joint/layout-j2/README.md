# 端到端演示结果

## 需求

原话：动力学结果：关节 j2 峰值 92.5 N·m、均方根 70.0 N·m、最高 20.0 rpm

## 方案

- `motor`：servo_motor.yaskawa-electric-corporation.sgm7j-04a-6
- `reducer`：reducer.harmonic-drive-llc.csf-32-100-2uh
- `drive`：drive.yaskawa-america-inc.sgd7s-2r8a

| 实例 | 厂商与型号 | 数据来源 | 复核 |
| --- | --- | --- | --- |
| `motor` | Yaskawa Electric Corporation SGM7J-04A（轴端代码 6） | `src-yaskawa-sgm7-rotary-manual` | AI 复核（两次独立抽取一致） |
| `reducer` | Harmonic Drive LLC CSF-32-100-2UH | `src-hd-csg-csf-gear-units` | AI 复核（两次独立抽取一致） |
| `drive` | Yaskawa America, Inc. SGD7S-2R8A | `src-yaskawa-sgd7s-ethercat-manual` | AI 复核（两次独立抽取一致） |

## 布局与干涉

- 第 1 轮：有干涉；干涉：drive–motor 4618.14 mm³、drive–reducer 338818 mm³
- 第 2 轮：通过；干涉：无


| 实例 | 位置 mm | 转轴 | 转角 ° |
| --- | --- | --- | --- |
| `drive` | [111.5, 0.0, 0.0] | [0.0, 0.0, 1.0] | 0.0 |
| `motor` | [0.0, 0.0, 0.0] | [0.0, 0.0, 1.0] | 0.0 |
| `reducer` | [0.0, 0.0, 0.0] | [0.0, 0.0, 1.0] | 0.0 |

## 按布局复核

待确认：有数据缺失，不能判定为可用。
- C3 法兰配合：待确认（数据缺失）
  - 缺少分度圆直径（端口：motor.mount_flange、reducer.motor_flange）
  - 缺少孔数（端口：motor.mount_flange、reducer.motor_flange）
  - 缺少孔的形式（通孔 / 螺纹孔）（端口：motor.mount_flange、reducer.motor_flange）
- C8 惯量比：待确认（数据缺失）
  - 惯量比：缺少减速器输入侧惯量（端口：motor.shaft、reducer.input_bore）
通过：C1、C2、C4、C5、C6、C7、C9、C10
不适用：C11 轴承与包络（系统中没有轴承，需求也未给包络外径限值）

## 文件

- `requirement.json`
- `bom.csv`
- `bom.json`
- `system.json`
- `candidate-1.urdf`
- `layout-iso.png`
