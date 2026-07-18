<template>
  <div class="onerad-app">
    <header class="app-header">
      <h1>OneRad</h1>
      <nav class="app-nav">
        <router-link to="/" exact-active-class="active">Agent</router-link>
        <router-link to="/settings" exact-active-class="active">设置</router-link>
      </nav>
    </header>
    <div class="app-body">
      <aside class="app-sidebar" :class="{ 'app-sidebar--collapsed': isSidebarCollapsed }">
        <div class="sidebar-toggle-bar">
          <el-button
            link
            size="small"
            :icon="isSidebarCollapsed ? Expand : Fold"
            :aria-label="isSidebarCollapsed ? '展开项目面板' : '折叠项目面板'"
            data-testid="sidebar-toggle-collapse"
            @click="handleToggleSidebar"
          />
        </div>
        <ProjectList v-show="!isSidebarCollapsed" />
      </aside>
      <main class="app-main">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Expand, Fold } from '@element-plus/icons-vue'
import ProjectList from '@/components/ProjectList.vue'

const SIDEBAR_COLLAPSED_KEY = 'onerad:app:sidebarCollapsed'

function loadSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}

function saveSidebarCollapsed(value: boolean): void {
  try {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(value))
  } catch {
    // ignore
  }
}

const isSidebarCollapsed = ref(loadSidebarCollapsed())

function handleToggleSidebar(): void {
  isSidebarCollapsed.value = !isSidebarCollapsed.value
  saveSidebarCollapsed(isSidebarCollapsed.value)
}
</script>

<style scoped>
.onerad-app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background-color: var(--app-bg);
  color: var(--app-text);
}

.app-header {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 0.75rem 1.5rem;
  border-bottom: 1px solid var(--app-border);
  background-color: var(--app-bg);
}

.app-header h1 {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--app-text);
}

.app-nav {
  display: flex;
  gap: 1rem;
}

.app-nav a {
  color: var(--app-text-secondary);
  text-decoration: none;
  font-size: 0.9375rem;
  padding: 0.25rem 0;
  border-bottom: 2px solid transparent;
  transition: color 0.2s, border-color 0.2s;
}

.app-nav a:hover {
  color: var(--app-text);
}

.app-nav a.active {
  color: var(--app-text);
  border-bottom-color: var(--app-accent);
}

.app-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.app-sidebar {
  width: 320px;
  border-right: 1px solid var(--app-border);
  background-color: var(--app-bg-panel);
  overflow-y: auto;
  transition: width 0.2s ease;
}

.sidebar-toggle-bar {
  display: flex;
  justify-content: flex-end;
  padding: 0.25rem 0.5rem;
}

.app-sidebar--collapsed {
  width: 40px;
}

.app-sidebar--collapsed .sidebar-toggle-bar {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}

.app-main {
  flex: 1;
  padding: 1.25rem 1.5rem;
  overflow-y: auto;
}
</style>
