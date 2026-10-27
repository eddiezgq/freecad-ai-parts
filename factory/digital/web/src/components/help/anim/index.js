// 帮助里的机制动画（ADR-0065）：名字 → 组件。新动画在这里登记，帮助正文用 ```anim name: 名字```。
import { defineAsyncComponent } from 'vue';

export const ANIMS = {
  flow: defineAsyncComponent(() => import('./FlowAnim.vue')),
  terminal: defineAsyncComponent(() => import('./TerminalAnim.vue')),
  mrp: defineAsyncComponent(() => import('./MrpAnim.vue')),
  workorder: defineAsyncComponent(() => import('./WorkOrderAnim.vue')),
  causal: defineAsyncComponent(() => import('./CausalAnim.vue')),
  'ai-draft': defineAsyncComponent(() => import('./AiDraftAnim.vue')),
  // 第 30 轮 §八 8-2：各领域的机制动画
  recall: defineAsyncComponent(() => import('./RecallAnim.vue')),
  inspect: defineAsyncComponent(() => import('./InspectAnim.vue')),
  shift: defineAsyncComponent(() => import('./ShiftAnim.vue')),
  risk: defineAsyncComponent(() => import('./RiskAnim.vue')),
  'energy-day': defineAsyncComponent(() => import('./EnergyDayAnim.vue')),
  spc: defineAsyncComponent(() => import('./SpcAnim.vue')),
  // 第 45 轮：机器人厂
  'bom-tree': defineAsyncComponent(() => import('./BomTreeAnim.vue')),
  'joint-test': defineAsyncComponent(() => import('./JointTestAnim.vue')),
};
