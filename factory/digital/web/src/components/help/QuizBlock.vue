<template>
  <!-- 你来选（第 30 轮 §八 H-11 第 4 种）：情景小题，选完显示对错和道理，选错链回讲这件事的那一段 -->
  <div class="hb quiz" role="group" :aria-label="'你来选：' + args.q">
    <p class="q"><span class="badge small">你来选</span>{{ args.q }}</p>
    <div class="opts">
      <button v-for="(o, i) in opts" :key="i" class="opt" :class="cls(i)" :disabled="picked !== null" :aria-pressed="picked === i"
        @click="picked = i">
        <span class="mark" aria-hidden="true">{{ picked === null ? String.fromCharCode(65 + i) : o.right ? '✓' : picked === i ? '✗' : '' }}</span>
        <span class="ot">{{ o.text }}<span v-if="picked !== null && o.why" class="why small">{{ o.why }}</span></span>
      </button>
    </div>
    <div v-if="picked !== null" class="verdict" role="status" aria-live="polite">
      <b :class="opts[picked].right ? 'good' : 'bad'">{{ opts[picked].right ? '选对了。' : '再想想。' }}</b>
      <span class="acts small">
        <router-link v-if="more && !opts[picked].right" :to="more">回到“{{ moreText }}”那一段看看 →</router-link>
        <router-link v-else-if="more" :to="more">道理在“{{ moreText }}”那一段 →</router-link>
        <button class="link" @click="picked = null">再选一次</button>
      </span>
    </div>
  </div>
</template>

<script setup>
// 块的写法：options 每项“文字 | right 或 wrong | 道理”；more 写“章节文件名#小节标题”（如 11-maint#保养：从异常到验收解锁），
// 同一章写“#小节标题”。纯前端，不记分。
import { computed, ref } from 'vue';
import { useRoute } from 'vue-router';

const props = defineProps({ args: { type: Object, default: () => ({}) } });
const route = useRoute();
const picked = ref(null);

function parseOption(s) {
  const [text, verdict, ...why] = String(s).split('|').map((x) => x.trim());
  return { text, right: /^(right|对|✓)$/i.test(verdict || ''), why: why.join(' | ') };
}
const opts = computed(() => (Array.isArray(props.args.options) ? props.args.options : []).map(parseOption));
const moreText = computed(() => decodeURIComponent((props.args.more || '').split('#')[1] || ''));
const more = computed(() => {
  const m = props.args.more;
  if (!m) return '';
  const [file, sec] = m.split('#');
  const ed = route.params.ed || 'teach';
  const slug = file ? file.replace(/\.md$/, '').replace(/^\d+-/, '') : route.params.ch;
  return `/help/${ed}/${slug}${sec ? '#' + encodeURIComponent(sec) : ''}`;
});
function cls(i) {
  if (picked.value === null) return '';
  const o = opts.value[i];
  return { right: o.right, wrong: !o.right && picked.value === i, dim: !o.right && picked.value !== i };
}
</script>

<style scoped>
.quiz { margin: 18px 0; padding: 14px 16px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); }
.q { margin: 0 0 10px; font-weight: 600; line-height: 1.6; }
.badge { display: inline-block; margin-right: 8px; padding: 1px 8px; border-radius: 999px; background: var(--task-bg); color: var(--task-ink);
  font-weight: 600; vertical-align: 1px; }
.opts { display: flex; flex-direction: column; gap: 6px; }
.opt { display: flex; gap: 10px; align-items: flex-start; text-align: left; padding: 9px 12px; border-radius: 8px; border: 1px solid var(--line);
  background: var(--surface-2); color: var(--ink); font: inherit; font-size: 15px; cursor: pointer; }
.opt:hover:not(:disabled) { border-color: var(--accent); }
.opt:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
.opt:disabled { cursor: default; }
.mark { flex: none; width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; font-size: 12px; font-weight: 700;
  background: var(--surface); border: 1px solid var(--line); }
.ot { display: flex; flex-direction: column; gap: 2px; }
.why { color: var(--muted); }
.opt.right { border-color: var(--good); background: var(--good-bg); }
.opt.right .mark { background: var(--good); color: #fff; border-color: var(--good); }
.opt.wrong { border-color: var(--bad); background: var(--bad-bg); }
.opt.wrong .mark { background: var(--bad); color: #fff; border-color: var(--bad); }
.opt.dim { opacity: 0.7; }
.verdict { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; }
.good { color: var(--good); } .bad { color: var(--bad); }
.acts { display: flex; gap: 12px; width: 100%; }
.link { background: none; border: 0; padding: 0; color: var(--muted); cursor: pointer; font: inherit; text-decoration: underline; }
</style>
