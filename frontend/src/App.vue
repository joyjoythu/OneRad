<template>
  <div class="onerad-app">
    <header class="app-header">
      <h1>OneRad</h1>
      <nav class="app-nav">
        <router-link to="/" exact-active-class="active">分析</router-link>
        <router-link to="/agent" exact-active-class="active">Agent</router-link>
      </nav>
    </header>
    <div class="app-body">
      <aside class="app-sidebar">
        <ProjectList />
      </aside>
      <main class="app-main">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import ProjectList from '@/components/ProjectList.vue'
</script>

<style scoped>
.onerad-app {
  display: flex;
  flex-direction: column;
  height: 100vh;
}

.app-header {
  padding: 1rem 2rem;
  border-bottom: 1px solid #e4e7ed;
}

.app-header h1 {
  margin: 0;
  font-size: 1.5rem;
}

.app-nav {
  display: flex;
  gap: 1rem;
}

.app-nav a {
  color: #606266;
  text-decoration: none;
  font-size: 0.9375rem;
  padding: 0.25rem 0;
  border-bottom: 2px solid transparent;
  transition: color 0.2s, border-color 0.2s;
}

.app-nav a:hover {
  color: #409eff;
}

.app-nav a.active {
  color: #409eff;
  border-bottom-color: #409eff;
}

.app-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.app-sidebar {
  width: 320px;
  border-right: 1px solid #e4e7ed;
  overflow-y: auto;
}

.app-main {
  flex: 1;
  padding: 1.5rem 2rem;
  overflow-y: auto;
}
</style>
