# 工厂本体定义（厂情中枢，第 17 轮）

每个领域一个文件；`_core.yaml` 是中枢自己的对象（异常、场景、动作记录……）。改本体只改这里，枢纽启动时校验，同步器可从头重放。

文件格式：

```yaml
domain: production          # 领域代号（唯一）
order: 7                    # 全貌地图上的顺序
label: 生产执行
label_en: Production
row: chain                  # chain = 价值链主线；support = 支撑面
types:
  Machine:                  # 对象类型代号（全局唯一，大驼峰）
    label: 设备
    label_en: Machine
    maturity: have          # have 已有数据 · erp ERPNext 可启用 · capture 待采集 · sim 教学模拟 · next 后续各期生成（异常、场景、动作、AI 运行）
    key: 设备号，小写，如 grd-01   # 编号规则（说明文字）
    title: "{key} {name}"   # 显示名模板
    sensitivity: 0          # 0 公开 1 内部 2 部门 3 受限（可写在类型或属性上）
    sources: [machine.status, machine.event]   # 数据来源（说明，映射代码在 hub/ont/mappers.py）
    props:
      name: {t: str, l: 名称}
      tool_life: {t: num, l: 刀具剩余寿命, u: "%"}
      state: {t: str, l: 状态, series: true}
    links:
      tools: {to: Tool, l: 装有, inv: 装在}   # 从本类型指向 to；inv 是反方向的叫法
```

属性类型 t：str、num、int、bool、date、time（时间戳）、json。
