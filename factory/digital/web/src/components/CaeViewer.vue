<template>
  <!-- 第 11 轮：设置时点选面（每个面单独着色），结果时显示应力 / 位移云图、变形、最大值位置、点哪查哪 -->
  <div class="cv">
    <div ref="box" class="stage" :class="{ pick: picking }" @pointerdown="down" @pointerup="up" @pointermove="move" @pointerleave="tip = ''">
      <div v-if="tip" class="tip small" :style="{ left: tipX + 'px', top: tipY + 'px' }">{{ tip }}</div>
      <div v-if="surface" class="cbar">
        <div class="cbar-max mono">{{ field === 'life' ? fmtH(lifeH(range[1])) : fmt(range[1]) }}</div>
        <div class="cbar-grad" :style="{ background: grad }"></div>
        <div class="cbar-min mono">{{ field === 'life' ? '≥ ' + fmtH(lifeH(range[0])) : fmt(range[0]) }}</div>
        <div class="cbar-unit">{{ field === 'vm' ? 'MPa' : field === 'u' ? 'mm' : field === 'temp' ? '℃' : '疲劳寿命' }}</div>
      </div>
      <slot />
    </div>
    <div class="tools small">
      <label>剖切
        <select v-model="clipAxis"><option value="">不剖</option><option value="x">X</option><option value="y">Y</option><option value="z">Z</option></select>
      </label>
      <input v-if="clipAxis" v-model.number="clipPos" type="range" min="0" max="1" step="0.005" aria-label="剖切位置">
      <button type="button" class="link" @click="fit">回到全景</button>
      <span class="muted">{{ note }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { turbo, turboCss } from '../lib/cae';

const props = defineProps({
  glbUrl: { type: String, default: '' },              // 设置时：按面分开的模型
  faces: { type: Array, default: () => [] },          // 面清单（提示用）
  faceColors: { type: Object, default: () => ({}) },  // {面编号: '#rrggbb'}
  picking: { type: Boolean, default: false },
  surface: { type: Object, default: null },           // 结果：fetchSurface() 的返回
  field: { type: String, default: 'vm' },             // vm 应力 / u 位移
  deform: { type: Number, default: 0 },               // 变形放大倍数（0 = 不变形）
  marks: { type: Array, default: () => [] },          // [{at: [x,y,z], label, color}]
  peaks: { type: Object, default: () => ({}) },
  blockSeconds: { type: Number, default: 1 },         // 疲劳：一块载荷谱的秒数（色标换算成小时）       // {vm, u}：全部节点（含内部、边中点）的最大值，色标上限与统计一致
});
const emit = defineEmits(['pick']);
const box = ref(null);
const clipAxis = ref('');
const clipPos = ref(0.5);
const note = ref('拖动旋转 · 滚轮缩放 · 右键平移');
const tip = ref(''), tipX = ref(0), tipY = ref(0);
const grad = turboCss();
// 疲劳（life）：按每块损伤的对数着色，红 = 损伤最大（寿命最短），显示 6 个数量级
const fieldArr = () => (!props.surface ? null : props.field === 'vm' ? props.surface.vm : props.field === 'u' ? props.surface.umag
  : props.field === 'temp' ? props.surface.temp : props.surface.lgD);
const range = computed(() => {
  const a = fieldArr();
  if (!a || !a.length) return [0, 1];
  let lo = Infinity, hi = -Infinity;
  for (const v of a) { if (v < lo) lo = v; if (v > hi) hi = v; }
  if (props.field === 'life') return [hi - 6, hi];
  hi = Math.max(hi, props.peaks[props.field] || 0);
  return [lo, hi > lo ? hi : lo + 1];
});
const lifeH = (lg) => (props.blockSeconds / 10 ** lg) / 3600;
const fmtH = (h) => (h >= 1e5 ? h.toExponential(1) : h >= 10 ? h.toFixed(0) : h.toPrecision(2)) + ' h';
const fmt = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(1) : v.toPrecision(3));

let renderer, scene, camera, controls, raf, ro, root, bbox, markObjs;
const faceMeshes = new Map();
let resultMesh = null, resultEdges = null;
const clip = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0);
const loader = new GLTFLoader();
const faceById = computed(() => Object.fromEntries(props.faces.map((f) => [f.id, f])));
const BASE = 0xb9c2ca;

// ---------------------------------------------------------------- 设置模型（按面）
let seq = 0;
function clearRoot() {
  root.clear(); faceMeshes.clear(); resultMesh = null; resultEdges = null;
}
function loadGlb() {
  if (!props.glbUrl || props.surface) return;
  const my = ++seq;
  note.value = '正在读取模型…';
  loader.load(props.glbUrl, (g) => {
    if (my !== seq || props.surface) return;
    clearRoot();
    const m = g.scene;
    m.scale.setScalar(1000);                                     // glb 是米
    m.traverse((o) => {
      if (!o.isMesh) return;
      let p = o, id = null;
      while (p && id === null) { const r = /^f(\d+)$/.exec(p.name || ''); if (r) id = +r[1]; p = p.parent; }
      o.material = new THREE.MeshStandardMaterial({ color: BASE, metalness: 0.25, roughness: 0.55, side: THREE.DoubleSide,
        clippingPlanes: [clip], polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
      if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals();   // gmsh 出的模型不带法向
      o.userData.face = id;
      if (id !== null) faceMeshes.set(id, o);
      const e = new THREE.LineSegments(new THREE.EdgesGeometry(o.geometry, 35), new THREE.LineBasicMaterial({ color: 0x55606a, clippingPlanes: [clip] }));
      o.add(e);
    });
    root.add(m);
    paintFaces();
    fit();
  }, undefined, () => { note.value = '模型读取失败'; });
}
function paintFaces() {
  for (const [id, mesh] of faceMeshes) {
    const c = props.faceColors[id];
    mesh.material.color.set(c || BASE);
    mesh.material.emissive.set(id === hoverId ? 0x333333 : 0x000000);
  }
}

// ---------------------------------------------------------------- 结果云图
function buildResult() {
  const s = props.surface;
  if (!s) return;
  seq++;
  clearRoot();
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(s.nv * 3), 3));
  g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(s.nv * 3), 3));
  g.setIndex(new THREE.BufferAttribute(s.triangles, 1));
  resultMesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0.05, roughness: 0.7,
    side: THREE.DoubleSide, clippingPlanes: [clip], polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }));
  root.add(resultMesh);
  updateResult();
  fit();
}
function updateResult() {
  const s = props.surface;
  if (!s || !resultMesh) return;
  const g = resultMesh.geometry;
  const pos = g.attributes.position.array, col = g.attributes.color.array;
  const val = fieldArr();
  const [lo, hi] = range.value;
  for (let i = 0; i < s.nv; i++) {
    for (let k = 0; k < 3; k++) pos[3 * i + k] = s.positions[3 * i + k] + props.deform * s.u[3 * i + k];
    const c = turbo((val[i] - lo) / (hi - lo));
    col[3 * i] = c[0]; col[3 * i + 1] = c[1]; col[3 * i + 2] = c[2];
  }
  g.attributes.position.needsUpdate = true;
  g.attributes.color.needsUpdate = true;
  g.computeVertexNormals();
  g.computeBoundingSphere();
  if (resultEdges) { root.remove(resultEdges); resultEdges.geometry.dispose(); }
  resultEdges = new THREE.LineSegments(new THREE.EdgesGeometry(g, 35), new THREE.LineBasicMaterial({ color: 0x2b3238, transparent: true, opacity: 0.45, clippingPlanes: [clip] }));
  root.add(resultEdges);
  drawMarks();
}

// ---------------------------------------------------------------- 标记（最大值位置）
function drawMarks() {
  if (markObjs) scene.remove(markObjs);
  markObjs = new THREE.Group();
  const r = Math.max(bboxSize() * 0.012, 0.3);
  for (const m of props.marks) {
    const s = new THREE.Mesh(new THREE.SphereGeometry(r, 16, 12), new THREE.MeshBasicMaterial({ color: m.color || 0xff00aa, depthTest: false }));
    s.position.set(...m.at); s.renderOrder = 10; markObjs.add(s);
  }
  scene.add(markObjs);
}

// ---------------------------------------------------------------- 视图
function bboxSize() { return bbox ? bbox.getSize(new THREE.Vector3()).length() : 100; }
function fit() {
  if (!root.children.length) return;
  bbox = new THREE.Box3().setFromObject(root);
  const c = bbox.getCenter(new THREE.Vector3()), r = bboxSize();
  camera.near = r / 500; camera.far = r * 50; camera.updateProjectionMatrix();
  camera.position.copy(c).add(new THREE.Vector3(r * 0.9, r * 0.55, r * 0.9));
  controls.target.copy(c);
  const s = bbox.getSize(new THREE.Vector3());
  note.value = `拖动旋转 · 滚轮缩放 · 右键平移 · 外形 ${s.x.toFixed(1)} × ${s.y.toFixed(1)} × ${s.z.toFixed(1)} mm`;
  applyClip();
}
function applyClip() {
  if (!bbox || !clipAxis.value) { renderer.localClippingEnabled = false; return; }
  renderer.localClippingEnabled = true;
  const ax = { x: new THREE.Vector3(-1, 0, 0), y: new THREE.Vector3(0, -1, 0), z: new THREE.Vector3(0, 0, -1) }[clipAxis.value];
  const lo = bbox.min[clipAxis.value], hi = bbox.max[clipAxis.value];
  clip.normal.copy(ax);
  clip.constant = lo + (hi - lo) * clipPos.value;
}
function resize() {
  if (!renderer) return;
  const w = box.value.clientWidth, h = box.value.clientHeight;
  renderer.setSize(w, h); camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix();
}

// ---------------------------------------------------------------- 点选、悬停
const ray = new THREE.Raycaster();
let downAt = null, hoverId = null;
function hit(ev) {
  const r = box.value.getBoundingClientRect();
  const p = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(p, camera);
  const objs = resultMesh ? [resultMesh] : [...faceMeshes.values()];
  return ray.intersectObjects(objs, false).filter((h) => !clipAxis.value || clip.distanceToPoint(h.point) >= 0)[0] || null;
}
function nearestValue(h) {
  const s = props.surface, f = h.face;
  let best = f.a, bd = Infinity;
  for (const i of [f.a, f.b, f.c]) {
    const d = Math.hypot(s.positions[3 * i] - h.point.x, s.positions[3 * i + 1] - h.point.y, s.positions[3 * i + 2] - h.point.z);
    if (d < bd) { bd = d; best = i; }
  }
  return best;
}
function down(ev) { downAt = [ev.clientX, ev.clientY]; }
function up(ev) {
  if (!downAt || Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 4) return;
  const h = hit(ev);
  if (!h) return;
  if (!resultMesh && props.picking && h.object.userData.face != null) emit('pick', h.object.userData.face);
}
let moveT = 0;
function move(ev) {
  const now = performance.now();
  if (now - moveT < 40) return;
  moveT = now;
  const h = hit(ev);
  const r = box.value.getBoundingClientRect();
  tipX.value = ev.clientX - r.left + 14; tipY.value = ev.clientY - r.top + 10;
  let id = null;
  if (!h) tip.value = '';
  else if (resultMesh) {
    const i = nearestValue(h), s = props.surface;
    const fid = s.faceOf[h.faceIndex];
    tip.value = `面 ${fid} · ` + (s.temp ? `温度 ${s.temp[i].toFixed(1)} ℃` + (s.thermoOnly ? '' : ' · ') : '')
      + (s.thermoOnly ? '' : `应力 ${s.vm[i].toFixed(1)} MPa · 位移 ${s.umag[i].toPrecision(3)} mm`)
      + (s.lgD && props.field === 'life' ? ` · 寿命 ${s.lgD[i] < -29 ? '无限' : fmtH(lifeH(s.lgD[i]))}` : '');
  } else {
    id = h.object.userData.face;
    const f = faceById.value[id];
    tip.value = f ? `面 ${f.id} · ${{ plane: '平面', cylinder: '圆柱面', cone: '圆锥面' }[f.kind] || '曲面'}${f.radius_mm ? ' Ø' + (2 * f.radius_mm).toFixed(1) : ''} · ${f.area_mm2.toFixed(1)} mm²${props.picking ? ' · 点击选中 / 取消' : ''}` : '';
  }
  if (id !== hoverId) { hoverId = id; paintFaces(); }
}

onMounted(() => {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });   // 报告要截图
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  box.value.prepend(renderer.domElement);
  scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a949c, 1.6));
  const d = new THREE.DirectionalLight(0xffffff, 1.4); d.position.set(3, 5, 4); scene.add(d);
  root = new THREE.Group(); scene.add(root);
  camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1e5);
  camera.up.set(0, 1, 0);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  ro = new ResizeObserver(resize); ro.observe(box.value); resize();
  const loop = () => { controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(loop); };
  loop();
  if (props.surface) buildResult(); else loadGlb();
});
watch(() => props.glbUrl, () => { if (!props.surface) loadGlb(); });
watch(() => props.surface, (s) => { if (s) buildResult(); else loadGlb(); });
watch(() => [props.field, props.deform, props.surface?.lgD], updateResult);
watch(() => JSON.stringify(props.faceColors), paintFaces);
watch(() => JSON.stringify(props.marks), drawMarks);
watch([clipAxis, clipPos], applyClip);
onUnmounted(() => { cancelAnimationFrame(raf); ro?.disconnect(); renderer?.dispose(); });

defineExpose({ snapshot: () => renderer?.domElement.toDataURL('image/png') });
</script>

<style scoped>
.cv { display: flex; flex-direction: column; gap: 6px; }
.stage { position: relative; height: 520px; border-radius: 8px; background: linear-gradient(#f6f7f8, #dfe4e8); overflow: hidden; }
.stage.pick { cursor: pointer; }
.tip { position: absolute; background: rgba(23, 33, 43, .88); color: #fff; padding: 3px 8px; border-radius: 5px; pointer-events: none; white-space: nowrap; z-index: 2; }
.cbar { position: absolute; right: 14px; top: 16px; bottom: 40px; width: 96px; display: flex; flex-direction: column; align-items: flex-start; pointer-events: none; }
.cbar-grad { flex: 1; width: 16px; border-radius: 3px; border: 1px solid rgba(0,0,0,.2); }
.cbar-max, .cbar-min { white-space: nowrap; font-size: 11px; background: rgba(255,255,255,.8); padding: 0 3px; border-radius: 3px; margin: 2px 0; }
.cbar-unit { font-size: 11px; color: var(--muted); }
.tools { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.tools select { height: 26px; border: 1px solid var(--line); border-radius: 5px; }
.link { border: 0; background: none; color: var(--accent); cursor: pointer; padding: 0; }
@media (max-width: 700px) { .stage { height: 360px; } }
</style>
