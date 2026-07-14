<template>
  <div class="analysis-view">
    <header class="analysis-header">
      <h2>{{ pageTitle }}</h2>
      <el-tag v-if="statusTag" :type="statusTag.type">{{ statusTag.label }}</el-tag>
    </header>

    <AnalysisForm
      :config="projectStore.currentConfig"
      @update:config="handleConfigUpdate"
      @save="handleSave"
      @run="handleRun"
      @stop="handleStop"
    />

    <div v-if="reportHref" class="analysis-report">
      <el-button
        type="success"
        :icon="Document"
        tag="a"
        :href="reportHref"
        target="_blank"
        rel="noopener noreferrer"
        :aria-label="reportAriaLabel"
      >
        查看报告
      </el-button>
    </div>

    <LogViewer
      v-if="showLogViewer"
      :logs="runStore.logs"
      @clear="runStore.clearLogs()"
      @close="showLogsOverride = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import AnalysisForm from '@/components/AnalysisForm.vue'
import LogViewer from '@/components/LogViewer.vue'
import { useProjectStore } from '@/stores/project'
import { useRunStore } from '@/stores/run'
import type { AnalysisConfig } from '@/api/projects'

const projectStore = useProjectStore()
const runStore = useRunStore()

const showLogsOverride = ref(true)

const pageTitle = computed(() => {
  return projectStore.currentProject
    ? `分析配置 - ${projectStore.currentProject.name}`
    : '分析配置'
})

const statusTag = computed(() => {
  if (runStore.running) {
    return { label: '运行中', type: 'primary' as const }
  }
  if (runStore.currentRun?.status === 'completed') {
    return { label: '已完成', type: 'success' as const }
  }
  if (runStore.currentRun?.status === 'cancelled') {
    return { label: '已取消', type: 'warning' as const }
  }
  if (runStore.currentRun?.status === 'failed') {
    return { label: '运行失败', type: 'danger' as const }
  }
  return null
})

const reportHref = computed(() => {
  // 后端目前返回的是本地报告路径。若已是 URL 则直接使用；
  // 否则按本地文件路径处理（file:// 前缀），相对路径会受浏览器沙箱限制。
  if (!runStore.reportUrl) return ''
  if (/^(https?:|file:)/i.test(runStore.reportUrl)) {
    return runStore.reportUrl
  }
  return `file://${runStore.reportUrl}`
})

const reportAriaLabel = '查看报告（在新标签页中打开）'

const showLogViewer = computed(() => {
  return showLogsOverride.value && (runStore.running || runStore.logs.length > 0)
})

function handleConfigUpdate(config: AnalysisConfig): void {
  if (projectStore.currentProject) {
    projectStore.currentConfig = config
  }
}

async function handleSave(): Promise<void> {
  if (!projectStore.currentProject || !projectStore.currentConfig) {
    ElMessage.warning('请先选择一个项目')
    return
  }

  try {
    await projectStore.saveConfig(
      projectStore.currentProject.id,
      projectStore.currentConfig
    )
    ElMessage.success('配置已保存')
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}

async function handleRun(): Promise<void> {
  if (!projectStore.currentProject || !projectStore.currentConfig) {
    ElMessage.warning('请先选择一个项目')
    return
  }

  showLogsOverride.value = true

  try {
    await projectStore.saveConfig(
      projectStore.currentProject.id,
      projectStore.currentConfig
    )
  } catch {
    return
  }

  try {
    await runStore.startRun(
      projectStore.currentProject.id,
      projectStore.currentConfig
    )
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}

async function handleStop(): Promise<void> {
  if (!runStore.currentRun) {
    ElMessage.warning('没有正在运行的分析')
    return
  }

  try {
    await runStore.stopRun(runStore.currentRun.id)
    ElMessage.success('分析已停止')
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}

onUnmounted(() => {
  runStore.disconnect()
})
</script>

<style scoped>
.analysis-view {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.analysis-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.analysis-header h2 {
  margin: 0;
  font-size: 1.25rem;
}

.analysis-report {
  margin-top: 0.5rem;
}

.log-viewer {
  margin-top: 0.5rem;
}
</style>
