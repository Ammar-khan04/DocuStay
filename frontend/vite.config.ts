import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({ mode }) => {
    // Load .env from frontend dir and from project root (so root .env can define VITE_PROXY_TARGET / VITE_API_URL)
    const rootEnv = loadEnv(mode, path.resolve(__dirname, '..'), '');
    const frontendEnv = loadEnv(mode, __dirname, '');
    const env = { ...rootEnv, ...frontendEnv };
    const proxyTarget = env.VITE_PROXY_TARGET || env.VITE_API_URL || process.env.VITE_PROXY_TARGET || process.env.VITE_API_URL || 'http://127.0.0.1:8000';

    return {
      server: {
        port: 3000,
        host: '0.0.0.0',
        proxy: {
          '/api': {
            target: proxyTarget,
            changeOrigin: true,
            rewrite: (p) => p.replace(/^\/api/, ''),
          },
        },
      },
      appType: 'spa',
      plugins: [react(), tailwindcss()],
      resolve: {
        alias: {
          '@': path.resolve(__dirname, '.'),
        }
      }
    };
});