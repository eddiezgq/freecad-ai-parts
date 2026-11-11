// 第 130 轮：数字工厂英文版的缺口检查（细则“验收”：本批页面缺口为 0）。
// 1. 本批页面文件里 t('…') / tk('…') 的中文钥匙，英文表（src/locales/en.json）里都要有；
// 2. 本批页面文件里，t() 之外不能再有中文（注释、带 i18n-ok 标记的行除外：标志字、语言切换按钮这类有意保留的）；
// 3. 本批页面显示的数据文件（设计产物、仿真结果、传感器说明……）里的中文，经 td() 查表 + 词组表后都要成英文。
// 用法：node tools/i18n_check.mjs [--json]（在 factory/digital/web 下运行）；有缺口时退出码 1。
// 第二批、第三批做完，把页面加进 BATCH 就行。
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { compileTemplates, hasCjk, sortPhrases, translate } from '../src/lib/i18n-core.js';

const WEB = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const SRC = path.join(WEB, 'src');
const REPO_FACTORY = path.resolve(WEB, '..', '..');           // factory/
const en = JSON.parse(fs.readFileSync(path.join(SRC, 'locales', 'en.json'), 'utf8'));
const phrases = sortPhrases([...JSON.parse(fs.readFileSync(path.join(SRC, 'locales', 'en_phrases.json'), 'utf8')),
  ...JSON.parse(fs.readFileSync(path.join(SRC, 'locales', 'en_names.json'), 'utf8'))]);
const tpls = compileTemplates(JSON.parse(fs.readFileSync(path.join(SRC, 'locales', 'en_templates.json'), 'utf8')));   // 第三批：后端句型

// 第一批（细则 D-4）：外壳与导航、首页、三维车间、电路分析、虚拟仪器、电路板设计（含固件）、芯片设计、功能测试台、零件与机器人库
export const BATCH = [
  'App.vue', 'pages/Login.vue', 'pages/Home.vue', 'pages/Factory3D.vue', 'pages/EmbedWorkshop.vue',
  'pages/Circuit.vue', 'pages/Instruments.vue', 'pages/PcbDesign.vue', 'pages/ChipDesign.vue', 'pages/Fct.vue', 'pages/Library.vue',
  'components/AiDrawer.vue', 'components/NotifyBell.vue', 'components/TourOverlay.vue', 'components/TaskBar.vue', 'components/BusNotice.vue',
  'components/ControlChart.vue', 'components/ObjLink.vue', 'components/ProposalModal.vue',
  'components/SchematicView.vue', 'components/SpiceChart.vue', 'components/ScopeScreen.vue', 'components/ModelViewer.vue',
  'components/FirmwarePanel.vue', 'components/MotorPanel.vue', 'components/MasterPanel.vue', 'components/LineChart.vue',
  'lib/fmt.js', 'lib/machinfo.js', 'lib/api.js', 'lib/schematics.js', 'lib/encif.js', 'lib/instruments.js', 'lib/spice.js', 'lib/bus.js',
];
// 第二批（细则 D-4）：工厂运营各页、厂情中枢、实验与任务页（含首页的实验 7 任务）
export const BATCH2 = [
  'pages/Planner.vue',
  'pages/Engineer.vue',
  'pages/Operator.vue',
  'pages/Quality.vue',
  'pages/Q8D.vue',
  'pages/Teach.vue',
  'pages/BusView.vue',
  'pages/DesignRelease.vue',
  'pages/ProcessPlan.vue',
  'pages/ProcessEdit.vue',
  'pages/DesignReview.vue',
  'pages/Members.vue',
  'pages/Configurator.vue',
  'pages/Eto.vue',                 // 第 139 轮
  'components/EtoDesign.vue',
  'components/EtoMaterials.vue',
  'components/EtoPlan.vue',
  'components/EtoShop.vue',
  'components/EtoQuality.vue',
  'components/EtoBilling.vue',
  'pages/WaferMap.vue',
  'pages/EncCurve.vue',
  'pages/MotorWave.vue',
  'pages/Ehs.vue',
  'pages/Maint.vue',
  'pages/People.vue',
  'pages/Supply.vue',
  'pages/Calib.vue',
  'pages/RobotService.vue',
  'pages/Energy.vue',
  'pages/Finance.vue',
  'pages/Director.vue',
  'pages/Cost.vue',
  'pages/CustomerService.vue',
  'pages/Tasks.vue',
  'pages/TaskReview.vue',
  'pages/TaskPage.vue',
  'pages/Labs.vue',
  'pages/Lab15.vue',
  'pages/Lab16.vue',
  'pages/Lab17.vue',
  'pages/Lab18.vue',
  'pages/Lab19.vue',
  'pages/Lab20.vue',
  'pages/Lab21.vue',
  'pages/Lab22.vue',
  'pages/Lab23.vue',
  'pages/Lab24.vue',
  'pages/Lab25.vue',
  'pages/Lab26.vue',
  'pages/Lab27.vue',
  'pages/Lab28.vue',
  'pages/Lab29.vue',
  'pages/Lab30.vue',
  'pages/Lab31.vue',
  'pages/Lab32.vue',
  'pages/Lab34.vue',
  'pages/LabQ.vue',
  'pages/LabO.vue',
  'pages/OntOps.vue',
  'pages/OntHub.vue',
  'pages/OntRules.vue',
  'pages/OntSim.vue',
  'pages/OntActions.vue',
  'pages/OntAi.vue',
  'pages/OntNotify.vue',
  'pages/OntReports.vue',
  'pages/OntType.vue',
  'pages/OntObject.vue',
  'components/ChainGraph.vue',
  'components/GanttChart.vue',
  'components/GcodeView.vue',
  'components/OntGraph.vue',
  'components/OptionsPanel.vue',
  'components/ProductionCost.vue',
  'components/RetroPanel.vue',
  'components/ShaftView.vue',
  'components/TeacherConsole.vue',
  'components/TimeChart.vue',
  'components/DayChart.vue',
  'lib/ont.js', 'lib/tasks.js', 'lib/ai.js',
];
// 第 130 轮第四批：工程软件 7 页与它们的组件
export const BATCH4 = ['pages/Cae.vue', 'pages/Cam.vue', 'pages/Cfd.vue', 'pages/Mbd.vue', 'pages/Opt.vue', 'pages/Twin.vue', 'pages/VirtualPlc.vue',
  'lib/cae.js', 'lib/cam.js', 'lib/mbd.js', 'components/CaeViewer.vue', 'components/CamLathe.vue', 'components/CamMill.vue',
  'components/CfdViewer.vue', 'components/MbdViewer.vue', 'components/TopoPanel.vue', 'components/GearboxTwin.vue',
  // 帮助页与它的块、动画（正文是文档，按语言换稿，见 help/index.js）
  'pages/Help.vue', 'components/help/HelpBlock.vue', 'components/help/LabBlock.vue', 'components/help/QuizBlock.vue', 'components/help/TryBlock.vue', 'components/help/anim/AiDraftAnim.vue', 'components/help/anim/BomTreeAnim.vue', 'components/help/anim/CausalAnim.vue', 'components/help/anim/EnergyDayAnim.vue', 'components/help/anim/FlowAnim.vue', 'components/help/anim/InspectAnim.vue', 'components/help/anim/JointTestAnim.vue', 'components/help/anim/MrpAnim.vue', 'components/help/anim/RecallAnim.vue', 'components/help/anim/RiskAnim.vue', 'components/help/anim/ShiftAnim.vue', 'components/help/anim/SpcAnim.vue', 'components/help/anim/TerminalAnim.vue', 'components/help/anim/WorkOrderAnim.vue'];
// 整个文件里的中文字面量都是钥匙（页面名字表）
const KEY_FILES = ['help/pages.js'];

const strip = (txt) => txt
  .replace(/<style[\s\S]*?<\/style>/g, (m) => m.replace(/[^\n]/g, ''))
  .replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, ' '))
  .replace(/(^|[\s;{}(])\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))   // 只认真正的注释（“machining/*/status”这类路径里的 /* 不算）
  .split('\n').map((l) => l.replace(/(^|[^:'"\\])\/\/.*$/, '$1')).join('\n');

const CALL = /\b(?:t|tk|tr)\(\s*(?:'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"|`([^`$]*)`)/g;
const LIT = /'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"/g;

function scan(rel, keysOnly) {
  const raw = fs.readFileSync(path.join(SRC, rel), 'utf8');
  const keys = new Set();
  const left = [];
  const lines = strip(raw).split('\n');
  const rawLines = raw.split('\n');
  lines.forEach((line, i) => {
    if (keysOnly) {
      for (const m of line.matchAll(LIT)) { const k = m[1] ?? m[2]; if (hasCjk(k) && !k.startsWith('/')) keys.add(k); }
      return;
    }
    for (const m of line.matchAll(CALL)) { const k = m[1] ?? m[2] ?? m[3]; if (hasCjk(k)) keys.add(k.replace(/\\'/g, "'")); }
    if (rawLines[i].includes('i18n-ok')) return;
    const rest = line.replace(CALL, '');
    if (hasCjk(rest)) left.push({ line: i + 1, text: rawLines[i].trim().slice(0, 160) });
  });
  return { keys, left };
}

// ---------------------------------------------------------------- 数据文件：取页面会显示的字段
const J = (p) => JSON.parse(fs.readFileSync(path.join(REPO_FACTORY, p), 'utf8'));
function pick(o, spec, out) {
  // spec：'a.b[].c'（[] 展开数组；[1] 取第 1 个元素）
  const parts = spec.split('.');
  let cur = [o];
  for (const p of parts) {
    const m = p.match(/^(\w*)((?:\[\d*\])*)$/);
    let next = [];
    for (const c of cur) { if (c == null) continue; next.push(m[1] ? c[m[1]] : c); }
    for (const b of (m[2].match(/\[\d*\]/g) || [])) {
      const n = b.slice(1, -1);
      next = next.flatMap((c) => (Array.isArray(c) ? (n === '' ? c : [c[+n]]) : []));
    }
    cur = next;
  }
  for (const v of cur) if (typeof v === 'string' && hasCjk(v)) out.add(v);
}
function csvCol(p, col) {
  const rows = fs.readFileSync(path.join(REPO_FACTORY, p), 'utf8').trim().split('\n').slice(1);
  const out = [];
  for (const line of rows) {
    const cells = []; let cur = ''; let q = false;
    for (const ch of line) { if (ch === '"') q = !q; else if (ch === ',' && !q) { cells.push(cur); cur = ''; } else cur += ch; }
    cells.push(cur);
    out.push(cells[col]);
  }
  return out;
}
export function dataStrings() {
  const s = new Set();
  for (const b of ['drv-joint', 'drv-joint-b']) {
    const d = J(`designs/${b}/out/design.json`);
    for (const f of ['name', 'rev', 'tool', 'disclaimer', 'sheets[].note', 'pcb_layers[].name', 'changes[].what', 'changes[].ref', 'firmware[]']) pick(d, f, s);
    const f = J(`designs/${b}/out/dfm.json`);
    for (const x of ['checks[].name', 'checks[].why', 'checks[].detail', 'checks[].unit']) pick(f, x, s);
    for (const v of csvCol(`designs/${b}/out/bom.csv`, 5)) if (hasCjk(v)) s.add(v);
    for (const v of csvCol(`designs/${b}/out/bom.csv`, 1)) if (hasCjk(v)) s.add(v);
  }
  const c = J('designs/wq-encif/out/design.json');
  for (const f of ['name', 'rev', 'disclaimer', 'pdk', 'pins[].dir', 'pins[].desc', 'regs[].access', 'regs[].bits[][1]', 'blocks[].name', 'blocks[].desc',
    'sim.cases[].name', 'images.layers[].name']) pick(c, f, s);
  for (const fn of fs.readdirSync(path.join(REPO_FACTORY, 'designs/wq-encif/out/sim'))) {
    if (/^\d+\.json$/.test(fn)) { const w = J('designs/wq-encif/out/sim/' + fn); pick(w, 'case', s); pick(w, 'signals[].name', s); }
  }
  if (c.transistor?.file) {
    const tr = J('designs/wq-encif/out/' + c.transistor.file);
    pick(tr, 'models', s);
  }
  const fwo = 'designs/drv-joint-b/fw/out/';
  const sim = J(fwo + 'sim.json');
  for (const f of ['title', 'disclaimer', 'scenarios[].name', 'scenarios[].desc', 'scenarios[].checks[].name', 'scenarios[].checks[].detail']) pick(sim, f, s);
  const fw = J(fwo + 'fw.json');
  for (const f of ['disclaimer', 'files[].note']) pick(fw, f, s);
  const mo = J(fwo + 'sim_motor.json');
  for (const f of ['title', 'disclaimer', 'params[].name', 'params[].value', 'params[].source', 'scenarios[].name', 'scenarios[].desc',
    'scenarios[].checks[].name', 'scenarios[].checks[].detail', 'scenarios[].frames[].text']) pick(mo, f, s);
  const ma = J(fwo + 'sim_master.json');
  for (const f of ['title', 'arm.note', 'scenarios[].name', 'scenarios[].desc', 'scenarios[].checks[].name', 'scenarios[].checks[].detail',
    'scenarios[].events[][1]', 'scenarios[].series.phase[]']) pick(ma, f, s);
  const sensors = JSON.parse(fs.readFileSync(path.join(SRC, 'lib', 'sensors.json'), 'utf8'));
  for (const v of Object.values(sensors)) if (v && typeof v === 'object' && hasCjk(v.note)) s.add(v.note);
  return s;
}

export function check() {
  const missing = new Map();   // 钥匙 → 文件
  const left = {};
  for (const rel of [...BATCH, ...BATCH2, ...BATCH4, ...KEY_FILES]) {
    const r = scan(rel, KEY_FILES.includes(rel));
    for (const k of r.keys) if (!en[k]) missing.set(k, rel);
    if (r.left.length) left[rel] = r.left;
  }
  const data = [...dataStrings()].filter((x) => hasCjk(translate(x, en, phrases, tpls)));
  // 第三批：后端写的句子按句型表能换成英文（抽几句真实样子的，含占位里套名字、分句）
  const SAMPLES = ['宋雨 的 HT-01 操作资质 20 天后到期', '外圆磨床（GRD-01）停机了。想一想：它会影响哪张订单？在“车间实况”和“订单与交期”里找答案。',
    '预计还要约 12 分钟（工厂时间）；排队 3 件，是本周瓶颈', '客户投诉 CP-00002：客户反映：设备异响、温度偏高（示例·海港起重 Harbor Crane Systems (Demo)）'];
  for (const x of SAMPLES) if (hasCjk(translate(x, en, phrases, tpls))) data.push('（句型自检）' + x);
  return { missing: [...missing.entries()].map(([k, f]) => ({ key: k, file: f })), left, data };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const r = check();
  if (process.argv.includes('--json')) {
    console.log(JSON.stringify(r, null, 1));
  } else {
    for (const m of r.missing) console.log(`缺英文  ${m.file}：${m.key}`);
    for (const [f, ls] of Object.entries(r.left)) for (const l of ls) console.log(`未包 t() ${f}:${l.line}  ${l.text}`);
    for (const d of r.data) console.log(`数据缺英文  ${d}`);
    console.log(`钥匙缺英文 ${r.missing.length}，t() 外的中文 ${Object.values(r.left).reduce((n, x) => n + x.length, 0)}，数据缺英文 ${r.data.length}`);
  }
  process.exit(r.missing.length || Object.keys(r.left).length || r.data.length ? 1 : 0);
}
