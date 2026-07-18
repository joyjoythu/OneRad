<template>
  <div class="script-panel">
    <el-card shadow="never">
      <template #header>
        <div class="script-panel-header">
          <span class="script-title">待执行 Python 脚本</span>
          <el-tag :type="riskType">风险等级：{{ riskLabel }}</el-tag>
        </div>
      </template>

      <div v-if="script" class="script-body">
        <pre class="script-code" tabindex="0"><code>{{ script.code || '脚本内容不可用' }}</code></pre>

        <div v-if="script.description" class="script-explanation">
          <div class="script-section-title">说明</div>
          <p>{{ script.description }}</p>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAgentStore } from '@/stores/agent'

const agentStore = useAgentStore()

const script = computed(() => agentStore.pendingScript)

const riskType = computed(() => {
  switch (script.value?.risk_level) {
    case 'low':
      return 'success' as const
    case 'medium':
      return 'warning' as const
    case 'high':
      return 'danger' as const
    default:
      return 'info' as const
  }
})

const riskLabel = computed(() => {
  switch (script.value?.risk_level) {
    case 'low':
      return '低'
    case 'medium':
      return '中'
    case 'high':
      return '高'
    default:
      return '未知'
  }
})
</script>

<style scoped>
.script-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.script-title {
  font-weight: 500;
  color: var(--app-text);
}

.script-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* 代码块刻意保持常暗：代码编辑器观感在深浅主题下均成立 */
.script-code {
  margin: 0;
  padding: 1rem;
  background-color: #1e1e1e;
  color: #d4d4d4;
  border-radius: var(--app-radius-md);
  overflow-x: auto;
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.875rem;
  line-height: 1.6;
}

.script-code code {
  white-space: pre;
  word-break: normal;
}

.script-explanation {
  padding: 0.75rem 1rem;
  background-color: var(--app-bg-hover);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.script-explanation p {
  margin: 0.5rem 0 0;
  color: var(--app-text-secondary);
  line-height: 1.5;
}

.script-section-title {
  font-weight: 500;
  color: var(--app-text);
}
</style>
