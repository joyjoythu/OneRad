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
            <div class="message-content">{{ message.content }}</div>
          </div>
        </div>
      </div>

      <div class="message-input-area">
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          resize="none"
          placeholder="请输入消息，Enter 发送，Shift+Enter 换行"
          aria-label="消息输入"
          :disabled="!agentStore.threadId"
          @keydown="handleKeydown"
        />
        <el-select
          v-model="selectedModel"
          class="model-selector"
          placeholder="选择模型"
          :disabled="!agentStore.threadId"
          @change="handleModelChange"
        >
          <el-option label="DeepSeek-V4 Flash" value="deepseek-v4-flash" />
          <el-option label="DeepSeek-V4 Pro" value="deepseek-v4-pro" />
        </el-select>
        <el-button
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
import { Promotion } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'

const agentStore = useAgentStore()
const projectStore = useProjectStore()

const emit = defineEmits<{
  'update:model': [model: string]
}>()

const input = ref('')
const messageContainer = ref<HTMLDivElement | null>(null)
const selectedModel = ref('deepseek-v4-flash')

const canSend = computed(() => {
  return agentStore.threadId && input.value.trim().length > 0
})

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

function handleModelChange(value: string): void {
  emit('update:model', value)
}

async function handleSend(): Promise<void> {
  const content = input.value.trim()
  if (!content || !agentStore.threadId) return

  input.value = ''
  try {
    await agentStore.sendMessage(content, 'user')
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}
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
