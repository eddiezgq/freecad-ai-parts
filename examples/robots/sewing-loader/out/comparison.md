# 案例 B：和公开资料的对照

> 这些公开数字只作参照：不进零件库、不参与校核，我们的方案也不以它们为依据（ADR-0115 第 5 节）。
> 参照数取各家公开页面，查阅日期 2026-11-26；我们的数全部取 `out/` 里的结果文件。

## 对照表

| 设备 | 形式 | 节拍 s/片 | 机器人负载 kg | 工作范围 mm | 抓手 |
| --- | --- | --- | --- | --- | --- |
| **本案例 B（我们的方案）** | 台面上的 X–Z 两轴龙门（费斯托直线模组） | 2.8（要求 ≤ 3） | —（按单片 0.1 kg 算） | X 行程 1600，门架占地 x = -400～1900 | 真空吸盘 SPF 15 |
| Robotextile 裁片取放单元（标准配置 KUKA SCARA） | SCARA 机器人 + 布料专用抓手 | 2–4 | 5 | 1600（直径） | 气流、黏附、橡胶辊、手指触觉四种原理 |
| Grabit Stackit（鞋面裁片叠放） | 改装的东芝 THL1000 SCARA + 电吸附抓手 | ≤ 1.5 | 10 | 未公开 | 电吸附（静电） |
| Kong、Liu、Kong（论文） 真空吸盘取单层机织布片（试验） | 试验台（真空吸盘抓手） | 未公开 | 未公开 | 未公开 | 真空吸盘（Ø2 mm，6–12 个），负压 −55 kPa；多种机织面料、5–10 层一叠，各组都判通过 |

我们的数出自：节拍取 build-result.json · cycle_time；X 行程取 build-result.json · picks；门架占地取 cad-result.json · cad.layout.col_x_mm；抓手取 build-result.json · gripper。

## 口径不同的地方（看表之前先看这里）

- **节拍**：我们的 2.8 s 是一圈 6 段直线动作加两处停留（取—升—移—降—放—回），取放距离 1500 mm，不含吸盘建立真空与破真空的时间、不含停稳时间；Robotextile 写“视布置与条件而定”，没给取放距离；Grabit 的数是我们按“一分钟 40 片”折算的平均值，鞋面裁片、取放距离没给。
- **负载**：参照里的负载是机器人本身能带的最大质量，不是一片布的质量；我们的模组按单片 100 g 加真实运动质量选的。
- **形式**：两家设备都是 SCARA（转动关节）；我们由 AI 提、代码初筛选了龙门（SCARA 构型在关节行程内够不着取放点，见报告第 1 节）。

## 从对照里看出的事

- 专做布料取放的 Robotextile 给每层 2–4 s，我们 2.8 s 落在这个范围里；要不要留出吸放与停稳的余量，要实物试后定。
- 抓手：公开试验（Kong 等）用多个 Ø2 mm 小吸盘、−55 kPa 从一叠机织布里只取最上一片，各组判通过，但没给成功率；我们按 1 个 SPF 15 核保持力，对布料的适用性与一次只取一片仍是待确认（报告第 6 节）。
- 本机质量：外购件 17.22 kg + 自制件 29.27 kg（BOM），参照都没公开整机质量，无从对照。

## 出处

- Robotextile 裁片取放单元（标准配置 KUKA SCARA）（专做布料逐层取放的设备厂，规格页直接给每层的节拍）：<https://robotextile.com/en/technology/>。原话：“cycle times of 2 to 4 seconds per fabric layer are possible”（厂商写“视布置与条件而定”）；“5 kg payload”（机器人本身的负载，不是裁片质量）；“working diameter of 1600mm diameter”（工作范围直径）；“by air flow / by adhesion / by rubber roller / by finger haptics”（规格页上的四个列表项）
- Grabit Stackit（鞋面裁片叠放）（电吸附抓手逐片取放鞋面裁片，公开报道给了片数与时间）：<https://www.themanufacturer.com/articles/robotics-start-up-aims-to-revolutionise-material-handling/>。原话：“handle up to 40 material pieces in under a minute”（原话是页面摘要；正文写一双鞋面“up to 40 pieces of material”、机器“less than one”分钟做完。我们按原话折算：60 s ÷ 40 片 = 平均不到 1.5 s/片；出处是行业媒体 The Manufacturer 2018-02-08 的报道，不是厂商规格页；鞋面裁片，不是缝纫车间的衣片）；“a maximum payload of 10kg”（机器人本身的负载）；“electroadhesive gripper”
- Kong、Liu、Kong（论文） 真空吸盘取单层机织布片（试验）（公开试验：真空吸盘从一叠机织布片里只取最上面一片）：<https://arxiv.org/abs/2408.09504>。原话：“The maximum supply of negative is dropped from -92kPa to -55kPa”（论文没给成功率、试验次数与节拍）
