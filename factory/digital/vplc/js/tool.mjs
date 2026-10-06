// 数字工厂虚拟 PLC 的计算工具（第 18 轮第 8 步）：node tool.mjs < job.json > result.json
// job.op = "shift"  { program: {st}, unit: "press" | "sorter", hours, seed, cycle } → 一个班次的事件表与汇总（shift.js）
//        = "import" { xml, unit }                                                 → { st }（PLCopen XML → ST）
//        = "check"  { st, unit }                                                  → { ok, error, review }（能否编译、程序检查）
// plc.js、plants.js、shift.js 是学习平台 services/gateway/app/production/labkit/ 里同名文件的副本（测试核对两边一致）。
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const require = createRequire(import.meta.url);
const P = require("./plc.js");
const W = require("./plants.js");
const S = require("./shift.js");
const PLANT = { press: "press", sorter: "sorter" };

const job = JSON.parse(readFileSync(0, "utf8"));
let out;
try {
  const plant = job.unit && PLANT[job.unit] ? W[PLANT[job.unit]]() : null;
  if (job.op === "shift") out = S.run(job);
  else if (job.op === "import") out = { ok: true, st: P.importXml(job.xml, { io: plant ? plant.io : [] }) };
  else if (job.op === "check") {
    const io = plant ? plant.io : [];
    try { new P.Runtime({ io, st: job.st }); out = { ok: true, error: null, review: P.review({ st: job.st }, io) }; }
    catch (e) { out = { ok: false, error: (e.line ? `第 ${e.line} 行：` : "") + e.message, review: [] }; }
  } else throw new Error("unknown op " + job.op);
} catch (e) {
  out = { ok: false, error: String(e.message || e) };
}
process.stdout.write(JSON.stringify(out));
