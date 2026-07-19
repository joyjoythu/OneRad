<template>
  <div class="onerad-app">
    <header class="app-header">
      <div class="app-brand" aria-label="OneRad">
        <span class="app-brand__mark" aria-hidden="true">R</span>
        <h1>OneRad</h1>
      </div>
      <nav class="app-nav">
        <router-link to="/" exact-active-class="active">Agent</router-link>
        <router-link to="/settings" exact-active-class="active">设置</router-link>
      </nav>
    </header>
    <div class="app-body">
      <aside
        v-auto-hide-scrollbar
        class="app-sidebar auto-hide-scrollbar"
        :class="{ 'app-sidebar--collapsed': isSidebarCollapsed }"
      >
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
        <ProjectTree v-show="!isSidebarCollapsed" />
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
import ProjectTree from '@/components/ProjectTree.vue'
import { vAutoHideScrollbar } from '@/directives/autoHideScrollbar'

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
  height: 100dvh;
  min-height: 0;
  background-color: var(--app-bg);
  color: var(--app-text);
}

.app-header {
  display: flex;
  align-items: center;
  min-height: 58px;
  flex: 0 0 auto;
  gap: 1.75rem;
  padding: 0.625rem 1.25rem;
  border-bottom: 1px solid var(--app-border);
  background-color: color-mix(in srgb, var(--app-bg-panel) 94%, transparent);
  box-shadow: 0 1px 0 rgba(22, 119, 255, 0.03);
}

.app-brand {
  display: inline-flex;
  align-items: center;
  gap: 0.625rem;
}

.app-brand__mark {
  display: inline-grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 10px;
  background: linear-gradient(145deg, var(--app-accent-hover), var(--app-accent-active));
  box-shadow: 0 6px 16px var(--app-focus-ring);
  color: #ffffff;
  font-size: 1rem;
  font-weight: 750;
}

.app-header h1 {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--app-accent-active);
}

.app-nav {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.app-nav a {
  color: var(--app-text-secondary);
  text-decoration: none;
  font-size: 0.9375rem;
  min-height: 36px;
  padding: 0.5rem 0.75rem;
  border: 1px solid transparent;
  border-radius: var(--app-radius-md);
  transition: color 0.16s ease, background-color 0.16s ease,
    border-color 0.16s ease;
}

.app-nav a:hover {
  background: var(--app-bg-hover);
  color: var(--app-accent-active);
}

.app-nav a:focus-visible {
  outline: 3px solid var(--app-focus-ring);
  outline-offset: 1px;
}

.app-nav a.active {
  border-color: var(--app-border);
  background: var(--app-sidebar-active);
  color: var(--app-accent-active);
  font-weight: 600;
}

.app-body {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.app-sidebar {
  width: 288px;
  min-height: 0;
  flex: 0 0 auto;
  border-right: 1px solid var(--app-border);
  background-color: var(--app-sidebar-bg);
  overflow-y: auto;
  transition: width 0.2s ease;
}

.sidebar-toggle-bar {
  display: flex;
  justify-content: flex-end;
  min-height: 44px;
  align-items: center;
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
  min-width: 0;
  min-height: 0;
  padding: 1rem 1.25rem;
  overflow-y: auto;
}

@media (max-width: 1050px) {
  .app-sidebar {
    width: 248px;
  }

  .app-main {
    padding: 0.875rem;
  }
}

@media (max-width: 720px) {
  .app-header {
    min-height: 54px;
    gap: 0.75rem;
    padding-inline: 0.75rem;
  }

  .app-brand__mark {
    width: 32px;
    height: 32px;
  }

  .app-body {
    flex-direction: column;
  }

  .app-sidebar {
    width: 100%;
    height: min(30dvh, 220px);
    border-right: 0;
    border-bottom: 1px solid var(--app-border);
    transition: height 0.2s ease;
  }

  .app-sidebar--collapsed {
    width: 100%;
    height: 44px;
  }

  .app-sidebar--collapsed .sidebar-toggle-bar {
    justify-content: flex-end;
    padding-right: 0.5rem;
  }

  .app-main {
    padding: 0.75rem;
  }
}
</style>
