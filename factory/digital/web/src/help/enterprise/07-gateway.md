# 现场网关与设备接入

> 工厂里一台小工控机：车间设备连它，它经加密通道连云上的数字工厂；断网时先存着，恢复后补发。

## 装网关

```anim
name: terminal
title: 工厂里的网关工控机
$ ls
ca.crt  docker-compose.yml  gateway.env  start.sh
$ sudo ./start.sh
现场网关已启动：车间设备连本机 1883，数据经 TLS 送到 factory.example.com:8883
```

1. 工控机装 Ubuntu 22.04 或 24.04 和 Docker，能访问云端域名的 8883 端口；
2. 把服务器上 `gateway-bundle/` 里的 `ca.crt`、`gateway.env` 复制过去（`gateway.env` 里有密码，只交给网关管理员）；
3. 运行 `sudo ./start.sh`。

## 设备按什么发数据

| 方向 | 主题 |
| --- | --- |
| 上行（车间 → 云） | `wq/gearbox/区域/设备编号/status`、`event`、`measurement` 等 |
| 下行（云 → 车间） | `wq/gearbox/区域/设备编号/cmd`、`gcode`、`release` |

设备编号就是工厂清单里的编号；区域是机加工、质检、物流、仓库、现场之一。PLC、OPC UA、Modbus 采集器按现场配置，接好后按上表发布即可。

## 现在接进来的设备

```live
kind: machines
```

```ask
q: 网关断网一个小时，数据会丢吗？
```
