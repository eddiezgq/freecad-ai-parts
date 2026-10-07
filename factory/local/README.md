# 问渠数字工厂 · 本地版

在企业自己的电脑或内网服务器上运行整座数字工厂（ADR-0058）：数据总线、历史库、工厂枢纽与工作台网页、仿真车间、
虚拟 PLC、Node-RED 桥接、模拟 ERPNext。数据只在本机的 Docker 卷里。

## 需要

- Docker：Windows / macOS 装 Docker Desktop 并启动；Linux 装 Docker Engine 与 compose 插件
- 第一次启动要下载镜像、构建（含 CalculiX、OpenFOAM、网页），约 10–20 分钟；之后几十秒
- 内存建议 8 GB 以上

## 启动与停止

Windows（PowerShell，在仓库根目录）：

```powershell
.\factory\local\start.ps1          # 演示：仿真车间在跑，看板有数据，用模拟 ERPNext
.\factory\local\start.ps1 -Prod    # 生产模式：只显示接入的真实设备
.\factory\local\stop.ps1           # 停止（数据保留）；-Reset 连数据一起删
```

Linux / macOS：

```bash
factory/local/start.sh             # 同上；--prod 生产模式；--erpnext http://你的ERPNext:8080 接真 ERPNext
factory/local/stop.sh              # 停止；--reset 连数据一起删
```

启动后打开 <http://localhost:8100>，左上角显示“本地版”。第一次启动会生成 `factory/digital/.env`（登录签名密钥随机生成）；
AI 工厂助手的密钥（可选）填在里面，不填就用规则回答。

| 地址 | 内容 |
| --- | --- |
| <http://localhost:8100> | 工作台（看板、订单与计划、设计与工艺、车间、质量、经营、3D 车间、仿真与分析、数字孪生） |
| <http://localhost:8091> | 模拟 ERPNext（演示用；接真 ERPNext 见上） |
| <http://localhost:1880> | Node-RED 数据流 |
| `localhost:1883` | 数据总线（MQTT），设备与 FreeCAD 发布都走这里 |

## 与 FreeCAD 连起来

FreeCAD 的 AI Parts 工作台：菜单“发布到工厂”，把当前方案（BOM、需求、校验结论、布局 STEP）发到本地工厂；
工作台左侧“CAD 方案”页列出各方案、BOM（零件来自公共库或企业库，带资料出处）与版本记录。数据经数据总线以
`cad.release` 消息发出（主题 `wq/gearbox/design/cad-<编号>/release`）。

**选型零件库**：工厂工作台左侧“选型零件库”页列出与 FreeCAD 同一份零件库——仓库的 `data/library`（公共库）
叠加企业库（同一零件以企业库为准）。企业库文件夹取环境变量 `FAP_ENTERPRISE_LIBRARY`，没有就取 FreeCAD 设置里选的
（`~/.freecad-ai-parts/settings.json`），启动时挂进工厂，只读。

**孪生记录给 FreeCAD**：`http://localhost:8100/api/twin/units/<序列号>/records.csv?instance=<布局里的减速器实例名>`
导出这台设备每天的运行小时、输出扭矩、输入转速，作为 FreeCAD“数字孪生”里的运行记录 CSV 打开即可算寿命消耗。

## 计算

工作台的“仿真与分析”“运动与动力分析”“流体分析”“数控编程”“设计优化”由计算服务 `cae` 算（本地版一起启动）。
计算内核与 FreeCAD 里的分析模块是同一份代码（本仓库 `analysis/`，ADR-0060），两边对同一题给出同样结果。

## 说明

- 演示工厂“问渠减速器厂”和产品 WQR-105 的数据是虚构的演示数据
- 接真 ERPNext：在 ERPNext 里生成 API 密钥，填进 `factory/digital/.env` 的 `WQ_ERP_API_KEY`、`WQ_ERP_API_SECRET`，用 `--erpnext` 启动
- 服务器部署（域名、HTTPS、备份）的脚本在 `factory/deploy/`，本地版不用
