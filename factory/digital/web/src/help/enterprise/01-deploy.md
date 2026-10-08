# 上线与部署

> 一台服务器、两个域名、一条命令：数字工厂、ERPNext、HTTPS、首次备份一起装好。

## 企业要准备的

| 项目 | 要求 |
| --- | --- |
| 服务器 | 4 核、16 GB 内存、100 GB 磁盘起；Ubuntu 22.04 或 24.04；装好 Docker |
| 域名 | 工作台（如 `factory.企业.com`）与 ERPNext（缺省 `erp.` 加工作台域名），都解析到服务器；国内要先备案 |
| 端口 | 对外开 80、443（网页）和 8883（现场网关）；SSH 只对部署人员开 |
| 管理员 | 数字工厂管理员一人（建第一个账号）、ERPNext 管理员一人 |
| AI 密钥 | 国内用 DeepSeek，其他地方用 Claude；两家都给更好，一家出错自动换另一家 |
| 工厂清单 | 按 Excel 模板填好（见“工厂清单”一章） |

## 一条命令安装

在服务器上，安装包目录里运行。没有清单时装的是演示工厂。

```anim
name: terminal
title: 服务器 · /opt/fap
$ ./install.sh --domain factory.example.com --email it@example.com --admin admin --plant plant.yaml
[10:02:11] 检查环境...
[10:02:12] 总线账号...
[10:02:15] 生成现场网关用的证书（工厂自有 CA，10 年）...
[10:02:16] 拉取镜像（第一次约 5–10 分钟）...
[10:09:40] 校验工厂清单 plant.yaml ...
清单无误：示例缝纫机厂，8 个工作站、13 台设备、12 道工序
[10:09:44] 新建 ERPNext 站点（约 3–5 分钟）...
[10:13:02] 完成 ERPNext 设置向导...
[10:13:40] 把工厂主数据导入 ERPNext...
完成：新建 81 条，已存在跳过 7 条
[10:13:52] 管理员 admin 已建好
[10:13:58] 首次备份完成（backups/）
[10:13:58] 安装完成：工作台 https://factory.example.com
```

终端里的厂名、条数是示例，以你的清单为准。安装可以重复运行，做过的步骤会跳过。

## 我们远程替你装

企业把 SSH 账号给我们，我们在自己这边一条命令部署，密码、密钥只在服务器上生成：

```anim
name: terminal
title: 部署人员的电脑
$ factory/enterprise/deploy.sh ops@203.0.113.10 --domain factory.example.com --email it@example.com --admin admin --plant plant.yaml
传安装包到 ops@203.0.113.10:/opt/fap ...
给管理员 admin 设密码（至少 10 位，字母加数字）：
安装完成：工作台 https://factory.example.com
```

## 装好后看什么

```live
kind: plant
```

浏览器打开工作台和 ERPNext 两个域名，证书有效、没有警告；用管理员登录，左栏能看到“账号与角色”。

```ask
q: 安装完成后，第一周应该先做哪几件事？
```
