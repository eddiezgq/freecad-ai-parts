// 帮助里的机制动画（ADR-0065）：名字 → 组件。新动画在这里登记，帮助正文用 ```anim name: 名字```。
import { defineAsyncComponent } from 'vue';

export const ANIMS = {
  flow: defineAsyncComponent(() => import('./FlowAnim.vue')),
  terminal: defineAsyncComponent(() => import('./TerminalAnim.vue')),
  mrp: defineAsyncComponent(() => import('./MrpAnim.vue')),
  workorder: defineAsyncComponent(() => import('./WorkOrderAnim.vue')),
  causal: defineAsyncComponent(() => import('./CausalAnim.vue')),
  'ai-draft': defineAsyncComponent(() => import('./AiDraftAnim.vue')),
};
