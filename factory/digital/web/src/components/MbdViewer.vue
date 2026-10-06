<template>
  <!-- 第 12 轮：动力学动画——每个构件一个节点，按每一帧的位置、姿态摆放；可画出记录点的轨迹 -->
  <div ref="box" class="mv"><div class="hint small">{{ note }}</div></div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const props = defineProps({
  modelUrl: { type: String, default: '' },
  anim: { type: Object, default: null },          // fetchAnim() 的结果
  time: { type: Number, default: 0 },
  trails: { type: Array, default: () => [] },     // [{points: [[x,y,z]…]（米）, color}]
});
const box = ref(null);
const note = ref('');
let renderer, scene, camera, controls, raf, ro, root, nodes = {}, trailGroup, fitted = false;
const loader = new GLTFLoader();

function load() {
  if (!props.modelUrl) return;
  note.value = '正在读取模型…';
  loader.load(props.modelUrl, (g) => {
    root.clear(); nodes = {}; fitted = false;
    g.scene.traverse((o) => {
      if (o.isMesh) {
        o.material = new THREE.MeshStandardMaterial({ color: o.material.color || 0xb8c2cc, vertexColors: !!o.geometry.attributes.color,
          metalness: 0.2, roughness: 0.6, side: THREE.DoubleSide });
        if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals();
      }
    });
    // 网格名 = 构件名；拿出来平铺在根下（每帧直接给世界坐标）
    const meshes = [];
    g.scene.traverse((o) => { if (o.isMesh) meshes.push(o); });
    for (const m of meshes) { m.position.set(0, 0, 0); m.quaternion.identity(); m.scale.set(1, 1, 1); root.add(m); nodes[m.name] = m; }
    note.value = '拖动旋转 · 滚轮缩放 · 右键平移';
    pose(); fit();
  }, undefined, () => { note.value = '模型读取失败'; });
}

function pose() {
  const a = props.anim;
  if (!a) return;
  let lo = 0, hi = a.frames - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (a.t[m] < props.time) lo = m; else hi = m; }
  const f = Math.abs(a.t[lo] - props.time) <= Math.abs(a.t[hi] - props.time) ? lo : hi;
  const nb = a.bodies.length;
  a.bodies.forEach((name, b) => {
    const n = nodes[name];
    if (!n) return;
    const p = 3 * (f * nb + b), q = 4 * (f * nb + b);
    n.position.set(a.pos[p], a.pos[p + 1], a.pos[p + 2]);
    n.quaternion.set(a.quat[q + 1], a.quat[q + 2], a.quat[q + 3], a.quat[q]);     // MuJoCo 四元数是 w,x,y,z
  });
}

function drawTrails() {
  trailGroup.clear();
  for (const tr of props.trails) {
    if (!tr.points.length) continue;
    const g = new THREE.BufferGeometry().setFromPoints(tr.points.map((p) => new THREE.Vector3(...p)));
    trailGroup.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: tr.color, linewidth: 2 })));
  }
}

function fit() {
  if (fitted || !root.children.length) return;
  const bb = new THREE.Box3().setFromObject(root);
  if (bb.isEmpty()) return;
  fitted = true;
  const c = bb.getCenter(new THREE.Vector3()), r = Math.max(bb.getSize(new THREE.Vector3()).length(), 0.05);
  camera.near = r / 200; camera.far = r * 100; camera.updateProjectionMatrix();
  camera.position.copy(c).add(new THREE.Vector3(r * 0.2, -r * 1.6, r * 0.7));       // 从前方（−Y）看平面机构
  controls.target.copy(c);
  scene.children.filter((o) => o.isGridHelper).forEach((o) => scene.remove(o));
  const grid = new THREE.GridHelper(r * 3, 20, 0xc9cfd4, 0xe1e5e8);
  grid.rotation.x = Math.PI / 2; grid.position.set(c.x, c.y, bb.min.z - r * 0.02);
  scene.add(grid);
}

function resize() {
  if (!renderer) return;
  const w = box.value.clientWidth, h = box.value.clientHeight;
  renderer.setSize(w, h); camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix();
}

onMounted(() => {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  box.value.prepend(renderer.domElement);
  scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a949c, 1.6));
  const d = new THREE.DirectionalLight(0xffffff, 1.4); d.position.set(2, -4, 5); scene.add(d);
  root = new THREE.Group(); scene.add(root);
  trailGroup = new THREE.Group(); scene.add(trailGroup);
  camera = new THREE.PerspectiveCamera(35, 1, 0.01, 1000);
  camera.up.set(0, 0, 1);                                                          // MuJoCo：Z 向上
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  ro = new ResizeObserver(resize); ro.observe(box.value); resize();
  const loop = () => { controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(loop); };
  loop();
  load(); drawTrails();
});
watch(() => props.modelUrl, load);
watch(() => props.time, pose);
watch(() => props.anim, () => { pose(); if (props.anim) { fitted = false; fit(); } });   // 出结果后按真实位置重新对焦
watch(() => props.trails, drawTrails);
onUnmounted(() => { cancelAnimationFrame(raf); ro?.disconnect(); renderer?.dispose(); });
defineExpose({ snapshot: () => renderer?.domElement.toDataURL('image/png') });
</script>

<style scoped>
.mv { position: relative; height: 440px; border-radius: 8px; background: linear-gradient(#f6f7f8, #dfe4e8); overflow: hidden; }
.hint { position: absolute; left: 10px; bottom: 8px; color: var(--muted); pointer-events: none; }
@media (max-width: 700px) { .mv { height: 320px; } }
</style>
