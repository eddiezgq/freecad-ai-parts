<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('仿真与分析') }}</h1>
      <span class="muted">{{ $t('有限元强度校核、疲劳寿命、温度场与热应力：选零件 → 材料 → 加约束和载荷（或热边界）→ 服务器计算 → 看应力、变形、安全系数、寿命、温度') }}</span>
      <span class="labs small">{{ $t('实验 8：') }}<a href="/api/cae/lab8/guide.docx">{{ $t('指导书') }}</a> · <a href="/api/cae/lab8/report-template.docx">{{ $t('报告模板') }}</a> · {{ $t('实验 11：') }}<a href="/api/cae/lab11/guide.docx">{{ $t('指导书') }}</a> · <a href="/api/cae/lab11/report-template.docx">{{ $t('报告模板') }}</a></span></div><!-- i18n-ok 只剩标点 -->

    <div class="row">
      <!-- 左：设置 -->
      <section class="card side">
        <div class="step"><b>1</b> {{ $t('零件') }}</div>
        <div class="line">
          <select v-model="partSel" class="grow-in" :aria-label="$t('零件')">
            <option value="" disabled>{{ $t('选择零件…') }}</option>
            <option v-for="p in parts" :key="p.item" :value="p.item">{{ $td(p.item) }}{{ p.name ? ' · ' + bi(p.name) : '' }}</option>
            <option v-for="e in examples" :key="e.key" :value="'ex:' + e.key">{{ $t('示例 · {a}', { a: $td(e.label) }) }}</option>
          </select>
          <button class="btn" :disabled="!partSel || busy" @click="loadItem">{{ $t('读入') }}</button>
        </div>
        <label class="small upload">{{ $t('或者上传 STEP（任何 CAD 导出）') }}
          <input type="file" accept=".step,.stp,.STEP,.STP" :disabled="busy" @change="upload"></label>
        <div v-if="mbdNote" class="small sugg">{{ mbdNote }}</div>
        <div v-if="exSel" class="exbox small">
          <div class="muted">{{ $t('示例参数（改了点“读入”重新生成）') }}</div>
          <div class="grid2"><label v-for="(n, k) in exSel.names" :key="k">{{ n }} <input v-model.number="exParams[k]" type="number" step="any"></label></div>
        </div>
        <div v-if="geo" class="small ok">{{ $t('{a} · {b} 个面 · 体积 {c} cm³', { a: $td(geo.name), b: geo.solid.faces, c: (geo.solid.volume_mm3 / 1000).toFixed(1) }) }}</div>

        <template v-if="geo">
          <div class="step"><b>2</b> {{ $t('材料') }}</div>
          <select v-model="matId" class="full" :aria-label="$t('材料')">
            <option v-for="m in materials" :key="m.id" :value="m.id">{{ $td(m.name) }}</option>
          </select>
          <div v-if="mat" class="small muted matline">
            <template v-if="analysis !== 'thermal'">E {{ (mat.E_mpa / 1000).toFixed(0) }} GPa · ν {{ $td(mat.nu) }} · {{ mat.yield_mpa ? $t('屈服 ') + mat.yield_mpa : $t('抗拉 ') + mat.ultimate_mpa }} MPa · σ₋₁ {{ $td(mat.sigma_1) }} MPa</template>
            <template v-if="analysis !== 'static'"><br>{{ $t('导热 {a} W/(m·K) · 比热 {b} J/(kg·K) · 线膨胀 {c}×10⁻⁶/K', { a: mat.k_w_mk, b: mat.c_j_kgk, c: mat.alpha_1e6 }) }}</template>
            <a href="#" @click.prevent="showSrc = !showSrc">{{ $t('出处') }}</a>
            <div v-if="showSrc" class="src-box">{{ $td(mat.note) }}<br><span v-for="s in mat.sources" :key="s">· {{ s }}<br></span></div>
          </div>

          <div class="step"><b>3</b> {{ $t('算什么') }}</div>
          <div class="seg">
            <button v-for="a in ANALYSES" :key="a.k" type="button" :class="{ on: analysis === a.k }" :title="a.hint" @click="analysis = a.k">{{ $td(a.label) }}</button>
          </div>
          <template v-if="analysis !== 'static'">
            <div class="step sub">{{ $t('热边界') }} <span class="muted small">{{ $t('点“+”再在模型上点面；对流可以勾“其余所有面”') }}</span></div>
            <div class="adds">
              <button v-for="(k, key) in TH_KINDS" :key="key" type="button" class="add" :style="{ '--c': k.color }" :title="k.hint" @click="addTh(key)">+ {{ $td(k.label) }}</button>
            </div>
            <div class="ai-box">
              <textarea v-model="thAiText" rows="2" maxlength="500" :placeholder="thAiHint"></textarea>
              <div class="line">
                <button class="btn" :disabled="thAiBusy || !thAiText.trim()" @click="thAiFill">{{ thAiBusy ? $t('AI 正在理解…') : $t('AI 填热边界') }}</button>
                <span class="small muted">{{ $t('AI 只填表，你确认后再点“开始计算”') }}</span>
              </div>
              <div v-if="thAiRes" class="small ai-notes">
                <div v-for="n in thAiRes.notes" :key="n">✓ {{ n }}</div>
                <div v-for="n in thAiRes.unmatched" :key="n" class="warnline">{{ $t('？没看懂或找不到面：“{a}”——请手动补上', { a: n }) }}</div>
                <div v-if="thAiRes.note" class="muted">{{ $td(thAiRes.note) }}</div>
                <div class="muted">{{ thAiRes.engine === 'rules' ? $t('（规则理解：能认发热 / 功率 W、对流 / 风扇 / 自然 / 水冷、散热系数 h、环境温度、固定温度、瞬态时长和初温、内壁 / 外表面 / 底面 / 接触面 / 其余所有面、面编号、材料）') : $t('（由 AI 模型理解）') }}</div>
              </div>
            </div>
            <button v-if="geo.example" type="button" class="btn ghost small-btn" @click="fillExample">{{ $t('填入示范题：{a}', { a: $td(geo.example.title) }) }}</button>
            <div v-for="(r, i) in thRows" :key="r.key" class="lrow" :class="{ active: active === 100 + i }" :style="{ '--c': TH_KINDS[r.kind].color }" @click="active = TH_KINDS[r.kind].nofaces || r.rest ? -1 : 100 + i">
              <div class="lhead"><i></i><b>{{ $td(TH_KINDS[r.kind].label) }}</b>
                <span v-if="!TH_KINDS[r.kind].nofaces && !r.rest" class="small muted">{{ active === 100 + i ? $t('正在选面：在模型上点') : $t('点这里再选面') }}</span>
                <button type="button" class="x" :title="$t('删除')" @click.stop="thRows.splice(i, 1); active = -1">×</button></div>
              <div v-if="!TH_KINDS[r.kind].nofaces && !r.rest" class="chips">
                <span v-for="f in r.faces" :key="f" class="chip" :title="faceText(faceById[f])">{{ $t('面 {a}', { a: f }) }} <a href="#" @click.prevent.stop="toggleThFace(i, f)">×</a></span>
                <span v-if="!r.faces.length" class="small muted">{{ $t('（还没选面）') }}</span>
              </div>
              <div class="params small">
                <template v-if="r.kind === 'temperature'"><label>{{ $t('温度') }} <input v-model.number="r.value" type="number"></label><span>℃</span></template>
                <template v-if="r.kind === 'heat_flux' || r.kind === 'heat_body'"><label>{{ $t('功率') }} <input v-model.number="r.value" type="number"></label><span>W</span></template>
                <template v-if="r.kind === 'convection'">
                  <label class="wide">{{ $t('散热系数') }} <select v-model="r.film" @change="r.h = films.find((x) => x.id === r.film)?.h ?? r.h">
                    <option v-for="f in films" :key="f.id" :value="f.id" :title="f.src">{{ $t('{a}（{b}）', { a: $td(f.name), b: f.h }) }}</option><option value="">{{ $t('自己填') }}</option></select></label>
                  <label>h <input v-model.number="r.h" type="number" step="any"></label><span>W/(m²·K)</span>
                  <label>{{ $t('环境') }} <input v-model.number="r.tinf" type="number"></label><span>℃</span>
                  <label class="chk"><input v-model="r.rest" type="checkbox"> {{ $t('其余所有面') }}</label>
                </template>
              </div>
            </div>
            <div v-if="analysis === 'thermal'" class="small line">
              <label class="chk"><input v-model="transient" type="checkbox"> {{ $t('瞬态（看温度随时间怎么变）') }}</label>
              <template v-if="transient"><label>{{ $t('时长') }} <input v-model.number="trDur" class="num" type="number"> s</label><label>{{ $t('初温') }} <input v-model.number="trT0" class="num" type="number"> ℃</label></template>
            </div>
            <label v-if="analysis === 'thermo_mech'" class="small">{{ $t('无应力参考温度') }} <input v-model.number="refT" class="num" type="number"> {{ $t('℃（装配时的温度）') }}</label>
          </template>

          <template v-if="analysis !== 'thermal'">
          <div class="step sub">{{ $t('约束与载荷') }} <span class="muted small">{{ analysis === 'thermo_mech' ? $t('至少一个固定或支承面；机械载荷可以不加（只看热应力）') : $t('一句话让 AI 填，或者点“+”再在模型上点面') }}</span></div>
          <div class="ai-box">
            <textarea v-model="aiText" rows="2" maxlength="500" :placeholder="aiHint"></textarea>
            <div class="line">
              <button class="btn" :disabled="aiBusy || !aiText.trim()" @click="aiFill">{{ aiBusy ? $t('AI 正在理解…') : $t('AI 填表') }}</button>
              <span class="small muted">{{ $t('AI 只填表，你确认后再点“开始计算”') }}</span>
            </div>
            <div v-if="aiRes" class="small ai-notes">
              <div v-for="n in aiRes.notes" :key="n">✓ {{ n }}</div>
              <div v-for="n in aiRes.unmatched" :key="n" class="warnline">{{ $t('？没看懂或找不到面：“{a}”——请手动补上', { a: n }) }}</div>
              <div v-if="aiRes.note" class="muted">{{ $td(aiRes.note) }}</div>
              <div class="muted">{{ aiRes.engine === 'rules' ? $t('（规则理解：能认端面、轴肩、外圆 / 孔 Øxx、键槽侧面 / 底面、面编号、方向和材料）') : $t('（由 AI 模型理解）') }}</div>
            </div>
          </div>
          <div class="adds">
            <button v-for="(k, key) in KINDS" :key="key" type="button" class="add" :style="{ '--c': k.color }" :title="k.hint" @click="addRow(key)">+ {{ $td(k.label) }}</button>
          </div>
          <button v-if="geo.item === 'SH-301'" type="button" class="btn ghost small-btn" @click="example">{{ $t('填入示范题：SH-301 受 350 N·m 扭矩') }}</button>
          <div v-if="!rows.length" class="empty">{{ $t('还没有约束和载荷。') }}</div>
          <div v-for="(r, i) in rows" :key="r.key" class="lrow" :class="{ active: active === i }" :style="{ '--c': KINDS[r.kind].color }" @click="active = i">
            <div class="lhead"><i></i><b>{{ $td(KINDS[r.kind].label) }}</b>
              <span class="small muted">{{ active === i ? $t('正在选面：在模型上点') : $t('点这里再选面') }}</span>
              <button type="button" class="x" :title="$t('删除')" @click.stop="rows.splice(i, 1); active = Math.min(active, rows.length - 1)">×</button></div>
            <div class="chips">
              <span v-for="f in r.faces" :key="f" class="chip" :title="faceText(faceById[f])">{{ $t('面 {a}', { a: f }) }} <a href="#" @click.prevent.stop="toggleFace(i, f)">×</a></span>
              <span v-if="!r.faces.length" class="small muted">{{ $t('（还没选面）') }}</span>
            </div>
            <div class="params small">
              <template v-if="r.kind === 'force'">
                <label>Fx <input v-model.number="r.fx" type="number"></label><label>Fy <input v-model.number="r.fy" type="number"></label><label>Fz <input v-model.number="r.fz" type="number"></label><span>N</span>
              </template>
              <template v-if="r.kind === 'moment'">
                <label>Mx <input v-model.number="r.mx" type="number"></label><label>My <input v-model.number="r.my" type="number"></label><label>Mz <input v-model.number="r.mz" type="number"></label><span>N·m</span>
              </template>
              <template v-if="r.kind === 'pressure'"><label>{{ $t('压力') }} <input v-model.number="r.value" type="number" step="0.1"></label><span>MPa</span></template>
              <template v-if="r.kind === 'torque'"><label>{{ $t('扭矩') }} <input v-model.number="r.value" type="number"></label><span>N·m</span></template>
              <template v-if="['torque', 'bearing', 'coupling'].includes(r.kind)">
                <label class="wide">{{ $t('绕') }}
                  <select v-model="r.axis"><option v-for="a in axes" :key="a.key" :value="a.key">{{ $td(a.label) }}</option></select></label>
              </template>
              <label v-if="r.kind === 'bearing'" class="chk"><input v-model="r.thrust" type="checkbox"> {{ $t('止推（也限制轴向）') }}</label>
              <label v-if="r.kind === 'bearing'" class="chk" :title="$t('单列深沟球轴承允许轴在轴承里转一点角度，接近铰支；整个轴承位都限径向相当于把轴夹住，刚度、固有频率偏高')"><input v-model="r.ring" type="checkbox"> {{ $t('只限中间一圈（铰支）') }}</label>
            </div>
            <div v-if="rowErr(r)" class="small err">{{ rowErr(r) }}</div>
          </div>

          </template>

          <div class="step"><b>4</b> {{ $t('网格') }}</div>
          <div class="seg">
            <button v-for="m in MESH" :key="m.k" type="button" :class="{ on: meshK === m.k && !meshOverride }" @click="meshK = m.k; meshOverride = null">{{ $td(m.label) }}</button>
          </div>
          <label class="small">{{ $t('或指定单元尺寸') }} <input type="number" min="0.5" step="0.5" class="num-in" :value="meshOverride || ''" placeholder="mm" @change="meshOverride = +$event.target.value > 0 ? +$event.target.value : null"> mm</label>
          <div class="small muted">{{ $t('单元尺寸约 {a} mm{b}，载荷面附近自动加密。网格越细越准、越慢；教学版上限约 20 万个单元、5 分钟。', { a: meshSize.toFixed(1), b: meshOverride ? $t('（指定值）') : '' }) }}</div>

          <label class="small">{{ $t('这次计算的名称') }} <input v-model.trim="title" class="full" maxlength="80" :placeholder="$t('例如：SH-301 额定扭矩校核')"></label>
          <button class="btn primary big-w" :disabled="!ready || submitting" @click="submit">{{ submitting ? $t('正在提交…') : $t('开始计算') }}</button>
          <div v-if="!ready && rows.length" class="small muted">{{ notReady }}</div>
        </template>
        <div v-if="err" class="err small">{{ err }}</div>
      </section>

      <!-- 右：模型与结果 -->
      <section class="card grow">
        <div class="card-head">
          <h2>{{ result ? $t('计算结果') : $t('模型') }}{{ job ? ' · ' + (job.title || job.item || '') : '' }}</h2>
          <template v-if="result">
            <div class="seg">
              <button v-if="isThermal" type="button" :class="{ on: field === 'temp' }" @click="field = 'temp'">{{ $t('温度') }}</button>
              <template v-if="jobAnalysis !== 'thermal'">
              <button type="button" :class="{ on: field === 'vm' }" @click="field = 'vm'">{{ $t('Von Mises 应力') }}</button>
              <button type="button" :class="{ on: field === 'u' }" @click="field = 'u'">{{ isThermal ? $t('热变形') : $t('位移') }}</button>
              <button v-if="!isThermal" type="button" :class="{ on: field === 'life' }" :disabled="!result.surface.lgD" :title="$t('先在下面算疲劳寿命')" @click="field = 'life'">{{ $t('疲劳寿命') }}</button>
              </template>
            </div>
            <label v-if="jobAnalysis !== 'thermal'" class="small deform">{{ $t('变形放大') }} <input v-model.number="deformK" type="range" min="0" max="1" step="0.01"> {{ deformX.toFixed(0) }}×</label>
            <button type="button" class="btn more" :disabled="reporting" @click="downloadReport">{{ reporting ? $t('正在生成报告…') : $t('下载计算报告（Word）') }}</button>
            <button type="button" class="btn ghost" @click="backToSetup">{{ $t('回到设置') }}</button>
          </template>
        </div>
        <div v-if="job && job.status !== 'done'" class="jobbar" :class="job.status">
          <template v-if="job.status === 'queued'">{{ $t('排队中{a}…', { a: job.position ? $t('：前面还有 ') + (job.position - 1) + $t(' 个任务') : '' }) }}</template>
          <template v-else-if="job.status === 'running'">{{ $t('正在划分网格、求解…（已 {a} 秒）', { a: elapsed }) }}<div class="spin"></div></template>
          <template v-else-if="job.status === 'failed'">{{ $t('没算成：{a}', { a: job.error }) }}</template>
        </div>
        <div v-if="!geo && !result" class="empty big-empty">{{ $t('先在左边选一个零件（例如 SH-301 输出轴）或上传 STEP。') }}</div>
        <CaeViewer v-else ref="viewer" :glb-url="result ? '' : geo?.model_url" :faces="geo?.faces || []" :face-colors="faceColors"
          :picking="!result && active >= 0" :surface="result?.surface" :field="field" :deform="deformX" :marks="marks" :peaks="{ vm: st.vm_peak_all_mpa, u: st.u_max_mm, temp: st.t_max_c }" :block-seconds="fat?.block_seconds || 1" @pick="onPick" />

        <div v-if="result && isThermal" class="stats">
          <div class="stat" :class="tTone"><span>{{ $t('最高温度') }}</span><b>{{ st.t_max_c.toFixed(1) }} <small>℃</small></b>
            <small class="muted">{{ $t('{a} mm · 红点', { a: st.t_max_at.map((x) => x.toFixed(0)).join(', ') }) }}</small></div>
          <div class="stat"><span>{{ $t('最低 / 表面平均') }}</span><b>{{ st.t_min_c.toFixed(1) }} / {{ st.t_surface_mean_c.toFixed(1) }} <small>℃</small></b></div>
          <div class="stat"><span>{{ $t('热平衡（进 / 散走）') }}</span><b>{{ st.heat_in_w.toFixed(0) }} / {{ st.heat_out_convection_w.toFixed(0) }} <small>W</small></b>
            <small class="muted">{{ job?.setup?.transient ? $t('瞬态：散走的是最后时刻') : $t('稳态时两者相等') }}</small></div>
          <div v-if="jobAnalysis === 'thermo_mech'" class="stat" :class="sfTone"><span>{{ $t('热应力 / 安全系数') }}</span><b>{{ st.vm_max_mpa.toFixed(0) }} <small>MPa</small> / {{ st.safety_factor?.toFixed(2) ?? '—' }}</b>
            <small class="muted">{{ $t('最大热变形 {a} mm', { a: st.u_max_mm.toPrecision(3) }) }}</small></div>
          <div v-else class="stat"><span>{{ $t('网格') }}</span><b>{{ (st.elements / 1000).toFixed(1) }}k <small>{{ $t('单元') }}</small></b><small class="muted">{{ $t('{a} mm · {b} 秒', { a: st.mesh_size_mm, b: st.seconds }) }}</small></div>
        </div>
        <div v-if="result && isThermal && (st.film_groups || []).length" class="small muted notes">
          <p v-for="g in st.film_groups" :key="g.load">{{ $t('对流散热（第 {a} 行）：面积 {b} m²，平均 {c} ℃，散走 {d} W', { a: g.load + 1, b: g.area_m2.toFixed(4), c: g.mean_c.toFixed(1), d: g.heat_w.toFixed(1) }) }}</p>
        </div>
        <div v-if="result && job?.setup?.formula" class="formula small">
          <b>{{ $t('和教材公式比') }}</b> {{ $td(job.setup.formula.name) }}
          <div v-if="job.setup.formula.t_oil_c != null">{{ $t('发热 P(1−η) = {a} W（输入 {b} kW，η = {c}），K_s = {d}，A = {e} m² →公式油温', { a: job.setup.formula.loss_w, b: job.setup.formula.P_in_kw, c: job.setup.formula.eta, d: job.setup.formula.K_s, e: job.setup.formula.A_m2 }) }} <b>{{ $td(job.setup.formula.t_oil_c) }} ℃</b>{{ $t('；有限元外表面平均') }} <b>{{ (st.film_groups?.[0]?.mean_c ?? st.t_surface_mean_c).toFixed(1) }} ℃</b>{{ $t('、最高 {a} ℃（限值约 {b} ℃）。', { a: st.t_max_c.toFixed(1), b: job.setup.formula.limit_c }) }}</div>
          <div v-else-if="job.setup.formula.sigma_mpa != null">{{ $t('梁理论：根部弯矩 {a} N·m、扭矩 {b} N·m →根部外表面 Von Mises 约', { a: job.setup.formula.M_root_nm, b: job.setup.formula.T_nm }) }} <b>{{ $td(job.setup.formula.vm_mpa) }} MPa</b>{{ $t('（屈服 {a} MPa，安全系数约 {b}），端部下沉', { a: job.setup.formula.yield_mpa, b: job.setup.formula.sf }) }} <b>{{ $td(job.setup.formula.delta_mm) }} mm</b>{{ $t('，这根管一端固定时的一阶固有频率约') }} <b>{{ $td(job.setup.formula.f1_tip_hz) }} Hz</b>{{ $t('（不计法兰质量 {a} Hz）。有限元：最大 Von Mises', { a: job.setup.formula.f1_hz }) }} <b>{{ st.vm_max_mpa.toFixed(2) }} MPa</b>{{ $t('（多在法兰与管的内角，是应力集中），最大位移') }} <b>{{ st.u_max_mm.toPrecision(3) }} mm</b>{{ $t('；固有频率点下面的“计算固有频率”。') }}</div>
          <div v-else-if="job.setup.formula.dt_air_c != null">{{ $t('发热 {a} W，风口 {b} m²，估算通风量 {c} m³/s →出风温升约', { a: job.setup.formula.loss_w, b: job.setup.formula.A_vent_m2, c: job.setup.formula.Q_m3s }) }} <b>{{ $td(job.setup.formula.dt_air_c) }} ℃</b>{{ $t('；有限元最高') }} <b>{{ st.t_max_c.toFixed(1) }} ℃</b>{{ $t('（元件限值约 {a} ℃）。', { a: job.setup.formula.limit_c }) }}</div>
          <div v-else>{{ $t('粗估 {a} ℃；有限元最高', { a: job.setup.formula.t_est_c }) }} <b>{{ st.t_max_c.toFixed(1) }} ℃</b>{{ $t('（限值约 {a} ℃）。', { a: job.setup.formula.limit_c }) }}</div>
          <div class="muted">{{ $td(job.setup.formula.note) }}</div>
        </div>
        <svg v-if="result && st.series" class="tchart" viewBox="0 0 600 160" :aria-label="$t('温度—时间曲线')">
          <polyline :points="seriesPts(1)" fill="none" stroke="#C0392B" stroke-width="1.5" />
          <polyline :points="seriesPts(2)" fill="none" stroke="#2E86C1" stroke-width="1.5" />
          <text x="6" y="14" font-size="11">{{ $t('最高（红）、平均（蓝）温度随时间：{a} → {b} ℃，{c} 秒', { a: st.series[0][2].toFixed(0), b: st.series[st.series.length - 1][2].toFixed(1), c: st.series[st.series.length - 1][0] }) }}</text>
        </svg>

        <div v-if="result && !isThermal" class="stats">
          <div class="stat"><span>{{ $t('最大应力（Von Mises）') }}</span><b>{{ st.vm_max_mpa.toFixed(1) }} <small>MPa</small></b>
            <small class="muted">{{ $t('面 {a} · 粉色点', { a: (st.vm_max_faces || []).join('、') || '—' }) }}</small></div><!-- i18n-ok 只剩标点 -->
          <div class="stat" :class="sfTone"><span>{{ $t('安全系数') }}</span><b>{{ st.safety_factor?.toFixed(2) ?? '—' }}</b>
            <small>{{ st.strength_mpa ? strengthKind + ' ' + st.strength_mpa + $t(' MPa ÷ 最大应力') : '' }}</small></div>
          <div class="stat"><span>{{ $t('最大位移') }}</span><b>{{ st.u_max_mm.toPrecision(3) }} <small>mm</small></b><small class="muted">{{ $t('青色点') }}</small></div>
          <div class="stat"><span>{{ $t('网格') }}</span><b>{{ (st.elements / 1000).toFixed(1) }}k <small>{{ $t('单元') }}</small></b>
            <small class="muted">{{ $t('{a} 节点 · {b} mm · {c} 秒', { a: st.nodes, b: st.mesh_size_mm, c: st.seconds }) }}</small></div>
        </div>
        <div v-if="result && !isThermal" class="small muted notes">
          <p v-if="st.vm_peak_all_mpa > st.vm_max_mpa * 1.01">{{ $t('约束面附近最高 {a} MPa：那是约束方式造成的（实际的支承没有那么“死”），评估时避开了约束面 {b} mm 以内的点。', { a: st.vm_peak_all_mpa.toFixed(1), b: (1.5 * st.mesh_size_mm).toFixed(1) }) }}</p>
          <p>{{ $t('尖角（没有圆角的内角）处的应力理论上没有上限，网格越细数值越大——看到最大值在尖角，就要考虑加圆角，或者按规范的应力集中系数去校核。') }}</p>
        </div>

        <div v-if="result && !isThermal" class="fat">
          <h3>{{ $t('固有频率') }} <span class="small muted">{{ $t('用同样的零件、材料、网格和支承求前几阶固有频率——高速轴看临界转速，工作转速（及其 2 倍）要离开它们') }}</span></h3>
          <div class="line">
            <button class="btn" :disabled="modBusy" @click="runModal">{{ modBusy ? $t('正在计算…') : (job?.modal ? $t('重新计算') : $t('计算固有频率')) }}</button>
            <label class="small">{{ $t('工作转速') }} <input v-model.number="workRpm" type="number" min="0" step="100" class="num-in"> r/min</label>
          </div>
          <div v-if="modErr" class="err small">{{ modErr }}</div>
          <table v-if="job?.modal" class="t small">
            <thead><tr><th>{{ $t('阶次') }}</th><th class="num">{{ $t('频率 Hz') }}</th><th class="num">{{ $t('相当转速 r/min') }}</th><th class="num">{{ $t('与工作转速之比') }}</th></tr></thead>
            <tbody><tr v-for="m in job.modal.freqs" :key="m.mode"><td>{{ $td(m.mode) }}</td><td class="num">{{ m.hz.toFixed(1) }}</td>
              <td class="num">{{ m.rpm.toFixed(0) }}</td><td class="num">{{ workRpm ? (m.rpm / workRpm).toFixed(2) : '—' }}</td></tr></tbody>
          </table>
          <p v-if="job?.modal" class="small muted">{{ $t('只算了零件本身（齿轮、曲柄等装在轴上的零件的质量没计入，计入后频率会降低）；去掉了 {a} 个刚体运动（绕轴转、沿轴移）。弯曲振型成对出现（两个方向）。', { a: job.modal.rigid_modes }) }}</p>
        </div>

        <div v-if="result" class="ai-exp">
          <div class="line"><h3>{{ $t('AI 解释与建议') }}</h3>
            <button class="btn" :disabled="expBusy" @click="explain">{{ expBusy ? $t('AI 正在分析…') : (exp ? $t('重新分析') : $t('请 AI 解释结果')) }}</button></div>
          <div v-if="expErr" class="err small">{{ expErr }}</div>
          <div v-if="exp" class="exp-text">
            <p v-for="(l, i) in exp.text.split('\n')" :key="i">{{ l }}</p>
            <div class="line">
              <button v-for="a in exp.actions" :key="a.label" class="btn primary" :disabled="actBusy" @click="act(a)">{{ $td(a.label) }}</button>
            </div>
            <div class="small muted">{{ $t('{a}，仅供参考；解释会写进计算报告。', { a: exp.engine === 'rules' ? $t('规则分析') : exp.engine === 'saved' ? $t('上次的分析') : $t('AI 模型分析') }) }}</div>
          </div>
        </div>

        <div v-if="result && !isThermal" class="fat">
          <h3>{{ $t('疲劳寿命') }} <span class="small muted">{{ $t('载荷反复变化时，零件能用多久（雨流计数 + S-N 曲线 + Miner 累积损伤，pyLife）') }}</span></h3>
          <div class="fat-grid">
            <div class="field">
              <label>{{ $t('载荷谱') }}</label>
              <div class="seg">
                <button type="button" :class="{ on: spec.kind === 'const' }" @click="spec.kind = 'const'">{{ $t('恒幅') }}</button>
                <button type="button" :class="{ on: spec.kind === 'log' }" :disabled="!hasTorque" :title="hasTorque ? '' : $t('要有扭矩载荷才能用转矩记录')" @click="spec.kind = 'log'">{{ $t('跑合试验台转矩记录') }}</button>
                <button v-if="job?.setup?.source" type="button" :class="{ on: spec.kind === 'mbd' }" @click="spec.kind = 'mbd'">{{ $t('动力学受力记录') }}</button>
                <button type="button" :class="{ on: spec.kind === 'joint' }" :disabled="!hasTorque" :title="hasTorque ? '' : $t('要有扭矩载荷才能用关节力矩记录')" @click="spec.kind = 'joint'">{{ $t('关节力矩记录') }}</button>
                <button type="button" :class="{ on: spec.kind === 'csv' }" @click="spec.kind = 'csv'">{{ $t('上传载荷记录') }}</button>
              </div>
            </div>
            <template v-if="spec.kind === 'const'">
              <div class="field"><label>{{ $t('最大（{a}）', { a: refUnit }) }}</label><input v-model.number="spec.max" type="number"></div>
              <div class="field"><label>{{ $t('最小（{a}）', { a: refUnit }) }}</label><input v-model.number="spec.min" type="number"></div>
              <div class="field"><label>{{ $t('每秒几次（Hz）') }}</label><input v-model.number="spec.freq" type="number" step="0.1" min="0.001"></div>
            </template>
            <template v-else-if="spec.kind === 'joint'">
              <div class="field wide">
                <label>{{ $t('“运动与动力分析”的计算（自己算完的）和关节——用这个关节的驱动力矩随时间的变化作载荷谱，按计算工况的扭矩线性缩放') }}</label>
                <select v-model="spec.mjob">
                  <option value="" disabled>{{ mjobs.length ? $t('选择计算…') : $t('还没有：先到“运动与动力分析”算一次机械臂的运动') }}</option>
                  <option v-for="m in mjobs" :key="m.id" :value="m.id">{{ m.title || m.id }} · {{ new Date(m.created * 1000).toLocaleString('zh-CN', { hour12: false }) }}</option>
                </select>
                <select v-model="spec.joint" :disabled="!spec.mjob">
                  <option value="" disabled>{{ $t('选择关节…') }}</option>
                  <option v-for="jn in mjoints" :key="jn" :value="jn">{{ $td(jn) }}</option>
                </select>
              </div>
            </template>
            <template v-else-if="spec.kind === 'csv'">
              <div class="field wide">
                <label>{{ $t('CSV 文件：每行一个数（多列时取最后一列），单位与计算工况相同（{a}）；整段当作一块，不断重复', { a: refUnit }) }}</label>
                <input type="file" accept=".csv,.txt" @change="readCsv">
                <span v-if="spec.values.length" class="small muted">{{ $t('读到 {a} 个点，最大 {b}', { a: spec.values.length, b: Math.max(...spec.values.map(Math.abs)).toPrecision(4) }) }}</span>
              </div>
              <div class="field"><label>{{ $t('这一段多少秒') }}</label><input v-model.number="spec.secs" type="number" step="0.1" min="0.001"></div>
            </template>
            <div v-else-if="spec.kind === 'mbd'" class="field wide small muted">{{ $t('用这根杆件在动力学计算中、沿所加力方向的受力随时间的变化作为载荷谱（整段运动当作一块，不断重复）。') }}</div>
            <div v-else class="field wide">
              <label>{{ $t('选一台减速器的记录（仿真车间跑合试验台，输出轴转矩）') }}</label>
              <select v-model="spec.log">
                <option value="" disabled>{{ logs.length ? $t('选择记录…') : $t('还没有记录：车间里有减速器做完跑合试验后才有') }}</option>
                <option v-for="l in logs" :key="l.id" :value="l.id">{{ $t('{a} · {b} · 峰值 {c} N·m · {d} 秒', { a: l.part_serial, b: new Date(l.ts).toLocaleString('zh-CN', { hour12: false }), c: l.peak_nm.toFixed(0), d: l.duration_s }) }}</option>
              </select>
              <svg v-if="logSeries.length" class="spark" viewBox="0 0 300 60" preserveAspectRatio="none" :aria-label="$t('转矩曲线')">
                <polyline :points="sparkPts" fill="none" stroke="var(--accent)" stroke-width="1" />
              </svg>
            </div>
            <div class="field"><label>{{ $t('表面状态') }}</label>
              <select v-model="fopt.surface"><option v-for="(v, k) in SURF" :key="k" :value="k">{{ $td(v) }}</option></select></div>
            <div class="field"><label>{{ $t('尺寸系数 ε') }} <span class="muted">{{ $t('直径 30–50 mm 约 0.85，越粗越小') }}</span></label><input v-model.number="fopt.size_factor" type="number" step="0.01" min="0.5" max="1"></div>
            <div class="field"><label>{{ $t('附加缺口系数 Kf') }} <span class="muted">{{ $t('有限元已算形状集中，一般 1') }}</span></label><input v-model.number="fopt.kf" type="number" step="0.1" min="1"></div>
            <label class="chk small"><input v-model="fopt.haibach" type="checkbox"> {{ $t('疲劳极限以下也计损伤（Haibach，偏安全）') }}</label>
          </div>
          <button class="btn primary" :disabled="fatBusy || (spec.kind === 'log' && !spec.log) || (spec.kind === 'joint' && !spec.joint) || (spec.kind === 'csv' && spec.values.length < 2)" @click="runFatigue">{{ fatBusy ? $t('正在计算…') : $t('计算疲劳寿命') }}</button>
          <div v-if="fatErr" class="err small">{{ fatErr }}</div>
          <div v-if="fat" class="fat-res">
            <div class="stat" :class="fat.infinite ? 'good' : fat.life_hours < 2000 ? 'bad' : fat.life_hours < 20000 ? 'warn' : 'good'">
              <span>{{ $t('寿命（最危险点）') }}</span>
              <b>{{ fat.infinite ? $t('无限') : fmtHours(fat.life_hours) }}</b>
              <small>{{ fat.infinite ? $t('应力幅都低于修正后的疲劳极限') : '≈ ' + (fat.life_blocks * fat.cycles_per_block).toPrecision(3) + $t(' 次循环') }}</small>
            </div>
            <div class="small fat-txt">
              <div>{{ $t('{a}；每块 {b} 个循环。', { a: $td(fat.label), b: fat.cycles_per_block }) }}</div>
              <div>{{ $t('修正后疲劳极限 S_D = σ₋₁ × β {a} × ε {b} ÷ Kf {c} =', { a: fat.beta, b: fat.size_factor, c: fat.kf }) }} <b>{{ $td(fat.S_D) }} MPa</b>{{ $t('（N_D = {a}，k = {b}）；Goodman 平均应力修正。', { a: fat.N_D.toExponential(0), b: fat.k }) }}</div>
              <table v-if="fat.hot_cycles?.length" class="t">
                <thead><tr><th class="num">{{ $t('载荷幅') }}</th><th class="num">{{ $t('均值') }}</th><th class="num">σa</th><th class="num">σm</th><th class="num">σa,eq MPa</th><th class="num">{{ $t('该幅值寿命 N') }}</th></tr></thead>
                <tbody><tr v-for="(c, i) in fat.hot_cycles" :key="i">
                  <td class="num">{{ c.load_amp.toFixed(1) }}</td><td class="num">{{ c.load_mean.toFixed(1) }}</td><td class="num">{{ c.sigma_a.toFixed(1) }}</td>
                  <td class="num">{{ c.sigma_m.toFixed(1) }}</td><td class="num">{{ c.sigma_a_eq.toFixed(1) }}</td><td class="num">{{ c.N == null ? '∞' : c.N.toPrecision(3) }}</td></tr></tbody>
              </table>
              <div class="muted">{{ $t('按最危险点列出幅值最大的几个循环。云图切到“疲劳寿命”看各处寿命；报告里会带上这一节。') }}</div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <section class="card">
      <div class="card-head"><h2>{{ teacher ? $t('本厂的计算记录') : $t('我的计算记录') }}</h2><span class="small muted">{{ $t('点一条看结果') }}</span></div>
      <div v-if="!jobs.length" class="empty">{{ $t('还没有计算记录。') }}</div>
      <table v-else class="t">
        <thead><tr><th>{{ $t('名称') }}</th><th>{{ $t('零件') }}</th><th v-if="teacher">{{ $t('提交人') }}</th><th>{{ $t('时间') }}</th><th>{{ $t('状态') }}</th><th class="num">{{ $t('最大应力 MPa / 温度') }}</th><th class="num">{{ $t('安全系数') }}</th><th></th></tr></thead>
        <tbody><tr v-for="j in jobs" :key="j.id" :class="{ cur: job?.id === j.id }">
          <td>{{ j.title || '—' }}</td><td class="mono">{{ j.item || $t('上传的零件') }}</td><td v-if="teacher">{{ $td(j.owner_name) }}</td>
          <td class="small">{{ new Date(j.created * 1000).toLocaleString('zh-CN', { hour12: false }) }}</td>
          <td><span class="pill" :class="TONE[j.status]">{{ $td(STATUS[j.status]) }}</span></td>
          <td class="num">{{ j.stats?.t_max_c != null ? $t('最高 ') + j.stats.t_max_c.toFixed(1) + ' ℃' : j.stats ? j.stats.vm_max_mpa.toFixed(1) : '' }}</td>
          <td class="num">{{ j.stats?.safety_factor?.toFixed(2) ?? '' }}</td>
          <td><a v-if="j.status === 'done'" href="#" @click.prevent="openJob(j)">{{ $t('看结果 →') }}</a>
            <span v-else-if="j.status === 'failed'" class="small err" :title="j.error">{{ $t('原因') }}</span></td>
        </tr></tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { bi, t as $t } from '../lib/i18n';
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { get, post, session, ApiError } from '../lib/api';
import { KINDS, TH_KINDS, toLoad, toThermal, axesOf, faceText, fetchSurface } from '../lib/cae';
import CaeViewer from '../components/CaeViewer.vue';

const router = useRouter();
const route = useRoute();
const mbdSource = ref(null);              // 从运动与动力分析送来的杆件（第 12 轮）
const mbdNote = ref('');
const STATUS = { queued: $t('排队'), running: $t('计算中'), done: $t('完成'), failed: $t('失败') };
const TONE = { queued: 'mute', running: 'info', done: 'good', failed: 'bad' };
const ANALYSES = [{ k: 'static', label: $t('强度'), hint: $t('线弹性静力：应力、变形、安全系数、疲劳') },
  { k: 'thermal', label: $t('温度'), hint: $t('温度场：发热、散热、稳态或瞬态') },
  { k: 'thermo_mech', label: $t('温度 + 热应力'), hint: $t('先算温度，再算热膨胀产生的应力和变形') }];
const MESH = [{ k: 'coarse', label: $t('粗（快）'), div: 20 }, { k: 'mid', label: $t('中'), div: 32 }, { k: 'fine', label: $t('细（慢）'), div: 48 }];

const teacher = computed(() => !!session.user?.teacher);
const parts = ref([]);
const materials = ref([]);
const partSel = ref('SH-301');
const examples = ref([]), films = ref([]);
const exParams = ref({});
const exSel = computed(() => (partSel.value.startsWith('ex:') ? examples.value.find((e) => 'ex:' + e.key === partSel.value) : null));
watch(exSel, (e) => { if (e) exParams.value = { ...e.params }; });
const analysis = ref('static');
const thRows = ref([]);
const transient = ref(false), trDur = ref(600), trT0 = ref(20), refT = ref(20);
const meshOverride = ref(null);
const geo = ref(null);
const matId = ref('45-QT');
const showSrc = ref(false);
const rows = ref([]);
const active = ref(-1);
const meshK = ref('mid');
const title = ref('');
const busy = ref(false);
const submitting = ref(false);
const err = ref('');
const job = ref(null);
const jobs = ref([]);
const result = ref(null);
const field = ref('vm');
const deformK = ref(0.3);
const elapsed = ref(0);
const viewer = ref(null);
let keyN = 0, pollT = null, listT = null;

const mat = computed(() => materials.value.find((m) => m.id === matId.value));
const faceById = computed(() => Object.fromEntries((geo.value?.faces || []).map((f) => [f.id, f])));
const axes = computed(() => axesOf(geo.value?.faces || []));
const diag = computed(() => { const b = geo.value?.solid.bbox_mm; return b ? Math.hypot(b[3] - b[0], b[4] - b[1], b[5] - b[2]) : 100; });
const meshSize = computed(() => meshOverride.value || diag.value / MESH.find((m) => m.k === meshK.value).div);
watch(meshK, () => { meshOverride.value = null; });
const jobAnalysis = computed(() => job.value?.setup?.analysis || 'static');
const isThermal = computed(() => jobAnalysis.value !== 'static');
const tTone = computed(() => { const t = st.value.t_max_c, lim = job.value?.setup?.formula?.limit_c; return lim == null || t == null ? '' : t > lim ? 'bad' : t > lim - 10 ? 'warn' : 'good'; });
function seriesPts(k) {
  const s = st.value.series || []; if (!s.length) return '';
  const t1 = s[s.length - 1][0] || 1;
  let lo = Infinity, hi = -Infinity;
  for (const r of s) { lo = Math.min(lo, r[1], r[2]); hi = Math.max(hi, r[1], r[2]); }
  if (hi <= lo) hi = lo + 1;
  return s.map((r) => `${(10 + r[0] / t1 * 580).toFixed(1)},${(150 - (r[k] - lo) / (hi - lo) * 125).toFixed(1)}`).join(' ');
}
const faceColors = computed(() => {
  const out = {};
  if (analysis.value !== 'thermal') rows.value.forEach((r) => r.faces.forEach((f) => { out[f] = KINDS[r.kind].color; }));
  if (analysis.value !== 'static') thRows.value.forEach((r) => (r.rest ? [] : r.faces).forEach((f) => { out[f] = TH_KINDS[r.kind].color; }));
  return out;
});
const st = computed(() => result.value?.stats || {});
const strengthKind = computed(() => (materials.value.find((m) => m.id === job.value?.setup?.material_id)?.yield_mpa ? $t('屈服强度') : $t('抗拉强度')));
const sfTone = computed(() => { const s = st.value.safety_factor; return s == null ? '' : s < 1 ? 'bad' : s < 1.5 ? 'warn' : 'good'; });
const deformX = computed(() => {                    // 滑块 0–1 → 让最大位移看起来约为外形的 0–10%
  const um = st.value.u_max_mm || 0;
  return um > 0 ? Math.round((deformK.value * 0.1 * diag.value) / um) : 0;
});
const marks = computed(() => (!result.value ? [] : st.value.t_max_at ? [{ at: st.value.t_max_at, color: 0xff2020 }]
  .concat(st.value.vm_max_at ? [{ at: st.value.vm_max_at, color: 0xff2bd6 }] : []) : [
  { at: st.value.vm_max_at, color: 0xff2bd6 }, { at: st.value.u_max_at, color: 0x00d0ff }]));

function rowErr(r) {
  if (!r.faces.length) return '';
  if (KINDS[r.kind].cyl && r.faces.some((f) => faceById.value[f]?.kind !== 'cylinder')) return $t('轴承支承、限制转动只能选圆柱面');
  if (['torque', 'bearing', 'coupling'].includes(r.kind) && !axes.value.length) return $t('这个零件没有圆柱面，找不到轴线');
  if (r.kind === 'force' && !(+r.fx || +r.fy || +r.fz)) return $t('力的大小是 0');
  if (r.kind === 'moment' && !(+r.mx || +r.my || +r.mz)) return $t('力矩的大小是 0');
  if (['pressure', 'torque'].includes(r.kind) && !+r.value) return $t('大小是 0');
  return '';
}
const notReady = computed(() => {
  if (analysis.value !== 'static') {
    if (!thRows.value.some((r) => (r.kind === 'temperature' || r.kind === 'convection') && (r.rest || r.faces.length))) return $t('还缺散热条件：至少一个固定温度或对流散热的面，否则热量散不出去');
    if (thRows.value.some((r) => !TH_KINDS[r.kind].nofaces && !r.rest && !r.faces.length)) return $t('有一行热边界还没选面');
    if (analysis.value === 'thermal') return '';
    if (!rows.value.some((r) => KINDS[r.kind].support && r.faces.length)) return $t('热应力还缺约束：至少一个固定或支承面');
    if (rows.value.some((r) => !r.faces.length) || rows.value.some(rowErr)) return $t('约束与载荷有一行没设好');
    return '';
  }
  if (!rows.value.some((r) => KINDS[r.kind].support && r.faces.length)) return $t('还缺约束：至少一个固定或支承面，否则零件会整体移动');
  if (!rows.value.some((r) => !KINDS[r.kind].support && r.faces.length)) return $t('还缺载荷');
  if (rows.value.some((r) => !r.faces.length)) return $t('有一行还没选面（选面或删掉这一行）');
  if (rows.value.some(rowErr)) return $t('有一行设置不对，看红字');
  return '';
});
const ready = computed(() => geo.value && mat.value && (analysis.value !== 'static' ? thRows.value.length : rows.value.length) && !notReady.value);

function addRow(kind) {
  const r = { key: ++keyN, kind, faces: [], fx: 0, fy: 0, fz: 0, mx: 0, my: 0, mz: 0, value: 0, axis: axes.value[0]?.key, thrust: false };
  if (kind === 'force') r.fy = -1000;
  if (kind === 'pressure') r.value = 1;
  if (kind === 'torque') r.value = 100;
  if (kind === 'moment') r.mx = 10;
  rows.value.push(r);
  active.value = rows.value.length - 1;
}
function toggleFace(i, f) {
  const r = rows.value[i];
  const k = r.faces.indexOf(f);
  if (k >= 0) { r.faces.splice(k, 1); return; }
  rows.value.forEach((o) => { const j = o.faces.indexOf(f); if (j >= 0) o.faces.splice(j, 1); });   // 一个面只放在一行里
  r.faces.push(f);
  if (KINDS[r.kind].cyl && faceById.value[f]?.kind === 'cylinder') {               // 圆柱支承：轴线就用这个面的
    const a = axes.value.find((x) => x.faces.includes(f));
    if (a) r.axis = a.key;
  }
}
function onPick(f) {
  if (active.value >= 100) toggleThFace(active.value - 100, f);
  else if (active.value >= 0) toggleFace(active.value, f);
}
let thKey = 0;
function addTh(kind) {
  const r = { key: ++thKey, kind, faces: [], value: kind === 'temperature' ? 80 : 100, film: 'air-vent', h: 17.45, tinf: 20, rest: false };
  thRows.value.push(r);
  active.value = TH_KINDS[kind].nofaces ? -1 : 100 + thRows.value.length - 1;
}
function toggleThFace(i, f) {
  const r = thRows.value[i];
  const k = r.faces.indexOf(f);
  if (k >= 0) { r.faces.splice(k, 1); return; }
  thRows.value.forEach((o) => { const j = o.faces.indexOf(f); if (j >= 0) o.faces.splice(j, 1); });
  r.faces.push(f);
}
function fillExample() {
  const ex = geo.value.example;
  thRows.value = ex.thermal.map((l) => ({ key: ++thKey, kind: l.type, faces: Array.isArray(l.faces) ? [...l.faces] : [], rest: l.faces === 'rest',
    value: l.value_c ?? l.power_w ?? 0, h: l.h_w_m2k ?? 17.45, tinf: l.t_inf_c ?? 20,
    film: films.value.find((f) => Math.abs(f.h - (l.h_w_m2k ?? -1)) < 1e-6)?.id || '' }));
  matId.value = ex.material_id; title.value = ex.title; meshOverride.value = ex.mesh_mm; active.value = -1;
}

// 第 66 轮：强度示例零件（WQ-CR5 大臂）：预设的约束、力、力矩
function fillStaticExample() {
  const ex = geo.value.example;
  rows.value = ex.rows.map((x) => ({ key: ++keyN, fx: 0, fy: 0, fz: 0, mx: 0, my: 0, mz: 0, value: 0, thrust: false, axis: null, ...x, faces: [...x.faces] }));
  matId.value = ex.material_id; title.value = ex.title; meshOverride.value = ex.mesh_mm; active.value = -1;
}

// 示范题：两处轴承（Ø35）、输出端（Ø30，离键槽远的一端）限制转动、键槽一侧受 350 N·m
function example() {
  const F = geo.value.faces;
  const brg = F.filter((f) => f.radius_mm === 17.5).sort((a, b) => a.center[2] - b.center[2]);
  const out = F.filter((f) => f.radius_mm === 15).sort((a, b) => b.center[2] - a.center[2])[0];
  const wall = F.find((f) => f.kind === 'plane' && f.normal && Math.abs(Math.abs(f.normal[0]) - 1) < 1e-3);
  if (brg.length < 2 || !out || !wall) { err.value = $t('这个版本的 SH-301 和示范题的形状对不上，请手动设置'); return; }
  const ax = axes.value[0]?.key;
  rows.value = [
    { key: ++keyN, kind: 'bearing', faces: [brg[0].id], axis: ax, thrust: true },
    { key: ++keyN, kind: 'bearing', faces: [brg[1].id], axis: ax, thrust: false },
    { key: ++keyN, kind: 'coupling', faces: [out.id], axis: ax },
    { key: ++keyN, kind: 'torque', faces: [wall.id], axis: ax, value: 350 },
  ];
  active.value = -1;
  matId.value = '45-QT';
  title.value = $t('SH-301 额定扭矩 350 N·m 校核');
}

async function loadItem() {
  if (exSel.value) {
    await withBusy(() => post('/cae/geometry/example/' + exSel.value.key, { params: exParams.value }));
    if (geo.value?.example) {
      if (geo.value.example.analysis === 'static') { analysis.value = 'static'; fillStaticExample(); } else { analysis.value = 'thermal'; fillExample(); }
    }
    return;
  }
  await withBusy(() => post('/cae/geometry/item/' + encodeURIComponent(partSel.value)));
}
async function upload(ev) {
  const f = ev.target.files[0];
  if (!f) return;
  const fd = new FormData(); fd.append('step', f);
  await withBusy(async () => {
    const r = await fetch('/api/cae/geometry/upload', { method: 'POST', headers: { 'x-wq-token': session.token }, body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new ApiError(r.status, d.detail || $t('读不了这个文件'));
    return d;
  });
  ev.target.value = '';
}
async function withBusy(fn) {
  busy.value = true; err.value = '';
  try {
    geo.value = await fn();
    rows.value = []; thRows.value = []; active.value = -1; result.value = null; job.value = null; title.value = ''; meshOverride.value = null;
  } catch (e) { err.value = e.message; } finally { busy.value = false; }
}

async function submit() {
  submitting.value = true; err.value = '';
  try {
    const setup = { material_id: matId.value, mesh: { size_mm: +meshSize.value.toFixed(2) },
      loads: analysis.value === 'thermal' ? [] : rows.value.map((r) => toLoad(r, axes.value)) };
    if (analysis.value !== 'static') {
      setup.analysis = analysis.value;
      setup.thermal = thRows.value.map(toThermal);
      if (analysis.value === 'thermal' && transient.value) setup.transient = { duration_s: +trDur.value, steps: 50, t0_c: +trT0.value };
      if (analysis.value === 'thermo_mech') setup.ref_temp_c = +refT.value;
    }
    if (geo.value.example && (geo.value.example.analysis || 'thermal') === (analysis.value === 'static' ? 'static' : 'thermal')) {
      setup.formula = geo.value.example.formula; setup.example = { key: geo.value.example.key, params: geo.value.example.params };
    }
    if (mbdSource.value && geo.value?.sha === mbdSource.value.sha) setup.source = { job: mbdSource.value.job, member: mbdSource.value.member };
    job.value = await post('/cae/jobs', { step_sha: geo.value.sha, setup, item: geo.value.item, title: title.value || geo.value.name });
    result.value = null;
    poll();
    loadJobs();
  } catch (e) { err.value = e.message; } finally { submitting.value = false; }
}
function poll() {
  clearTimeout(pollT);
  if (!job.value || ['done', 'failed'].includes(job.value.status)) return;
  pollT = setTimeout(async () => {
    try {
      job.value = await get('/cae/jobs/' + job.value.id);
      if (job.value.started) elapsed.value = Math.round(Date.now() / 1000 - job.value.started);
      if (job.value.status === 'done') { await showResult(job.value); loadJobs(); return; }
      if (job.value.status === 'failed') { loadJobs(); return; }
    } catch (e) { /* 网络抖动：下次再问 */ }
    poll();
  }, 1500);
}
async function showResult(j) {
  const surface = await fetchSurface(j.id);
  result.value = { stats: j.stats, surface };
  field.value = j.setup?.analysis && j.setup.analysis !== 'static' ? 'temp' : 'vm';
  surface.thermoOnly = j.setup?.analysis === 'thermal';
  exp.value = j.ai_text ? { text: j.ai_text, actions: [], engine: 'saved' } : null;
  resetFatigue(j);
}
async function openJob(j) {
  job.value = j;
  err.value = '';
  try { await showResult(j); window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) { err.value = e.message; }
}
// ---------------------------------------------------------------- AI：一句话设置、结果解释（第 11 轮 F3、F7）
const aiText = ref('');
const aiBusy = ref(false);
const aiRes = ref(null);
const aiHint = computed(() => (geo.value?.item === 'SH-301'
  ? $t('例如：两个 Ø35 轴承位支承（左边那个止推），右端 Ø30 轴伸限制转动，键槽侧面加 350 N·m 扭矩，45 钢调质')
  : $t('例如：左端面固定，右端面加 1000 N 向下的力，6061 铝')));
async function aiFill() {
  aiBusy.value = true; err.value = '';
  try {
    const r = await post('/cae/ai-setup', { text: aiText.value, faces: geo.value.faces, solid: geo.value.solid });
    aiRes.value = r;
    const ax = axes.value[0]?.key;
    rows.value = r.rows.map((x) => ({ key: ++keyN, fx: 0, fy: 0, fz: 0, value: 0, thrust: false, axis: ax, ...x, faces: [...x.faces] }));
    rows.value.forEach((x) => {                                   // 圆柱支承：轴线跟着所选圆柱面
      if (KINDS[x.kind].cyl) { const a = axes.value.find((y) => y.faces.includes(x.faces[0])); if (a) x.axis = a.key; }
    });
    if (r.material_id) matId.value = r.material_id;
    active.value = -1;
    if (!title.value) title.value = aiText.value.slice(0, 40);
  } catch (e) { err.value = e.message; } finally { aiBusy.value = false; }
}
// 第 14 轮：一句话设置热边界
const thAiText = ref(''), thAiBusy = ref(false), thAiRes = ref(null);
const thAiHint = computed(() => (geo.value?.example?.key === 'heatsink'
  ? $t('例如：CPU 接触面发热 65 W，其余所有面风扇直吹散热，室温 25 ℃')
  : geo.value?.example ? $t('例如：箱体内壁发热 480 W，外表面自然对流（通风良好），底面装在机座上不散热，环境 20 度')
    : $t('例如：面 3 发热 20 W，其余所有面自然对流，环境 25 ℃，6061 铝')));
async function thAiFill() {
  thAiBusy.value = true; err.value = '';
  try {
    const r = await post('/cae/ai-setup-thermal', { text: thAiText.value, faces: geo.value.faces, solid: geo.value.solid, groups: geo.value.example?.groups });
    thAiRes.value = r;
    thRows.value = r.rows.map((x) => ({ key: ++thKey, faces: [], rest: false, value: 0, h: 17.45, tinf: 20,
      ...x, film: x.film ?? (films.value.find((f) => Math.abs(f.h - (x.h ?? -1)) < 1e-6)?.id || ''), faces: [...(x.faces || [])] }));
    if (r.material_id) matId.value = r.material_id;
    if (r.transient && analysis.value === 'thermal') { transient.value = true; trDur.value = r.transient.duration_s; trT0.value = r.transient.t0_c ?? trT0.value; }
    if (r.ref_temp_c != null) refT.value = r.ref_temp_c;
    active.value = -1;
    if (!title.value) title.value = thAiText.value.slice(0, 40);
  } catch (e) { err.value = e.message; } finally { thAiBusy.value = false; }
}
const exp = ref(null);
const expBusy = ref(false);
const expErr = ref('');
const actBusy = ref(false);
async function explain() {
  expBusy.value = true; expErr.value = '';
  try { exp.value = await post(`/cae/jobs/${encodeURIComponent(job.value.id)}/explain`, geo.value?.sha === job.value.step_sha ? { faces: geo.value.faces } : {}); }
  catch (e) { expErr.value = e.message; } finally { expBusy.value = false; }
}
async function act(a) {
  if (a.kind === 'example') {                                     // 第 14 轮：示例零件改参数重算（加散热筋、加片数）
    const ex = job.value?.setup?.example;
    if (!ex) return;
    actBusy.value = true;
    try {
      partSel.value = 'ex:' + ex.key;
      await nextTick();
      exParams.value = { ...ex.params, ...a.params };
      await loadItem();
      if (geo.value?.example) { title.value = geo.value.example.title; await submit(); }
    } finally { actBusy.value = false; }
    return;
  }
  if (a.kind === 'design') {
    router.push({ path: '/work/engineer', query: { suggest: JSON.stringify(a.params), note: a.note || '' } });
    return;
  }
  if (a.kind === 'material') {                                    // 同一零件、同一工况，换材料重算
    actBusy.value = true; expErr.value = '';
    try {
      const j0 = job.value;
      const mname = materials.value.find((m) => m.id === a.material_id)?.name || a.material_id;
      job.value = await post('/cae/jobs', { step_sha: j0.step_sha, item: j0.item, title: $t('{a}（换 {b}）', { a: j0.title || j0.item || '', b: mname }),
        setup: { ...j0.setup, material_id: a.material_id } });
      result.value = null; exp.value = null;
      poll(); loadJobs();
    } catch (e) { expErr.value = e.message; } finally { actBusy.value = false; }
  }
}

// ---------------------------------------------------------------- 疲劳寿命
const SURF = { polished: $t('抛光（β 1.0）'), ground: $t('磨削（β 0.92）'), fine_turned: $t('精车（β 0.85）'), rough_turned: $t('粗车（β 0.75）'), forged: $t('锻造毛坯（β 0.55）') };
const hasTorque = computed(() => (job.value?.setup?.loads || []).some((l) => l.type === 'torque'));
const refLoad = computed(() => (job.value?.setup?.loads || []).filter((l) => l.type === 'torque').reduce((a, l) => a + l.value_nmm / 1000, 0));
const refUnit = computed(() => (hasTorque.value ? 'N·m' : $t('× 计算工况')));
const spec = ref({ kind: 'const', max: 350, min: 0, freq: 1, log: '', mjob: '', joint: '', values: [], secs: 1, name: '' });
const mjobs = ref([]);                  // 第 11 轮 F1：关节力矩记录
const mjoints = computed(() => ((mjobs.value.find((m) => m.id === spec.value.mjob)?.stats?.drives) || []).map((d) => d.joint));
async function readCsv(ev) {
  const f = ev.target.files[0];
  if (!f) return;
  const nums = [];
  for (const line of (await f.text()).split(/\r?\n/)) {
    const cells = line.split(/[,;\t]/).map((x) => x.trim()).filter(Boolean);
    const v = cells.length ? Number(cells[cells.length - 1]) : NaN;
    if (Number.isFinite(v)) nums.push(v);
  }
  spec.value = { ...spec.value, values: nums.slice(0, 200000), name: f.name };
}
const fopt = ref({ surface: 'ground', size_factor: 0.85, kf: 1, haibach: true });
const fat = ref(null);
const modBusy = ref(false), modErr = ref(''), workRpm = ref(0);       // 固有频率（第 11 轮 F2）
async function runModal() {
  modBusy.value = true; modErr.value = '';
  try { job.value = { ...job.value, modal: await post(`/cae/jobs/${encodeURIComponent(job.value.id)}/modal`) }; } catch (e) { modErr.value = e.message; } finally { modBusy.value = false; }
}
const fatBusy = ref(false);
const fatErr = ref('');
const logs = ref([]);
const logSeries = ref([]);
const sparkPts = computed(() => {
  const s = logSeries.value; if (!s.length) return '';
  const hi = Math.max(...s.map(Math.abs)) || 1;
  return s.map((v, i) => `${(i / (s.length - 1) * 300).toFixed(1)},${(58 - (v / hi) * 54).toFixed(1)}`).join(' ');
});
const fmtHours = (h) => (h >= 8.76e9 ? $t('超过 100 万年（实际上无限）') : h >= 87600 ? (h / 8760).toPrecision(3) + $t(' 年（') + h.toExponential(2) + ' h）' : h >= 100 ? h.toFixed(0) + $t(' 小时') : h.toPrecision(3) + $t(' 小时'));   // i18n-ok 只剩标点
watch(() => spec.value.log, async (id) => {
  logSeries.value = [];
  if (id) { try { logSeries.value = (await get('/cae/torque-logs/' + id)).samples_nm; } catch (e) { /* 看不到曲线不影响计算 */ } }
});
watch(() => spec.value.kind, async (k) => { if (k === 'log' && !logs.value.length) { try { logs.value = (await get('/cae/torque-logs')).logs; } catch (e) { /* */ } } });
watch(() => spec.value.kind, async (k) => { if (k === 'joint' && !mjobs.value.length) { try { mjobs.value = ((await get('/mbd/jobs')).jobs || []).filter((m) => m.status === 'done'); } catch (e) { /* */ } } });
function resetFatigue(j) {
  fat.value = j?.fatigue || null; fatErr.value = '';
  spec.value = { kind: 'const', max: hasTorque.value ? +refLoad.value.toFixed(1) : 1, min: hasTorque.value ? 0 : -1, freq: 1, log: '', mjob: '', joint: '', values: [], secs: 1, name: '' };
}
async function runFatigue() {
  fatBusy.value = true; fatErr.value = '';
  try {
    const k = spec.value.kind;
    const sp = k === 'log' ? { kind: 'log', id: spec.value.log } : k === 'mbd' ? { kind: 'mbd' }
      : k === 'joint' ? { kind: 'joint', job: spec.value.mjob, joint: spec.value.joint }
      : k === 'csv' ? { kind: 'csv', values: spec.value.values, duration_s: spec.value.secs, name: spec.value.name }
      : { kind: 'const', max: spec.value.max, min: spec.value.min, freq_hz: spec.value.freq };
    const r = await post(`/cae/jobs/${encodeURIComponent(job.value.id)}/fatigue`, { spectrum: sp, ...fopt.value });
    fat.value = r.summary;
    job.value = { ...job.value, fatigue: r.summary };
    const raw = Uint8Array.from(atob(r.damage_b64), (c) => c.charCodeAt(0));
    const D = new Float32Array(raw.buffer);
    const lg = new Float32Array(D.length);
    for (let i = 0; i < D.length; i++) lg[i] = D[i] > 0 ? Math.log10(D[i]) : -30;
    result.value.surface.lgD = lg;
    field.value = 'life';
  } catch (e) { fatErr.value = e.message; } finally { fatBusy.value = false; }
}

// 报告：自动截应力、位移两张云图，连同设置和结果生成 Word
const reporting = ref(false);
const frame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
async function downloadReport() {
  reporting.value = true; err.value = '';
  const keep = field.value;
  try {
    const images = [];
    const shots = jobAnalysis.value === 'thermal' ? [['temp', $t('温度云图（℃）')]] : jobAnalysis.value === 'thermo_mech'
      ? [['temp', $t('温度云图（℃）')], ['vm', $t('热应力 Von Mises 云图（MPa）')], ['u', $t('热变形云图（mm）')]] : [['vm', $t('Von Mises 应力云图（MPa）')], ['u', $t('位移云图（mm）')]];
    if (result.value.surface.lgD) shots.push(['life', $t('疲劳寿命云图（红 = 寿命最短）')]);
    for (const [f, cap] of shots) {
      field.value = f;
      await frame(); await frame();
      images.push({ data: viewer.value.snapshot(), caption: $t('{a}，色标蓝 → 红 = 低 → 高（最高 {b}），变形放大 {c} 倍；粉点为最大应力位置，青点为最大位移位置', { a: cap, b: f === 'temp' ? st.value.t_max_c.toFixed(1) + ' ℃' : f === 'vm' ? st.value.vm_peak_all_mpa.toFixed(1) + ' MPa' : f === 'u' ? st.value.u_max_mm.toPrecision(3) + ' mm' : (fat.value?.infinite ? $t('无限寿命') : $t('最短 ') + fmtHours(fat.value.life_hours)), c: deformX.value }) });
    }
    const r = await fetch(`/api/cae/jobs/${encodeURIComponent(job.value.id)}/report`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'x-wq-token': session.token }, body: JSON.stringify({ images }) });
    if (!r.ok) throw new ApiError(r.status, (await r.json().catch(() => ({}))).detail || $t('报告生成失败'));
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await r.blob());
    a.download = $t('{a}报告-{b}.docx', { a: isThermal.value ? $t('温度场') : $t('有限元'), b: job.value.item || job.value.id });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch (e) { err.value = e.message; } finally { field.value = keep; reporting.value = false; }
}
function backToSetup() { result.value = null; job.value = null; }
watch(analysis, (a) => { if (a !== 'static' && field.value === 'life') field.value = 'temp'; });
async function loadJobs() { try { jobs.value = (await get('/cae/jobs')).jobs; } catch (e) { /* 计算服务没开时不挡页面 */ } }

watch(axes, (a) => rows.value.forEach((r) => { if (!a.find((x) => x.key === r.axis)) r.axis = a[0]?.key; }));

onMounted(async () => {
  try {
    const [p, m] = await Promise.all([get('/cae/parts'), get('/cae/materials')]);
    parts.value = p.items; materials.value = m.materials; examples.value = p.examples || []; films.value = m.films || [];
  } catch (e) { err.value = e.status === 503 ? $t('计算服务暂时连不上，请稍后再试') : e.message; }
  if (route.query.example && examples.value.find((e) => e.key === route.query.example)) {   // 第 14 轮：设计优化 → 按这组参数重算温度场
    partSel.value = 'ex:' + route.query.example;
    await nextTick();
    try { exParams.value = { ...exParams.value, ...JSON.parse(route.query.params || '{}') }; } catch (e) { /* 参数坏了用默认 */ }
    await loadItem();
  }
  if (route.query.mbd && route.query.member) {                     // 第 12 轮：动力学 → 有限元
    busy.value = true;
    try {
      const r = await post(`/mbd/jobs/${encodeURIComponent(route.query.mbd)}/to-fea`, { member: route.query.member });
      geo.value = r.geometry;
      rows.value = r.rows.map((x) => ({ key: ++keyN, fx: 0, fy: 0, fz: 0, value: 0, thrust: false, axis: null, ...x }));
      title.value = r.title; matId.value = '45-QT'; active.value = -1;
      mbdSource.value = { ...r.source, sha: r.geometry.sha };
      mbdNote.value = $t('来自运动与动力分析：') + r.note + $t('；最大受力 {a} N，出现在 t = {b} s。', { a: r.peak_N.toFixed(0), b: r.peak_t.toFixed(3) });
    } catch (e) { err.value = e.message; } finally { busy.value = false; }
  }
  if (route.query.cfd) {                                           // 第 16 轮：流体分析算出的散热系数 → 温度场
    busy.value = true;
    try {
      const r = await post(`/cfd/jobs/${encodeURIComponent(route.query.cfd)}/to-thermal`, {});
      geo.value = r.geometry;
      partSel.value = r.geometry.example ? 'ex:' + r.geometry.example.key : '';
      analysis.value = 'thermal';
      await nextTick();
      thRows.value = r.thermal.map((l) => ({ key: ++thKey, kind: l.type, faces: Array.isArray(l.faces) ? [...l.faces] : [], rest: l.faces === 'rest',
        value: l.value_c ?? l.power_w ?? 0, h: l.h_w_m2k ?? 17.45, tinf: l.t_inf_c ?? 20, film: '' }));
      if (r.material_id) matId.value = r.material_id;
      if (r.mesh_mm) meshOverride.value = r.mesh_mm;
      title.value = r.title; active.value = -1;
      mbdNote.value = $t('来自流体分析：') + r.note + '。';   // i18n-ok 只剩标点
    } catch (e) { err.value = e.message; } finally { busy.value = false; }
  }
  if (route.query.topo) {                                          // 第 14 轮：拓扑优化 → 拉伸成板件做有限元校核
    busy.value = true;
    try {
      const r = await post(`/opt/topo/${encodeURIComponent(route.query.topo)}/to-fea`, {});
      geo.value = r.geometry;
      rows.value = r.rows.map((x) => ({ key: ++keyN, fx: 0, fy: 0, fz: 0, value: 0, thrust: false, axis: null, ...x }));
      title.value = r.title; matId.value = r.material_id; meshOverride.value = r.mesh_mm; active.value = -1;
      mbdNote.value = $t('来自拓扑优化：') + r.note + '。';   // i18n-ok 只剩标点
    } catch (e) { err.value = e.message; } finally { busy.value = false; }
  }
  loadJobs();
  listT = setInterval(() => { if (jobs.value.some((j) => ['queued', 'running'].includes(j.status))) loadJobs(); }, 5000);
});
onUnmounted(() => { clearTimeout(pollT); clearInterval(listT); });
</script>

<style scoped>
.labs { margin-left: auto; white-space: nowrap; }
.side { width: 380px; flex-shrink: 0; display: flex; flex-direction: column; gap: 9px; align-self: flex-start; }
.grow { flex: 1; min-width: 0; }
.step { display: flex; align-items: center; gap: 8px; font-weight: 600; margin-top: 6px; }
.step b { width: 22px; height: 22px; border-radius: 50%; background: var(--accent); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; }
.line { display: flex; gap: 8px; }
.grow-in, .full { flex: 1; height: 34px; border: 1px solid #C8CEC7; border-radius: 6px; padding: 0 8px; background: #fff; width: 100%; }
.upload { display: flex; flex-direction: column; gap: 4px; color: var(--muted); }
.matline { line-height: 1.6; }
.src-box { background: var(--surface-2); border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; margin-top: 4px; }
.adds { display: flex; flex-wrap: wrap; gap: 6px; }
.add { border: 1px solid var(--c); color: var(--c); background: #fff; border-radius: 14px; padding: 3px 10px; cursor: pointer; font-size: 12px; }
.add:hover { background: color-mix(in srgb, var(--c) 10%, #fff); }
.small-btn { height: 30px; font-size: 12px; }
.step.sub { margin-top: 2px; font-size: 13px; }
.exbox { border: 1px dashed var(--line); border-radius: 8px; padding: 6px 8px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; margin-top: 4px; }
.grid2 input { width: 70px; height: 26px; border: 1px solid #C8CEC7; border-radius: 5px; }
input.num { width: 70px; height: 26px; border: 1px solid #C8CEC7; border-radius: 5px; padding: 0 4px; }
.formula { margin-top: 10px; border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; background: var(--surface-2); line-height: 1.7; }
.tchart { width: 100%; height: 160px; margin-top: 10px; background: var(--surface-2); border-radius: 8px; }
.lrow { border: 1px solid var(--line); border-left: 4px solid var(--c); border-radius: 8px; padding: 8px 10px; cursor: pointer; display: flex; flex-direction: column; gap: 6px; }
.lrow.active { box-shadow: 0 0 0 2px color-mix(in srgb, var(--c) 35%, transparent); }
.lhead { display: flex; align-items: center; gap: 8px; }
.lhead i { width: 10px; height: 10px; border-radius: 2px; background: var(--c); }
.x { margin-left: auto; border: 0; background: none; font-size: 18px; line-height: 1; cursor: pointer; color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 4px; }
.chip { font-size: 12px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 10px; padding: 1px 8px; }
.chip a { color: var(--muted); margin-left: 2px; }
.params { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; }
.params input[type=number] { width: 74px; height: 28px; border: 1px solid #C8CEC7; border-radius: 5px; padding: 0 6px; }
.params select { height: 28px; border: 1px solid #C8CEC7; border-radius: 5px; max-width: 250px; }
.params .wide { flex-basis: 100%; }
.chk { display: flex; align-items: center; gap: 4px; }
.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; align-self: flex-start; }
.seg button { border: 0; background: #fff; padding: 6px 12px; cursor: pointer; font-size: 13px; }
.seg button.on { background: var(--accent-bg); font-weight: 600; }
.big-w { height: 42px; font-size: 15px; margin-top: 6px; }
.card-head { flex-wrap: wrap; align-items: center; }
.deform { display: flex; align-items: center; gap: 6px; }
.jobbar { border-radius: 8px; padding: 10px 14px; margin-bottom: 10px; background: var(--accent-bg); color: var(--accent); display: flex; align-items: center; gap: 10px; }
.jobbar.failed { background: var(--bad-bg); color: var(--bad); }
.spin { width: 14px; height: 14px; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: sp 0.8s linear infinite; }
@keyframes sp { to { transform: rotate(360deg); } }
.big-empty { padding: 120px 0; text-align: center; }
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 12px; }
.stat { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; display: flex; flex-direction: column; gap: 2px; }
.stat span { font-size: 12px; color: var(--muted); }
.stat b { font-size: 22px; font-family: var(--mono); }
.stat b small { font-size: 12px; font-weight: 400; }
.stat.good { background: var(--good-bg); } .stat.good b { color: var(--good); }
.stat.warn { background: var(--warn-bg); } .stat.warn b { color: var(--warn-ink); }
.stat.bad { background: var(--bad-bg); } .stat.bad b { color: var(--bad); }
.notes p { margin: 8px 0 0; }
tr.cur td { background: var(--accent-bg); }
.sugg { background: var(--task-bg); border: 1px solid var(--task-line); color: var(--task-ink); border-radius: 6px; padding: 6px 8px; }
.ai-box { display: flex; flex-direction: column; gap: 6px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
.ai-box textarea { border: 1px solid #C8CEC7; border-radius: 6px; padding: 6px 8px; resize: vertical; }
.ai-notes { display: flex; flex-direction: column; gap: 2px; }
.warnline { color: var(--warn-ink); }
.ai-exp { border-top: 1px solid var(--line); margin-top: 16px; padding-top: 14px; display: flex; flex-direction: column; gap: 8px; }
.ai-exp h3 { font-size: 15px; }
.ai-exp .line { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.exp-text p { margin: 4px 0; line-height: 1.7; }
.fat { border-top: 1px solid var(--line); margin-top: 16px; padding-top: 14px; display: flex; flex-direction: column; gap: 10px; }
.fat h3 { font-size: 15px; }
.num-in { width: 90px; }
.fat-grid { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: flex-end; }
.fat-grid .field input { width: 120px; }
.fat-grid .field.wide { flex-basis: 100%; }
.fat-grid .field.wide select { max-width: 560px; }
.spark { width: 100%; max-width: 560px; height: 60px; background: var(--surface-2); border-radius: 6px; }
.fat .btn { align-self: flex-start; }
.fat-res { display: flex; gap: 14px; align-items: flex-start; }
.fat-res .stat { min-width: 200px; }
.fat-txt { display: flex; flex-direction: column; gap: 6px; flex: 1; }
@media (max-width: 1100px) { .side { width: 100%; } .stats { grid-template-columns: repeat(2, 1fr); } }
</style>
