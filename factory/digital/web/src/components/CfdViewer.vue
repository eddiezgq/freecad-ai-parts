<template>
  <!-- 第 16 轮：流体分析结果——零件表面按压力或散热系数着色，流线按速度着色，水平截面上的速度云图；鼠标停上去看数 -->
  <div class="fv">
    <div ref="box" class="stage" @pointermove="move" @pointerleave="tip = ''">
      <div v-if="tip" class="tip small" :style="{ left: tipX + 'px', top: tipY + 'px' }">{{ tip }}</div>
      <div class="cbar">
        <div class="mono">{{ fmt(range[1]) }}</div>
        <div class="grad" :style="{ background: turboCss() }"></div>
        <div class="mono">{{ fmt(range[0]) }}</div>
        <div class="small">{{ UNIT[field] }}</div>
      </div>
    </div>
    <div class="tools small">
      <label>表面 <select v-model="field"><option value="p">压力</option><option v-if="hasH" value="h">散热系数 h</option></select></label>
      <label class="chk"><input v-model="showLines" type="checkbox"> 流线</label>
      <label class="chk"><input v-model="showSlice" type="checkbox"> 速度截面</label>
      <button type="button" class="link" @click="fit">回到全景</button>
      <span class="muted">拖动旋转 · 滚轮缩放 · 右键平移</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { turbo, turboCss } from '../lib/cae';

const props = defineProps({ surface: { type: Object, required: true }, aux: { type: Object, required: true } });
const UNIT = { p: '压力 Pa（相对来流）', h: '散热系数 W/(m²·K)', v: '速度 m/s' };
const field = ref('p'), showLines = ref(true), showSlice = ref(true);
const box = ref(null), tip = ref(''), tipX = ref(0), tipY = ref(0);
const hasH = computed(() => (props.surface.h || []).some((x) => x > 0));
let renderer, scene, camera, controls, raf, ro, partMesh, lines, slice, center, diag;

const vals = computed(() => props.surface[field.value] || []);
const range = computed(() => {
  const v = [...vals.value].sort((a, b) => a - b);
  if (!v.length) return [0, 1];
  const lo = v[Math.floor(v.length * 0.02)], hi = v[Math.floor(v.length * 0.98)];
  return [lo, hi > lo ? hi : lo + 1];
});
const fmt = (x) => (Math.abs(x) >= 100 ? x.toFixed(0) : Math.abs(x) >= 10 ? x.toFixed(1) : x.toFixed(2));
const col = (v, [a, b]) => turbo((v - a) / (b - a || 1));

function buildPart() {
  if (partMesh) scene.remove(partMesh);
  const s = props.surface;
  const pos = new Float32Array(s.positions.flat());
  const idx = s.triangles.flat();
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setIndex(idx);
  const c = new Float32Array(pos.length);
  vals.value.forEach((v, i) => { const [r, gg, b] = col(v, range.value); c[3 * i] = r; c[3 * i + 1] = gg; c[3 * i + 2] = b; });
  g.setAttribute('color', new THREE.BufferAttribute(c, 3));
  g.computeVertexNormals();
  partMesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.6, side: THREE.DoubleSide }));
  scene.add(partMesh);
  g.computeBoundingBox();
  center = g.boundingBox.getCenter(new THREE.Vector3());
  diag = g.boundingBox.getSize(new THREE.Vector3()).length();
}

function buildLines() {
  if (lines) scene.remove(lines);
  lines = new THREE.Group();
  const sl = props.aux.streamlines || [];
  const vmax = props.aux.slice?.vmax || Math.max(1e-6, ...sl.flatMap((l) => l.speed));
  for (const l of sl) {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(l.pts.flat()), 3));
    const c = new Float32Array(l.pts.length * 3);
    l.speed.forEach((v, i) => { const [r, gg, b] = turbo(v / vmax); c[3 * i] = r; c[3 * i + 1] = gg; c[3 * i + 2] = b; });
    g.setAttribute('color', new THREE.BufferAttribute(c, 3));
    lines.add(new THREE.Line(g, new THREE.LineBasicMaterial({ vertexColors: true })));
  }
  lines.visible = showLines.value;
  scene.add(lines);
}

function buildSlice() {
  if (slice) scene.remove(slice);
  const s = props.aux.slice;
  if (!s) return;
  const cv = document.createElement('canvas');
  cv.width = s.nx; cv.height = s.ny;
  const ctx = cv.getContext('2d');
  const img = ctx.createImageData(s.nx, s.ny);
  for (let j = 0; j < s.ny; j += 1) {
    for (let i = 0; i < s.nx; i += 1) {
      const v = s.speed[j][i], o = ((s.ny - 1 - j) * s.nx + i) * 4;
      if (v < 0) { img.data[o + 3] = 0; continue; }
      const [r, g, b] = turbo(v / (s.vmax || 1));
      img.data[o] = r * 255; img.data[o + 1] = g * 255; img.data[o + 2] = b * 255; img.data[o + 3] = 120;
    }
  }
  ctx.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(cv);
  tex.magFilter = THREE.LinearFilter;
  const w = s.x1_mm - s.x0_mm, h = s.y1_mm - s.y0_mm;
  slice = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex, transparent: true, side: THREE.DoubleSide, depthWrite: false }));
  const A = 'xyz'.indexOf(s.axis), L = 'xyz'.indexOf(s.lateral), N = 'xyz'.indexOf(s.normal);
  // 平面默认在 xy：先放好，再按轴转
  const m = new THREE.Matrix4();
  const ex = new THREE.Vector3(), ey = new THREE.Vector3(), ez = new THREE.Vector3();
  ex.setComponent(A, 1); ey.setComponent(L, 1); ez.setComponent(N, 1);
  m.makeBasis(ex, ey, ez);
  slice.quaternion.setFromRotationMatrix(m);
  const c = new THREE.Vector3();
  c.setComponent(A, (s.x0_mm + s.x1_mm) / 2); c.setComponent(L, (s.y0_mm + s.y1_mm) / 2); c.setComponent(N, s.at_mm);
  slice.position.copy(c);
  slice.visible = showSlice.value;
  scene.add(slice);
}

function fit() {
  camera.position.copy(center).add(new THREE.Vector3(0.9, -1.4, 0.9).multiplyScalar(diag * 1.1));
  camera.up.set(0, 0, 1);
  camera.near = diag / 100; camera.far = diag * 100; camera.updateProjectionMatrix();
  controls.target.copy(center); controls.update();
}

function move(e) {
  if (!renderer || !partMesh) return;
  const r = renderer.domElement.getBoundingClientRect();
  const p = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  const rc = new THREE.Raycaster(); rc.setFromCamera(p, camera);
  const hit = rc.intersectObject(partMesh, false)[0];
  if (!hit) { tip.value = ''; return; }
  const ti = hit.faceIndex, f = props.surface.face_of_triangle[ti];
  const a = props.surface.triangles[ti][0];
  const fa = (props.aux.faces || []).find((x) => x.id === f);
  tip.value = `面 ${f}：压力 ${fmt(props.surface.p[a])} Pa` + (hasH.value ? `，h ${fmt(props.surface.h[a])}（面平均 ${fa?.h_w_m2k?.toFixed(1)}）W/(m²·K)` : '');
  tipX.value = e.clientX - r.left + 12; tipY.value = e.clientY - r.top + 12;
}

onMounted(() => {
  const el = box.value;
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });   // 报告要截图
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
  el.prepend(renderer.domElement);
  scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.5));
  const dl = new THREE.DirectionalLight(0xffffff, 1.3); dl.position.set(1, -2, 3); scene.add(dl);
  camera = new THREE.PerspectiveCamera(35, 1, 0.1, 1e6);
  controls = new OrbitControls(camera, renderer.domElement);
  const size = () => { const w = el.clientWidth, h = el.clientHeight; renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); };
  ro = new ResizeObserver(size); ro.observe(el); size();
  buildPart(); buildLines(); buildSlice(); fit();
  const loop = () => { raf = requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); };
  loop();
});
watch(field, buildPart);
watch(showLines, (v) => { if (lines) lines.visible = v; });
watch(showSlice, (v) => { if (slice) slice.visible = v; });
watch(() => [props.surface, props.aux], () => { buildPart(); buildLines(); buildSlice(); fit(); });
defineExpose({ snapshot: () => renderer?.domElement.toDataURL('image/png'), setField: (f) => { field.value = f; } });
onUnmounted(() => { cancelAnimationFrame(raf); ro?.disconnect(); renderer?.dispose(); });
</script>

<style scoped>
.fv { display: flex; flex-direction: column; gap: 6px; }
.stage { position: relative; height: 460px; background: var(--surface-2); border-radius: 8px; overflow: hidden; }
.stage :deep(canvas) { display: block; }
.tip { position: absolute; background: #fff; border: 1px solid var(--line); border-radius: 6px; padding: 4px 8px; pointer-events: none; z-index: 2; }
.cbar { position: absolute; right: 10px; top: 10px; bottom: 10px; display: flex; flex-direction: column; align-items: center; gap: 4px; font-size: 11px; background: rgba(255,255,255,.7); border-radius: 6px; padding: 4px; }
.grad { flex: 1; width: 14px; border-radius: 3px; }
.tools { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.chk { display: flex; gap: 4px; align-items: center; }
.link { border: 0; background: none; color: var(--accent); cursor: pointer; }
</style>
