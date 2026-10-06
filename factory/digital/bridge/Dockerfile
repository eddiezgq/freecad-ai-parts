# 问渠数字工厂：ERPNext ↔ 统一数据总线 桥接（Node-RED）
FROM nodered/node-red:4.1.1
COPY --chown=node-red:node-red settings.js flows.json /data/
COPY --chown=node-red:node-red lib/ /data/lib/
ENV NODE_RED_USER_DIR=/data
CMD ["--settings", "/data/settings.js"]
