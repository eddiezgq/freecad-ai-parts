<template>
  <div class="help" :class="{ bare: !session.token }">
    <header v-if="!session.token" class="topbar">
      <router-link to="/help" class="brand"><span class="logo">渠</span><b>问渠数字工厂</b><span class="muted">帮助</span></router-link>
      <router-link class="btn" :to="{ path: '/login', query: { next: $route.fullPath } }">登录</router-link>
    </header>

    <!-- 首页：实时 3D 车间 + 全流程 -->
    <template v-if="!chapter && !isDocs">
      <section class="hero">
        <div class="stage">
        <div ref="host" class="scene" aria-hidden="true"></div>
        <div class="hero-txt">
          <div class="eds" role="tablist" aria-label="帮助版本">
            <button v-for="e in EDITIONS" :key="e.key" role="tab" :aria-selected="e.key === ed" :class="{ on: e.key === ed }"
              @click="setEd(e.key)">{{ e.name }}<span>{{ e.who }}</span></button>
          </div>
          <h1>{{ ed === 'teach' ? '从一张图纸，到一台出厂的产品' : '把你的车间搬进数字工厂' }}</h1>
          <p class="lead">{{ ed === 'teach'
            ? `${plantName}在你眼前运转：设计、ERP、MRP、MES、车间、质量、厂情中枢连成一条线。点下面任一站，看它怎么做。`
            : `${plantName}的数字工厂：交一份 Excel 建好车间，产品从 FreeCAD 进来，计划、生产、质量、经营在一个工作台上。` }}</p>
        </div>
        </div>
        <div class="hero-flow">
          <FlowAnim dark clickable @pick="pickStage" />
        </div>
      </section>

      <section class="index">
        <div class="index-head">
          <h2>{{ edName }} · 共 {{ chapters.length }} 章</h2>
          <input v-model="q" type="search" class="search" placeholder="搜索帮助，比如：订单、Excel、备份" aria-label="搜索帮助">
        </div>
        <ol v-if="!q" class="line">
          <li v-for="(c, i) in chapters" :key="c.slug">
            <router-link :to="`/help/${ed}/${c.slug}`">
              <span class="stop">{{ i + 1 }}</span>
              <span class="t"><b>{{ c.title }}</b><span class="small muted">{{ c.lead }}</span></span>
              <span class="tags small"><span v-for="t in c.has" :key="t">{{ t }}</span></span>
            </router-link>
          </li>
        </ol>
        <div v-else class="results">
          <p v-if="!hits.length" class="muted">没有找到“{{ q }}”。换个词试试，或者直接问 AI 工厂助手。</p>
          <router-link v-for="h in hits" :key="h.slug" :to="`/help/${ed}/${h.slug}`" class="hit">
            <b>{{ h.title }}</b><span class="small" v-html="h.snip"></span>
          </router-link>
        </div>
      </section>

      <!-- 资料：仓库 docs/帮助、docs/演示 里较长的说明（服务器 /api/help/docs 列出、转成网页） -->
      <section class="index docs-index" aria-label="资料">
        <div class="index-head"><h2>资料</h2><span class="small muted">较长的说明文件：领域说明、术语表、演示脚本、企业版与课程接口</span></div>
        <p v-if="!session.token" class="small muted">登录后可以看。</p>
        <p v-else-if="docsErr" class="small muted">{{ docsErr }}</p>
        <div v-else class="dgroups">
          <div v-for="g in docGroups" :key="g.group" class="dg">
            <span class="small muted">{{ g.group }}</span>
            <router-link v-for="i in g.items" :key="i.name" :to="'/help/docs/' + i.name">{{ i.title }}</router-link>
          </div>
        </div>
      </section>
    </template>

    <!-- 资料里的一份说明 -->
    <div v-else-if="isDocs" class="read">
      <nav class="toc" aria-label="资料目录">
        <router-link :to="`/help/${defaultEd}`" class="back small">← 帮助首页</router-link>
        <div v-for="g in docGroups" :key="g.group" class="dg">
          <span class="small muted">{{ g.group }}</span>
          <router-link v-for="i in g.items" :key="i.name" :to="'/help/docs/' + i.name" :class="{ on: i.name === docName }">{{ i.title }}</router-link>
        </div>
      </nav>
      <article class="doc" @click="onLink">
        <p class="kicker small muted">资料</p>
        <p v-if="!session.token" class="muted">资料要登录后看。<router-link :to="{ path: '/login', query: { next: $route.fullPath } }">登录</router-link></p>
        <p v-else-if="docErr" class="muted">{{ docErr }}</p>
        <!-- 正文来自仓库里的 Markdown（服务器转 HTML），不是用户输入 -->
        <div v-if="doc" class="md docmd" v-html="doc.html"></div>
      </article>
    </div>

    <!-- 一章 -->
    <div v-else class="read">
      <nav class="toc" aria-label="章节">
        <router-link :to="`/help/${ed}`" class="back small">← {{ edName }}目录</router-link>
        <ol>
          <li v-for="(c, i) in chapters" :key="c.slug" :class="{ on: c.slug === chapter.slug }">
            <router-link :to="`/help/${ed}/${c.slug}`"><span class="stop">{{ i + 1 }}</span>{{ c.title }}</router-link>
            <ul v-if="c.slug === chapter.slug && c.heads.length" class="heads">
              <li v-for="h in c.heads" :key="h.id"><a :href="'#' + h.id" @click.prevent="jump(h.id)">{{ h.text }}</a></li>
            </ul>
          </li>
        </ol>
      </nav>
      <article class="doc" @click="onLink">
        <p class="kicker small muted">{{ edName }} · 第 {{ idx + 1 }} 章</p>
        <h1>{{ chapter.title }}</h1>
        <p v-if="chapter.lead" class="lead">{{ chapter.lead }}</p>
        <template v-for="(s, i) in chapter.segments" :key="i">
          <div v-if="s.type === 'md'" class="md" v-html="s.html"></div>
          <HelpBlock v-else :kind="s.kind" :args="s.args" :media="media" />
        </template>
        <footer class="pn">
          <router-link v-if="idx > 0" :to="`/help/${ed}/${chapters[idx - 1].slug}`" class="prev">
            <span class="small muted">上一章</span><b>{{ chapters[idx - 1].title }}</b></router-link>
          <router-link v-if="idx < chapters.length - 1" :to="`/help/${ed}/${chapters[idx + 1].slug}`" class="next">
            <span class="small muted">下一章</span><b>{{ chapters[idx + 1].title }}</b></router-link>
        </footer>
      </article>
    </div>
  </div>
</template>

<script setup>
// 帮助（第 30 轮 H-3，搬自 freecad-ai-parts ADR-0065）：教学版、企业版，另有“资料”（以前的帮助文件）。首页是实时 3D 车间和全流程动画；正文是 Markdown 加自定义块（带我去做、动画、视频、实时数据、问 AI）。
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { EDITIONS, STAGE_CHAPTER, chapterFiles } from '../help';
import { parse } from '../lib/helpdoc';
import { get, loadConfig, session } from '../lib/api';
import { bus, connectBus, onBus } from '../lib/bus';
import { createWorkshop } from '../lib/workshop3d';
import FlowAnim from '../components/help/anim/FlowAnim.vue';
import HelpBlock from '../components/help/HelpBlock.vue';

const route = useRoute();
const router = useRouter();
const cfg = ref(null);
const media = ref([]);
const q = ref('');
const host = ref(null);
let ws = null;
let off = null;

// 缺省版本：演示工厂打开教学版，企业工厂（工厂清单 demo_data: false）打开企业版
const defaultEd = computed(() => (cfg.value?.plant?.demo === false ? 'enterprise' : 'teach'));
const ed = computed(() => (EDITIONS.some((e) => e.key === route.params.ed) ? route.params.ed : defaultEd.value));
const isDocs = computed(() => route.params.ed === 'docs');
const edName = computed(() => EDITIONS.find((e) => e.key === ed.value)?.name);
const plantName = computed(() => cfg.value?.plant?.name || '问渠减速器厂');
const vars = computed(() => ({ 厂名: plantName.value, 公司: cfg.value?.plant?.company || '', 币种: cfg.value?.plant?.currency || '',
  班次: cfg.value?.plant?.shift || '' }));
const chapters = computed(() => chapterFiles(ed.value).map((f) => {
  const d = parse(f.src, vars.value);
  const kinds = new Set(d.segments.filter((s) => s.type === 'block').map((s) => s.kind));
  const has = [['goto', '带我去做'], ['video', '视频'], ['anim', '动画'], ['live', '实时数据']].filter(([k]) => kinds.has(k)).map(([, n]) => n);
  return { slug: f.slug, ...d, has };
}));
const chapter = computed(() => chapters.value.find((c) => c.slug === route.params.ch) || null);
const idx = computed(() => chapters.value.findIndex((c) => c.slug === route.params.ch));

const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const hits = computed(() => {
  const w = q.value.trim();
  if (!w) return [];
  return chapters.value.filter((c) => c.title.includes(w) || c.text.includes(w)).map((c) => {
    const i = c.text.indexOf(w);
    const raw = i < 0 ? c.lead : c.text.slice(Math.max(0, i - 30), i + w.length + 50);
    return { slug: c.slug, title: c.title, snip: esc(raw).replace(esc(w), `<mark>${esc(w)}</mark>`) };
  });
});

// 资料（第 30 轮 H-3）：以前的帮助（/api/help/docs），较长的说明文件
const docGroups = ref([]);
const docsErr = ref('');
const doc = ref(null);
const docErr = ref('');
const docName = computed(() => (isDocs.value ? route.params.ch || '使用说明' : ''));
async function loadDocList() {
  if (!session.token || docGroups.value.length) return;
  try { docGroups.value = (await get('/help/docs')).groups.filter((g) => g.items.length); docsErr.value = ''; } catch (e) { docsErr.value = e.message; }
}
async function loadDoc() {
  doc.value = null; docErr.value = '';
  if (!isDocs.value || !session.token) return;
  loadDocList();
  try { doc.value = await get('/help/docs/' + encodeURIComponent(docName.value)); window.scrollTo(0, 0); } catch (e) { docErr.value = e.message; }
}
watch(docName, loadDoc);
watch(() => session.token, () => { loadDocList(); loadDoc(); });
// 以前的地址 /help/<文件名>（书签、旧链接）转到资料
function legacy() {
  const e = route.params.ed;
  if (e && e !== 'docs' && !EDITIONS.some((x) => x.key === e)) router.replace('/help/docs/' + e);
}
watch(() => route.params.ed, legacy);

function setEd(k) { router.push(`/help/${k}`); }
function pickStage(i) {
  const slug = (STAGE_CHAPTER[ed.value] || [])[i];
  if (slug) router.push(`/help/${ed.value}/${slug}`);
}
function jump(id) { document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
// 正文里的站内链接不整页刷新
function onLink(e) {
  const a = e.target.closest('a');
  const href = a?.getAttribute('href');
  if (href && href.startsWith('/')) { e.preventDefault(); router.push(href); }
}

async function mount3d() {
  ws?.dispose(); ws = null;
  await nextTick();
  if (!host.value) return;
  try {
    const L = await get('/layout');
    if (!host.value) return;
    ws = createWorkshop(host.value, L, { night: true, autoRotate: !matchMedia('(prefers-reduced-motion: reduce)').matches });
    ws.update(bus.machines, bus.agvs);
  } catch { /* 没有 3D 也不影响帮助 */ }
}

watch(() => [route.params.ed, route.params.ch], () => {
  if (!route.params.ch && !isDocs.value) mount3d(); else { ws?.dispose(); ws = null; window.scrollTo(0, 0); }
});
onMounted(async () => {
  legacy();
  try { cfg.value = await loadConfig(); } catch { /* 用缺省 */ }
  // 没登录时工作台框架不连总线；帮助首页自己只读连上（与可嵌入 3D 车间一样，总线匿名只读）
  if (!session.token && cfg.value && !bus.connected) {
    try { connectBus(cfg.value.mqtt_ws.replace('localhost', location.hostname), cfg.value.plant?.demo === false ? 'prod' : 'teach'); } catch { /* 没有实时状态也能看 */ }
  }
  try { media.value = (await get('/help/media')).files || []; } catch { /* 没有视频 */ }
  off = onBus(() => ws?.update(bus.machines, bus.agvs));
  if (!route.params.ch && !isDocs.value) mount3d();
  loadDocList();
  loadDoc();
});
onUnmounted(() => { ws?.dispose(); off?.(); });
</script>

<style scoped>
.help { --read: 68ch; padding-bottom: 48px; }
.help.bare { background: var(--bg); min-height: 100vh; }
.topbar { display: flex; align-items: center; justify-content: space-between; padding: 12px 24px; background: var(--rail); }
.brand { display: flex; align-items: center; gap: 10px; color: #F4F6F3; text-decoration: none; }
.brand .logo { width: 28px; height: 28px; border-radius: 6px; background: var(--brand); color: var(--rail); display: grid; place-items: center; font-weight: 700; }
.brand .muted { color: var(--rail-muted); }

/* 首页：深色车间 */
.hero { position: relative; background: #17212B; color: #F4F6F3; border-radius: 0 0 14px 14px; overflow: hidden; }
.bare .hero { border-radius: 0; }
.stage { position: relative; }
.scene { height: min(56vh, 520px); min-height: 320px; }
.hero-txt { position: absolute; left: 0; top: 0; bottom: 0; width: min(100%, 760px); padding: 28px 32px; pointer-events: none;
  background: linear-gradient(90deg, rgba(23, 33, 43, 0.96) 0%, rgba(23, 33, 43, 0.85) 55%, rgba(23, 33, 43, 0) 100%); }
.hero h1 { font-size: clamp(28px, 4vw, 50px); line-height: 1.15; font-weight: 700; letter-spacing: -0.01em; max-width: 11em; margin-top: 22px; }
.hero .lead { color: #C9D3DA; max-width: 30em; line-height: 1.75; font-size: 15px; margin: 14px 0 0; }
.eds { display: inline-flex; gap: 4px; background: rgba(255, 255, 255, 0.06); padding: 4px; border-radius: 10px; pointer-events: auto; }
.eds button { background: none; border: 0; color: #C9D3DA; padding: 6px 14px; border-radius: 7px; cursor: pointer; display: flex; flex-direction: column;
  align-items: flex-start; font-size: 14px; font-weight: 600; }
.eds button span { font-size: 11px; font-weight: 400; color: #8795A1; }
.eds button.on { background: var(--brand); color: #17212B; }
.eds button.on span { color: #4A3A00; }
.eds button:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
.hero-flow { padding: 6px 28px 18px; background: #17212B; }

/* 章节：沿着一条线 */
.index { max-width: 980px; margin: 28px auto 0; padding: 0 24px; }
.index-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
.index-head h2 { font-size: 18px; }
.search { width: min(360px, 100%); padding: 9px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); font-size: 14px; }
.line { list-style: none; padding: 0; margin: 0; position: relative; }
.line::before { content: ''; position: absolute; left: 17px; top: 18px; bottom: 18px; width: 3px; background: var(--line); border-radius: 2px; }
.line li a { display: grid; grid-template-columns: 36px 1fr auto; gap: 14px; align-items: center; padding: 10px 12px 10px 0;
  color: var(--ink); text-decoration: none; border-radius: 8px; position: relative; }
.line li a:hover .stop, .line li a:focus-visible .stop { background: var(--brand); border-color: var(--brand); }
.line li a:hover b { color: var(--accent); }
.stop { width: 36px; height: 36px; border-radius: 50%; background: var(--surface); border: 3px solid var(--line); display: grid; place-items: center;
  font-weight: 700; font-size: 13px; z-index: 1; transition: background 0.2s; }
.line .t { display: flex; flex-direction: column; gap: 2px; }
.line .t b { font-size: 16px; }
.tags { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
.tags span { padding: 2px 8px; border-radius: 999px; background: var(--accent-bg); color: var(--accent); }
.results { display: flex; flex-direction: column; gap: 8px; }
.hit { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border-radius: 8px; background: var(--surface); color: var(--ink); text-decoration: none; }
.hit :deep(mark) { background: var(--task-bg); color: inherit; }

/* 阅读 */
.read { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 40px; max-width: 1180px; margin: 0 auto; padding: 24px; }
.toc { position: sticky; top: 16px; align-self: start; max-height: calc(100vh - 32px); overflow: auto; }
.toc ol { list-style: none; padding: 0; margin: 12px 0 0; }
.toc li > a { display: flex; align-items: center; gap: 8px; padding: 6px 6px; border-radius: 6px; color: var(--ink); text-decoration: none; font-size: 13px; }
.toc .stop { width: 22px; height: 22px; border-width: 2px; font-size: 11px; flex: none; }
.toc li.on > a { background: var(--surface); font-weight: 600; }
.toc li.on .stop { background: var(--brand); border-color: var(--brand); }
.heads { list-style: none; padding: 2px 0 6px 36px; margin: 0; }
.heads a { display: block; padding: 3px 0; font-size: 12px; color: var(--muted); }
.doc { max-width: var(--read); min-width: 0; }
.kicker { margin: 0 0 6px; }
.doc h1 { font-size: clamp(24px, 3vw, 34px); line-height: 1.2; }
.doc .lead { font-size: 16px; color: var(--muted); line-height: 1.7; margin: 10px 0 8px; }
.md :deep(h2) { font-size: 20px; margin: 34px 0 10px; scroll-margin-top: 16px; }
.md :deep(h3) { font-size: 16px; margin: 22px 0 8px; }
.md :deep(p), .md :deep(li) { line-height: 1.8; font-size: 15px; }
.md :deep(code) { font-family: var(--mono); font-size: 13px; background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }
.md :deep(pre) { background: var(--surface-2); padding: 12px 14px; border-radius: 8px; overflow: auto; }
.md :deep(pre code) { background: none; padding: 0; }
.md :deep(.tablewrap) { overflow-x: auto; margin: 12px 0; }
.md :deep(table) { border-collapse: collapse; font-size: 14px; min-width: 100%; }
.md :deep(td:first-child), .md :deep(th:first-child) { white-space: nowrap; }
.md :deep(th) { white-space: nowrap; }
.md :deep(td) { min-width: 5em; }
.md :deep(th), .md :deep(td) { border-bottom: 1px solid var(--line); padding: 7px 10px; text-align: left; vertical-align: top; }
.md :deep(th) { background: var(--surface-2); font-weight: 600; }
.md :deep(blockquote) { margin: 16px 0; padding: 8px 14px; border-left: 4px solid var(--accent); background: var(--accent-bg); border-radius: 0 8px 8px 0; }
.md :deep(blockquote p) { margin: 4px 0; }
.pn { display: flex; justify-content: space-between; gap: 12px; margin-top: 40px; padding-top: 18px; border-top: 1px solid var(--line); }
.pn a { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; border-radius: 8px; background: var(--surface); text-decoration: none; color: var(--ink); max-width: 48%; }
.pn .next { margin-left: auto; text-align: right; }

/* 资料 */
.docs-index { margin-top: 36px; }
.read .toc .back + .dg { margin-top: 14px; }
.dgroups { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 14px 24px; }
.dg { display: flex; flex-direction: column; gap: 2px; margin-bottom: 10px; }
.dg > span { padding: 0 6px 4px; }
.dg a { padding: 3px 6px; border-radius: 5px; color: var(--ink); text-decoration: none; font-size: 13px; }
.dg a:hover { color: var(--accent); }
.dg a.on { background: var(--surface); font-weight: 600; }
.docmd :deep(table) { display: block; overflow-x: auto; }
.docmd :deep(h1) { font-size: clamp(22px, 3vw, 30px); line-height: 1.25; }

@media (max-width: 860px) {
  .read { grid-template-columns: 1fr; gap: 16px; }
  .toc { position: static; max-height: none; }
  .toc ol { display: none; }
  .hero-txt { padding: 18px 16px; width: 100%; background: linear-gradient(180deg, rgba(23, 33, 43, 0.95) 40%, rgba(23, 33, 43, 0.4) 100%); }
  .hero-flow { padding: 4px 8px 12px; overflow-x: auto; }
  .hero-flow :deep(svg) { min-width: 720px; }
  .index { padding: 0 16px; }
  .line li a { grid-template-columns: 36px 1fr; }
  .tags { display: none; }
}
</style>
