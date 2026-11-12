<!-- 设计案例（第 161 轮）：本厂三个“任务书 → 方案 → 计算 → 仿真 → 三维与图纸 → 工艺 → 制造 → 总结”全过程案例。只读；
     资料由 tools/cases 生成（factory/cases/<厂>/<案例号>/）。手机宽度可用：八步在窄屏上变成横向滚动的标签。 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('设计案例') }}</h1>
      <span class="muted">{{ $t('从任务书到车间：每一步都用本平台的软件算出来') }}</span>
      <span class="r small"><router-link to="/help/teach/design-cases">{{ $t('帮助') }}</router-link></span></div>
    <div v-if="err" class="err">{{ err }}</div>

    <!-- 列表 -->
    <template v-if="!id && list">
      <div class="grid" data-help="cases-grid">
        <component :is="c.ready ? 'router-link' : 'div'" v-for="c in cards" :key="c.id" :to="c.ready ? '/cases/' + c.id : undefined"
                   class="card cs" :class="{ off: !c.ready, ok: c.all_ok }" data-help="cases-card">
          <div class="lh"><b class="no">{{ c.id }}</b><span class="dom small">{{ levelName(c.id) }}</span>
            <span v-if="c.ready" class="small r" :class="c.all_ok ? 'good' : 'warn'">{{ $t('校核 {a}/{b}', { a: c.n_ok, b: c.n_checks }) }}</span></div>
          <h2>{{ c.ready ? (en ? c.title_en : c.title) : $t('制作中') }}</h2>
          <p v-if="c.ready" class="small muted">{{ en ? c.summary_en : c.summary }}</p>
          <p v-else class="small muted">{{ $t('这一级的案例还在做，做好后出现在这里。') }}</p>
        </component>
      </div>
      <p class="small muted note">{{ $t('A 是一个零件或模块，B 是一个部件，C 是整台产品；A、B 正好是 C 里的零部件。') }}</p>
    </template>

    <!-- 一个案例 -->
    <template v-if="id && c">
      <p class="small"><router-link to="/cases">← {{ $t('全部案例') }}</router-link></p>
      <div class="card head">
        <div class="lh"><b class="no">{{ c.id }}</b><span class="dom small">{{ levelName(c.id) }}</span><span class="small muted">{{ c.item }}</span></div>
        <h2>{{ en ? c.title_en : c.title }}</h2>
        <p class="muted">{{ en ? c.summary_en : c.summary }}</p>
        <p class="small honest">{{ en ? c.honest_en : c.honest }}</p>
      </div>
      <div class="steps" role="tablist" data-help="cases-steps">
        <button v-for="(s, i) in c.steps" :key="s.key" class="st" :class="{ on: cur === i }" role="tab" @click="go(i)">
          <span class="n">{{ i + 1 }}</span>{{ en ? s.title_en : s.title }}
          <span v-if="badStep(s.key)" class="bad">✗</span></button>
      </div>
      <div v-if="step" class="card body">
        <h2>{{ cur + 1 }}. {{ en ? step.title_en : step.title }}</h2>
        <p class="sum">{{ en ? step.summary_en : step.summary }}</p>
        <div v-if="step.facts.length" class="facts">
          <span v-for="f in step.facts" :key="f.name" class="fact"><span class="small muted">{{ en ? f.name_en : f.name }}</span><b>{{ f.value }}</b><span class="small">{{ f.unit }}</span></span>
        </div>
        <div v-if="step.tools.length" class="tools small">{{ $t('打开软件：') }}
          <router-link v-for="t in step.tools" :key="t.route" :to="t.route" class="btn">{{ en ? t.label_en : t.label }}</router-link></div>
        <figure v-for="f in step.figs" :key="f.file" class="fig">
          <a :href="url(f.file)" target="_blank" rel="noopener"><img :src="url(f.file)" :alt="f.caption" loading="lazy"></a>
          <figcaption class="small muted">{{ en ? f.caption_en : f.caption }}</figcaption>
        </figure>
        <div v-if="step.key === 'review'" class="tw">
          <table class="tbl"><thead><tr><th></th><th>{{ $t('项目') }}</th><th>{{ $t('结果') }}</th><th>{{ $t('要求') }}</th><th>{{ $t('出处') }}</th></tr></thead>
            <tbody><tr v-for="(k, j) in c.checks" :key="j"><td :class="k.ok ? 'good' : 'warn'">{{ k.ok ? '✓' : '✗' }}</td>
              <td>{{ en ? k.what_en : k.what }}</td><td>{{ k.value }} {{ k.unit }}</td><td>{{ k.op }} {{ k.limit }}</td><td class="small muted">{{ $td(k.src) }}</td></tr></tbody></table>
        </div>
        <p v-if="en && step.md" class="small muted">{{ $t('下面的正文是中文。') }}</p>
        <div v-if="html" class="md" v-html="html"></div>
        <div v-if="step.files.length" class="files small">{{ $t('下载：') }}
          <a v-for="f in step.files" :key="f.file" :href="url(f.file)" target="_blank" rel="noopener">{{ en ? f.label_en : f.label }}</a></div>
        <div class="nav">
          <button v-if="cur > 0" class="btn" @click="go(cur - 1)">← {{ en ? c.steps[cur - 1].title_en : c.steps[cur - 1].title }}</button>
          <button v-if="cur < c.steps.length - 1" class="btn primary r" @click="go(cur + 1)">{{ en ? c.steps[cur + 1].title_en : c.steps[cur + 1].title }} →</button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { t as $t, isEn } from '../lib/i18n';
import { computed, nextTick, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import MarkdownIt from 'markdown-it';
import { get } from '../lib/api';

const md = new MarkdownIt({ html: false, linkify: true });
md.renderer.rules.table_open = () => '<div class="tablewrap"><table>';
md.renderer.rules.table_close = () => '</table></div>';
const route = useRoute();
const router = useRouter();
const en = computed(() => isEn());
const id = computed(() => route.params.id || '');
const list = ref(null);
const c = ref(null);
const err = ref('');
const cur = ref(0);
const html = ref('');
const LEVELS = { A: ['简单', 'Simple'], B: ['中等', 'Intermediate'], C: ['完整', 'Complete'] };   // i18n-ok 中英对照
const levelName = (k) => (en.value ? LEVELS[k][1] : LEVELS[k][0]);
const cards = computed(() => ['A', 'B', 'C'].map((k) => ({ id: k, ...(list.value?.cases.find((x) => x.id === k) || {}), ready: !!list.value?.cases.find((x) => x.id === k) })));
const step = computed(() => c.value?.steps[cur.value]);
const url = (f) => `/api/cases/${c.value.plant}/${c.value.id}/f/${encodeURIComponent(f)}`;
const badStep = (k) => c.value?.checks.some((x) => x.step === k && !x.ok);

function go(i) { router.replace({ query: { ...route.query, s: String(i + 1) } }); }

async function loadMd() {
  html.value = '';
  const s = step.value;
  if (!s?.md) return;
  try {
    const r = await fetch(url(s.md));
    const text = await r.text();
    if (step.value === s) html.value = md.render(text.replace(/^# .+\n/, ''));   // 标题已在卡片上
  } catch (e) { err.value = e.message; }
}

watch(id, async (v) => {
  err.value = '';
  try {
    if (!v) { c.value = null; list.value = await get('/cases'); return; }
    c.value = await get('/cases/' + v);
  } catch (e) { err.value = e.message; }
}, { immediate: true });
watch(() => [c.value, route.query.s], () => {
  const n = parseInt(route.query.s || '1', 10);
  cur.value = c.value ? Math.min(Math.max(n - 1, 0), c.value.steps.length - 1) : 0;
  loadMd();
  nextTick(() => document.querySelector('.st.on')?.scrollIntoView({ block: 'nearest', inline: 'center' }));   // 手机上当前一步滚到看得见
});
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.r { margin-left: auto; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.cs { display: flex; flex-direction: column; gap: 4px; color: inherit; text-decoration: none; border-left: 4px solid var(--line); }
a.cs:hover { box-shadow: 0 1px 6px rgba(0, 0, 0, .1); }
.cs.ok { border-left-color: var(--good); }
.cs.off { opacity: .6; }
.lh { display: flex; gap: 8px; align-items: center; }
.no { font-size: 18px; }
.dom { background: var(--surface-2); border-radius: 10px; padding: 1px 8px; }
.cs h2, .head h2 { margin: 2px 0; font-size: 17px; }
.note { margin-top: 10px; }
.good { color: var(--good); }
.warn { color: var(--warn); }
.honest { background: var(--surface-2); padding: 4px 8px; border-radius: 4px; display: inline-block; }
.steps { display: flex; flex-wrap: wrap; gap: 4px; margin: 12px 0 8px; }
@media (max-width: 700px) { .steps { flex-wrap: nowrap; overflow-x: auto; padding-bottom: 2px; } }
.st { flex: 0 0 auto; border: 1px solid var(--line); background: var(--surface); border-radius: 16px; padding: 4px 12px 4px 4px; cursor: pointer; display: flex; align-items: center; gap: 6px; font: inherit; color: inherit; }
.st .n { display: inline-flex; width: 22px; height: 22px; border-radius: 50%; background: var(--surface-2); align-items: center; justify-content: center; font-size: 12px; }
.st.on { border-color: var(--accent); background: var(--accent); color: #fff; }
.st.on .n { background: rgba(255, 255, 255, .25); }
.st .bad { color: var(--bad, #c92a2a); }
.body h2 { margin-top: 0; font-size: 18px; }
.sum { font-size: 15px; }
.facts { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
.fact { display: inline-flex; flex-direction: column; border: 1px solid var(--line); border-radius: 6px; padding: 4px 10px; min-width: 90px; }
.fact b { font-size: 17px; }
.tools { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 8px 0; }
.fig { margin: 12px 0; }
.fig img { max-width: 100%; height: auto; border: 1px solid var(--line); border-radius: 4px; background: #fff; }
.md { line-height: 1.65; overflow-wrap: anywhere; }
.md :deep(.tablewrap), .tw { overflow-x: auto; }
.md :deep(table), .tbl { border-collapse: collapse; margin: 8px 0; font-size: 13px; }
.md :deep(th), .md :deep(td), .tbl th, .tbl td { border: 1px solid var(--line); padding: 3px 8px; text-align: left; vertical-align: top; }
.md :deep(h2) { font-size: 16px; margin-top: 18px; }
.md :deep(code) { background: var(--surface-2); padding: 0 3px; border-radius: 3px; }
.files { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 12px; border-top: 1px solid var(--line); padding-top: 8px; }
.nav { display: flex; margin-top: 16px; gap: 8px; }
</style>
