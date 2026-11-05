// 测试用（tests/test_circuit.py）：stdin 读 {名: 网表}，用浏览器同一个引擎（src/lib/spice.js）跑，stdout 写 {名: meas}
import { run } from '../src/lib/spice.js';
let buf = '';
for await (const c of process.stdin) buf += c;
const nets = JSON.parse(buf);
const out = {};
for (const [k, net] of Object.entries(nets)) out[k] = (await run(net)).meas;
process.stdout.write(JSON.stringify(out));
process.exit(0);
