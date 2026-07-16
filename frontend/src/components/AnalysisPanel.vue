<template>
  <div class="analysis-panel">
    <el-card shadow="never">
      <template #header>
        <div class="analysis-panel-header">
          <span class="analysis-title">待确认影像组学分析</span>
          <el-tag type="warning">需确认</el-tag>
        </div>
      </template>

      <div v-if="analysis" class="analysis-body">
        <div class="analysis-summary">
          <div>
            <span class="analysis-label">特征文件：</span>
            <code class="analysis-code">{{ analysis.feature_csv }}</code>
          </div>
          <div>
            <span class="analysis-label">临床表：</span>
            <code class="analysis-code">{{ analysis.clinical }}</code>
          </div>
          <div>
            <span class="analysis-label">ID 列：</span>
            <code class="analysis-code">{{ analysis.id_col }}</code>
          </div>
          <div>
            <span class="analysis-label">标签列：</span>
            <code class="analysis-code">{{ analysis.label_col }}</code>
          </div>
          <div>
            <span class="analysis-label">匹配病例数 / 特征数 / 临床可用列数：</span>
            {{ analysis.n_matched }} / {{ analysis.n_features }} / {{ analysis.available_clinical_columns.length }}
          </div>
          <div>
            <span class="analysis-label">协变量：</span>
            <span v-if="analysis.covariates.length > 0">{{ analysis.covariates.join(', ') }}</span>
            <span v-else class="analysis-placeholder">无</span>
          </div>
          <div>
            <span class="analysis-label">输出目录：</span>
            <code class="analysis-code">{{ analysis.output_dir }}</code>
          </div>
        </div>

        <div class="analysis-actions">
          <el-button type="primary" :icon="CircleCheck" @click="handleConfirm">
            确认分析
          </el-button>
          <el-button :icon="Close" @click="handleCancel">取消</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck, Close } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'

const agentStore = useAgentStore()

const analysis = computed(() => agentStore.pendingRadiomicsAnalysis)

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
</script>

<style scoped>
.analysis-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.analysis-title {
  font-weight: 500;
}

.analysis-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.analysis-summary {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  font-size: 0.875rem;
}

.analysis-label {
  color: #606266;
  font-size: 0.875rem;
}

.analysis-code {
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.8125rem;
  padding: 0.125rem 0.375rem;
  background-color: #f5f7fa;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
  word-break: break-all;
}

.analysis-placeholder {
  color: #909399;
}

.analysis-actions {
  display: flex;
  gap: 0.75rem;
}
</style>
