<template>
  <div class="onerad-app">
    <header class="app-header">
      <h1>OneRad</h1>
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

.placeholder {
  color: #909399;
}
</style>
