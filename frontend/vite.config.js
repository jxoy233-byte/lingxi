import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// 与后端 .chatme/config.json app.port / frontend/electron/main.js / electron.config.js
// VITE_PROXY_BACKEND 三处保持一致。改值需同步上述三处。
// Vite dev server 端口 18211；与 frontend/electron/electron.config.js devServer.port /
// frontend/package.json wait-on URL 一致。
export const viteServerConfig = {
  host:'0.0.0.0',
  port: 18211,
  strictPort: true,
  proxy: {
    '/chat': {
      target: 'http://127.0.0.1:38211',
      changeOrigin: true,
      rewrite: (path) => path
    },
    '/static': {
      target: 'http://127.0.0.1:38211',
      changeOrigin: true,
      rewrite: (path) => path
    },
    '/admin': {
      target: 'http://127.0.0.1:38211',
      changeOrigin: true,
      rewrite: (path) => path
    }
  },
  allowedHosts: true
}

export const viteBuildConfig = {
  outDir: 'dist',
  emptyOutDir: true
  // 注意：base 选项必须在顶层 defineConfig 里设，这里放无效
}

export const viteResolveConfig = {
  alias: {
    '@': path.resolve(__dirname, './src')
  }
}

// Vite 默认导出
export default defineConfig({
  // base 必须是顶层选项：file:// 加载时要用相对路径才能解析到 ./assets/*
  base: './',
  plugins: [vue()],
  resolve: viteResolveConfig,
  server: viteServerConfig,
  build: viteBuildConfig,
})
