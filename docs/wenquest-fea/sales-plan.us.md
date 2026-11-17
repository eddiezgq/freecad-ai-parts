# 问渠有限元 · 美国与国际销售方案（第一版，交项目负责人定）

2026-11-17。销售主体：项目负责人在美国（佛罗里达）的公司。产品英文名 WenQuest FEA。ADR-0096 第 6 步。

## 一句话

在美国卖“FreeCAD 里的、带核查和计算书的有限元”。免费版拉用户，专业版 **$990 / 年 / 单机**，
价格不到 Fusion + 仿真扩展（$2,145 / 年）的一半、SOLIDWORKS Premium（$4,716 / 年）的约五分之一。
卖点不是“便宜的 Ansys”，而是：一句话起草、每次都核查、能直接交给审核人的报告。

## 卖给谁

| 优先级 | 客户 | 为什么买 | 在哪找 |
| --- | --- | --- | --- |
| 1 | 用 FreeCAD 的机械工程师、小型机器人与自动化公司、硬件创业公司 | 已经在用 FreeCAD，缺一个可信、省事的强度校核和计算书 | FreeCAD 论坛与社区、Reddit（r/FreeCAD、r/robotics、r/MechanicalEngineering）、YouTube |
| 2 | 小型工程咨询公司、独立工程师（含 PE） | 要给客户交计算书，审核清单和可追溯信息省时间 | LinkedIn、ASME 地方分会、行业展会（Automate、MD&M） |
| 3 | 大学与社区学院 | 教学用免费软件，学生毕业后带进公司 | 问渠在美国的培训课程、教授邮件 |

## 价格（建议就按这个定）

| 产品 | 价格 | 说明 |
| --- | --- | --- |
| Free | $0 | 单个实体零件的静力、模态、屈曲，带核查；不限时间 |
| Pro · 年订阅（单机） | **$990 / year** | 绑定一台电脑；含升级与邮件支持（2 个工作日内答复） |
| Pro · 月订阅 | **$99 / month** | 给短期项目用；随时取消 |
| Pro · 多台 | 5 台起 **10% off**，10 台起 **20% off** | 每台一个单机授权（第一版没有浮动席位） |
| Education | 免费 | 教学用，签教学授权；不得用于商业项目 |
| Founding customer | 首年 **$590** | 前 30 家客户，换取使用反馈和一个可公开的案例 |

定价依据：

- Autodesk Fusion $680 / 年 [1] + Fusion Simulation Extension $1,465 / 年 [2] = $2,145 / 年；SOLIDWORKS Premium（含仿真）美国订阅
  $4,716 / 年 [3]；SimScale 的付费方案不公开报价，免费版限 10 次仿真 [4]。
- $990 是小公司信用卡能直接刷、不用走采购审批的价位；年付为主，月付比年付贵 20%，引导年付。
- AI 调用由用户自己的 Claude 密钥付给 Anthropic，不进我们的价格。

## 怎么卖

1. **官网（问渠英文官网 “Enterprise solutions” 下）下载免费版**，用 Stripe 收款，付款后按激活码自动或人工签发授权文件（第一阶段人工，24 小时内）。
2. **内容**：YouTube 每周一条 3 分钟视频（“One sentence to a stress report”），用三个入门例子；在 FreeCAD 论坛按论坛规矩发版本公告与技术帖，不刷广告。
3. **社区信任**：验证手册公开放官网（42 道标准题，含 NAFEMS），这是工程师最认的东西。
4. **直销**：项目负责人用 LinkedIn 联系机器人和自动化小公司的工程负责人，约 20 分钟线上演示，用客户自己的零件。
5. **教育**：通过问渠在美国的在线培训课程推教育版。

## 合同、收款、合规

- 由美国公司签约、收款（Stripe；企业客户可用 PO / 发票）。
- 出口管制：软件含标准加密通信（HTTPS 调 AI），发版前按 ADR-0096 决策 4 核一次出口分类；收款时按美国受限名单筛查客户，不卖给名单上的单位和受禁运地区。
- 销售税：数字产品在部分州要收销售税，用 Stripe Tax 按州自动计算。
- 隐私：模型和结果只在用户电脑上；AI 只收到那句话和零件特征清单。写进隐私说明和许可协议。

## 许可协议要点（EULA；正式文本发版前请律师过一遍）

1. **Grant**：单机授权限一台电脑（每年可申请迁移一次）；教育版限教学。
2. **Term**：订阅到期回到 Free，已出的报告与文件照常可用。
3. **Restrictions**：不得转售、出租、分享授权文件，不得绕过授权校验。
4. **Engineering responsibility**：结果须由有资质的工程师审核后使用；软件不替代工程判断。
5. **Warranty / liability**：按“现状”提供；责任上限为客户过去 12 个月实际支付的费用；不承担间接损失。
6. **Data**：我们不收集模型和结果；AI 调用由用户用自己的密钥直接发给模型服务商，适用其条款。
7. **Open source**：FreeCAD（LGPL）、CalculiX 与 Gmsh（GPL）按各自许可证随附，本协议不限制用户对它们的权利。
8. **Refund**：购买 30 天内全额退款。
9. **Governing law**：佛罗里达州法律；争议在佛罗里达州法院解决。
10. **Export**：用户承诺遵守美国出口管制法规。

## 第一年目标（建议）

| 指标 | 目标 |
| --- | --- |
| 免费版下载 | 3,000 |
| 付费客户 | 50 个（含首批 30 个） |
| 收入 | 约 $35,000 |
| 公开案例 | 5 个 |

## 要项目负责人定的

- 价格表（建议照用）；
- 首批客户价（建议给）；
- 收款用 Stripe（建议）；第一阶段人工签发授权文件（建议，量大了再做自动签发）。

## 出处

1. activepieces.com，《Autodesk Fusion 360 Pricing 2026》：https://www.activepieces.com/blog/autodesk-fusion-360-pricing-2026-what-it-costs-a-month
2. Novedge，Fusion Simulation Extension 年订阅报价（2026-11-17 查）：https://novedge.com/collections/autodesk/products/buy-fusion-simulation-extension-subscription
3. ohmycad.com，《How much will SOLIDWORKS cost in 2026?》，2026-10 更新：https://ohmycad.com/en/official-price-list-3dexperience-solidworks/
4. SimScale 官网价格页（2026-11-17 查）：https://www.simscale.com/product/pricing/
