import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// 开发时把 /api 转给枢纽服务（hub）；打包后由 hub 直接提供网页
export default defineConfig({
  plugins: [vue()],
  server: { port: 5180, proxy: { '/api': 'http://localhost:8100' } },
  build: { chunkSizeWarningLimit: 900 },
});
