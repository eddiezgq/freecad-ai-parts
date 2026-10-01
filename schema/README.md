# schema

全项目的共同契约：组件（Component）、端口（Port）、连接规则（Rule）、系统（System）的 JSON Schema（Draft 2020-12），以及 `port-types/` 端口类型库。

- 文件命名：`<对象>.schema.json`，例如 `component.schema.json`
- 端口类型：`port-types/<类别>.<名称>.schema.json`，例如 `mechanical.flange.schema.json`
- 概念上对应 SysML v2（端口定义、端口用法、接口），见 [ADR-0002](../docs/adr/0002-port-schema.md)
- 任何修改先写决策记录，再改 schema；CI 会校验此目录下所有 `*.schema.json`

状态：M1（2026-10-05 至 10-25）定稿。
