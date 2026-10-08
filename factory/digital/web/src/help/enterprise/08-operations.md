# 运维：备份、恢复、升级

> 每天自动备份；升级先备份；换清单先校验。

## 日常命令（在服务器安装目录）

| 命令 | 作用 |
| --- | --- |
| `./status.sh` | 各服务状态、工作台和 ERPNext 能否打开、磁盘剩余、最近一次备份 |
| `./backup.sh` | 备份历史库、ERPNext（数据库加附件）、配置与证书、工厂清单；保留 14 份 |
| `./restore.sh 备份包` | 恢复历史库与 ERPNext；配置只解压出来供核对 |
| `./upgrade.sh [标签] [--plant 清单]` | 先备份，再拉新镜像、重启；给了清单就先校验再换 |

```anim
name: terminal
title: 服务器 · /opt/fap
$ ./status.sh
hub  running  Up 3 days (healthy)
工作台 https://factory.example.com：正常
ERPNext https://erp.factory.example.com：正常
磁盘剩余：62G
最近备份：backups/fap-20261008-020000.tar.gz
$ ./upgrade.sh --plant plant.yaml
升级前已备份
清单无误：示例缝纫机厂，8 个工作站、14 台设备、12 道工序
换了工厂清单，补建 ERPNext 的工作站与工序...
升级完成（latest）
```

## 要注意的

- 每天定时备份：`echo "30 2 * * * root /opt/fap/backup.sh" > /etc/cron.d/fap-backup`（远程部署时我们替你设好）；`FAP_BACKUP_COPY_TO` 可把备份包再复制一份到别的存储；
- 换清单只补建新的工作站和工序，不改 ERPNext 里的公司；
- 工作日历只排了清单里的休息日，法定节假日在 ERPNext 里补；
- 恢复演练：在另一台机器上用 `restore.sh` 恢复一次，确认备份能用。

```ask
q: 升级失败了怎么回到升级前？
```
