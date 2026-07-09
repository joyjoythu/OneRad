import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'Home', component: () => import('@/views/HomeView.vue') },
  { path: '/agent', name: 'Agent', component: () => import('@/views/AgentView.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
