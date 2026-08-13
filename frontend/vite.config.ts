import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// Ports are configurable via env so this app can run alongside AITrader-1
// (which uses 5174 / 8001) without colliding. Defaults: 5173 / 8000.
//   VITE_PORT=5175 VITE_API_TARGET=http://localhost:8001 npm run dev
const port = Number(process.env.VITE_PORT) || 5173;
const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8000';

// Read the root .env (single source of truth). The API auth token lives there
// as API_AUTH_TOKEN and is injected into the client build as VITE_API_TOKEN so
// the frontend can authenticate every request against the backend.
const rootEnv = loadEnv('', path.resolve(__dirname, '..'), '');
const apiToken = (rootEnv.API_AUTH_TOKEN || '').trim();

export default defineConfig({
  define: {
    'import.meta.env.VITE_API_TOKEN': JSON.stringify(apiToken),
  },
  plugins: [
    react(),
    tailwindcss()
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  server: {
    port,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        ws: true,
        proxyTimeout: 300000,  // 5 min — code gen can take 60-90s
        timeout: 300000,       // 5 min socket timeout
        configure: (proxy, _options) => {
          proxy.on('error', (err, _req, _res) => {
            console.log('proxy error:', err);
          });
        }
      }
    }
  }
})