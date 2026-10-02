# 端到端演示结果

## 需求

原话：六轴机械臂第 2 关节：输出连续扭矩 25 N·m、峰值 50 N·m，输出转速 30 rpm，220 V 单相供电，EtherCAT 总线

## 方案

- `motor`：test.servo_motor.test-vendor.m200
- `reducer`：test.reducer.test-vendor.r25-100
- `drive`：test.drive.test-vendor.d200
- `sleeve`：test.adapter.test-vendor.sleeve-11-19
- `plate`：test.adapter.test-vendor.plate-70-90

| 实例 | 厂商与型号 | 数据来源 | 复核 |
| --- | --- | --- | --- |
| `motor` | Test Vendor M200 | 虚构测试组件（ADR-0015） | — |
| `reducer` | Test Vendor R25-100 | 虚构测试组件（ADR-0015） | — |
| `drive` | Test Vendor D200 | 虚构测试组件（ADR-0015） | — |
| `sleeve` | Test Vendor SL-11-19 | 虚构测试组件（ADR-0015） | — |
| `plate` | Test Vendor PL-70-90 | 虚构测试组件（ADR-0015） | — |

## 布局与干涉

- 第 1 轮：有干涉；干涉：drive–motor 2850.99 mm³、drive–plate 40000 mm³、drive–reducer 255075 mm³、drive–sleeve 4712.39 mm³
  - 需有通孔：plate（motor.shaft 穿过）
- 第 2 轮：通过；干涉：无
  - 需有通孔：plate（motor.shaft 穿过）

注意：motor.shaft ↔ sleeve.inner：插入深度未知（轴无 usable_length_mm、孔无 depth_mm），孔口按轴端放置，请用 offset_mm 指定

| 实例 | 位置 mm | 转轴 | 转角 ° |
| --- | --- | --- | --- |
| `drive` | [90.0, 0.0, 0.0] | [0.0, 0.0, 1.0] | 0.0 |
| `motor` | [0.0, 0.0, 0.0] | [0.0, 0.0, 1.0] | 0.0 |
| `plate` | [0.0, 0.0, 0.0] | [0.0, 0.0, 1.0] | 0.0 |
| `reducer` | [0.0, 0.0, 30.0] | [0.0, 0.0, 1.0] | 0.0 |
| `sleeve` | [0.0, 0.0, 30.0] | [0.0, 0.0, 1.0] | 0.0 |

## 按布局复核

可用：全部适用项通过。
通过：C1、C2、C3、C4、C5、C6、C7、C9、C10
不适用：C8 惯量比（需求未给负载惯量）
不适用：C11 轴承与包络（系统中没有轴承，需求也未给包络外径限值）

## 文件

- `requirement.json`
- `bom.csv`
- `bom.json`
- `system.json`
- `candidate-1.urdf`
- `layout-iso.png`
