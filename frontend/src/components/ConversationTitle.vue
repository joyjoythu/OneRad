<template>
  <div
    v-if="projectStore.currentProject"
    class="conversation-header"
    data-testid="current-conversation-title"
  >
    <span class="conversation-header__label">当前会话</span>
    <h2 :title="currentConversationTitle">{{ currentConversationTitle }}</h2>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'

const agentStore = useAgentStore()
const projectStore = useProjectStore()

const currentConversationTitle = computed(() => {
  const title = agentStore.currentThread?.title?.trim()
  if (title) return title
  return agentStore.threadId ? '未命名会话' : '新对话'
})
</script>

<style scoped>
.conversation-header {
  display: flex;
  min-width: 0;
  min-height: 36px;
  align-items: center;
  gap: 0.625rem;
  padding: 0 0.25rem;
}

.conversation-header__label {
  flex: 0 0 auto;
  padding: 0.1875rem 0.5rem;
  border: 1px solid var(--app-border-strong);
  border-radius: 999px;
  background: var(--app-bg-panel);
  color: var(--app-text-muted);
  font-size: 0.6875rem;
  font-weight: 600;
}

.conversation-header h2 {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--app-text);
  font-size: 1rem;
  font-weight: 650;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
