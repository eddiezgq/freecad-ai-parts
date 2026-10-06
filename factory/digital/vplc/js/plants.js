// WenQuest virtual machines for PLC labs (第 18 轮 〔VP〕): the machine model (I/O, physics, faults) and its 3D view.
//
// Each machine is a factory WQPLANTS.<name>(options) returning a plant for WQ.lab({view: "plc", plant}):
//   io        the machine's I/O table (as on the real machine's wiring diagram): use it as plc.io
//   panel     the operator panel (push buttons, NC buttons, switches)
//   faults    faults the student (or a test) can inject
//   reset(s, {faults, seed}), inputs(s) -> {name: value}, step(dt_ms, outputs, s), read(s, name)
//   build3d(st, THREE) -> view; draw3d(view, s, io): the 3D picture (three.js primitives, no network)
// The physics is deliberately simple (kinematics, first-order lags) but it has the things a commissioning engineer
// meets: sensor bounce, travel times, limit switches, analogue noise, stuck sensors, jammed cylinders, broken wires.
// A machine also reports hazards (read(s, "hazard")): a test can demand { never: { hazard: true } }.
(function (root) {
"use strict";

// ---------------------------------------------------------------- helpers
function rng(seed) {   // mulberry32, the same in every browser
  let a = (seed >>> 0) || 1;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const approach = (x, target, rate, dt) => (x < target ? Math.min(target, x + rate * dt) : Math.max(target, x - rate * dt));
// a bouncing contact: after a change the reading chatters for `ms` (the reason for input filters, Ch. 3 and 6)
function bounce(s, key, v, now, ms) {
  const b = s._b || (s._b = {});
  const c = b[key] || (b[key] = { v, t: -1e9 });
  if (c.v !== v) { c.v = v; c.t = now; }
  if (ms > 0 && now - c.t < ms) return Math.floor((now - c.t) / 2) % 2 === 0 ? v : !v;
  return v;
}

// 3D building blocks
function kit3d(st, THREE) {
  const mats = {};
  const mat = (color, opts = {}) => {
    const k = color + JSON.stringify(opts);
    return mats[k] || (mats[k] = new THREE.MeshStandardMaterial(Object.assign({ color, roughness: 0.6, metalness: 0.1 }, opts)));
  };
  const add = (obj, parent) => { obj.castShadow = true; obj.receiveShadow = true; (parent || st.scene).add(obj); return obj; };
  const box = (w, h, d, color, x, y, z, parent) => { const m = add(new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(color)), parent); m.position.set(x, y, z); return m; };
  const cyl = (r, h, color, x, y, z, parent, axis) => {
    const m = add(new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 24), mat(color)), parent);
    if (axis === "x") m.rotation.z = Math.PI / 2; if (axis === "z") m.rotation.x = Math.PI / 2;
    m.position.set(x, y, z); return m;
  };
  const lamp = (r, color, x, y, z, parent) => {
    const m = add(new THREE.Mesh(new THREE.SphereGeometry(r, 20, 14), new THREE.MeshStandardMaterial({ color: 0x333333, emissive: color, emissiveIntensity: 0, roughness: 0.3 })), parent);
    m.position.set(x, y, z); m.userData.on = (v) => { m.material.emissiveIntensity = v ? 1.6 : 0; m.material.color.setHex(v ? color : 0x333333); };
    return m;
  };
  const label = (text, x, y, z, size = 0.12, parent) => {
    const c = document.createElement("canvas"); c.width = 256; c.height = 64;
    const g = c.getContext("2d"); g.font = "bold 34px system-ui, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillStyle = "rgba(255,255,255,0.85)"; g.fillRect(0, 8, 256, 48); g.fillStyle = "#1f2a33"; g.fillText(text, 128, 33);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false }));
    sp.scale.set(size * 4, size, 1); sp.position.set(x, y, z); sp.renderOrder = 10;
    (parent || st.scene).add(sp); return sp;
  };
  const beam = (from, to, color) => {
    const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...from), new THREE.Vector3(...to)]);
    const l = new THREE.Line(g, new THREE.LineDashedMaterial({ color, dashSize: 0.03, gapSize: 0.02 }));
    l.computeLineDistances(); st.scene.add(l);
    l.userData.on = (v) => { l.material.color.setHex(v ? 0xd1242f : 0x9aa7b0); };
    return l;
  };
  const camera = (pos, target) => { st.camera.position.set(...pos); st.camera.lookAt(new THREE.Vector3(...target)); st.target = target; };
  return { mat, box, cyl, lamp, label, beam, camera };
}

// ---------------------------------------------------------------- 1. traffic light (crossroads)
// Outputs: NS_R/Y/G, EW_R/Y/G (north–south, east–west lamps), P_Wait (pedestrian "wait" lamp); inputs: S_Ped (request),
// S_Night (night mode switch). Hazard: both directions show green or yellow at the same time.
function traffic(o = {}) {
  const io = [
    { name: "S_Ped", addr: "%IX0.0", dir: "in", comment: ["行人过街请求按钮", "Pedestrian request button"] },
    { name: "S_Night", addr: "%IX0.1", dir: "in", comment: ["夜间模式开关", "Night mode switch"] },
    { name: "NS_R", addr: "%QX0.0", dir: "out", comment: ["南北红灯", "North–south red"] },
    { name: "NS_Y", addr: "%QX0.1", dir: "out", comment: ["南北黄灯", "North–south yellow"] },
    { name: "NS_G", addr: "%QX0.2", dir: "out", comment: ["南北绿灯", "North–south green"] },
    { name: "EW_R", addr: "%QX0.3", dir: "out", comment: ["东西红灯", "East–west red"] },
    { name: "EW_Y", addr: "%QX0.4", dir: "out", comment: ["东西黄灯", "East–west yellow"] },
    { name: "EW_G", addr: "%QX0.5", dir: "out", comment: ["东西绿灯", "East–west green"] },
    { name: "P_Wait", addr: "%QX0.6", dir: "out", comment: ["行人“请等待”指示灯", "Pedestrian 'wait' lamp"] },
  ];
  const go = (out, d) => out[d + "_G"] || out[d + "_Y"];
  return {
    io,
    panel: [{ name: "S_Ped", kind: "push", label: ["行人请求", "Pedestrian"] }, { name: "S_Night", kind: "switch", label: ["夜间模式", "Night mode"] }],
    faults: [{ id: "lampNS", name: ["南北绿灯烧坏", "NS green lamp burnt out"] }],
    reset(s, opt) {
      s.f = (opt && opt.faults) || {}; s.t = 0; s.hazard = false; s.out = {};
      s.cars = [{ d: "NS", x: -6 }, { d: "NS", x: -12 }, { d: "EW", x: -5 }, { d: "EW", x: -10.5 }];
      s.lightNS = "off"; s.lightEW = "off"; s.yellowTime = 0;
    },
    inputs() { return {}; },
    step(dt, out, s) {
      s.t += dt; s.out = out;
      if (go(out, "NS") && go(out, "EW")) s.hazard = true;
      const ns = out.NS_G && !s.f.lampNS ? "G" : out.NS_Y ? "Y" : out.NS_R ? "R" : "off";
      const ew = out.EW_G ? "G" : out.EW_Y ? "Y" : out.EW_R ? "R" : "off";
      s.lightNS = ns; s.lightEW = ew;
      // cars: drive at 6 m/s, stop before the stop line (x = -2.5) unless green; leave and come back
      for (const c of s.cars) {
        const light = c.d === "NS" ? ns : ew;
        const ahead = s.cars.filter((k) => k.d === c.d && k.x > c.x).reduce((m, k) => Math.min(m, k.x), 1e9);
        let v = 6;
        if (c.x < -2.5 && c.x > -4.5 && light !== "G") v = 0;
        if (ahead - c.x < 4) v = 0;
        c.x += v * dt / 1000;
        if (c.x > 12) c.x -= 24;
      }
    },
    read(s, n) { if (n === "hazard") return s.hazard; return undefined; },
    build3d(st, THREE) {
      const K = kit3d(st, THREE);
      K.box(30, 0.02, 4, 0x55606a, 0, 0.01, 0); K.box(4, 0.021, 30, 0x55606a, 0, 0.011, 0);
      for (let k = -14; k < 14; k += 2) { K.box(1, 0.025, 0.1, 0xffffff, k + 0.5, 0.012, 0); K.box(0.1, 0.026, 1, 0xffffff, 0, 0.013, k + 0.5); }
      const head = (x, z, rot, name) => {
        const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = rot; st.scene.add(g);
        K.cyl(0.06, 3, 0x30363d, 0, 1.5, 0, g); K.box(0.35, 1.0, 0.3, 0x24292f, 0, 3.0, 0, g);
        const r = K.lamp(0.11, 0xff3b30, 0, 3.32, 0.16, g), y = K.lamp(0.11, 0xffb000, 0, 3.0, 0.16, g), gr = K.lamp(0.11, 0x2ecc71, 0, 2.68, 0.16, g);
        K.label(name, 0, 3.8, 0, 0.6, g);
        return { r, y, g: gr };
      };
      const v = { ns: head(2.4, 2.4, 0, "NS"), ew: head(-2.4, 2.4, Math.PI / 2, "EW"), cars: [], K };
      v.wait = K.lamp(0.12, 0xffb000, 2.6, 1.2, -2.6);
      K.label("P", 2.6, 1.6, -2.6, 0.45);
      for (let k = 0; k < 4; k++) v.cars.push(K.box(1.8, 0.8, 0.9, [0x1f6feb, 0xc2570c, 0x8250df, 0x1a7f37][k], 0, 0.5, 0));
      K.camera([11, 10, 13], [0, 0.5, 0]);
      return v;
    },
    draw3d(v, s) {
      const o = s.out || {};
      v.ns.r.userData.on(o.NS_R); v.ns.y.userData.on(o.NS_Y); v.ns.g.userData.on(o.NS_G && !(s.f || {}).lampNS);
      v.ew.r.userData.on(o.EW_R); v.ew.y.userData.on(o.EW_Y); v.ew.g.userData.on(o.EW_G);
      v.wait.userData.on(o.P_Wait);
      (s.cars || []).forEach((c, k) => {
        const m = v.cars[k];
        if (c.d === "NS") { m.position.set(1, 0.5, -c.x); m.rotation.y = Math.PI / 2; } else { m.position.set(c.x, 0.5, -1); m.rotation.y = 0; }
      });
    },
  };
}

// ---------------------------------------------------------------- 2. three-floor elevator
// Inputs: floor sensors B_F1..B_F3 (flags at each floor), limit switches S_LowLim / S_TopLim (NC: FALSE = hit), call
// buttons S_C1..S_C3, door sensors B_DoorOpen / B_DoorClosed. Outputs: K_Up, K_Down (hoist contactors), Y_DoorOpen,
// Y_DoorClose, H_C1..H_C3 (call lamps). Hazards: both contactors on; moving with the door open; overtravel.
function elevator(o = {}) {
  const io = [
    { name: "B_F1", addr: "%IX0.0", dir: "in", comment: ["1 楼平层传感器", "Floor 1 level sensor"] },
    { name: "B_F2", addr: "%IX0.1", dir: "in", comment: ["2 楼平层传感器", "Floor 2 level sensor"] },
    { name: "B_F3", addr: "%IX0.2", dir: "in", comment: ["3 楼平层传感器", "Floor 3 level sensor"] },
    { name: "S_LowLim", addr: "%IX0.3", dir: "in", comment: ["下极限开关（常闭）", "Bottom limit (NC)"] },
    { name: "S_TopLim", addr: "%IX0.4", dir: "in", comment: ["上极限开关（常闭）", "Top limit (NC)"] },
    { name: "S_C1", addr: "%IX0.5", dir: "in", comment: ["1 楼呼梯按钮", "Call button floor 1"] },
    { name: "S_C2", addr: "%IX0.6", dir: "in", comment: ["2 楼呼梯按钮", "Call button floor 2"] },
    { name: "S_C3", addr: "%IX0.7", dir: "in", comment: ["3 楼呼梯按钮", "Call button floor 3"] },
    { name: "B_DoorOpen", addr: "%IX1.0", dir: "in", comment: ["门开到位", "Door fully open"] },
    { name: "B_DoorClosed", addr: "%IX1.1", dir: "in", comment: ["门关到位", "Door fully closed"] },
    { name: "K_Up", addr: "%QX0.0", dir: "out", comment: ["上行接触器", "Hoist up contactor"] },
    { name: "K_Down", addr: "%QX0.1", dir: "out", comment: ["下行接触器", "Hoist down contactor"] },
    { name: "Y_DoorOpen", addr: "%QX0.2", dir: "out", comment: ["开门", "Open door"] },
    { name: "Y_DoorClose", addr: "%QX0.3", dir: "out", comment: ["关门", "Close door"] },
    { name: "H_C1", addr: "%QX0.4", dir: "out", comment: ["1 楼呼梯指示", "Call lamp floor 1"] },
    { name: "H_C2", addr: "%QX0.5", dir: "out", comment: ["2 楼呼梯指示", "Call lamp floor 2"] },
    { name: "H_C3", addr: "%QX0.6", dir: "out", comment: ["3 楼呼梯指示", "Call lamp floor 3"] },
  ];
  const H = 3.0, SPEED = 1.0, FLAG = 0.04;   // floor height m, car speed m/s, half-length of a level flag m
  return {
    io,
    panel: [1, 2, 3].map((k) => ({ name: "S_C" + k, kind: "push", label: [`${k} 楼呼梯`, `Call ${k}`] })),
    faults: [{ id: "f2dead", name: ["2 楼平层传感器坏（常为 0）", "Floor-2 sensor dead (always 0)"] },
             { id: "doorJam", name: ["门卡住（关不上）", "Door jammed (will not close)"] }],
    reset(s, opt) {
      s.f = (opt && opt.faults) || {}; s.t = 0; s.z = (o.startFloor || 1) * H - H; s.v = 0; s.door = 1; s.hazard = false; s.why = ""; s.out = {};
      s.trips = 0; s.lastFloor = Math.round(s.z / H) + 1;
    },
    inputs(s) {
      const at = (k) => Math.abs(s.z - (k - 1) * H) <= FLAG;
      return {
        B_F1: at(1), B_F2: at(2) && !s.f.f2dead, B_F3: at(3),
        S_LowLim: s.z > -0.15, S_TopLim: s.z < 2 * H + 0.15,
        B_DoorOpen: s.door >= 0.99, B_DoorClosed: s.door <= 0.01,
      };
    },
    step(dt, out, s) {
      s.t += dt; s.out = out;
      const sec = dt / 1000;
      if (out.K_Up && out.K_Down) { s.hazard = true; s.why = "both"; }
      const target = out.K_Up && !out.K_Down ? SPEED : out.K_Down && !out.K_Up ? -SPEED : 0;
      // motoring: 2.5 m/s² up to speed; contactor off: the brake drops and stops the car within about 1 cm
      s.v = approach(s.v, target, target === 0 || Math.sign(target) !== Math.sign(s.v) ? 60 : 2.5, sec);
      s.z += s.v * sec;
      if (Math.abs(s.v) > 0.02 && s.door > 0.05) { s.hazard = true; s.why = "door"; }
      if (s.z < -0.3 || s.z > 2 * H + 0.3) { s.hazard = true; s.why = "overtravel"; s.z = clamp(s.z, -0.3, 2 * H + 0.3); s.v = 0; }
      const dTarget = out.Y_DoorOpen && !out.Y_DoorClose ? 1 : out.Y_DoorClose && !out.Y_DoorOpen && !s.f.doorJam ? 0 : s.door;
      s.door = approach(s.door, dTarget, 1 / 1.5, sec);   // 1.5 s to open or close
      if (s.f.doorJam && out.Y_DoorClose) s.door = Math.max(s.door, 0.3);
      const fl = Math.round(s.z / H) + 1;
      if (Math.abs(s.z - (fl - 1) * H) <= FLAG && Math.abs(s.v) < 0.05 && fl !== s.lastFloor) { s.trips++; s.lastFloor = fl; }
    },
    read(s, n) {
      if (n === "hazard") return s.hazard;
      if (n === "floor") { const fl = Math.round(s.z / H) + 1; return Math.abs(s.z - (fl - 1) * H) <= FLAG ? fl : 0; }
      if (n === "z") return s.z;
      if (n === "door") return s.door;
      if (n === "trips") return s.trips;
      return undefined;
    },
    build3d(st, THREE) {
      const K = kit3d(st, THREE);
      const v = { K };
      K.box(2.4, 0.1, 2.4, 0x8c959f, 0, 0.05, 0);
      for (const x of [-1.15, 1.15]) for (const z of [-1.15, 1.15]) K.box(0.08, 3 * H + 0.6, 0.08, 0x57606a, x, (3 * H + 0.6) / 2, z);
      for (let k = 0; k < 3; k++) {
        K.box(2.4, 0.06, 0.5, 0xd0d7de, 0, k * H, 1.45);
        K.label(`${k + 1}F`, -1.7, k * H + 0.6, 1.2, 0.5);
        v["lamp" + (k + 1)] = K.lamp(0.07, 0xffb000, 1.45, k * H + 1.1, 1.25);
        v["flag" + (k + 1)] = K.box(0.05, 0.08, 0.05, 0x1a7f37, 1.05, k * H + 0.2, -1.0);
      }
      v.car = new THREE.Group(); st.scene.add(v.car);
      K.box(1.8, 0.08, 1.8, 0x6e7781, 0, 0, 0, v.car); K.box(1.8, 0.08, 1.8, 0x6e7781, 0, 2.2, 0, v.car);
      K.box(0.06, 2.2, 1.8, 0xafb8c1, -0.9, 1.1, 0, v.car); K.box(0.06, 2.2, 1.8, 0xafb8c1, 0.9, 1.1, 0, v.car); K.box(1.8, 2.2, 0.06, 0xafb8c1, 0, 1.1, -0.9, v.car);
      v.doorL = K.box(0.9, 2.1, 0.05, 0x8ea8c3, -0.45, 1.1, 0.92, v.car); v.doorR = K.box(0.9, 2.1, 0.05, 0x8ea8c3, 0.45, 1.1, 0.92, v.car);
      v.sensor = K.box(0.1, 0.1, 0.1, 0x24292f, 1.0, 0.2, -0.95, v.car);
      v.rope = K.cyl(0.015, 1, 0x24292f, 0, 0, 0);
      v.motor = K.cyl(0.35, 0.5, 0x6e7781, 0, 3 * H + 0.75, 0, null, "x");
      K.camera([12, 8, 15], [0, 4.2, 0]);
      return v;
    },
    draw3d(v, s) {
      const z = s.z || 0, o = s.out || {};
      v.car.position.set(0, z + 0.04, 0);
      const open = (s.door || 0) * 0.85;
      v.doorL.position.x = -0.45 - open; v.doorR.position.x = 0.45 + open;
      const top = 3 * H + 0.5, len = top - (z + 2.25);
      v.rope.scale.y = Math.max(0.01, len); v.rope.position.set(0, z + 2.25 + len / 2, 0);
      v.motor.material = v.K.mat(o.K_Up || o.K_Down ? 0x2da44e : 0x6e7781);
      for (let k = 1; k <= 3; k++) v["lamp" + k].userData.on(o["H_C" + k]);
    },
  };
}

// ---------------------------------------------------------------- 3. sorting conveyor (the digital factory's finished-part sorter)
// Parts arrive at the entry; a color sensor (red/blue), an inductive sensor (metal) and a height sensor (tall) look at
// them on the way; three pushers put metal parts into bin 1, red plastic into bin 2, blue plastic into bin 3; anything
// else runs off the end into the reject box. Inputs: B_Entry, B_Red, B_Metal, B_Tall, B_Y1Out/B_Y2Out/B_Y3Out (pusher
// extended), B_Y1In.. (retracted), B_End; outputs: M_Belt, Y1..Y3 (pushers, spring return), H_Full (bin full lamp).
function sorter(o = {}) {
  const io = [
    { name: "B_Entry", addr: "%IX0.0", dir: "in", comment: ["入口光电", "Entry photo sensor"] },
    { name: "B_Insp", addr: "%IX0.1", dir: "in", comment: ["检测工位到位光电", "Part at the inspection station"] },
    { name: "B_Red", addr: "%IX0.2", dir: "in", comment: ["颜色传感器（红）", "Colour sensor (red)"] },
    { name: "B_Metal", addr: "%IX0.3", dir: "in", comment: ["电感式传感器（金属）", "Inductive sensor (metal)"] },
    { name: "B_Tall", addr: "%IX1.6", dir: "in", comment: ["高度检测（高件）", "Height sensor (tall part)"] },
    { name: "B_P1", addr: "%IX0.4", dir: "in", comment: ["推杆 1 前光电", "Photo sensor at pusher 1"] },
    { name: "B_P2", addr: "%IX0.5", dir: "in", comment: ["推杆 2 前光电", "Photo sensor at pusher 2"] },
    { name: "B_P3", addr: "%IX0.6", dir: "in", comment: ["推杆 3 前光电", "Photo sensor at pusher 3"] },
    { name: "B_Y1Out", addr: "%IX1.0", dir: "in", comment: ["推杆 1 伸出到位", "Pusher 1 extended"] },
    { name: "B_Y2Out", addr: "%IX1.1", dir: "in", comment: ["推杆 2 伸出到位", "Pusher 2 extended"] },
    { name: "B_Y3Out", addr: "%IX1.2", dir: "in", comment: ["推杆 3 伸出到位", "Pusher 3 extended"] },
    { name: "B_End", addr: "%IX1.3", dir: "in", comment: ["末端光电（废品）", "End sensor (reject)"] },
    { name: "S_Start", addr: "%IX1.4", dir: "in", comment: ["启动按钮", "Start button"] },
    { name: "S_Stop", addr: "%IX1.5", dir: "in", comment: ["停止按钮（常闭）", "Stop button (NC)"] },
    { name: "M_Belt", addr: "%QX0.0", dir: "out", comment: ["输送带电机", "Belt motor"] },
    { name: "Y1", addr: "%QX0.1", dir: "out", comment: ["推杆 1 电磁阀", "Pusher 1 valve"] },
    { name: "Y2", addr: "%QX0.2", dir: "out", comment: ["推杆 2 电磁阀", "Pusher 2 valve"] },
    { name: "Y3", addr: "%QX0.3", dir: "out", comment: ["推杆 3 电磁阀", "Pusher 3 valve"] },
    { name: "H_Run", addr: "%QX0.4", dir: "out", comment: ["运行指示灯", "Running lamp"] },
    { name: "H_Fault", addr: "%QX0.5", dir: "out", comment: ["故障指示灯", "Fault lamp"] },
  ];
  const L = 3.0, V = 0.2;                           // belt length m, speed m/s
  const POS = { entry: 0.15, insp: 0.7, p1: 1.4, p2: 1.9, p3: 2.4, end: 2.9 };   // the inspection sensors all look at x = 0.7 m
  const KINDS = { metal: { color: 0x8c959f, h: 0.06 }, red: { color: 0xd1242f, h: 0.06 }, blue: { color: 0x1f6feb, h: 0.06 }, tallred: { color: 0xd1242f, h: 0.11 } };
  const bin = { metal: 1, red: 2, blue: 3 };
  return {
    io,
    panel: [{ name: "S_Start", kind: "push", label: ["启动", "Start"] }, { name: "S_Stop", kind: "nc-push", label: ["停止", "Stop"] }],
    faults: [{ id: "y2stuck", name: ["推杆 2 卡住", "Pusher 2 stuck"] }, { id: "colorDirty", name: ["颜色传感器脏（漏检）", "Colour sensor dirty (misses)"] },
             { id: "bounce", name: ["入口光电抖动", "Entry sensor bounce"] }],
    reset(s, opt) {
      s.f = (opt && opt.faults) || {}; s.t = 0; s.out = {};
      s.rand = rng((opt && opt.seed) || o.seed || 7);
      s.seq = (o.sequence || ["metal", "red", "blue", "red", "tallred", "metal", "blue", "red"]).slice();
      s.parts = []; s.next = 1500; s.y = [0, 0, 0];
      s.bins = { 1: [], 2: [], 3: [], reject: [] }; s.wrong = 0; s.sorted = 0; s.hazard = false; s.spawned = 0;
    },
    inputs(s) {
      const near = (x, w = 0.04, pred = () => true) => s.parts.some((p) => !p.gone && Math.abs(p.x - x) < w && pred(p));
      const dirty = s.f.colorDirty && Math.floor(s.t / 1700) % 2 === 0;
      return {
        B_Entry: bounce(s, "entry", near(POS.entry, 0.05), s.t, s.f.bounce ? 40 : 0),
        B_Insp: near(POS.insp, 0.03),
        B_Red: !dirty && near(POS.insp, 0.05, (p) => p.kind === "red" || p.kind === "tallred"),
        B_Metal: near(POS.insp, 0.05, (p) => p.kind === "metal"),
        B_Tall: near(POS.insp, 0.05, (p) => KINDS[p.kind].h > 0.08),
        B_P1: near(POS.p1, 0.03), B_P2: near(POS.p2, 0.03), B_P3: near(POS.p3, 0.03),
        B_Y1Out: s.y[0] > 0.97, B_Y2Out: s.y[1] > 0.97, B_Y3Out: s.y[2] > 0.97,
        B_End: near(POS.end, 0.04),
      };
    },
    step(dt, out, s) {
      s.t += dt; s.out = out;
      const sec = dt / 1000;
      // parts arrive every 3 s while the belt runs and the entry is clear
      if (out.M_Belt) s.next -= dt;
      if (s.next <= 0 && s.seq.length && !s.parts.some((p) => !p.gone && p.x < 0.35)) {
        s.parts.push({ kind: s.seq.shift(), x: 0.0, z: 0, gone: false, id: ++s.spawned }); s.next = o.interval || 3000;
      }
      ["Y1", "Y2", "Y3"].forEach((k, i) => {
        const stuck = i === 1 && s.f.y2stuck;
        s.y[i] = approach(s.y[i], out[k] && !stuck ? 1 : 0, 1 / 0.25, sec);   // 0.25 s stroke, spring return
      });
      for (const p of s.parts) {
        if (p.gone) continue;
        // a pusher at its station moves the part sideways off the belt
        const st = [POS.p1, POS.p2, POS.p3].findIndex((x) => Math.abs(p.x - x) < 0.06);
        if (st >= 0 && s.y[st] > 0.2) { p.z = Math.max(p.z, s.y[st] * 0.45); }
        if (p.z >= 0.4) { p.gone = true; s.bins[st + 1].push(p.kind); s.sorted++; if (bin[p.kind.replace("tall", "")] !== st + 1 || p.kind === "tallred") s.wrong++; continue; }
        if (out.M_Belt && p.z < 0.05) p.x += V * sec;
        if (p.x >= L) { p.gone = true; s.bins.reject.push(p.kind); if (p.kind !== "tallred") s.wrong++; }
      }
      s.parts = s.parts.filter((p) => !p.gone);
    },
    read(s, n) {
      if (n === "hazard") return s.hazard;
      if (n === "wrong") return s.wrong;
      if (n === "sorted") return s.sorted;
      if (n === "bin1") return s.bins[1].length;
      if (n === "bin2") return s.bins[2].length;
      if (n === "bin3") return s.bins[3].length;
      if (n === "rejects") return s.bins.reject.length;
      if (n === "done") return !s.seq.length && !s.parts.some((p) => !p.gone);
      return undefined;
    },
    build3d(st, THREE) {
      const K = kit3d(st, THREE);
      const v = { K, parts: {} };
      K.box(L + 0.2, 0.06, 0.32, 0x2d333b, L / 2, 0.75, 0);
      for (const x of [0.1, L - 0.1]) K.cyl(0.04, 0.34, 0x8c959f, x, 0.78, 0, null, "z");
      for (const x of [0.2, L / 2, L - 0.2]) for (const z of [-0.14, 0.14]) K.box(0.05, 0.72, 0.05, 0x57606a, x, 0.36, z);
      const sensor = (x, name, color) => { K.box(0.06, 0.18, 0.06, 0x24292f, x, 0.9, -0.22); K.label(name, x, 1.15, -0.22, 0.11); return K.beam([x, 0.82, -0.2], [x, 0.82, 0.2], color); };
      K.box(0.3, 0.05, 0.4, 0x24292f, POS.insp, 1.25, 0); K.cyl(0.04, 0.1, 0xd1242f, POS.insp - 0.08, 1.18, 0); K.cyl(0.04, 0.1, 0x8c959f, POS.insp + 0.08, 1.18, 0);
      v.beams = { entry: sensor(POS.entry, "B_Entry"), insp: sensor(POS.insp, "B_Insp"),
        p1: sensor(POS.p1 - 0.12, "B_P1"), p2: sensor(POS.p2 - 0.12, "B_P2"), p3: sensor(POS.p3 - 0.12, "B_P3"), end: sensor(POS.end, "B_End") };
      v.push = [POS.p1, POS.p2, POS.p3].map((x, i) => {
        K.box(0.14, 0.1, 0.3, 0x6e7781, x, 0.85, -0.42);
        const rod = K.box(0.12, 0.08, 0.04, 0xe1e4e8, x, 0.83, -0.2);
        K.box(0.4, 0.3, 0.3, [0x8c959f, 0xd1242f, 0x1f6feb][i], x, 0.15, 0.45);
        K.label(`Y${i + 1} → ${i + 1}`, x, 0.45, 0.62, 0.12);
        return rod;
      });
      K.box(0.4, 0.3, 0.4, 0x24292f, L + 0.2, 0.15, 0); K.label("reject", L + 0.2, 0.45, 0.2, 0.12);
      v.run = K.lamp(0.05, 0x2ecc71, 0.1, 1.1, 0.3);
      K.camera([1.6, 2.6, 3.4], [1.5, 0.75, 0]);
      return v;
    },
    draw3d(v, s) {
      const ins = this.inputs(s);
      v.beams.entry.userData.on(ins.B_Entry); v.beams.insp.userData.on(ins.B_Insp); v.beams.p1.userData.on(ins.B_P1); v.beams.p2.userData.on(ins.B_P2); v.beams.p3.userData.on(ins.B_P3); v.beams.end.userData.on(ins.B_End);
      v.push.forEach((rod, i) => { rod.position.z = -0.2 + (s.y[i] || 0) * 0.35; });
      v.run.userData.on((s.out || {}).H_Run);
      const live = new Set();
      for (const p of s.parts || []) {
        if (p.gone) continue;
        live.add(p.id);
        let m = v.parts[p.id];
        if (!m) { const k = KINDS[p.kind]; m = v.parts[p.id] = v.K.cyl(0.07, k.h, k.color, 0, 0, 0); m.userData.h = k.h; }
        m.position.set(p.x, 0.78 + m.userData.h / 2, p.z);
      }
      for (const [id, m] of Object.entries(v.parts)) if (!live.has(+id)) { m.parent.remove(m); delete v.parts[id]; }
    },
  };
}

// ---------------------------------------------------------------- 4. press-fit station (bearing into the gearbox cover)
// The operator puts a part in the fixture (panel switch), presses both two-hand buttons; the PLC clamps, presses the
// bearing down while watching the force (analogue, %IW64, 0–27648 = 0–10 kN), then checks the end force window and
// shows OK or NOK. A light curtain (NC, safety) must stop the press. Inputs: B_Part, B_Clamped, B_Unclamped, B_PressUp,
// B_PressDown, S_Hand1, S_Hand2, S_LC (light curtain, NC), AI_Force; outputs: Y_Clamp, Y_PressDown, Y_PressUp, H_OK, H_NOK.
// Force at the bottom: about 5.6 kN for a good part (window 4–7 kN), 9.1 kN too tight, 2.1 kN too loose.
// Operating elements (Chapter 15): e-stop (NC), mode switch, reset/home, single step, manual clamp and ram jog; lamps
// Ready and Fault. The ram valve is a 5/3 closed-centre valve: with neither coil on, the ram stops where it is.
function press(o = {}) {
  const io = [
    { name: "B_Part", addr: "%IX0.0", dir: "in", comment: ["工件在位", "Part present"] },
    { name: "B_Clamped", addr: "%IX0.1", dir: "in", comment: ["夹紧到位", "Clamped"] },
    { name: "B_Unclamped", addr: "%IX0.2", dir: "in", comment: ["松开到位", "Unclamped"] },
    { name: "B_PressUp", addr: "%IX0.3", dir: "in", comment: ["压头上位", "Ram at top"] },
    { name: "B_PressDown", addr: "%IX0.4", dir: "in", comment: ["压头下位（压装到底）", "Ram at bottom (seated)"] },
    { name: "S_Hand1", addr: "%IX0.5", dir: "in", comment: ["双手按钮左", "Two-hand button left"] },
    { name: "S_Hand2", addr: "%IX0.6", dir: "in", comment: ["双手按钮右", "Two-hand button right"] },
    { name: "S_LC", addr: "%IX0.7", dir: "in", comment: ["安全光幕（常闭，挡光为 0）", "Light curtain (NC, 0 when broken)"] },
    { name: "AI_Force", addr: "%IW64", dir: "in", type: "INT", comment: ["压装力 0–27648 ↔ 0–10 kN", "Press force 0–27648 ↔ 0–10 kN"] },
    { name: "S_EStop", addr: "%IX1.0", dir: "in", comment: ["急停（常闭，按下为 0）", "Emergency stop (NC, 0 when pressed)"] },
    { name: "S_Auto", addr: "%IX1.1", dir: "in", comment: ["方式选择：1 自动 / 0 手动", "Mode switch: 1 auto / 0 manual"] },
    { name: "S_Reset", addr: "%IX1.2", dir: "in", comment: ["复位（回原点）按钮", "Reset (home) button"] },
    { name: "S_Step", addr: "%IX1.3", dir: "in", comment: ["单步按钮", "Single-step button"] },
    { name: "S_JogClamp", addr: "%IX1.4", dir: "in", comment: ["手动：夹紧／松开", "Manual: clamp / unclamp"] },
    { name: "S_JogDown", addr: "%IX1.5", dir: "in", comment: ["手动：压头下行（点动）", "Manual: ram down (jog)"] },
    { name: "S_JogUp", addr: "%IX1.6", dir: "in", comment: ["手动：压头上行（点动）", "Manual: ram up (jog)"] },
    { name: "Y_Clamp", addr: "%QX0.0", dir: "out", comment: ["夹紧气缸", "Clamp cylinder"] },
    { name: "Y_PressDown", addr: "%QX0.1", dir: "out", comment: ["压头下行", "Ram down"] },
    { name: "Y_PressUp", addr: "%QX0.2", dir: "out", comment: ["压头上行", "Ram up"] },
    { name: "H_OK", addr: "%QX0.3", dir: "out", comment: ["合格灯（绿）", "OK lamp (green)"] },
    { name: "H_NOK", addr: "%QX0.4", dir: "out", comment: ["不合格灯（红）", "NOK lamp (red)"] },
    { name: "H_Ready", addr: "%QX0.5", dir: "out", comment: ["就绪灯（白）：在原点、可以启动", "Ready lamp (white): at home, may start"] },
    { name: "H_Fault", addr: "%QX0.6", dir: "out", comment: ["故障灯（黄）", "Fault lamp (amber)"] },
  ];
  const STROKE = 0.12, CONTACT = 0.085, SPEED = 0.06;   // ram stroke m, where the bearing meets the bore, ram speed m/s
  return {
    io,
    panel: [{ name: "B_Part", kind: "switch", label: ["放上工件", "Load part"] }, { name: "S_Hand1", kind: "push", label: ["双手左", "Hand L"] },
            { name: "S_Hand2", kind: "push", label: ["双手右", "Hand R"] },
            { names: ["S_Hand1", "S_Hand2"], kind: "push", label: ["双手同时按住", "Both hands"] }, { name: "S_LC", kind: "nc-push", label: ["手伸进光幕", "Hand in curtain"] },
            { name: "S_EStop", kind: "estop", label: ["急停（再按一次释放）", "E-stop (press again to release)"] }, { name: "S_Auto", kind: "switch", label: ["自动", "Auto"] },
            { name: "S_Reset", kind: "push", label: ["复位", "Reset"] }, { name: "S_Step", kind: "push", label: ["单步", "Step"] },
            { name: "S_JogClamp", kind: "switch", label: ["手动夹紧", "Jog clamp"] }, { name: "S_JogDown", kind: "push", label: ["手动下", "Jog down"] },
            { name: "S_JogUp", kind: "push", label: ["手动上", "Jog up"] }],
    faults: [{ id: "tight", name: ["过盈太大（力超上限）", "Interference too large (force high)"] },
             { id: "loose", name: ["过盈太小（力不足）", "Interference too small (force low)"] },
             { id: "clampWire", name: ["夹紧到位传感器断线", "Clamp sensor wire broken"] },
             { id: "upStuck", name: ["压头上位开关粘连（常为 1）", "Ram-top switch stuck closed (always 1)"] }],
    reset(s, opt) {
      s.f = (opt && opt.faults) || {}; s.t = 0; s.out = {}; s.clamp = o.clamp0 || 0; s.ram = o.ram0 || 0; s.force = 0; s.hazard = false; s.seated = false;
      s.rand = rng((opt && opt.seed) || 11); s.part = false; s.panelLC = true; s.peak = 0;
    },
    inputs(s) {
      const kN = s.force + (s.rand() - 0.5) * 0.05;   // ±0.025 kN noise
      return {
        B_Clamped: s.clamp > 0.97 && !s.f.clampWire, B_Unclamped: s.clamp < 0.03,
        B_PressUp: s.ram < 0.002 || !!s.f.upStuck, B_PressDown: s.ram > STROKE - 0.002,
        AI_Force: Math.round(clamp(kN, 0, 10) / 10 * 27648),
        S_EStop: true, S_LC: true,      // NC safety contacts: closed (TRUE) unless the panel or a test opens them
      };
    },
    step(dt, out, s, ins) {
      s.t += dt; s.out = out;
      if (ins) { s.part = !!ins.B_Part; s.panelLC = ins.S_LC !== false; }
      const sec = dt / 1000;
      s.clamp = approach(s.clamp, out.Y_Clamp ? 1 : 0, 1 / 0.3, sec);
      const dir = out.Y_PressDown && !out.Y_PressUp ? 1 : out.Y_PressUp && !out.Y_PressDown ? -1 : 0;
      // the part must be clamped before the ram touches it; the light curtain (read from the panel) is a hazard check
      const lcOk = s.panelLC;
      if (ins && ins.S_EStop === false && dir !== 0) { s.hazard = true; s.why = "estop"; }   // e-stop pressed but the ram still moves
      if (dir > 0 && !lcOk) { s.hazard = true; s.why = "curtain"; }
      if (dir > 0 && s.ram > 0.02 && s.clamp < 0.9) { s.hazard = true; s.why = "unclamped"; }
      s.ram = clamp(s.ram + dir * SPEED * sec, 0, STROKE);
      // force: zero until contact, then the press-fit force grows with depth; a hard stop at the bottom
      const k = s.f.tight ? 260 : s.f.loose ? 60 : 160;   // kN per m of engagement
      if (s.ram > CONTACT && dir >= 0 && s.part) s.force = k * (s.ram - CONTACT);
      else if (dir < 0 || s.ram <= CONTACT) s.force = approach(s.force, 0, 40, sec);
      s.peak = Math.max(s.peak, s.force);
      if (s.ram >= STROKE - 0.002 && s.part) s.seated = true;
    },
    read(s, n) {
      if (n === "hazard") return s.hazard;
      if (n === "force") return s.force;
      if (n === "peak") return s.peak;
      if (n === "seated") return s.seated;
      return undefined;
    },
    build3d(st, THREE) {
      const K = kit3d(st, THREE);
      const v = { K };
      K.box(1.0, 0.8, 0.7, 0x57606a, 0, 0.4, 0);
      K.box(0.1, 1.2, 0.1, 0x6e7781, -0.35, 1.4, -0.2); K.box(0.1, 1.2, 0.1, 0x6e7781, 0.35, 1.4, -0.2);
      K.box(0.9, 0.15, 0.3, 0x6e7781, 0, 2.05, -0.1);
      K.cyl(0.08, 0.35, 0x8c959f, 0, 1.8, 0);
      v.ram = K.cyl(0.03, 0.4, 0xe1e4e8, 0, 1.45, 0);
      v.bearing = K.cyl(0.07, 0.03, 0xafb8c1, 0, 1.0, 0);
      v.part = K.box(0.36, 0.14, 0.36, 0x7d8590, 0, 0.87, 0);
      v.clampL = K.box(0.06, 0.1, 0.2, 0xc2570c, -0.35, 0.87, 0); v.clampR = K.box(0.06, 0.1, 0.2, 0xc2570c, 0.35, 0.87, 0);
      v.ok = K.lamp(0.05, 0x2ecc71, 0.45, 2.1, 0.1); v.nok = K.lamp(0.05, 0xff3b30, 0.6, 2.1, 0.1);
      v.curtain = [-0.45, 0.45].map((x) => K.box(0.04, 1.0, 0.04, 0xffb000, x, 1.3, 0.38));
      K.label("OK", 0.45, 1.95, 0.12, 0.09); K.label("NOK", 0.62, 1.85, 0.12, 0.09);
      K.camera([2.4, 2.3, 3.4], [0, 1.1, 0]);
      return v;
    },
    draw3d(v, s) {
      const o = s.out || {};
      const y = 1.45 - (s.ram || 0) * 3.2;
      v.ram.position.y = y;
      v.bearing.visible = !!s.part; v.part.visible = !!s.part;
      v.bearing.position.y = Math.max(0.95, Math.min(1.0, y - 0.21));
      const c = (s.clamp || 0) * 0.12;
      v.clampL.position.x = -0.35 + c; v.clampR.position.x = 0.35 - c;
      v.ok.userData.on(o.H_OK); v.nok.userData.on(o.H_NOK);
      v.curtain.forEach((b) => { b.material = v.K.mat(s.panelLC ? 0xffb000 : 0xd1242f); });
    },
  };
}

// ---------------------------------------------------------------- 5. feed conveyor (Part I project: the digital factory's raw-store feed line)
// A belt from the raw store to the band saw SAW-01. The operator (or the store robot) puts a bar on the entry; the PLC
// runs the belt until the bar reaches the end sensor, where the saw's loader takes it away. Start (NO), stop (NC) and a
// latching e-stop (NC); an overload relay contact (NC) of the motor; green running lamp, red fault lamp.
// Inputs: S1_Start, S2_Stop, S0_EStop, F1_Overload, B1_Entry, B2_End; outputs: KM1_Run, H1_Run, H2_Fault.
function conveyor(o = {}) {
  const io = [
    { name: "S1_Start", addr: "%IX0.0", dir: "in", comment: ["启动按钮 S1（常开）", "Start button S1 (NO)"] },
    { name: "S2_Stop", addr: "%IX0.1", dir: "in", comment: ["停止按钮 S2（常闭，按下为 0）", "Stop button S2 (NC, 0 when pressed)"] },
    { name: "S0_EStop", addr: "%IX0.2", dir: "in", comment: ["急停 S0（常闭，按下为 0）", "Emergency stop S0 (NC, 0 when pressed)"] },
    { name: "F1_Overload", addr: "%IX0.3", dir: "in", comment: ["电机热继电器 F1 辅助触点（常闭，过载为 0）", "Motor overload relay F1 (NC, 0 on overload)"] },
    { name: "B1_Entry", addr: "%IX0.4", dir: "in", comment: ["入口光电开关 B1（有料为 1）", "Entry photo sensor B1 (1 = part)"] },
    { name: "B2_End", addr: "%IX0.5", dir: "in", comment: ["末端光电开关 B2（有料为 1）", "End photo sensor B2 (1 = part)"] },
    { name: "KM1_Run", addr: "%QX0.0", dir: "out", comment: ["输送电机接触器 KM1", "Conveyor motor contactor KM1"] },
    { name: "H1_Run", addr: "%QX0.1", dir: "out", comment: ["运行指示灯 H1（绿）", "Running lamp H1 (green)"] },
    { name: "H2_Fault", addr: "%QX0.2", dir: "out", comment: ["故障指示灯 H2（黄）", "Fault lamp H2 (amber)"] },
  ];
  const L = 3.0, V = 0.25;                       // belt length m, belt speed m/s (about 12 s from entry to end)
  const ENTRY = 0.15, END = 2.85;                // sensor positions m
  return {
    io,
    panel: [{ name: "S1_Start", kind: "push", label: ["启动 S1", "Start S1"] }, { name: "S2_Stop", kind: "nc-push", label: ["停止 S2", "Stop S2"] },
            { name: "S0_EStop", kind: "estop", label: ["急停 S0（再按一次释放）", "E-stop S0 (press again to release)"] },
            { name: "PutPart", kind: "push", label: ["放一根料", "Put a bar"] }, { name: "TakePart", kind: "push", label: ["取走末端的料", "Take the bar away"] }],
    faults: [{ id: "jam", name: ["卡料（带在转，料不走）", "Jam (belt runs, bar stuck)"] }, { id: "b2dead", name: ["末端光电 B2 坏（常为 0）", "End sensor B2 dead (always 0)"] },
             { id: "overload", name: ["电机过载（热继电器动作）", "Motor overload (relay trips)"] }],
    reset(s, opt) {
      s.f = (opt && opt.faults) || {}; s.t = 0; s.out = {}; s.v = 0; s.parts = (o.parts || [0.15]).map((x) => ({ x })); s.hazard = false;
      s.delivered = 0; s.runMs = 0; s.lastPut = false; s.lastTake = false; s.why = "";
    },
    inputs(s) {
      const at = (x, w) => s.parts.some((p) => Math.abs(p.x - x) < w);
      return { B1_Entry: at(ENTRY, 0.12), B2_End: !s.f.b2dead && at(END, 0.12), F1_Overload: !s.f.overload, S2_Stop: true, S0_EStop: true };
    },
    step(dt, out, s, ins) {
      s.t += dt; s.out = out;
      const sec = dt / 1000;
      // the panel's "put a bar" / "take it away" (a test sets PutPart / TakePart the same way)
      if (ins) {
        if (ins.PutPart && !s.lastPut && !s.parts.some((p) => p.x < 0.5)) s.parts.push({ x: ENTRY });
        if (ins.TakePart && !s.lastTake) s.parts = s.parts.filter((p) => { const gone = p.x > END - 0.2; if (gone) s.delivered++; return !gone; });
        s.lastPut = !!ins.PutPart; s.lastTake = !!ins.TakePart;
        if (ins.S0_EStop === false && out.KM1_Run) { s.hazard = true; s.why = "estop"; }
        if (ins.F1_Overload === false && out.KM1_Run && s.f.overload) { s.hazard = true; s.why = "overload"; }
      }
      // the motor needs about 0.3 s to reach speed, stops in about 0.2 s
      const target = out.KM1_Run ? V : 0;
      s.v += (target - s.v) * Math.min(1, dt / (target ? 300 : 200));
      if (out.KM1_Run) s.runMs += dt;
      for (const p of s.parts) {
        if (s.f.jam && p.x > 1.4 && p.x < 1.5) continue;            // stuck at the middle guide
        const ahead = s.parts.some((q) => q !== p && q.x > p.x && q.x - p.x < 0.45);
        if (!ahead) p.x = Math.min(L - 0.05, p.x + s.v * sec);       // a bar at the end stops against the end stop
      }
      // a bar pushed against the end stop while the belt keeps running: wear, not a hazard; running into a person is the hazard
    },
    read(s, n) {
      if (n === "hazard") return s.hazard;
      if (n === "delivered") return s.delivered;
      if (n === "x") return s.parts.length ? Math.max(...s.parts.map((p) => p.x)) : 0;
      if (n === "atEnd") return s.parts.some((p) => p.x > END - 0.12);
      if (n === "runMs") return s.runMs;
      return undefined;
    },
    build3d(st, THREE) {
      const K = kit3d(st, THREE);
      const v = { K, parts: [] };
      K.box(L + 0.3, 0.08, 0.5, 0x2d333b, L / 2, 0.8, 0);
      for (const x of [0.05, L - 0.05]) K.cyl(0.06, 0.52, 0x8c959f, x, 0.82, 0, null, "z");
      for (const x of [0.2, L / 2, L - 0.2]) for (const z of [-0.22, 0.22]) K.box(0.06, 0.78, 0.06, 0x57606a, x, 0.39, z);
      v.motor = K.cyl(0.12, 0.3, 0x6e7781, -0.1, 0.62, 0.42, null, "z");
      K.label("M1", -0.1, 0.95, 0.5, 0.1);
      const sensor = (x, name) => { K.box(0.06, 0.2, 0.06, 0x24292f, x, 0.95, -0.32); K.label(name, x, 1.2, -0.32, 0.1); return K.beam([x, 0.9, -0.29], [x, 0.9, 0.29], 0x9aa7b0); };
      v.b1 = sensor(ENTRY, "B1"); v.b2 = sensor(END, "B2");
      K.box(0.05, 0.25, 0.5, 0x6e7781, L + 0.02, 0.97, 0);          // end stop
      K.box(0.4, 0.6, 0.15, 0xd0d7de, -0.5, 1.1, 0.6);              // control box with lamps
      v.h1 = K.lamp(0.045, 0x2da44e, -0.6, 1.3, 0.69); v.h2 = K.lamp(0.045, 0xd4a72c, -0.4, 1.3, 0.69);
      K.label("H1", -0.6, 1.42, 0.7, 0.08); K.label("H2", -0.4, 1.42, 0.7, 0.08);
      K.camera([1.2, 2.6, 4.2], [1.4, 0.8, 0]);
      return v;
    },
    draw3d(v, s) {
      const ins = this.inputs(s), o = s.out || {};
      v.b1.userData.on(ins.B1_Entry); v.b2.userData.on(ins.B2_End);
      v.h1.userData.on(o.H1_Run); v.h2.userData.on(o.H2_Fault);
      v.motor.material = v.K.mat(o.KM1_Run ? 0x2da44e : 0x6e7781);
      while (v.parts.length < s.parts.length) v.parts.push(v.K.box(0.4, 0.09, 0.09, 0xb08800, 0, 0, 0));
      v.parts.forEach((m, i) => { const p = s.parts[i]; m.visible = !!p; if (p) m.position.set(p.x, 0.89, 0); });
    },
  };
}

// ---------------------------------------------------------------- 6. motor control circuits (Ch. 2): reversing and star–delta
// Contactors as they really behave: the coil needs PICK ms to pull the armature in, and after the coil is switched off the
// armature holds DROP ms before the contacts open; the arc on an opening main contact lasts until the next current zero
// (0–10 ms at 50 Hz), so a main contact keeps conducting a little after it opens. The auxiliary contacts are mechanically
// linked to the main contacts (a welded main contact keeps the NO auxiliary contact closed, IEC 60947-4-1 mirror contacts).
// An "interrupted" coil that is re-energised before DROP only makes the armature clack. Two contactors whose main contacts
// conduct together short-circuit two phases: the circuit breaker Q1 trips at once (hazard "short").
const PICK = 20, DROP = 12, CLACK = 4;      // ms: pick-up, drop-out, the shortest gap the armature notices
function contactor() { return { coil: false, closed: false, on: 0, off: 1e9, arcUntil: -1, welded: false, clacks: 0, drops: 0, closes: 0 }; }
function stepContactor(k, coil, s, dt, rand, weld) {
  if (coil) {
    if (k.off > 0 && k.off < 1e8 && k.closed && k.off >= CLACK) k.clacks++;      // re-energised before it dropped: a clack
    k.on += dt; k.off = 0;
    if (!k.closed && k.on >= PICK) { k.closed = true; k.closes++; if (weld) k.welded = true; }
  } else {
    k.off += dt; k.on = 0;
    if (k.closed && k.off >= DROP && !k.welded) { k.closed = false; k.drops++; k.arcUntil = s.t + 10 * rand(); }
  }
  k.coil = coil;
}
const conducting = (k, s) => k.closed || s.t < k.arcUntil;
// a squirrel-cage motor, per unit: slip sl = 1 − w (w = speed / synchronous speed, negative when reversed); current and
// torque from a simple Kloss-type model, start current KI × In, load torque ∝ speed² (fan-like) plus friction
function motorPU(m, supply, scale, dt, H) {
  // supply: +1 forward, −1 reverse, 0 none; scale: 1 delta / direct, 1/3 star (voltage 1/√3 → current and torque 1/3)
  const sec = dt / 1000;
  let I = 0, T = 0;
  if (supply) {
    const sl = supply - m.w;                                   // slip relative to the rotating field (0…2)
    const a = Math.abs(sl), sk = 0.22;
    T = Math.sign(sl) * scale * 2 * m.Tk / (a / sk + sk / Math.max(a, 1e-4)) * (a < 1e-4 ? 0 : 1);
    const Ia = m.KI * a / Math.sqrt(a * a + m.aI * m.aI) * Math.sqrt(1 + m.aI * m.aI);
    I = scale * Math.sqrt(0.35 * 0.35 + Ia * Ia);
  }
  const TL = Math.sign(m.w) * (m.TL * m.w * m.w + 0.03);
  m.w += (T - TL) / H * sec;
  if (!supply && Math.abs(m.w) < 0.003) m.w = 0;
  m.I = I;
  // overload relay F1 (set to the rated current): a first-order thermal image, time constant 290 s, trips at 1.25 —
  // class 10 of IEC 60947-4-1: 7.2 × setting trips in about 7 s (4–10 s), 1.2 × trips (in about 10 min), 1.05 × never
  m.heat += (I * I - m.heat) / 290 * sec;
  if (m.heat >= 1.25) m.tripped = true;
}
function newMotor(o) { return { w: 0, I: 0, heat: 0, tripped: false, Tk: o.Tk || 2.6, KI: o.KI || 6.5, aI: o.aI || 0.24, TL: o.TL || 0.6 }; }

function reversing(o = {}) {
  const io = [
    { name: "S2_Stop", addr: "%IX0.0", dir: "in", comment: ["停止按钮 S2（常闭，按下为 0）", "Stop button S2 (NC, 0 when pressed)"] },
    { name: "S1_Fwd", addr: "%IX0.1", dir: "in", comment: ["正转按钮 S1（常开）", "Forward button S1 (NO)"] },
    { name: "S3_Rev", addr: "%IX0.2", dir: "in", comment: ["反转按钮 S3（常开）", "Reverse button S3 (NO)"] },
    { name: "F1_Overload", addr: "%IX0.3", dir: "in", comment: ["热继电器 F1 辅助触点（常闭，过载为 0）", "Overload relay F1 (NC, 0 on overload)"] },
    { name: "KM1_Aux", addr: "%IX0.4", dir: "in", comment: ["接触器 KM1 的常开辅助触点（吸合为 1）", "Contactor KM1 auxiliary contact (NO, 1 when closed)"] },
    { name: "KM2_Aux", addr: "%IX0.5", dir: "in", comment: ["接触器 KM2 的常开辅助触点（吸合为 1）", "Contactor KM2 auxiliary contact (NO, 1 when closed)"] },
    { name: "KM1_Fwd", addr: "%QX0.0", dir: "out", comment: ["正转接触器 KM1 线圈", "Forward contactor KM1 coil"] },
    { name: "KM2_Rev", addr: "%QX0.1", dir: "out", comment: ["反转接触器 KM2 线圈", "Reverse contactor KM2 coil"] },
  ];
  const NSYNC = 1500, IN = 1.9;          // 0.75 kW, 4-pole, 380 V: synchronous speed r/min, rated current A
  return {
    io,
    panel: [{ name: "S2_Stop", kind: "nc-push", label: ["停止 S2", "Stop S2"] }, { name: "S1_Fwd", kind: "push", label: ["正转 S1", "Forward S1"] },
            { name: "S3_Rev", kind: "push", label: ["反转 S3", "Reverse S3"] },
            { name: "F1_Reset", kind: "push", label: ["热继电器复位", "Reset F1"] }, { name: "Q1_On", kind: "push", label: ["重新合上断路器 Q1", "Close breaker Q1 again"] }],
    faults: [{ id: "weld1", name: ["KM1 主触点熔焊（第二次吸合时粘住，不再断开）", "KM1 main contacts weld (on the second closing they stay closed)"] },
             { id: "auxbad", name: ["KM1 自锁触点接触不良（运转中偶尔断开几毫秒）", "KM1 seal-in contact intermittent (opens for ms while running)"] },
             { id: "heavy", name: ["负载卡滞（电机堵转，热继电器动作）", "Load jammed (motor stalls, F1 trips)"] }],
    reset(s, opt) {
      s.f = (opt && opt.faults) || {}; s.t = 0; s.out = {}; s.k1 = contactor(); s.k2 = contactor(); s.m = newMotor({});
      s.rand = rng((opt && opt.seed) || 7); s.blown = false; s.hazard = false; s.why = ""; s.shorts = 0;
      s.gap = 0; s.gaps = 0; s.nextGap = 20000 + 280000 * s.rand(); s.lastF = false; s.lastR = false; s.press = 0; s.restartAt = -1; s.peakI = 0;
    },
    inputs(s) {
      let aux1 = s.k1.closed;
      if (s.gap > 0) aux1 = false;                                     // the worn seal-in contact springs open for a moment
      const r = { S2_Stop: true, F1_Overload: !s.m.tripped, KM1_Aux: aux1, KM2_Aux: s.k2.closed };
      if (o.operator) r.S1_Fwd = s.press > 0;                         // book only: an operator who restarts a stopped belt
      return r;
    },
    step(dt, out, s, ins) {
      s.t += dt; s.out = out;
      if (ins) {
        if (ins.F1_Reset && s.m.heat < 1.0) s.m.tripped = false;
        if (ins.Q1_On && !s.lastQ1) s.blown = false;
        s.lastQ1 = !!ins.Q1_On;
      }
      stepContactor(s.k1, !!out.KM1_Fwd, s, dt, s.rand, s.f.weld1 && s.k1.closes >= 1);   // welds on its second closing
      stepContactor(s.k2, !!out.KM2_Rev, s, dt, s.rand, false);
      if (!s.blown && conducting(s.k1, s) && conducting(s.k2, s)) {     // L1 and L3 short-circuited through KM1 and KM2: Q1 trips
        s.blown = true; s.hazard = true; s.why = "short"; s.shorts++;
      }
      const supply = s.blown ? 0 : (s.k1.closed && !s.k2.closed ? 1 : s.k2.closed && !s.k1.closed ? -1 : 0);
      motorPU(s.m, supply, 1, dt, s.f.heavy ? 1e9 : 0.9);
      if (s.f.heavy && supply) s.m.w = 0;                               // locked rotor
      s.peakI = Math.max(s.peakI, s.m.I * IN);
      // the worn seal-in contact: while the belt runs it springs open now and then (every 20–300 s; half of the gaps under 5 ms, up to 31 ms)
      if (s.gap > 0) s.gap = Math.max(0, s.gap - dt);
      if (o.gaps) for (const [t0, len] of o.gaps) if (s.t > t0 - dt && s.t <= t0) { s.gap = len; s.gaps++; }   // book figures: gaps at given times
      if (s.f.auxbad && s.k1.closed && Math.abs(s.m.w) > 0.5 && s.gap === 0 && s.t >= s.nextGap) {
        const u = s.rand(); s.gap = 1 + 30 * u * u * u; s.gaps++; s.nextGap = s.t + 20000 + 280000 * s.rand();
      }
      // book only: the operator presses forward again 8 s after the belt stopped by itself
      if (o.operator) {
        if (s.press > 0) s.press = Math.max(0, s.press - dt);
        if (!s.k1.coil && s.press === 0 && s.restartAt < 0 && s.k1.closes > 0) s.restartAt = s.t + 8000;
        if (s.restartAt >= 0 && s.t >= s.restartAt) { s.press = 300; s.restartAt = -1; }
      }
    },
    read(s, n) {
      switch (n) {
        case "hazard": return s.hazard;
        case "short": return s.shorts > 0;
        case "Q1_Tripped": return s.blown;
        case "speed": return Math.round(s.m.w * NSYNC);
        case "current": return +(s.m.I * IN).toFixed(2);
        case "peakCurrent": return +s.peakI.toFixed(2);
        case "KM1_Main": return conducting(s.k1, s);
        case "KM2_Main": return conducting(s.k2, s);
        case "KM1_Closed": return s.k1.closed;
        case "KM1_Moving": return s.k1.closed && !s.k1.coil && s.k1.off >= CLACK;   // the armature is on its way out (released, not yet open)
        case "KM2_Closed": return s.k2.closed;
        case "clacks": return s.k1.clacks;
        case "drops": return s.k1.drops;
        case "gaps": return s.gaps;
        case "restarts": return s.k1.closes;
        case "tripped": return s.m.tripped;
      }
      return undefined;
    },
    build3d(st, THREE) {
      const K = kit3d(st, THREE);
      const v = { K };
      K.box(1.2, 0.05, 0.6, 0x57606a, 0.4, 0.5, 0);                              // base plate
      v.motor = K.cyl(0.16, 0.42, 0x3d6f9e, 0.2, 0.72, 0, null, "x");
      K.box(0.12, 0.08, 0.28, 0x3d6f9e, 0.2, 0.56, 0);
      v.shaft = K.cyl(0.03, 0.3, 0x8c959f, 0.55, 0.72, 0, null, "x");
      v.key = K.box(0.02, 0.12, 0.03, 0xd98c3a, 0.66, 0.72, 0);                // a mark on the coupling shows the rotation
      v.fan = K.box(0.02, 0.26, 0.04, 0x24292f, -0.03, 0.72, 0);
      K.label("M1", 0.2, 1.0, 0, 0.1);
      K.box(0.9, 1.1, 0.12, 0xd0d7de, -0.9, 1.0, -0.2);                           // control cabinet
      v.km1 = K.box(0.18, 0.24, 0.12, 0x8c959f, -1.1, 1.15, -0.08); K.label("KM1", -1.1, 1.38, -0.05, 0.08);
      v.km2 = K.box(0.18, 0.24, 0.12, 0x8c959f, -0.8, 1.15, -0.08); K.label("KM2", -0.8, 1.38, -0.05, 0.08);
      v.fu = K.box(0.36, 0.1, 0.1, 0xe6e6e6, -0.95, 0.8, -0.08); K.label("Q1", -0.95, 0.68, -0.05, 0.08);
      v.f1 = K.lamp(0.035, 0xd98c3a, -0.6, 0.8, -0.08); K.label("F1", -0.6, 0.68, -0.05, 0.08);
      K.camera([1.4, 1.9, 2.6], [-0.2, 0.85, 0]);
      return v;
    },
    draw3d(v, s) {
      v.km1.material = v.K.mat(s.k1.closed ? 0x2da44e : 0x8c959f);
      v.km2.material = v.K.mat(s.k2.closed ? 0x2da44e : 0x8c959f);
      v.fu.material = v.K.mat(s.blown ? 0xd1242f : 0xe6e6e6);
      v.f1.userData.on(s.m.tripped);
      v.ang = (v.ang || 0) + s.m.w * 0.9;
      v.key.position.set(0.66, 0.72 + 0.04 * Math.cos(v.ang), 0.04 * Math.sin(v.ang)); v.key.rotation.x = -v.ang;
      v.fan.rotation.x = v.ang;
    },
  };
}

function stardelta(o = {}) {
  const io = [
    { name: "S2_Stop", addr: "%IX0.0", dir: "in", comment: ["停止按钮 S2（常闭，按下为 0）", "Stop button S2 (NC, 0 when pressed)"] },
    { name: "S1_Start", addr: "%IX0.1", dir: "in", comment: ["启动按钮 S1（常开）", "Start button S1 (NO)"] },
    { name: "F1_Overload", addr: "%IX0.3", dir: "in", comment: ["热继电器 F1 辅助触点（常闭，过载为 0）", "Overload relay F1 (NC, 0 on overload)"] },
    { name: "KM1_Aux", addr: "%IX0.4", dir: "in", comment: ["主接触器 KM1 常开辅助触点", "Main contactor KM1 auxiliary (NO)"] },
    { name: "KM2_Aux", addr: "%IX0.5", dir: "in", comment: ["星形接触器 KM2 常开辅助触点", "Star contactor KM2 auxiliary (NO)"] },
    { name: "KM3_Aux", addr: "%IX0.6", dir: "in", comment: ["三角形接触器 KM3 常开辅助触点", "Delta contactor KM3 auxiliary (NO)"] },
    { name: "KM1_Main", addr: "%QX0.0", dir: "out", comment: ["主接触器 KM1 线圈", "Main contactor KM1 coil"] },
    { name: "KM2_Star", addr: "%QX0.1", dir: "out", comment: ["星形接触器 KM2 线圈", "Star contactor KM2 coil"] },
    { name: "KM3_Delta", addr: "%QX0.2", dir: "out", comment: ["三角形接触器 KM3 线圈", "Delta contactor KM3 coil"] },
  ];
  const NSYNC = 1500, IN = 15.4;         // 7.5 kW, 4-pole, 380 V Δ
  return {
    io,
    panel: [{ name: "S2_Stop", kind: "nc-push", label: ["停止 S2", "Stop S2"] }, { name: "S1_Start", kind: "push", label: ["启动 S1", "Start S1"] },
            { name: "F1_Reset", kind: "push", label: ["热继电器复位", "Reset F1"] }, { name: "Q1_On", kind: "push", label: ["重新合上断路器 Q1", "Close breaker Q1 again"] }],
    faults: [{ id: "weld2", name: ["KM2（星形）主触点熔焊", "KM2 (star) main contacts welded"] }],
    reset(s, opt) {
      s.f = (opt && opt.faults) || {}; s.t = 0; s.out = {}; s.k1 = contactor(); s.k2 = contactor(); s.k3 = contactor();
      s.m = newMotor({ TL: o.TL || 0.7 }); s.rand = rng((opt && opt.seed) || 5); s.blown = false; s.hazard = false; s.why = ""; s.shorts = 0; s.peakI = 0;
    },
    inputs(s) { return { S2_Stop: true, F1_Overload: !s.m.tripped, KM1_Aux: s.k1.closed, KM2_Aux: s.k2.closed, KM3_Aux: s.k3.closed }; },
    step(dt, out, s, ins) {
      s.t += dt; s.out = out;
      if (ins) {
        if (ins.F1_Reset && s.m.heat < 1.0) s.m.tripped = false;
        if (ins.Q1_On && !s.lastQ1) s.blown = false;
        s.lastQ1 = !!ins.Q1_On;
      }
      stepContactor(s.k1, !!out.KM1_Main, s, dt, s.rand, false);
      stepContactor(s.k2, !!out.KM2_Star, s, dt, s.rand, s.f.weld2);
      stepContactor(s.k3, !!out.KM3_Delta, s, dt, s.rand, false);
      if (!s.blown && conducting(s.k1, s) && conducting(s.k2, s) && conducting(s.k3, s)) { s.blown = true; s.hazard = true; s.why = "short"; s.shorts++; }
      const fed = !s.blown && s.k1.closed;
      const scale = fed && s.k3.closed && !s.k2.closed ? 1 : fed && s.k2.closed && !s.k3.closed ? 1 / 3 : 0;
      motorPU(s.m, scale ? 1 : 0, scale || 1, dt, 1.6);
      s.peakI = Math.max(s.peakI, s.m.I * IN);
    },
    read(s, n) {
      switch (n) {
        case "hazard": return s.hazard;
        case "short": return s.shorts > 0;
        case "speed": return Math.round(s.m.w * NSYNC);
        case "current": return +(s.m.I * IN).toFixed(1);
        case "peakCurrent": return +s.peakI.toFixed(1);
        case "KM1_Closed": return s.k1.closed;
        case "KM2_Closed": return s.k2.closed;
        case "KM3_Closed": return s.k3.closed;
        case "KM2_Main": return conducting(s.k2, s);
        case "KM3_Main": return conducting(s.k3, s);
        case "tripped": return s.m.tripped;
      }
      return undefined;
    },
    build3d(st, THREE) {
      const K = kit3d(st, THREE);
      const v = { K };
      K.box(1.4, 0.05, 0.7, 0x57606a, 0.5, 0.45, 0);
      v.motor = K.cyl(0.24, 0.6, 0x3d6f9e, 0.3, 0.75, 0, null, "x");
      v.fan = K.box(0.02, 0.4, 0.05, 0x24292f, -0.05, 0.75, 0);
      v.key = K.box(0.02, 0.14, 0.03, 0xd98c3a, 0.85, 0.75, 0);
      K.cyl(0.035, 0.4, 0x8c959f, 0.75, 0.75, 0, null, "x");
      K.label("M1  7.5 kW", 0.3, 1.12, 0, 0.1);
      K.box(1.2, 1.1, 0.12, 0xd0d7de, -1.0, 1.0, -0.2);
      v.k = ["KM1", "KM2", "KM3"].map((n, i) => { K.label(n + ["", " Y", " Δ"][i], -1.35 + i * 0.35, 1.38, -0.05, 0.08); return K.box(0.2, 0.26, 0.12, 0x8c959f, -1.35 + i * 0.35, 1.15, -0.08); });
      v.fu = K.box(0.4, 0.1, 0.1, 0xe6e6e6, -1.0, 0.8, -0.08); K.label("Q1", -1.0, 0.68, -0.05, 0.08);
      K.camera([1.6, 2.0, 2.9], [-0.2, 0.85, 0]);
      return v;
    },
    draw3d(v, s) {
      [s.k1, s.k2, s.k3].forEach((k, i) => { v.k[i].material = v.K.mat(k.closed ? 0x2da44e : 0x8c959f); });
      v.fu.material = v.K.mat(s.blown ? 0xd1242f : 0xe6e6e6);
      v.ang = (v.ang || 0) + s.m.w * 0.9;
      v.key.position.set(0.85, 0.75 + 0.05 * Math.cos(v.ang), 0.05 * Math.sin(v.ang)); v.fan.rotation.x = v.ang;
    },
  };
}

// ---------------------------------------------------------------- 7. a pulse source (Ch. 3, 20): a square wave on B1_Pulse
// The PLC reads the input only at its scans, so pulses shorter than a scan are lost (o.f: frequency in Hz, 50 % duty).
function pulser(o = {}) {
  const io = [
    { name: "B1_Pulse", addr: "%IX0.0", dir: "in", comment: ["脉冲输入（例如接近开关数齿）", "Pulse input (e.g. a proximity switch counting teeth)"] },
    { name: "S2_Reset", addr: "%IX0.1", dir: "in", comment: ["清零按钮", "Reset button"] },
  ];
  const f = o.f || 10;
  return {
    io, panel: [{ name: "S2_Reset", kind: "push", label: ["清零", "Reset"] }], faults: [],
    reset(s) { s.t = 0; s.pulses = 0; s.last = false; },
    inputs(s) { return { B1_Pulse: Math.floor((s.t + 1e-9) * 2 * f / 1000) % 2 === 1 }; },
    step(dt, out, s) {
      s.t += dt;
      s.pulses = Math.floor((s.t + 1e-9) * f / 1000 + 0.5);    // rising edges so far (edges at (k + ½)/f)
    },
    read(s, n) { if (n === "pulses") return s.pulses; return undefined; },
  };
}

// ---------------------------------------------------------------- 8. a counting conveyor (Ch. 4): parts pass a photo sensor
// Parts 40 mm long, 60 mm apart, pass B1_Part (1 while a part blocks the beam). Belt speed 0.5 m/s, or 2 m/s with the panel
// switch Fast, or 5 m/s with VeryFast: the beam is blocked for 80, 20 or 8 ms. The PLC must count every part.
function counter(o = {}) {
  const io = [
    { name: "B1_Part", addr: "%IX0.0", dir: "in", comment: ["计件光电开关 B1（有工件挡光为 1）", "Counting photo sensor B1 (1 while a part blocks it)"] },
    { name: "S1_Reset", addr: "%IX0.1", dir: "in", comment: ["计数清零按钮 S1", "Reset button S1"] },
    { name: "HSC1_CV", addr: "%ID1000", dir: "in", type: "DINT", comment: ["高速计数器 HSC1 的当前值（硬件对 B1 的上升沿计数，与扫描无关）", "High-speed counter HSC1 value (hardware counts B1's rising edges, independent of the scan)"] },
    { name: "H1_Count", addr: "%QX0.0", dir: "out", comment: ["计件指示灯 H1（每数到一个闪一下）", "Count lamp H1 (blinks per part)"] },
  ];
  const LEN = 0.04, PITCH = 0.1;
  const speed = (s) => (s.fast2 ? 5 : s.fast ? 2 : o.v || 0.5);
  return {
    io,
    panel: [{ name: "S1_Reset", kind: "push", label: ["清零 S1", "Reset S1"] }, { name: "Fast", kind: "switch", label: ["带速 2 m/s", "Belt 2 m/s"] },
            { name: "VeryFast", kind: "switch", label: ["带速 5 m/s", "Belt 5 m/s"] }],
    faults: [],
    reset(s) { s.t = 0; s.x = 0; s.parts = 0; s.since = 0; s.fast = !!o.fast; s.fast2 = !!o.fast2; s.out = {}; },
    inputs(s) { const p = s.x % PITCH; return { B1_Part: p < LEN, HSC1_CV: s.parts }; },
    step(dt, out, s, ins) {
      s.t += dt; s.out = out;
      if (ins && "Fast" in ins) s.fast = !!ins.Fast;
      if (ins && "VeryFast" in ins) s.fast2 = !!ins.VeryFast;
      const x0 = s.x;
      s.x += speed(s) * dt / 1000;
      const k = Math.floor(s.x / PITCH) - Math.floor(x0 / PITCH);   // a part's front edge reached the beam
      s.parts += k;
      s.since = ins && ins.S1_Reset ? 0 : s.since + k;                 // parts since the last press of S1 (the reference for the PLC's count)
    },
    read(s, n) {
      if (n === "parts") return s.parts;
      if (n === "since") return s.since;
      if (n === "speed") return speed(s);
      if (n === "pulseMs") return LEN / speed(s) * 1000;
      return undefined;
    },
    build3d(st, THREE) {
      const K = kit3d(st, THREE);
      const v = { K, boxes: [] };
      K.box(3.2, 0.06, 0.4, 0x2d333b, 0, 0.8, 0);
      for (let i = 0; i < 32; i++) v.boxes.push(K.box(0.04 * 4, 0.12, 0.2, 0xb08800, 0, 0.89, 0));
      K.box(0.06, 0.25, 0.06, 0x24292f, 0, 1.0, -0.3); K.label("B1", 0, 1.25, -0.3, 0.1);
      v.beam = K.beam([0, 0.9, -0.27], [0, 0.9, 0.27], 0x9aa7b0);
      v.h1 = K.lamp(0.05, 0x2da44e, 0.4, 1.25, -0.3); K.label("H1", 0.4, 1.4, -0.3, 0.08);
      K.camera([0.8, 1.9, 2.4], [0, 0.85, 0]);
      return v;
    },
    draw3d(v, s) {
      v.beam.userData.on(this.inputs(s).B1_Part); v.h1.userData.on((s.out || {}).H1_Count);
      // parts drawn 4x enlarged in pitch so they stay visible: the scene shows the rhythm, not the scale
      const off = (s.x % PITCH) / PITCH;
      v.boxes.forEach((m, i) => { const x = (i - 16 + off) * PITCH * 4 * 0.25 * 4; m.position.set(x - 0.08, 0.89, 0); m.visible = Math.abs(x) < 1.55; });
    },
  };
}

const API = { traffic, elevator, sorter, press, conveyor, reversing, stardelta, pulser, counter, kit3d, rng };
if (typeof module !== "undefined" && module.exports) module.exports = API;
else root.WQPLANTS = API;
})(typeof window !== "undefined" ? window : globalThis);
