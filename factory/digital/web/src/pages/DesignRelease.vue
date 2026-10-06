<template>
  <div class="page">
    <div class="page-title"><h1>设计发布与审批</h1>
      <span class="muted">任何 CAD 画的零件：上传 STEP（可带图纸、加工程序）→ {{ prod ? '审批人看图、批注、批准后生效' : '教学模式提交即生效' }}</span></div>

    <div class="row">
      <section class="card side">
        <div class="card-head"><h2>提交新版本</h2></div>
        <form class="form" @submit.prevent="submit">
          <label>物料编号 <input v-model.trim="item" placeholder="例如 SH-301、CAP-52-T" required @change="lookup"></label>
          <div v-if="info" class="small ok">{{ info.name }} · 现行 rev {{ info.revision }}</div>
          <div v-if="infoErr" class="small err">{{ infoErr }}</div>
          <label>三维模型（STEP） <input type="file" accept=".step,.stp,.STEP,.STP" @change="pick('step', $event)"></label>
          <label>图纸（PDF 或 SVG，可选） <input type="file" accept=".pdf,.svg" @change="pick('drawing', $event)"></label>
          <label>加工程序（G 代码，可选） <input type="file" accept=".nc,.gcode,.ngc,.txt,.tap" @change="pick('gcode', $event)"></label>
          <label v-if="files.gcode">用于哪道工序
            <select v-model="operation" required><option value="" disabled>选择工序</option><option v-for="o in info?.operations || []" :key="o" :value="o">{{ o }}</option></select>
          </label>
          <label>改动说明 <textarea v-model="note" rows="3" maxlength="500" placeholder="改了什么、为什么改"></textarea></label>
          <button class="btn primary" :disabled="busy || !info || (!files.step && !files.drawing)">{{ busy ? '正在上传并生成网页模型…' : (prod ? '提交审批' : '发布') }}</button>
          <div v-if="msg" :class="msgOk ? 'ok' : 'err'" class="small">{{ msg }}</div>
        </form>
        <p class="small muted">用 FreeCAD、SolidWorks、中望等任何 CAD 都可以：导出 STEP 后在这里上传。FreeCAD 用户也可以在“设计与工艺”页下载宏包，在 FreeCAD 里一键提交。</p>
      </section>

      <section class="card grow">
        <div class="card-head"><h2>{{ prod ? '待审与已处理' : '发布记录' }}</h2>
          <div class="seg"><button v-for="t in tabs" :key="t.k" type="button" :class="{ on: tab === t.k }" @click="tab = t.k; load()">{{ t.label }}</button></div></div>
        <div v-if="!rows.length" class="empty">{{ tab === 'pending' ? '没有待审的提交。' : '还没有记录。' }}</div>
        <table v-else class="t">
          <thead><tr><th>物料</th><th>状态</th><th>提交人</th><th>时间</th><th>说明</th><th class="num">未处理批注</th><th></th></tr></thead>
          <tbody><tr v-for="r in rows" :key="r.id">
            <td class="mono b">{{ r.item }}</td>
            <td><span class="pill" :class="TONE[r.status]">{{ STATUS[r.status] }}{{ r.revision ? ' rev ' + r.revision : '' }}</span></td>
            <td>{{ r.author }}<span v-if="r.mine" class="muted small">（我）</span></td>
            <td class="small">{{ timeOf(r.ts) }}</td>
            <td class="small">{{ r.note || '—' }}</td>
            <td class="num">{{ r.open_comments || '' }}</td>
            <td><router-link :to="'/design/' + r.id">{{ r.status === 'pending' && prod ? '看图审阅 →' : '查看 →' }}</router-link></td>
          </tr></tbody>
        </table>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { get, session } from '../lib/api';
import { timeOf } from '../lib/fmt';

const STATUS = { pending: '待审', approved: '已生效', rejected: '退回', withdrawn: '撤回' };
const TONE = { pending: 'warn', approved: 'good', rejected: 'bad', withdrawn: '' };
const router = useRouter();
const prod = computed(() => session.user?.mode === 'prod');
const tabs = computed(() => (prod.value ? [{ k: 'pending', label: '待审' }, { k: '', label: '全部' }] : [{ k: '', label: '全部' }]));
const tab = ref(prod.value ? 'pending' : '');
const rows = ref([]);
const item = ref('');
const info = ref(null);
const infoErr = ref('');
const files = ref({});
const operation = ref('');
const note = ref('');
const busy = ref(false);
const msg = ref('');
const msgOk = ref(true);

async function load() { rows.value = await get('/plm/submissions' + (tab.value ? '?status=' + tab.value : '')); }
async function lookup() {
  info.value = null; infoErr.value = '';
  if (!item.value) return;
  try { info.value = await get('/plm/item/' + encodeURIComponent(item.value)); } catch (e) { infoErr.value = e.message; }
}
function pick(k, ev) { files.value = { ...files.value, [k]: ev.target.files[0] || null }; }
async function submit() {
  busy.value = true; msg.value = '';
  const fd = new FormData();
  fd.append('item', item.value); fd.append('note', note.value); fd.append('operation', operation.value);
  for (const [k, f] of Object.entries(files.value)) if (f) fd.append(k, f);
  try {
    const r = await fetch('/api/plm/submit', { method: 'POST', headers: { 'x-wq-token': session.token }, body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || '提交失败（' + r.status + '）');
    msgOk.value = true;
    msg.value = d.status === 'approved' ? `已发布 rev ${d.revision}` : '已提交，等待审批';
    router.push('/design/' + d.id);
  } catch (e) { msgOk.value = false; msg.value = e.message; } finally { busy.value = false; }
}
onMounted(load);
</script>

<style scoped>
.grow { flex-grow: 1; min-width: 0; }
.side { width: 360px; flex-shrink: 0; }
.form { display: flex; flex-direction: column; gap: 10px; }
.form label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.form input[type=text], .form input:not([type]), .form select, .form textarea { border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; font: inherit; }
.b { font-weight: 600; }
.ok { color: var(--good); } .err { color: var(--bad); }
.seg { margin-left: auto; display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
.seg button { border: 0; background: #fff; padding: 5px 10px; cursor: pointer; font-size: 13px; }
.seg button.on { background: var(--accent-bg); font-weight: 600; }
@media (max-width: 1100px) { .side { width: auto; } }
</style>
