<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('数字孪生') }}</h1>
      <span class="muted">{{ $t('卖出去的每一台 WQR-105 在这里都有一个“分身”：出厂数据 + 现场运行数据 + 寿命模型，算还能用多久、哪里快坏了、该做什么') }}</span>
      <span class="labs small">{{ $t('实验 13：') }}<a href="/api/cae/lab13/guide.docx">{{ $t('指导书') }}</a> · <a href="/api/cae/lab13/report-template.docx">{{ $t('报告模板') }}</a></span></div>

    <div class="topbar">
      <span class="pill info">{{ $t('现场日期 {a}', { a: fleet?.field_today || '…' }) }}</span>
      <span v-if="fleet?.clock.simulated" class="small muted">{{ $t('客户现场是模拟的：{a}', { a: fleet.clock.paused ? $t('时钟停着') : $t('1 分钟 = {a} 个现场日', { a: fleet.clock.days_per_min }) }) }}</span>
      <span v-else class="small muted">{{ $t('等真设备上报数据（主题 wq/gearbox/field/&lt;序列号&gt;/telemetry）') }}</span>
      <span class="grow"></span>
      <label class="small">{{ $t('客户') }} <select v-model="siteSel"><option value="">{{ $t('全部') }}</option><option v-for="(s, k) in fleet?.sites || {}" :key="k" :value="k">{{ $td(s.label) }}</option></select></label>
      <label class="small">{{ $t('排序') }} <select v-model="sortBy"><option value="health">{{ $t('健康度') }}</option><option value="life">{{ $t('剩余寿命') }}</option><option value="serial">{{ $t('序列号') }}</option></select></label>
      <button v-if="teacher && fleet?.clock.simulated" class="btn small-btn" type="button" @click="showConsole = !showConsole">{{ showConsole ? $t('收起') : $t('老师控制台') }}</button>
    </div>

    <section v-if="showConsole && teacher" class="card console">
      <div class="card-head"><h2>{{ $t('老师控制台') }}</h2><span class="small muted">{{ $t('学生看不到这里；故障从当前现场日开始生效') }}</span></div>
      <div class="line">{{ $t('现场时钟：') }}
        <button v-for="v in [0, 1, 3, 10, 30]" :key="v" type="button" class="btn small-btn" :class="{ primary: fleet.clock.days_per_min === v && !(v && fleet.clock.paused) }" @click="setClock(v)">{{ v ? $t('1 分钟 = {a} 天', { a: v }) : $t('停住') }}</button>
      </div>
      <table v-if="faults" class="t">
        <thead><tr><th>{{ $t('序列号') }}</th><th>{{ $t('客户') }}</th><th>{{ $t('现在的故障') }}</th><th>{{ $t('注入故障') }}</th></tr></thead>
        <tbody><tr v-for="u in faults.units" :key="u.serial">
          <td class="mono">{{ $td(u.serial) }}</td><td>{{ $td(fleet.sites[u.site]?.label) }}</td>
          <td class="small">{{ u.faults.map((f) => $td(FAULT_NAME[f.kind] || f.kind) + $t('（{a} 起）', { a: f.start })).join($t('；')) || '—' }}</td>
          <td class="line"><button v-for="(t, k) in faults.catalog" :key="k" type="button" class="btn small-btn" :title="t" @click="fault(u.serial, k)">{{ $td(FAULT_NAME[k]) }}</button>
            <button v-if="u.faults.length" type="button" class="btn ghost small-btn" @click="fault(u.serial, null)">{{ $t('清除') }}</button></td>
        </tr></tbody>
      </table>
    </section>

    <div class="row">
      <section class="card side">
        <div class="card-head"><h2>{{ $t('在用设备 {a} 台', { a: shown.length }) }}</h2>
          <span class="small"><span class="dot red"></span>{{ $td(count.red) }} <span class="dot yellow"></span>{{ $td(count.yellow) }} <span class="dot green"></span>{{ $td(count.green) }}</span></div>
        <div v-if="!fleet" class="empty">{{ $t('正在读取…') }}</div>
        <div v-else-if="!shown.length" class="empty">{{ $t('还没有设备。跑合试验通过的 WQR-105 会自动建档。') }}</div>
        <button v-for="u in shown" :key="u.serial" type="button" class="unit" :class="[u.health, { on: sel === u.serial }]" @click="open(u.serial)">
          <div class="u1"><span class="dot" :class="u.health"></span><b class="mono">{{ $td(u.serial) }}</b><span class="small muted">{{ $td(fleet.sites[u.site]?.label) || $t('现场接入') }}</span></div>
          <div class="u2 small">
            <span>{{ $td(u.summary.worst_bearing.name.replace(/（.*）/, '')) }}<!-- i18n-ok --> {{ pctx(u.summary.worst_bearing.used) }}</span>
            <span>{{ $t('· 剩 {a}', { a: daysTxt(u.summary.worst_bearing.remaining_days) }) }}</span>
            <span v-if="u.summary.vib != null">{{ $t('· 振动 {a}', { a: u.summary.vib.toFixed(2) }) }}</span>
          </div>
          <div v-for="a in u.alerts.filter((x) => x.level !== 'info')" :key="a.kind" class="u3 small" :class="a.level">{{ $td(a.title) }}</div>
        </button>
      </section>

      <section class="card grow">
        <div v-if="!d" class="big-empty muted">{{ $t('左边点一台，看它的分身：三维健康图、运行曲线、寿命预测、出厂数据、“假如”分析。') }}</div>
        <template v-else>
          <div class="card-head"><h2 class="mono"><ObjLink type="FieldUnit" :k="d.serial" /></h2>
            <span class="pill" :class="{ red: 'bad', yellow: 'warn', green: 'good' }[d.health]">{{ { red: $t('报警'), yellow: $t('注意'), green: $t('正常') }[d.health] }}</span>
            <span class="small muted">{{ $t('{a} · {b} 起运行 · 已运行 {c} 小时、起动 {d} 次', { a: d.customer || $t('现场接入'), b: d.start_day, c: d.state.run_h.toFixed(0), d: d.state.starts }) }}</span></div>

          <div v-for="e in openAlerts" :key="e.id" class="alert" :class="e.level">
            <div><b>{{ $td(e.title) }}</b><span class="small muted">{{ $t('（{a}）', { a: e.day }) }}</span></div>
            <div class="small">{{ $td(e.detail.detail) }}</div>
            <div class="small"><b>{{ $t('原因：') }}</b>{{ $td(e.detail.cause) }}</div>
            <div class="small"><b>{{ $t('建议：') }}</b>{{ $td(e.detail.advice) }}</div>
            <div v-if="e.detail.action" class="line">
              <button v-if="e.status === 'open'" class="btn small-btn" type="button" @click="preview(e.detail.action.kind, e)">{{ $td(e.detail.action.label) }}</button>
              <span v-else class="small okline">{{ $t('已派单，等维修完成') }}</span>
            </div>
          </div>
          <div class="line">
            <button class="btn small-btn" type="button" :disabled="expBusy" @click="explain">{{ expBusy ? $t('AI 正在看…') : $t('请 AI 说说这台怎么了') }}</button>
            <button class="btn ghost small-btn" type="button" @click="preview('oil', null)">{{ $t('开维修单：换油') }}</button>
          </div>
          <div v-if="exp" class="exp"><p v-for="(t, i) in exp.text.split('\n')" :key="i">{{ t }}</p>
            <div class="small muted">{{ exp.engine === 'rules' ? $t('（规则生成：没配 AI 模型时用）') : $t('（由 AI 模型生成）') }}</div></div>
          <div v-if="pv" class="order">
            <div><b>{{ $t('维修单预览') }}</b>{{ $t('（确认后写进 ERPNext 的服务工单 Issue，派给服务工程师）') }}</div>
            <div class="small"><b>{{ $td(pv.subject) }}</b> · {{ $t('优先级：{a}', { a: pv.priority }) }}</div>
            <pre class="small">{{ $td(pv.description) }}</pre>
            <div class="line"><button class="btn primary small-btn" type="button" :disabled="ordBusy" @click="order">{{ $t('确认开单') }}</button>
              <button class="btn ghost small-btn" type="button" @click="pv = null">{{ $t('取消') }}</button></div>
          </div>
          <div v-for="o in openOrders" :key="o.id" class="order">
            <div><b>{{ $td(o.title) }}</b> <span class="small muted">{{ $t('（{a} 开单，{b}；提议 {c}）', { a: $td(o.detail.by), b: o.day, c: o.detail.proposal_id }) }}</span></div>
            <div class="line"><input v-model="doneNote[o.id]" class="note" :placeholder="$t('维修记录（可不填），例如：拆检发现中间轴轴承 B 外圈剥落，已更换')">
              <button class="btn primary small-btn" type="button" @click="done(o)">{{ $t('维修完成') }}</button></div>
          </div>

          <div class="two">
            <GearboxTwin :bearings="viewBearings" :shaft="{ used: d.summary.shaft.used }" :housing="housing" />
            <div class="cards">
              <div class="kpi" :class="lvl(d.summary.worst_bearing.used)"><span class="small muted">{{ $t('最先到期的轴承') }}</span>
                <span class="big">{{ $td(d.summary.worst_bearing.name.replace(/（.*）/, '')) }}<!-- i18n-ok --></span>
                <span class="small">{{ $t('已用 L10 {a} · 约剩 {b}', { a: pctx(d.summary.worst_bearing.used), b: daysTxt(d.summary.worst_bearing.remaining_days) }) }}</span></div>
              <div class="kpi" :class="lvl(d.summary.shaft.used / 0.5 * 0.8)"><span class="small muted">{{ $t('输出轴疲劳') }}</span>
                <span class="big">{{ pctx(d.summary.shaft.used, 2) }}</span><span class="small">{{ $t('约剩 {a}', { a: daysTxt(d.summary.shaft.remaining_days) }) }}</span></div>
              <div class="kpi" :class="d.summary.oil.left_h <= 0 ? 'bad' : d.summary.oil.days != null && d.summary.oil.days < 14 ? 'warn' : ''"><span class="small muted">{{ $t('换油') }}</span>
                <span class="big">{{ d.summary.oil.left_h <= 0 ? $t('已过期') : $t('剩 ') + d.summary.oil.left_h.toFixed(0) + ' h' }}</span>
                <span class="small">{{ $t('当量 {a} / {b} h', { a: d.summary.oil.eq_h.toFixed(0), b: d.summary.oil.due_h }) }}</span></div>
              <div class="kpi" :class="(d.summary.resid_c || 0) > 12 ? 'bad' : (d.summary.resid_c || 0) > 6 ? 'warn' : ''"><span class="small muted">{{ $t('油温 实测 − 模型') }}</span>
                <span class="big">{{ d.summary.resid_c == null ? '—' : (d.summary.resid_c > 0 ? '+' : '') + d.summary.resid_c.toFixed(1) + ' ℃' }}</span><span class="small">{{ $t('超过 6 ℃ 说明散热变差') }}</span></div>
              <div class="kpi" :class="{ C: 'warn', D: 'bad' }[d.summary.vib_zone] || ''"><span class="small muted">{{ $t('振动烈度') }}</span>
                <span class="big">{{ d.summary.vib == null ? '—' : d.summary.vib.toFixed(2) + ' mm/s' }}</span><span class="small">{{ $t('ISO 10816-1 {a} 区', { a: d.summary.vib_zone || '' }) }}</span></div>
            </div>
          </div>

          <div class="seg"><button v-for="r in RANGES" :key="r" type="button" :class="{ on: range === r }" @click="range = r">{{ $t('最近 {a} 天', { a: r }) }}</button></div>
          <DayChart :title="$t('油温：实测和热平衡模型')" unit="℃" :days="days" :series="[
            { label: $t('实测'), values: col('oil_t_c'), color: '#D64541' }, { label: $t('模型'), values: col('oil_model_c'), color: '#2F6FDE', dash: '6 4' },
            { label: $t('环境'), values: col('t_amb_c'), color: '#8A948C' }]" :refs="[{ y: 90, label: '90 ℃', color: '#D64541' }]" />
          <DayChart :title="$t('振动烈度')" unit="mm/s" :days="days" :min="0" :series="[{ label: $t('振动'), values: col('vib_mm_s'), color: '#7C4DDB' }]"
            :bands="[{ from: 0, to: 0.71, color: '#2E9E5B', label: 'A' }, { from: 1.8, to: 4.5, color: '#E0A100', label: 'C' }, { from: 4.5, to: 99, color: '#D64541', label: 'D' }]"
            :refs="[{ y: 1.8, label: $t('C 区'), color: '#E0A100' }, { y: 4.5, label: $t('D 区'), color: '#D64541' }]" />
          <DayChart :title="$t('输出转矩')" unit="N·m" :days="days" :min="0" :series="[
            { label: $t('运行时平均'), values: col('torque_mean_nm'), color: '#1F8A5B' }, { label: $t('当天最大'), values: col('torque_max_nm'), color: '#E08A00' }]"
            :refs="[{ y: 350, label: $t('额定 350'), color: '#5B6670' }]" />

          <h3>{{ $t('六个轴承') }}</h3>
          <table class="t">
            <thead><tr><th>{{ $t('轴承') }}</th><th>{{ $t('型号') }}</th><th class="num">C kN</th><th class="num">{{ $t('额定时径向力 N') }}</th><th class="num">{{ $t('额定时 L10 h') }}</th><th class="num">{{ $t('已用') }}</th><th class="num">{{ $t('约剩') }}</th></tr></thead>
            <tbody><tr v-for="b in d.summary.bearings" :key="b.id" :class="lvl(b.used)">
              <td>{{ $td(b.name) }}</td><td>{{ $td(b.model) }}</td><td class="num">{{ (b.C_n / 1000).toFixed(1) }}</td>
              <td class="num">{{ d.model?.loads?.[b.id]?.toFixed(0) }}</td><td class="num">{{ d.model?.l10?.[b.id]?.toFixed(0) }}</td>
              <td class="num">{{ pctx(b.used) }}</td><td class="num">{{ daysTxt(b.remaining_days) }}</td></tr></tbody>
          </table>
          <div class="small muted">{{ $t('L10 = (C/P)³ × 10⁶ 转（ISO 281，球轴承）；P 是直齿轮啮合力分到轴承上的径向力（两支点简支）。“已用”按现场每天的转矩分布累加：Σ 运行小时 ÷ 该转矩下的 L10。') }}</div>

          <h3>{{ $t('假如……') }}</h3>
          <div class="whatif">
            <label>{{ $t('负载') }} <input v-model.number="wi.load" type="range" min="0.5" max="1.3" step="0.05"><b>{{ Math.round(wi.load * 100) }}%</b></label>
            <label class="chk"><input v-model="wi.fan" type="checkbox"> {{ $t('轴端加风扇（散热系数 17.45 → {a}）', { a: fan.k }) }}<span class="small muted" :title="fan.src">{{ fan.src.startsWith('流体') /* i18n-ok 数据前缀 */ ? $t('· 来自流体分析') : $t('· 教材值') }}</span></label>
            <label>{{ $t('输出轴材料') }} <select v-model="wi.mat"><option value="45-QT">{{ $t('45 钢调质（现行）') }}</option><option value="40Cr-QT">{{ $t('40Cr 调质') }}</option></select></label>
            <button class="btn" type="button" :disabled="wiBusy" @click="whatif">{{ wiBusy ? $t('计算中…') : $t('重算') }}</button>
          </div>
          <table v-if="wiRes" class="t">
            <thead><tr><th></th><th class="num">{{ $t('最先到期的轴承约剩') }}</th><th class="num">{{ $t('输出轴约剩') }}</th><th class="num">{{ $t('换油间隔') }}</th><th class="num">{{ $t('平均油温') }}</th></tr></thead>
            <tbody>
              <tr><td>{{ $t('现在') }}</td><td class="num">{{ daysTxt(wiRes.base.bearing_days) }}</td><td class="num">{{ daysTxt(wiRes.base.shaft_days) }}</td><td class="num">{{ daysTxt(wiRes.base.oil_interval_days) }}</td><td class="num">{{ wiRes.base.oil_t_c?.toFixed(1) }} ℃</td></tr>
              <tr class="good"><td>{{ $t('假如') }}</td><td class="num">{{ daysTxt(wiRes.alt.bearing_days) }}</td><td class="num">{{ daysTxt(wiRes.alt.shaft_days) }}</td><td class="num">{{ daysTxt(wiRes.alt.oil_interval_days) }}</td><td class="num">{{ wiRes.alt.oil_t_c?.toFixed(1) }} ℃</td></tr>
            </tbody>
          </table>
          <div v-if="wiRes" class="small muted">{{ $t('按最近 {a} 个现场日的实测工况重算：轴承寿命 ∝ 1/载荷³（降到 {b}% 约为 {c} 倍）；疲劳按 S-N 曲线（斜率 9，对载荷更敏感）；换油按油温每高 10 ℃ 寿命减半。', { a: wiRes.days, b: Math.round(wiRes.load * 100), c: (1 / wiRes.load ** 3).toFixed(2) }) }}</div>

          <h3>{{ $t('出厂数据') }}</h3>
          <div class="ab small">
            <div>{{ $t('工单') }} <b class="mono"><ObjLink v-if="d.as_built.work_order" type="WorkOrder" :k="d.as_built.work_order" /><template v-else>—</template></b>{{ $t('；{a}', { a: d.as_built.note || '' }) }}</div>
            <div v-if="d.as_built.design">{{ $t('输出轴设计：SH-301 第 {a} 版，齿轮位 Ø{b}，材料 {c}', { a: d.as_built.design.revision ?? '—', b: d.as_built.design.segments?.[2]?.[0], c: d.as_built.design.material || '45-QT' }) }}</div>
            <div v-if="d.as_built.runin?.peak_nm">{{ $t('跑合试验：{a}，峰值 {b} N·m、运行平均 {c} N·m', { a: d.as_built.runin.program, b: d.as_built.runin.peak_nm, c: d.as_built.runin.mean_run_nm }) }}</div>
            <div v-if="d.as_built.shaft">{{ $t('输出轴') }} <b class="mono"><ObjLink type="PartSerial" :k="d.as_built.shaft.serial" /></b>{{ $t('（{a}）：', { a: d.as_built.shaft.how }) }}
              <span v-for="(m, k) in d.as_built.shaft.meas" :key="k" class="meas">{{ $td(m.name) }} {{ $td(m.value) }}</span></div>
            <div v-if="!d.as_built.shaft && !d.as_built.runin" class="muted">{{ $t('这台是现场先接入的设备，没有出厂档案。') }}</div>
          </div>

          <h3>{{ $t('维修与报警记录') }}</h3>
          <table class="t">
            <thead><tr><th>{{ $t('现场日') }}</th><th>{{ $t('类别') }}</th><th>{{ $t('内容') }}</th><th>{{ $t('状态') }}</th></tr></thead>
            <tbody><tr v-for="e in d.events" :key="e.id"><td>{{ $td(e.day) }}</td><td>{{ e.kind === 'maint' ? $t('维修') : e.kind === 'order' ? $t('维修单') : LV[e.level] }}</td><td>{{ $td(e.title) }}</td><td>{{ ST[e.status] || e.status }}</td></tr></tbody>
          </table>
        </template>
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>{{ $t('机械臂关节孪生') }}</h2><span class="small muted">{{ $t('一个搬运循环（“运动与动力分析”算的关节力矩、转速）→ 每个关节谐波减速器的寿命，按每天运行小时累计') }}</span></div>
      <div class="line">
        <select v-model="rb.job" class="jobsel"><option value="">{{ $t('选一次已完成的动力学计算…') }}</option>
          <option v-for="j in mbdJobs" :key="j.id" :value="j.id">{{ $t('{a}（{b}）', { a: j.title || j.id, b: j.id }) }}</option></select>
        <label class="small">{{ $t('每天运行') }} <input v-model.number="rb.hours" type="number" min="1" max="24" class="numin"> {{ $t('小时') }}</label>
        <button class="btn small-btn" type="button" :disabled="!rb.job || rbBusy" @click="addRobot">{{ rbBusy ? $t('计算中…') : $t('建孪生') }}</button>
        <a href="/mbd" class="small">{{ $t('去“运动与动力分析”算一个搬运循环 →') }}</a>
      </div>
      <div v-if="!robotList.length" class="empty small">{{ $t('还没有机械臂孪生。') }}</div>
      <div v-for="r in robotList" :key="r.id" class="robot">
        <div><b>{{ $td(r.name) }}</b> <span class="small muted">{{ $t('· {a} 起 · 每天 {b} h · 已运行 {c} h · 循环 {d} s · 最先到期：{e}', { a: r.start_day, b: r.hours_per_day, c: r.run_h.toFixed(0), d: r.cycle_s?.toFixed(1), e: r.first || '—' }) }}</span></div>
        <table class="t">
          <thead><tr><th>{{ $t('关节') }}</th><th>{{ $t('谐波减速器') }}</th><th class="num">i</th><th class="num">{{ $t('平均负载力矩') }}</th><th class="num">{{ $t('平均输入转速') }}</th><th class="num">L10 h</th><th>{{ $t('已用') }}</th><th class="num">{{ $t('约剩') }}</th></tr></thead>
          <tbody><tr v-for="j in r.joints" :key="j.joint" :class="lvl(j.used)">
            <td class="mono">{{ $td(j.joint) }}</td><td>{{ $t('{a}（额定 {b} N·m）', { a: j.gear, b: j.rated_Nm }) }}</td><td class="num">{{ $td(j.ratio) }}</td>
            <td class="num">{{ j.T_av?.toFixed(1) }} N·m</td><td class="num">{{ j.n_av_in?.toFixed(0) }} r/min</td><td class="num">{{ j.L10_h ? j.L10_h.toFixed(0) : '—' }}</td>
            <td><span class="bar"><i :style="{ width: Math.min(100, j.used * 100) + '%' }"></i></span> {{ pctx(j.used) }}</td><td class="num">{{ daysTxt(j.remaining_days) }}</td></tr></tbody>
        </table>
        <div class="small muted">{{ $t('{a}；T_av 按输入转速加权的立方平均，n_av 含停顿；每天负载在 ±10% 内变，按 3 次方折算。', { a: r.formula }) }}</div>
      </div>
    </section>

    <section class="card">
      <div class="card-head"><h2>{{ $t('机队数据反馈设计') }}</h2><span class="small muted">{{ $t('每类客户的实际载荷和设计假设（额定 350 N·m）比，寿命最短的部位') }}</span>
        <button class="btn small-btn" type="button" @click="loadFb">{{ fb ? $t('刷新') : $t('汇总') }}</button></div>
      <template v-if="fb">
        <table class="t">
          <thead><tr><th>{{ $t('客户') }}</th><th class="num">{{ $t('台数') }}</th><th class="num">{{ $t('平均每天 h') }}</th><th class="num">{{ $t('平均转矩') }}</th><th class="num">{{ $t('轴承当量转矩') }}</th><th class="num">{{ $t('占额定') }}</th><th class="num">{{ $t('日最大转矩 P95') }}</th><th class="num">{{ $t('卡料天数') }}</th><th>{{ $t('最先到期') }}</th><th class="num">{{ $t('每年用掉 L10') }}</th></tr></thead>
          <tbody><tr v-for="x in fb.sites" :key="x.site" :class="x.worst_rate_per_year > 0.25 ? 'warn' : ''">
            <td>{{ $td(x.label) }}</td><td class="num">{{ $td(x.units) }}</td><td class="num">{{ x.hours_per_day.toFixed(1) }}</td>
            <td class="num">{{ x.torque_mean_nm.toFixed(0) }}</td><td class="num">{{ x.torque_eq_nm.toFixed(0) }}</td><td class="num">{{ (x.eq_vs_rated * 100).toFixed(0) }}%</td>
            <td class="num">{{ x.torque_max_p95_nm?.toFixed(0) }}</td><td class="num">{{ (x.shock_days_pct * 100).toFixed(0) }}%</td>
            <td>{{ $td(x.worst_bearing_name) }}</td><td class="num">{{ (x.worst_rate_per_year * 100).toFixed(0) }}%</td></tr></tbody>
        </table>
        <p v-for="(n, i) in fb.notes" :key="i" class="small">{{ n }}</p>
        <div class="line"><button class="btn small-btn" type="button" @click="toDesign">{{ $t('把现场结论带到设计台 →') }}</button>
          <span class="small muted">{{ $t('设计台里填好现行参数和这段说明，工程师据此改版（还没发布）') }}</span></div>
      </template>
    </section>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post, session } from '../lib/api';
import GearboxTwin from '../components/GearboxTwin.vue';
import DayChart from '../components/DayChart.vue';
import ObjLink from '../components/ObjLink.vue';

const route = useRoute(), router = useRouter();
const FAULT_NAME = { cooling: $t('散热变差'), bearing: $t('轴承损坏'), overload: $t('过载') };
const LV = { info: $t('提示'), warn: $t('警告'), critical: $t('严重') };
const ST = { open: $t('未处理'), cleared: $t('已消失'), done: $t('已完成'), ordered: $t('已派单'), resolved: $t('已解决') };
const RANGES = [30, 90, 365];
const H_ORDER = { red: 0, yellow: 1, green: 2 };
const teacher = computed(() => !!session.user?.teacher);
const fleet = ref(null), d = ref(null), sel = ref(route.query.serial || ''), faults = ref(null);
const siteSel = ref(''), sortBy = ref('health'), showConsole = ref(false), range = ref(90);
const fan = ref({ k: 31, src: $t('教材') });
const wi = ref({ load: 0.8, fan: false, mat: '45-QT' }), wiRes = ref(null), wiBusy = ref(false);
const exp = ref(null), expBusy = ref(false), pv = ref(null), ordBusy = ref(false), doneNote = ref({}), fb = ref(null);
const mbdJobs = ref([]), robotList = ref([]), rb = ref({ job: '', hours: 16 }), rbBusy = ref(false);
async function loadRobots() {
  try { robotList.value = (await get('/twin/robots')).robots; } catch (e) { /* */ }
  try { mbdJobs.value = (await get('/mbd/jobs')).jobs.filter((j) => j.status === 'done'); } catch (e) { /* */ }
}
async function addRobot() {
  rbBusy.value = true;
  try { await post('/twin/robots', { mbd_job: rb.value.job, hours_per_day: rb.value.hours }); await loadRobots(); }
  catch (e) { alert(e.message); } finally { rbBusy.value = false; }
}
let timer = null;
const openOrders = computed(() => (d.value?.events || []).filter((e) => e.kind === 'order' && e.status === 'ordered'));
async function explain() {
  expBusy.value = true;
  try { exp.value = await post(`/twin/units/${encodeURIComponent(sel.value)}/explain`); } catch (e) { alert(e.message); } finally { expBusy.value = false; }
}
let pvEvent = null;
async function preview(action, ev) {
  pvEvent = ev;
  try { pv.value = await post(`/twin/units/${encodeURIComponent(sel.value)}/order`, { action, event_id: ev?.id, preview_only: true }); } catch (e) { alert(e.message); }
}
async function order() {
  ordBusy.value = true;
  try { await post(`/twin/units/${encodeURIComponent(sel.value)}/order`, { action: pv.value.action, event_id: pvEvent?.id }); pv.value = null; await loadUnit(); }
  catch (e) { alert(e.message); } finally { ordBusy.value = false; }
}
async function done(o) {
  try { await post(`/twin/units/${encodeURIComponent(sel.value)}/done`, { order_id: o.id, note: doneNote.value[o.id] || '' }); await loadFleet(); }
  catch (e) { alert(e.message); }
}
async function loadFb() { try { fb.value = await get('/twin/feedback'); } catch (e) { alert(e.message); } }
async function toDesign() {
  const p = await get('/design/SH-301/params');
  router.push({ path: '/work/engineer', query: { suggest: JSON.stringify(p.params), note: $t('数字孪生现场反馈：') + fb.value.notes.join(' ') } });
}

const shown = computed(() => {
  const u = (fleet.value?.units || []).filter((x) => !siteSel.value || x.site === siteSel.value);
  const life = (x) => x.summary.worst_bearing.remaining_days ?? 1e9;
  return [...u].sort((a, b) => (sortBy.value === 'serial' ? a.serial.localeCompare(b.serial)
    : sortBy.value === 'life' ? life(a) - life(b) : (H_ORDER[a.health] - H_ORDER[b.health]) || life(a) - life(b)));
});
const count = computed(() => { const c = { red: 0, yellow: 0, green: 0 }; shown.value.forEach((u) => { c[u.health] += 1; }); return c; });
const openAlerts = computed(() => (d.value?.events || []).filter((e) => ['open', 'ordered'].includes(e.status) && !['maint', 'order'].includes(e.kind)));
const logs = computed(() => (d.value?.log || []).slice(-range.value));
const days = computed(() => logs.value.map((r) => r.day));
const col = (k) => logs.value.map((r) => (r.run_h > 0 && r[k] != null ? r[k] : (k === 't_amb_c' ? r[k] : null)));
const viewBearings = computed(() => {
  const alarm = openAlerts.value.find((e) => e.kind === 'bearing');
  const bid = alarm?.detail?.action?.kind?.split(':')[1];
  return (d.value?.summary.bearings || []).map((b) => ({ ...b, alarm: b.id === bid }));
});
const housing = computed(() => {
  const s = d.value?.summary || {}, r = s.resid_c || 0;
  const level = r > 12 || s.oil?.left_h <= 0 ? 'bad' : r > 6 ? 'warn' : 'ok';
  return { level, text: $t('油温比模型{a} {b} ℃；换油{c}', { a: r >= 0 ? $t('高') : $t('低'), b: Math.abs(r).toFixed(1), c: s.oil?.left_h <= 0 ? $t('已过期') : $t('还剩 {a} 当量小时', { a: s.oil?.left_h?.toFixed(0) }) }) };
});
const pctx = (u, n = 1) => `${((u || 0) * 100).toFixed(n)}%`;
const lvl = (u) => (u >= 0.8 ? 'bad' : u >= 0.5 ? 'warn' : '');
function daysTxt(v) {
  if (v == null) return $t('很久');
  if (v > 3650) return $t('> 10 年');
  if (v > 365) return (v / 365).toFixed(1) + $t(' 年');
  return Math.round(v) + $t(' 天');
}

async function loadFleet() {
  try { fleet.value = await get('/twin/fleet'); } catch (e) { /* */ }
  if (sel.value) loadUnit();
  if (showConsole.value) loadFaults();
}
async function loadUnit() {
  try { d.value = await get('/twin/units/' + encodeURIComponent(sel.value)); } catch (e) { d.value = null; }
}
async function loadFaults() { try { faults.value = await get('/twin/faults'); } catch (e) { /* */ } }
function open(s) {
  sel.value = s; wiRes.value = null; exp.value = null; pv.value = null;
  router.replace({ query: { ...route.query, serial: s } });
  loadUnit();
}
async function whatif() {
  wiBusy.value = true;
  try { wiRes.value = await post(`/twin/units/${encodeURIComponent(sel.value)}/whatif`, wi.value); } catch (e) { alert(e.message); } finally { wiBusy.value = false; }
}
async function setClock(v) { await post('/twin/clock', { days_per_min: v }); loadFleet(); }
async function fault(serial, kind) { await post(`/twin/units/${encodeURIComponent(serial)}/fault`, { kind }); loadFaults(); }
watch(showConsole, (v) => { if (v) loadFaults(); });

onMounted(() => { get('/twin/fan').then((r) => { fan.value = r; }).catch(() => {}); loadFleet(); loadRobots(); timer = setInterval(() => { loadFleet(); get('/twin/robots').then((r) => { robotList.value = r.robots; }).catch(() => {}); }, 10000); });
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.labs { margin-left: auto; white-space: nowrap; }
.topbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.topbar .grow { flex: 1; }
.side { width: 360px; flex-shrink: 0; display: flex; flex-direction: column; gap: 6px; align-self: flex-start; max-height: calc(100vh - 180px); overflow-y: auto; }
.grow { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.unit { text-align: left; border: 1px solid var(--line); border-left: 4px solid #2E9E5B; border-radius: 8px; padding: 6px 8px; background: #fff; cursor: pointer; display: flex; flex-direction: column; gap: 2px; }
.unit.yellow { border-left-color: #E0A100; }
.unit.red { border-left-color: #D64541; }
.unit.on { background: var(--accent-bg); }
.u1 { display: flex; gap: 6px; align-items: center; }
.u1 .muted { margin-left: auto; }
.u3.warn { color: #9A6B00; }
.u3.critical { color: #B03030; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; background: #2E9E5B; margin: 0 2px 0 6px; }
.dot.yellow { background: #E0A100; }
.dot.red { background: #D64541; }
.two { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 10px; }
.cards { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; align-content: start; }
.kpi { border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; display: flex; flex-direction: column; gap: 1px; }
.kpi.warn, tr.warn td { background: #FFF6DD; }
.kpi.bad, tr.bad td { background: #FDECEC; }
tr.good td { background: var(--good-bg); }
.big { font-size: 16px; font-weight: 600; }
.alert { border-radius: 8px; padding: 8px 12px; background: #FFF6DD; border: 1px solid #F0D58A; display: flex; flex-direction: column; gap: 2px; }
.alert.critical { background: #FDECEC; border-color: #F2B8B8; }
.alert.info { background: var(--surface-2); border-color: var(--line); }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; align-self: flex-start; }
.seg button { border: 0; background: #fff; padding: 5px 12px; cursor: pointer; font-size: 13px; }
.seg button.on { background: var(--accent-bg); font-weight: 600; }
h3 { margin: 8px 0 0; font-size: 15px; }
.whatif { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
.whatif select { height: 28px; border: 1px solid #C8CEC7; border-radius: 5px; }
.chk { display: flex; gap: 6px; align-items: center; }
.ab { display: flex; flex-direction: column; gap: 3px; line-height: 1.6; }
.meas { display: inline-block; margin-right: 10px; }
.exp { background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 6px 12px; }
.exp p { margin: 3px 0; line-height: 1.7; }
.order { border: 1px dashed var(--accent); border-radius: 8px; padding: 8px 12px; display: flex; flex-direction: column; gap: 4px; }
.order pre { white-space: pre-wrap; margin: 0; font-family: inherit; }
.note { flex: 1; height: 28px; border: 1px solid #C8CEC7; border-radius: 5px; padding: 0 6px; }
.okline { color: var(--good, #1B5E20); }
.jobsel { height: 30px; min-width: 320px; }
.numin { width: 60px; height: 26px; }
.robot { border-top: 1px solid var(--line); padding-top: 8px; margin-top: 6px; }
.bar { display: inline-block; width: 90px; height: 8px; background: var(--surface-2); border-radius: 4px; overflow: hidden; vertical-align: middle; }
.bar i { display: block; height: 100%; background: var(--accent); }
.big-empty { padding: 140px 0; text-align: center; }
.console .line { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.small-btn { height: 28px; font-size: 12px; }
select { height: 26px; border: 1px solid #C8CEC7; border-radius: 5px; }
@media (max-width: 1100px) { .side { width: 100%; max-height: none; } .two { grid-template-columns: 1fr; } }
</style>
