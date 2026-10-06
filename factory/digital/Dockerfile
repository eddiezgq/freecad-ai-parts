# 问渠数字工厂：枢纽服务（历史库写入、看板指标、AI 助手、MES、工作台网页）与仿真车间共用这个镜像
# 构建上下文是上一级目录（问渠仓库的 factory/，要用到其中的工厂数据 factory/factory/）

FROM node:22-slim AS web
WORKDIR /web
COPY digital/web/package.json digital/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY digital/web/ ./
RUN npm run build

# 动力学用的机器人模型（第 12 轮）：MuJoCo Menagerie 固定提交里的几台机械臂
FROM alpine:3.20 AS menagerie
RUN apk add --no-cache git
COPY deploy/fetch_menagerie.sh /fetch_menagerie.sh
RUN sh /fetch_menagerie.sh /opt/menagerie

# 固定 Debian 12（bookworm）：Debian 13 的 calculix-ccx 因 openmpi 升级装不上（Debian bug #1089784）
FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=America/New_York
WORKDIR /app
# build123d（网页设计台出 STEP，第 6 轮 W3）用到 OpenCASCADE，需要这几个系统库；
# 有限元（第 11 轮）：CalculiX 求解器 ccx，gmsh 需要 libGLU 等
# 流体分析（第 16 轮）：OpenFOAM（Debian 自带的软件包）与并行用的 Open MPI；虚拟 PLC（第 18 轮）：nodejs
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libxrender1 libx11-6 libxext6 \
        calculix-ccx libglu1-mesa libxcursor1 libxft2 libxinerama1 libgomp1 openfoam openmpi-bin nodejs \
    && rm -rf /var/lib/apt/lists/*
COPY digital/requirements.txt digital/requirements.txt
RUN pip install -r digital/requirements.txt "requests>=2.31"
COPY factory/ factory/
# 服务器首次安装时用它把减速器厂数据导入 ERPNext（第 3 轮 D6）
COPY seed.py seed.py
COPY digital/wqbus/ digital/wqbus/
COPY digital/sim/ digital/sim/
# 虚拟 PLC（第 18 轮第 8 步）：班次在仿真车间里算、回放；PLC 引擎是学习平台实验台的同一份 JS（Debian 自带的 nodejs 运行）
COPY digital/vplc/ digital/vplc/
COPY digital/hub/ digital/hub/
# 工厂本体定义（第 17 轮 A 期：15 个业务域的对象类型、属性、链接）
COPY digital/ontology/ digital/ontology/
COPY digital/twin/ digital/twin/
COPY digital/freecad/ digital/freecad/
COPY --from=menagerie /opt/menagerie /opt/menagerie
COPY digital/cae/ digital/cae/
# 工艺数据表与读表模块（第 13 轮：教材原件的副本，见 digital/std/sync.py）
COPY digital/std/ digital/std/
COPY ["digital/实验8_输出轴强度与疲劳校核.md", "digital/实验9_机械臂关节力矩与电机选型.md", "digital/实验10_输出轴数控车削与键槽铣削编程.md", "digital/实验11_减速器热平衡与输出轴轻量化.md", "digital/实验12_一根轴的数字化设计与两个典型案例.md", "digital/实验13_减速器数字孪生与预测性维护.md", "digital/实验14_减速器风扇冷却的流体与传热分析.md", "digital/"]
COPY digital/mock_erpnext/ digital/mock_erpnext/
COPY --from=web /web/dist digital/web/dist
WORKDIR /app/digital
EXPOSE 8100
CMD ["uvicorn", "hub.app:app", "--host", "0.0.0.0", "--port", "8100"]
