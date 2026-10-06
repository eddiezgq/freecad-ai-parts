<template>
  <div class="og">
    <div class="bar">
      <span class="small muted">关系图 · 单击展开一跳，双击进入</span>
      <label class="small">跳数
        <select v-model.number="depth" @change="reload"><option :value="1">1</option><option :value="2">2</option><option :value="3">3</option></select></label>
      <button class="btn ghost sm" title="重新排布" @click="relayout">排布</button>
    </div>
    <div ref="el" class="canvas" role="img" :aria-label="'关系图：' + nodes + ' 个对象、' + edges + ' 条关系'"></div>
    <div class="foot small muted">{{ nodes }} 个对象 · {{ edges }} 条关系<span v-if="truncated">（太多了，只画了一部分，可以从相关对象表里找）</span>
      <span v-if="hover" class="hover">{{ hover }}</span></div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import cytoscape from 'cytoscape';
import { getGraph, objPath, DOMAIN_COLOR } from '../lib/ont';

const props = defineProps({ type: String, objKey: String });
const router = useRouter();
const el = ref(null);
const depth = ref(1);
const nodes = ref(0);
const edges = ref(0);
const truncated = ref(false);
const hover = ref('');
let cy = null;
const expanded = new Set();

function short(s, n = 18) { return s && s.length > n ? s.slice(0, n - 1) + '…' : s; }

function add(g) {
  const els = [];
  for (const n of g.nodes) {
    if (cy.getElementById(n.id).length) continue;
    els.push({ group: 'nodes', data: { id: n.id, label: short(n.display), full: `${n.label} · ${n.display}`, type: n.type, key: n.key,
      color: DOMAIN_COLOR[n.domain] || '#888', root: n.root ? 1 : 0, hop: n.hop ?? 9, missing: n.missing ? 1 : 0 } });
  }
  for (const e of g.edges) {
    if (cy.getElementById(e.id).length) continue;
    els.push({ group: 'edges', data: { id: e.id, source: e.from, target: e.to, label: e.label } });
  }
  cy.add(els);
  truncated.value = truncated.value || g.truncated;
  nodes.value = cy.nodes().length;
  edges.value = cy.edges().length;
}

function relayout() {
  cy.layout({ name: 'concentric', concentric: (n) => 10 - n.data('hop'), levelWidth: () => 1, minNodeSpacing: 22,
    animate: false, padding: 30 }).run();
  if (cy.zoom() > 1.4) { cy.zoom(1.4); cy.center(); }     // 对象少时别放得太大
}

async function reload() {
  if (!cy) return;
  cy.elements().remove();
  expanded.clear();
  truncated.value = false;
  try {
    add(await getGraph(props.type, props.objKey, depth.value));
    expanded.add(props.type + '|' + props.objKey);
    relayout();
  } catch (e) { hover.value = e.message; }
}

onMounted(() => {
  cy = cytoscape({
    container: el.value,
    wheelSensitivity: 0.3,
    minZoom: 0.2,
    maxZoom: 3,
    style: [
      { selector: 'node', style: { 'background-color': 'data(color)', label: 'data(label)', 'font-size': 10, color: '#17212B',
        'text-valign': 'bottom', 'text-margin-y': 3, width: 16, height: 16, 'text-wrap': 'none',
        'text-background-color': '#fff', 'text-background-opacity': 0.75, 'text-background-padding': 1 } },
      { selector: 'node[root = 1]', style: { width: 28, height: 28, 'border-width': 3, 'border-color': '#F2B705', 'font-weight': 600, 'font-size': 12 } },
      { selector: 'node[missing = 1]', style: { 'background-opacity': 0.25, 'border-width': 1, 'border-style': 'dashed', 'border-color': '#888' } },
      { selector: 'edge', style: { width: 1.2, 'line-color': '#B9C1C8', 'target-arrow-color': '#B9C1C8', 'target-arrow-shape': 'triangle',
        'curve-style': 'bezier', 'arrow-scale': 0.7, label: 'data(label)', 'font-size': 8, color: '#6B7280', 'text-rotation': 'autorotate',
        'text-background-color': '#fff', 'text-background-opacity': 0.8, 'min-zoomed-font-size': 7 } },
      { selector: '.faded', style: { opacity: 0.15 } },
    ],
  });
  cy.on('tap', 'node', async (ev) => {
    const n = ev.target;
    const id = n.id();
    cy.elements().addClass('faded');
    n.closedNeighborhood().removeClass('faded');
    if (expanded.has(id)) return;
    expanded.add(id);
    try {
      const before = cy.nodes().length;
      add(await getGraph(n.data('type'), n.data('key'), 1));
      if (cy.nodes().length > before) {
        cy.nodes().forEach((x) => { if (x.data('hop') === 9 || x.data('hop') > n.data('hop') + 1) x.data('hop', Math.min(x.data('hop'), n.data('hop') + 1)); });
        relayout();
      }
      cy.elements().addClass('faded');
      n.closedNeighborhood().removeClass('faded');
    } catch (e) { hover.value = e.message; }
  });
  cy.on('tap', (ev) => { if (ev.target === cy) cy.elements().removeClass('faded'); });
  cy.on('dbltap', 'node', (ev) => router.push(objPath(ev.target.data('type'), ev.target.data('key'))));
  cy.on('mouseover', 'node', (ev) => { hover.value = ev.target.data('full'); });
  cy.on('mouseout', 'node', () => { hover.value = ''; });
  reload();
});
watch(() => [props.type, props.objKey], reload);
onBeforeUnmount(() => { if (cy) cy.destroy(); cy = null; });
</script>

<style scoped>
.og { display: flex; flex-direction: column; height: 100%; min-height: 420px; }
.bar { display: flex; gap: 10px; align-items: center; flex-shrink: 0; min-height: 28px; }
.bar label { margin-left: auto; display: flex; gap: 4px; align-items: center; }
.bar select { height: 26px; border: 1px solid var(--line); border-radius: 4px; }
.btn.sm { height: 26px; padding: 0 8px; }
.canvas { flex: 1; min-height: 380px; border: 1px solid var(--line-soft); border-radius: 8px; margin-top: 6px; background: #FBFCFA; }
.foot { margin-top: 4px; display: flex; gap: 8px; flex-shrink: 0; }
.hover { margin-left: auto; color: var(--ink); }
</style>
