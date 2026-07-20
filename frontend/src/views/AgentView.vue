<template>
  <div class="agent-view">
    <header v-if="projectStore.currentProject || interruptTag" class="agent-header">
      <ConversationTitle />
      <el-tag v-if="interruptTag" :type="interruptTag.type">
        {{ interruptTag.label }}
      </el-tag>
    </header>

    <div class="agent-workspace">
      <div class="agent-chat-wrapper">
        <AgentChat
          ref="agentChatRef"
          @send-message="handleSendMessage"
          @stop="handleStop"
        />
      </div>

      <div
        v-auto-hide-scrollbar
        class="agent-side-panel auto-hide-scrollbar"
        :class="{ 'agent-side-panel--collapsed': isSidePanelCollapsed }"
      >
        <div class="side-panel-header">
          <el-button
            link
            size="small"
            :icon="isSidePanelCollapsed ? Expand : Fold"
            :aria-label="isSidePanelCollapsed ? '展开计划文件面板' : '折叠计划文件面板'"
            data-testid="side-panel-toggle"
            @click="handleToggleSidePanel"
          />
          <span v-show="!isSidePanelCollapsed" class="side-panel-title">
            计划 / 文件
          </span>
        </div>
        <template v-if="!isSidePanelCollapsed">
          <div class="side-panel-content">
            <PlanDisplay v-if="showPlan" />
            <CommandPanel v-else-if="showCommand" />
            <ScriptPanel v-else-if="showScript" />
            <RadiomicsPanel v-else-if="showRadiomics" />
            <AnalysisPanel v-else-if="showAnalysis" />
            <div v-else class="side-panel-empty">暂无待审批的计划/文件</div>
          </div>

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
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import AgentChat from '@/components/AgentChat.vue'
import ConversationTitle from '@/components/ConversationTitle.vue'
import { Expand, Fold } from '@element-plus/icons-vue'
import PlanDisplay from '@/components/PlanDisplay.vue'
import CommandPanel from '@/components/CommandPanel.vue'
import ScriptPanel from '@/components/ScriptPanel.vue'
import RadiomicsPanel from '@/components/RadiomicsPanel.vue'
import AnalysisPanel from '@/components/AnalysisPanel.vue'
import { vAutoHideScrollbar } from '@/directives/autoHideScrollbar'

const agentStore = useAgentStore()
const projectStore = useProjectStore()

const agentChatRef = ref<InstanceType<typeof AgentChat> | null>(null)

const SIDE_PANEL_COLLAPSED_KEY = 'onerad:agent:sidePanelCollapsed'

function loadSidePanelCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDE_PANEL_COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}

function saveSidePanelCollapsed(value: boolean): void {
  try {
    localStorage.setItem(SIDE_PANEL_COLLAPSED_KEY, String(value))
  } catch {
    // ignore
  }
}

const isSidePanelCollapsed = ref(loadSidePanelCollapsed())

function handleToggleSidePanel(): void {
  isSidePanelCollapsed.value = !isSidePanelCollapsed.value
  saveSidePanelCollapsed(isSidePanelCollapsed.value)
}

const showPlan = computed(
  () => !agentStore.busy && agentStore.interrupt === 'file_plan' && agentStore.pendingPlan
)
const showCommand = computed(
  () => !agentStore.busy && agentStore.interrupt === 'system_command' && agentStore.pendingCommand
)
const showScript = computed(
  () => !agentStore.busy && agentStore.interrupt === 'python_script' && agentStore.pendingScript
)
const showRadiomics = computed(
  () =>
    !agentStore.busy &&
    (agentStore.interrupt === 'radiomics_plan' || agentStore.interrupt === 'radiomics_execution') &&
    (agentStore.pendingRadiomicsPlan || agentStore.pendingRadiomicsExecution)
)
const showAnalysis = computed(
  () => !agentStore.busy && agentStore.interrupt === 'radiomics_analysis' && agentStore.pendingRadiomicsAnalysis
)

const interruptTag = computed(() => {
  switch (agentStore.interrupt) {
    case 'file_plan':
      return { label: '待确认文件计划', type: 'warning' as const }
    case 'system_command':
      return { label: '待确认系统命令', type: 'warning' as const }
    case 'python_script':
      return { label: '待确认 Python 脚本', type: 'danger' as const }
    case 'radiomics_plan':
      return { label: '待确认配对计划', type: 'warning' as const }
    case 'radiomics_execution':
      return { label: '待确认特征提取', type: 'warning' as const }
    case 'radiomics_analysis':
      return { label: '待确认影像组学分析', type: 'warning' as const }
    default:
      return null
  }
})

async function handleSendMessage(content: string): Promise<void> {
  const sent = await sendContent(content)
  if (sent) agentChatRef.value?.clearInput()
}

async function sendContent(content: string): Promise<boolean> {
  const projectId = projectStore.currentProject?.id
  if (!projectId) return false
  const config = projectStore.currentConfig
  if (!config) return false
  if (!agentStore.threadId) {
    await agentStore.ensureThread(projectId)
  }
  try {
    await agentStore.sendMessage(content, 'user')
    return true
  } catch {
    // errors handled by axios interceptor
    return false
  }
}

async function handleStop(): Promise<void> {
  try {
    await agentStore.stop()
  } catch {
    // errors handled by axios interceptor
  }
}

onUnmounted(() => {
  agentStore.disconnect()
})

watch(
  () => projectStore.currentProject?.id,
  async (newId, oldId) => {
    if (newId === oldId) return
    // 当前对话已属于该项目（例如在设置页通过侧边栏打开了当前项目的会话）：
    // 不重置、不重复加载。
    if (newId && agentStore.threadId && agentStore.currentThread?.project_id === newId) {
      // 不重载对话，但离开页面时 SSE 已断开，恢复事件流与最新状态。
      void agentStore.reconnect()
      return
    }
    agentStore.resetThread()
    if (!newId) return
    await agentStore.listThreads(newId)
    const config = projectStore.currentConfig
    if (!config) return
    // 侧边栏跨项目点选对话时设置了 preferredThreadId，优先加载它。
    const preferred = agentStore.preferredThreadId
    agentStore.preferredThreadId = null
    const target =
      agentStore.threads.find((t) => t.id === preferred) ?? agentStore.threads[0]
    if (target) {
      await agentStore.loadThread(target.id)
    }
  },
  { immediate: true }
)
</script>

<style scoped>
.agent-view {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  height: 100%;
  gap: 0.75rem;
}

.agent-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-shrink: 0;
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
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.agent-side-panel {
  width: 420px;
  min-width: 0;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 0.875rem;
  padding: 0.75rem;
  overflow-y: auto;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-bg-panel);
  box-shadow: var(--app-shadow-sm);
  transition: width 0.2s ease, padding 0.2s ease;
}

.agent-side-panel--collapsed {
  width: 48px;
  padding-inline: 0.375rem;
  align-items: center;
}

.side-panel-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.agent-side-panel--collapsed .side-panel-header {
  justify-content: center;
}

.side-panel-title {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--app-text);
}

.side-panel-content {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.side-panel-empty {
  padding: 2rem 1rem;
  text-align: center;
  color: var(--app-text-muted);
  font-size: 0.875rem;
  border: 1px dashed var(--app-border-strong);
  border-radius: var(--app-radius-lg);
}

.operation-log {
  max-height: 240px;
  overflow-y: auto;
  padding: 0.75rem 1rem;
  background-color: var(--app-bg-hover);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  color: var(--app-text-secondary);
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

@media (max-width: 1200px) {
  .agent-side-panel:not(.agent-side-panel--collapsed) {
    width: 340px;
  }
}

@media (max-width: 820px) {
  .agent-workspace {
    flex-direction: column;
  }

  .agent-chat-wrapper {
    flex: 1 1 58%;
  }

  .agent-side-panel,
  .agent-side-panel:not(.agent-side-panel--collapsed) {
    width: 100%;
    max-height: 42%;
  }

  .agent-side-panel--collapsed {
    width: 100%;
    min-height: 48px;
    max-height: 48px;
    align-items: stretch;
  }

  .agent-side-panel--collapsed .side-panel-header {
    justify-content: flex-end;
  }
}
</style>
