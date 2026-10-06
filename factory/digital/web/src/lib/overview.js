// 首页数据：每 5 秒从历史库取一次汇总；设备状态再用总线实时消息覆盖（更快）
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { get } from './api';
import { bus } from './bus';

export function useOverview(every = 5000) {
  const ov = ref(null);
  const error = ref(null);
  let timer;
  async function load() {
    try {
      ov.value = await get('/overview');
      error.value = null;
    } catch (e) {
      error.value = e.message;
    }
  }
  onMounted(() => { load(); timer = setInterval(load, every); });
  onUnmounted(() => clearInterval(timer));
  const machines = computed(() => (ov.value?.machines || []).map((m) => {
    const live = bus.machines[m.unit];
    if (live && (!m.ts || live.ts >= m.ts)) {
      return { ...m, ...live, code: m.code, name: m.name, bottleneck: m.bottleneck, unit: m.unit };
    }
    return m;
  }));
  return { ov, error, load, machines };
}
