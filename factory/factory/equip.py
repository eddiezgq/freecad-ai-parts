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
          ("ft", "handler"), ("tr", "taping"),
          # 第 125 轮：传感器厂（编码器线、扭矩传感器线）
          ("iqc", "incoming"), ("dcl", "diskclean"), ("cb", "centering"), ("hm", "headmount"), ("ecal", "enccal"), ("tcy", "thermcycle"),
          ("eft", "enctest"), ("sg", "gauging"), ("tb", "bridgewire"), ("tcp", "thermcomp"), ("dwt", "deadweight"), ("tft", "torquetest"),
          # 第 131 轮：电机厂（定子线、转子线、总装线）
          ("stk", "stackpress"), ("wd", "winder"), ("ins", "insertion"), ("vo", "varnish"), ("stt", "statortest"), ("mg", "magbond"),
          ("mz", "magnetizer"), ("bal", "balancer"), ("bt", "braketest"), ("dyn", "dyno"),
          # 第 134 轮：问渠缝纫机厂（铸造、机壳加工、关键零件、平缝机与包缝机装配）
          ("chg", "charging"), ("ind", "induction"), ("lab", "lab"), ("pour", "pouring"), ("core", "coreshoot"), ("cq", "incoming"),
          ("mold", "molding"), ("cool", "cooling"), ("so", "shakeout"), ("sand", "sandplant"), ("mix", "sandplant"), ("gate", "fettling"),
          ("shot", "shotblast"), ("vib", "knockout"), ("fet", "fettling"), ("age", "furnace"), ("put", "paint"), ("prime", "paint"),
          ("ci", "incoming"), ("tap", "mc"), ("deb", "deburr"), ("wash", "washer"), ("leak", "leaktest"), ("paint", "paint"), ("oven", "oven"),
          ("qt", "furnace"), ("car", "furnace"), ("ihd", "ihardening"), ("str", "straightener"), ("lap", "lapping"), ("adj", "adjust"),
          ("rin", "sewrunin"), ("eol", "eoltest"))

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
    # 第 125 轮：传感器厂（示例值）
    "incoming": dict(hazards=[('码盘碎裂划手', 1, 2, ['戴指套拿边缘'])], name="来料检验台", value=15000, bought=2023, pm_text="校显微镜、千分尺与电桥",
                     pm_min=30, repair_usd=150, lost_per_h=40, beta=2.0, eta_h=6000, mttr_min=60, pm_h=1500, init_h=300, modes=[("scope", "显微镜失焦")],
                     power=(0.3, 0.1, 0.02), air=False, wet=False, noise=50, auto=False, check=["量具在校准有效期内"]),
    "diskclean": dict(hazards=[('清洗剂（异丙醇）易燃', 2, 3, ['远离明火', '通风']), ('超声清洗槽热水', 1, 2, ['戴手套'])], name="码盘清洗台",
                      value=12000, bought=2023, pm_text="换清洗液、清超声槽、换风淋过滤器", pm_min=45, repair_usd=200, lost_per_h=40, beta=2.0, eta_h=5000,
                      mttr_min=60, pm_h=800, init_h=300, modes=[("filter", "过滤器堵塞、洁净度下降"), ("ultrasonic", "超声功率下降")],
                      power=(1.5, 0.5, 0.1), air=False, wet=True, noise=60, auto=False, check=["洁净间压差、粒子计数在规定内", "清洗液在更换周期内"]),
    "centering": dict(hazards=[('紫外灯伤眼', 2, 2, ['遮光罩', '戴防紫外眼镜'])], name="码盘粘接对心机", value=60000, bought=2022,
                      pm_text="校对心夹具与显微相机、量主轴跳动、换紫外灯", pm_min=60, repair_usd=600, lost_per_h=80, beta=2.2, eta_h=4000, mttr_min=90,
                      pm_h=800, init_h=500, modes=[("fixture", "对心夹具磨损、偏心变大"), ("uv", "紫外灯衰减、胶没固化透")], power=(0.8, 0.3, 0.05),
                      air=True, wet=False, noise=50, auto=False, check=["标准盘对心复测 ≤ 1 µm", "紫外灯强度在规定内"]),
    "headmount": dict(hazards=[('静电损坏读头', 2, 2, ['戴防静电腕带'])], name="读头装调台", value=25000, bought=2023, pm_text="校间隙塞规、示波器与李萨如图",
                      pm_min=45, repair_usd=300, lost_per_h=60, beta=2.0, eta_h=5000, mttr_min=60, pm_h=1000, init_h=300,
                      modes=[("gauge", "间隙塞规磨损"), ("scope", "示波器探头接触不良")], power=(0.4, 0.2, 0.05), air=False, wet=False, noise=50,
                      auto=False, check=["间隙塞规在校准有效期内", "防静电接地良好"]),
    "enccal": dict(hazards=[('转台旋转夹手', 1, 2, ['防护罩'])], name="编码器标定台", value=120000, bought=2022, pm_text="基准编码器比对、校转台同轴度",
                   pm_min=90, repair_usd=1500, lost_per_h=150, beta=2.0, eta_h=4000, mttr_min=180, pm_h=800, init_h=400,
                   modes=[("ref", "基准编码器漂移"), ("coupling", "联轴器松动")], power=(0.8, 0.3, 0.05), air=False, wet=False, noise=52, auto=True,
                   check=["基准编码器在校准有效期内", "标准件复测通过"]),
    "thermcycle": dict(hazards=[('箱内高低温烫伤冻伤', 2, 2, ['戴隔热手套', '回到室温再取'])], name="温度循环箱", value=30000, bought=2022,
                       pm_text="校温度、查压缩机与门封", pm_min=60, repair_usd=600, lost_per_h=50, beta=2.0, eta_h=5000, mttr_min=120, pm_h=1500, init_h=600,
                       modes=[("compressor", "压缩机制冷下降")], power=(6.0, 3.0, 0.3), air=False, wet=False, noise=62, auto=True, check=["温度曲线记录完整"]),
    "enctest": dict(hazards=[('转台旋转夹手', 1, 2, ['防护罩'])], name="编码器终检台", value=80000, bought=2022, pm_text="基准编码器比对、校测试软件版本",
                    pm_min=60, repair_usd=1000, lost_per_h=120, beta=2.0, eta_h=4000, mttr_min=150, pm_h=800, init_h=400, modes=[("ref", "基准编码器漂移")],
                    power=(0.6, 0.3, 0.05), air=False, wet=False, noise=52, auto=True, check=["标准件（金样编码器）复测通过"]),
    "gauging": dict(hazards=[('应变胶接触皮肤', 2, 2, ['戴丁腈手套']), ('显微镜长时间用眼', 3, 1, ['定时休息'])], name="应变片粘贴台", value=8000,
                    bought=2023, pm_text="清台面、校压块压力、查显微镜", pm_min=30, repair_usd=100, lost_per_h=40, beta=2.0, eta_h=6000, mttr_min=45,
                    pm_h=1500, init_h=300, modes=[("clamp", "压块压力不均")], power=(0.2, 0.1, 0.02), air=False, wet=False, noise=48, auto=False,
                    check=["应变胶回温、在有效期内", "贴片前表面打磨清洁"]),
    "bridgewire": dict(hazards=[('烙铁烫伤', 1, 2, ['烙铁架']), ('焊锡烟', 2, 1, ['抽烟罩开启'])], name="组桥焊线台", value=5000, bought=2023,
                       pm_text="换烙铁头、校温度、清抽烟罩过滤棉", pm_min=30, repair_usd=80, lost_per_h=30, beta=2.0, eta_h=6000, mttr_min=30, pm_h=1500,
                       init_h=200, modes=[("iron", "烙铁头氧化")], power=(0.3, 0.1, 0.02), air=False, wet=False, noise=48, auto=False,
                       check=["烙铁温度在规定内", "桥路电阻复测"]),
    "thermcomp": dict(hazards=[('箱内高低温烫伤冻伤', 2, 2, ['戴隔热手套'])], name="温度补偿箱", value=35000, bought=2022, pm_text="校温度、查采集通道",
                      pm_min=60, repair_usd=600, lost_per_h=50, beta=2.0, eta_h=5000, mttr_min=120, pm_h=1500, init_h=500,
                      modes=[("thermo", "温控失准")], power=(4.0, 2.0, 0.2), air=False, wet=False, noise=58, auto=True, check=["温度曲线记录完整"]),
    "deadweight": dict(hazards=[('砝码坠落砸脚', 2, 3, ['穿安全鞋', '砝码轻放']), ('加载杠杆夹手', 2, 2, ['手离开再加载'])], name="砝码标定台",
                       value=50000, bought=2021, pm_text="砝码送检、校杠杆臂长与水平", pm_min=90, repair_usd=500, lost_per_h=60, beta=2.0, eta_h=8000,
                       mttr_min=120, pm_h=2000, init_h=900, modes=[("lever", "杠杆刀口磨损")], power=(0.3, 0.1, 0.02), air=False, wet=False, noise=50,
                       auto=False, check=["砝码在检定有效期内", "杠杆水平"]),
    "torquetest": dict(hazards=[('加载装置夹手', 1, 2, ['防护罩'])], name="扭矩终检台", value=40000, bought=2022, pm_text="标准传感器比对、校采集",
                       pm_min=60, repair_usd=500, lost_per_h=60, beta=2.0, eta_h=5000, mttr_min=120, pm_h=1000, init_h=400, modes=[("daq", "采集通道漂移")],
                       power=(0.5, 0.2, 0.05), air=False, wet=False, noise=50, auto=False, check=["标准扭矩传感器比对通过"]),
    # 第 131 轮：电机厂（示例值）
    "stackpress": dict(hazards=[('压头夹手', 2, 3, ['双手按钮', '光幕']), ('冲片边缘划手', 2, 1, ['戴防割手套'])], name="铁芯叠压机", value=45000, bought=2022,
                       pm_text="校压力与叠高、查液压油与光幕", pm_min=60, repair_usd=600, lost_per_h=60, beta=2.2, eta_h=5000, mttr_min=120, pm_h=1000,
                       init_h=600, modes=[("hydraulic", "液压压力不稳"), ("die", "扣片模具磨损")], power=(4.0, 1.5, 0.2), air=False, wet=False, noise=72,
                       auto=False, check=["光幕、双手按钮有效", "叠高抽检在规定内"]),
    "winder": dict(hazards=[('绕线针头运动夹手', 2, 3, ['防护门联锁']), ('漆包线断线回弹', 1, 2, ['戴护目镜'])], name="绕线机", value=80000, bought=2022,
                   pm_text="校张力器、换导针、查排线", pm_min=60, repair_usd=800, lost_per_h=90, beta=2.0, eta_h=4000, mttr_min=90, pm_h=800, init_h=500,
                   modes=[("tension", "张力器不稳、线拉细或匝数漂"), ("needle", "导针磨损刮漆")], power=(2.5, 0.8, 0.1), air=True, wet=False, noise=68,
                   auto=True, check=["张力器读数在规定内", "首件匝数与电阻核对"]),
    "insertion": dict(hazards=[('槽楔锐边划手', 1, 2, ['戴手套'])], name="嵌线整形台", value=8000, bought=2023, pm_text="查整形模具、清台面", pm_min=30,
                      repair_usd=150, lost_per_h=40, beta=2.0, eta_h=6000, mttr_min=45, pm_h=1500, init_h=300, modes=[("die", "整形模具变形")],
                      power=(0.5, 0.1, 0.02), air=True, wet=False, noise=55, auto=False, check=["槽绝缘纸无破损", "端部高度在规定内"]),
    "varnish": dict(hazards=[('绝缘漆挥发物', 2, 2, ['排风开启', '戴防护口罩']), ('烘箱高温烫伤', 2, 3, ['戴隔热手套', '降温后取料'])], name="浸漆烘箱",
                    value=60000, bought=2021, pm_text="测炉温曲线、校温控、清漆槽、查真空泵", pm_min=90, repair_usd=800, lost_per_h=70, beta=2.0, eta_h=5000,
                    mttr_min=150, pm_h=1000, init_h=900, modes=[("heater", "加热管老化、炉温偏低"), ("vacuum", "真空度不够、漆浸不透")],
                    power=(18.0, 8.0, 0.5), air=False, wet=True, noise=60, auto=True, check=["炉温曲线记录完整", "漆的黏度在规定内"]),
    "statortest": dict(hazards=[('耐压测试高压触电', 3, 4, ['测试罩联锁', '不碰测试夹'])], name="定子测试台", value=35000, bought=2022,
                       pm_text="标准电阻、标准定子比对，查高压联锁", pm_min=45, repair_usd=400, lost_per_h=60, beta=2.0, eta_h=5000, mttr_min=90, pm_h=1000,
                       init_h=400, modes=[("probe", "测试夹接触不良"), ("hv", "高压模块漂移")], power=(0.6, 0.2, 0.05), air=False, wet=False, noise=50,
                       auto=True, check=["高压联锁有效", "标准定子复测通过"]),
    "magbond": dict(hazards=[('磁钢胶接触皮肤', 2, 2, ['戴丁腈手套']), ('磁钢碎片', 1, 2, ['戴护目镜'])], name="磁钢粘贴台", value=15000, bought=2023,
                    pm_text="校定位工装、清胶嘴", pm_min=30, repair_usd=200, lost_per_h=50, beta=2.0, eta_h=5000, mttr_min=60, pm_h=1000, init_h=300,
                    modes=[("fixture", "定位工装磨损、磁钢贴歪"), ("glue", "点胶量不稳")], power=(0.3, 0.1, 0.02), air=True, wet=False, noise=50,
                    auto=False, check=["定位工装用标准转子复核", "磁钢胶在有效期内"]),
    "magnetizer": dict(hazards=[('强磁场吸附铁件夹手', 3, 3, ['周围不放铁件', '充磁时手离开']), ('高压电容触电', 2, 4, ['放电后再维修'])], name="充磁机",
                       value=90000, bought=2021, pm_text="测充磁电压与磁通、查电容", pm_min=60, repair_usd=1500, lost_per_h=100, beta=2.0, eta_h=4000,
                       mttr_min=180, pm_h=800, init_h=900, modes=[("cap", "电容老化、充磁电压偏低"), ("fixture", "充磁头线圈发热")],
                       power=(8.0, 1.0, 0.2), air=False, wet=False, noise=65, auto=True, check=["充磁电压在规定内", "标准转子磁通复测"]),
    "balancer": dict(hazards=[('转子高速旋转', 2, 3, ['防护罩闭合再启动'])], name="动平衡机", value=50000, bought=2022, pm_text="标准转子校准、查传感器",
                     pm_min=45, repair_usd=600, lost_per_h=60, beta=2.0, eta_h=5000, mttr_min=120, pm_h=1000, init_h=500, modes=[("sensor", "振动传感器漂移")],
                     power=(1.5, 0.3, 0.05), air=False, wet=False, noise=70, auto=False, check=["标准转子复测通过"]),
    "braketest": dict(hazards=[('加载夹手', 1, 2, ['防护罩'])], name="抱闸测试台", value=25000, bought=2022, pm_text="标准扭矩扳手比对、校电源",
                      pm_min=45, repair_usd=300, lost_per_h=50, beta=2.0, eta_h=5000, mttr_min=90, pm_h=1000, init_h=400, modes=[("sensor", "扭矩传感器漂移")],
                      power=(0.5, 0.2, 0.05), air=False, wet=False, noise=52, auto=True, check=["标准件复测通过"]),
    "dyno": dict(hazards=[('联轴器高速旋转', 2, 3, ['防护罩闭合再启动']), ('电机外壳发热', 1, 2, ['测完再拿'])], name="电机终检台（测功台）", value=150000,
                 bought=2022, pm_text="标准电机比对、校扭矩传感器与功率分析仪、查联轴器对中", pm_min=90, repair_usd=2000, lost_per_h=150, beta=2.0, eta_h=4000,
                 mttr_min=180, pm_h=800, init_h=600, modes=[("torque", "扭矩传感器漂移"), ("coupling", "联轴器不对中")], power=(5.0, 1.5, 0.2), air=False,
                 wet=False, noise=72, auto=True, check=["标准电机（金样）复测通过", "联轴器对中"]),
    "general": dict(hazards=[('机械伤害', 2, 3, ['防护罩', '急停按钮'])], name="通用设备", value=20000, bought=2022, pm_text="例行保养", pm_min=120, repair_usd=400, lost_per_h=60,
                    beta=2.0, eta_h=2000, mttr_min=120, pm_h=800, init_h=300, modes=[("general", "设备故障")],
                    power=(5.0, 1.5, 0.3), air=False, wet=False, noise=70, auto=False, check=[]),
}
def _k(name, value, pm_text, modes, power, hazards, check, noise=75, wet=False, air=True, auto=False, bought=2022, pm_min=120,
       repair_usd=800, lost_per_h=100, beta=2.0, eta_h=3000, mttr_min=180, pm_h=800, init_h=600):
    return dict(hazards=hazards, name=name, value=value, bought=bought, pm_text=pm_text, pm_min=pm_min, repair_usd=repair_usd,
                lost_per_h=lost_per_h, beta=beta, eta_h=eta_h, mttr_min=mttr_min, pm_h=pm_h, init_h=init_h, modes=modes, power=power,
                air=air, wet=wet, noise=noise, auto=auto, check=check)


# 第 134 轮：问渠缝纫机厂的设备类别（全部示例值）
KIND.update({
    "charging": _k("配料加料车", 30000, "校配料秤、查加料车行走与电磁吸盘", [("scale", "配料秤称量超差"), ("magnet", "电磁吸盘吸力不足")], (5.0, 1.0, 0.2),
                   [('炉料坠落砸伤', 2, 4, ['吊运区域不站人', '戴安全帽'])], ["配料秤用砝码核对"], noise=78, air=False),
    "induction": _k("中频感应电炉", 260000, "查炉衬侵蚀厚度、冷却水压力与水质、感应线圈绝缘", [("lining", "炉衬侵蚀、需修炉"), ("water", "冷却水压力低报警")],
                    (550.0, 60.0, 5.0), [('铁水喷溅烫伤', 3, 5, ['加料前炉料烘干、不加潮湿料', '穿阻燃服戴面罩']), ('漏炉', 1, 5, ['炉衬测厚', '漏炉报警'])],
                    ["冷却水压力、温度正常", "炉衬厚度在规定以上"], noise=82, air=False, repair_usd=5000, lost_per_h=600, mttr_min=480, pm_h=400),
    "lab": _k("理化分析室", 120000, "光谱仪用标样校准、试验机与硬度计校验", [("drift", "仪器漂移、标样复测超差")], (3.0, 1.0, 0.3),
              [('取样烫伤', 2, 3, ['用取样勺、戴手套'])], ["标样复测在允差内"], noise=60, auto=True),
    "pouring": _k("自动浇注机", 180000, "查浇包耐材、塞杆、随流孕育给料器", [("stopper", "塞杆密封不严、滴铁"), ("feeder", "孕育剂给料器堵塞")], (15.0, 3.0, 0.5),
                  [('铁水喷溅烫伤', 3, 5, ['浇注区禁止站人', '穿阻燃服'])], ["孕育剂干燥、给料顺畅", "浇包预热"], noise=78, air=True, lost_per_h=500),
    "coreshoot": _k("覆膜砂射芯机", 90000, "清芯盒、查加热与射砂嘴", [("heater", "芯盒加热不均"), ("nozzle", "射砂嘴堵塞")], (25.0, 8.0, 1.0),
                    [('芯盒高温烫伤', 3, 3, ['戴隔热手套']), ('酚醛树脂烟气', 3, 2, ['排风开启'])], ["芯盒温度 230–260 ℃"], noise=76),
    "molding": _k("脱箱射压造型线", 900000, "查射砂板、液压系统、砂型输送", [("hyd", "液压系统压力不足"), ("pattern", "模板磨损、起模不良")], (90.0, 25.0, 3.0),
                  [('合型、推型挤压', 2, 5, ['光幕与联锁', '检修挂牌上锁'])], ["型硬度点检 ≥ 85", "模板清洁、脱模剂喷涂正常"], noise=88,
                  repair_usd=6000, lost_per_h=1200, mttr_min=360, pm_h=400),
    "cooling": _k("铸型冷却线", 200000, "查输送链与驱动", [("chain", "输送链卡滞")], (11.0, 4.0, 0.3), [('高温砂型烫伤', 2, 3, ['冷却线围栏'])],
                  ["冷却时间符合工艺"], noise=70, air=False, auto=True),
    "shakeout": _k("振动落砂机", 80000, "查激振电机、弹簧与筛板", [("motor", "激振电机轴承损坏"), ("grid", "筛板开裂")], (30.0, 6.0, 0.5),
                   [('噪声', 4, 2, ['戴耳罩']), ('粉尘（含游离二氧化硅）', 4, 3, ['除尘开启', '戴防尘口罩'])], ["除尘风量正常"], noise=95, air=False),
    "sandplant": _k("砂处理设备", 400000, "查混砂机刮板与碾轮、在线紧实率仪、旧砂冷却器", [("blade", "刮板磨损"), ("sensor", "在线紧实率 / 水分仪漂移")],
                    (75.0, 20.0, 2.0), [('混砂机转动伤人', 2, 4, ['检修挂牌上锁']), ('粉尘', 3, 3, ['除尘开启'])], ["在线水分仪与实验室比对"], noise=85,
                    lost_per_h=600),
    "shotblast": _k("吊钩式抛丸机", 120000, "换叶片与护板、查丸料与除尘滤筒", [("blade", "抛丸器叶片磨损"), ("filter", "除尘滤筒堵塞")], (37.0, 8.0, 0.5),
                    [('钢丸飞出', 2, 3, ['门联锁']), ('粉尘', 3, 3, ['除尘开启'])], ["丸料量充足、除尘压差正常"], noise=92, air=True),
    "knockout": _k("振动清砂机", 50000, "查激振器与夹具", [("exciter", "激振器故障")], (11.0, 2.0, 0.2),
                   [('噪声', 4, 2, ['隔声罩、戴耳罩']), ('粉尘', 3, 3, ['除尘开启'])], ["内腔清砂后用内窥镜抽检"], noise=96),
    "fettling": _k("清理打磨工位", 12000, "换砂轮、查除尘", [("wheel", "砂轮磨损"), ("dust", "除尘吸力不足")], (5.5, 1.0, 0.1),
                   [('砂轮破裂飞出', 2, 5, ['砂轮防护罩', '核对砂轮线速度']), ('粉尘', 4, 3, ['除尘台、戴防尘口罩'])], ["砂轮无裂纹"], noise=90),
    "furnace": _k("热处理炉", 220000, "测炉温均匀性、校热电偶、查炉门密封与气氛", [("tc", "热电偶漂移、实际炉温偏离"), ("heater", "加热元件老化")],
                  (90.0, 30.0, 3.0), [('高温烫伤', 3, 3, ['戴隔热手套', '出炉区围栏']), ('可控气氛泄漏（渗碳炉）', 1, 4, ['气体报警', '通风'])],
                  ["炉温曲线记录完整", "热电偶校准在有效期内"], noise=65, air=False, auto=True, pm_h=1500, init_h=2000),
    "paint": _k("涂装设备", 60000, "换过滤棉、清喷枪、查排风与水帘", [("filter", "过滤棉堵塞、漆雾超标"), ("gun", "喷枪雾化不良")], (11.0, 3.0, 0.3),
                [('漆雾吸入', 3, 3, ['排风开启', '戴防毒面具']), ('溶剂起火', 1, 5, ['防爆电器', '灭火器在手边'])], ["排风正常", "漆的黏度在规定内"], noise=72),
    "oven": _k("烘道", 80000, "测炉温曲线、查输送链与燃烧器", [("heater", "炉温偏低、漆膜不干"), ("chain", "悬挂链卡滞")], (40.0, 15.0, 1.0),
               [('高温烫伤', 2, 3, ['出口降温段后取件'])], ["炉温曲线记录完整"], noise=62, air=False, auto=True),
    "deburr": _k("去毛刺工位", 10000, "换去毛刺刀具与刷子、校内窥镜", [("tool", "去毛刺刀具磨损")], (2.0, 0.5, 0.1),
                 [('毛刺划手', 3, 2, ['戴防割手套'])], ["内窥镜成像清楚"], noise=72),
    "washer": _k("清洗机", 150000, "换清洗液、清过滤器、查喷嘴与热风", [("nozzle", "定点喷嘴堵塞"), ("filter", "清洗液过滤器堵塞、清洁度变差")], (45.0, 15.0, 1.0),
                 [('高压水射流', 2, 3, ['门联锁']), ('热水烫伤', 2, 2, ['戴手套'])], ["清洗液浓度、温度在规定内", "过滤器压差正常"], noise=74, wet=True),
    "leaktest": _k("渗漏试验台", 40000, "用标准漏孔校准、查封堵夹具密封", [("seal", "封堵密封圈老化、误判")], (1.0, 0.3, 0.1),
                   [('封堵夹具夹手', 2, 2, ['双手按钮'])], ["标准漏孔核对通过"], noise=58),
    "ihardening": _k("高频淬火机", 160000, "查感应器、淬火液浓度与冷却水", [("coil", "感应器老化、加热不足"), ("quench", "淬火液浓度偏离")], (160.0, 10.0, 1.0),
                     [('高频电磁场', 2, 3, ['屏蔽罩联锁']), ('淬火液飞溅', 2, 2, ['防护门'])], ["感应器无烧蚀", "淬火液浓度在规定内"], noise=68, wet=True),
    "straightener": _k("校直机", 45000, "校压头与测量表、查液压", [("gauge", "测量表失准")], (5.5, 1.0, 0.1),
                       [('压头挤压', 2, 3, ['双手按钮'])], ["标准棒复测通过"], noise=65),
    "lapping": _k("梭尖研磨机", 70000, "换研磨头、校对刀仪", [("head", "研磨头磨损")], (3.0, 1.0, 0.2),
                  [('研磨粉尘', 2, 2, ['吸尘开启'])], ["对刀仪复测通过"], noise=66),
    "adjust": _k("调试工位", 15000, "校针杆高度规、塞尺、定时量仪", [("gauge", "定时量仪失准")], (1.5, 0.3, 0.05),
                 [('机针刺伤', 3, 2, ['调试时停机、手不进针区'])], ["量规在校准有效期内"], noise=70),
    "sewrunin": _k("缝纫机跑合台", 8000, "查电源、温度与噪声传感器", [("sensor", "温度传感器漂移")], (0.8, 0.1, 0.02),
                   [('皮带、手轮卷入', 2, 3, ['防护罩', '跑合时不碰手轮'])], ["传感器校准在有效期内"], noise=80, air=False, auto=True),
    "eoltest": _k("出厂测试台", 30000, "校声级计、转速计、停针角度检测", [("sensor", "声级计 / 角度传感器漂移")], (1.0, 0.3, 0.05),
                  [('机针刺伤', 3, 2, ['试缝时手不进针区'])], ["标准机（金样）复测通过"], noise=80, air=False),
})
STAFFED_EXCEPT = ("bench", "runin", "reflow", "burnin", "cure", "plasma", "thermcycle", "thermcomp", "varnish",
                  "furnace", "oven", "cooling", "sewrunin")   # 第 134 轮：热处理炉、烘道、冷却线、跑合台   # 第 61 轮：自动测试台、跑合台不用人看着开（其余设备“要有人”）；第 85 轮：回流炉、老化房；第 103 轮：固化烘箱、等离子清洗；第 125 轮：温度循环箱、温度补偿箱；第 131 轮：浸漆烘箱
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
