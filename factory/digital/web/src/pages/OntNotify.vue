<!-- 通知设置（第 17 轮 D 期 D6）：我订阅哪些领域、什么严重程度、邮件、免打扰；厂长设置群机器人 -->
<template>
  <div class="page">
    <div class="page-title"><h1>通知设置</h1>
      <span class="muted">厂情中枢主动提醒：新的严重异常、待我批准的动作、日报周报。站内铃铛总能收到；生产模式下还可以发邮件和群消息</span></div>
    <div v-if="err" class="err">{{ err }}</div>
    <template v-if="d">
      <section class="card">
        <div class="card-head"><h2>我的订阅</h2><span class="small muted">{{ d.sub.custom ? '已自定义' : '现在用的是按角色的默认订阅' }}</span></div>
        <div class="field"><label>领域</label>
          <label class="ck"><input v-model="all" type="checkbox"> 全部领域</label>
          <div v-if="!all" class="doms">
            <label v-for="x in d.domains" :key="x.domain" class="ck"><input v-model="form.domains" type="checkbox" :value="x.domain"> {{ x.label }}</label>
          </div></div>
        <div class="field"><label>最低严重程度</label>
          <select v-model="form.min_severity"><option v-for="(l, k) in d.severities" :key="k" :value="k">{{ l }}及以上</option></select></div>
        <div class="field"><label>邮件</label>
          <label class="ck"><input v-model="form.email_on" type="checkbox" :disabled="!d.external"> 同时发邮件到</label>
          <input v-model="form.email" type="email" placeholder="you@example.com" :disabled="!d.external">
          <span class="small muted">{{ !d.external ? '教学模式只发站内通知' : d.smtp ? '' : '服务器还没配发信（SMTP），配好之前邮件发不出去' }}</span></div>
        <div class="field"><label>免打扰</label>
          <label class="ck"><input v-model="form.quiet_on" type="checkbox"> 从</label>
          <input v-model="form.q_from" type="time" :disabled="!form.quiet_on"> 到 <input v-model="form.q_to" type="time" :disabled="!form.quiet_on">
          <span class="small muted">只挡邮件和群消息；“严重”的照发</span></div>
        <div class="row"><button class="btn primary" @click="save">保存</button>
          <button class="btn" @click="test">发一条测试通知</button><span class="small ok">{{ msg }}</span></div>
      </section>

      <section v-if="d.can_channels" class="card">
        <div class="card-head"><h2>群机器人</h2><span class="small muted">把厂情提醒和日报周报推到企业微信、钉钉或飞书群（生产模式）。可以按领域分到不同的群</span></div>
        <table v-if="d.channels.length" class="tbl small">
          <thead><tr><th>名称</th><th>种类</th><th>领域</th><th>最低严重程度</th><th>地址</th><th>添加人</th><th></th></tr></thead>
          <tbody><tr v-for="c in d.channels" :key="c.id"><td>{{ c.name }}</td><td>{{ d.channel_kinds[c.kind] }}</td>
            <td>{{ c.domain ? domLabel(c.domain) : '全部' }}</td><td>{{ d.severities[c.min_severity] }}</td><td class="mono">…{{ c.tail }}</td>
            <td>{{ c.created_by }}</td><td><button class="linkbtn" @click="del(c.id)">删除</button></td></tr></tbody>
        </table>
        <p v-else class="small muted">还没有群机器人。</p>
        <div class="add">
          <select v-model="ch.kind"><option v-for="(l, k) in d.channel_kinds" :key="k" :value="k">{{ l }}</option></select>
          <input v-model="ch.name" placeholder="名称，例如：车间管理群">
          <select v-model="ch.domain"><option value="">全部领域</option><option v-for="x in d.domains" :key="x.domain" :value="x.domain">{{ x.label }}</option></select>
          <select v-model="ch.min_severity"><option v-for="(l, k) in d.severities" :key="k" :value="k">{{ l }}及以上</option></select>
          <input v-model="ch.url" class="url" placeholder="Webhook 地址（https://…）">
          <button class="btn" @click="add">添加</button>
        </div>
        <p class="small muted">在群里：设置 → 群机器人 → 添加机器人 → 复制 Webhook 地址，贴到这里。地址加密保存，页面只显示最后 4 位。</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { api, get, post } from '../lib/api';

const httpDel = (p) => api('DELETE', p);

const d = ref(null);
const err = ref('');
const msg = ref('');
const all = ref(true);
const form = reactive({ domains: [], min_severity: 'warn', email: '', email_on: false, quiet_on: false, q_from: '22:00', q_to: '07:00' });
const ch = reactive({ kind: 'wecom', name: '', domain: '', min_severity: 'warn', url: '' });

function fill(x) {
  d.value = x;
  const s = x.sub;
  all.value = s.domains === null;
  form.domains = s.domains ? [...s.domains] : [];
  form.min_severity = s.min_severity;
  form.email = s.email || '';
  form.email_on = !!(s.channels || {}).email;
  form.quiet_on = !!s.quiet;
  if (s.quiet) { form.q_from = s.quiet.from; form.q_to = s.quiet.to; }
}
function domLabel(k) { return d.value.domains.find((x) => x.domain === k)?.label || k; }
async function load() { try { fill(await get('/notifications/subs')); } catch (e) { err.value = e.message; } }
async function save() {
  try {
    fill(await post('/notifications/subs', { domains: all.value ? null : form.domains, min_severity: form.min_severity, email: form.email,
      channels: { email: form.email_on }, quiet: form.quiet_on ? { from: form.q_from, to: form.q_to } : null }));
    msg.value = '已保存';
  } catch (e) { alert(e.message); }
}
async function test() {
  try {
    const r = await post('/notifications/test', {});
    const g = r.groups.map((x) => `${x.name}${x.ok ? ' ✓' : ' ✗'}`).join('、');
    msg.value = '已发：站内铃铛' + (r.email === null ? '' : r.email ? '、邮件 ✓' : '、邮件 ✗') + (g ? '、群：' + g : '');
  } catch (e) { alert(e.message); }
}
async function add() { try { fill(await post('/notifications/channels', { ...ch })); ch.url = ''; ch.name = ''; } catch (e) { alert(e.message); } }
async function del(id) { if (confirm('删除这个群机器人？')) { try { fill(await httpDel('/notifications/channels/' + id)); } catch (e) { alert(e.message); } } }
onMounted(load);
</script>

<style scoped>
.field { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 10px 0; }
.field > label:first-child { width: 110px; font-weight: 500; }
.ck { display: inline-flex; gap: 4px; align-items: center; font-size: 13px; }
.doms { display: flex; flex-wrap: wrap; gap: 6px 12px; flex-basis: 100%; padding-left: 120px; }
input, select { height: 30px; border: 1px solid var(--line); border-radius: 6px; padding: 0 8px; }
.row { display: flex; gap: 10px; align-items: center; margin-top: 12px; }
.add { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
.add .url { flex: 1 1 260px; min-width: 0; }
.linkbtn { border: none; background: none; color: var(--accent); cursor: pointer; font-size: 12px; }
.ok { color: var(--good); }
@media (max-width: 700px) { .doms { padding-left: 0; } }
</style>
