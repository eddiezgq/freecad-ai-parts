// 帮助正文（ADR-0065）：Markdown + 几种自定义块。自定义块写成围栏代码块，类型是 goto / anim / video / live / ask，
// 第 30 轮 §八 加 lab（嵌虚拟实验）/ try（当场动手）/ quiz（你来选）。块内每行“键: 值”；键后面空着、下面几行“  - 项”的是列表
// （quiz 的 options）。写法见 factory/digital/docs/帮助编写/块的写法.md。正文里的 {{厂名}} {{公司}} {{币种}} 换成当前工厂的（ADR-0064）。
import MarkdownIt from 'markdown-it';

export const BLOCKS = ['goto', 'anim', 'video', 'live', 'ask', 'lab', 'try', 'quiz'];
const md = new MarkdownIt({ html: false, linkify: true, breaks: false });
// 表格包一层，窄屏能横向滚动
md.renderer.rules.table_open = () => '<div class="tablewrap"><table>';
md.renderer.rules.table_close = () => '</table></div>';

const FENCE = new RegExp('^```(' + BLOCKS.join('|') + ')[ \\t]*\\n([\\s\\S]*?)^```[ \\t]*$', 'gm');

export function args(body) {
  const out = { _body: body.replace(/\n$/, '') };       // 原文（终端动画按行用）
  let list = null;                                      // 上一个键后面空着：下面的“- 项”归它
  for (const line of body.split('\n')) {
    const li = list && line.match(/^\s+-\s+(.*)$/);
    if (li) { out[list].push(li[1].trim()); continue; }
    const m = line.match(/^\s*([a-z_]+)\s*:\s*(.*)$/);
    if (m) {
      out[m[1]] = m[2].trim();
      list = m[2].trim() ? null : m[1];
      if (list) out[list] = [];
    }
  }
  return out;
}

export function fill(text, vars) {
  return text.replace(/\{\{(厂名|公司|币种|班次)\}\}/g, (_, k) => vars[k] ?? '');
}

// 第 30 轮 §八 8-3：正文里单独一行“:::查表”以后的内容（规则表、谁做什么、方案表）收进一个折叠的“查表”，正文只留旁白和互动
export const FOLD = /^:::查表[ \t]*$/m;

// 一章 → { title, lead, segments: [{ type:'md', html, fold? } | { type:'block', kind, args, fold? }], heads: [{ id, text }], text }
export function parse(src, vars = {}) {
  const lines = fill(src, vars).replace(/\r\n/g, '\n');
  const title = (lines.match(/^# (.+)$/m) || [])[1] || '';
  const lead = (lines.match(/^> (.+)$/m) || [])[1] || '';
  const body = lines.replace(/^# .+\n/m, '').replace(/^> .+\n/m, '');
  const segments = [];
  let last = 0;
  for (const m of body.matchAll(FENCE)) {
    if (m.index > last) segments.push({ type: 'md', src: body.slice(last, m.index) });
    segments.push({ type: 'block', kind: m[1], args: args(m[2]) });
    last = m.index + m[0].length;
  }
  if (last < body.length) segments.push({ type: 'md', src: body.slice(last) });
  // 折叠线：所在的那段 md 一分为二，后面的都标 fold
  for (let i = 0; i < segments.length; i++) {
    const s = segments[i];
    const m = s.type === 'md' && s.src.match(FOLD);
    if (!m) continue;
    const after = { type: 'md', src: s.src.slice(m.index + m[0].length), fold: true };
    s.src = s.src.slice(0, m.index);
    segments.splice(i + 1, 0, after);
    for (let k = i + 1; k < segments.length; k++) segments[k].fold = true;
    break;
  }
  const heads = [];
  let n = 0;
  for (const s of segments) {
    if (s.type !== 'md') continue;
    // 中文段落里的换行不该变成空格：两边都是中日韩字符或全角标点时直接接上
    s.html = md.render(s.src.replace(/([\u3000-\u9fff\uff00-\uffef])\n(?=[\u3000-\u9fff\uff00-\uffef])/g, '$1')).replace(/<h2>(.*?)<\/h2>/g, (_, t) => {
      const id = 's' + (++n);
      heads.push({ id, text: t.replace(/<[^>]+>/g, '') });
      return `<h2 id="${id}">${t}</h2>`;
    });
  }
  const text = body.replace(FOLD, ' ').replace(FENCE, ' ').replace(/[#>*`|_\-[\]()]/g, ' ').replace(/\s+/g, ' ');
  return { title, lead, segments, heads, text };
}
