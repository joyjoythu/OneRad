<template>
  <div class="agent-chat">
    <div
      v-if="!projectStore.currentProject"
      class="chat-empty"
    >
      <el-empty description="请先选择一个项目开始对话" />
    </div>

    <template v-else>
      <div
        ref="messageContainer"
        class="message-list"
        role="log"
        aria-live="polite"
        aria-atomic="false"
      >
        <div
          v-for="(message, index) in agentStore.messages"
          :key="index"
          :class="['message-row', `message-row--${message.role}`]"
        >
          <AgentAvatar
            v-if="message.role === 'assistant'"
            class="message-avatar"
          />
          <div :class="['message-main', `message-main--${message.role}`]">
            <div
              :class="[
                'message-bubble',
                `message-bubble--${message.role}`,
              ]"
            >
              <div
                v-if="message.role === 'tool'"
                class="message-tool-call"
              >
                <el-tag size="small" type="info" effect="plain">
                  工具调用
                </el-tag>
              </div>
              <div
                v-else-if="toolCallNames(message)"
                class="message-tool-call"
              >
                <el-tag size="small" type="warning" effect="plain">
                  调用工具：{{ toolCallNames(message) }}
                </el-tag>
              </div>
              <div
                v-if="message.content"
                class="message-content"
                :class="{
                  'message-content--tool': message.role === 'tool',
                  'is-collapsed':
                    message.role === 'tool' &&
                    isToolCollapsed(index, message.content),
                }"
              >
                {{ message.content }}
              </div>
              <div
                v-if="
                  message.role === 'tool' &&
                  shouldCollapseTool(message.content)
                "
                class="tool-toggle"
              >
                <el-button
                  link
                  size="small"
                  :aria-label="
                    isToolCollapsed(index, message.content)
                      ? '展开工具输出'
                      : '收起工具输出'
                  "
                  @click="toggleTool(index, message.content)"
                >
                  {{ isToolCollapsed(index, message.content) ? '展开' : '收起' }}
                </el-button>
              </div>
            </div>
            <div v-if="message.timestamp" class="message-time">
              {{ formatMessageTime(message.timestamp) }}
            </div>
          </div>
        </div>
      </div>

      <ApprovalPanel />

      <div
        class="chat-status"
        :class="{ 'chat-status--idle': !statusText }"
        role="status"
      >
        <template v-if="statusText">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>{{ statusText }}</span>
        </template>
      </div>

      <div class="input-container">
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          resize="none"
          :placeholder="inputPlaceholder"
          aria-label="消息输入"
          :disabled="inputDisabled"
          @keydown="handleKeydown"
        />
        <div class="input-toolbar">
          <div class="auto-approve-row">
            <span class="auto-approve-label">自动审批</span>
            <el-switch
              :model-value="agentStore.autoApprove"
              :disabled="agentStore.autoApproveSyncing"
              size="small"
              aria-label="自动审批"
              @change="handleAutoApproveChange"
            />
          </div>
          <div class="input-toolbar-right">
            <el-tooltip :content="contextTooltip" placement="top">
              <span class="context-usage" :class="contextUsageLevel">
                <el-icon><Odometer /></el-icon>
                <span>{{ contextUsageText }}</span>
              </span>
            </el-tooltip>
            <el-select
              v-model="selectedModel"
              class="model-selector"
              placeholder="模型（仅新会话）"
            >
              <el-option label="DeepSeek-V4 Flash" value="deepseek-v4-flash" />
              <el-option label="DeepSeek-V4 Pro" value="deepseek-v4-pro" />
            </el-select>
            <el-button
              v-if="agentStore.busy"
              circle
              type="danger"
              :icon="CircleClose"
              aria-label="停止"
              @click="handleStop"
            />
            <el-button
              v-else
              circle
              type="primary"
              :icon="Promotion"
              :disabled="!canSend"
              aria-label="发送"
              @click="handleSend"
            />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watchEffect, nextTick } from 'vue'
import { Loading, CircleClose, Promotion, Odometer } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import { DEFAULT_AGENT_MODEL } from '@/api/agent'
import type { AgentMessage } from '@/api/agent'
import AgentAvatar from './AgentAvatar.vue'
import ApprovalPanel from './ApprovalPanel.vue'
import { formatMessageTime } from '@/utils/time'

const agentStore = useAgentStore()
const projectStore = useProjectStore()

const emit = defineEmits<{
  'update:model': [model: string]
  'send-message': [content: string]
  'stop': []
}>()

const props = defineProps<{
  model?: string
}>()

const input = ref('')
const messageContainer = ref<HTMLDivElement | null>(null)
const selectedModel = computed({
  get: () => props.model ?? DEFAULT_AGENT_MODEL,
  set: (value) => emit('update:model', value),
})

/** 工具输出超过该阈值（行数）后自动折叠。 */
const TOOL_COLLAPSE_LINE_THRESHOLD = 10
/** 工具输出超过该阈值（字符数）后同样折叠：后端把工具结果 json.dumps 成
 * 单行字符串（换行转义为 \n），只数真实换行永远是一行，需按长度兜底。 */
const TOOL_COLLAPSE_CHAR_THRESHOLD = 600
/** 记录用户手动展开/收起的工具输出索引。 */
const expandedToolIndexes = ref<Record<number, boolean>>({})

function shouldCollapseTool(content?: string): boolean {
  if (!content) return false
  if (content.split('\n').length > TOOL_COLLAPSE_LINE_THRESHOLD) return true
  return content.length > TOOL_COLLAPSE_CHAR_THRESHOLD
}

function isToolCollapsed(index: number, content?: string): boolean {
  if (!content) return false
  if (expandedToolIndexes.value[index]) return false
  return shouldCollapseTool(content)
}

function toggleTool(index: number, content?: string): void {
  if (!content) return
  const currentlyExpanded = !isToolCollapsed(index, content)
  expandedToolIndexes.value[index] = !currentlyExpanded
}

const canSend = computed(() => {
  return (
    projectStore.currentProject !== null &&
    !agentStore.busy &&
    !agentStore.interrupt &&
    input.value.trim().length > 0
  )
})

const inputDisabled = computed(() => {
  return !projectStore.currentProject || agentStore.busy || !!agentStore.interrupt
})

const inputPlaceholder = computed(() => {
  if (agentStore.busy) return '智能体正在处理中，请稍候…'
  if (agentStore.interrupt) return '请先确认或取消当前待处理的操作'
  return '请输入消息，Enter 发送，Shift+Enter 换行'
})

async function handleAutoApproveChange(value: string | number | boolean): Promise<void> {
  try {
    await agentStore.setAutoApprove(Boolean(value))
  } catch {
    // 错误已由 axios 拦截器统一提示；store 已回滚开关状态。
  }
}

// 根据运行状态推导用户可见的状态文案。
// busy 优先于 interrupt：确认后 execute_confirmed 清除 interrupt_type
// 之前的中间快照仍带有旧值，此时实际仍在运行。
const statusText = computed(() => {
  if (agentStore.busy) {
    const progress = agentStore.radiomicsProgress
    if (progress) {
      if (progress.stage === 'finalizing') return '正在保存特征结果…'
      if (progress.stage === 'extracting') {
        const suffix = progress.patient_id ? `：${progress.patient_id}` : ''
        return `正在提取影像组学特征 (${progress.current}/${progress.total})${suffix}…`
      }
      return `正在准备提取影像组学特征（共 ${progress.total} 例）…`
    }
    const last = agentStore.messages[agentStore.messages.length - 1]
    if (last?.role === 'assistant' && last.tool_calls?.length) {
      const name = last.tool_calls[0]?.name
      return name ? `正在调用工具：${name}…` : '正在调用工具…'
    }
    return '正在思考…'
  }
  if (agentStore.interrupt) return '等待确认操作…'
  return ''
})

/** 格式化 token 数：>=1000 用 k，>=1M 用 M。 */
function formatTokens(n: number): string {
  if (n >= 1_000_000) {
    return `${parseFloat((n / 1_000_000).toFixed(2))}M`
  }
  if (n >= 1_000) {
    return `${parseFloat((n / 1_000).toFixed(1))}k`
  }
  return String(n)
}

/** badge 文案：当前上下文用量/窗口 · 百分比；无数据显示 --。 */
const contextUsageText = computed(() => {
  const usage = agentStore.contextUsage
  const window = agentStore.contextWindow
  if (!usage || !window) return '--'
  const pct = ((usage.input_tokens / window) * 100).toFixed(1)
  return `${formatTokens(usage.input_tokens)}/${formatTokens(window)} · ${pct}%`
})

/** 用量阈值样式：>=80% 橙色，>=95% 红色。 */
const contextUsageLevel = computed(() => {
  const usage = agentStore.contextUsage
  const window = agentStore.contextWindow
  if (!usage || !window) return ''
  const ratio = usage.input_tokens / window
  if (ratio >= 0.95) return 'context-usage--danger'
  if (ratio >= 0.8) return 'context-usage--warning'
  return ''
})

/** 悬停 tooltip：精确 token 明细。 */
const contextTooltip = computed(() => {
  const usage = agentStore.contextUsage
  if (!usage) return '发送首条消息后显示上下文用量'
  return (
    `输入 ${usage.input_tokens.toLocaleString()} / ` +
    `输出 ${usage.output_tokens.toLocaleString()} / ` +
    `合计 ${usage.total_tokens.toLocaleString()} tokens`
  )
})

function toolCallNames(message: AgentMessage): string {
  if (!message.tool_calls?.length) return ''
  return message.tool_calls
    .map((tc) => tc.name)
    .filter(Boolean)
    .join(', ')
}

watchEffect(async () => {
  if (agentStore.messages.length) {
    await nextTick()
    scrollToBottom()
  }
})

function scrollToBottom(): void {
  if (messageContainer.value) {
    messageContainer.value.scrollTop = messageContainer.value.scrollHeight
  }
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.isComposing) return
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    handleSend()
  }
}

async function handleSend(): Promise<void> {
  if (!canSend.value) return
  const content = input.value.trim()
  if (!content) return

  emit('send-message', content)
}

function handleStop(): void {
  emit('stop')
}

function clearInput(): void {
  input.value = ''
}

defineExpose({ clearInput })
</script>

<style scoped>
.agent-chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 1rem;
}

.chat-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 1rem;
  border: 1px solid var(--app-border-strong);
  border-radius: var(--app-radius-lg);
  background-color: var(--app-bg-panel);
}

.message-row {
  display: flex;
  margin-bottom: 0.75rem;
}

.message-row--user {
  justify-content: flex-end;
}

.message-row--assistant {
  justify-content: flex-start;
}

.message-row--tool {
  justify-content: center;
}

.message-main {
  display: flex;
  flex-direction: column;
  max-width: 80%;
}

.message-main--tool {
  max-width: 90%;
}

.message-main--user {
  align-items: flex-end;
}

.message-main--assistant {
  align-items: flex-start;
}

.message-avatar {
  margin-right: 0.5rem;
  margin-top: 2px;
}

.message-time {
  margin-top: 0.25rem;
  padding: 0 0.25rem;
  font-size: 0.75rem;
  line-height: 1.2;
  color: var(--app-text-muted);
}

.message-bubble {
  padding: 0.75rem 1rem;
  border-radius: var(--app-radius-lg);
  line-height: 1.5;
  word-break: break-word;
  white-space: pre-wrap;
}

.message-bubble--user {
  background-color: var(--app-bg-bubble);
  color: var(--app-text);
}

.message-bubble--assistant {
  background-color: transparent;
  color: var(--app-text);
  padding-left: 0;
  padding-right: 0;
}

.message-bubble--tool {
  background-color: var(--app-bg-hover);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  color: var(--app-text-secondary);
  font-size: 0.875rem;
  padding: 0.5rem 0.75rem;
}

.message-tool-call {
  margin-bottom: 0.25rem;
}

.message-content {
  white-space: pre-wrap;
  word-break: break-word;
}

.message-content--tool.is-collapsed {
  max-height: calc(1.5 * 0.875rem * 10);
  overflow: hidden;
}

.tool-toggle {
  display: flex;
  justify-content: flex-end;
  margin-top: 0.25rem;
}

.chat-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  /* 固定占位高度：状态栏出现/消失不再改变消息列表高度，
     避免贴底滚动时内容被挤压回弹。 */
  height: calc(0.875rem * 1.5 + 0.5rem);
  padding: 0.25rem 0.5rem;
  box-sizing: border-box;
  color: var(--app-text-secondary);
  font-size: 0.875rem;
  line-height: 1.5;
}

.chat-status--idle {
  visibility: hidden;
}

.input-container {
  border: 1px solid var(--app-border-strong);
  border-radius: var(--app-radius-lg);
  background-color: var(--app-bg-panel);
  transition: border-color 0.2s;
  /* 容器内输入控件去边框去底色：边框由容器统一提供 */
  --el-input-border-color: transparent;
  --el-input-hover-border-color: transparent;
  --el-input-focus-border-color: transparent;
  --el-input-bg-color: transparent;
  --el-fill-color-blank: transparent;
  --el-disabled-bg-color: transparent;
  --el-disabled-border-color: transparent;
}

.input-container:focus-within {
  border-color: var(--app-text-muted);
}

.input-container :deep(.el-textarea__inner) {
  padding: 0.75rem 0.75rem 0.25rem;
}

/* select 的边线是 box-shadow（读 --el-border-color），容器变量覆盖不到，需显式去除 */
.input-container :deep(.el-select__wrapper),
.input-container :deep(.el-select__wrapper.is-hovering),
.input-container :deep(.el-select__wrapper.is-focused) {
  box-shadow: none;
}

.input-toolbar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.25rem 0.75rem 0.5rem;
}

.auto-approve-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--app-text-muted);
  font-size: 0.75rem;
}

.input-toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-left: auto;
}

.model-selector {
  width: 150px;
}

.context-usage {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: var(--app-text-muted);
  white-space: nowrap;
  cursor: default;
}

.context-usage--warning {
  color: var(--app-warning);
}

.context-usage--danger {
  color: var(--app-danger);
}
</style>
