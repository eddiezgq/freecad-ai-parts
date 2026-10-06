<template>
  <!-- 第 6 轮 W4：按参数在浏览器里生成阶梯轴（旋转体 + 键槽），改参数即时更新；可拖动旋转、滚轮缩放 -->
  <div ref="box" class="shaft3d" aria-label="输出轴三维模型"></div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

const props = defineProps({ params: { type: Object, required: true } });
const box = ref(null);
let renderer, scene, camera, controls, outer, raf, ro;

function profile(p) {
  // LatheGeometry 绕 Y 轴旋转：点为 (半径, 高度)；两端倒角
  const segs = p.segments.map(([d, l]) => [Number(d) || 0, Number(l) || 0]).filter(([d, l]) => d > 0 && l > 0);
  if (!segs.length) return null;
  const c = Math.max(0, Math.min(Number(p.chamfer) || 0, segs[0][0] / 2 - 0.1, segs[segs.length - 1][0] / 2 - 0.1));
  const pts = [new THREE.Vector2(0, 0)];
  let z = 0;
  segs.forEach(([d, l], i) => {
    const r = d / 2;
    if (i === 0) { pts.push(new THREE.Vector2(r - c, 0), new THREE.Vector2(r, c)); } else { pts.push(new THREE.Vector2(r, z)); }
    z += l;
    if (i === segs.length - 1) { pts.push(new THREE.Vector2(r, z - c), new THREE.Vector2(r - c, z)); } else { pts.push(new THREE.Vector2(r, z)); }
  });
  pts.push(new THREE.Vector2(0, z));
  return { pts, total: z, segs };
}

function slotMesh(p, segs) {
  const kw = p.keyway;
  if (!kw) return null;
  const i = Number(kw.segment);
  if (!(i >= 0 && i < segs.length)) return null;
  const b = Number(kw.b), t = Number(kw.t), L = Number(kw.L);
  if (!(b > 0 && t > 0 && L >= b)) return null;
  let z0 = 0;
  for (let k = 0; k < i; k += 1) z0 += segs[k][1];
  const d = segs[i][0];
  const zc = z0 + segs[i][1] / 2;
  // 长圆形（两端半圆）截面，沿半径方向挤出 t
  const s = new THREE.Shape();
  const h = (L - b) / 2, r = b / 2;
  s.moveTo(-r, -h); s.lineTo(-r, h); s.absarc(0, h, r, Math.PI, 0, true); s.lineTo(r, -h); s.absarc(0, -h, r, 0, Math.PI, true);
  const g = new THREE.ExtrudeGeometry(s, { depth: t + 0.4, bevelEnabled: false, curveSegments: 24 });
  const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0x1f2a33, roughness: 0.8 }));
  // 截面在 XY 平面（长度沿 Y＝轴线），挤出沿 +Z（半径方向，朝向相机一侧）
  m.position.set(0, zc, d / 2 - t);
  return m;
}

function rebuild() {
  if (!scene) return;
  if (outer) { scene.remove(outer); outer.traverse((o) => { o.geometry?.dispose(); o.material?.dispose?.(); }); outer = null; }
  const group = new THREE.Group();
  const pr = profile(props.params);
  if (pr) {
    const shaft = new THREE.Mesh(new THREE.LatheGeometry(pr.pts, 96),
      new THREE.MeshStandardMaterial({ color: 0xb8c2cc, metalness: 0.55, roughness: 0.35 }));
    group.add(shaft);
    const slot = slotMesh(props.params, pr.segs);
    if (slot) group.add(slot);
    group.position.y = -pr.total / 2;
    outer = new THREE.Group();
    outer.add(group);
    outer.rotation.z = -Math.PI / 2;                      // 轴线水平
    scene.add(outer);
    fit(pr.total);
  }
}

let fitted = 0;
function fit(total) {
  // 第一次和总长变化较大时，按总长调整相机距离
  if (fitted && Math.abs(total - fitted) / fitted < 0.25) return;
  fitted = total;
  camera.position.set(0.1 * total, 0.45 * total, 1.05 * total + 60);
  controls?.target.set(0, 0, 0);
}

function resize() {
  const el = box.value;
  if (!el || !renderer) return;
  const w = el.clientWidth, h = el.clientHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

onMounted(() => {
  const el = box.value;
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  el.appendChild(renderer.domElement);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(35, 1, 1, 5000);
  camera.position.set(40, 120, 260);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(100, 200, 150);
  scene.add(sun);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  fitted = 0;
  rebuild();
  resize();
  ro = new ResizeObserver(resize);
  ro.observe(el);
  const loop = () => { raf = requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); };
  loop();
});

watch(() => JSON.stringify(props.params), rebuild);

onUnmounted(() => {
  cancelAnimationFrame(raf);
  ro?.disconnect();
  renderer?.dispose();
});
</script>

<style scoped>
.shaft3d { width: 100%; height: 260px; border-radius: 8px; background: linear-gradient(#f4f6f8, #e3e8ec); cursor: grab; }
</style>
