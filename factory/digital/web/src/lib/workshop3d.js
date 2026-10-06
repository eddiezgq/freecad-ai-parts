// 3D 车间场景：工作台“3D 车间”页和可嵌入的只读车间（/embed/workshop，第 4 轮 C8）共用
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export const HEX = { run: '#1F7A4D', idle: '#9AA3AD', setup: '#C98A12', down: '#B42318', fault: '#B42318' };
const HEIGHT = { 'ht-01': 2.6, 'store-01': 3, 'store-02': 3, 'hmc-01': 2.4, 'vmc-01': 2.3, 'cnc-l01-a': 1.8, 'cnc-l01-b': 1.8,
  'grd-01': 1.7, 'hob-01': 2, 'key-01': 1.6, 'saw-01': 1.2, 'qc-01': 1.5, 'asm-01': 1.0, 'test-01': 1.3 };

function labelSprite(text, color = '#17212B') {
  const c = document.createElement('canvas');
  c.width = 256; c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = 'rgba(255,255,255,0.92)'; g.fillRect(0, 0, 256, 64);
  g.fillStyle = color; g.font = 'bold 28px "IBM Plex Mono", monospace'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text, 128, 34);
  const tex = new THREE.CanvasTexture(c);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
  sp.scale.set(3.2, 0.8, 1);
  return sp;
}

// layout：/api/layout 的返回；host：放画布的元素。返回 { update(machines, agvs), pick(event), focus(unit), render hook, dispose() }
export function createWorkshop(host, L, { onFrame } = {}) {
  const [FW, FD] = L.floor;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#EEF0EC');
  const camera = new THREE.PerspectiveCamera(45, host.clientWidth / Math.max(1, host.clientHeight), 0.1, 500);
  camera.position.set(FW / 2, 40, FD + 34);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
  renderer.setSize(host.clientWidth, host.clientHeight);
  host.appendChild(renderer.domElement);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(FW / 2, 0, FD / 2);
  controls.maxPolarAngle = Math.PI / 2.1;
  controls.update();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f86, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(20, 40, 10);
  scene.add(sun);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(FW, FD), new THREE.MeshLambertMaterial({ color: '#D9DDD6' }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(FW / 2, 0, FD / 2);
  scene.add(floor);
  for (const a of L.aisles) {
    const s = new THREE.Mesh(new THREE.PlaneGeometry(FW - 4, 2.2), new THREE.MeshLambertMaterial({ color: '#F2EDD7' }));
    s.rotation.x = -Math.PI / 2; s.position.set(FW / 2 + 1, 0.01, a); scene.add(s);
  }
  const cross = new THREE.Mesh(new THREE.PlaneGeometry(2.2, L.aisles[1] - L.aisles[0]), new THREE.MeshLambertMaterial({ color: '#F2EDD7' }));
  cross.rotation.x = -Math.PI / 2; cross.position.set(L.cross_x, 0.01, (L.aisles[0] + L.aisles[1]) / 2); scene.add(cross);

  const meshes = {};
  for (const [u, v] of Object.entries(L.units)) {
    const hgt = HEIGHT[u] || 1.5;
    const store = u.startsWith('store');
    const body = new THREE.Mesh(new THREE.BoxGeometry(v.w, hgt, v.d),
      new THREE.MeshLambertMaterial({ color: store ? '#B8BEB5' : u === 'ht-01' ? '#6E7B85' : '#DCE2E6' }));
    body.position.set(v.x, hgt / 2, v.y);
    body.userData.unit = u;
    scene.add(body);
    const lamp = new THREE.Mesh(new THREE.BoxGeometry(v.w * 0.9, 0.12, v.d * 0.9), new THREE.MeshLambertMaterial({ color: '#9AA3AD', emissive: '#000' }));
    lamp.position.set(v.x, hgt + 0.06, v.y);
    lamp.userData.unit = u;
    scene.add(lamp);
    const label = labelSprite(u.toUpperCase());
    label.position.set(v.x, hgt + 1.1, v.y);
    scene.add(label);
    const queue = new THREE.Group();
    scene.add(queue);
    meshes[u] = { body, lamp, label, queue, v, hgt };
  }
  const agvMeshes = {};
  for (const a of Object.keys(L.agv_home)) {
    const g = new THREE.Group();
    const base = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.35, 0.8), new THREE.MeshLambertMaterial({ color: '#F2B705' }));
    base.position.y = 0.25;
    const load = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 0.5, 16), new THREE.MeshLambertMaterial({ color: '#5D6873' }));
    load.rotation.z = Math.PI / 2; load.position.y = 0.6; load.visible = false;
    g.add(base, load);
    const [x, y] = L.agv_home[a];
    g.position.set(x, 0, y);
    g.userData = { target: new THREE.Vector3(x, 0, y), load };
    const lb = labelSprite(a.toUpperCase(), '#6B4E00');
    lb.scale.set(2.2, 0.55, 1); lb.position.set(0, 1.4, 0);
    g.add(lb);
    scene.add(g);
    agvMeshes[a] = g;
  }
  let machines = {};
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();

  function update(ms, agvs) {
    machines = ms || {};
    for (const [u, o] of Object.entries(meshes)) {
      const st = machines[u];
      const state = st?.state || 'idle';
      o.lamp.material.color.set(HEX[state] || '#9AA3AD');
      o.lamp.material.emissive.set(state === 'run' ? '#0B3320' : state === 'down' || state === 'fault' ? '#4A0D08' : '#000');
      // 待加工的零件：在设备旁摆成一排小圆柱
      const n = Math.min(st?.queue || 0, 12);
      while (o.queue.children.length > n) o.queue.remove(o.queue.children[0]);
      while (o.queue.children.length < n) {
        const p = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.9, 12), new THREE.MeshLambertMaterial({ color: '#4A5560' }));
        p.rotation.z = Math.PI / 2;
        o.queue.add(p);
      }
      o.queue.children.forEach((p, i) => p.position.set(o.v.x - o.v.w / 2 + 0.3 + (i % 6) * 0.4, 0.2 + Math.floor(i / 6) * 0.35, o.v.y + o.v.d / 2 + 0.5));
    }
    for (const [a, g] of Object.entries(agvMeshes)) {
      const s = (agvs || {})[a];
      if (!s) continue;
      g.userData.target.set(s.x_m, 0, s.y_m);
      g.rotation.y = -((s.heading_deg || 0) * Math.PI) / 180;
      g.userData.load.visible = !!s.load;
    }
  }

  // 镜头对准某台设备（嵌入页 view=device）
  function focus(unit) {
    const o = meshes[unit];
    if (!o) return false;
    controls.target.set(o.v.x, o.hgt / 2, o.v.y);
    camera.position.set(o.v.x + 6, 7, o.v.y + 9);
    controls.update();
    o.body.material.color.set('#C9E4EA');
    return true;
  }

  function pick(e) {
    const r = renderer.domElement.getBoundingClientRect();
    pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(Object.values(meshes).flatMap((o) => [o.body, o.lamp]))[0];
    return hit ? hit.object.userData.unit : null;
  }

  let raf;
  function loop() {
    raf = requestAnimationFrame(loop);
    for (const g of Object.values(agvMeshes)) g.position.lerp(g.userData.target, 0.08);
    const t = performance.now() / 300;
    for (const [u, o] of Object.entries(meshes)) {
      const st = machines[u]?.state;
      o.lamp.scale.y = st === 'down' || st === 'fault' ? 1 + 0.6 * Math.abs(Math.sin(t)) : 1;
    }
    controls.update();
    renderer.render(scene, camera);
    if (onFrame) onFrame();
  }
  loop();

  function resize() {
    camera.aspect = host.clientWidth / Math.max(1, host.clientHeight);
    camera.updateProjectionMatrix();
    renderer.setSize(host.clientWidth, host.clientHeight);
  }
  window.addEventListener('resize', resize);

  return {
    update, focus, pick, resize,
    dispose() { cancelAnimationFrame(raf); window.removeEventListener('resize', resize); renderer.dispose(); },
  };
}
