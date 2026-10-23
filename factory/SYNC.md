# 两边数字工厂的同步清单（第 30 轮 H-9）

数字工厂有两份代码：

- **问渠这边**：本仓库 `factory/`，教学为主（E1–E7、实验 7–23、情景导演、第 29 轮课程用到的仿真）；
- **那边**：freecad-ai-parts 仓库的 `factory/`，企业为主（企业安装版、账号、CAD 发布、选型零件库、新产品进工厂）。

2026-10-06 那边从这边的提交 `8710ae0c` 整套搬过去，之后两边各走了一段。第 30 轮起的规矩：

1. 下面没列的路径都是**两边共有**，内容应当逐字一致。
2. **教学功能在这边改，企业功能在那边改**；共有部分谁改了，同一轮里同步到另一边。
3. 每轮结束跑一次比对脚本，报告 0 差异才算这一轮做完。

## 怎么比对

在本仓库根目录运行（只用 Python 标准库，不用装别的）：

```bash
python3 tools/factory_sync.py                                   # 那边的仓库缺省在 /home/claude/freecad-ai-parts
python3 tools/factory_sync.py /path/to/freecad-ai-parts         # 指定那边仓库的位置
python3 tools/factory_sync.py --diff                            # 同时打印每个不同文件的逐行差异
python3 tools/factory_sync.py --diff digital/hub/app.py         # 只看某几个文件的差异
```

脚本报告三类：共有文件内容不同、只在这边有、只在那边有。下面三张清单里的路径不比对。
两边是 git 仓库时只看入了 git（或没被 .gitignore 挡住的新文件），`node_modules`、`dist`、`__pycache__` 这类不算。
有差异时退出码是 1，没差异是 0（可以放进 CI）。

清单写在下面的代码块里（脚本读这些代码块）：一行一个路径，相对 `factory/`；以 `/` 结尾的是整个目录，可以用 `*` 通配；
`#` 后面是说明。

## 只在问渠这边（教学、问渠线上）

```sync-a-only
digital/help/                 # 服务器端的说明文件（docs/帮助 经 help/sync.py 同步来的）
digital/docs/                 # 各轮截图
digital/hub/design_sw_api.py  # 设计软件提交 CAE（第 39 轮第 4 步 / 第 41 轮）：学习平台上的问渠凸轮、缝纫机设计软件
digital/tests/test_design_sw.py
```

## 只在那边（企业）

```sync-b-only
enterprise/                   # 企业安装版（install.sh、upgrade.sh、企业 compose）
gateway/                      # 那边的模型网关
library_ref/                  # 测试里与问渠零件库互核的文件
digital/Dockerfile.dockerignore   # 那边镜像从仓库根构建
digital/hub/accounts.py       # 企业账号（ADR-0063）
digital/hub/cad_link.py       # FreeCAD 方案发布到工厂（ADR-0058）
digital/hub/fap_library.py    # 选型零件库（ADR-0058）
digital/hub/products.py       # 新产品进工厂（ADR-0061）
digital/hub/enterprise_api.py # 上面这些企业功能挂到枢纽上的唯一入口（共有的 hub/app.py 有它就调用 mount）
digital/hub/seats_api.py      # 浮动席位（ADR-0066），由 enterprise_api 挂上
digital/bridge/lib/erp_enterprise.js   # 桥接里企业独有的提议（CAD 方案转生产物料、到货入库），共有的 erp.js 有它就加载
digital/cae/_fap.py           # 计算转接到 analysis/（ADR-0060）
digital/web/src/pages/Accounts.vue
digital/web/src/pages/CadDesigns.vue
digital/web/src/pages/FapLibrary.vue
digital/tests/test_accounts.py
digital/tests/test_cad_link.py
digital/tests/test_fap_library.py
digital/tests/test_products.py
digital/tests/test_seats_hub.py
digital/tools/help_videos_enterprise.py   # 企业功能的帮助视频剧本（共有的 help_videos.py 有它就并进去）
```

## 两边都有、各自实现（同名文件，故意不同）

```sync-own
README.md                     # 那边开头多一段来源说明
deploy/                       # 问渠线上服务器的部署；那边留着分叉时的副本，企业部署在 enterprise/
digital/Dockerfile            # 构建目录不同：这边 factory/，那边仓库根
digital/docker-compose.yml    # 那边挂选型零件库、多一个计算服务
digital/实施细则_*.md          # 各轮细则存档（这边继续写，那边是分叉时的副本）
digital/twin/models.py        # 那边 S-N 曲线取 analysis/fatigue
digital/tests/test_mbd.py     # 那边互核文件在 library_ref/
digital/tests/test_local_edition.py   # 跟着本地版脚本走，两边各测各的
digital/web/src/help/extra.json   # 本仓库独有的引导（tours）与帮助视频清单（videos）：问渠这边空，那边是企业功能的
local/                        # 本地版：这边给学校机房（老师密码、局域网地址、离线导入）；那边给企业（挂 FreeCAD 零件库）
digital/web/src/help/enterprise/   # 企业版帮助：这边只留本仓库有的功能（6 章），那边全套
# 那边计算内核并入 analysis/（ADR-0060），cae/ 里这些只剩转接层；这边保持完整实现（第 30 轮 H-7）
digital/cae/cam.py
digital/cae/cam_post.py
digital/cae/cam_power.py
digital/cae/cam_sim.py
digital/cae/cfd.py
digital/cae/cfd_bench.py
digital/cae/cfd_heat.py
digital/cae/fatigue.py
digital/cae/foam.py
digital/cae/geometry.py
digital/cae/mbd.py
digital/cae/mech_mjcf.py
digital/cae/modal.py
digital/cae/solve.py
digital/cae/thermal.py
digital/cae/topo.py
```

## 还没理顺的共有文件（第 30 轮记录，H-8 同步时处理）

- `digital/hub/app.py`、`digital/hub/db.py`、`digital/hub/ai.py`、`digital/hub/mrp.py`、`digital/hub/process.py`、
  `digital/mock_erpnext/server.py`、`digital/bridge/lib/erp.js`、`digital/wqbus/envelope.py`、`digital/hub/twin_api.py`、
  `digital/web/src/lib/api.js`、`digital/web/src/main.js`、`digital/web/src/pages/Login.vue`、`Planner.vue`：
  那边在这些共有文件里直接加了企业功能（账号、CAD、产品、零件库）。同步时把企业部分挪进那边独有的模块
  （例如 `hub/enterprise_api.py`，共有的 `app.py` 有就挂上），共有文件才能逐字一致。
- 第 4、5 步已做：教学版帮助 `digital/web/src/help/teach/` 及帮助框架是共有的（同步时带过去）；本地版与企业版帮助各自实现（见上）。
