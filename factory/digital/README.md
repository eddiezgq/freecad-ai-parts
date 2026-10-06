# 问渠数字工厂 · 第 1 轮（WenQuest Digital Factory）

一个平台，两种用途：**教学模式**下学生扮演计划员、工艺员、操作工、质检员、厂长，完成真实的生产任务；**生产模式**下它就是一家工厂的日常工作台。所有软件、设备和 AI 只经**统一数据总线**交换数据，全部消息存入历史库，首页看板和 AI 都从历史库取数。

第 1 轮做通“一张订单到一根轴”的最小闭环：接单与算料 → 设计发布 → 下达车间 → 仿真机床加工 → 三坐标检验 → 完工入库 → 成本分析。依据：项目文档《虚拟工厂/实施细则/第1轮》。

## 一、组成

| 目录 / 服务 | 作用 | 端口 |
| --- | --- | --- |
| `mosquitto/` → `bus` | 统一数据总线（MQTT）；浏览器用 WebSocket 连 | 1883、9001 |
| `db` | 历史库（PostgreSQL）：表 `bus_message` 存总线上每一条消息 | — |
| `hub/` → `hub` | 枢纽服务：历史库写入、看板指标、AI 工厂助手、MES、教学评分、工作台网页 | **8100** |
| `sim/` → `sim` | 仿真车间：12 台设备、2 台 AGV、三坐标；教学情景“实验 7” | — |
| `bridge/` → `bridge` | Node-RED 桥接：ERPNext ↔ 总线 | 1880 |
| `web/` | 工作台网页源码（Vue 3），打包后由 hub 提供 | — |
| `freecad/` | FreeCAD 发布宏、键槽 CAM、零件图 | — |
| `wqbus/` | 总线规范的 Python 实现（主题、信封、校验、车间布置） | — |
| `mock_erpnext/` | 模拟 ERPNext，给自动测试和“先试一下”用 | 8091 |
| `tests/` | 自动测试，含完整闭环测试 | — |

ERPNext 沿用上一级目录 `factory` 里的那套（端口 8090，数据由 `seed.py` 导入）。

## 二、在 Windows 上安装（约 30 分钟）

前提：已按 `factory/README.md` 装好 Docker Desktop，ERPNext 在 `http://localhost:8090` 能打开，并运行过 `py seed.py --opening-stock`。

1. **给桥接一把 ERPNext 钥匙**：用 Administrator 登录 ERPNext → 右上角头像 → “我的设置” → 往下找“API 访问” → “生成密钥”。页面会弹出 API Secret（只显示一次），连同上方的 API Key 一起记下。
2. **配置**：在 PowerShell 里
   ```powershell
   cd D:\code\wenquest\factory\digital
   copy .env.example .env
   notepad .env
   ```
   填 `WQ_ERP_API_KEY`、`WQ_ERP_API_SECRET`；有 Claude 的 API 密钥就填 `WQ_CLAUDE_KEY`（不填也能用，AI 改用规则回答）；`WQ_SECRET` 随便改一串字母数字。
3. **启动**：
   ```powershell
   docker compose up -d --build
   ```
   第一次要下载镜像并打包网页，约 5–10 分钟。之后每次启动十几秒。
4. **打开工作台**：浏览器访问 `http://localhost:8100`，填名字、选角色和模式，进入工厂。第一次启动时历史库是空的，系统会自动载入“实验 7”教学情景，首页半分钟内出现数据。
5. **看数据流**：`http://localhost:1880` 是 Node-RED，可以看到桥接的六条数据流和每条的状态。

还没装 ERPNext、只想先看看：`.env` 里设 `WQ_ERPNEXT_API=http://mock-erpnext:8091`，然后 `docker compose --profile mock up -d --build`。

停止：`docker compose down`（数据保留）；连数据一起清掉：`docker compose down -v`。

**更新到最新版本**：在 `factory\digital` 目录运行 `.\update.ps1`（拉取 GitHub 上的最新代码、重新构建并启动）。数字工厂的代码在问渠仓库的 `factory/` 目录；只改这里时，GitHub 不会重新部署学习平台的服务器。

## 三、日常使用

- **首页（运营总览）**：AI 今日简报、6 个关键指标、车间实况、订单与交期、计划与实际、质量控制图、关键物料、提醒与待办。每 5 秒从历史库刷新，设备状态经总线实时更新。点设备卡进车间终端，点“进入 3D 车间”看立体车间。
- **角色工作区**：订单与计划（计划员）、设计与工艺（工艺员）、车间执行（操作工，即车间终端）、质量（质检员）、经营与成本（厂长；教学模式下也是教师控制台）。
- **AI 工厂助手**：左侧栏“AI 工厂助手”或首页右上的输入框。教学模式只提示方向，不代做；生产模式可以起草订单等提议，**你确认后才写入 ERPNext**。
- **教学模式与生产模式**：顶栏随时切换。两种模式的数据分开记（消息里的 `mode` 字段），看板和评分只看当前模式。
- **教师控制台**（经营与成本页，教学模式）：改仿真倍速、给某台设备制造一次故障、重置实验 7 情景。

## 四、设计发布（网页设计台 / FreeCAD）

**网页设计台**（第 6 轮）：“设计与工艺”页的“在线设计”改参数、看三维和校核、点“发布新版本”；服务器（`hub/design.py`，build123d 出 STEP）生成全部文件，消息格式与下面的桌面宏完全相同。

**桌面 FreeCAD（进阶）**：同一页可下载填好地址和凭证的宏包，步骤见页面右侧。宏在 `digital/freecad`：改 `wq_shaft.py` 的参数 → 执行 `wq_publish.py`。它导出 STEP、画零件图、生成键槽 G 代码，经工作台发到总线；桥接在 ERPNext 里把 SH-301 的“设计版本”加一、挂上附件，钢材用量变了就建新版 BOM；AI 检查在制工单是否受影响。没装 FreeCAD 也能在命令行运行（不导出 STEP）。

## 五、自动测试

```bash
cd digital
python3 -m pytest -q tests          # 单元测试（总线、仿真、指标、算料、AI 规则、FreeCAD）
python3 tests/closed_loop.py        # 完整闭环：需要 bus、db、hub、sim、bridge、mock-erpnext 都在运行
```
完整闭环按实验 7 走一遍，并在模拟 ERPNext 里核对：订单、工单、7 张作业卡（工时不重叠）、每件一张质量检验单、完工入库扣料加成品、字段名全部符合 ERPNext v16 定义，最后实验 7 应得 100 分。

## 六、常见问题

| 现象 | 处理 |
| --- | --- |
| 左下角“统一数据总线 未连接” | `docker compose ps` 看 `bus` 是否在运行；防火墙放行 9001 |
| 提议一直“执行中” | Node-RED 页面看“执行已确认的提议”节点的红字；多半是 API 钥匙不对或 ERPNext 没开 |
| ERPNext 报“工时与其他记录重叠” | 同一工位的作业卡工时冲突；第 1 轮按仿真时间记工时，重置情景后重新做即可，并把现象告诉我们 |
| 首页全是空的 | 教学模式：在“经营与成本”点“重置”；生产模式：要有真实设备或 ERPNext 数据才会有内容 |
| 想换成真实机床 | 设备按附录 A 发同样的消息即可（`source` 写 `plc/<设备>`），其他部分不改 |

## 七、第 1 轮的边界

- 只做输出轴 SH-301 的闭环（决定 F4）；算料会列出整台减速器的需求，但只下达 SH-301 工单。
- 零件图是宏自己画的 SVG，不是 FreeCAD TechDraw；键槽 G 代码用自写的后处理生成（与 CAM 工作台的刀路等价，便于学生读懂）。
- 教学情景里的历史订单和库存是演示数据（`source=demo/...`），不在 ERPNext 里；看板会标注。
- 模拟 ERPNext 只模仿与闭环有关的规则；真正的验收要在你电脑的 ERPNext 上实测（第 9 步）。
