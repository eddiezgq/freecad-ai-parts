# -*- coding: utf-8 -*-
"""设备的维护、能耗数据（第 59 轮）：清单里写了产品的厂（机器人厂等）打开“设备维护、能源、经营财务”时，每台设备的
原值、保养、可靠性（威布尔）、功率从这里来。

- 每台设备先按**类别**取缺省值（示例值，不对应任何真实设备）：类别按设备编号的前缀认（saw 锯床、cnc 车床、vmc/hmc 加工中心、grd 磨床……），
  认不出的按“通用设备”；
- 清单里这台设备写了 `maint`（原值、购入年、保养内容和时长、修理费、停机每小时损失、威布尔参数）或 `power_kw`（运行、空转、待机）就用清单的；
- 演示工厂（减速器厂）不走这里：它的数在 sim/reliability.py、sim/energy.py、hub/maint.py、hub/energy.py 里原样不动。
只做查表，不联网、不读数据库。"""

# 类别：编号前缀 → 类别名（先长后短，按顺序认）
PREFIX = (("saw", "saw"), ("cnc", "lathe"), ("vmc", "mc"), ("hmc", "mc"), ("grd", "grinder"), ("cmm", "cmm"), ("qc", "cmm"),
          ("ja", "assembly"), ("asm", "assembly"), ("ra", "assembly"), ("aa", "assembly"), ("ha", "assembly"), ("jt", "bench"), ("test", "bench"),
          ("cal", "calib"), ("run", "runin"), ("at", "agvtest"),
          # 第 85 轮：电路板厂的 SMT 线与后段
          ("sp", "printer"), ("spi", "spi"), ("pp", "placer"), ("rf", "reflow"), ("aoi", "aoi"), ("sw", "selsolder"), ("ict", "ict"),
          ("pg", "program"), ("cc", "coater"), ("bi", "burnin"), ("fct", "fct"), ("pk", "pack"),
          # 第 103 轮：芯片封测厂
          ("wi", "waferqc"), ("prb", "prober"), ("bg", "grindwafer"), ("dc", "dicer"), ("da", "diebond"), ("pl", "plasma"),
          ("wb", "wirebond"), ("mld", "mold"), ("cur", "cure"), ("lm", "laser"), ("plt", "plating"), ("tf", "trimform"),
          ("ft", "handler"), ("tr", "taping"))

# 类别缺省（示例值）：原值 $、购入年、保养内容、保养分钟、一次修理费 $、停机每小时损失 $、
# 威布尔 β、η 运行小时、平均修复分钟、保养周期 运行小时、开始时已运行小时、故障模式 [(代码, 名称)]、功率 (运行, 空转, 待机) kW、
# 用压缩空气、湿式加工（出油雾）、噪声 dB(A)、自动设备（不按班次关机）
KIND = {
    "saw": dict(hazards=[('锯条断裂', 2, 3, ['锯条张紧检查', '防护罩'])], name="锯床", value=18000, bought=2021, pm_text="换液压油、查锯条张紧", pm_min=120, repair_usd=400, lost_per_h=60,
                beta=2.0, eta_h=1600, mttr_min=120, pm_h=800, init_h=300, modes=[("blade", "锯条断裂"), ("hyd", "液压进给漏油")],
                power=(7.5, 2.0, 0.3), air=False, wet=False, noise=80, auto=False, check=["锯条张紧适当"]),
    "lathe": dict(hazards=[('卡盘夹伤', 2, 4, ['防护门联锁', '装夹时停主轴']), ('切屑飞溅', 3, 3, ['防护门', '戴防护眼镜'])], name="数控车床", value=65000, bought=2022, pm_text="换主轴润滑脂、查刀塔定位、清冷却箱", pm_min=120, repair_usd=700,
                  lost_per_h=80, beta=2.5, eta_h=1400, mttr_min=240, pm_h=600, init_h=380,
                  modes=[("spindle", "主轴轴承异响"), ("turret", "刀塔定位失准")], power=(15.0, 5.0, 0.6), air=True, wet=True, noise=74,
                  auto=False, check=["卡盘夹紧可靠"]),
    "mc": dict(hazards=[('切屑飞溅', 3, 3, ['防护门', '戴防护眼镜']), ('换刀时刀具伤手', 2, 3, ['换刀前停主轴', '戴防割手套'])], name="加工中心", value=110000, bought=2023, pm_text="换主轴润滑脂、查导轨", pm_min=120, repair_usd=800, lost_per_h=100,
               beta=2.5, eta_h=1500, mttr_min=240, pm_h=600, init_h=250, modes=[("spindle", "主轴轴承异响"), ("atc", "换刀机构卡刀")],
               power=(15.0, 5.0, 0.6), air=True, wet=True, noise=74, auto=False, check=["刀库、换刀动作正常"]),
    "grinder": dict(hazards=[('砂轮破裂飞出', 2, 5, ['砂轮防护罩', '开机前空转 1 分钟', '核对砂轮线速度']), ('磨削粉尘', 3, 2, ['吸尘装置', '戴防尘口罩'])], name="磨床", value=120000, bought=2021, pm_text="换液压油、查主轴轴承、校砂轮平衡", pm_min=180, repair_usd=1200,
                    lost_per_h=150, beta=3.0, eta_h=900, mttr_min=480, pm_h=500, init_h=420,
                    modes=[("spindle", "主轴轴承异响"), ("hyd", "液压系统漏油"), ("balance", "砂轮不平衡、振纹")],
                    power=(11.0, 4.0, 0.5), air=True, wet=True, noise=78, auto=False, check=["砂轮无裂纹、防护罩紧固", "液压油位、油温正常"]),
    "cmm": dict(hazards=[('测头与工件碰撞', 2, 2, ['手动移动时降速'])], name="测量设备", value=90000, bought=2023, pm_text="校测头、查气浮导轨", pm_min=120, repair_usd=600, lost_per_h=60,
                beta=2.0, eta_h=3000, mttr_min=120, pm_h=1000, init_h=350, modes=[("probe", "测头失准")],
                power=(2.0, 1.0, 0.2), air=True, wet=False, noise=60, auto=True, check=["测头标定在有效期内", "室温 20 ± 1 ℃"]),
    "assembly": dict(hazards=[('压装挤压', 2, 4, ['双手按钮', '光幕']), ('电动工具伤手', 2, 2, ['扭矩扳手反作用臂', '戴手套'])], name="装配工位", value=25000, bought=2023, pm_text="校电动扳手扭矩、查压装机", pm_min=90, repair_usd=400, lost_per_h=80,
                     beta=2.0, eta_h=3000, mttr_min=90, pm_h=1000, init_h=400, modes=[("tool", "电动扳手扭矩超差")],
                     power=(3.0, 1.0, 0.2), air=True, wet=False, noise=68, auto=False, check=["扭矩扳手校准在有效期内"]),
    "bench": dict(hazards=[('关节意外转动（带电调试）', 2, 4, ['防护罩联锁', '急停按钮在手边', '调试时只用低速'])], name="测试台", value=60000, bought=2023, pm_text="校扭矩、编码器和电流传感器", pm_min=120, repair_usd=600, lost_per_h=80,
                  beta=2.0, eta_h=2500, mttr_min=150, pm_h=1000, init_h=500, modes=[("sensor", "扭矩传感器漂移")],
                  power=(8.0, 1.5, 0.3), air=False, wet=False, noise=70, auto=True, check=["传感器校准在有效期内"]),
    "calib": dict(hazards=[('机器人意外运动（带电标定）', 2, 4, ['围栏与门联锁', '示教器使能开关', '标定时降速 250 mm/s']), ('激光照射眼睛（2 类激光跟踪仪）', 2, 2, ['不直视光束', '激光警示牌'])], name="标定工位", value=150000, bought=2024, pm_text="激光跟踪仪自检、校靶球", pm_min=120, repair_usd=900, lost_per_h=100,
                  beta=2.0, eta_h=3000, mttr_min=180, pm_h=1000, init_h=300, modes=[("tracker", "激光跟踪仪测距超差")],
                  power=(2.5, 1.0, 0.2), air=False, wet=False, noise=62, auto=True, check=["跟踪仪自检通过", "靶球清洁"]),
    "runin": dict(hazards=[('机器人带负载运动撞人', 2, 5, ['围栏与门联锁', '负载夹具点检', '区域内无人才能启动'])], name="跑合台", value=50000, bought=2023, pm_text="查负载加载机构、校电流采集", pm_min=120, repair_usd=600, lost_per_h=80,
                  beta=2.0, eta_h=2500, mttr_min=150, pm_h=1000, init_h=450, modes=[("load", "负载加载机构卡滞")],
                  power=(12.0, 1.5, 0.3), air=False, wet=False, noise=72, auto=True, check=["负载夹具紧固"]),
    "agvtest": dict(hazards=[('AGV 碰撞', 2, 3, ['激光避障', '地面通道标线', '调试时限速'])], name="调试场地", value=20000, bought=2023, pm_text="查充电桩、校定位标签", pm_min=60, repair_usd=300, lost_per_h=50,
                    beta=2.0, eta_h=3000, mttr_min=90, pm_h=1000, init_h=300, modes=[("charger", "充电桩故障")],
                    power=(4.0, 0.8, 0.2), air=False, wet=False, noise=62, auto=True, check=["场地标签完好"]),
    # 第 85 轮：电路板厂（示例值）
    "printer": dict(hazards=[('刮刀夹手', 2, 3, ['安全门联锁', '换钢网时停机']), ('锡膏接触皮肤（含银、锡）', 3, 2, ['戴丁腈手套', '用后洗手'])],
                    name="锡膏印刷机", value=80000, bought=2023, pm_text="清洗钢网与刮刀、校视觉对位、查擦网纸与真空", pm_min=90, repair_usd=600,
                    lost_per_h=120, beta=2.0, eta_h=2500, mttr_min=90, pm_h=500, init_h=300, modes=[("vision", "视觉对位失准"), ("wiper", "自动擦网卡纸")],
                    power=(3.0, 1.5, 0.3), air=True, wet=False, noise=65, auto=False, check=["钢网张力、无堵孔", "锡膏回温 4 小时以上、在有效期内"]),
    "spi": dict(hazards=[('光源照射眼睛', 1, 2, ['不直视光源'])], name="锡膏检测仪", value=70000, bought=2023, pm_text="校高度基准块、清洁镜头", pm_min=60,
                repair_usd=500, lost_per_h=100, beta=2.0, eta_h=4000, mttr_min=90, pm_h=1000, init_h=300, modes=[("camera", "相机标定漂移")],
                power=(1.5, 0.8, 0.2), air=True, wet=False, noise=58, auto=True, check=["高度标定块核对通过"]),
    "placer": dict(hazards=[('贴装头高速运动夹手', 2, 4, ['安全门联锁', '换料时暂停']), ('飞达弹簧伤手', 2, 2, ['按规程装飞达'])],
                   name="贴片机", value=250000, bought=2022, pm_text="清洁与更换吸嘴、校吸嘴中心与相机、查飞达", pm_min=120, repair_usd=1500,
                   lost_per_h=250, beta=2.2, eta_h=1800, mttr_min=180, pm_h=400, init_h=500,
                   modes=[("nozzle", "吸嘴磨损、吸取偏心"), ("feeder", "飞达送料不良"), ("vacuum", "真空泄漏")],
                   power=(4.0, 2.0, 0.4), air=True, wet=False, noise=70, auto=False, check=["吸嘴无堵塞、无磨损", "飞达与料号核对（防错料）"]),
    "reflow": dict(hazards=[('高温烫伤（出口约 60 ℃、炉内 250 ℃）', 3, 3, ['戴隔热手套', '开盖前降温']), ('助焊剂烟气', 3, 2, ['排风开启'])],
                   name="回流焊炉", value=120000, bought=2022, pm_text="测炉温曲线、清助焊剂回收、查链条与风机", pm_min=180, repair_usd=1000,
                   lost_per_h=250, beta=2.5, eta_h=3000, mttr_min=240, pm_h=600, init_h=800, modes=[("heater", "加热器老化、温区温度偏低"), ("fan", "热风电机故障")],
                   power=(30.0, 18.0, 2.0), air=False, wet=False, noise=68, auto=True, check=["炉温曲线在有效期内（每周测一次）", "排风正常"]),
    "aoi": dict(hazards=[('光源照射眼睛', 1, 2, ['不直视光源'])], name="自动光学检测", value=90000, bought=2023, pm_text="校相机与光源、复核检测程序", pm_min=60,
                repair_usd=500, lost_per_h=100, beta=2.0, eta_h=4000, mttr_min=90, pm_h=1000, init_h=300, modes=[("camera", "相机标定漂移")],
                power=(1.5, 0.8, 0.2), air=True, wet=False, noise=58, auto=True, check=["标准板（金板）检出全部缺陷"]),
    "selsolder": dict(hazards=[('锡炉高温烫伤（约 280 ℃）', 2, 4, ['戴隔热手套', '加锡时用工具']), ('助焊剂易燃', 2, 3, ['远离明火', '灭火器在手边'])],
                      name="选择焊", value=110000, bought=2023, pm_text="清锡渣、换喷嘴、校助焊剂喷涂量", pm_min=120, repair_usd=800,
                      lost_per_h=120, beta=2.0, eta_h=2200, mttr_min=150, pm_h=500, init_h=400, modes=[("nozzle", "焊锡喷嘴堵塞"), ("pump", "锡泵故障")],
                      power=(12.0, 8.0, 1.0), air=True, wet=False, noise=66, auto=False, check=["锡温 280 ± 5 ℃", "助焊剂液位"]),
    "ict": dict(hazards=[('针床压合夹手', 2, 3, ['双手按钮', '安全门'])], name="在线测试仪", value=60000, bought=2023, pm_text="清洁、更换磨损探针、自检", pm_min=90,
                repair_usd=500, lost_per_h=100, beta=2.0, eta_h=3500, mttr_min=120, pm_h=800, init_h=300, modes=[("probe", "探针接触不良")],
                power=(1.2, 0.6, 0.2), air=True, wet=False, noise=60, auto=False, check=["针床探针计数在寿命内", "标准板自检通过"]),
    "program": dict(hazards=[('静电损坏器件', 3, 2, ['戴防静电腕带'])], name="烧录工位", value=6000, bought=2024, pm_text="核对固件版本与校验和", pm_min=30,
                    repair_usd=200, lost_per_h=60, beta=2.0, eta_h=6000, mttr_min=45, pm_h=1500, init_h=200, modes=[("adapter", "烧录座接触不良")],
                    power=(0.3, 0.2, 0.05), air=False, wet=False, noise=50, auto=False, check=["固件版本与工艺文件一致"]),
    "coater": dict(hazards=[('三防漆溶剂挥发（易燃、刺激）', 3, 3, ['排风开启', '戴防护眼镜与口罩'])], name="三防涂覆机", value=70000, bought=2023,
                   pm_text="清洗喷阀、校涂覆厚度与路径", pm_min=90, repair_usd=600, lost_per_h=80, beta=2.0, eta_h=2500, mttr_min=120, pm_h=600,
                   init_h=300, modes=[("valve", "喷阀堵塞")], power=(2.5, 1.0, 0.2), air=True, wet=False, noise=62, auto=False, check=["喷阀出胶正常", "排风正常"]),
    "burnin": dict(hazards=[('高温带电板子烫伤、触电', 2, 3, ['断电后再取板', '戴隔热手套'])], name="老化房", value=40000, bought=2022,
                   pm_text="查温控与负载、校温度传感器", pm_min=60, repair_usd=400, lost_per_h=40, beta=2.0, eta_h=5000, mttr_min=120, pm_h=1500,
                   init_h=600, modes=[("thermo", "温控失准")], power=(15.0, 6.0, 0.5), air=False, wet=False, noise=55, auto=True, check=["温度 55 ± 3 ℃"]),
    "fct": dict(hazards=[('带电测试触电（48 V、大电流）', 2, 3, ['安全盖联锁', '急停按钮在手边'])], name="功能测试台", value=45000, bought=2024,
                pm_text="校电压、电流测量通道（用标准源）", pm_min=90, repair_usd=500, lost_per_h=100, beta=2.0, eta_h=3500, mttr_min=120, pm_h=800,
                init_h=300, modes=[("fixture", "测试夹具接触不良"), ("meter", "测量通道漂移")],
                power=(2.0, 0.8, 0.2), air=True, wet=False, noise=58, auto=False, check=["标准板复测通过", "测量通道校准在有效期内"]),
    "pack": dict(hazards=[('封口机烫伤', 1, 2, ['不碰封口条'])], name="包装台", value=3000, bought=2023, pm_text="查封口机与防静电台垫", pm_min=30,
                 repair_usd=100, lost_per_h=30, beta=2.0, eta_h=8000, mttr_min=30, pm_h=2000, init_h=200, modes=[("sealer", "封口机故障")],
                 power=(0.5, 0.1, 0.02), air=False, wet=False, noise=55, auto=False, check=["防静电台垫接地良好"]),
    # 第 103 轮：芯片封测厂（示例值）
    "waferqc": dict(hazards=[('晶圆碎裂划手', 1, 2, ['戴洁净手套', '用真空吸笔取片'])], name="晶圆来料检验台", value=30000, bought=2023,
                    pm_text="校显微镜与片号读码器、清洁台面", pm_min=30, repair_usd=200, lost_per_h=60, beta=2.0, eta_h=6000, mttr_min=60, pm_h=1500,
                    init_h=300, modes=[("reader", "片号读码失败")], power=(0.5, 0.2, 0.05), air=False, wet=False, noise=50, auto=False,
                    check=["洁净度在规定等级内", "防静电接地良好"]),
    "prober": dict(hazards=[('探针台承片台运动夹手', 2, 2, ['安全盖联锁']), ('静电损坏晶圆', 3, 2, ['戴防静电腕带'])], name="探针台与测试机",
                   value=900000, bought=2022, pm_text="清洁探针、量探针平面度与接触电阻、校承片台", pm_min=120, repair_usd=5000, lost_per_h=600,
                   beta=2.0, eta_h=2000, mttr_min=240, pm_h=400, init_h=600, modes=[("probe", "探针磨损、接触电阻升高"), ("chuck", "承片台吸附不良")],
                   power=(6.0, 3.0, 0.8), air=True, wet=False, noise=60, auto=True, check=["探针卡触点次数在寿命内", "标准片（金片）复测通过"]),
    "grindwafer": dict(hazards=[('砂轮高速旋转', 2, 4, ['防护罩联锁']), ('研磨废水', 3, 2, ['按规程排放'])], name="晶圆减薄机", value=600000, bought=2022,
                       pm_text="修整砂轮、量厚度、查冷却水", pm_min=120, repair_usd=3000, lost_per_h=300, beta=2.2, eta_h=2500, mttr_min=180, pm_h=600,
                       init_h=500, modes=[("wheel", "砂轮磨损、厚度超差"), ("chuck", "吸盘漏气")], power=(18.0, 6.0, 1.0), air=True, wet=True, noise=75,
                       auto=False, check=["减薄后厚度在规格内", "冷却水流量正常"]),
    "dicer": dict(hazards=[('划片刀高速旋转（3 万转）', 2, 4, ['防护罩联锁', '换刀时断电']), ('切割水溅出', 2, 1, ['防护罩'])], name="划片机",
                  value=400000, bought=2022, pm_text="换划片刀、修刀、校刀高与对位相机", pm_min=90, repair_usd=2500, lost_per_h=300, beta=2.0,
                  eta_h=2500, mttr_min=150, pm_h=500, init_h=400, modes=[("blade", "划片刀磨损、崩边增多"), ("spindle", "主轴振动")],
                  power=(5.0, 2.0, 0.5), air=True, wet=True, noise=72, auto=False, check=["刀片寿命在规定米数内", "切割道对位核对"]),
    "diebond": dict(hazards=[('装片头运动夹手', 2, 2, ['安全门联锁']), ('银浆接触皮肤', 2, 2, ['戴手套'])], name="装片机", value=350000, bought=2023,
                    pm_text="清洁点胶头、校吸嘴与相机", pm_min=90, repair_usd=2000, lost_per_h=250, beta=2.0, eta_h=2500, mttr_min=150, pm_h=500,
                    init_h=300, modes=[("dispense", "点胶量不稳"), ("pick", "吸取失败")], power=(3.0, 1.5, 0.3), air=True, wet=False, noise=62,
                    auto=False, check=["银浆回温时间够、在有效期内", "装片偏移抽检合格"]),
    "plasma": dict(hazards=[('射频辐射', 1, 3, ['门联锁']), ('工艺气体（氩、氧）', 2, 2, ['气体检测报警'])], name="等离子清洗机", value=80000, bought=2023,
                   pm_text="清腔体、查真空泵与气体流量", pm_min=60, repair_usd=800, lost_per_h=80, beta=2.0, eta_h=4000, mttr_min=120, pm_h=1000,
                   init_h=300, modes=[("pump", "真空泵抽速下降")], power=(3.0, 1.0, 0.3), air=False, wet=False, noise=60, auto=True,
                   check=["水滴角测试合格"]),
    "wirebond": dict(hazards=[('键合头运动夹手', 2, 2, ['安全盖联锁']), ('显微镜长时间用眼', 3, 1, ['定时休息'])], name="引线键合机", value=280000,
                     bought=2022, pm_text="换劈刀、校超声功率与焊线压力、清洁送线路径", pm_min=60, repair_usd=1500, lost_per_h=200, beta=2.0,
                     eta_h=2000, mttr_min=120, pm_h=400, init_h=400, modes=[("capillary", "劈刀磨损、拉力下降"), ("ultrasonic", "超声换能器漂移")],
                     power=(1.5, 0.8, 0.2), air=True, wet=False, noise=58, auto=False, check=["劈刀焊点数在寿命内", "首件拉力与推力合格"]),
    "mold": dict(hazards=[('模具高温烫伤（约 175 ℃）', 3, 3, ['戴隔热手套']), ('合模压力夹手', 2, 4, ['双手按钮', '光栅'])], name="塑封机",
                 value=500000, bought=2022, pm_text="清模具、查顶针与排气槽、校合模压力与温度", pm_min=180, repair_usd=3000, lost_per_h=400,
                 beta=2.2, eta_h=2500, mttr_min=240, pm_h=500, init_h=600, modes=[("vent", "排气槽堵、空洞增多"), ("heater", "模温不均")],
                 power=(25.0, 15.0, 2.0), air=True, wet=False, noise=70, auto=False, check=["塑封料回温 ≥ 16 h、开封后限时用完", "模温 175 ± 5 ℃"]),
    "cure": dict(hazards=[('高温烫伤（175 ℃）', 2, 3, ['戴隔热手套', '降温后取料'])], name="后固化烘箱", value=40000, bought=2022,
                 pm_text="校温度、查风机与门封", pm_min=60, repair_usd=400, lost_per_h=60, beta=2.0, eta_h=5000, mttr_min=120, pm_h=1500, init_h=600,
                 modes=[("thermo", "温控失准")], power=(12.0, 6.0, 0.5), air=False, wet=False, noise=55, auto=True, check=["炉温记录完整"]),
    "laser": dict(hazards=[('激光伤眼（4 类）', 2, 4, ['防护罩联锁', '戴激光护目镜']), ('烟尘', 2, 2, ['抽烟尘开启'])], name="激光打标机", value=60000,
                  bought=2023, pm_text="清镜片、校功率与字符位置", pm_min=60, repair_usd=800, lost_per_h=80, beta=2.0, eta_h=4000, mttr_min=120,
                  pm_h=1000, init_h=300, modes=[("lens", "镜片污染、字迹浅")], power=(2.0, 0.8, 0.2), air=False, wet=False, noise=60, auto=False,
                  check=["首件字符清晰、位置正确"]),
    "plating": dict(hazards=[('酸液灼伤', 3, 4, ['戴耐酸手套与面罩', '洗眼器在手边']), ('含锡废水', 3, 3, ['按规程处理排放'])], name="电镀线",
                    value=300000, bought=2021, pm_text="分析槽液、补加药剂、清阳极袋", pm_min=180, repair_usd=2000, lost_per_h=250, beta=2.0,
                    eta_h=3000, mttr_min=240, pm_h=500, init_h=900, modes=[("bath", "槽液浓度失调、镀层偏薄"), ("rectifier", "整流器故障")],
                    power=(30.0, 10.0, 2.0), air=True, wet=True, noise=65, auto=False, check=["槽液分析在规格内", "镀层厚度抽检合格"]),
    "trimform": dict(hazards=[('冲切模具夹手', 2, 4, ['双手按钮', '光栅'])], name="切筋成型机", value=150000, bought=2022, pm_text="磨冲头、清模具、校成型高度",
                     pm_min=120, repair_usd=1200, lost_per_h=200, beta=2.0, eta_h=3000, mttr_min=150, pm_h=600, init_h=400,
                     modes=[("punch", "冲头磨损、毛刺")], power=(5.0, 2.0, 0.3), air=True, wet=False, noise=80, auto=False, check=["切口无毛刺"]),
    "handler": dict(hazards=[('分选机运动夹手', 2, 2, ['安全门联锁'])], name="测试分选机与测试机", value=700000, bought=2022,
                    pm_text="清洁测试座、换磨损的测试针、标准件校验", pm_min=120, repair_usd=4000, lost_per_h=500, beta=2.0, eta_h=2500, mttr_min=180,
                    pm_h=500, init_h=500, modes=[("socket", "测试座接触不良"), ("jam", "分选机卡料")], power=(8.0, 3.0, 0.8), air=True, wet=False,
                    noise=68, auto=True, check=["标准件（金样）复测通过", "测试程序版本与工艺文件一致"]),
    "taping": dict(hazards=[('封带热压头烫伤', 1, 2, ['不碰热压头'])], name="编带机", value=50000, bought=2023, pm_text="校封带温度与剥离力、清洁视觉",
                   pm_min=60, repair_usd=400, lost_per_h=60, beta=2.0, eta_h=5000, mttr_min=60, pm_h=1500, init_h=300, modes=[("seal", "封带剥离力超差")],
                   power=(1.0, 0.4, 0.1), air=True, wet=False, noise=60, auto=False, check=["盖带剥离力在规格内", "方向与数量核对"]),
    "general": dict(hazards=[('机械伤害', 2, 3, ['防护罩', '急停按钮'])], name="通用设备", value=20000, bought=2022, pm_text="例行保养", pm_min=120, repair_usd=400, lost_per_h=60,
                    beta=2.0, eta_h=2000, mttr_min=120, pm_h=800, init_h=300, modes=[("general", "设备故障")],
                    power=(5.0, 1.5, 0.3), air=False, wet=False, noise=70, auto=False, check=[]),
}
STAFFED_EXCEPT = ("bench", "runin", "reflow", "burnin", "cure", "plasma")   # 第 61 轮：自动测试台、跑合台不用人看着开（其余设备“要有人”）；第 85 轮：回流炉、老化房；第 103 轮：固化烘箱、等离子清洗
MAINT_KEYS = ("value", "bought", "pm_text", "pm_min", "repair_usd", "lost_per_h", "beta", "eta_h", "mttr_min", "pm_h", "init_h")


def kind_of(uid):
    for pre, k in PREFIX:
        if uid.startswith(pre) and (len(uid) == len(pre) or not uid[len(pre)].isalpha()):
            return k
    return "general"


def validate_unit(at, u):
    """清单里一台设备的 maint、power_kw（可选）"""
    errs = []
    m = u.get("maint")
    if m is not None:
        if not isinstance(m, dict):
            return ["{}.maint：要是 {{原值 value, 购入年 bought, …}}".format(at)]
        for k, v in m.items():
            if k not in MAINT_KEYS:
                errs.append("{}.maint.{}：不认识的字段（可写 {}）".format(at, k, "、".join(MAINT_KEYS)))
            elif k == "pm_text":
                if not (isinstance(v, str) and v):
                    errs.append("{}.maint.pm_text：保养内容要写文字".format(at))
            elif not (isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0):
                errs.append("{}.maint.{}：要是正数".format(at, k))
    pw = u.get("power_kw")
    if pw is not None and not (isinstance(pw, list) and len(pw) == 3 and all(isinstance(x, (int, float)) and x >= 0 for x in pw)):
        errs.append("{}.power_kw：[运行, 空转, 待机] kW".format(at))
    return errs


def profiles(units):
    """清单的 units 列表 → {设备编号: 合并后的数据}；只取车间里的设备（有工作站的）"""
    out = {}
    for u in units:
        if not u.get("workstation"):
            continue
        k = kind_of(u["id"])
        d = dict(KIND[k], kind=k, name=u["name"])
        d.update(u.get("maint") or {})
        if u.get("power_kw"):
            d["power"] = tuple(u["power_kw"])
        d["modes"] = [tuple(x) for x in d["modes"]]
        d["check"] = list(d["check"])
        d["hazards"] = [tuple(x) for x in d["hazards"]]
        out[u["id"]] = d
    return out


def active():
    """当前工厂（清单里写了产品、又不是演示工厂）的设备数据；演示工厂或没有清单时 None"""
    try:
        from factory import plant
    except ImportError:
        return None
    p = plant.active()
    if not p or p["DEMO_DATA"] or not p.get("ITEMS"):
        return None
    return p.get("EQUIP")


def bottleneck():
    """第 67 轮：本厂的瓶颈设备（AI 巡检用）。演示工厂是外圆磨床 grd-01；其他厂按工艺路线：各工作站的标准工时之和 ÷ 台数，最大的那个工作站的第一台"""
    if active() is None:
        return "grd-01"
    from factory import data as F
    load = {}
    for ops in F.ROUTINGS.values():
        for op, mins in ops:
            ws = F.OPERATIONS.get(op)
            if ws:
                load[ws] = load.get(ws, 0.0) + float(mins) / max(1, F.WORKSTATIONS.get(ws, (1,))[0])
    if not load:
        return None
    ws = max(load, key=load.get)
    from factory import plant
    units = plant.active()["UNITS"]
    return next((u for u, v in units.items() if v[3] == ws), None)


def key_items():
    """第 67 轮：来料不合格判“严重”的物料——演示工厂是轴承（BRG- 开头），其他厂取清单的关键物料（key_materials）"""
    if active() is None:
        return None
    from factory import data as F
    return set(getattr(F, "KEY_MATERIALS", None) or ())
