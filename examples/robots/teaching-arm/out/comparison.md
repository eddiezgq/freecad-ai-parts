# 案例 A：和公开资料的对照

> 这些公开数字只作参照：不进零件库、不参与校核，我们的方案也不以它们为依据（ADR-0115 第 5 节）。
> 参照数取各厂商自己的规格页，查阅日期 2026-11-24；我们的数全部取 `out/` 里的结果文件。

## 对照表

| 机器人 | 自由度 | 负载 kg | 臂展 mm | 自重 kg | 负载自重比 | 重复定位 mm | 主臂关节最高速度 rpm |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **本案例 A（我们的方案）** | 5 | 0.5 | 350 | 1.983 | 0.25 | ±0.95 | 12 |
| ROBOTIS OpenMANIPULATOR-X（RM-X52-TNM） | 4 | 0.5 | 380 | 0.7 | 0.71 | ±0.2 | 46 |
| DOBOT（越疆） Magician | 4 | 0.5 | 320 | 3.4 | 0.15 | ±0.2 | 53.3 |
| Niryo Ned2 | 6 | 0.3 | 490 | 7 | 0.04 | ±0.5 | 5–7.5 |
| UFACTORY Lite 6 | 6 | 0.6 | 440 | 8 | 0.07 | ±0.5 | 30 |

我们的数出自：自由度、负载、臂展取 concept-result.json · conditions（臂展已由初筛验证能到）；自重取 cad/cad-result.json · mass_kg；重复定位取 build-result.json · repeatability · worst_mm；关节速度取 verify-result.json · S3（带载最紧一点）。

## 口径不同的地方（看表之前先看这里）

- **自重**：我们的自重是三维装配里 5 个模组加 15 个自制件，不含夹爪、控制器、电源、线缆和桌面夹具；各厂商的自重口径见表下出处里的原话（例如 Magician 写整机净重，Lite 6 注明只算机械臂），含不含控制器各不相同。负载自重比因此只能看量级。
- **重复定位精度**：我们的 ±0.95 mm 是按编码器分辨率逐关节累加的最坏值（代码算的，偏保守），只对同向趋近成立；厂商给的是实测统计值（Niryo 注明按 ISO 9283）。两者不是同一种量，不能直接比高低。
- **关节速度**：我们的 12 rpm 是带满载、在检验动作最紧的一点上模组还能达到的转速（需求 10 rpm）；厂商给的是各自口径的最高值：Magician 注明带 250 g，Ned2 是名义值，其余没写带多少负载。
- **自由度**：OpenMANIPULATOR-X 另有 1 个夹爪自由度，表里只计机械臂。

## 从对照里看出的事

- 我们的自重里自制支架和管件占 58%（BOM：自制件 1.158 kg，外购模组 0.825 kg）。支架有限元里对屈服的安全系数最低 10.6、对弯曲疲劳最低 3.7，要求 1.2（fea-result.json），支架有减薄的余地；减薄后负载自重比会提高。减薄要另定方案。
- 同厂的 OpenMANIPULATOR-X 用小一号的模组、4 个自由度，自重 0.7 kg、负载同为 0.5 kg；我们 5 个自由度、臂展 350 mm，自重 1.983 kg。模组选型由我们的载荷与校核决定，不以它为依据。
- 上表公开教学臂的重复定位精度在 ±0.2～±0.5 mm，我们需求是 ±1 mm、最坏估算 ±0.95 mm；反向趋近时的回差（报告第 6 节）这几家的规格页都没有给，无从对照。

## 节拍与续航

- 节拍：这几家的规格页都没有给统一工况下的节拍。我们的检验动作是各关节同时转 90°、用时 2 s（build-result.json · assumptions），只用来算载荷，不是节拍指标。
- 续航：桌面臂接市电，不适用。

## 出处

- ROBOTIS OpenMANIPULATOR-X（RM-X52-TNM）（同一厂商、同一系列关节模组（DYNAMIXEL XM430-W350-T，比我们的 XM540 小一号））：<https://emanual.robotis.com/docs/en/platform/openmanipulator_x/specification/>。原话：“5 (4 DOF + 1 DOF Gripper)”；“Payload 500 (g)”；“Reach 380 (14.9) mm (in)”；“Weight 0.70 (1.54) kg (lb)”；“Repeatability < 0.2 mm”；“Speed (Joint) 46 RPM”
- DOBOT（越疆） Magician（4 轴桌面教学臂，负载与我们相同）：<https://dobot-robots.com/products/education/magician.html>。原话：“Number of Axis 4”；“Payload 500 g”；“Max. Reach 320 mm”；“Net Weight 3.4 KG”；“Repeatability ±0.2 mm”；“Max Speed (250 g workload): Joint 1 base 320° / s, Joint 2 rear arm 320° / s, Joint 3 forearm 320° / s”
- Niryo Ned2（6 轴教学臂，厂商按 ISO 9283 给重复定位精度）：<https://niryo.com/wp-content/uploads/2026/06/10001874-4_TECHNICAL_SPECIFICATIONS_NED2.pdf>。原话：“6 rotating joints”；“Payload 300 g / 0,6 lbs (z = 20mm TCP)”；“Reach 490 mm / 19,29 In”；“Weight 7 kg / 15,4 lbs”；“Repeatability +/- 0.5 mm (ISO 9283)”；“Joint 1 : 45°/s, Joint 2 : 30°/s, Joint 3 : 45°/s”
- UFACTORY Lite 6（6 轴桌面协作臂，负载与我们相近）：<https://docs.lite6.ufactory.cc/9.technical_specifications.html>、<https://www.ufactory.cc/lite-6-collaborative-robot>。原话：“6”；“Maximum Payload 600g”；“Reach 440 mm”；“Weight (robotic only) 8KG”；“Repeatability ±0.5mm”；“Max joint speed 180°/s”
