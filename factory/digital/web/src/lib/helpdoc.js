// 帮助正文（ADR-0065）：Markdown + 几种自定义块。自定义块写成围栏代码块，类型是 goto / anim / video / live / ask，
// 块内每行“键: 值”。正文里的 {{厂名}} {{公司}} {{币种}} 换成当前工厂的（ADR-0064）。
import MarkdownIt from 'markdown-it';

export const BLOCKS = ['goto', 'anim', 'video', 'live', 'ask'];
const md = new MarkdownIt({ html: false, linkify: true, breaks: false });
// 表格包一层，窄屏能横向滚动
md.renderer.rules.table_open = () => '<div class="tablewrap"><table>';
md.renderer.rules.table_close = () => '</table></div>';

const FENCE = /^```(goto|anim|video|live|ask)[ \t]*\n([\s\S]*?)^```[ \t]*$/gm;

function args(body) {
  const out = { _body: body.replace(/\n$/, '') };       // 原文（终端动画按行用）
  for (const line of body.split('\n')) {
    const m = line.match(/^\s*([a-z_]+)\s*:\s*(.*)$/);
    if (m) out[m[1]] = m[2].trim();
  }
  return out;
}

export function fill(text, vars) {
  return text.replace(/\{\{(厂名|公司|币种|班次)\}\}/g, (_, k) => vars[k] ?? '');
}

// 一章 → { title, lead, segments: [{ type:'md', html } | { type:'block', kind, args }], heads: [{ id, text }], text }
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
  const text = body.replace(FENCE, ' ').replace(/[#>*`|_\-[\]()]/g, ' ').replace(/\s+/g, ' ');
  return { title, lead, segments, heads, text };
}
