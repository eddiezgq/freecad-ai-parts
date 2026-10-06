export const pct = (v, d = 0) => (v === null || v === undefined ? '—' : (v * 100).toFixed(d) + '%');
export const pctSigned = (v, d = 1) => (v === null || v === undefined ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(d) + '%');
export const money = (v) => (v === null || v === undefined ? '—' : '$' + Number(v).toFixed(2));
export const short = (s) => (s || '').replace('示例·', '').split(' ')[0];
export const opShort = (s) => (s || '').split(' ')[0];
export function timeOf(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
}
export function kpiValue(k) {
  if (k.fmt === 'ratio') return `${k.value} / ${k.total}`;
  if (k.value === null || k.value === undefined) return '—';
  if (k.fmt === 'pct0') return pct(k.value, 0);
  if (k.fmt === 'pct1') return pct(k.value, 1);
  if (k.fmt === 'pct_signed') return pctSigned(k.value, 1);
  if (k.fmt === 'int') return `${k.value}${k.unit ? ' ' + k.unit : ''}`;
  return String(k.value);
}
export const STATE = {
  run: { label: '运行', color: 'var(--good)', bg: 'var(--good-bg)' },
  idle: { label: '空闲', color: 'var(--idle-ink)', bg: 'var(--idle-bg)' },
  setup: { label: '调整', color: 'var(--warn-ink)', bg: 'var(--warn-bg)' },
  down: { label: '停机', color: 'var(--bad)', bg: 'var(--bad-bg)' },
  fault: { label: '故障', color: 'var(--bad)', bg: 'var(--bad-bg)' },
};
export const TONE = { good: 'var(--good)', warn: 'var(--warn-ink)', bad: 'var(--bad)', mute: 'var(--muted)', info: 'var(--accent)' };
