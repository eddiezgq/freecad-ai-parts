<template>
  <!-- 第 8 轮 Q2、Q3：网页看图——转动、剖切、测距、两版对比、在模型上点一处写批注 -->
  <div class="mv">
    <div class="tools">
      <div class="seg" role="group" :aria-label="t('显示')">
        <button v-for="o in viewOpts" :key="o.k" type="button" :class="{ on: view === o.k }" :disabled="o.dis" @click="view = o.k">{{ t(o.label) }}</button>
      </div>
      <label class="small">{{ t('剖切') }}
        <select v-model="clipAxis"><option value="">{{ t('不剖') }}</option><option value="x">X</option><option value="y">Y</option><option value="z">Z</option></select>
      </label>
      <input v-if="clipAxis" v-model.number="clipPos" type="range" min="0" max="1" step="0.005" :aria-label="t('剖切位置')">
      <div class="seg" role="group" :aria-label="t('点击做什么')">
        <button type="button" :class="{ on: tool === 'orbit' }" @click="setTool('orbit')">{{ t('转动') }}</button>
        <button type="button" :class="{ on: tool === 'measure' }" @click="setTool('measure')">{{ t('测距') }}</button>
        <button v-if="canPin" type="button" :class="{ on: tool === 'pin' }" @click="setTool('pin')">{{ t('点处批注') }}</button>
      </div>
    </div>
    <div ref="box" class="stage" :class="{ pick: tool !== 'orbit' }" @pointerdown="down" @pointerup="up">
      <div v-for="p in pinLabels" :key="p.n" class="pinlab" :class="{ done: p.resolved }" :style="{ left: p.x + 'px', top: p.y + 'px' }">{{ p.n }}</div>
      <div v-if="legend" class="legend small"><i class="r"></i>{{ t('新增或改动') }} <i class="b"></i>{{ t('去掉的') }} <i class="g"></i>{{ t('没变') }}</div>
    </div>
    <div class="note small muted">{{ note }}</div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { t, tk } from '../lib/i18n';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const props = defineProps({
  url: { type: String, required: true },          // 本版模型（glb）
  baseUrl: { type: String, default: '' },         // 现行版（对比用）
  diffUrl: { type: String, default: '' },         // 差异着色模型
  pins: { type: Array, default: () => [] },       // [{n, x, y, z, resolved}]（毫米）
  canPin: { type: Boolean, default: false },
});
const emit = defineEmits(['pick']);
const box = ref(null);
const view = ref('new');
const clipAxis = ref('');
const clipPos = ref(0.5);
const tool = ref('orbit');
const note = ref(t('正在读取模型…'));
const pinLabels = ref([]);
const viewOpts = computed(() => [
  { k: 'new', label: tk('本版') },
  { k: 'diff', label: tk('差异着色'), dis: !props.diffUrl },
  { k: 'overlay', label: tk('叠加现行版'), dis: !props.baseUrl },
]);
const legend = computed(() => view.value === 'diff');

let renderer, scene, camera, controls, raf, ro, root, bbox;
const models = {};
const loader = new GLTFLoader();
const clip = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0);
const MM = 1000;                                   // glb 是米，场景里按毫米

function load(key, url, my) {
  return new Promise((res) => {
    if (!url) { res(null); return; }
    loader.load(url, (g) => {
      const m = g.scene;
      m.scale.setScalar(MM);
      m.traverse((o) => {
        if (!o.isMesh) return;
        const mats = [].concat(o.material);
        mats.forEach((mt) => { mt.side = THREE.DoubleSide; mt.clippingPlanes = [clip]; mt.clipShadows = true; });
        if (key === 'base') o.material = new THREE.MeshStandardMaterial({ color: 0x3478dc, transparent: true, opacity: 0.25, depthWrite: false, clippingPlanes: [clip], side: THREE.DoubleSide });
        if (key === 'new' && !o.geometry.attributes.color) mats.forEach((mt) => { mt.color?.set(0xb8c2cc); mt.metalness = 0.4; mt.roughness = 0.45; });
        if (key === 'diff') mats.forEach((mt) => { mt.vertexColors = true; mt.transparent = true; });
      });
      if (my !== seq) { res(null); return; }                 // 已经有更新的一次读取
      models[key] = m;
      root.add(m);
      res(m);
    }, undefined, () => { note.value = t('模型读取失败'); res(null); });
  });
}

function show() {
  if (models.new) models.new.visible = view.value === 'new' || view.value === 'overlay';
  if (models.diff) models.diff.visible = view.value === 'diff';
  if (models.base) models.base.visible = view.value === 'overlay';
}

function applyClip() {
  if (!bbox || !clipAxis.value) { renderer.clippingPlanes = []; renderer.localClippingEnabled = false; return; }
  renderer.localClippingEnabled = true;
  const ax = { x: new THREE.Vector3(-1, 0, 0), y: new THREE.Vector3(0, -1, 0), z: new THREE.Vector3(0, 0, -1) }[clipAxis.value];
  const lo = bbox.min[clipAxis.value], hi = bbox.max[clipAxis.value];
  clip.normal.copy(ax);
  clip.constant = lo + (hi - lo) * clipPos.value;
}

// ---- 点选：测距、批注
const ray = new THREE.Raycaster();
let downAt = null, measurePts = [], measureObj = null;
function hit(ev) {
  const r = box.value.getBoundingClientRect();
  const p = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(p, camera);
  const target = models[view.value === 'diff' ? 'diff' : 'new'];
  if (!target) return null;
  const hits = ray.intersectObject(target, true).filter((h) => !clipAxis.value || clip.distanceToPoint(h.point) >= 0);
  return hits[0]?.point || null;
}
function down(ev) { downAt = [ev.clientX, ev.clientY]; }
function up(ev) {
  if (tool.value === 'orbit' || !downAt || Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 4) return;
  const p = hit(ev);
  if (!p) return;
  if (tool.value === 'pin') { emit('pick', { x: +p.x.toFixed(3), y: +p.y.toFixed(3), z: +p.z.toFixed(3) }); return; }
  measurePts.push(p.clone());
  if (measurePts.length === 1) { note.value = t('已选第一点，再点第二点'); drawMeasure(); return; }
  const d = measurePts[0].distanceTo(measurePts[1]);
  drawMeasure();
  note.value = t('两点距离 {d} mm（ΔX {x}，ΔY {y}，ΔZ {z}）· 再点开始新的测量', { d: d.toFixed(2), x: Math.abs(measurePts[1].x - measurePts[0].x).toFixed(2), y: Math.abs(measurePts[1].y - measurePts[0].y).toFixed(2), z: Math.abs(measurePts[1].z - measurePts[0].z).toFixed(2) });
  measurePts = [];
}
function drawMeasure() {
  if (measureObj) { scene.remove(measureObj); measureObj = null; }
  const pts = measurePts.length ? measurePts : [];
  if (!pts.length) return;
  const g = new THREE.Group();
  const s = Math.max(bboxSize() * 0.008, 0.2);
  pts.forEach((p) => { const m = new THREE.Mesh(new THREE.SphereGeometry(s), new THREE.MeshBasicMaterial({ color: 0xd64541 })); m.position.copy(p); g.add(m); });
  if (pts.length === 2) g.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0xd64541 })));
  measureObj = g; scene.add(g);
}
function setTool(k) { tool.value = k; measurePts = []; drawMeasure(); note.value = t({ orbit: tk('拖动旋转 · 滚轮缩放 · 右键平移'), measure: tk('点模型上两点量距离（毫米）'), pin: tk('点模型上要批注的位置') }[k]); }

// ---- 批注编号跟着模型走
let pinObjs = null;
function drawPins() {
  if (pinObjs) scene.remove(pinObjs);
  pinObjs = new THREE.Group();
  const s = Math.max(bboxSize() * 0.01, 0.3);
  for (const p of props.pins) {
    const m = new THREE.Mesh(new THREE.SphereGeometry(s), new THREE.MeshBasicMaterial({ color: p.resolved ? 0x2e8b57 : 0xe0a100 }));
    m.position.set(p.x, p.y, p.z); m.userData = p; pinObjs.add(m);
  }
  scene.add(pinObjs);
}
function placeLabels() {
  if (!pinObjs || !box.value) return;
  const w = box.value.clientWidth, h = box.value.clientHeight;
  pinLabels.value = pinObjs.children.map((m) => {
    const v = m.position.clone().project(camera);
    return { n: m.userData.n, resolved: m.userData.resolved, x: (v.x + 1) / 2 * w + 8, y: (1 - v.y) / 2 * h - 18, vis: v.z < 1 };
  }).filter((p) => p.vis);
}

function bboxSize() { return bbox ? bbox.getSize(new THREE.Vector3()).length() : 100; }
function fit() {
  bbox = new THREE.Box3().setFromObject(models.new || models.diff);
  const c = bbox.getCenter(new THREE.Vector3()), r = bboxSize();
  camera.near = r / 500; camera.far = r * 50; camera.updateProjectionMatrix();
  camera.position.copy(c).add(new THREE.Vector3(r * 0.85, r * 0.6, r * 1.1));
  controls.target.copy(c);
  const s = bbox.getSize(new THREE.Vector3());
  note.value = t('拖动旋转 · 滚轮缩放 · 外形 {x} × {y} × {z} mm', { x: s.x.toFixed(1), y: s.y.toFixed(1), z: s.z.toFixed(1) });
}
function resize() {
  if (!renderer) return;
  const w = box.value.clientWidth, h = box.value.clientHeight;
  renderer.setSize(w, h); camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix();
}

let seq = 0;
async function loadAll() {
  const my = ++seq;
  root.clear();
  for (const k of Object.keys(models)) delete models[k];
  await Promise.all([load('new', props.url, my), load('diff', props.diffUrl, my), load('base', props.baseUrl, my)]);
  if (my !== seq) return;
  if (models.new || models.diff) fit();
  show(); applyClip(); drawPins();
}

onMounted(() => {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  box.value.prepend(renderer.domElement);
  scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a949c, 1.5));
  const d = new THREE.DirectionalLight(0xffffff, 1.5); d.position.set(3, 5, 4); scene.add(d);
  root = new THREE.Group(); scene.add(root);
  camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1e5);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  ro = new ResizeObserver(resize); ro.observe(box.value); resize();
  const loop = () => { controls.update(); renderer.render(scene, camera); placeLabels(); raf = requestAnimationFrame(loop); };
  loop();
  loadAll();
});
watch(view, show);
watch([clipAxis, clipPos], applyClip);
watch(() => [props.url, props.baseUrl, props.diffUrl].join('|'), loadAll);   // 只在地址真变了时重读
watch(() => JSON.stringify(props.pins), drawPins);
onUnmounted(() => { cancelAnimationFrame(raf); ro?.disconnect(); renderer?.dispose(); });
</script>

<style scoped>
.mv { display: flex; flex-direction: column; gap: 8px; }
.tools { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.seg button { border: 0; background: #fff; padding: 6px 10px; cursor: pointer; font-size: 13px; }
.seg button.on { background: var(--accent-bg); font-weight: 600; }
.seg button:disabled { opacity: .45; cursor: not-allowed; }
.stage { position: relative; height: 460px; border-radius: 8px; background: linear-gradient(#f4f6f8, #e1e6ea); overflow: hidden; }
.stage.pick { cursor: crosshair; }
.pinlab { position: absolute; background: #e0a100; color: #fff; font-size: 12px; font-weight: 700; border-radius: 10px; padding: 1px 7px; pointer-events: none; }
.pinlab.done { background: #2e8b57; }
.legend { position: absolute; left: 10px; bottom: 10px; background: rgba(255,255,255,.85); border-radius: 6px; padding: 4px 8px; display: flex; gap: 6px; align-items: center; }
.legend i { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
.legend .r { background: #d64541; } .legend .b { background: #3478dc; } .legend .g { background: #bec4ca; }
@media (max-width: 700px) { .stage { height: 320px; } }
</style>
