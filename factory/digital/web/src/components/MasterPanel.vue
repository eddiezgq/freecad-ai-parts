<!-- 第 115 轮（电子 E14）：多关节 CAN 主站——一个主站（master/master.py）带两块驱动板 B 版，水平两关节机械臂末端走直线；
     报警、掉线时“一个停、全停”。产物 factory/designs/drv-joint-b/fw/out/sim_master.json。 -->
<template>
  <div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="d">
      <div class="dia">
        <div class="row">
          <div class="b host">{{ t('主站 master.py') }}<small>{{ t('100 Hz：收帧 → 监督 → 直线插补 → 逆运动学 → 发指令') }}</small></div><span class="ar">⇄ CAN ⇄</span>
          <div class="b mcu">{{ t('关节 1 驱动板（节点 1）') }}<small>0x201 / 0x181 / 0x081 / 0x701</small></div>
          <div class="b mcu">{{ t('关节 2 驱动板（节点 2）') }}<small>0x202 / 0x182 / 0x082 / 0x702</small></div>
        </div>
      </div>
      <p class="small">{{ t('两块驱动板跑的是同一份固件（只是节点号不同，make NODE=2），在 Renode 里同时仿真、时间同步；主站程序每 10 ms 推进一拍，真的“在环”——它看到的只是 CAN 帧，不知道自己在仿真里。') }}
        {{ t('机械臂：大臂 {a} m、小臂 {b} m，水平面里转；', { a: d.arm.l1, b: d.arm.l2 }) }}{{ td(d.arm.note) }}{{ t('。') }}</p>
      <p class="small">{{ t('监督规则：任何一个关节报警 → 下一拍给所有关节发“停”；任何一个关节心跳 {h} ms 没来 → 一起停；跟踪误差超过 {m}° → 一起停。', { h: d.arm.heart_timeout * 1000, m: d.arm.track_max }) }}</p>

      <h3>{{ t('场景（{p} / {n} 通过）', { p: d.scenarios.filter((s) => s.ok).length, n: d.scenarios.length }) }}</h3>
      <div class="line">
        <button v-for="s in d.scenarios" :key="s.id" class="chip" :class="{ on: sc && sc.id === s.id }" @click="pick(s.id)">
          {{ s.ok ? '✓' : '✗' }} {{ td(s.name) }}</button>
      </div>
      <div v-if="sc" class="card2">
        <p class="small">{{ td(sc.desc) }}</p>
        <div class="wrap">
          <div class="arm">
            <svg :viewBox="'0 0 ' + VW + ' ' + VH" class="svg">
              <line :x1="X(0)" :y1="Y(-0.05)" :x2="X(0)" :y2="Y(0.6)" class="ax" />
              <line :x1="X(-0.1)" :y1="Y(0)" :x2="X(0.6)" :y2="Y(0)" class="ax" />
              <line :x1="X(d.arm.p0[0])" :y1="Y(d.arm.p0[1])" :x2="X(d.arm.p1[0])" :y2="Y(d.arm.p1[1])" class="ideal" />
              <polyline :points="tipPath" class="tip" />
              <template v-if="pose">
                <line :x1="X(0)" :y1="Y(0)" :x2="X(pose.e[0])" :y2="Y(pose.e[1])" class="lk" />
                <line :x1="X(pose.e[0])" :y1="Y(pose.e[1])" :x2="X(pose.t[0])" :y2="Y(pose.t[1])" class="lk" />
                <circle :cx="X(0)" :cy="Y(0)" r="6" class="jt" />
                <circle :cx="X(pose.e[0])" :cy="Y(pose.e[1])" r="5" class="jt" />
                <circle :cx="X(pose.t[0])" :cy="Y(pose.t[1])" r="4" class="tp" />
              </template>
            </svg>
            <div class="slider">
              <input v-model.number="k" type="range" min="0" :max="S.t.length - 1" />
              <span class="small">{{ S.t[k].toFixed(2) }} s · {{ td(S.phase[k]) }} · {{ t('关节') }} {{ S.j1[k].toFixed(2) }}°, {{ S.j2[k].toFixed(2) }}°</span>
            </div>
            <p class="small muted">{{ t('虚线：要走的直线；实线：末端实际走过的路（由两个关节的真实角度算出）。') }}</p>
          </div>
          <div class="charts">
            <LineChart :title="t('关节 1 角度 °')" :t="S.t" :series="[{ name: tk('主站指令'), data: S.ref1, cls: 'ref' }, { name: tk('实际'), data: S.j1, cls: 'truth' }]" />
            <LineChart :title="t('关节 2 角度 °')" :t="S.t" :series="[{ name: tk('主站指令'), data: S.ref2, cls: 'ref' }, { name: tk('实际'), data: S.j2, cls: 'truth' }]" />
            <LineChart :title="t('输出开（MOE）与抱闸松开')" :t="S.t" :zero="true"
              :series="[{ name: tk('关节 1 输出'), data: S.moe1, cls: 'c2' }, { name: tk('关节 2 输出'), data: S.moe2, cls: 'c3' },
                        { name: tk('关节 1 抱闸松开'), data: S.brk1, cls: 'fwk' }, { name: tk('关节 2 抱闸松开'), data: S.brk2, cls: 'ref' }]" />
          </div>
        </div>
        <h4>{{ t('主站做的决定') }}</h4>
        <ul class="small ev"><li v-for="(e, i) in sc.events" :key="i"><b>{{ e[0].toFixed(2) }} s</b> {{ td(e[1]) }}</li></ul>
        <table class="tbl">
          <thead><tr><th>{{ t('判据') }}</th><th>{{ t('结果') }}</th><th>{{ t('读数') }}</th></tr></thead>
          <tbody><tr v-for="c in sc.checks" :key="c.name"><td>{{ td(c.name) }}</td><td>{{ c.ok ? '✓' : '✗' }}</td><td>{{ td(c.detail) }}</td></tr></tbody>
        </table>
        <details class="small"><summary>{{ t('CAN 帧（不含每 10 ms 的位置指令和状态帧，前 {n} 帧）', { n: sc.frames.length }) }}</summary>
          <div class="fr"><table class="tbl"><tbody>
            <tr v-for="(f, i) in sc.frames" :key="i" :class="{ emcy: (f.id & 0x780) === 0x080 }">
              <td>{{ f.t.toFixed(4) }}</td><td>{{ f.dir === 'tx' ? t('板→主站') : t('主站→板') }}</td><td class="mono">0x{{ f.id.toString(16).toUpperCase().padStart(3, '0') }}</td><td class="mono">{{ f.data }}</td></tr>
          </tbody></table></div>
        </details>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import LineChart from './LineChart.vue';
import { t, td, tk } from '../lib/i18n';

const d = ref(null);
const err = ref('');
const sc = ref(null);
const k = ref(0);
const VW = 360; const VH = 330; const SC = 520;
const X = (x) => 40 + x * SC;
const Y = (y) => VH - 30 - y * SC;
const S = computed(() => sc.value.series);
function fk(a1, a2) {
  const r1 = (a1 * Math.PI) / 180; const r2 = ((a1 + a2) * Math.PI) / 180;
  const e = [d.value.arm.l1 * Math.cos(r1), d.value.arm.l1 * Math.sin(r1)];
  return { e, t: [e[0] + d.value.arm.l2 * Math.cos(r2), e[1] + d.value.arm.l2 * Math.sin(r2)] };
}
const pose = computed(() => (sc.value ? fk(S.value.j1[k.value], S.value.j2[k.value]) : null));
const tipPath = computed(() => S.value.x.map((x, i) => X(x).toFixed(1) + ',' + Y(S.value.y[i]).toFixed(1)).join(' '));
function pick(id) {
  sc.value = d.value.scenarios.find((s) => s.id === id);
  const t = sc.value.series.t;
  const mid = sc.value.id === 'line' ? 1.45 : 1.6;
  k.value = Math.max(0, t.findIndex((x) => x >= mid));
}
onMounted(async () => {
  try {
    const r = await fetch('/api/designs/drv-joint-b/fw/sim_master.json');
    if (!r.ok) throw new Error(t('读不到多关节主站仿真结果（{s}）', { s: r.status }));
    d.value = await r.json();
    pick('line');
  } catch (e) { err.value = e.message || String(e); }
});
</script>

<style scoped>
.dia { border: 1px solid #e3e6ee; border-radius: 8px; padding: 8px; margin: 6px 0; background: #fbfcfe; }
.row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 4px 0; }
.b { border: 1px solid #cfd6e4; border-radius: 8px; padding: 5px 8px; background: #fff; font-size: 12px; font-weight: 600; }
.b small { display: block; font-weight: 400; color: #64748b; font-size: 11px; }
.b.mcu { background: #eff6ff; border-color: #93c5fd; } .b.host { background: #fff7ed; border-color: #fdba74; }
.ar { color: #64748b; }
.line { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.chip { border: 1px solid var(--line, #ccd); background: #fff; border-radius: 14px; padding: 3px 10px; cursor: pointer; font-size: 13px; }
.chip.on { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
.card2 { border: 1px solid #e3e6ee; border-radius: 8px; padding: 8px 10px; margin: 6px 0; }
.wrap { display: grid; grid-template-columns: minmax(260px, 360px) 1fr; gap: 12px; }
@media (max-width: 720px) { .wrap { grid-template-columns: 1fr; } }
.svg { width: 100%; background: #fff; border: 1px solid #eef0f5; border-radius: 8px; }
.ax { stroke: #cbd5e1; stroke-width: 1; }
.ideal { stroke: #94a3b8; stroke-width: 2; stroke-dasharray: 5 4; }
.tip { fill: none; stroke: #dc2626; stroke-width: 2; }
.lk { stroke: #1d4ed8; stroke-width: 6; stroke-linecap: round; }
.jt { fill: #fff; stroke: #1d4ed8; stroke-width: 2; } .tp { fill: #dc2626; }
.slider input { width: 100%; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; }
.ev { margin: 4px 0; padding-left: 18px; }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 6px; }
.tbl th, .tbl td { border-bottom: 1px solid #eef0f5; padding: 4px 6px; text-align: left; vertical-align: top; }
.fr { max-height: 40vh; overflow: auto; }
tr.emcy td { background: #fef2f2; }
.mono { font-family: ui-monospace, monospace; }
</style>
