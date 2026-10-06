// WenQuest shift runner (第 18 轮第 8 步〔数字工厂虚拟 PLC〕): one production shift of a virtual machine under a PLC program.
//
// The same engine (plc.js) and machine models (plants.js) as the lab bench and the book's tests, plus what a shift
// needs and a lab does not: a simulated operator (loads parts, presses buttons, calls maintenance, resets faults),
// a random stream of parts (a few with a bad press fit), and scheduled breakdowns that a maintenance man repairs
// after a while. The run is deterministic for a given seed and returns a time-stamped event list (simulated ms from
// the start of the shift) and a summary; the digital factory replays the events on its bus at factory speed.
//
//   WQSHIFT.run({ program: {st}, unit: "press" | "sorter", hours: 8, seed: 1, cycle: 10, breakdowns: [...] })
//     -> { ok, error, events: [{t, kind, ...}], summary }
//   kinds: state {state: run|idle|fault|down|stop}, cycle {good, cycle_s, ...}, alarm {code, text}, recover {code},
//          hazard {why}, stall {since_s}, plc_stop {error}
(function (root) {
"use strict";
const P = typeof module !== "undefined" && module.exports ? require("./plc.js") : root.WQPLC;
const W = typeof module !== "undefined" && module.exports ? require("./plants.js") : root.WQPLANTS;

function rng(seed) {
  let a = (seed >>> 0) || 1;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const H = 3600000;

// fault codes of program 15.5.1 (the book's reference) for the alarm text; other programs just give the number
const PRESS_CODES = { 1: ["夹紧超时", "Clamp timeout"], 2: ["压装超时", "Press timeout"], 3: ["回程超时", "Return timeout"], 4: ["松开超时", "Unclamp timeout"],
  5: ["回原点超时", "Homing timeout"], 9: ["传感器冲突", "Sensor conflict"] };

const UNITS = {
  // ------------------------------------------------------------ bearing press-fit station (Chapter 15)
  press: {
    plant: () => W.press(),
    breakdowns: [{ at_h: 2.6, fault: "clampWire", repair_min: 15 }, { at_h: 6.2, fault: "upStuck", repair_min: 10 }],
    alarmOutput: "H_Fault", codeVar: "Main.faultCode", codePrefix: "E-PRESS-", codes: PRESS_CODES,
    busy: (o) => o.Y_Clamp || o.Y_PressDown || o.Y_PressUp,
    operator(ctx) {
      const { o, ins, r, t, op, ps, faults, plant } = ctx;
      const set = ctx.set;
      if (!op.k) { Object.assign(op, { k: "boot", until: t + 2000 }); set({ S_Auto: true, S_EStop: true, S_LC: true, B_Part: false, S_Hand1: false, S_Hand2: false, S_Reset: false, S_Step: false, S_JogClamp: false, S_JogDown: false, S_JogUp: false }); }
      const wait = (lo, hi) => t + lo + r() * (hi - lo);
      // a fault lamp: the operator stops, calls maintenance, and resets once the machine is fixed (or after a look round)
      if (o.H_Fault && op.k !== "fault") { set({ S_Hand1: false, S_Hand2: false }); Object.assign(op, { k: "fault", until: t + (ctx.faultWait || 180000) }); }
      switch (op.k) {
        case "boot": if (t >= op.until) { ctx.pulse("S_Reset"); Object.assign(op, { k: "load", until: wait(4000, 8000) }); } break;
        case "load":
          if (t >= op.until) {
            const x = r();   // the next part's fit: about 2 % too loose, 1 % too tight
            faults.loose = x < 0.02; faults.tight = x >= 0.02 && x < 0.03;
            set({ B_Part: true }); Object.assign(op, { k: "start", until: t + 300 + r() * 500, late: r() < 0.01 });
          }
          break;
        case "start":        // both hands, the second within 0–0.25 s (1 % of the time 0.7 s: the PLC must refuse)
          if (t >= op.until) {
            set({ S_Hand1: true });
            Object.assign(op, { k: "hand2", until: t + (op.late ? 700 : r() * 250), tStart: t, curtain: r() < 0.003 && !ctx.noCurtain ? t + 900 + r() * 600 : 0, began: false });
          }
          break;
        case "hand2":
          if (t >= op.until) { set({ S_Hand2: true }); op.k = "hold"; }
          break;
        case "hold":         // hold both until the ram comes back up or a lamp says the part is done
          // (the lamps of the last part stay on until the PLC starts this one: only count them once the clamp has moved;
          //  with remote I/O, as in the OpenPLC check, the PLC sees the buttons a few tens of ms later)
          if (o.Y_Clamp) op.began = true;
          if (op.curtain && t >= op.curtain && t < op.curtain + 300) set({ S_LC: false }); else set({ S_LC: true });
          if (o.Y_PressUp || (op.began && (o.H_OK || o.H_NOK)) || t - op.tStart > 8000) {
            set({ S_Hand1: false, S_Hand2: false, S_LC: true });
            Object.assign(op, { k: "done", tHold: t });
          }
          break;
        case "done":
          if (o.Y_Clamp) op.began = true;
          if (op.began && (o.H_OK || o.H_NOK) && ins.B_Unclamped && !o.Y_Clamp) Object.assign(op, { k: "unload", until: wait(3000, 5000) });
          else if (t - op.tHold > 20000 && !o.Y_Clamp && !o.Y_PressDown && !o.Y_PressUp) {
            // the press did not start (two hands too far apart, or the program did not react): take hands off and try again
            set({ S_Hand1: false, S_Hand2: false }); Object.assign(op, { k: "start", until: t + 1500, late: false });
          }
          break;
        case "unload":
          if (t >= op.until) { set({ B_Part: false }); faults.loose = faults.tight = false; Object.assign(op, { k: "load", until: wait(4000, 8000) }); }
          break;
        case "fault":
          // wait for the repair (ctx.broken) and then a few minutes of looking; then reset and take the part out
          if (!ctx.broken && t >= op.until) {
            ctx.pulse("S_Reset");
            set({ B_Part: false }); faults.loose = faults.tight = false;
            Object.assign(op, { k: "after", until: t + 30000 });
          } else if (ctx.broken) op.until = Math.max(op.until, t + 120000);
          break;
        case "after":
          if (!o.H_Fault && (o.H_Ready || t >= op.until)) Object.assign(op, { k: "load", until: wait(4000, 8000) });
          else if (o.H_Fault && t >= op.until) Object.assign(op, { k: "fault", until: t + (ctx.faultWait || 180000) });
          break;
      }
    },
    part(ctx, prev) {        // a finished part: the OK or NOK lamp comes on
      const { o, plant, ps } = ctx;
      if ((o.H_OK && !prev.H_OK) || (o.H_NOK && !prev.H_NOK)) return { good: !!o.H_OK, peak_kN: Math.round(plant.read(ps, "peak") * 100) / 100 };
      return null;
    },
  },
  // ------------------------------------------------------------ finished-part sorting line
  sorter: {
    plant: () => W.sorter({ interval: 4000 }),
    breakdowns: [{ at_h: 3.2, fault: "y2stuck", repair_min: 20 }, { at_h: 5.5, fault: "colorDirty", repair_min: 15 }],
    alarmOutput: "H_Fault", codeVar: "Main.faultCode", codePrefix: "E-SORT-", codes: { 1: ["推杆 1 不动作", "Pusher 1 failed"], 2: ["推杆 2 不动作", "Pusher 2 failed"], 3: ["推杆 3 不动作", "Pusher 3 failed"] },
    busy: (o) => o.M_Belt,
    operator(ctx) {
      const { o, r, t, op, ps } = ctx;
      const set = ctx.set;
      if (!op.k) { Object.assign(op, { k: "boot", until: t + 1000 }); set({ S_Stop: true, S_Start: false }); }
      // keep parts coming: metal 30 %, red 30 %, blue 30 %, tall (reject) 10 %
      if (ps.seq && ps.seq.length < 3) { const x = r(); ps.seq.push(x < 0.3 ? "metal" : x < 0.6 ? "red" : x < 0.9 ? "blue" : "tallred"); }
      if (o.H_Fault && op.k !== "fault") Object.assign(op, { k: "fault", until: t + (ctx.faultWait || 120000) });
      switch (op.k) {
        case "boot": if (t >= op.until) { ctx.pulse("S_Start"); op.k = "run"; op.until = t + 5000; } break;
        case "run":
          if (!o.M_Belt && t >= op.until) { ctx.pulse("S_Start"); op.until = t + 60000; }   // the line stopped by itself: start it again (once a minute)
          break;
        case "fault":
          if (!ctx.broken && t >= op.until) { ctx.pulse("S_Stop", false); Object.assign(op, { k: "restart", until: t + 2000 }); }
          else if (ctx.broken) op.until = Math.max(op.until, t + 60000);
          break;
        case "restart":
          if (t >= op.until) { ctx.pulse("S_Start"); Object.assign(op, { k: "run", until: t + 60000 }); }
          break;
      }
    },
    part(ctx, prev) {        // a part left the belt: into a bin or off the end
      const { plant, ps } = ctx;
      const n = plant.read(ps, "sorted") + plant.read(ps, "rejects"), wrong = plant.read(ps, "wrong");
      const last = prev._n || 0, lastWrong = prev._wrong || 0;
      prev._n = n; prev._wrong = wrong;
      if (n > last) return { good: wrong === lastWrong, count: n - last };
      return null;
    },
  },
};

// One machine with its operator, part stream, breakdowns and bookkeeping, driven scan by scan by any PLC:
//   const S = session({unit, seed, hours, breakdowns}); each scan: ins = S.inputs(t); …PLC scan…; S.step(t, outputs, dt, codeFn)
// run() drives it with the WenQuest engine in simulated time; the OpenPLC check (vplc/openplc) drives it in real time.
function session(job) {
  const u = UNITS[job.unit];
  if (!u) throw new Error("unknown unit " + job.unit);
  const plant = u.plant();
  const hours = job.hours || 8, end = hours * H;
  const r = rng(job.seed || 1);
  const events = [];
  const ev = (t, kind, data) => events.push(Object.assign({ t: Math.round(t), kind }, data || {}));
  const summary = { unit: job.unit, hours, parts: 0, good: 0, nok: 0, alarms: 0, alarm_codes: {}, hazards: 0, downtime_min: 0, stalls: 0,
    cycle_mean_s: null, scans: 0, plc_error: null, breakdowns: [] };
  const ps = {}, faults = {};
  plant.reset(ps, { faults, seed: job.seed || 1 });
  const manual = {}, pulses = [], op = {}, partMemo = {}, cycles = [];
  const breakdowns = (job.breakdowns || u.breakdowns).map((b) => ({ at: b.at_h * H, fault: b.fault, until: b.at_h * H + b.repair_min * 60000, on: false }));
  let state = "", prevOut = {}, lastPart = null, lastActive = 0, stalled = false, downSince = null, broken = false, lastIns = {};
  const S = {
    plant, ps, io: plant.io, events, summary, end,
    // the machine's sensors, overridden by what the operator does with the panel
    inputs(t) {
      broken = false;
      for (const b of breakdowns) {
        if (!b.on && t >= b.at && t < b.until) { b.on = true; faults[b.fault] = true; summary.breakdowns.push({ fault: b.fault, at_min: Math.round(b.at / 60000), repair_min: Math.round((b.until - b.at) / 60000) }); }
        if (b.on && t >= b.until) { b.on = false; b.done = true; faults[b.fault] = false; }
        if (b.on) broken = true;
      }
      const fromPlant = plant.inputs(ps);
      const ins = {};
      for (const io of plant.io) if (io.dir === "in") {
        const v = io.name in manual ? manual[io.name] : fromPlant[io.name];
        if (v !== undefined) ins[io.name] = v;
      }
      lastIns = ins;
      return ins;
    },
    // after the PLC's scan: the machine moves, the operator acts, parts, alarms and states are booked
    step(t, o, dt, codeNow) {
      const ins = lastIns;
      plant.step(dt, o, ps, ins);
      const ctx = { o, ins, r, t, op, ps, faults, plant, broken, faultWait: job.faultWait, noCurtain: job.noCurtain,
        set: (m) => Object.assign(manual, m),
        pulse: (name, v = true) => { manual[name] = v; pulses.push({ name, v: !v, at: t + 150 }); } };
      for (let k = pulses.length - 1; k >= 0; k--) if (t >= pulses[k].at) { manual[pulses[k].name] = pulses[k].v; pulses.splice(k, 1); }
      u.operator(ctx);
      const p = u.part(ctx, Object.assign(partMemo, prevOut));
      if (p) {
        const n = p.count || 1;
        summary.parts += n; if (p.good) summary.good += n; else summary.nok += n;
        const cs = lastPart == null ? null : (t - lastPart) / 1000;
        if (cs != null) cycles.push(cs / n);
        lastPart = t;
        ev(t, "cycle", { good: p.good, cycle_s: cs == null ? null : Math.round(cs * 10) / 10, ...(p.peak_kN != null ? { peak_kN: p.peak_kN } : {}), ...(n > 1 ? { count: n } : {}) });
      }
      // alarms from the program's fault lamp, with the program's fault code when it has one
      if (o[u.alarmOutput] && !prevOut[u.alarmOutput]) {
        const c = codeNow ? codeNow(u.codeVar) : null;
        const code = u.codePrefix + (c == null ? "X" : c);
        const text = (c != null && u.codes[c]) || ["故障灯亮", "Fault lamp on"];
        summary.alarms++; summary.alarm_codes[code] = (summary.alarm_codes[code] || 0) + 1;
        ev(t, "alarm", { code, text });
      } else if (!o[u.alarmOutput] && prevOut[u.alarmOutput]) ev(t, "recover", {});
      if (plant.read(ps, "hazard")) { summary.hazards++; ev(t, "hazard", { why: ps.why || "" }); ps.hazard = false; }
      // machine state: fault (lamp), down (broken but the program did not notice), run, idle
      const busy = u.busy(o);
      const st = o[u.alarmOutput] ? "fault" : broken && !busy ? "down" : busy ? "run" : "idle";
      if (st !== "idle") lastActive = t;   // a fault or a breakdown is downtime of its own, not a stall
      if (st !== state) {
        if ((st === "fault" || st === "down") && downSince == null) downSince = t;
        if (st !== "fault" && st !== "down" && downSince != null) { summary.downtime_min += (t - downSince) / 60000; downSince = null; }
        ev(t, "state", { state: st }); state = st;
      }
      // nothing has happened for 10 minutes outside a fault: the line stands (a program that hangs)
      if (!stalled && t - lastActive > 600000 && st === "idle") { stalled = true; summary.stalls++; ev(t, "stall", { since_s: Math.round((t - lastActive) / 1000) }); downSince = lastActive; }
      if (stalled && busy) stalled = false;
      prevOut = o;
    },
    plcStop(t, msg) {
      summary.plc_error = msg;
      ev(t, "plc_stop", { error: msg }); ev(t, "state", { state: "stop" });
      if (downSince == null) downSince = t;
    },
    finish(tEnd) {
      if (downSince != null) summary.downtime_min += (tEnd - downSince) / 60000;
      summary.downtime_min = Math.round(summary.downtime_min * 10) / 10;
      if (cycles.length) { cycles.sort((a, b) => a - b); summary.cycle_mean_s = Math.round(cycles.reduce((a, b) => a + b, 0) / cycles.length * 10) / 10; summary.cycle_median_s = cycles[cycles.length >> 1]; }
      summary.yield = summary.parts ? Math.round(summary.good / summary.parts * 1000) / 1000 : null;
      return { ok: !summary.plc_error, error: summary.plc_error, events, summary };
    },
  };
  return S;
}

function run(job) {
  const S = session(job);
  const cycle = job.cycle || 10;
  let rt;
  try { rt = new P.Runtime({ io: S.io, st: job.program.st, cycle }); }
  catch (e) { return { ok: false, error: (e.line ? `line ${e.line}: ` : "") + e.message, events: S.events, summary: S.summary }; }
  const codeNow = (path) => { try { const v = rt.watch(path); return typeof v === "number" ? v : null; } catch (e) { return null; } };
  const addr = {};
  for (const io of rt.io) addr[io.name] = io.addr;
  let t = 0;
  for (; t < S.end; t += cycle) {
    const ins = S.inputs(t);
    for (const k in ins) rt.phys[addr[k]] = ins[k];
    if (!rt.scan()) { S.plcStop(t, rt.error.message); break; }
    S.step(t, rt.outputs(), cycle, codeNow);
  }
  S.summary.scans = rt.scans;
  return S.finish(S.end);
}

const API = { run, session, UNITS: Object.keys(UNITS) };
if (typeof module !== "undefined" && module.exports) module.exports = API;
else root.WQSHIFT = API;
})(typeof window !== "undefined" ? window : globalThis);
