<!-- 因果链图（第 17 轮 B 期）：原因在上、异常居中、影响在下；点边看依据，点节点看对象，双击进入 360 页 -->
<template>
  <div class="cg">
    <div ref="el" class="canvas" role="img" :aria-label="'因果链：' + (chain?.nodes?.length || 0) + ' 个对象'"></div>
    <div class="legend small muted">
      <span><i class="dot cause"></i>原因</span><span><i class="dot anomaly"></i>异常</span><span><i class="dot impact"></i>影响</span>
      <span class="r">单击边看依据 · 双击节点进入对象页<span v-if="chain?.truncated">（对象太多，只画了一部分）</span></span>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import cytoscape from 'cytoscape';
import { objPath, DOMAIN_COLOR } from '../lib/ont';

const props = defineProps({ chain: Object });
const emit = defineEmits(['edge', 'node']);
const router = useRouter();
const el = ref(null);
let cy = null;

function short(s, n = 16) { return s && s.length > n ? s.slice(0, n - 1) + '…' : s; }

// 从异常（或主体）出发按无向距离分层；原因放左边，影响放右边
function positions(nodes, edges) {
  const start = nodes.find((n) => n.role === 'anomaly') || nodes.find((n) => n.role === 'subject') || nodes[0];
  const adj = {};
  for (const e of edges) { (adj[e.from] ||= []).push(e.to); (adj[e.to] ||= []).push(e.from); }
  const depth = { [start.id]: 0 };
  const q = [start.id];
  while (q.length) {
    const x = q.shift();
    for (const y of adj[x] || []) if (depth[y] === undefined) { depth[y] = depth[x] + 1; q.push(y); }
  }
  const cols = {};
  for (const n of nodes) {
    const d = depth[n.id] ?? 1;
    const side = n.role === 'cause' ? -1 : n.role === 'anomaly' ? 0 : 1;
    const col = n.role === 'anomaly' ? 0 : side * Math.max(1, d);
    (cols[col] ||= []).push(n.id);
  }
  // 竖排：原因在上、异常居中、影响往下；同一层的对象横向排开，太多时折成几行
  const pos = {};
  let y = 0;
  const keys = Object.keys(cols).map(Number).sort((a, b) => a - b);
  for (const c of keys) {
    const ids = cols[c];
    const per = 6;
    for (let r = 0; r * per < ids.length; r += 1) {
      const row = ids.slice(r * per, (r + 1) * per);
      row.forEach((id, i) => { pos[id] = { x: (i - (row.length - 1) / 2) * 150 + (r % 2) * 40, y }; });
      y += 72;
    }
  }
  return pos;
}

function draw() {
  if (!cy) return;
  cy.elements().remove();
  const ch = props.chain;
  if (!ch || !ch.nodes?.length) return;
  const pos = positions(ch.nodes, ch.edges || []);
  cy.add(ch.nodes.map((n) => ({ group: 'nodes', position: pos[n.id], data: { id: n.id, label: short(n.hidden ? '原因待查' : n.display),
    type: n.type, key: n.key, role: n.role, hidden: n.hidden ? 1 : 0, color: n.role === 'anomaly' ? '#B42318' : (DOMAIN_COLOR[n.domain] || '#888'), kind: n.label } })));
  const seen = new Set();
  cy.add((ch.edges || []).filter((e) => { const k = e.from + '>' + e.to + '>' + e.label; if (seen.has(k)) return false; seen.add(k); return true; })
    .map((e, i) => ({ group: 'edges', data: { id: 'e' + i, source: e.from, target: e.to, label: short(e.label, 22), idx: ch.edges.indexOf(e) } })));
  cy.layout({ name: 'preset', fit: true, padding: 30 }).run();
  if (cy.zoom() > 1.2) { cy.zoom(1.2); cy.center(); }
}

onMounted(() => {
  cy = cytoscape({
    container: el.value, wheelSensitivity: 0.3, minZoom: 0.15, maxZoom: 2.5,
    style: [
      { selector: 'node', style: { 'background-color': 'data(color)', label: 'data(label)', 'font-size': 11, 'text-valign': 'bottom',
        'text-margin-y': 3, width: 18, height: 18, color: '#17212B', 'text-background-color': '#fff', 'text-background-opacity': 0.8,
        'text-background-padding': 1 } },
      { selector: 'node[role = "anomaly"]', style: { shape: 'diamond', width: 30, height: 30, 'font-weight': 600, 'font-size': 11 } },
      { selector: 'node[role = "cause"]', style: { 'border-width': 3, 'border-color': '#C98A12' } },
      { selector: 'node[role = "subject"]', style: { width: 24, height: 24, 'border-width': 3, 'border-color': '#F2B705' } },
      { selector: 'node[hidden = 1]', style: { 'background-color': '#fff', 'border-width': 2, 'border-style': 'dashed', 'border-color': '#9AA3AD', color: '#6B7280' } },
      { selector: 'edge', style: { width: 1.4, 'line-color': '#B9C1C8', 'target-arrow-color': '#B9C1C8', 'target-arrow-shape': 'triangle',
        'curve-style': 'bezier', 'arrow-scale': 0.8, label: 'data(label)', 'font-size': 8, color: '#5D6873', 'text-rotation': 'autorotate',
        'text-background-color': '#fff', 'text-background-opacity': 0.85, 'min-zoomed-font-size': 7 } },
      { selector: 'edge:selected', style: { 'line-color': '#0E5E6F', 'target-arrow-color': '#0E5E6F', width: 3 } },
    ],
  });
  cy.on('tap', 'edge', (ev) => emit('edge', props.chain.edges[ev.target.data('idx')]));
  cy.on('tap', 'node', (ev) => emit('node', props.chain.nodes.find((n) => n.id === ev.target.id())));
  cy.on('dbltap', 'node', (ev) => {
    const d = ev.target.data();
    if (!d.hidden && d.type && d.key && d.type !== 'Hidden') router.push(objPath(d.type, d.key));
  });
  draw();
});
watch(() => props.chain, draw);
onBeforeUnmount(() => { if (cy) cy.destroy(); cy = null; });
</script>

<style scoped>
.cg { display: flex; flex-direction: column; height: 100%; min-height: 460px; }
.canvas { flex: 1; min-height: 440px; border: 1px solid var(--line-soft); border-radius: 8px; background: #FBFCFA; }
.legend { display: flex; gap: 12px; margin-top: 4px; flex-wrap: wrap; align-items: center; }
.legend .r { margin-left: auto; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; vertical-align: -1px; background: #9AA3AD; }
.dot.cause { border: 2px solid #C98A12; background: #fff; }
.dot.anomaly { background: #B42318; transform: rotate(45deg); border-radius: 1px; }
.dot.impact { background: #0E5E6F; }
</style>
