<template>
  <div class="onerad-app">
    <header class="app-header">
      <h1>OneRad</h1>
    </header>
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.app-header {
  padding: 1rem 2rem;
  border-bottom: 1px solid #e4e7ed;
}

.app-header h1 {
  margin: 0;
  font-size: 1.5rem;
}

.app-main {
  padding: 1.5rem 2rem;
}
</style>
