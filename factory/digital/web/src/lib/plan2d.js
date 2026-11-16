// 第 171b 轮：3D 车间的“平面图”——俯视厂区，白板手绘线条（rough.js，和白板图同一个库）。
// 和三维场景（workshop3d.js）同样的接口：update / flyZone / flyUnit / flyRect / overview / highlight / showRoute / clearRoute / resize / dispose，
// 点设备、点车间用回调 onPick(unit)、onZone(zone)。线条一次画好，状态变化只改灯的颜色。
import rough from 'roughjs';
import { HEX } from './workshop3d';

const S = 10;                      // 画布单位：分米（rough.js 的抖动按像素量级设计，按米画太乱）
const NS = 'http://www.w3.org/2000/svg';
const ZONE_FILL = ['#E3EEF8', '#E8F4E5', '#FBEEDC', '#EFE8F7', '#F9E4E4', '#E2F2F1', '#F3F1DE'];

function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

export function createPlan(host, L, { zones = [], onPick, onZone, unitLabel } = {}) {
  const [FW, FD] = L.floor;
  const svg = el('svg', { width: '100%', height: '100%', style: 'display:block;background:#FBFBF8;touch-action:none;cursor:grab' }, host);
  const rc = rough.svg(svg);
  const gBase = el('g', {}, svg), gZone = el('g', {}, svg), gUnit = el('g', {}, svg), gLamp = el('g', {}, svg);
  const gRoute = el('g', {}, svg), gAgv = el('g', {}, svg), gLab = el('g', { 'font-family': '"Noto Sans SC", "PingFang SC", sans-serif' }, svg);
  const gUlab = el('g', { 'font-family': '"IBM Plex Mono", monospace' }, gLab);
  const gUname = el('g', {}, gLab);
  const zoneTexts = [];
  const seed = (s) => [...String(s)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 9973, 7) + 1;   // 每台设备的线条固定，不每次乱抖

  // 厂房外墙、通道
  gBase.appendChild(rc.rectangle(0, 0, FW * S, FD * S, { stroke: '#5D6873', strokeWidth: 3, roughness: 1.2, seed: 3 }));
  for (const a of L.aisles || []) {
    gBase.appendChild(rc.line(10, a * S, FW * S - 10, a * S, { stroke: '#D9C98F', strokeWidth: 14, roughness: 0.6, seed: 5 }));
  }
  if ((L.aisles || []).length > 1) {
    const lo = Math.min(...L.aisles), hi = Math.max(...L.aisles);
    gBase.appendChild(rc.line(L.cross_x * S, lo * S, L.cross_x * S, hi * S, { stroke: '#D9C98F', strokeWidth: 14, roughness: 0.6, seed: 6 }));
  }
  // 车间
  const zoneRect = {};
  zones.filter((z) => !z.auto).forEach((z, i) => {
    const [x0, y0, x1, y1] = z.rect;
    zoneRect[z.id] = z.rect;
    const n = rc.rectangle(x0 * S, y0 * S, (x1 - x0) * S, (y1 - y0) * S,
      { fill: ZONE_FILL[i % ZONE_FILL.length], fillStyle: 'solid', stroke: '#7B8794', strokeWidth: 2.2, roughness: 1.4, seed: 11 + i });
    n.dataset.zone = z.id; n.style.cursor = 'pointer';
    gZone.appendChild(n);
    const fs = Math.max(30, Math.min((x1 - x0) * S / 9, 70));
    const tx = el('text', { x: (x0 + 1.5) * S, y: y0 * S + fs * 1.15, 'font-size': fs, 'font-weight': 700, fill: '#17212B', 'data-zone': z.id }, gLab);
    tx.textContent = z.name_shown || z.name;
    tx.style.cursor = 'pointer';
    zoneTexts.push(tx);
  });
  // 设备
  const lamps = {}, boxes = {};
  for (const [u, v] of Object.entries(L.units)) {
    const store = u.startsWith('store');
    const x = (v.x - v.w / 2) * S, y = (v.y - v.d / 2) * S, w = v.w * S, d = v.d * S;
    const n = rc.rectangle(x, y, w, d, { fill: store ? '#C9CFC6' : '#E6EAED', fillStyle: store ? 'cross-hatch' : 'hachure', hachureGap: 5,
      fillWeight: 0.8, stroke: '#3E4A55', strokeWidth: 1.4, roughness: 1, seed: seed(u) });
    n.dataset.unit = u; n.style.cursor = 'pointer';
    gUnit.appendChild(n);
    boxes[u] = [x, y, w, d];
    const r = Math.max(4, Math.min(w, d) * 0.16);
    lamps[u] = el('circle', { cx: x + w - r * 1.4, cy: y + r * 1.4, r, fill: HEX.idle, stroke: '#fff', 'stroke-width': 1.5, 'data-unit': u, style: 'cursor:pointer' }, gLamp);
    const t = el('text', { x: x + w / 2, y: y + d / 2, 'font-size': Math.max(6, Math.min(12, w / 5)), 'text-anchor': 'middle', 'dominant-baseline': 'middle',
      fill: '#17212B', 'data-unit': u, style: 'cursor:pointer' }, gUlab);
    t.textContent = u.toUpperCase();
    if (unitLabel) {
      const t2 = el('text', { x: x + w / 2, y: y + d + 8, 'font-size': 6, 'text-anchor': 'middle', fill: '#5D6873', 'data-unit': u }, gUname);
      t2.textContent = unitLabel(u);
    }
  }
  const agvs = {};
  for (const [a, [x, y]] of Object.entries(L.agv_home || {})) {
    agvs[a] = el('circle', { cx: x * S, cy: y * S, r: 7, fill: '#F2B705', stroke: '#6B4E00', 'stroke-width': 1.5, 'data-unit': a, style: 'cursor:pointer' }, gAgv);
  }
  const hl = el('rect', { fill: 'none', stroke: '#0E7C93', 'stroke-width': 4, rx: 4, visibility: 'hidden' }, svg);

  // ---- 视野（viewBox，单位分米），保持宽高比
  let vb = [0, 0, FW * S, FD * S], anim = null;
  function fit([x, y, w, h]) {
    const ar = host.clientWidth / Math.max(1, host.clientHeight);
    if (w / h > ar) { const nh = w / ar; return [x, y - (nh - h) / 2, w, nh]; }
    const nw = h * ar; return [x - (nw - w) / 2, y, nw, h];
  }
  function apply() {
    svg.setAttribute('viewBox', vb.join(' '));
    gUlab.style.display = vb[2] < 1100 ? '' : 'none';             // 放大到 110 米以内才显示设备号
    gUname.style.display = vb[2] < 450 ? '' : 'none';             // 45 米以内再显示设备名
    for (const z of zoneTexts) z.setAttribute('opacity', vb[2] < 1500 ? 0.22 : 1);   // 放大进车间后车间名变淡，不挡设备
  }
  function animate(to, ms = 700) {
    const from = vb.slice(), t0 = performance.now();
    cancelAnimationFrame(anim);
    const stepf = () => {
      const k = Math.min(1, (performance.now() - t0) / ms), e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
      vb = from.map((a, i) => a + (to[i] - a) * e); apply();
      if (k < 1) anim = requestAnimationFrame(stepf);
    };
    stepf();
  }
  function flyRect([x0, y0, x1, y1]) {
    const m = Math.max(x1 - x0, y1 - y0) * 0.06 + 2;
    animate(fit([(x0 - m) * S, (y0 - m) * S, (x1 - x0 + 2 * m) * S, (y1 - y0 + 2 * m) * S]));
  }
  const overview = () => flyRect([0, 0, FW, FD]);
  const flyZone = (id) => zoneRect[id] && flyRect(zoneRect[id]);
  function flyUnit(u) {
    const b = boxes[u];
    let cx, cy;
    if (b) { cx = (b[0] + b[2] / 2) / S; cy = (b[1] + b[3] / 2) / S; } else if (agvs[u]) { cx = +agvs[u].getAttribute('cx') / S; cy = +agvs[u].getAttribute('cy') / S; } else return false;
    flyRect([cx - 14, cy - 9, cx + 14, cy + 9]);
    return true;
  }
  function highlight(u) {
    const b = boxes[u];
    if (!b) { hl.setAttribute('visibility', 'hidden'); return; }
    hl.setAttribute('x', b[0] - 4); hl.setAttribute('y', b[1] - 4); hl.setAttribute('width', b[2] + 8); hl.setAttribute('height', b[3] + 8);
    hl.setAttribute('visibility', 'visible');
  }
  // 工艺路线：手绘箭头 + 序号
  function clearRoute() { while (gRoute.firstChild) gRoute.removeChild(gRoute.firstChild); }
  function showRoute(units) {
    clearRoute();
    const pts = units.map((u) => boxes[u]).filter(Boolean).map((b) => [b[0] + b[2] / 2, b[1] + b[3] / 2]);
    for (let i = 0; i + 1 < pts.length; i++) {
      const [a, b] = [pts[i], pts[i + 1]];
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (len < 1) continue;
      const nx = -(b[1] - a[1]) / len, ny = (b[0] - a[0]) / len, bow = Math.min(60, len * 0.15);
      const mid = [(a[0] + b[0]) / 2 + nx * bow, (a[1] + b[1]) / 2 + ny * bow];
      gRoute.appendChild(rc.curve([a, mid, b], { stroke: '#C2410C', strokeWidth: 2.4, roughness: 0.9, seed: 100 + i }));
      const dx = b[0] - mid[0], dy = b[1] - mid[1], dl = Math.hypot(dx, dy) || 1, ux = dx / dl, uy = dy / dl, s = 12;
      gRoute.appendChild(rc.polygon([b, [b[0] - ux * s - uy * s * 0.5, b[1] - uy * s + ux * s * 0.5], [b[0] - ux * s + uy * s * 0.5, b[1] - uy * s - ux * s * 0.5]],
        { fill: '#C2410C', fillStyle: 'solid', stroke: '#C2410C', roughness: 0.5, seed: 200 + i }));
      const n = el('text', { x: mid[0], y: mid[1], 'font-size': 14, 'font-weight': 700, fill: '#C2410C', 'text-anchor': 'middle', stroke: '#fff', 'stroke-width': 3, 'paint-order': 'stroke' }, gRoute);
      n.textContent = String(i + 1);
    }
  }
  function update(ms, ag) {
    for (const [u, c] of Object.entries(lamps)) c.setAttribute('fill', HEX[ms?.[u]?.state] || HEX.idle);
    for (const [a, c] of Object.entries(agvs)) {
      const s = ag?.[a];
      if (s) { c.setAttribute('cx', s.x_m * S); c.setAttribute('cy', s.y_m * S); }
    }
  }

  // ---- 鼠标：滚轮缩放（以光标为中心）、拖动平移、点击
  let drag = null;
  function toWorld(e) {
    const r = svg.getBoundingClientRect();
    return [vb[0] + (e.clientX - r.left) / r.width * vb[2], vb[1] + (e.clientY - r.top) / r.height * vb[3]];
  }
  function wheel(e) {
    e.preventDefault();
    cancelAnimationFrame(anim);
    const [wx, wy] = toWorld(e), k = Math.exp(e.deltaY * 0.0015);
    const w = Math.min(FW * S * 3, Math.max(80, vb[2] * k)), h = w * vb[3] / vb[2];
    vb = [wx - (wx - vb[0]) * w / vb[2], wy - (wy - vb[1]) * h / vb[3], w, h]; apply();
  }
  function down(e) { drag = { x: e.clientX, y: e.clientY, vb: vb.slice(), moved: false }; try { svg.setPointerCapture(e.pointerId); } catch (err) { /* 合成事件没有指针 */ } svg.style.cursor = 'grabbing'; }
  function move(e) {
    if (!drag) return;
    const r = svg.getBoundingClientRect(), dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.hypot(dx, dy) > 4) drag.moved = true;
    if (drag.moved) { vb = [drag.vb[0] - dx / r.width * vb[2], drag.vb[1] - dy / r.height * vb[3], vb[2], vb[3]]; apply(); }
  }
  function up(e) {
    svg.style.cursor = 'grab';
    if (!drag) return;
    const moved = drag.moved;
    drag = null;
    if (moved) return;
    let t = document.elementFromPoint(e.clientX, e.clientY);
    while (t && t !== svg && !(t.dataset && (t.dataset.unit || t.dataset.zone))) t = t.parentNode;
    if (!t || t === svg) return;
    if (t.dataset.unit) onPick && onPick(t.dataset.unit);
    else if (t.dataset.zone) onZone && onZone(t.dataset.zone);
  }
  svg.addEventListener('wheel', wheel, { passive: false });
  svg.addEventListener('pointerdown', down);
  svg.addEventListener('pointermove', move);
  svg.addEventListener('pointerup', up);
  function resize() { vb = fit(vb); apply(); }
  window.addEventListener('resize', resize);
  vb = fit([-20, -20, FW * S + 40, FD * S + 40]); apply();

  return {
    update, flyRect, flyZone, flyUnit, overview, highlight, showRoute, clearRoute, resize,
    dispose() { cancelAnimationFrame(anim); window.removeEventListener('resize', resize); svg.remove(); },
  };
}
