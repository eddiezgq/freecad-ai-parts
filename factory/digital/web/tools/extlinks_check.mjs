// 测试用（tests/test_extlinks.py）：stdin 读 [{entry, size}]，用网页同一个模块（src/lib/extlinks.js）拼外部库链接，stdout 写 JSON
import { bomLinks, extLinks, si } from '../src/lib/extlinks.js';
let buf = '';
for await (const c of process.stdin) buf += c;
const req = JSON.parse(buf);
process.stdout.write(JSON.stringify({ links: req.cases.map((c) => extLinks(c.entry, c.size)), si: req.si.map(([v, u]) => si(v, u)),
  bom: (req.bom || []).map((r) => bomLinks(r)) }));
