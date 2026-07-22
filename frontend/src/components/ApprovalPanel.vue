<template>
  <div v-if="view" class="approval-panel">
    <div
      class="approval-header"
      role="button"
      tabindex="0"
      :aria-expanded="expanded"
      @click="toggle"
      @keydown.enter="toggle"
      @keydown.space.prevent="toggle"
    >
      <span class="approval-dot" />
      <span class="approval-title">待确认：{{ view.label }}</span>
      <el-icon class="approval-toggle">
        <ArrowUp v-if="expanded" />
        <ArrowDown v-else />
      </el-icon>
    </div>
    <div v-show="expanded" class="approval-body">
      <PlanEditor v-if="view.type === 'file_plan'" />
      <template v-else>
        <div class="approval-summary">
          <el-tag
            v-if="view.type === 'python_script'"
            :type="riskTagType"
            size="small"
          >
            风险等级：{{ riskLabel }}
          </el-tag>
          <span>{{ view.summary }}</span>
        </div>
        <div class="approval-actions">
          <el-button type="primary" :icon="CircleCheck" @click="handleConfirm">
            {{ view.confirmLabel }}
          </el-button>
          <el-button :icon="Close" @click="handleCancel">取消</el-button>
          <el-button :icon="EditPen" @click="toggleOther">其他</el-button>
        </div>
        <div v-if="otherOpen" class="approval-other">
          <el-input
            v-model="otherInstruction"
            type="textarea"
            :rows="3"
            placeholder="输入自定义指令…"
          />
          <div class="approval-other-actions">
            <el-button
              type="primary"
              size="small"
              :disabled="!otherInstruction.trim()"
              @click="handleOtherSubmit"
            >
              提交
            </el-button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowUp, ArrowDown, CircleCheck, Close, EditPen } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import PlanEditor from './PlanEditor.vue'

const agentStore = useAgentStore()

type ApprovalType =
  | 'file_plan'
  | 'system_command'
  | 'python_script'
  | 'radiomics_plan'
  | 'radiomics_execution'
  | 'radiomics_analysis'
  | 'feature_statistics'
  | 'subagent_dispatch'

interface ApprovalView {
  type: ApprovalType
  label: string
  summary: string
  confirmLabel: string
}

const view = computed<ApprovalView | null>(() => {
  if (agentStore.busy) return null
  switch (agentStore.interrupt) {
    case 'file_plan':
      return agentStore.pendingPlan
        ? { type: 'file_plan', label: '文件计划', summary: '', confirmLabel: '' }
        : null
    case 'system_command':
      return agentStore.pendingCommand
        ? {
            type: 'system_command',
            label: '系统命令',
            summary: `工具：${agentStore.pendingCommand._pending_tool}`,
            confirmLabel: '确认执行',
          }
        : null
    case 'python_script':
      return agentStore.pendingScript
        ? { type: 'python_script', label: 'Python 脚本', summary: '', confirmLabel: '确认执行' }
        : null
    case 'radiomics_plan': {
      const plan = agentStore.pendingRadiomicsPlan
      if (!plan) return null
      const high = plan.pairs?.high?.length ?? 0
      const medium = plan.pairs?.medium?.length ?? 0
      const low = plan.pairs?.low?.length ?? 0
      return {
        type: 'radiomics_plan',
        label: '配对计划',
        summary: `发现 ${plan.images_found ?? 0} 图 / ${plan.masks_found ?? 0} 掩膜，配对 高${high} 中${medium} 低${low}`,
        confirmLabel: '确认',
      }
    }
    case 'radiomics_execution': {
      const execution = agentStore.pendingRadiomicsExecution
      if (!execution) return null
      return {
        type: 'radiomics_execution',
        label: '特征提取',
        summary: `病例数：${execution.n_cases}`,
        confirmLabel: '确认提取',
      }
    }
    case 'radiomics_analysis': {
      const analysis = agentStore.pendingRadiomicsAnalysis
      if (!analysis) return null
      return {
        type: 'radiomics_analysis',
        label: '影像组学分析',
        summary: `特征：${analysis.feature_csv}，标签列：${analysis.label_col}，匹配 ${analysis.n_matched} 例，`
          + `${analysis.n_splits ?? 5} 折，LASSO≤${analysis.max_lasso_features ?? 100} 特征，`
          + `种子 ${analysis.random_state ?? 42}`,
        confirmLabel: '确认分析',
      }
    }
    case 'feature_statistics': {
      const stats = agentStore.pendingFeatureStatistics
      if (!stats) return null
      return {
        type: 'feature_statistics',
        label: '特征统计',
        summary: `筛选特征：${stats.n_selected} 个，标签列：${stats.label_col}，匹配 ${stats.n_matched} 例`,
        confirmLabel: '确认统计',
      }
    }
    case 'subagent_dispatch': {
      const subagent = agentStore.pendingSubagent
      if (!subagent) return null
      const n = subagent.tasks.length
      return {
        type: 'subagent_dispatch',
        label: n > 1 ? `分派 ${n} 个子任务（并行）` : '分派子任务',
        summary: subagent.tasks.map((t, i) => (n > 1 ? `${i + 1}. ${t}` : t)).join('\n'),
        confirmLabel: '确认分派',
      }
    }
    default:
      return null
  }
})

const riskTagType = computed(() => {
  switch (agentStore.pendingScript?.risk_level) {
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
  switch (agentStore.pendingScript?.risk_level) {
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

const expanded = ref(true)

// 新审批到达（interrupt 类型或任一 pending 对象引用变化）时自动展开；
// 用户手动折叠只改 expanded，同一审批保持折叠状态。
watch(
  () => [
    agentStore.interrupt,
    agentStore.pendingPlan,
    agentStore.pendingCommand,
    agentStore.pendingScript,
    agentStore.pendingRadiomicsPlan,
    agentStore.pendingRadiomicsExecution,
    agentStore.pendingRadiomicsAnalysis,
    agentStore.pendingFeatureStatistics,
    agentStore.pendingSubagent,
  ],
  () => {
    expanded.value = true
  }
)

function toggle(): void {
  expanded.value = !expanded.value
}

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

const otherOpen = ref(false)
const otherInstruction = ref('')

function toggleOther(): void {
  otherOpen.value = !otherOpen.value
  if (!otherOpen.value) {
    otherInstruction.value = ''
  }
}

async function handleOtherSubmit(): Promise<void> {
  const instruction = otherInstruction.value.trim()
  if (!instruction) return
  try {
    await agentStore.other(instruction)
  } catch {
    // 错误已由 axios 拦截器统一提示
  } finally {
    otherInstruction.value = ''
    otherOpen.value = false
  }
}
</script>

<style scoped>
.approval-panel {
  border: 1px solid var(--app-border-strong);
  border-radius: var(--app-radius-md);
  background-color: var(--app-bg-panel);
}

.approval-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  cursor: pointer;
  user-select: none;
}

.approval-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--app-warning);
  flex-shrink: 0;
}

.approval-title {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--app-text);
}

.approval-toggle {
  margin-left: auto;
  color: var(--app-text-muted);
}

.approval-body {
  border-top: 1px solid var(--app-border);
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.approval-summary {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--app-text-secondary);
  font-size: 0.875rem;
  /* 子任务列表等多行摘要保留换行 */
  white-space: pre-wrap;
}

.approval-actions {
  display: flex;
  gap: 0.75rem;
}

.approval-other {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.approval-other-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
