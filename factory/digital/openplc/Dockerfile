# 问渠数字工厂 · OpenPLC 运行时（第 18 轮第 8 步，OpenPLC 兼容性检查）
# 构建上下文：factory/digital。OpenPLC v3 固定在一个提交上；只在数字工厂内部网络，对外不开端口。
# 容器里跑三样：OpenPLC 网页与运行时（127.0.0.1:8080，只给本容器的检查服务用）、虚拟设备从站（检查时临时起，127.0.0.1:5020）、
# 检查服务 control.py（:8300，仿真车间里的虚拟 PLC 调它）。
FROM debian:trixie-20251020
ARG OPENPLC_COMMIT=b5d41356dab4aeadca0dd7ca64ba542f870b595d
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates nodejs python3 sqlite3 procps \
    && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/thiagoralves/OpenPLC_v3.git /workdir && cd /workdir && git checkout "$OPENPLC_COMMIT"
WORKDIR /workdir
RUN ./install.sh docker && rm -rf /var/lib/apt/lists/*
# 从站轮询 20 ms、超时 200 ms；关掉不用的对外协议（Modbus 从站、EtherNet/IP、S7）
RUN sqlite3 webserver/openplc.db "update Settings set Value='20' where Key='Slave_polling'; update Settings set Value='200' where Key='Slave_timeout'; \
    update Settings set Value='disabled' where Key in ('Modbus_port','Enip_port','Dnp3_port'); update Settings set Value='false' where Key='snap7';"
COPY vplc/__init__.py vplc/openplc_st.py /opt/wq/vplc/
COPY vplc/js/ /opt/wq/vplc/js/
COPY openplc/control.py openplc/start.sh /opt/wq/openplc/
EXPOSE 8300
CMD ["sh", "/opt/wq/openplc/start.sh"]
