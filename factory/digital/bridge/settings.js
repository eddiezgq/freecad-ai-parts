// Node-RED 设置（问渠数字工厂桥接）。环境变量见 README：WQ_ERPNEXT_API、WQ_ERP_API_KEY、WQ_ERP_API_SECRET、
// WQ_MQTT_HOST、WQ_MQTT_PORT、WQ_MODE、WQ_TZ、WQ_HUB_PUBLIC_URL。
const fs = require('fs');
const path = require('path');
const { ERP } = require('./lib/erp');
const wq = require('./lib/wq');

// 服务器版（第 3 轮 D5）：总线要账号。Node-RED 的账号只能放在凭据文件里，所以启动时按环境变量
// WQ_MQTT_USER / WQ_MQTT_PASSWORD 写出不加密的 flows_cred.json（文件只在容器里，不进仓库）。
// Node-RED 在“用户目录”里找凭据文件（容器里是 /data）。
const USER_DIR = process.env.NODE_RED_USER_DIR || path.join(__dirname, '.node-red');
const MQTT_USER = process.env.WQ_MQTT_USER || '';
if (MQTT_USER) {
  fs.mkdirSync(USER_DIR, { recursive: true });
  fs.writeFileSync(path.join(USER_DIR, 'flows_cred.json'),
    JSON.stringify({ 'wq-broker': { user: MQTT_USER, password: process.env.WQ_MQTT_PASSWORD || '' } }));
}

module.exports = {
  uiPort: process.env.PORT || 1880,
  flowFile: path.join(__dirname, 'flows.json'),
  userDir: USER_DIR,
  credentialSecret: MQTT_USER ? false : (process.env.NODE_RED_CREDENTIAL_SECRET || 'wq-digital-factory'),
  flowFilePretty: true,
  functionGlobalContext: { wqErp: new ERP(), wq },
  logging: { console: { level: 'info', metrics: false, audit: false } },
  editorTheme: { projects: { enabled: false }, page: { title: '问渠数字工厂 · 桥接 Node-RED' } },
};
