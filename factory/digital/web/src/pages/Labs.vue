<!-- 实验与任务（第 19 轮 J-8）：一个入口列出实验 7、15–23，每个写领域、学时、我的得分；进去还是原来的实验页。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>{{ $t('实验与任务') }}</h1>
      <span class="muted">{{ $t('每个实验平台自动评一部分分数，报告由老师在课程里批改') }}</span>
      <span class="r small"><router-link :to="robot ? '/help/robot/labs' : '/help/teach/labs'">{{ $t('帮助') }}</router-link><template v-if="d?.teacher && !robot"> · <router-link to="/director">{{ $t('情景导演') }}</router-link></template></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <p v-if="d && d.mode !== 'teach'" class="card empty">{{ $t('实验只在教学模式出现。右上角切到“教学模式”。') }}</p>
    <div v-if="d && d.mode === 'teach'" class="grid" data-help="labs-grid">
      <router-link v-for="l in d.labs" :key="l.no" :to="l.path" class="card lab" :class="{ done: l.done === l.tasks, started: l.started }">
        <div class="lh"><b class="no">{{ $t('实验 {a}', { a: $td(l.no) }) }}</b><span class="dom small">{{ $td(l.domain) }}</span></div>
        <h2>{{ $td(l.title) }}</h2>
        <p class="small muted">{{ $t('{a} · {b} 个任务{c}', { a: typeof l.hours === 'number' ? $td(l.hours) + $t(' 学时') : $td(l.hours), b: $td(l.tasks), c: l.team ? $t(' · 4–6 人一组') : '' }) }}</p>
        <p class="sc"><b>{{ $td(l.score) }}</b> / {{ $td(l.of) }}<span class="small muted">{{ $t('（自动评）+ 报告 {a}', { a: l.report_points || '—' }) }}</span>
          <span class="small st">{{ l.done === l.tasks ? $t('✓ 全部完成') : (l.started ? $t('做到第 ') + (l.done + 1) + $t(' 个任务') : $t('还没开始')) }}</span></p>
        <span class="small"><a v-if="l.guide" :href="l.guide" @click.stop>{{ $t('指导书') }}</a><template v-if="l.template"> · <a :href="l.template" @click.stop>{{ $t('报告模板') }}</a></template></span>
      </router-link>
    </div>
  </div>
</template>

<script setup>
import { t as $t } from '../lib/i18n';
import { computed, onMounted, ref } from 'vue';
import { get } from '../lib/api';

const d = ref(null);
const err = ref('');
const robot = computed(() => !!d.value?.labs?.some((l) => l.plant));          // 机器人厂的实验 24、25（第 47 轮）
onMounted(async () => { try { d.value = await get('/labs'); } catch (e) { err.value = e.message; } });
</script>

<style scoped>
.page-title { flex-wrap: wrap; }
.r { margin-left: auto; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.lab { display: flex; flex-direction: column; gap: 4px; color: inherit; text-decoration: none; border-left: 4px solid var(--line); }
.lab:hover { box-shadow: 0 1px 6px rgba(0, 0, 0, .1); }
.lab.started { border-left-color: var(--warn); }
.lab.done { border-left-color: var(--good); }
.lh { display: flex; gap: 8px; align-items: center; }
.dom { background: var(--surface-2); border-radius: 10px; padding: 1px 8px; }
.lab h2 { margin: 2px 0; font-size: 16px; }
.sc { margin: 4px 0; display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
.sc b { font-size: 20px; }
.st { margin-left: auto; }
</style>
