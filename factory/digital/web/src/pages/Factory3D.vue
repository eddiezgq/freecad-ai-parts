<template>
  <div class="wrap3d">
    <div ref="host" class="host" @pointerdown="down" @pointerup="up"></div>
    <div class="legend small">
      <span v-for="s in ['run', 'idle', 'setup', 'down']" :key="s"><i :style="{ background: HEX[s] }"></i>{{ STATE[s].label }}</span>
      <span class="muted">拖动旋转 · 滚轮缩放 · 点设备看详情</span>
    </div>
    <aside v-if="sel" class="panel">
      <button class="x" aria-label="关闭" @click="sel = null">×</button>
      <h2>{{ sel.toUpperCase() }} {{ layout?.units[sel]?.name }}</h2>
      <template v-if="bus.machines[sel]">
        <p><span class="pill" :style="{ color: STATE[m.state].color, background: STATE[m.state].bg }">{{ STATE[m.state].label }}</span>
          <span v-if="m.reason" class="small"> {{ m.reason }}</span></p>
        <p class="small">工单 <b class="mono">{{ m.work_order || '—' }}</b> · {{ (m.operation || '').split(' ')[0] }} · {{ m.qty_done }}/{{ m.qty }} 件</p>
        <p class="small">待加工 {{ m.queue }} 件 · 刀具寿命 {{ Math.round((m.tool_life_left ?? 1) * 100) }}%</p>
        <router-link :to="{ path: '/work/operator', query: { unit: sel } }" class="small">打开车间终端 →</router-link>
      </template>
      <p v-else class="small muted">这个单元没有状态消息。</p>
      <template v-if="sel === 'key-01' || isLathe">
        <hr>
        <h3>{{ sel === 'key-01' ? '键槽刀路回放' : '车削刀路回放' }}<span v-if="gcInfo" class="small muted"> {{ gcInfo }}</span></h3>
        <div ref="gcHost" class="gchost"></div>
        <p v-if="!gcode" class="small muted">{{ sel === 'key-01' ? '还没有 G 代码：工艺员在 FreeCAD 或网页设计台发布后生成。' : '还没有车削程序：在“数控编程”里给粗车或精车工序编程，挂到工艺规程上审批生效后才有。' }}</p>
        <button v-else class="btn" @click="playGcode">{{ gcPlaying ? '重新播放' : '播放刀路' }}</button>
      </template>
    </aside>
    <div v-if="err" class="errbox err">{{ err }}</div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import * as THREE from 'three';
import { createWorkshop, HEX } from '../lib/workshop3d';
import { get } from '../lib/api';
import { bus } from '../lib/bus';
import { STATE } from '../lib/fmt';
import { parseGcode } from '../lib/gcode';

const route = useRoute();
const host = ref(null);
const gcHost = ref(null);
const layout = ref(null);
const sel = ref(null);
const err = ref('');
const gcode = ref('');
const gcPlaying = ref(false);
const m = computed(() => bus.machines[sel.value] || {});
const isLathe = computed(() => (sel.value || '').startsWith('cnc-l01'));
let ws, downAt;
let gc = null;             // 刀路小窗

function applyStatus() { if (ws) ws.update(bus.machines, bus.agvs); }
function down(e) { downAt = [e.clientX, e.clientY]; }
function up(e) {
  if (!ws || !downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
  const u = ws.pick(e);
  if (u) sel.value = u;
}

// ---------------------------------------------------------------- 刀路小窗
let design = null;
const gcInfo = ref('');
// 键槽：设计发布带的或数控编程下发的“铣键槽”程序；车削：数控编程随工艺规程下发到 CNC-L01 的最新程序（第 13 轮）
async function loadGcode(unit) {
  gcode.value = ''; gcInfo.value = '';
  let ref_ = unit === 'key-01' ? route.query.gcode : null;
  if (!ref_) {
    design = design || await get('/design/SH-301');
    const g = unit === 'key-01' ? design.gcode.find((x) => (x.operation || '').startsWith('铣键槽'))
      : design.gcode.filter((x) => (x.machine || '').startsWith('cnc-l01'))
        .sort((a, b) => (b.process_revision || 0) - (a.process_revision || 0) || (a.program || 0) - (b.program || 0))[0];
    ref_ = g?.gcode_ref;
    if (g && g.program) gcInfo.value = `O${String(g.program).padStart(4, '0')} · ${(g.operation || '').split(' ')[0]}`;
  }
  if (ref_) gcode.value = await (await fetch(ref_)).text();
}
function initGc() {
  if (!gcHost.value || gc) return;
  if (isLathe.value) { initLathe(); return; }
  const w = gcHost.value.clientWidth, h = 200;
  const s = new THREE.Scene();
  s.background = new THREE.Color('#F6F7F4');
  const cam = new THREE.PerspectiveCamera(40, w / h, 0.1, 2000);
  const r = new THREE.WebGLRenderer({ antialias: true });
  r.setSize(w, h);
  gcHost.value.appendChild(r.domElement);
  s.add(new THREE.HemisphereLight(0xffffff, 0x888888, 2));
  const pts = parseGcode(gcode.value);
  const xs = pts.map((p) => p[0]);
  const xmid = (Math.min(...xs) + Math.max(...xs)) / 2;
  // 轴段（Ø40），轴线沿 X；Z0 为最高母线
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(20, 20, 120, 48), new THREE.MeshLambertMaterial({ color: '#C7CDD1' }));
  shaft.rotation.z = Math.PI / 2; shaft.position.set(xmid, -20, 0);
  s.add(shaft);
  const tool = new THREE.Mesh(new THREE.CylinderGeometry(6, 6, 30, 24), new THREE.MeshLambertMaterial({ color: '#F2B705' }));
  s.add(tool);
  const trail = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: '#0E5E6F' }));
  s.add(trail);
  cam.position.set(xmid - 40, 70, 110);
  cam.lookAt(xmid, -5, 0);
  gc = { s, cam, r, pts, tool, trail, i: 0, f: 0, done: [], render() {
    if (gcPlaying.value) {
      const a = this.pts[this.i], b = this.pts[this.i + 1];
      if (!b) { gcPlaying.value = false; } else {
        this.f += b[3] ? 0.2 : 0.035;
        const p = [a[0] + (b[0] - a[0]) * Math.min(1, this.f), a[2] + (b[2] - a[2]) * Math.min(1, this.f)];
        this.tool.position.set(p[0], p[1] + 15, 0);
        if (!b[3]) { this.done.push(new THREE.Vector3(p[0], p[1], 0)); this.trail.geometry.setFromPoints(this.done); }
        if (this.f >= 1) { this.f = 0; this.i += 1; }
      }
    }
    this.r.render(this.s, this.cam);
  } };
  gc.tool.position.set(pts[0][0], pts[0][2] + 15, 0);
}
function initLathe() {
  // 车床：程序的 X 是直径、Z 沿轴线；场景里 x = Z，y = X/2（只画上半边刀路），毛坯是半透明圆柱
  const w = gcHost.value.clientWidth, h = 200;
  const s = new THREE.Scene();
  s.background = new THREE.Color('#F6F7F4');
  const cam = new THREE.PerspectiveCamera(40, w / h, 0.1, 3000);
  const r = new THREE.WebGLRenderer({ antialias: true });
  r.setSize(w, h);
  gcHost.value.appendChild(r.domElement);
  s.add(new THREE.HemisphereLight(0xffffff, 0x888888, 2));
  const pts = parseGcode(gcode.value).filter((p) => Math.abs(p[0]) < 150 && p[2] < 50);      // 去掉换刀点
  const zs = pts.map((p) => p[2]), rmax = Math.max(...pts.map((p) => p[0] / 2));
  const zmin = Math.min(...zs), zmax = Math.max(...zs), zmid = (zmin + zmax) / 2;
  // 只画后半个毛坯圆柱（剖开看），刀路画在剖面上
  const stock = new THREE.Mesh(new THREE.CylinderGeometry(rmax - 2, rmax - 2, zmax - zmin, 48, 1, false, Math.PI / 2, Math.PI),
    new THREE.MeshLambertMaterial({ color: '#C7CDD1', side: THREE.DoubleSide }));
  stock.rotation.z = Math.PI / 2; stock.position.set(zmid, 0, 0);
  s.add(stock);
  const tool = new THREE.Mesh(new THREE.ConeGeometry(3, 12, 16), new THREE.MeshLambertMaterial({ color: '#F2B705' }));
  tool.rotation.x = Math.PI;                         // 刀尖朝下，正好落在刀位点上
  s.add(tool);
  const trail = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: '#C62828' }));
  s.add(trail);
  cam.position.set(zmid, 40, (zmax - zmin) * 0.9 + 60);
  cam.lookAt(zmid, 5, 0);
  const P = pts.map((p) => [p[2], p[0] / 2, 0, p[3]]);
  gc = { s, cam, r, pts: P, tool, trail, i: 0, f: 0, done: [], render() {
    if (gcPlaying.value) {
      const a = this.pts[this.i], b = this.pts[this.i + 1];
      if (!b) { gcPlaying.value = false; } else {
        const L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
        this.f += (b[3] ? 6 : 1.2) / L;
        const p = [a[0] + (b[0] - a[0]) * Math.min(1, this.f), a[1] + (b[1] - a[1]) * Math.min(1, this.f)];
        this.tool.position.set(p[0], p[1] + 6, 0);
        if (!b[3]) { this.done.push(new THREE.Vector3(p[0], p[1], 0)); this.trail.geometry.setFromPoints(this.done); }
        if (this.f >= 1) { this.f = 0; this.i += 1; }
      }
    }
    this.r.render(this.s, this.cam);
  } };
  if (P.length) gc.tool.position.set(P[0][0], P[0][1] + 6, 0);
}
function playGcode() {
  initGc();
  if (!gc) return;
  gc.i = 0; gc.f = 0; gc.done = [];
  gcPlaying.value = true;
}
watch(sel, async (u) => {
  if (gc) { gc.r.dispose(); gc = null; }
  gcPlaying.value = false;
  if (u === 'key-01' || (u || '').startsWith('cnc-l01')) {
    try { await loadGcode(u); } catch (e) { gcode.value = ''; }
    await nextTick(); if (gcode.value) initGc();
  }
});

let off;
onMounted(async () => {
  try {
    layout.value = await get('/layout');
    ws = createWorkshop(host.value, layout.value, { onFrame: () => { if (gc) gc.render(); } });
    applyStatus();
    off = watch(() => [bus.machines, bus.agvs], applyStatus, { deep: true });
    if (route.query.gcode) sel.value = 'key-01';
    else if (route.query.unit) sel.value = String(route.query.unit);           // 数控编程页“到 3D 车间回放”带过来
  } catch (e) { err.value = '3D 车间载入失败：' + e.message; }
});
onUnmounted(() => {
  if (off) off();
  if (ws) ws.dispose();
  if (gc) gc.r.dispose();
});
</script>

<style scoped>
.wrap3d { position: relative; height: calc(100vh - 64px); }
.host { position: absolute; inset: 0; }
.legend { position: absolute; left: 16px; bottom: 16px; background: rgba(255, 255, 255, .92); border-radius: 8px; padding: 8px 12px;
  display: flex; gap: 12px; flex-wrap: wrap; }
.legend i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; margin-right: 5px; }
.panel { position: absolute; right: 16px; top: 16px; width: 340px; background: #fff; border-radius: 10px; border: 1px solid var(--line);
  padding: 14px 16px; max-height: calc(100% - 32px); overflow-y: auto; }
.panel h3 { font-size: 14px; margin: 6px 0; }
.x { position: absolute; right: 10px; top: 6px; border: 0; background: none; font-size: 20px; cursor: pointer; color: var(--muted); }
.gchost { width: 100%; height: 200px; margin-bottom: 8px; border-radius: 8px; overflow: hidden; }
.errbox { position: absolute; left: 16px; top: 16px; background: #fff; padding: 10px; border-radius: 8px; }
hr { border: 0; border-top: 1px solid var(--line); margin: 12px 0; }
</style>
