# 新块样张（只用于测试与截图）

> 第 30 轮 §八 8-1 的新块都在这一页：拖着玩、当场动手、做完打勾、你来选、实时数据。不放进 web/src/help/。

## 设备还能撑多久

```anim
name: causal
caption: 一次停机，因果链从设备一层层亮到客户
```

```lab
id: weibull
preset: grd
height: 640
```

## 当场动手

```try
action: stop-grinder
label: 让磨床停机 2 小时
note: 按下去以后看下面的设备状态：GRD-01 几秒后变红。
```

```live
kind: machines
```

```goto
tour: planner-order
label: 接一张订单并算料（做完打勾）
```

## 三个方案

现在保养、下班后保养、不做：比确定花费加预期损失。

```quiz
q: 磨床逾期 120 小时，急单在赶：
options:
  - 现在保养 | wrong | 瓶颈停 3 小时少挣 $600，合计约 $817
  - 下班后保养 | right | 合计约 $235，不占生产时间
  - 不做 | wrong | 预期损失 $375，坏了急单要晚
more: #三个方案
```

```ask
q: 我们厂现在哪台设备最该保养？
```
