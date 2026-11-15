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
// night：深色车间（帮助首页用）；autoRotate：镜头缓慢环绕
// zones（第 171 轮）：车间分区 [{id, name, rect: [x0, y0, x1, y1], auto}]；给了就在地面上画每个车间（auto = 整厂一个区，不画）
const ZONE_COLORS = ['#E3EEF8', '#E8F4E5', '#FBEEDC', '#EFE8F7', '#F9E4E4', '#E2F2F1', '#F3F1DE'];

function zoneLabel(text) {
  const c = document.createElement('canvas');
  c.width = 1024; c.height = 128;
  const g = c.getContext('2d');
  g.font = 'bold 72px "Noto Sans SC", "PingFang SC", sans-serif';
  const w = Math.min(1000, g.measureText(text).width + 60);
  g.fillStyle = 'rgba(255,255,255,0.88)'; g.fillRect((1024 - w) / 2, 8, w, 112);
  g.fillStyle = '#17212B'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text, 512, 66);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false }));
  return sp;
}

export function createWorkshop(host, L, { onFrame, night = false, autoRotate = false, zones = null } = {}) {
  const [FW, FD] = L.floor;
  const C = night ? { bg: '#17212B', floor: '#22303C', aisle: '#34485A' } : { bg: '#EEF0EC', floor: '#D9DDD6', aisle: '#F2EDD7' };
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(C.bg);
  const camera = new THREE.PerspectiveCamera(45, host.clientWidth / Math.max(1, host.clientHeight), 0.1, Math.max(500, (L.floor[0] + L.floor[1]) * 3));
  camera.position.set(FW / 2, 40, FD + 34);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
  renderer.setSize(host.clientWidth, host.clientHeight);
  host.appendChild(renderer.domElement);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(FW / 2, 0, FD / 2);
  controls.maxPolarAngle = Math.PI / 2.1;
  controls.autoRotate = autoRotate;
  controls.autoRotateSpeed = 0.35;
  controls.update();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f86, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(20, 40, 10);
  scene.add(sun);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(FW, FD), new THREE.MeshLambertMaterial({ color: C.floor }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(FW / 2, 0, FD / 2);
  scene.add(floor);
  for (const a of L.aisles) {
    const s = new THREE.Mesh(new THREE.PlaneGeometry(FW - 4, 2.2), new THREE.MeshLambertMaterial({ color: C.aisle }));
    s.rotation.x = -Math.PI / 2; s.position.set(FW / 2 + 1, 0.01, a); scene.add(s);
  }
  if (L.aisles.length > 1) {           // 只有一条主通道的车间没有纵向连接通道
    const lo = Math.min(...L.aisles), hi = Math.max(...L.aisles);
    const cross = new THREE.Mesh(new THREE.PlaneGeometry(2.2, hi - lo), new THREE.MeshLambertMaterial({ color: C.aisle }));
    cross.rotation.x = -Math.PI / 2; cross.position.set(L.cross_x, 0.01, (lo + hi) / 2); scene.add(cross);
  }

  const zoneObjs = {};
  (zones || []).filter((z) => !z.auto).forEach((z, i) => {
    const [x0, y0, x1, y1] = z.rect, w = x1 - x0, d = y1 - y0;
    const patch = new THREE.Mesh(new THREE.PlaneGeometry(w, d), new THREE.MeshLambertMaterial({ color: ZONE_COLORS[i % ZONE_COLORS.length] }));
    patch.rotation.x = -Math.PI / 2; patch.position.set(x0 + w / 2, 0.005, y0 + d / 2);
    patch.userData.zone = z.id;
    scene.add(patch);
    const wallMat = new THREE.MeshLambertMaterial({ color: '#8C99A6', transparent: true, opacity: 0.55 });
    for (const [cx, cz, ww, dd] of [[x0 + w / 2, y0, w, 0.25], [x0 + w / 2, y1, w, 0.25], [x0, y0 + d / 2, 0.25, d], [x1, y0 + d / 2, 0.25, d]]) {
      const wall = new THREE.Mesh(new THREE.BoxGeometry(ww, 0.8, dd), wallMat);
      wall.position.set(cx, 0.4, cz); scene.add(wall);
    }
    const lb = zoneLabel(z.name_shown || z.name);
    const sw = Math.max(10, Math.min(w * 0.8, 40));
    lb.scale.set(sw, sw / 8, 1); lb.position.set(x0 + w / 2, 6 + sw / 10, y0 + 1.5);
    scene.add(lb);
    zoneObjs[z.id] = { patch, label: lb, rect: z.rect };
  });

  const meshes = {};
  for (const [u, v] of Object.entries(L.units)) {
    const hgt = v.h || HEIGHT[u] || 1.5;     // 高度：工厂清单给的（第 30 轮），否则演示工厂的
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

  for (const [a, g] of Object.entries(agvMeshes)) g.children.forEach((c) => { c.userData.unit = a; });

  function pick(e) {
    const r = renderer.domElement.getBoundingClientRect();
    pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects([...Object.values(meshes).flatMap((o) => [o.body, o.lamp]), ...Object.values(agvMeshes).flatMap((g) => g.children)])[0];
    return hit ? hit.object.userData.unit : null;
  }
  // 点到车间地面（没点到设备时）：返回车间 id
  function pickZone(e) {
    const r = renderer.domElement.getBoundingClientRect();
    pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(Object.values(zoneObjs).map((z) => z.patch))[0];
    return hit ? hit.object.userData.zone : null;
  }

  // ---- 镜头飞行（第 171 轮：分车间、参观）
  let fly = null;
  function flyTo(target, pos, ms = 1200) {
    fly = { t0: performance.now(), ms, a: { t: controls.target.clone(), p: camera.position.clone() }, b: { t: target, p: pos } };
  }
  function flyRect([x0, y0, x1, y1]) {
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, s = Math.max(x1 - x0, (y1 - y0) * 1.6);
    const dist = s * 0.95 + 10;
    flyTo(new THREE.Vector3(cx, 0, cy), new THREE.Vector3(cx, dist * 0.62, cy + dist * 0.78));
  }
  function overview() { flyRect([0, 0, FW, FD]); }
  function flyZone(id) { const z = zoneObjs[id]; if (z) flyRect(z.rect); }
  function flyUnit(u) {
    const o = meshes[u];
    let x, y, h;
    if (o) { x = o.v.x; y = o.v.y; h = o.hgt; } else if (agvMeshes[u]) { x = agvMeshes[u].position.x; y = agvMeshes[u].position.z; h = 0.6; } else return false;
    flyTo(new THREE.Vector3(x, h / 2, y), new THREE.Vector3(x + 9, h + 12, y + 17));
    return true;
  }
  // 选中的设备：机身变浅蓝（再选别的就恢复）
  let hl = null;
  function highlight(u) {
    if (hl && meshes[hl]) meshes[hl].body.material.color.set(meshes[hl].base);
    hl = meshes[u] ? u : null;
    if (hl) meshes[hl].body.material.color.set('#9FD3E0');
  }
  for (const o of Object.values(meshes)) o.base = '#' + o.body.material.color.getHexString();
  // 工艺路线：按工序顺序在设备之间画箭头
  const routeGroup = new THREE.Group();
  scene.add(routeGroup);
  function showRoute(units) {
    clearRoute();
    const pts = units.map((u) => meshes[u]).filter(Boolean).map((o) => new THREE.Vector3(o.v.x, o.hgt + 0.6, o.v.y));
    const mat = new THREE.LineBasicMaterial({ color: '#C2410C' });
    for (let i = 0; i + 1 < pts.length; i++) {
      const a = pts[i], b = pts[i + 1];
      if (a.distanceTo(b) < 0.1) continue;
      const mid = a.clone().add(b).multiplyScalar(0.5); mid.y += Math.min(6, a.distanceTo(b) * 0.15) + 0.5;
      const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      routeGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(24)), mat));
      const cone = new THREE.Mesh(new THREE.ConeGeometry(0.35, 0.9, 12), new THREE.MeshLambertMaterial({ color: '#C2410C' }));
      const tip = curve.getPoint(0.92), dir = curve.getTangent(0.92);
      cone.position.copy(tip); cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
      routeGroup.add(cone);
      const n = labelSprite(String(i + 1), '#C2410C'); n.scale.set(1.2, 0.3, 1); n.position.copy(curve.getPoint(0.5)).add(new THREE.Vector3(0, 0.5, 0));
      routeGroup.add(n);
    }
  }
  function clearRoute() { while (routeGroup.children.length) routeGroup.remove(routeGroup.children[0]); }
  if (zones) {                 // 3D 车间页：一开始就看全厂（大厂也装得下）
    const s = Math.max(FW, FD * 1.6), dist = s * 0.95 + 10;
    controls.target.set(FW / 2, 0, FD / 2); camera.position.set(FW / 2, dist * 0.62, FD / 2 + dist * 0.78); controls.update();
  }

  let raf;
  function loop() {
    raf = requestAnimationFrame(loop);
    if (fly) {
      const k = Math.min(1, (performance.now() - fly.t0) / fly.ms), e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
      controls.target.lerpVectors(fly.a.t, fly.b.t, e); camera.position.lerpVectors(fly.a.p, fly.b.p, e);
      if (k >= 1) fly = null;
    }
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
    update, focus, pick, resize, pickZone, flyRect, flyZone, flyUnit, overview, highlight, showRoute, clearRoute,
    dispose() { cancelAnimationFrame(raf); window.removeEventListener('resize', resize); renderer.dispose(); },
  };
}
