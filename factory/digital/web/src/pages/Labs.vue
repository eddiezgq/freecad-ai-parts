<!-- 实验与任务（第 19 轮 J-8）：一个入口列出实验 7、15–23，每个写领域、学时、我的得分；进去还是原来的实验页。手机宽度可用 -->
<template>
  <div class="page">
    <div class="page-title"><h1>实验与任务</h1>
      <span class="muted">每个实验平台自动评一部分分数，报告由老师在课程里批改</span>
      <span class="r small"><router-link to="/help/teach/labs">帮助</router-link><template v-if="d?.teacher"> · <router-link to="/director">情景导演</router-link></template></span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <p v-if="d && d.mode !== 'teach'" class="card empty">实验只在教学模式出现。右上角切到“教学模式”。</p>
    <div v-if="d && d.mode === 'teach'" class="grid" data-help="labs-grid">
      <router-link v-for="l in d.labs" :key="l.no" :to="l.path" class="card lab" :class="{ done: l.done === l.tasks, started: l.started }">
        <div class="lh"><b class="no">实验 {{ l.no }}</b><span class="dom small">{{ l.domain }}</span></div>
        <h2>{{ l.title }}</h2>
        <p class="small muted">{{ typeof l.hours === 'number' ? l.hours + ' 学时' : l.hours }} · {{ l.tasks }} 个任务{{ l.team ? ' · 4–6 人一组' : '' }}</p>
        <p class="sc"><b>{{ l.score }}</b> / {{ l.of }}<span class="small muted">（自动评）+ 报告 {{ l.report_points || '—' }}</span>
          <span class="small st">{{ l.done === l.tasks ? '✓ 全部完成' : (l.started ? '做到第 ' + (l.done + 1) + ' 个任务' : '还没开始') }}</span></p>
        <a v-if="l.guide" class="small" :href="l.guide" @click.stop>指导书</a>
      </router-link>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import { get } from '../lib/api';

const d = ref(null);
const err = ref('');
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
