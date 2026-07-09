import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const HomePlaceholder = {
  template: '<div class="placeholder">Select a project</div>',
}

const AgentPlaceholder = {
  template: '<div class="placeholder">Agent workspace placeholder</div>',
}

const routes: RouteRecordRaw[] = [
  { path: '/', component: HomePlaceholder },
  { path: '/agent', component: AgentPlaceholder },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
