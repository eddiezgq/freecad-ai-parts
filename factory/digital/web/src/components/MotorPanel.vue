<!-- 第 102 轮（电子 E8）：驱动板 B 版固件的电机控制与 CAN——控制框图、场景（曲线、判据、CAN 帧）、协议、参数表。第 107 轮输出端编码器、第 110 轮抱闸。
     产物 factory/designs/drv-joint-b/fw/out/sim_motor.json。 -->
<template>
  <div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="d">
      <div class="dia">
        <div class="row">
          <div class="b host">{{ t('CAN 主站') }}<small>{{ t('指令 0x201 / 状态 0x181') }}</small></div><span class="ar">⇄</span>
          <div class="b">{{ t('位置环 1 kHz') }}<small>{{ t('梯形轨迹 + P') }}</small></div><span class="ar">→</span>
          <div class="b">{{ t('速度环 2 kHz') }}<small>PI</small></div><span class="ar">→</span>
          <div class="b mcu">{{ t('电流环 20 kHz（FOC）') }}<small>{{ t('Clarke/Park、d/q PI、SVPWM') }}</small></div><span class="ar">→</span>
          <div class="b">{{ t('TIM1 三相 PWM') }}<small>{{ t('死区 200 ns') }}</small></div><span class="ar">→</span>
          <div class="b pw">{{ t('逆变桥 48 V → 电机 → 减速器 1:100 → 摆臂') }}</div>
        </div>
        <div class="row fb">
          <span>{{ t('抱闸：') }}</span><div class="b">{{ t('TIM4 PWM（PB6）') }}<small>{{ t('松闸先 100% 50 ms，再保持平均 24 V') }}</small></div><span class="ar">→</span>
          <div class="b pw">{{ t('U16 栅极驱动 → Q7 → 电机轴上的失电制动抱闸') }}<small>{{ t('没输出就抱住（第 110 轮）') }}</small></div><span class="ar">→</span>
          <div class="b">{{ t('R39 采样 → PB0（ADC）') }}<small>{{ t('测线圈电流：断线、过流、抱不住（第 114 轮）') }}</small></div>
        </div>
        <div class="row fb">
          <span>{{ t('反馈：') }}</span><div class="b chip">{{ t('编码器 → WQ-ENCIF → SPI1') }}<small>{{ t('角度、转速') }}</small></div>
          <div class="b chip">{{ t('输出端绝对值编码器 → SSI → SPI3') }}<small>{{ t('开机原点、双编码器互检（第 107 轮）') }}</small></div>
          <div class="b">{{ t('三相电流 → INA240 → ADC1') }}<small>{{ t('40 mV/A，过流 25 A 立即关管') }}</small></div>
        </div>
      </div>
      <p class="small">{{ t('编译出来的真固件（{f} 字节 Flash、{r} 字节 RAM，170 MHz、硬件浮点）在 Renode 里跑；', { f: d.firmware.flash, r: d.firmware.ram }) }}
        {{ t('电机、减速器、摆臂、逆变桥、电流采样和 CAN 主站都是仿真的（参数见下表，零件库没有的标“示例”）。判据都对仿真里的物理真值。') }}</p>
      <p class="small muted">⚠ {{ td(d.disclaimer) }}</p>
      <p class="small">{{ t('抱闸（第 110 轮，B 版电路加了抱闸驱动）：上电抱住；运动前先在原地稳住再松闸；“停”和欠压先停住、抱住，再关输出，摆臂不落；过流、编码器类危险故障关输出的同时抱闸，摆臂落一点就被抱住。第 107 轮还没有抱闸时，关输出后摆臂会在重力下落下。') }}</p>

      <h3>{{ t('场景（{p} / {n} 通过）', { p: d.scenarios.filter((s) => s.passed).length, n: d.scenarios.length }) }}</h3>
      <div class="line">
        <button v-for="s in d.scenarios" :key="s.id" class="chip" :class="{ on: sc && sc.id === s.id }" @click="pick(s.id)">
          {{ s.passed ? '✓' : '✗' }} {{ td(s.name) }}</button>
      </div>
      <div v-if="sc" class="card2">
        <p class="small">{{ td(sc.desc) }}</p>
        <div class="charts">
          <LineChart v-for="c in charts" :key="c.title" :title="c.title" :t="c.t || S.t" :series="c.series" :zero="c.zero" />
        </div>
        <table class="tbl">
          <thead><tr><th>{{ t('判据') }}</th><th>{{ t('结果') }}</th><th>{{ t('读数') }}</th></tr></thead>
          <tbody><tr v-for="(c, i) in sc.checks" :key="i"><td class="small">{{ td(c.name) }}</td>
            <td :class="c.ok ? 'ok' : 'bad'">{{ c.ok ? t('✓ 通过') : t('✗ 不通过') }}</td><td class="small">{{ td(c.detail) }}</td></tr></tbody>
        </table>
        <h4>{{ t('CAN 总线记录') }}
          <label class="small"><input v-model="routine" type="checkbox" /> {{ t('显示例行状态帧、心跳') }}</label></h4>
        <div class="fr">
          <table class="tbl">
            <thead><tr><th>{{ t('时刻 s') }}</th><th>{{ t('方向') }}</th><th>ID</th><th>{{ t('数据') }}</th><th>{{ t('解释') }}</th></tr></thead>
            <tbody><tr v-for="(f, i) in frames" :key="i" :class="f.id === '0x081' ? 'emcy' : ''">
              <td class="mono">{{ f.t.toFixed(4) }}</td><td>{{ f.dir === 'rx' ? t('主站→板') : t('板→主站') }}</td>
              <td class="mono">{{ f.id }}</td><td class="mono">{{ f.data }}</td><td class="small">{{ td(f.text) }}</td></tr></tbody>
          </table>
        </div>
      </div>

      <h3>{{ t('CAN 协议（示例，经典 CAN 1 Mbit/s，节点 1）') }}</h3>
      <table class="tbl small">
        <thead><tr><th>ID</th><th>{{ t('方向') }}</th><th>{{ t('内容') }}</th></tr></thead>
        <tbody>
          <tr><td class="mono">0x201</td><td>{{ t('主站→板') }}</td><td>{{ t('指令：[0] 模式（0 停、1 速度、2 位置、3 清故障、4 力矩）[1..4] 目标（速度 rpm；位置 关节 0.001°；力矩 q 轴 mA）。运行中至少 10 Hz 发。从就绪开始运动：先稳住、松闸，60 ms 后执行；“停”：停住 → 抱闸 → 关输出（第 110 轮）') }}</td></tr>
          <tr><td class="mono">0x181</td><td>{{ t('板→主站') }}</td><td>{{ t('状态 100 Hz：状态、故障码、关节角 0.01°、电机转速 rpm、q 轴电流 0.01 A') }}</td></tr>
          <tr><td class="mono">0x081</td><td>{{ t('板→主站') }}</td><td>{{ t('报警（出故障立即发）：故障码 1 过流、2 欠压、3 编码器、4 通信超时、5 输出端编码器、6 减速器 / 编码器不一致（第 107 轮）；相关值。1、3、5、6 立即关输出（同时抱闸）；4 减速停住、保持位置不断电；2 停住、抱闸后关输出；7 抱闸故障（第 114 轮，[3] 1 断线、2 过流、3 抱不住）：先在原地保持，确实抱住才关输出，抱不住就一直保持') }}</td></tr>
          <tr><td class="mono">0x701</td><td>{{ t('板→主站') }}</td><td>{{ t('心跳 10 Hz：状态、母线电压 0.1 V、抱闸（0 抱住、1 松开，第 110 轮）') }}</td></tr>
        </tbody>
      </table>

      <h3>{{ t('参数') }}</h3>
      <table class="tbl small">
        <thead><tr><th>{{ t('项目') }}</th><th>{{ t('值') }}</th><th>{{ t('来源') }}</th></tr></thead>
        <tbody><tr v-for="p in d.params" :key="p.name"><td>{{ td(p.name) }}</td><td>{{ td(p.value) }} {{ p.unit }}</td>
          <td :class="p.source.startsWith('示例') ? 'muted' : ''">{{ td(p.source) }}</td><!-- i18n-ok 按数据判断 --></tr></tbody>
      </table>
    </template>
    <p v-else-if="!err" class="muted">{{ t('读取中…') }}</p>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import LineChart from './LineChart.vue';
import { t, td, tk } from '../lib/i18n';

const d = ref(null);
const sc = ref(null);
const err = ref('');
const routine = ref(false);
const S = computed(() => sc.value.series);
function pick(id) { sc.value = d.value.scenarios.find((s) => s.id === id); }

function sub(t0, t1) {   // 取一段时间窗
  const idx = S.value.t.map((t, i) => (t >= t0 && t <= t1 ? i : -1)).filter((i) => i >= 0);
  return { t: idx.map((i) => S.value.t[i]), f: (k) => idx.map((i) => S.value[k][i]) };
}
const charts = computed(() => {
  const s = S.value; const id = sc.value.id;
  if (id === 'boot') {
    return [{ title: tk('d 轴电流 A（对零时 3 A）'), series: [{ name: tk('实际'), data: s.id, cls: 'truth' }], zero: true },
      { title: tk('关节角 °（转子被拉到电角度 0°）'), series: [{ name: tk('实际'), data: s.joint, cls: 'truth' }] }];
  }
  if (id === 'cur') {
    const w = sub(0.4995, 0.506);
    return [{ title: tk('q 轴电流 A（0.5 s 起阶跃，放大看 6 ms）'), t: w.t,
      series: [{ name: tk('实际'), data: w.f('iq'), cls: 'truth' }, { name: tk('指令'), data: w.f('iq_ref'), cls: 'ref' }], zero: true }];
  }
  if (id === 'spd') {
    return [{ title: tk('电机转速 rpm'), series: [{ name: tk('实际'), data: s.rpm, cls: 'truth' }, { name: tk('指令'), data: s.rpm_ref, cls: 'ref' },
      { name: tk('固件估计'), data: s.rpm_fw, cls: 'fwk' }], zero: true },
    { title: tk('q 轴电流 A'), series: [{ name: tk('实际'), data: s.iq, cls: 'truth' }], zero: true }];
  }
  if (id === 'pos') {
    return [{ title: tk('关节角 °'), series: [{ name: tk('实际'), data: s.joint, cls: 'truth' }, { name: tk('轨迹'), data: s.joint_ref, cls: 'ref' }] },
      { title: tk('电机转速 rpm'), series: [{ name: tk('实际'), data: s.rpm, cls: 'truth' }, { name: tk('指令'), data: s.rpm_ref, cls: 'ref' }], zero: true }];
  }
  if (id === 'hold') {
    const w = sub(1.7, 2.45);
    return [{ title: tk('关节角偏差 0.001°（1.9 s 加 0.5 kg）'), t: w.t, series: [{ name: tk('实际 − 90°'), data: w.f('joint').map((v) => (v - 90) * 1000), cls: 'truth' }], zero: true },
      { title: tk('q 轴电流 A'), t: w.t, series: [{ name: tk('实际'), data: w.f('iq'), cls: 'truth' }], zero: true }];
  }
  if (id === 'abs') {
    return [{ title: tk('关节角 °（开机在 37.5°，指令 90°）'), series: [{ name: tk('实际'), data: s.joint, cls: 'truth' }, { name: tk('轨迹'), data: s.joint_ref, cls: 'ref' }] }];
  }
  if (id === 'ssi' || id === 'slip') {
    return [{ title: id === 'ssi' ? tk('电机转速 rpm（0.6 s 线断）') : tk('关节角 °（0.9 s 打滑 2°）'),
      series: [{ name: tk('实际'), data: id === 'ssi' ? s.rpm : s.joint, cls: 'truth' }], zero: id === 'ssi' },
    { title: tk('状态（2 运行、3 故障）与输出'), series: [{ name: tk('状态'), data: s.state, cls: 'c2' }, { name: tk('输出开（MOE）'), data: s.moe, cls: 'ref' }], zero: true }];
  }
  if (id === 'stop') {
    return [{ title: tk('关节角 °（1.6 s 起不再发指令；2.6 s 欠压）'), series: [{ name: tk('实际'), data: s.joint, cls: 'truth' }], zero: true },
      { title: tk('状态与输出'), series: [{ name: tk('状态'), data: s.state, cls: 'c2' }, { name: tk('输出开（MOE）'), data: s.moe, cls: 'ref' },
        { name: tk('抱闸松开'), data: s.brake, cls: 'fwk' }], zero: true }];
  }
  if (id === 'brk_boot') {
    const w = sub(0.38, 0.6);
    return [{ title: tk('关节角 °（开机 60°，0.45 s 指令 90°）'), series: [{ name: tk('实际'), data: s.joint, cls: 'truth' }] },
      { title: tk('0.38–0.6 s 放大：关节角偏差 0.001°（相对 0.45 s）'), t: w.t,
        series: [{ name: tk('实际'), data: w.f('joint').map((v, i, a) => (v - a[w.t.findIndex((t) => t >= 0.45)]) * 1000), cls: 'truth' }], zero: true },
      { title: tk('输出与抱闸'), t: w.t, series: [{ name: tk('输出开（MOE）'), data: w.f('moe'), cls: 'ref' }, { name: tk('抱闸松开'), data: w.f('brake'), cls: 'fwk' },
        { name: tk('线圈电流 A'), data: w.f('brake_i'), cls: 'c3' }], zero: true }];
  }
  if (id === 'brk_open') {
    const w = sub(0.0, 0.2);
    return [{ title: tk('0–0.2 s：抱闸线圈电流 A（线断了：一直是 0）与输出'), t: w.t,
      series: [{ name: tk('线圈电流 A'), data: w.f('brake_i'), cls: 'c3' }, { name: tk('状态（3 = 故障）'), data: w.f('state'), cls: 'c2' },
        { name: tk('输出开（MOE）'), data: w.f('moe'), cls: 'ref' }], zero: true },
      { title: tk('关节角 °（一直在 60°）'), series: [{ name: tk('实际'), data: s.joint, cls: 'truth' }] }];
  }
  if (id === 'brk_short' || id === 'brk_fet') {
    const w = sub(1.65, id === 'brk_fet' ? 2.1 : 2.0);
    return [{ title: id === 'brk_short' ? tk('线圈电流 A（1.7 s 线圈短路）') : tk('线圈电流 A（1.7 s 开关管击穿）'), t: w.t,
      series: [{ name: tk('线圈电流 A'), data: w.f('brake_i'), cls: 'c3' }, { name: tk('抱闸松开'), data: w.f('brake'), cls: 'fwk' },
        { name: tk('输出开（MOE）'), data: w.f('moe'), cls: 'ref' }], zero: true },
      { title: tk('关节角偏差 0.001°（相对 90°）'), t: w.t, series: [{ name: tk('实际 − 90°'), data: w.f('joint').map((v) => (v - 90) * 1000), cls: 'truth' }], zero: true }];
  }
  if (id === 'brk_uv' || id === 'brk_ssi' || id === 'brk_stop') {
    const w = sub(1.65, 2.0);
    const ev = { brk_uv: tk('关节角偏差 0.001°（相对 90°，1.7 s 欠压）'), brk_ssi: tk('关节角偏差 0.001°（相对 90°，1.7 s 输出端编码器线断）'), brk_stop: tk('关节角偏差 0.001°（相对 90°，1.7 s 发“停”）') }[id];
    return [{ title: ev, t: w.t, series: [{ name: tk('实际 − 90°'), data: w.f('joint').map((v) => (v - 90) * 1000), cls: 'truth' }], zero: true },
      { title: tk('输出与抱闸'), t: w.t, series: [{ name: tk('输出开（MOE）'), data: w.f('moe'), cls: 'ref' }, { name: tk('抱闸松开'), data: w.f('brake'), cls: 'fwk' },
        { name: tk('线圈电流 A'), data: w.f('brake_i'), cls: 'c3' }], zero: true }];
  }
  return [{ title: tk('电机转速 rpm'), series: [{ name: tk('实际'), data: s.rpm, cls: 'truth' }], zero: true },
    { title: tk('相电流 A（0.6 s 短路）'), series: [{ name: tk('A 相'), data: s.ia, cls: 'c3' }, { name: tk('B 相'), data: s.ib, cls: 'fwk' }], zero: true },
    { title: tk('状态（0 对零、1 就绪、2 运行、3 故障）'), series: [{ name: tk('状态'), data: s.state, cls: 'c2' }, { name: tk('输出开（MOE）'), data: s.moe, cls: 'ref' }], zero: true }];
});
const frames = computed(() => (routine.value ? sc.value.frames : sc.value.frames.filter((f) => f.id !== '0x181' && f.id !== '0x701')));

onMounted(async () => {
  try {
    const r = await fetch('/api/designs/drv-joint-b/fw/sim_motor.json');
    if (!r.ok) throw new Error(t('读不到电机控制仿真结果（{s}）', { s: r.status }));
    d.value = await r.json();
    pick('pos');
  } catch (e) { err.value = e.message || String(e); }
});
</script>

<style scoped>
.dia { border: 1px solid #e3e6ee; border-radius: 8px; padding: 8px; margin: 6px 0; background: #fbfcfe; }
.row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 4px 0; }
.row.fb { font-size: 12px; color: #64748b; }
.b { border: 1px solid #cfd6e4; border-radius: 8px; padding: 5px 8px; background: #fff; font-size: 12px; font-weight: 600; }
.b small { display: block; font-weight: 400; color: #64748b; font-size: 11px; }
.b.mcu { background: #eff6ff; border-color: #93c5fd; } .b.chip { background: #ecfdf5; border-color: #86efac; }
.b.host { background: #fff7ed; border-color: #fdba74; } .b.pw { background: #fef2f2; border-color: #fca5a5; }
.ar { color: #64748b; }
.line { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.chip { border: 1px solid var(--line, #ccd); background: #fff; border-radius: 14px; padding: 3px 10px; cursor: pointer; font-size: 13px; }
.chip.on { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
.card2 { border: 1px solid #e3e6ee; border-radius: 8px; padding: 8px 10px; margin: 6px 0; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 6px; }
.tbl th, .tbl td { border-bottom: 1px solid #eef0f5; padding: 4px 6px; text-align: left; vertical-align: top; }
.fr { max-height: 50vh; overflow: auto; }
tr.emcy td { background: #fef2f2; }
.ok { color: #15803d; } .bad { color: #b91c1c; }
h4 { margin: 10px 0 2px; font-size: 14px; } h4 label { font-weight: 400; margin-left: 8px; }
</style>
