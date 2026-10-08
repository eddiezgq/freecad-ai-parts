<template>
  <figure class="term" :aria-label="'命令行演示：' + title">
    <div class="bar"><i></i><i></i><i></i><span>{{ title }}</span>
      <button class="again" @click="play">重放</button></div>
    <pre ref="pre"><template v-for="(l, i) in shown" :key="i"><span :class="l.cls">{{ l.text }}</span>
</template><span v-if="typing" class="cur">▍</span></pre>
  </figure>
</template>

<script setup>
// 终端动画（ADR-0065）：以 “$ ” 开头的行逐字打出来（命令），其余行一次出现（输出）。企业版的安装、升级、备份用它。
import { onMounted, onUnmounted, ref } from 'vue';

const props = defineProps({ args: { type: Object, default: () => ({}) } });
const title = props.args.title || '服务器终端';
const lines = (props.args._body || '').split('\n').filter((l) => !/^\s*(name|title|caption)\s*:/.test(l));
const shown = ref([]);
const typing = ref(false);
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
let timer, gen = 0;

function cls(l) { return l.startsWith('$ ') ? 'cmd' : /出错|失败|错误|处错/.test(l) || /^\s+- /.test(l) ? 'bad' : /完成|无误|已/.test(l) ? 'ok' : 'out'; }
function play() {
  const g = ++gen;
  clearTimeout(timer);
  if (reduced) { shown.value = lines.map((l) => ({ text: l, cls: cls(l) })); return; }
  shown.value = [];
  let i = 0;
  const step = () => {
    if (g !== gen || i >= lines.length) { typing.value = false; return; }
    const l = lines[i++];
    if (l.startsWith('$ ')) {
      typing.value = true;
      const row = { text: '', cls: 'cmd' };
      shown.value.push(row);
      let k = 0;
      const type = () => {
        if (g !== gen) return;
        row.text = l.slice(0, ++k);
        shown.value = [...shown.value];
        timer = setTimeout(k < l.length ? type : step, k < l.length ? 28 : 500);
      };
      type();
    } else {
      shown.value.push({ text: l, cls: cls(l) });
      timer = setTimeout(step, 180);
    }
  };
  step();
}
onMounted(play);
onUnmounted(() => { gen++; clearTimeout(timer); });
</script>

<style scoped>
.term { margin: 16px 0; border-radius: 10px; overflow: hidden; background: #17212B; }
.bar { display: flex; align-items: center; gap: 6px; padding: 8px 12px; background: #22303C; color: #A9B5BF; font-size: 12px; }
.bar i { width: 10px; height: 10px; border-radius: 50%; background: #34485A; }
.bar span { margin-left: 8px; }
.again { margin-left: auto; background: none; border: 1px solid #34485A; color: #C9D3DA; border-radius: 6px; padding: 2px 8px; cursor: pointer; }
pre { margin: 0; padding: 14px 16px; min-height: 120px; font-family: var(--mono); font-size: 13px; line-height: 1.6; color: #C9D3DA;
  white-space: pre; overflow-x: auto; }
.cmd { color: #F4F6F3; }
.ok { color: #7CCB9B; }
.bad { color: #F08A80; }
.cur { color: var(--brand); animation: blink 1s steps(1) infinite; }
@keyframes blink { 50% { opacity: 0; } }
</style>
