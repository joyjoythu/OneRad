<template>
  <!-- MarkdownIt has raw HTML disabled, so v-html receives escaped output. -->
  <!-- eslint-disable vue/no-v-html -->
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
        v-auto-hide-scrollbar
        class="message-list auto-hide-scrollbar"
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
                v-if="message.role === 'assistant' && message.reasoning_content"
                class="reasoning-block"
              >
                <el-button
                  link
                  size="small"
                  class="reasoning-toggle"
                  :aria-label="
                    isReasoningExpanded(index) ? '收起思考过程' : '展开思考过程'
                  "
                  @click="toggleReasoning(index)"
                >
                  {{ isReasoningExpanded(index) ? '收起' : '展开' }}思考过程
                </el-button>
                <div
                  v-show="isReasoningExpanded(index)"
                  class="reasoning-content"
                >
                  {{ message.reasoning_content }}
                </div>
              </div>
              <div
                v-if="message.role === 'tool'"
                class="message-tool-call"
              >
                <el-tag size="small" type="info" effect="plain">
                  工具结果
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
                v-if="message.content && message.role === 'assistant'"
                class="message-content message-content--markdown"
                v-html="renderMarkdown(message.content)"
              />
              <div
                v-else-if="message.content && message.role === 'tool'"
                class="message-content message-content--tool"
                :class="{
                  'is-collapsed': isToolCollapsed(
                    index,
                    toolMessageDisplay(index).text
                  ),
                }"
              >
                <div
                  v-if="toolMessageDisplay(index).format === 'markdown'"
                  class="message-content--markdown"
                  v-html="renderMarkdown(toolMessageDisplay(index).text)"
                />
                <div v-else>{{ toolMessageDisplay(index).text }}</div>
              </div>
              <div
                v-else-if="message.content"
                class="message-content"
              >
                {{ message.content }}
              </div>
              <div
                v-if="
                  message.role === 'tool' &&
                  shouldCollapseTool(toolMessageDisplay(index).text)
                "
                class="tool-toggle"
              >
                <el-button
                  link
                  size="small"
                  :aria-label="
                    isToolCollapsed(index, toolMessageDisplay(index).text)
                      ? '展开工具输出'
                      : '收起工具输出'
                  "
                  @click="toggleTool(index, toolMessageDisplay(index).text)"
                >
                  {{
                    isToolCollapsed(index, toolMessageDisplay(index).text)
                      ? '展开'
                      : '收起'
                  }}
                </el-button>
              </div>
            </div>
            <div v-if="message.timestamp" class="message-time">
              {{ formatMessageTime(message.timestamp) }}
            </div>
          </div>
        </div>
        <div
          v-if="showThinkingStream"
          class="message-row message-row--assistant"
        >
          <AgentAvatar class="message-avatar" />
          <div class="message-main message-main--assistant">
            <div class="message-bubble message-bubble--assistant thinking-stream">
              <div class="thinking-stream-header">
                <el-icon class="is-loading"><Loading /></el-icon>
                <span>思考过程</span>
              </div>
              <div class="thinking-stream-content">{{ agentStore.currentThinking?.text }}</div>
            </div>
          </div>
        </div>
        <div
          v-for="sub in subagentPanels"
          :key="sub.id"
          class="subagent-stage"
          :class="`subagent-stage--${sub.status}`"
          data-testid="subagent-stage"
          role="status"
        >
          <span class="subagent-stage__marker" aria-hidden="true" />
          <div class="subagent-panel">
            <div class="subagent-header">
              <div class="subagent-heading">
                <span class="subagent-eyebrow">内部执行阶段</span>
                <span class="subagent-title">{{ sub.task }}</span>
              </div>
              <el-icon
                v-if="sub.status === 'running'"
                class="is-loading subagent-spinner"
              ><Loading /></el-icon>
              <el-tag
                size="small"
                :type="subagentTagType(sub.status)"
                effect="plain"
              >
                {{ subagentStatusLabel(sub.status) }}
              </el-tag>
              <el-button
                link
                size="small"
                class="subagent-toggle"
                :aria-label="subagentExpanded[sub.id] !== false ? '收起子任务过程' : '展开子任务过程'"
                @click="toggleSubagent(sub.id)"
              >
                {{ subagentExpanded[sub.id] !== false ? '收起' : '展开' }}过程
              </el-button>
            </div>
            <p v-if="subagentStatusHint(sub.status)" class="subagent-status-hint">
              {{ subagentStatusHint(sub.status) }}
            </p>
            <div
              v-show="subagentExpanded[sub.id] !== false"
              class="subagent-entries"
            >
              <div
                v-for="(entry, i) in sub.entries"
                :key="i"
                class="subagent-entry"
                :class="`subagent-entry--${entry.role}`"
              >
                {{ entry.text }}
              </div>
              <div
                v-if="!sub.entries.length"
                class="subagent-entry subagent-entry--muted"
              >
                等待子任务输出…
              </div>
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
      <div class="chat-progress">
        <el-progress
          v-if="extractionPercent !== null"
          :percentage="extractionPercent"
          :stroke-width="6"
        />
      </div>

      <div class="input-container">
        <el-mention
          ref="mentionRef"
          v-model="input"
          type="textarea"
          :rows="3"
          resize="none"
          :options="mentionOptions"
          :loading="mentionLoading"
          :filter-option="false"
          placement="top"
          whole
          :placeholder="inputPlaceholder"
          aria-label="消息输入"
          :disabled="inputDisabled"
          @search="handleMentionSearch"
          @keydown="handleKeydown"
        />
        <div class="input-toolbar">
          <div class="input-toolbar-left">
            <el-dropdown
              placement="top-start"
              trigger="click"
              popper-class="quick-actions-menu"
              :disabled="inputDisabled"
              @command="handleQuickAction"
            >
              <el-button
                plain
                size="small"
                class="quick-actions-trigger"
                :icon="Operation"
                :disabled="inputDisabled"
                data-testid="quick-actions-trigger"
              >
                快捷操作
                <el-icon class="el-icon--right"><ArrowUp /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    v-for="action in QUICK_ACTIONS"
                    :key="action.command"
                    :command="action.command"
                    :icon="action.icon"
                    :divided="action.divided"
                    :class="{ 'quick-action--danger': action.command === 'clear-task' }"
                    :data-testid="`quick-action-${action.command}`"
                  >
                    {{ action.label }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>

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
          </div>
          <div class="input-toolbar-right">
            <el-select
              ref="modelSelectRef"
              :model-value="agentStore.selectedModel"
              class="model-select"
              :style="{ width: modelSelectWidth }"
              size="small"
              aria-label="模型选择"
              data-testid="model-select"
              @change="(value: string) => agentStore.setModel(value)"
            >
              <el-option
                v-for="model in AVAILABLE_MODELS"
                :key="model"
                :label="model"
                :value="model"
              />
            </el-select>
            <el-tooltip :content="contextTooltip" placement="top">
              <span class="context-usage" :class="contextUsageLevel">
                <el-icon><Odometer /></el-icon>
                <span>{{ contextUsageText }}</span>
              </span>
            </el-tooltip>
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
  <!-- eslint-enable vue/no-v-html -->
</template>

<script setup lang="ts">
import { ref, computed, watch, watchEffect, nextTick, onMounted } from 'vue'
import {
  ArrowUp,
  CircleClose,
  DataAnalysis,
  Delete,
  Download,
  List,
  Loading,
  Odometer,
  Operation,
  Promotion,
  Refresh,
} from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import { useAgentStore, AVAILABLE_MODELS } from '@/stores/agent'
import { useProjectStore } from '@/stores/project'
import type { AgentMessage } from '@/api/agent'
import { listProjectEntries } from '@/api/projects'
import AgentAvatar from './AgentAvatar.vue'
import ApprovalPanel from './ApprovalPanel.vue'
import { formatMessageTime } from '@/utils/time'
import { renderMarkdown } from '@/utils/markdown'
import { formatToolMessage, type ToolMessageDisplay } from '@/utils/toolMessage'
import { vAutoHideScrollbar } from '@/directives/autoHideScrollbar'

const agentStore = useAgentStore()
const projectStore = useProjectStore()

const emit = defineEmits<{
  'send-message': [content: string]
  'stop': []
}>()

const input = ref('')
const mentionRef = ref<{ dropdownVisible?: boolean; focus?: () => void } | null>(null)

// @ 文件引用：el-mention 触发 search 后防抖查询项目文件列表，
// 选项已由后端按关键词过滤，故本地 filter-option 关闭。
const mentionOptions = ref<{ value: string }[]>([])
const mentionLoading = ref(false)
let mentionTimer: ReturnType<typeof setTimeout> | undefined
// 响应乱序保护：只有最后一次查询允许写回选项。
let mentionSeq = 0

function handleMentionSearch(pattern: string): void {
  const projectId = projectStore.currentProject?.id
  if (!projectId) {
    mentionOptions.value = []
    return
  }
  clearTimeout(mentionTimer)
  mentionTimer = setTimeout(async () => {
    const seq = ++mentionSeq
    mentionLoading.value = true
    try {
      const entries = await listProjectEntries(projectId, pattern)
      if (seq === mentionSeq) {
        mentionOptions.value = entries.map((e) => ({ value: e }))
      }
    } catch {
      // 索引失败不阻断输入：仅清空候选，错误已由 axios 拦截器统一提示。
      if (seq === mentionSeq) mentionOptions.value = []
    } finally {
      if (seq === mentionSeq) mentionLoading.value = false
    }
  }, 200)
}
const messageContainer = ref<HTMLDivElement | null>(null)

const emptyToolMessageDisplay: ToolMessageDisplay = { text: '', format: 'plain' }
const toolMessageDisplays = computed(() =>
  agentStore.messages.map((message) =>
    message.role === 'tool'
      ? formatToolMessage(message.content || '')
      : emptyToolMessageDisplay
  )
)

function toolMessageDisplay(index: number): ToolMessageDisplay {
  return toolMessageDisplays.value[index] ?? emptyToolMessageDisplay
}

const QUICK_ACTIONS = [
  {
    command: 'start-analysis',
    label: '开始分析',
    icon: DataAnalysis,
    divided: false,
    prompt: '请检查当前项目配置与数据完整性，并开始执行完整的影像组学分析流程。',
  },
  {
    command: 'structured-conclusion',
    label: '生成结构化结论',
    icon: List,
    divided: true,
    prompt:
      '请基于当前分析结果生成结构化结论，按研究目的、数据概况、核心发现、统计证据、局限性和下一步建议组织。',
  },
  {
    command: 'export-report',
    label: '导出报告',
    icon: Download,
    divided: false,
    prompt:
      '请将当前分析结果整理并导出为正式报告，保存到项目输出目录，并返回生成文件的完整路径。',
  },
  {
    command: 'reanalyze',
    label: '重新分析',
    icon: Refresh,
    divided: true,
    prompt:
      '请基于当前项目配置重新执行完整分析；开始前先说明将复用的数据、参数以及会覆盖或新生成的结果。',
  },
  {
    command: 'clear-task',
    label: '清除当前任务',
    icon: Delete,
    divided: false,
    prompt: '',
  },
] as const

/** 工具输出超过该阈值（行数）后自动折叠。 */
const TOOL_COLLAPSE_LINE_THRESHOLD = 10
/** 工具输出超过该阈值（字符数）后同样折叠：后端把工具结果 json.dumps 成
 * 单行字符串（换行转义为 \n），只数真实换行永远是一行，需按长度兜底。 */
const TOOL_COLLAPSE_CHAR_THRESHOLD = 600
/** 记录用户手动展开/收起的工具输出索引。 */
const expandedToolIndexes = ref<Record<number, boolean>>({})

/** 记录用户手动展开/收起的思考过程区块索引（默认折叠）。 */
const expandedReasoningIndexes = ref<Record<number, boolean>>({})

function isReasoningExpanded(index: number): boolean {
  return !!expandedReasoningIndexes.value[index]
}

function toggleReasoning(index: number): void {
  expandedReasoningIndexes.value[index] = !expandedReasoningIndexes.value[index]
}

/** 流式思考气泡：busy 且当前轮思考未结束时显示。 */
const showThinkingStream = computed(() => {
  const thinking = agentStore.currentThinking
  return (
    agentStore.busy && !!thinking && !thinking.done && thinking.text.length > 0
  )
})

// 子任务面板：仅在父 agent 运行期间展示（结束后结论在历史消息的
// 工具结果里，面板随之收起）。并行分派时每个子 agent 一个面板，
// 展开/收起状态按子线程 id 分别记录，新子任务默认展开。
const subagentExpanded = ref<Record<string, boolean>>({})

const subagentPanels = computed(() => {
  if (!agentStore.busy) return []
  return Object.values(agentStore.subagentStatuses)
})

function subagentStatusLabel(status: string): string {
  switch (status) {
    case 'running':
      return '运行中'
    case 'done':
      return '结果已返回'
    case 'failed':
      return '执行失败'
    case 'cancelled':
      return '已停止'
    default:
      return ''
  }
}

function subagentStatusHint(status: string): string {
  switch (status) {
    case 'done':
      return '该内部子任务已经返回结果，主任务仍在整理结果或继续执行。'
    case 'failed':
      return '该内部子任务执行失败，主任务仍在评估后续处理方式。'
    case 'cancelled':
      return '该内部子任务已停止，主任务仍在处理中。'
    default:
      return ''
  }
}

function subagentTagType(status: string): 'success' | 'danger' | 'warning' | 'info' {
  switch (status) {
    case 'failed':
      return 'danger'
    case 'cancelled':
      return 'warning'
    default:
      return 'info'
  }
}

function toggleSubagent(id: string): void {
  subagentExpanded.value[id] = subagentExpanded.value[id] === false
}

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

async function handleQuickAction(command: string): Promise<void> {
  if (inputDisabled.value) return

  if (command === 'clear-task') {
    try {
      await ElMessageBox.confirm(
        '清除当前任务上下文并开始新对话？历史对话仍会保留。',
        '清除当前任务',
        {
          type: 'warning',
          confirmButtonText: '清除',
          cancelButtonText: '取消',
          customClass: 'compact-confirm-box',
        }
      )
    } catch {
      return
    }
    agentStore.resetThread()
    return
  }

  const action = QUICK_ACTIONS.find((item) => item.command === command)
  if (!action?.prompt) return
  // 提示词先填入输入框，由用户调整后再手动发送，而不是直接发出。
  const draft = input.value.trimEnd()
  input.value = draft ? `${draft}\n${action.prompt}` : action.prompt
  mentionRef.value?.focus?.()
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

// 特征提取进度条百分比；无提取进行中时为 null（不渲染进度条）。
const extractionPercent = computed(() => {
  if (!agentStore.busy) return null
  const progress = agentStore.radiomicsProgress
  if (!progress || !progress.total) return null
  if (progress.stage === 'finalizing') return 100
  if (progress.stage === 'extracting') {
    return Math.min(100, Math.round((progress.current / progress.total) * 100))
  }
  return 0
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

// 选择框宽度 = 选中文字的实际渲染宽度 + 固有部分（内边距与下拉箭头约 40px），
// 避免估算宽度在文字与箭头之间留出空隙。jsdom 无布局，量不到时回退为 CSS 默认。
const modelSelectRef = ref<{ $el?: HTMLElement } | null>(null)
const modelTextWidth = ref(0)
const modelSelectWidth = computed(() =>
  modelTextWidth.value ? `${modelTextWidth.value + 40}px` : ''
)

async function measureModelSelectText(): Promise<void> {
  await nextTick()
  const root = modelSelectRef.value?.$el
  const label = root?.querySelector('.el-select__selected-item')
  modelTextWidth.value = label instanceof HTMLElement ? label.offsetWidth : 0
}

watch(
  () => agentStore.selectedModel,
  () => {
    void measureModelSelectText()
  },
  { flush: 'post' }
)
onMounted(() => {
  void measureModelSelectText()
})

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

// 流式思考文本更新时保持贴底滚动。
watchEffect(async () => {
  if (agentStore.currentThinking?.text) {
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
  if (mentionRef.value?.dropdownVisible) {
    // 补全弹层打开时：Enter 由 el-mention 自己用于选中候选（不能发送）；
    // Tab 同样映射为选中。el-mention 未暴露选中方法，向其 Enter
    // 处理路径转发一个合成 Enter 事件完成选中。
    if (event.key === 'Tab') {
      event.preventDefault()
      ;(event.target as HTMLElement | null)?.dispatchEvent(
        new KeyboardEvent('keydown', {
          key: 'Enter',
          bubbles: true,
          cancelable: true,
        })
      )
    }
    return
  }
  if (event.defaultPrevented) return
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
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  height: 100%;
  gap: 0.75rem;
  width: 100%;
}

/* 聊天列（会话标题、消息列表、状态栏、输入框、审批面板）统一限宽并水平
 * 居中：两侧面板折叠/展开时列位置保持居中，输入框始终与消息列表同宽对齐。 */
.agent-chat > * {
  width: 100%;
  max-width: 880px;
  margin-inline: auto;
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
  padding: clamp(0.75rem, 2vw, 1.25rem);
  /* 无框设计：消息气泡直接落在页面背景上，依靠气泡自身的底色区分层次 */
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
  /* 与助手消息一致靠左：工具结果不再随内容宽度居中漂移 */
  justify-content: flex-start;
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
  background-color: var(--app-accent);
  color: #ffffff;
  box-shadow: 0 4px 12px var(--app-focus-ring);
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

/* Markdown 排版：只作用于助手消息的 v-html 渲染结果，
   所有取值来自设计令牌。 */
.message-content--markdown {
  white-space: normal;
}

.message-content--markdown > :deep(*:first-child) {
  margin-top: 0;
}

.message-content--markdown > :deep(*:last-child) {
  margin-bottom: 0;
}

.message-content--markdown :deep(p) {
  margin: 0.5em 0;
}

.message-content--markdown :deep(h1),
.message-content--markdown :deep(h2),
.message-content--markdown :deep(h3),
.message-content--markdown :deep(h4) {
  margin: 0.75em 0 0.375em;
  font-weight: 600;
  line-height: 1.4;
}

.message-content--markdown :deep(h1) {
  font-size: 1.25em;
}

.message-content--markdown :deep(h2) {
  font-size: 1.125em;
}

.message-content--markdown :deep(h3),
.message-content--markdown :deep(h4) {
  font-size: 1em;
}

.message-content--markdown :deep(ul),
.message-content--markdown :deep(ol) {
  margin: 0.5em 0;
  padding-left: 1.375em;
}

.message-content--markdown :deep(li + li) {
  margin-top: 0.25em;
}

.message-content--markdown :deep(code) {
  padding: 0.1em 0.35em;
  border-radius: var(--app-radius-sm);
  background-color: var(--app-bg-hover);
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.875em;
}

.message-content--markdown :deep(pre) {
  margin: 0.5em 0;
  padding: 0.75rem 1rem;
  border-radius: var(--app-radius-md);
  background-color: var(--app-bg-hover);
  overflow-x: auto;
}

.message-content--markdown :deep(pre code) {
  padding: 0;
  background-color: transparent;
  font-size: 0.8125rem;
  line-height: 1.5;
}

.message-content--markdown :deep(blockquote) {
  margin: 0.5em 0;
  padding-left: 0.75em;
  border-left: 3px solid var(--app-border-strong);
  color: var(--app-text-secondary);
}

.message-content--markdown :deep(table) {
  margin: 0.5em 0;
  border-collapse: collapse;
  font-size: 0.875em;
}

.message-content--markdown :deep(th),
.message-content--markdown :deep(td) {
  padding: 0.375em 0.75em;
  border: 1px solid var(--app-border-strong);
}

.message-content--markdown :deep(th) {
  background-color: var(--app-bg-hover);
  font-weight: 600;
}

.message-content--markdown :deep(a) {
  color: var(--app-text);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.message-content--markdown :deep(hr) {
  margin: 0.75em 0;
  border: none;
  border-top: 1px solid var(--app-border-strong);
}

.tool-toggle {
  display: flex;
  justify-content: flex-end;
  margin-top: 0.25rem;
}

.reasoning-block {
  margin-bottom: 0.25rem;
}

.reasoning-content {
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--app-text-secondary);
  font-size: 0.875rem;
  border-left: 2px solid var(--app-border);
  padding-left: 0.5rem;
  margin-top: 0.25rem;
}

.thinking-stream {
  width: 100%;
}

.thinking-stream-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  color: var(--app-text-muted);
  font-size: 0.875rem;
  margin-bottom: 0.25rem;
}

.thinking-stream-content {
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--app-text-secondary);
  font-size: 0.875rem;
  border-left: 2px solid var(--app-border);
  padding-left: 0.5rem;
}

.subagent-stage {
  display: flex;
  align-items: flex-start;
  gap: 0.625rem;
  margin: 0.25rem 0 1rem;
  padding: 0 0.25rem;
}

.subagent-stage__marker {
  width: 0.625rem;
  height: 0.625rem;
  margin-top: 0.875rem;
  flex: 0 0 auto;
  border-radius: 999px;
  background: var(--app-border-strong);
  box-shadow: 0 0 0 4px var(--app-bg-hover);
}

.subagent-stage--running .subagent-stage__marker {
  background: var(--app-accent);
  animation: subagent-pulse 1.6s ease-in-out infinite;
}

.subagent-stage--failed .subagent-stage__marker {
  background: var(--app-danger);
}

.subagent-stage--cancelled .subagent-stage__marker {
  background: var(--app-warning);
}

.subagent-panel {
  width: auto;
  min-width: 0;
  flex: 1;
  border: 1px solid var(--app-border);
  border-left: 3px solid var(--app-border-strong);
  border-radius: var(--app-radius-md);
  padding: 0.625rem 0.75rem;
  background: var(--app-bg-hover);
}

.subagent-stage--running .subagent-panel {
  border-left-color: var(--app-accent);
}

.subagent-stage--failed .subagent-panel {
  border-left-color: var(--app-danger);
}

.subagent-stage--cancelled .subagent-panel {
  border-left-color: var(--app-warning);
}

.subagent-header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  color: var(--app-text-secondary);
  font-size: 0.875rem;
}

.subagent-heading {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 0.125rem;
}

.subagent-eyebrow {
  color: var(--app-text-muted);
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  line-height: 1.2;
  text-transform: uppercase;
}

.subagent-title {
  overflow: hidden;
  color: var(--app-text);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subagent-toggle {
  flex-shrink: 0;
}

.subagent-spinner {
  flex-shrink: 0;
  color: var(--app-accent);
}

.subagent-status-hint {
  margin: 0.375rem 0 0;
  color: var(--app-text-muted);
  font-size: 0.8125rem;
  line-height: 1.5;
}

.subagent-entries {
  margin-top: 0.375rem;
  border-left: 2px solid var(--app-border);
  padding-left: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  max-height: 16rem;
  overflow-y: auto;
}

.subagent-entry {
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--app-text-secondary);
  font-size: 0.8125rem;
  line-height: 1.5;
}

.subagent-entry--tool {
  color: var(--app-text-muted);
}

.subagent-entry--muted {
  color: var(--app-text-muted);
  font-style: italic;
}

@keyframes subagent-pulse {
  0%,
  100% {
    opacity: 0.6;
    transform: scale(0.9);
  }
  50% {
    opacity: 1;
    transform: scale(1);
  }
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

.chat-progress {
  /* 与状态栏同理：固定占位高度，进度条出现/消失不改变布局 */
  height: calc(6px + 0.5rem);
  padding: 0.25rem 0.5rem;
  box-sizing: border-box;
}

.chat-progress .el-progress {
  width: 100%;
}

.chat-status--idle {
  visibility: hidden;
}

.input-container {
  border: 1px solid var(--app-border-strong);
  border-radius: var(--app-radius-lg);
  background-color: var(--app-bg-panel);
  box-shadow: var(--app-shadow-sm);
  transition: border-color 0.16s ease, box-shadow 0.16s ease;
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
  border-color: var(--app-accent);
  box-shadow: 0 0 0 3px var(--app-focus-ring), var(--app-shadow-sm);
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

.input-toolbar-left {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.75rem;
}

.quick-actions-trigger {
  border-color: var(--app-border-strong);
  color: var(--app-text-secondary);
}

.quick-actions-trigger:hover,
.quick-actions-trigger:focus-visible {
  border-color: var(--app-accent);
  background: var(--app-sidebar-hover);
  color: var(--app-accent-active);
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

@media (max-width: 680px) {
  .message-main {
    max-width: 90%;
  }

  .message-list {
    padding: 0.75rem;
  }

  .input-toolbar {
    gap: 0.5rem;
    padding-inline: 0.625rem;
  }

  .input-toolbar-left {
    gap: 0.5rem;
  }

  .quick-actions-trigger {
    padding-inline: 0.625rem;
  }

  .context-usage {
    font-size: 0;
  }

  .context-usage :deep(.el-icon) {
    font-size: 0.875rem;
  }
}
</style>
