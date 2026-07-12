import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

export const viteServerConfig = {
  host:'0.0.0.0',
  port: 5173,
  strictPort: true,
  proxy: {
    '/chat': {
      target: 'http://127.0.0.1:8211',
      changeOrigin: true,
      rewrite: (path) => path
    },
    '/static': {
      target: 'http://127.0.0.1:8211',
      changeOrigin: true,
      rewrite: (path) => path
    },
    '/admin': {
      target: 'http://127.0.0.1:8211',
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
