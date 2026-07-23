<template>
  <div
    class="subagent-stage"
    :class="`subagent-stage--${sub.status}`"
    data-testid="subagent-stage"
    role="status"
  >
    <span class="subagent-stage__marker" aria-hidden="true" />
    <div class="subagent-panel">
      <div class="subagent-header">
        <div class="subagent-heading">
          <span class="subagent-eyebrow">子 Agent · 内部执行阶段</span>
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
          :aria-label="expanded ? '收起子任务过程' : '展开子任务过程'"
          @click="emit('toggle')"
        >
          {{ expanded ? '收起' : '展开' }}过程
        </el-button>
      </div>
      <p v-if="subagentStatusHint(sub.status)" class="subagent-status-hint">
        {{ subagentStatusHint(sub.status) }}
      </p>
      <div
        v-show="expanded"
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
</template>

<script setup lang="ts">
import { Loading } from '@element-plus/icons-vue'
import type { SubagentStatus } from '@/api/agent'

const props = defineProps<{
  sub: SubagentStatus
  /** 父流程是否仍在运行：决定“主任务仍在处理”类提示是否展示。 */
  busy: boolean
  expanded: boolean
}>()

const emit = defineEmits<{
  toggle: []
}>()

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
  // “主任务仍在处理”类提示只在父流程运行中有意义；结束后面板定格，
  // 终态由状态标签本身表达。
  if (!props.busy) return ''
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
</script>

<style scoped>
.subagent-stage {
  display: flex;
  align-items: flex-start;
  gap: 0.625rem;
  /* 水平方向必须保持 auto：否则会覆盖 .message-list > * 的 margin-inline:auto，
     导致子 Agent 面板脱离 880px 居中列、整体偏左。 */
  margin: 0.25rem auto 1rem;
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
</style>
