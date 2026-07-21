<template>
  <div class="todo-panel" data-testid="todo-panel">
    <div class="todo-panel-header">
      <span class="todo-panel-title">分析计划</span>
      <span class="todo-panel-progress">已完成 {{ doneCount }}/{{ todos.length }}</span>
    </div>
    <ul class="todo-list">
      <li
        v-for="(todo, index) in todos"
        :key="index"
        class="todo-item"
        :class="`todo-item--${todo.status}`"
      >
        <el-icon v-if="todo.status === 'completed'" class="todo-icon todo-icon--completed">
          <CircleCheckFilled />
        </el-icon>
        <el-icon v-else-if="todo.status === 'in_progress'" class="todo-icon todo-icon--running is-loading">
          <Loading />
        </el-icon>
        <el-icon v-else-if="todo.status === 'cancelled'" class="todo-icon todo-icon--cancelled">
          <WarningFilled />
        </el-icon>
        <span v-else class="todo-icon todo-icon--pending" />
        <span class="todo-content">{{ todo.content }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { CircleCheckFilled, Loading, WarningFilled } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'

const agentStore = useAgentStore()
const { todos } = storeToRefs(agentStore)

const doneCount = computed(
  () => todos.value.filter((t) => t.status === 'completed').length
)
</script>

<style scoped>
.todo-panel {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-bg-panel);
  padding: 0.75rem 1rem;
}

.todo-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}

.todo-panel-title {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--app-text);
}

.todo-panel-progress {
  font-size: 0.75rem;
  color: var(--app-text-muted);
}

.todo-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.todo-item {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  font-size: 0.875rem;
  line-height: 1.5;
  color: var(--app-text-secondary);
}

.todo-item--in_progress {
  color: var(--app-text);
  font-weight: 500;
}

.todo-item--completed {
  color: var(--app-text-muted);
}

.todo-icon {
  flex-shrink: 0;
  margin-top: 0.2rem;
  font-size: 0.9375rem;
}

.todo-icon--completed {
  color: var(--el-color-success);
}

.todo-icon--running {
  color: var(--el-color-primary);
}

.todo-icon--cancelled {
  color: var(--el-color-warning);
}

.todo-icon--pending {
  width: 0.75rem;
  height: 0.75rem;
  margin: 0.32rem 0.125rem 0;
  border: 1.5px solid var(--app-border-strong);
  border-radius: 50%;
  box-sizing: border-box;
}

.todo-content {
  min-width: 0;
  word-break: break-word;
}
</style>
