<template>
  <div class="radiomics-panel">
    <el-card shadow="never">
      <template #header>
        <div class="radiomics-panel-header">
          <span class="radiomics-title">
            {{ isExecution ? '待执行特征提取' : '待确认配对计划' }}
          </span>
          <el-tag type="warning">需确认</el-tag>
        </div>
      </template>

      <div v-if="execution" class="radiomics-body">
        <div class="radiomics-summary">
          <div><span class="radiomics-label">病例数：</span>{{ execution.n_cases }}</div>
          <div>
            <span class="radiomics-label">参数配置：</span>
            <code class="radiomics-code">{{ execution.yaml_path }}</code>
          </div>
          <div>
            <span class="radiomics-label">输出目录：</span>
            <code class="radiomics-code">{{ execution.output_dir }}</code>
          </div>
        </div>

        <div class="radiomics-pairs">
          <div class="radiomics-label">配对列表：</div>
          <div class="radiomics-pairs-list">
            <div
              v-for="(pair, index) in execution.pairs"
              :key="index"
              class="radiomics-pair"
            >
              {{ pair.patient_id }}: {{ pair.image_path }} → {{ pair.mask_path }}
            </div>
          </div>
        </div>

        <div class="radiomics-actions">
          <el-button type="primary" :icon="CircleCheck" @click="handleConfirm">
            确认提取
          </el-button>
          <el-button :icon="Close" @click="handleCancel">取消</el-button>
        </div>
      </div>

      <div v-else-if="plan" class="radiomics-body">
        <div class="radiomics-summary">
          <div>
            <span class="radiomics-label">发现图像/掩膜：</span>
            {{ plan.images_found ?? 0 }} / {{ plan.masks_found ?? 0 }}
          </div>
          <div>
            <span class="radiomics-label">配对结果：</span>
            高置信 {{ planPairs.high.length }}，中置信 {{ planPairs.medium.length }}，
            低置信 {{ planPairs.low.length }}
          </div>
          <div v-if="(plan.unmatched_images?.length ?? 0) > 0">
            <span class="radiomics-label">未匹配图像：</span>
            {{ plan.unmatched_images?.length }}
          </div>
          <div v-if="(plan.unmatched_masks?.length ?? 0) > 0">
            <span class="radiomics-label">未匹配掩膜：</span>
            {{ plan.unmatched_masks?.length }}
          </div>
        </div>

        <div v-if="matchedPairs.length > 0" class="radiomics-pairs">
          <div class="radiomics-label">配对列表：</div>
          <div class="radiomics-pairs-list">
            <div
              v-for="(pair, index) in matchedPairs"
              :key="index"
              class="radiomics-pair"
            >
              {{ pair.patient_id }}: {{ pair.image_path }} → {{ pair.mask_path }}
            </div>
          </div>
        </div>

        <div class="radiomics-actions">
          <el-button type="primary" :icon="CircleCheck" @click="handleConfirm">
            确认
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
import type { RadiomicsPair } from '@/api/agent'

const agentStore = useAgentStore()

const execution = computed(() => agentStore.pendingRadiomicsExecution)
const plan = computed(() => agentStore.pendingRadiomicsPlan)
const isExecution = computed(() => execution.value !== null)

const planPairs = computed(() => ({
  high: plan.value?.pairs?.high ?? [],
  medium: plan.value?.pairs?.medium ?? [],
  low: plan.value?.pairs?.low ?? [],
}))

const matchedPairs = computed<RadiomicsPair[]>(() => [
  ...planPairs.value.high,
  ...planPairs.value.medium,
])

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
.radiomics-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.radiomics-title {
  font-weight: 500;
}

.radiomics-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.radiomics-summary {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  font-size: 0.875rem;
}

.radiomics-label {
  color: #606266;
  font-size: 0.875rem;
}

.radiomics-code {
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.8125rem;
  padding: 0.125rem 0.375rem;
  background-color: #f5f7fa;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
  word-break: break-all;
}

.radiomics-pairs-list {
  max-height: 240px;
  overflow-y: auto;
  margin-top: 0.375rem;
  padding: 0.5rem 0.75rem;
  background-color: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.75rem;
  line-height: 1.6;
}

.radiomics-pair {
  white-space: pre-wrap;
  word-break: break-all;
}

.radiomics-actions {
  display: flex;
  gap: 0.75rem;
}
</style>
