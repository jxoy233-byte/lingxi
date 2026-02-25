import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/:sessionId?',
      name: 'chat',
      component: () => import('../App.vue')
    }
  ]
})

export default router
