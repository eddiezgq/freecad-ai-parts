<template>
  <!-- WQR-105 孪生的三维示意：三根轴、四个齿轮（按分度圆）、六个轴承、箱体；部件按健康度着色，鼠标停上去看数 -->
  <div ref="box" class="gt" @mousemove="hover" @mouseleave="tip = null">
    <div v-if="tip" class="tip small" :style="{ left: tip.x + 'px', top: tip.y + 'px' }"><b>{{ tip.name }}</b><div>{{ tip.text }}</div></div>
    <div class="legend small"><span><i style="background:#2E9E5B"></i>正常</span><span><i style="background:#E0A100"></i>注意</span><span><i style="background:#D64541"></i>报警 / 快到期</span></div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

const props = defineProps({
  bearings: { type: Array, default: () => [] },   // [{id, name, model, used, alarm}]
  shaft: { type: Object, default: () => ({ used: 0 }) },
  housing: { type: Object, default: () => ({ level: 'ok', text: '' }) },   // level: ok / warn / bad
});
const box = ref(null), tip = ref(null);
const C = { ok: 0x2e9e5b, warn: 0xe0a100, bad: 0xd64541, steel: 0x9aa4ad, gear: 0x7d8790 };
let renderer, scene, camera, controls, raf, ro;
const pickable = [];
const S = 0.01;                                  // mm → 场景单位
// 中心距：(24+72)·2/2 = 96，(20+70)·3/2 = 135；三根轴同一平面
const X = { in: 0, mid: 96, out: 231 };
const GEARS = [['in', 35, 24, 2, 30], ['mid', 35, 72, 2, 30], ['mid', 85, 20, 3, 40], ['out', 85, 70, 3, 40]];
const BRG = { 'in-A': ['in', 0, 52], 'in-B': ['in', 120, 52], 'mid-A': ['mid', 0, 62], 'mid-B': ['mid', 120, 62], 'out-A': ['out', 0, 72], 'out-B': ['out', 120, 72] };

const level = (u, alarm) => (alarm ? 'bad' : u >= 0.8 ? 'bad' : u >= 0.5 ? 'warn' : 'ok');
const pct = (u) => `${(u * 100).toFixed(1)}%`;

function cyl(r, len, color, x, z, opacity = 1) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r * S, r * S, len * S, 48),
    new THREE.MeshStandardMaterial({ color, metalness: 0.3, roughness: 0.6, transparent: opacity < 1, opacity }));
  m.rotation.x = Math.PI / 2;
  m.position.set(x * S, 0, z * S);
  scene.add(m);
  return m;
}

function build() {
  scene.clear();
  pickable.length = 0;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
  const dl = new THREE.DirectionalLight(0xffffff, 1.5); dl.position.set(3, 4, 5); scene.add(dl);
  // 轴
  const sh = cyl(15, 230, C[level(props.shaft.used || 0)], X.out, 30);
  sh.userData = { name: '输出轴 SH-301（疲劳）', text: `累积损伤 ${pct(props.shaft.used || 0)}；1 = 预计出现疲劳裂纹` };
  pickable.push(sh);
  cyl(12, 150, C.steel, X.in, 60); cyl(15, 140, C.steel, X.mid, 60);
  // 齿轮（分度圆）
  for (const [s, z, n, m, b] of GEARS) cyl(n * m / 2, b, C.gear, X[s], z, 0.9);
  // 轴承
  for (const b of props.bearings) {
    const [s, z, d] = BRG[b.id] || [];
    if (s === undefined) continue;
    const lv = level(b.used, b.alarm);
    const t = new THREE.Mesh(new THREE.TorusGeometry(d / 2 * S * 0.75, d / 2 * S * 0.28, 16, 48),
      new THREE.MeshStandardMaterial({ color: C[lv], emissive: lv === 'bad' ? 0x551111 : 0x000000, roughness: 0.4 }));
    t.position.set(X[s] * S, 0, z * S);
    t.userData = { name: `${b.name}（${b.model}）`, text: `已用 L10 寿命 ${pct(b.used)}${b.alarm ? '；振动报警' : ''}` };
    scene.add(t); pickable.push(t);
  }
  // 箱体（线框 + 半透明），按油温 / 散热着色
  const hb = new THREE.BoxGeometry(410 * S, 300 * S, 150 * S);
  const col = { ok: C.ok, warn: C.warn, bad: C.bad }[props.housing.level] || C.ok;
  const hm = new THREE.Mesh(hb, new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.07, depthWrite: false }));
  const cx = (X.out + X.in) / 2 * S;
  hm.position.set(cx, 0, 60 * S);
  hm.userData = { name: '箱体与润滑油', text: props.housing.text };
  scene.add(hm); pickable.push(hm);
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(hb), new THREE.LineBasicMaterial({ color: col }));
  edges.position.copy(hm.position); scene.add(edges);
}

function hover(e) {
  if (!renderer) return;
  const r = renderer.domElement.getBoundingClientRect();
  const p = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  const rc = new THREE.Raycaster(); rc.setFromCamera(p, camera);
  const hit = rc.intersectObjects(pickable, false).sort((a, b) => (a.object.geometry.type === 'BoxGeometry') - (b.object.geometry.type === 'BoxGeometry'))[0];
  tip.value = hit ? { ...hit.object.userData, x: e.clientX - r.left + 12, y: e.clientY - r.top + 12 } : null;
}

onMounted(() => {
  const el = box.value;
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
  el.prepend(renderer.domElement);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(35, 1, 0.01, 100);
  camera.position.set(1.15, 2.3, 4.6);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(1.15, 0, 0.5);
  controls.update();
  const size = () => { const w = el.clientWidth, h = el.clientHeight; renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); };
  ro = new ResizeObserver(size); ro.observe(el); size();
  build();
  const loop = () => { raf = requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); };
  loop();
});
watch(() => [props.bearings, props.shaft, props.housing], build, { deep: true });
onUnmounted(() => { cancelAnimationFrame(raf); ro?.disconnect(); renderer?.dispose(); });
</script>

<style scoped>
.gt { position: relative; height: 300px; background: var(--surface-2); border-radius: 8px; overflow: hidden; }
.gt :deep(canvas) { display: block; }
.tip { position: absolute; background: #fff; border: 1px solid var(--line); border-radius: 6px; padding: 4px 8px; pointer-events: none; max-width: 260px; box-shadow: 0 2px 6px rgba(0,0,0,.12); }
.legend { position: absolute; left: 8px; bottom: 6px; display: flex; gap: 10px; color: var(--muted); }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: -1px; }
</style>
