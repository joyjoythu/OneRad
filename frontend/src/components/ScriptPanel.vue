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

        <div class="script-actions">
          <el-button type="primary" :icon="CircleCheck" @click="handleConfirm">
            确认执行
          </el-button>
          <el-button :icon="Close" @click="handleCancel">取消</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck, Close } from '@element-plus/icons-vue'
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

async function handleConfirm(): Promise<void> {
  try {
    await agentStore.confirm()
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}

async function handleCancel(): Promise<void> {
  try {
    await agentStore.cancel()
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}
</script>

<style scoped>
.script-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.script-title {
  font-weight: 500;
}

.script-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.script-code {
  margin: 0;
  padding: 1rem;
  background-color: #1e1e1e;
  color: #d4d4d4;
  border-radius: 4px;
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
  background-color: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
}

.script-explanation p {
  margin: 0.5rem 0 0;
  color: #606266;
  line-height: 1.5;
}

.script-section-title {
  font-weight: 500;
  color: #303133;
}

.script-actions {
  display: flex;
  gap: 0.75rem;
}
</style>
