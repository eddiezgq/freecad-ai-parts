// 第 92 轮：WQ-ENCIF 的 JS 行为模型逐拍跑测试激励（标准输入：{"cases": {名字: [激励字…]}}），输出每拍 [cnt, idx, status, miso]
import { run } from '../web/src/lib/encif.js';
let buf = '';
process.stdin.on('data', (d) => { buf += d; });
process.stdin.on('end', () => {
  const inp = JSON.parse(buf);
  const out = {};
  for (const [k, words] of Object.entries(inp.cases)) out[k] = run(words);
  process.stdout.write(JSON.stringify(out));
});
