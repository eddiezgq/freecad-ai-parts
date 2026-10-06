# 问渠数字工厂 · 实施细则 · 第 10 轮：班级（小组）工厂、SolidWorks 提交宏

2026-10-01 · 承接：第 9 轮（演示工厂的做法）、第 8 轮（企业版）

> 状态：**已确认（2026-10-01）；施工完成、已上线，验收见第七节（SolidWorks 宏待 Eddie 实测）**

## 一、Eddie 的要求（2026-10-01）

- 目前是开发阶段，**先跑通一个班**；“班”可以是一个班，也可以是一个小组。
- **保留原来的公共教学工厂**（factory.）。
- 有正版 SolidWorks，第二期的 SolidWorks 接入可以做。

## 二、决定（已确认）

| 编号 | 决定 | 理由 |
|---|---|---|
| K1 | **班级工厂 = 一座独立的教学工厂**，做法和第 9 轮演示工厂相同：自己的总线、枢纽、仿真车间、桥接，历史库 `wq_c_<编号>`，ERPNext 站点 `c-<编号>`（同一套 ERPNext 程序，只多一个站点） | 演示工厂已经证明这样省内存、隔离彻底；“小组”就是多建几座 |
| K2 | **怎么建**：在仓库的 `factory/deploy/classes.yaml` 里写一行（编号、名称、对应的问渠课程、任课老师的问渠账号编号），推送后自动部署时建好（ERPNext 站点、数据、单点登录）；删掉一行不自动删数据（防误删），另有清理命令 | 开发阶段最简单可靠；以后再做“老师在课程里点按钮建厂” |
| K3 | **网址**：`https://<编号>.factory.wenquestrobotics.com`（工作台），ERPNext `https://<编号>.erp.wenquestrobotics.com`。需要 Eddie 加**两条通配解析**（第六节），以后再加班不用再动解析 | 每加一个班都改解析太麻烦 |
| K4 | **谁能进**：开发阶段，登录过问渠的人都能进（教学模式，学生四个岗位）；`classes.yaml` 里写的任课老师有厂长角色和教师控制台，重置、倍速、制造故障只影响本班 | 先跑通；以后按课程选课名单限制 |
| K5 | **公共教学工厂、演示工厂都不变** | Eddie 要求保留 |
| K6 | **第一个班**：`classes.yaml` 先写一个试点班 `pilot`（任课老师：Eddie），用它跑通实验 7 | 只建一个 |
| S1 | **SolidWorks 提交宏**：一个文本格式的 SolidWorks 宏（`.swb`，工具 → 宏 → 运行即可，不用安装插件）：把当前零件导出 STEP；同名工程图打开时一并导出 PDF；弹框填物料编号和改动说明，提交到“设计发布与审批”（和 FreeCAD 按钮同一个接口）。地址和登录凭证由宏包预先填好 | 第 8 轮 Q5 第二期；宏比插件好装，Eddie 能直接试 |
| S2 | SolidWorks 宏随“我的 FreeCAD 宏包”一起下载（宏包改名“我的 CAD 宏包”） | 一处下载 |

## 三、交付物与验收

| 交付物 | 验收 |
|---|---|
| 班级工厂机制 | `classes.yaml` 加一行 → 部署后自动建好；演练（GitHub 上的真 ERPNext）里建一个班级工厂并跑通实验 7 闭环（得 100 分） |
| 试点班 pilot | 线上 `pilot.factory.` 能打开，问渠账号进入是教学模式，车间有设备；Eddie 用厂长角色重置情景，公共教学工厂的数据不受影响 |
| SolidWorks 宏 | Eddie 在 SolidWorks 里运行宏提交一个零件，“设计发布与审批”里出现这次提交，三维能看（我这里没有 SolidWorks，只能写好、由 Eddie 实测） |
| 帮助 | 《数字工厂上线与维护》加“怎么加一个班”；企业版说明加 SolidWorks |

## 四、施工顺序

1. 班级工厂：配置生成（按 `classes.yaml` 生成每个班的服务配置）、建站与导数据脚本、Caddy 通配网址、演练。
2. 试点班 pilot 上线。
3. SolidWorks 宏、宏包合并。
4. 帮助、验收。

## 五、实施记录

- 第 1 步（班级工厂）：`factory/deploy/classes.yaml`（先写一个 `pilot` 试点班）；`deploy/classes.py` 按它生成 `docker-compose.classes.yml`（每班 bus/hub/sim/bridge/erp-frontend 五个服务，历史库 `wq_c_<编号>`，ERPNext 站点 `c-<编号>`）和编号表 `classes.ids`，部署时生成并随部署文件拷到服务器；`deploy/lib.sh` 把第 9 轮演示工厂的建站步骤整理成通用的 `site_setup`，演示工厂和班级工厂共用（演示工厂的 .env 名字不变）；`update.sh` 先补各班工作台密钥，再逐班 `class_setup`（新建要可用内存 ≥ 0.9 GB，失败不影响其他工厂）；服务器上 `dc` 自动带上 `docker-compose.classes.yml`。删掉一行时 `--remove-orphans` 只停掉这班的容器，数据（历史库、ERPNext 站点）保留。
- 枢纽：`/api/caddy/ask`（公共工厂回答 Caddy 某个 `<编号>.factory/erp` 是否已建）、`WQ_CLASS_TEACHERS`（班级任课老师按老师对待）、`WQ_FACTORY_NAME`（顶栏显示“问渠减速器厂（试点班）”）。学习平台 Caddy：`*.factory`、`*.erp` 两个通配网址，按需申请证书（先问枢纽），按网址第一段转到这班的服务。
- “服务器演练”加“班级工厂”：生成 pilot 的配置（端口开到本机）→ `class_setup pilot` → 对 pilot 跑完整实验 7 闭环（真 ERPNext 的 c-pilot 站点）。演练时限 75 → 110 分钟。
- 第 3 步（SolidWorks）：`freecad/wq_submit_solidworks.swb`（文本宏，“工具 → 宏 → 运行”）：导出 STEP、同名工程图已打开时导出 PDF、问物料编号和改动说明、上传到 `/api/plm/submit`；物料编号记在文件属性 `WQ_Item` 里。**宏里的提示用英文**（只用 ASCII 字符，在任何语言的 Windows 上都不乱码）——与细则的偏差。宏包改名“我的 CAD 宏包”，多一个 `SolidWorks/` 文件夹，使用说明加 SolidWorks 三步。
- 测试：`test_class_factory_bits`；宏包测试加 SolidWorks 宏（地址、凭证已填）。全部 71 项通过。


## 六、需要 Eddie 做的

1. 确认本细则。
2. 在域名服务商加两条**通配** A 记录，都指向 `137.184.76.60`：主机名 `*.factory`、`*.erp`。
3. SolidWorks 宏写好后在你的电脑上试一次。

## 七、验收（2026-10-02）

| 交付物 | 结果 |
|---|---|
| 班级工厂机制 | ✓ 部署前“服务器演练”在真 ERPNext 上建好 pilot（c-pilot 站点）并跑完整实验 7 闭环通过 |
| 试点班 pilot | ✓ 线上检查：`pilot.factory` 能打开（按需证书已发）、教学模式、12 台设备在发数据；`pilot.erp` 登录页有“用问渠账号登录”和自动跳转。公共教学工厂、演示工厂同时检查正常。**待 Eddie 用厂长角色在 pilot 里重置情景，确认公共工厂不受影响** |
| SolidWorks 宏 | 宏写好、随“我的 CAD 宏包”下载（地址、凭证已填，CRLF 换行）；**待 Eddie 在 SolidWorks 里实测** |
| 帮助 | ✓ 《上线与维护》加“怎么加一个班”；《企业版使用说明》加 SolidWorks |

Eddie 的通配解析 `*.factory`、`*.erp` 已生效（2026-10-01 晚）。
