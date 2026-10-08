# 协作机器人肩、肘、腕关节（UR5e 一类）

## 依据

- [Universal Robots UR5e 数据表](https://www.universal-robots.com/manuals/latest/en/datasheets/ur5e/)：负载 5 kg、臂展 850 mm、自重 20.7 kg、各关节最高 ±180°/s
- [UR 论坛：UR5e Plant Model for MPC（引 ROS-Industrial universal_robot 的 DH 与质量）](https://forum.universal-robots.com/t/ur5e-plant-model-for-mpc-matlab/19067)：大臂 a2 = 425 mm、小臂 a3 = 392.25 mm；质量 3.70 / 8.393 / 2.275 / 1.219 / 1.219 / 0.1879 kg（外部测量，可能与实物不同）
- [Universal Robots：DH Parameters for calculations of kinematics and dynamics（UR5e 表）](https://www.universal-robots.com/articles/ur/application-installation/dh-parameters-for-calculations-of-kinematics-and-dynamics/)：腕部 d5 = 0.0997 m、d6 = 0.0996 m；第 5、6 节质量 1.3、0.365 kg（腕关节 j4 用）
- [问渠《机械设计》第 33.10 节案例：协作机器人肩关节空心轴 RJ-201](https://github.com/eddiezgq/freecad-ai-parts/blob/main/factory/digital/hub/case_parts.py)：空心轴各段直径、长度与 Ø30 贯通内孔

## 假设（不是零件库数据，按需改）

- 肩关节最不利工况：大臂、小臂水平伸直（重力矩最大），满载 5 kg + 腕部三个模组 2.626 kg 集中在小臂末端
- 运动：肩、肘各转 90°，用时 1.0 s，加减速各占 25%（最高 120°/s，低于数据表的 180°/s）
- 供电按控制柜 200 V 三相交流、EtherCAT 总线（零件库里的伺服是 200 V 交流；真实协作臂多用 48 V 直流关节）
- 工作制：每天 16 小时，按动力学这一段动作重复（数字孪生的运行记录是仿真工况，不是现场数据）
- 腕关节 j4（wrist 1）最不利工况：d5、d6 沿同一方向水平伸出（力臂取上界 199.3 mm），第 5、6 节按均布杆、负载 5 kg 在末端；转 90° 用时 1.0 s
- 表面系数 β = 0.92（磨削）、尺寸系数 ε = 0.85：取问渠数字工厂实验 8 的示例值，实际按教材图表查
- 关节壳体自然对流散热系数 8 W/(m²·K)（自然对流常见范围 5–10），环境 25 °C

## 各步结果

| 步骤 | 结论 | 摘要 |
| --- | --- | --- |
| 动力学 | 完成 | 肩 j2 峰值 92.5 N·m、均方根 70.0 N·m、最高 20.0 rpm；肘 j3 峰值 42.4 N·m；水平伸直重力矩 92.5 N·m（手算 Σm·g·r 92.5） |
| 动力学：腕关节 j4 | 完成 | 峰值 11.4 N·m、均方根 7.7 N·m、最高 20.0 rpm；水平伸出重力矩 11.4 N·m（手算 11.4） |
| 选型 j2 | 待确认 | 需求 连续 70.0 / 峰值 92.5 N·m、20.0 rpm → SGM7J-04A-6、CSF-32-100-2UH、SGD7S-2R8A；总体 unknown（C3 unknown：缺少分度圆直径；C8 unknown：惯量比：缺少减速器输入侧惯量）；共 1 个候选 |
| 选型 j3 | 待确认 | 需求 连续 34.2 / 峰值 42.4 N·m、20.0 rpm → SGM7J-02A-6、CSF-25-100-2UH、SGD7S-1R6A；总体 unknown（C3 unknown：缺少分度圆直径；C8 unknown：惯量比：缺少减速器输入侧惯量）；共 4 个候选，外购件最轻的是 SGM7J-02A-6、CSF-25-100-2UH、SGD7S-1R6A（3.2 kg） |
| 选型 j4 | 待确认 | 需求 连续 7.7 / 峰值 11.4 N·m、20.0 rpm → SGM7J-02A-6、CSF-25-100-2UH、SGD7S-1R6A；总体 unknown（C3 unknown：缺少分度圆直径；C8 unknown：惯量比：缺少减速器输入侧惯量）；共 14 个候选，外购件最轻的是 SGM7J-A5A-6、CSF-17-100-2UH、SGD7S-1R6A（1.88 kg） |
| 布局与干涉 | 完成 | FreeCAD 按端口摆放、检查干涉并按布局复核：总体 unknown（C3 unknown：缺少分度圆直径；C8 unknown：惯量比：缺少减速器输入侧惯量）；截图 有（layout-j2/） |
| BOM | 完成 | 肩关节外购件 3 种：Yaskawa Electric Corporation SGM7J-04A（轴端代码 6）、Harmonic Drive LLC CSF-32-100-2UH、Yaskawa America, Inc. SGD7S-2R8A；外购件总质量 5.4 kg |
| 有限元：空心轴 RJ-201 | 完成 | 峰值扭矩 92.5 N·m：最大 Von Mises 27.7 MPa，安全系数 12.83；花键段（按小径 Ø42.75、内孔 Ø30）手算 τ = T·r/Iₚ = 8.0 MPa（等效 √3·τ = 13.8；有限元最大值在台阶与加载面附近，含应力集中） |
| 疲劳：空心轴 RJ-201 | 完成 | 按动力学的扭矩记录（每个动作 11 个循环）：远超设计寿命（应力远低于疲劳极限，按 Haibach 外推 9.4e+26 小时） |
| 热分析：关节壳体 J2-HSG | 完成 | 平均输出功率 81.1 W，效率按曲线取（ADR-0047）：3500 rpm 曲线，环境温度 25 °C，取 0.69，减速器损耗约 36.4 W（电机损耗零件库无数据，未计）；按连续往复运动估算（偏保守），壳体最高 89.7 °C——温升偏高，实际要有停顿或加散热 |
| 拓扑优化：大臂侧板 | 完成 | 悬臂构形、材料用量 45%：柔度 933 → 154；板面积 29369 mm²；拉伸 6 mm 板件做有限元（末端 49 N）：最大应力 1.5 MPa、最大位移 0.018 mm |
| 数控编程 | 完成 | RJ-201 车外圆两次装夹 2 个程序、约 4.1 min，检查 ok（Ø30 内孔另钻镗，本模块不编）；J2-HSG 外轮廓与 4 个螺纹底孔约 5.7 min，检查 ok；程序存 O*.nc（示例机床虚构） |
| 数字孪生：减速器 | 待确认 | Harmonic Drive LLC CSF-32-100-2UH：缺样本参数：rated_life_h、rated_input_speed_rpm（可用“补数据”或“导入规格书”补）——零件库的谐波减速器还没有额定寿命，补录后即可算剩余寿命 |
| 流体分析 | 不适用 | 关节是封闭结构、靠壳体自然散热，没有需要算的流场（流体用在平缝机控制箱散热器） |
| 发布到工厂 | 完成 | 方案 COBOT-J2 第 1 版，带自制件 RJ-201、J2-HSG 与总装工艺 |
