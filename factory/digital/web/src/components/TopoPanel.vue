<template>
  <div class="topo">
    <div class="row">
      <section class="card side">
        <div class="step"><b>1</b> 选一个板件</div>
        <select v-model="preset" class="full" aria-label="拓扑优化算例">
          <option v-for="p in presets" :key="p.key" :value="p.key">{{ p.label }}</option>
        </select>
        <div v-if="cur" class="small muted">{{ cur.note }}</div>
        <svg class="bcfig" viewBox="0 0 240 125" aria-label="支承与载荷示意">
          <rect :x="fig.x" :y="fig.y" :width="fig.w" :height="fig.h" fill="#E9ECE8" stroke="#8A948C" />
          <g v-for="(s, i) in fig.sup" :key="'s' + i">
            <polygon v-if="s.t === 'pin'" :points="`${s.x},${s.y} ${s.x - 7},${s.y + 11} ${s.x + 7},${s.y + 11}`" fill="#5B6670" />
            <g v-else-if="s.t === 'roller'"><polygon :points="`${s.x},${s.y} ${s.x - 7},${s.y + 9} ${s.x + 7},${s.y + 9}`" fill="#5B6670" />
              <circle :cx="s.x - 4" :cy="s.y + 12" r="2.5" fill="#5B6670" /><circle :cx="s.x + 4" :cy="s.y + 12" r="2.5" fill="#5B6670" /></g>
            <g v-else-if="s.t === 'wall'"><line :x1="s.x" :y1="fig.y - 4" :x2="s.x" :y2="fig.y + fig.h + 4" stroke="#5B6670" stroke-width="4" /></g>
            <g v-else-if="s.t === 'sym'"><line :x1="s.x" :y1="fig.y - 6" :x2="s.x" :y2="fig.y + fig.h + 6" stroke="#5B6670" stroke-dasharray="4 3" />
              <text :x="s.x - 4" :y="fig.y + fig.h + 18" class="figt">对称面</text></g>
          </g>
          <g :transform="`translate(${fig.load.x},${fig.load.y})`">
            <line x1="0" y1="-26" x2="0" y2="-3" stroke="#D64541" stroke-width="2.5" />
            <polygon points="0,0 -5,-9 5,-9" fill="#D64541" /><text x="6" y="-16" class="figt red">F</text>
          </g>
        </svg>

        <div class="step"><b>2</b> 材料用多少、网格多细</div>
        <label class="line">材料用量（体积比）<input v-model.number="volfrac" type="range" min="0.2" max="0.7" step="0.05" /><b>{{ Math.round(volfrac * 100) }}%</b></label>
        <div class="line">网格 <input v-model.number="nelx" type="number" min="8" max="120" /> × <input v-model.number="nely" type="number" min="4" max="80" />
          <span class="small muted">共 {{ nelx * nely }} 格（上限 {{ maxEl }}）</span></div>
        <details class="small">
          <summary>算法参数（一般不用改）</summary>
          <div class="line">惩罚指数 p <input v-model.number="penal" type="number" min="1" max="5" step="0.5" />
            过滤半径 <input v-model.number="rmin" type="number" min="1" max="4" step="0.1" /> 格</div>
          <div class="muted">p 越大图越黑白分明（p = 1 时全是灰色）；过滤半径决定最细的杆有多粗，太小会出现“棋盘格”。</div>
        </details>

        <div class="step"><b>3</b> 实际尺寸（拉伸成板件做有限元校核用）</div>
        <div class="line">{{ preset === 'mbb' ? '整根梁长' : '长' }} <input v-model.number="length" type="number" min="20" max="2000" /> mm
          板厚 <input v-model.number="thick" type="number" min="1" max="200" /> mm</div>
        <div class="line">载荷 <input v-model.number="force" type="number" min="1" /> N
          材料 <select v-model="matId" aria-label="材料"><option v-for="m in materials" :key="m.id" :value="m.id">{{ m.name }}</option></select></div>

        <button class="btn primary big-w" type="button" :disabled="submitting" @click="submit">{{ submitting ? '提交中…' : '开始拓扑优化' }}</button>
        <div v-if="err" class="small warnline">{{ err }}</div>
      </section>

      <section class="card grow">
        <div class="card-head"><h2>{{ job ? job.title : '结果' }}</h2>
          <span v-if="job" class="pill" :class="TONE[job.status]">{{ STATUS[job.status] }}</span></div>
        <div v-if="!job" class="big-empty muted">左边选好板件、材料用量，点“开始拓扑优化”。<br />材料会从均匀的灰色慢慢“长”成桁架、拱这样的形状——几秒钟算完。</div>
        <div v-else-if="job.status !== 'done'" class="jobbar" :class="job.status">{{ job.status === 'failed' ? '失败：' + job.error : '正在计算…（一般几秒到二十秒）' }}</div>
        <template v-else-if="res">
          <div class="canvas-wrap">
            <canvas ref="cv" class="dens" />
          </div>
          <div class="line">
            <button class="btn small-btn" type="button" @click="togglePlay">{{ playing ? '暂停' : '▶ 播放生长过程' }}</button>
            <input v-model.number="frame" type="range" min="0" :max="res.frames.length - 1" step="1" class="grow-in" aria-label="迭代帧" />
            <span class="small mono">第 {{ res.frames[frame]?.it }} / {{ res.iterations }} 次</span>
          </div>
          <div class="cards">
            <div class="kpi"><span class="small muted">柔度（越小越刚）</span><span class="big">{{ res.history[0][1].toFixed(1) }} → {{ res.compliance.toFixed(1) }}</span>
              <span class="small">下降 {{ ((1 - res.compliance / res.history[0][1]) * 100).toFixed(0) }}%</span></div>
            <div class="kpi"><span class="small muted">迭代</span><span class="big">{{ res.iterations }} 次</span>
              <span class="small">{{ res.converged ? '已收敛' : '到次数上限' }} · {{ res.seconds }} 秒</span></div>
            <div class="kpi"><span class="small muted">灰色单元</span><span class="big">{{ (res.grey * 100).toFixed(0) }}%</span>
              <span class="small">越少轮廓越清楚</span></div>
          </div>
          <svg class="chart" viewBox="0 0 640 200" aria-label="柔度随迭代的变化">
            <text x="44" y="16" class="figt">柔度</text><text x="600" y="194" class="figt">迭代</text>
            <line x1="40" y1="180" x2="630" y2="180" stroke="#8A948C" /><line x1="40" y1="20" x2="40" y2="180" stroke="#8A948C" />
            <polyline :points="histPts" fill="none" stroke="var(--accent)" stroke-width="2" />
            <line :x1="hx(res.frames[frame]?.it || 1)" y1="20" :x2="hx(res.frames[frame]?.it || 1)" y2="180" stroke="#D64541" stroke-dasharray="3 3" />
          </svg>
          <div class="exp">
            <p v-for="(t, i) in (res.explain || '').split('\n')" :key="i" class="exp-p">{{ t }}</p>
          </div>
          <div class="line">
            <button class="btn primary" type="button" @click="toFea">拉伸成板件，去有限元校核 →</button>
            <span class="small muted">按密度 0.5 取轮廓、拉伸成 {{ job.spec.thickness_mm }} mm 厚的板，支承、载荷自动填好</span>
          </div>
        </template>
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>{{ teacher ? '本厂的拓扑优化记录' : '我的拓扑优化记录' }}</h2></div>
      <div v-if="!jobs.length" class="empty">还没有记录。</div>
      <table v-else class="t">
        <thead><tr><th>名称</th><th v-if="teacher">提交人</th><th>时间</th><th>状态</th><th class="num">体积比</th><th class="num">柔度</th><th></th></tr></thead>
        <tbody><tr v-for="j in jobs" :key="j.id">
          <td>{{ j.title }}</td><td v-if="teacher">{{ j.owner_name }}</td>
          <td class="small">{{ new Date(j.created * 1000).toLocaleString('zh-CN', { hour12: false }) }}</td>
          <td><span class="pill" :class="TONE[j.status]">{{ STATUS[j.status] }}</span></td>
          <td class="num">{{ j.spec?.volfrac }}</td><td class="num">{{ j.stats?.compliance?.toFixed?.(1) ?? '' }}</td>
          <td><a href="#" @click.prevent="openJob(j.id)">看 →</a></td>
        </tr></tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { get, post, session } from '../lib/api';

const router = useRouter();
const STATUS = { queued: '排队', running: '计算中', done: '完成', failed: '失败' };
const TONE = { queued: 'mute', running: 'info', done: 'good', failed: 'bad' };
const LENGTH = { mbb: 300, cantilever: 200, bridge: 400, bracket: 150 };
const teacher = computed(() => !!session.user?.teacher);
const presets = ref([]), maxEl = ref(6000), materials = ref([]);
const preset = ref('mbb'), nelx = ref(60), nely = ref(20), volfrac = ref(0.5), penal = ref(3), rmin = ref(1.5);
const length = ref(300), thick = ref(10), force = ref(2000), matId = ref('6061-T6');
const submitting = ref(false), err = ref('');
const job = ref(null), res = ref(null), jobs = ref([]);
const frame = ref(0), playing = ref(false), cv = ref(null);
let pollT = null, playT = null;

const cur = computed(() => presets.value.find((p) => p.key === preset.value));
watch(preset, (k) => { const p = cur.value; if (p) { nelx.value = p.nelx; nely.value = p.nely; } length.value = LENGTH[k] || 200; });

// 支承与载荷示意图
const fig = computed(() => {
  const r = nely.value / nelx.value, w = Math.min(190, 70 / r), h = w * r, x = 120 - w / 2, y = 30 + (70 - h) / 2;
  const k = preset.value;
  if (k === 'mbb') return { x, y, w, h, sup: [{ t: 'sym', x }, { t: 'roller', x: x + w, y: y + h }], load: { x, y } };
  if (k === 'bridge') return { x, y, w, h, sup: [{ t: 'pin', x, y: y + h }, { t: 'roller', x: x + w, y: y + h }], load: { x: x + w / 2, y: y + h + 26 } };
  if (k === 'cantilever') return { x, y, w, h, sup: [{ t: 'wall', x }], load: { x: x + w, y: y + h / 2 } };
  return { x, y, w, h, sup: [{ t: 'wall', x }], load: { x: x + w, y: y + h } };
});

const hmax = computed(() => (res.value ? Math.max(...res.value.history.map((r) => r[1])) : 1));
const hx = (it) => 40 + (it - 1) / Math.max(1, (res.value?.iterations || 2) - 1) * 590;
const histPts = computed(() => (res.value ? res.value.history.map((r) => `${hx(r[0]).toFixed(1)},${(180 - r[1] / hmax.value * 155).toFixed(1)}`).join(' ') : ''));

function draw() {
  const c = cv.value, f = res.value?.frames[frame.value];
  if (!c || !f) return;
  const d = f.density, ny = d.length, nx = d[0].length;
  const mirror = res.value.preset === 'mbb';                         // MBB 梁：同时画出镜像的另一半，看整根梁
  const W = mirror ? nx * 2 : nx;
  const s = Math.max(2, Math.floor(Math.min(820 / W, 360 / ny)));
  c.width = W * s; c.height = ny * s;
  const g = c.getContext('2d');
  const img = g.createImageData(W, ny);
  for (let j = 0; j < ny; j += 1) {
    for (let i = 0; i < W; i += 1) {
      const v = mirror ? (i < nx ? d[j][nx - 1 - i] : d[j][i - nx]) : d[j][i];
      const o = (j * W + i) * 4, gray = 255 - v;
      img.data[o] = gray; img.data[o + 1] = gray; img.data[o + 2] = gray; img.data[o + 3] = 255;
    }
  }
  const tmp = document.createElement('canvas'); tmp.width = W; tmp.height = ny;
  tmp.getContext('2d').putImageData(img, 0, 0);
  g.imageSmoothingEnabled = false;
  g.drawImage(tmp, 0, 0, W * s, ny * s);
  if (mirror) { g.strokeStyle = '#D64541'; g.setLineDash([4, 4]); g.beginPath(); g.moveTo(nx * s, 0); g.lineTo(nx * s, ny * s); g.stroke(); }
}
watch(frame, draw);

function togglePlay() {
  if (playing.value) { clearInterval(playT); playing.value = false; return; }
  if (frame.value >= res.value.frames.length - 1) frame.value = 0;
  playing.value = true;
  playT = setInterval(() => {
    if (frame.value >= res.value.frames.length - 1) { clearInterval(playT); playing.value = false; return; }
    frame.value += 1;
  }, 160);
}

async function submit() {
  err.value = ''; submitting.value = true;
  try {
    job.value = await post('/opt/topo', { spec: { preset: preset.value, nelx: nelx.value, nely: nely.value, volfrac: volfrac.value, penal: penal.value,
      rmin: rmin.value, length_mm: length.value, thickness_mm: thick.value, force_n: force.value, material_id: matId.value } });
    res.value = null; poll();
  } catch (e) { err.value = e.message; } finally { submitting.value = false; }
}

async function poll() {
  clearTimeout(pollT);
  try {
    job.value = await get('/opt/jobs/' + encodeURIComponent(job.value.id));
    if (job.value.status === 'done') { await loadRes(); loadJobs(); return; }
    if (job.value.status === 'failed') { loadJobs(); return; }
  } catch (e) { err.value = e.message; return; }
  pollT = setTimeout(poll, 1200);
}

async function loadRes() {
  res.value = await get(`/opt/topo/${encodeURIComponent(job.value.id)}/result`);
  frame.value = res.value.frames.length - 1;
  await nextTick(); draw();
  if (res.value.frames.length > 1) { frame.value = 0; await nextTick(); draw(); togglePlay(); }
}

async function openJob(id) {
  clearInterval(playT); playing.value = false;
  job.value = await get('/opt/jobs/' + encodeURIComponent(id)); res.value = null;
  if (job.value.status === 'done') await loadRes(); else poll();
}

function toFea() { router.push({ path: '/cae', query: { topo: job.value.id } }); }

async function loadJobs() { try { jobs.value = (await get('/opt/topo/jobs')).jobs; } catch (e) { /* */ } }

onMounted(async () => {
  try {
    const [p, m] = await Promise.all([get('/opt/topo/presets'), get('/cae/materials')]);
    presets.value = p.presets; maxEl.value = p.max_elements; materials.value = m.materials;
  } catch (e) { err.value = e.status === 503 ? '计算服务暂时连不上，请稍后再试' : e.message; }
  loadJobs();
});
onUnmounted(() => { clearTimeout(pollT); clearInterval(playT); });
</script>

<style scoped>
.topo { display: flex; flex-direction: column; gap: 14px; }
.side { width: 400px; flex-shrink: 0; display: flex; flex-direction: column; gap: 9px; align-self: flex-start; }
.grow { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.step { display: flex; align-items: center; gap: 8px; font-weight: 600; margin-top: 6px; }
.step b { width: 22px; height: 22px; border-radius: 50%; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; }
.full { width: 100%; height: 34px; border: 1px solid #C8CEC7; border-radius: 6px; padding: 0 8px; background: #fff; }
.line { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
input[type=number] { width: 70px; height: 26px; border: 1px solid #C8CEC7; border-radius: 5px; padding: 0 4px; }
select { height: 26px; border: 1px solid #C8CEC7; border-radius: 5px; }
.grow-in { flex: 1; }
.bcfig { width: 100%; height: 135px; background: var(--surface-2); border-radius: 8px; }
.figt { font-size: 11px; fill: #5B6670; }
.figt.red { fill: #D64541; font-weight: 600; }
.big-w { height: 42px; font-size: 15px; margin-top: 6px; }
.small-btn { height: 28px; font-size: 12px; }
.warnline { color: var(--warn-ink); }
.big-empty { padding: 120px 0; text-align: center; line-height: 1.8; }
.jobbar { border-radius: 8px; padding: 10px 14px; background: var(--accent-bg); color: var(--accent); }
.jobbar.failed { background: var(--bad-bg); color: var(--bad); }
.canvas-wrap { background: var(--surface-2); border-radius: 8px; padding: 12px; display: flex; justify-content: center; overflow-x: auto; }
.dens { image-rendering: pixelated; border: 1px solid var(--line); background: #fff; max-width: 100%; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.kpi { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; display: flex; flex-direction: column; gap: 2px; }
.big { font-size: 16px; font-weight: 600; }
.chart { width: 100%; height: 200px; background: var(--surface-2); border-radius: 8px; }
.exp { border-top: 1px solid var(--line); padding-top: 8px; }
.exp-p { margin: 2px 0; line-height: 1.7; }
@media (max-width: 1100px) { .side { width: 100%; } }
</style>
