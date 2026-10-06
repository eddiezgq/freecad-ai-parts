> **来源**：本目录搬自问渠仓库（wenquest）的 `factory/`，提交 `8710ae0c`（2026-10-06），原样搬入，之后在本仓库维护（ADR-0058）。
> 搬入时的改动只有：数字工厂测试里与问渠零件库互核的几份文件放在 `library_ref/`，测试路径随之改。
> 演示工厂“问渠减速器厂”与 WQR-105 的数据是虚构的演示数据。

# 问渠虚拟工厂（ERPNext 版）

一座只生产一种产品的虚拟工厂：**二级圆柱齿轮减速器 WQR-105**（传动比 10.5）。装好后，ERPNext 里已经有完整的产品结构、工艺路线、工作中心、质量检验方案、供应商和客户，学生可以直接从销售订单做到发货，走通 MRP、采购、车间报工、质检、序列号追溯和成本核算。

| 文件 | 内容 |
| --- | --- |
| `docker-compose.yml` | ERPNext v16.34.1 单机版（基于官方 frappe_docker），浏览器端口 8090 |
| `seed.py` | 一键导入工厂主数据（可重复运行） |
| `factory/data.py` | 工厂的全部数据：物料、BOM、工艺、工位、检验标准。改工厂就改这个文件 |
| `工厂设计.md` | 工厂设计说明：传动设计、产品结构、成本、瓶颈分析（由 data.py 自动生成） |
| `实验指导.md` | 6 个教学实验：从接单到发货，含不合格品处理和瓶颈改进 |
| `tests/` | 数据一致性检查，以及对照 ERPNext v16 字段定义的模拟导入 |

## 电脑要求

Windows 10/11，内存 16 GB 更流畅（最低 8 GB），磁盘空余 15 GB。ERPNext 会同时运行十来个容器，第一次下载镜像约 2 GB。

## 一、安装 Docker Desktop

从 [docker.com](https://www.docker.com/products/docker-desktop/) 下载 Docker Desktop for Windows，按默认选项安装（使用 WSL 2），装完重启电脑，打开 Docker Desktop 等它显示 “Engine running”。

## 二、启动 ERPNext

本文件夹在问渠仓库的 `factory` 目录里。把仓库克隆到比如 `D:\code\wenquest`（`git clone git@github.com:<你的用户名>/wenquest.git`），在 PowerShell 里：

```powershell
cd D:\code\wenquest\factory
docker compose up -d
docker compose logs -f create-site
```

最后一条命令会显示建站过程，看到它结束（出现 `Current Site set to frontend` 一类的字样后自动退出），按 `Ctrl+C` 离开。首次约 5–10 分钟。

浏览器打开下面这个地址，用户名 `Administrator`，密码 `admin`：

```
http://localhost:8090
```

## 三、完成初始设置向导

第一次登录会进入设置向导，按下面填：

| 项目 | 填写 |
| --- | --- |
| 语言 | English 或 简体中文（两种都可以，导入脚本不受影响） |
| 国家 / 时区 / 币种 | United States / America/New_York / USD |
| 公司名称 | 问渠减速器厂 WenQuest Gearbox（缩写 `WQ`） |
| 会计科目表 | 默认的 Standard |
| 示例数据 | 不要生成（如果向导问到） |

## 四、导入工厂数据

```powershell
py -m pip install -r requirements.txt
py seed.py --opening-stock
```

大约一两分钟。屏幕上会逐项显示进度，最后一行是“完成：新建 N 条”。`--opening-stock` 会放入小五金和齿轮油的期初库存，让实验聚焦在轴承、钢材、铸锻件这些关键物料上。脚本可以重复运行，已存在的记录会跳过。

导入后检查：在 ERPNext 里打开 **BOM** 列表，应有 13 个已提交的 BOM；打开 `WQR-105` 的 BOM，总成本应与《工厂设计.md》末尾的标准成本（约 1,232 美元）接近。

## 五、日常操作

| 要做的事 | 命令 |
| --- | --- |
| 暂停（保留数据） | `docker compose stop` |
| 继续 | `docker compose start` |
| 清空重来（删除全部数据） | `docker compose down -v`，然后重复第二到第四步 |
| 修改工厂设计 | 改 `factory/data.py` → `py -m factory.make_docs` 更新设计文档 → `py seed.py` 导入新增内容 |
| 运行检查 | `py -m pip install pytest`，然后 `py -m pytest tests` |

## 说明

- 默认账号密码都是 `admin`，只适合在自己电脑上学习。要放到服务器给学生用，需要改密码、加 HTTPS，再告诉 Claude 把它并入学习平台的部署。
- `seed.py` 发出的每一条数据都已对照 ERPNext v16 的字段定义做过模拟检查（`tests/test_factory.py`），但还没有在真实的 ERPNext 上运行过。第一次导入如果报错，把屏幕上“出错：”后面的内容发给 Claude。
- 所有供应商、客户都是虚构的示例单位；单价是教学用的示意数值。
- `tests/schemas/` 里的 JSON 文件取自 ERPNext（GPL v3），只用于测试。
