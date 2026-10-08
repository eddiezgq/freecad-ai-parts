# 问渠数字工厂 · 企业安装版（ADR-0063）

企业自己的服务器（云服务器或内网机器）上一套完整的数字工厂。它和问渠学习平台无关，账号是企业自己的。
包含的服务：工作台与 AI 助手、数据总线、历史库、计算服务（有限元、流体、数控、动力学）、Node-RED 桥接、ERPNext v16。
入口由 Caddy 提供，自动启用 HTTPS。镜像从 GitHub 容器仓库拉取，不在现场构建。

对企业的要求见 [企业上线清单](../../docs/enterprise-onboarding.md)。

## 远程部署到企业的云服务器（在我们这边运行）

```bash
factory/enterprise/deploy.sh ubuntu@203.0.113.10 --domain factory.example.com --email it@example.com --admin admin
factory/enterprise/deploy.sh ubuntu@203.0.113.10 --status
factory/enterprise/deploy.sh ubuntu@203.0.113.10 --upgrade          # 先备份，再换新镜像
factory/enterprise/deploy.sh ubuntu@203.0.113.10 --backup
```

`deploy.sh` 经 SSH 把本目录和公共零件库传到服务器的 `/opt/fap`，再运行 `install.sh`。
密码和密钥都在服务器上生成，不经过我们这边；管理员密码在安装时于终端里输入。

## 在服务器上直接安装

```bash
./install.sh --domain factory.example.com --email it@example.com --admin admin     # 公网：Let's Encrypt 证书
./install.sh --domain factory.local --tls-internal --admin admin --demo            # 内网 / 试用：自签证书，带仿真车间
```

| 选项 | 说明 |
| --- | --- |
| `--domain` | 工作台域名。ERPNext 在 `erp.<域名>`，可用 `--erp-domain` 改。两个域名都要解析到这台服务器 |
| `--email` / `--tls-internal` | 二选一：申请正式证书用的邮箱，或使用自签证书 |
| `--admin` | 第一个管理员的用户名。密码从 `FAP_ADMIN_PASSWORD` 读，没有时提示输入 |
| `--region cn\|intl` | AI 模型地区：`cn` 用 DeepSeek，`intl` 用 Claude。不给时按服务器时区推断 |
| `--claude-key`、`--deepseek-key` | AI 密钥，也可以以后写进 `.env` |
| `--demo` | 演示模式：启动仿真车间 |
| `--plant 清单.yaml` | 企业自己的工厂清单（ADR-0064，Excel 模板见 `docs/enterprise-onboarding.md` 第五节）。ERPNext 的公司、国家、币种、时区，工作站、工序，车间平面都按它建；不给时装演示工厂 |
| `--images 标签`、`--no-pull`、`--registry-token` | 镜像版本、离线安装、拉取私有镜像用的令牌 |

`install.sh` 可以重复运行，已经做过的步骤会跳过。它依次完成这些事：
1. 检查环境（Docker、内存 ≥ 8 GB、磁盘 ≥ 40 GB）。
2. 生成密码与密钥，写入 `.env`（权限 600）。
3. 建总线账号，生成现场网关用的证书。
4. 拉取镜像。
5. 校验工厂清单（给了 `--plant` 时），建 ERPNext 站点，按清单的公司完成设置向导，生成桥接用的钥匙。
6. 启动数字工厂，并把工厂主数据导入 ERPNext。
7. 建第一个管理员。
8. 生成现场网关的连接包（`gateway-bundle/`），并做首次备份。

Windows 本机：先装 Docker Desktop 和 WSL2，再运行 `.\factory\enterprise\install.ps1 -Domain factory.local`。它在 WSL 里运行同一个 `install.sh`。

## 日常运维

| 脚本 | 作用 |
| --- | --- |
| `status.sh` | 各服务状态、工作台和 ERPNext 能否打开、磁盘剩余、最近一次备份 |
| `backup.sh` | 备份历史库、ERPNext（数据库加附件）、配置与证书，存到 `backups/`。保留 14 份，`FAP_BACKUP_COPY_TO` 可再复制一份到别处。建议每天由 cron 运行 |
| `restore.sh 备份包` | 恢复历史库与 ERPNext。配置只解压出来供核对，不覆盖现有的 |
| `upgrade.sh [标签] [--plant 清单.yaml]` | 先备份，再拉新镜像、重启。给了 `--plant` 就换工厂清单：先校验，有错不换；补建新的工作站、工序后重启。公司不随之改 |

## 端口与安全

- 对外开放：80、443（网页）；8883（现场网关，TLS 加账号密码，证书由安装时生成的工厂自有 CA 签发）
- 不对外：数据库、ERPNext 数据库、Node-RED 编辑器、总线的 1883 端口
- 登录：企业账号（用户名加密码，管理员在“账号与角色”里管理）。连续输错 5 次锁 10 分钟
- AI：缺省按地区选择，国内用 DeepSeek，其他地方用 Claude；一家出错时换另一家。厂长可在“厂情中枢 → AI 运行记录”里切换

## 目前的限制

- 工厂模型（设备、工作站、工序表）仍是问渠减速器厂的那一套。企业的产品可以经“转为生产物料”进来，但企业自己的车间布局要在下一阶段导入
- ERPNext 的公司按演示公司建（问渠减速器厂，币种美元）。要改成企业自己的公司名称和币种，目前要在 ERPNext 里手动调整
