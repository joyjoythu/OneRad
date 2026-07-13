<template>
  <div class="agent-view">
    <header class="agent-header">
      <h2>{{ pageTitle }}</h2>
      <el-tag v-if="interruptTag" :type="interruptTag.type">
        {{ interruptTag.label }}
      </el-tag>
    </header>

    <div class="agent-workspace">
      <div class="agent-chat-wrapper">
        <AgentChat />
      </div>

      <div class="agent-side-panel">
        <PlanPanel
          v-if="agentStore.interrupt === 'file_plan' && agentStore.pendingPlan"
        />
        <CommandPanel
          v-else-if="agentStore.interrupt === 'system_command' && agentStore.pendingCommand"
        />
        <ScriptPanel
          v-else-if="agentStore.interrupt === 'python_script' && agentStore.pendingScript"
        />

        <el-collapse v-if="agentStore.operationLog.length > 0">
          <el-collapse-item title="操作日志">
            <div class="operation-log">
              <div
                v-for="(log, index) in agentStore.operationLog"
                :key="index"
                class="operation-log-entry"
              >
                {{ log }}
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch, onMounted, onUnmounted } from 'vue'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import AgentChat from '@/components/AgentChat.vue'
import PlanPanel from '@/components/PlanPanel.vue'
import CommandPanel from '@/components/CommandPanel.vue'
import ScriptPanel from '@/components/ScriptPanel.vue'

const agentStore = useAgentStore()
const projectStore = useProjectStore()

const pageTitle = computed(() => {
  return projectStore.currentProject
    ? `AI 助手 - ${projectStore.currentProject.name}`
    : 'AI 助手'
})

const interruptTag = computed(() => {
  switch (agentStore.interrupt) {
    case 'file_plan':
      return { label: '待确认文件计划', type: 'warning' as const }
    case 'system_command':
      return { label: '待确认系统命令', type: 'warning' as const }
    case 'python_script':
      return { label: '待确认 Python 脚本', type: 'danger' as const }
    default:
      return null
  }
})

async function initThread(projectId: string): Promise<void> {
  if (agentStore.threadId) {
    await agentStore.reconnect()
  } else {
    const config = projectStore.currentConfig
    if (!config) {
      return
    }
    await agentStore.ensureThread(projectId, config)
  }
}

function resetAndInit(projectId: string): void {
  agentStore.resetThread()
  void initThread(projectId)
}

onMounted(() => {
  if (projectStore.currentProject) {
    void initThread(projectStore.currentProject.id)
  }
})

onUnmounted(() => {
  agentStore.disconnect()
})

watch(
  () => projectStore.currentProject?.id,
  (newId, oldId) => {
    if (!newId) {
      agentStore.resetThread()
      return
    }
    if (newId !== oldId) {
      resetAndInit(newId)
    }
  }
)
</script>

<style scoped>
.agent-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 1rem;
}

.agent-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}

.agent-header h2 {
  margin: 0;
  font-size: 1.25rem;
}

.agent-workspace {
  display: flex;
  flex: 1;
  min-height: 0;
  gap: 1rem;
}

.agent-chat-wrapper {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.agent-side-panel {
  width: 420px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow-y: auto;
}

.operation-log {
  max-height: 240px;
  overflow-y: auto;
  padding: 0.75rem 1rem;
  background-color: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.875rem;
  line-height: 1.5;
}

.operation-log-entry {
  white-space: pre-wrap;
  word-break: break-all;
}

.operation-log-entry + .operation-log-entry {
  margin-top: 0.25rem;
}
</style>
