// AI 工厂助手的对话状态（全站共用一个抽屉）。第 17 轮 D 期起后台是 AI 代理：回答带引用 [n]、数字核对、运行记录
import { reactive } from 'vue';
import { post } from './api';

export const ai = reactive({ open: false, busy: false, messages: [], error: null });

function push(r) {
  ai.messages.push({ role: 'assistant', content: r.answer, proposals: r.proposals || [], actions: r.actions || [], engine: r.engine,
    note: r.note, refs: r.refs || [], check: r.check || null, run_id: r.run_id, feedback: 0 });
}

export async function ask(text) {
  if (!text.trim() || ai.busy) return;
  ai.open = true;
  ai.error = null;
  ai.messages.push({ role: 'user', content: text.trim() });
  ai.busy = true;
  try {
    push(await post('/ai/chat', { messages: ai.messages.map(({ role, content }) => ({ role, content })) }));
  } catch (e) {
    ai.error = e.message;
  } finally {
    ai.busy = false;
  }
}

// 指挥台“让 AI 分析”
export async function analyze(aid, key) {
  if (ai.busy) return;
  ai.open = true;
  ai.error = null;
  ai.messages.push({ role: 'user', content: `分析异常 ${key}：原因、影响，以及怎么处理最划算` });
  ai.busy = true;
  try {
    push(await post(`/ont/anomalies/${aid}/analyze`, {}));
  } catch (e) {
    ai.error = e.message;
  } finally {
    ai.busy = false;
  }
}

export async function feedback(m, value) {
  if (!m.run_id) return;
  const v = m.feedback === value ? 0 : value;
  await post(`/ai/runs/${m.run_id}/feedback`, { value: v });
  m.feedback = v;
}

// 把回答切成：文字段、引用 [n]；数字核对没通过的行标出来
export function segments(m) {
  const bad = (m.check?.unverified || []).map((u) => u.sentence.replace(/\s+/g, ''));
  return (m.content || '').split('\n').map((line) => {
    const plain = line.replace(/\[\d{1,3}\]/g, '').replace(/\s+/g, '');
    const flagged = bad.some((s) => s && (plain.includes(s) || s.includes(plain)) && plain.length > 0);
    const parts = [];
    let last = 0;
    for (const x of line.matchAll(/\[(\d{1,3})\]/g)) {
      if (x.index > last) parts.push({ text: line.slice(last, x.index) });
      const n = Number(x[1]);
      parts.push({ ref: (m.refs || []).find((r) => r.n === n) || { n, missing: true } });
      last = x.index + x[0].length;
    }
    if (last < line.length) parts.push({ text: line.slice(last) });
    return { parts, flagged };
  });
}
