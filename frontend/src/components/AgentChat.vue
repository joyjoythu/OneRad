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
            <div v-if="message.content" class="message-content">{{ message.content }}</div>
          </div>
        </div>
      </div>

      <div v-if="statusText" class="chat-status" role="status">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>{{ statusText }}</span>
      </div>

      <div class="message-input-area">
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
          type="danger"
          :icon="CircleClose"
          @click="handleStop"
        >
          停止
        </el-button>
        <el-button
          v-else
          type="primary"
          :icon="Promotion"
          :disabled="!canSend"
          @click="handleSend"
        >
          发送
        </el-button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watchEffect, nextTick } from 'vue'
import { Loading, CircleClose, Promotion } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import { DEFAULT_AGENT_MODEL } from '@/api/agent'
import type { AgentMessage } from '@/api/agent'

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

// 根据运行状态推导用户可见的状态文案。
// busy 优先于 interrupt：确认后 execute_confirmed 清除 interrupt_type
// 之前的中间快照仍带有旧值，此时实际仍在运行。
const statusText = computed(() => {
  if (agentStore.busy) {
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
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  background-color: #ffffff;
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

.message-bubble {
  max-width: 80%;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  line-height: 1.5;
  word-break: break-word;
  white-space: pre-wrap;
}

.message-bubble--user {
  background-color: #409eff;
  color: #ffffff;
}

.message-bubble--assistant {
  background-color: #f5f7fa;
  color: #303133;
  border: 1px solid #e4e7ed;
}

.message-bubble--tool {
  max-width: 90%;
  background-color: #f4f4f5;
  color: #606266;
  font-size: 0.875rem;
  padding: 0.5rem 0.75rem;
}

.message-tool-call {
  margin-bottom: 0.25rem;
}

.chat-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.25rem 0.5rem;
  color: #909399;
  font-size: 0.875rem;
}

.message-content {
  white-space: pre-wrap;
  word-break: break-word;
}

.message-input-area {
  display: flex;
  align-items: flex-end;
  gap: 0.75rem;
}

.message-input-area :deep(.el-textarea) {
  flex: 1;
}

.message-input-area .el-button {
  margin-bottom: 1px;
}

.model-selector {
  width: 150px;
}

.model-selector :deep(.el-select__wrapper) {
  margin-bottom: 1px;
}
</style>
