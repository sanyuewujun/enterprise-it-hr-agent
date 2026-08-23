import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// 开发时把 /api 代理到后端（默认 8000），生产构建由 FastAPI 托管 dist
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            '/api': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
        },
    },
});
