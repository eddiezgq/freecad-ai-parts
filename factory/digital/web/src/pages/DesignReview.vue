<template>
  <div class="page">
    <div class="page-title"><h1>审阅 {{ s?.item }}</h1>
      <router-link to="/design" class="small">← 返回列表</router-link></div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="s" class="row">
      <section class="card grow">
        <div class="card-head">
          <h2>三维模型</h2>
          <span class="pill" :class="TONE[s.status]">{{ STATUS[s.status] }}{{ s.revision ? ' · rev ' + s.revision : '' }}</span>
          <span class="muted small">提交时现行 rev {{ s.base_rev }}</span>
        </div>
        <ModelViewer v-if="glb" :url="glb" :base-url="s.base_glb || ''" :diff-url="diffUrl" :pins="pins"
          :can-pin="s.status === 'pending'" @pick="startPin" />
        <div v-else class="empty">这次提交没有三维模型（只有图纸）。</div>
        <div v-if="s.diff" class="diff small">
          <b>与现行版的差异：</b>
          <span v-if="s.diff.changed === false">几何没有变化。</span>
          <template v-else>
            <span v-if="s.diff.changed_area_mm2 !== undefined">新增或改动的表面 {{ s.diff.changed_area_mm2 }} mm²，去掉的表面 {{ s.diff.removed_area_mm2 }} mm²；</span>
            体积 {{ s.diff.volume_old_mm3 }} → {{ s.diff.volume_new_mm3 }} mm³；外形 {{ (s.diff.size_old_mm || []).join(' × ') }} → {{ (s.diff.size_new_mm || []).join(' × ') }} mm。
          </template>
          <span v-if="s.diff.note" class="muted">{{ s.diff.note }}</span>
        </div>
        <div class="files small">
          <a v-for="f in s.files.filter((x) => ['step', 'drawing'].includes(x.kind))" :key="f.sha256" :href="f.url" target="_blank">{{ f.kind === 'step' ? 'STEP' : '图纸' }} · {{ f.name }}</a>
          <a v-if="s.gcode" :href="s.gcode.url" target="_blank">加工程序（{{ s.gcode.operation.split(' ')[0] }} → {{ s.gcode.machine.toUpperCase() }}）</a>
        </div>
        <div v-if="drawing" class="drawing">
          <img v-if="drawing.name.endsWith('.svg')" :src="drawing.url" alt="零件图">
          <iframe v-else :src="drawing.url" title="零件图"></iframe>
        </div>
      </section>

      <section class="card side">
        <div class="card-head"><h2>提交信息</h2></div>
        <p class="small"><b>{{ s.author }}</b><span v-if="s.mine" class="muted">（我）</span> · {{ timeOf(s.ts) }}</p>
        <p class="small">{{ s.note || '（没有写改动说明）' }}</p>
        <p v-if="s.decided_by" class="small muted">{{ STATUS[s.status] }}：{{ s.decided_by }} · {{ timeOf(s.decided_at) }}{{ s.decision ? ' · ' + s.decision : '' }}</p>

        <div class="card-head"><h2>批注</h2><span class="muted small">{{ openCount }} 条未处理</span></div>
        <div v-if="!s.comments.length" class="empty small">还没有批注。{{ s.status === 'pending' ? '可以在左边选“点处批注”，点模型上的位置写意见。' : '' }}</div>
        <div v-for="(c, i) in s.comments" :key="c.id" class="cm" :class="{ done: c.resolved }">
          <div class="small"><span v-if="c.anchor" class="num-badge" :class="{ done: c.resolved }">{{ i + 1 }}</span><b>{{ c.author }}</b>
            <span class="muted"> · {{ timeOf(c.ts) }}</span></div>
          <div>{{ c.body }}</div>
          <button v-if="s.status === 'pending'" class="btn ghost small" @click="resolve(c)">{{ c.resolved ? '重新打开' : '标为已处理' }}</button>
        </div>
        <form v-if="s.status === 'pending'" class="add" @submit.prevent="addComment">
          <div v-if="anchor" class="small muted">位置：({{ anchor.x.toFixed(1) }}, {{ anchor.y.toFixed(1) }}, {{ anchor.z.toFixed(1) }}) mm
            <a href="#" @click.prevent="anchor = null">不指定位置</a></div>
          <textarea v-model="body" rows="3" maxlength="2000" :placeholder="anchor ? '对这个位置的意见' : '整体意见（也可以在模型上点一处）'"></textarea>
          <button class="btn" :disabled="!body.trim()">添加批注</button>
        </form>

        <template v-if="s.status === 'pending'">
          <div class="card-head"><h2>结论</h2></div>
          <textarea v-model="decision" rows="2" maxlength="500" placeholder="审批意见（退回时必填）"></textarea>
          <div class="line">
            <button v-if="s.can_approve" class="btn primary" :disabled="openCount > 0" :title="openCount ? '还有没处理的批注' : ''" @click="decide('approve')">批准生效</button>
            <button v-if="s.can_approve" class="btn danger" @click="decide('reject')">退回</button>
            <button v-if="s.mine" class="btn ghost" @click="decide('withdraw')">撤回</button>
          </div>
          <p v-if="!s.can_approve && !s.mine" class="small muted">审批要用“审批人”或“厂长”角色（顶栏切换）。</p>
          <p v-if="s.mine" class="small muted">自己的提交不能自己批准，请另一位审批人批准。</p>
        </template>
        <div v-if="msg" :class="msgOk ? 'ok' : 'err'" class="small">{{ msg }}</div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { get, post } from '../lib/api';
import { timeOf } from '../lib/fmt';
import ModelViewer from '../components/ModelViewer.vue';

const STATUS = { pending: '待审', approved: '已生效', rejected: '退回', withdrawn: '撤回' };
const TONE = { pending: 'warn', approved: 'good', rejected: 'bad', withdrawn: '' };
const route = useRoute();
const s = ref(null);
const err = ref('');
const body = ref('');
const anchor = ref(null);
const decision = ref('');
const msg = ref('');
const msgOk = ref(true);

const fileOf = (k) => s.value?.files.find((f) => f.kind === k);
const glb = computed(() => fileOf('glb')?.url || '');
const diffUrl = computed(() => fileOf('diff')?.url || '');
const drawing = computed(() => fileOf('drawing'));
const pins = computed(() => (s.value?.comments || []).map((c, i) => (c.anchor ? { n: i + 1, ...c.anchor, resolved: c.resolved } : null)).filter(Boolean));
const openCount = computed(() => (s.value?.comments || []).filter((c) => !c.resolved).length);

async function load() {
  try { s.value = await get('/plm/submissions/' + route.params.id); } catch (e) { err.value = e.message; }
}
function startPin(p) { anchor.value = p; msg.value = '已选位置，在右边写意见'; msgOk.value = true; }
async function addComment() {
  s.value = await post(`/plm/submissions/${s.value.id}/comments`, { body: body.value, anchor: anchor.value });
  await load(); body.value = ''; anchor.value = null; msg.value = '';
}
async function resolve(c) { await post(`/plm/submissions/${s.value.id}/comments/${c.id}`, { resolved: !c.resolved }); await load(); }
async function decide(d) {
  msg.value = '';
  try {
    await post(`/plm/submissions/${s.value.id}/decision`, { decision: d, note: decision.value });
    await load();
    msgOk.value = true;
    msg.value = { approve: `已批准，生效为 rev ${s.value.revision}；ERPNext 和车间随后更新。`, reject: '已退回提交人。', withdraw: '已撤回。' }[d];
  } catch (e) { msgOk.value = false; msg.value = e.message; }
}
onMounted(load);
</script>

<style scoped>
.grow { flex-grow: 1; min-width: 0; }
.side { width: 380px; flex-shrink: 0; display: flex; flex-direction: column; gap: 8px; }
.diff { margin-top: 10px; background: var(--surface-2); border-radius: 8px; padding: 8px 10px; }
.files { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 8px; }
.drawing { margin-top: 10px; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.drawing img { width: 100%; display: block; }
.drawing iframe { width: 100%; height: 520px; border: 0; }
.cm { border-top: 1px solid var(--line-soft); padding: 8px 0; display: flex; flex-direction: column; gap: 4px; }
.cm.done > div:nth-child(2) { color: var(--muted); text-decoration: line-through; }
.num-badge { background: #e0a100; color: #fff; border-radius: 9px; padding: 0 6px; font-weight: 700; margin-right: 6px; }
.num-badge.done { background: #2e8b57; }
.add, .side textarea { display: flex; flex-direction: column; gap: 6px; }
.side textarea { border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; font: inherit; }
.line { display: flex; gap: 8px; flex-wrap: wrap; }
.ok { color: var(--good); } .err { color: var(--bad); }
.btn.small { height: 26px; font-size: 12px; align-self: flex-start; }
@media (max-width: 1100px) { .side { width: auto; } }
</style>
