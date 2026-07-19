import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  // 必须用 hash 模式：file:// 加载 + reload 不存在 dev server 兜底，
  // history 模式会把 URL 变成 file:///.../dist/<sid>，刷新时 Electron 静态白名单
  // 找不到 <sid> 文件直接返回 404 错误页。hash 模式下 URL 是
  // file:///.../dist/index.html#/<sid>，reload 永远先拿 index.html，
  // Vue 启动后从 hash 读出 sid 恢复会话。
  history: createWebHashHistory(),
  routes: [
    {
      path: '/:sessionId?',
      name: 'chat',
      component: () => import('../App.vue')
    }
  ]
})

export default router
