#!/bin/sh
# OpenPLC 网页与运行时在后台，检查服务在前台（它退出容器就重启）
cd /workdir/webserver && /workdir/.venv/bin/python3 webserver.py > /tmp/openplc.log 2>&1 &
for i in $(seq 1 30); do python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/login', timeout=2)" 2>/dev/null && break; sleep 1; done
exec python3 /opt/wq/openplc/control.py
