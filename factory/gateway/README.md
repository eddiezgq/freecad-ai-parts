# 现场网关（ADR-0063）

数字工厂装在云上时，工厂里放一台小工控机当网关：
- 车间设备和采集器连网关本机的 1883 端口（工厂内网）
- 网关经 TLS 把数据送到云上数字工厂的 8883 端口，并把下发给车间的指令、数控程序和工艺下达带回来
- 断网时消息存在网关上（持久队列），恢复后补发

## 安装

1. 工控机：Ubuntu 22.04/24.04，装好 Docker；能访问云端域名的 8883 端口
2. 把云端安装生成的连接包（服务器上 `/opt/fap/gateway-bundle/` 里的 `ca.crt`、`gateway.env`）复制到本目录。`gateway.env` 里有密码，只交给网关管理员
3. 运行 `sudo ./start.sh`。要给本机 1883 加账号时，设 `FAP_LOCAL_USER`、`FAP_LOCAL_PASSWORD`

## 转发哪些主题

| 方向 | 主题 |
| --- | --- |
| 上行（车间 → 云） | `wq/gearbox/{machining,quality,logistics,warehouse,field}/#` |
| 下行（云 → 车间） | `wq/gearbox/+/+/cmd`、`gcode`、`release` |

云端只允许网关账号写这些车间区域、读这三类下行主题（见 `factory/enterprise/mosquitto/acl`）。
设备本身怎么接（PLC 地址表、OPC UA、Modbus 采集器）按现场配置，接好后按上表的主题发布即可。
