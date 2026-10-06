// OpenPLC 兼容性检查用的“虚拟设备从站”（第 18 轮第 8 步）：node plant_server.mjs <设备> <秒> [端口]
// 虚拟设备（plants.js）和模拟操作工（shift.js 的 session）按真实时间每 10 ms 走一步，作为 Modbus TCP 从站：
//   离散输入 = 设备的数字量输入（%IXb.i → 序号 b*8+i），输入寄存器 = 模拟量输入（按 I/O 表顺序），
//   线圈 = PLC 的数字量输出（%QXb.i → 序号 b*8+i）。
// OpenPLC 运行时作为 Modbus 主站轮询它：读离散输入、输入寄存器，写线圈（OpenPLC 的从站设备映射到 %IX100.0、%IW100、%QX100.0 起）。
// 跑满规定的秒数后，把这段时间的工件、报警、危险动作汇总成 JSON 打到标准输出。
import net from "node:net";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const S = require("./shift.js");

const unit = process.argv[2] || "press";
const seconds = +(process.argv[3] || 60);
const port = +(process.argv[4] || 5020);
const sess = S.session({ unit, seed: 3, hours: 12, breakdowns: [], faultWait: 3000, noCurtain: true });   // 检查只有一分钟：故障灯亮 3 秒就复位；不模拟手伸进光幕（远程 I/O 有几十毫秒延迟，光幕靠硬接线安全回路）
const di = [], coils = new Array(64).fill(false), ir = [];
const map = { di: {}, coil: {}, ir: {} };
let nIr = 0;
for (const x of sess.io) {
  const m = /^%([IQ])([XW])(\d+)(?:\.(\d+))?$/.exec(x.addr);
  if (m[2] === "X") map[m[1] === "I" ? "di" : "coil"][x.name] = +m[3] * 8 + +(m[4] || 0);
  else if (m[1] === "I") map.ir[x.name] = nIr++;
}
let polls = 0, writes = 0;

// ---- Modbus TCP 从站（功能码 1、2、3、4、5、6、15、16）
function reply(sock, head, pdu) {
  const b = Buffer.alloc(7 + pdu.length);
  head.copy(b, 0, 0, 4); b.writeUInt16BE(pdu.length + 1, 4); b[6] = head[6]; pdu.copy(b, 7);
  sock.write(b);
}
function bits(arr, start, n) {
  const out = Buffer.alloc(Math.ceil(n / 8));
  for (let k = 0; k < n; k++) if (arr[start + k]) out[k >> 3] |= 1 << (k & 7);
  return out;
}
net.createServer((sock) => {
  let buf = Buffer.alloc(0);
  sock.on("data", (d) => {
    buf = Buffer.concat([buf, d]);
    while (buf.length >= 8) {
      const len = buf.readUInt16BE(4);
      if (buf.length < 6 + len) break;
      const head = buf.subarray(0, 7), fc = buf[7], body = buf.subarray(8, 6 + len);
      buf = buf.subarray(6 + len);
      const a = body.readUInt16BE(0), n = body.length >= 4 ? body.readUInt16BE(2) : 0;
      if (fc === 1 || fc === 2) {
        polls++;
        const src = fc === 1 ? coils : di;
        const bb = bits(src, a, n);
        reply(sock, head, Buffer.concat([Buffer.from([fc, bb.length]), bb]));
      } else if (fc === 3 || fc === 4) {
        const out = Buffer.alloc(2 + 2 * n); out[0] = fc; out[1] = 2 * n;
        for (let k = 0; k < n; k++) out.writeUInt16BE(((fc === 4 ? ir[a + k] : 0) || 0) & 0xffff, 2 + 2 * k);
        reply(sock, head, out);
      } else if (fc === 5) {
        coils[a] = body.readUInt16BE(2) === 0xff00; writes++;
        reply(sock, head, Buffer.concat([Buffer.from([fc]), body.subarray(0, 4)]));
      } else if (fc === 15) {
        for (let k = 0; k < n; k++) coils[a + k] = !!(body[5 + (k >> 3)] & (1 << (k & 7)));
        writes++;
        reply(sock, head, Buffer.concat([Buffer.from([fc]), body.subarray(0, 4)]));
      } else if (fc === 6 || fc === 16) {
        reply(sock, head, Buffer.concat([Buffer.from([fc]), body.subarray(0, 4)]));
      } else reply(sock, head, Buffer.from([fc | 0x80, 1]));
    }
  });
  sock.on("error", () => {});
}).listen(port, "127.0.0.1");

// ---- 真实时间推进：每 10 ms 一步（落后了就补步）。等 PLC 开始轮询（第一次写线圈）才开表，最多等 30 秒
const DT = 10;
let t0 = null, waitSince = Date.now();
let t = 0;
function refreshInputs() {
  const ins = sess.inputs(t);
  for (const [name, k] of Object.entries(map.di)) di[k] = !!ins[name];
  for (const [name, k] of Object.entries(map.ir)) ir[k] = ins[name] | 0;
}
refreshInputs();
const timer = setInterval(() => {
  if (t0 == null) {
    if (writes === 0 && Date.now() - waitSince < 30000) return;
    t0 = Date.now();
  }
  const now = Date.now() - t0;
  while (t + DT <= now) {
    const o = {};
    for (const [name, k] of Object.entries(map.coil)) o[name] = !!coils[k];
    sess.step(t, o, DT, null);
    t += DT;
    refreshInputs();
  }
  if (process.env.WQ_PLANT_DEBUG && Math.floor(now / 1000) !== Math.floor((now - 5) / 1000)) {
    const o = {}; for (const [name, k] of Object.entries(map.coil)) if (coils[k]) o[name] = 1;
    const i = {}; for (const [name, k] of Object.entries(map.di)) if (di[k]) i[name] = 1;
    process.stderr.write(`${Math.round(now / 1000)}s in ${Object.keys(i).join(",")} | out ${Object.keys(o).join(",")}\n`);
  }
  if (now >= seconds * 1000) {
    clearInterval(timer);
    const r = sess.finish(t);
    process.stdout.write(JSON.stringify({ ok: true, summary: r.summary, polls, writes,
      alarms: r.events.filter((e) => e.kind === "alarm").map((e) => e.code),
      cycles: r.events.filter((e) => e.kind === "cycle").slice(0, 50),
      hazards: r.events.filter((e) => e.kind === "hazard").slice(0, 20) }));
    process.exit(0);
  }
}, 5);
