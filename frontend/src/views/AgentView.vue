<template>
  <div class="agent-view">
    <header class="agent-header">
      <h2>{{ pageTitle }}</h2>
      <el-tag v-if="interruptTag" :type="interruptTag.type">
        {{ interruptTag.label }}
      </el-tag>
    </header>

    <div class="agent-workspace">
      <ThreadList
        :threads="agentStore.threads"
        :current-thread-id="agentStore.currentThread?.id ?? null"
        :collapsed="isThreadListCollapsed"
        @select="handleSelectThread"
        @create="handleCreateThread"
        @rename="handleRenameThread"
        @delete="handleDeleteThread"
        @toggle-collapse="handleToggleThreadListCollapse"
      />
      <div class="agent-chat-wrapper">
        <AgentChat
          ref="agentChatRef"
          :model="selectedModel"
          @update:model="selectedModel = $event"
          @send-message="handleSendMessage"
          @stop="handleStop"
        />
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
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import AgentChat from '@/components/AgentChat.vue'
import ThreadList from '@/components/ThreadList.vue'
import PlanPanel from '@/components/PlanPanel.vue'
import CommandPanel from '@/components/CommandPanel.vue'
import ScriptPanel from '@/components/ScriptPanel.vue'
import { DEFAULT_AGENT_MODEL } from '@/api/agent'

const agentStore = useAgentStore()
const projectStore = useProjectStore()

const selectedModel = ref(DEFAULT_AGENT_MODEL)
const agentChatRef = ref<InstanceType<typeof AgentChat> | null>(null)

const THREAD_LIST_COLLAPSED_KEY = 'onerad:agent:threadListCollapsed'

function loadThreadListCollapsed(): boolean {
  try {
    return localStorage.getItem(THREAD_LIST_COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}

function saveThreadListCollapsed(value: boolean): void {
  try {
    localStorage.setItem(THREAD_LIST_COLLAPSED_KEY, String(value))
  } catch {
    // ignore
  }
}

const isThreadListCollapsed = ref(loadThreadListCollapsed())

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

async function handleSendMessage(content: string): Promise<void> {
  const projectId = projectStore.currentProject?.id
  if (!projectId) return
  const config = projectStore.currentConfig
  if (!config) return
  if (!agentStore.threadId) {
    await agentStore.ensureThread(projectId, config.api_key, selectedModel.value)
  }
  try {
    await agentStore.sendMessage(content, 'user')
    agentChatRef.value?.clearInput()
  } catch {
    // errors handled by axios interceptor
  }
}

async function handleStop(): Promise<void> {
  try {
    await agentStore.stop()
  } catch {
    // errors handled by axios interceptor
  }
}

async function handleSelectThread(threadId: string): Promise<void> {
  const projectId = projectStore.currentProject?.id
  const config = projectStore.currentConfig
  if (!projectId || !config) return
  if (threadId === agentStore.currentThread?.id) return
  const thread = agentStore.threads.find((t) => t.id === threadId)
  if (!thread) return
  selectedModel.value = thread.llm_model
  await agentStore.loadThread(threadId, config.api_key, thread.llm_model)
}

async function handleCreateThread(): Promise<void> {
  const projectId = projectStore.currentProject?.id
  const config = projectStore.currentConfig
  if (!projectId || !config) return
  await agentStore.createThread(projectId, config.api_key, selectedModel.value)
  agentChatRef.value?.clearInput()
}

async function handleRenameThread(threadId: string, title: string): Promise<void> {
  const projectId = projectStore.currentProject?.id
  if (!projectId) return
  await agentStore.renameThread(threadId, title, projectId)
}

async function handleDeleteThread(threadId: string): Promise<void> {
  const projectId = projectStore.currentProject?.id
  if (!projectId) return
  await agentStore.deleteThread(threadId, projectId)
}

function handleToggleThreadListCollapse(): void {
  isThreadListCollapsed.value = !isThreadListCollapsed.value
  saveThreadListCollapsed(isThreadListCollapsed.value)
}

onMounted(() => {
  // 项目切换 watcher 已设置 immediate: true，首次加载会自动处理。
})

onUnmounted(() => {
  agentStore.disconnect()
})

watch(
  () => projectStore.currentProject?.id,
  async (newId, oldId) => {
    if (newId !== oldId) {
      agentStore.resetThread()
      if (newId) {
        await agentStore.listThreads(newId)
        if (agentStore.threads.length > 0) {
          const config = projectStore.currentConfig
          if (config) {
            const latest = agentStore.threads[0]
            await agentStore.loadThread(
              latest.id,
              config.api_key,
              latest.llm_model
            )
            selectedModel.value = latest.llm_model
          }
        }
      }
    }
  },
  { immediate: true }
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
