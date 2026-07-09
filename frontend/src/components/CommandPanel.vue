<template>
  <div class="command-panel">
    <el-card shadow="never">
      <template #header>
        <div class="command-panel-header">
          <span class="command-title">待执行系统命令</span>
          <el-tag type="warning">需确认</el-tag>
        </div>
      </template>

      <div v-if="command" class="command-body">
        <div class="command-line">
          <span class="command-label">工具：</span>
          <code class="command-tool">{{ command._pending_tool }}</code>
        </div>

        <div class="command-args">
          <div class="command-label">参数：</div>
          <pre class="command-args-pre">{{ formattedArgs }}</pre>
        </div>

        <div class="command-actions">
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

const command = computed(() => agentStore.pendingCommand)

const formattedArgs = computed(() => {
  if (!command.value) return ''
  return JSON.stringify(command.value.args, null, 2)
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
.command-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.command-title {
  font-weight: 500;
}

.command-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.command-line {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.command-label {
  color: #606266;
  font-size: 0.875rem;
}

.command-tool {
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.875rem;
  padding: 0.25rem 0.5rem;
  background-color: #f5f7fa;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
}

.command-args-pre {
  margin: 0.5rem 0 0;
  padding: 0.75rem 1rem;
  background-color: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.875rem;
  white-space: pre-wrap;
  word-break: break-all;
}

.command-actions {
  display: flex;
  gap: 0.75rem;
}
</style>
