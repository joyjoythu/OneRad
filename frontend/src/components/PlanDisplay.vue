<template>
  <div class="plan-display">
    <div class="plan-display-title">文件计划（{{ plan.length }} 步）</div>
    <el-table :data="plan" border stripe style="width: 100%">
      <el-table-column label="序号" type="index" width="60" align="center" />
      <el-table-column label="操作" prop="action" min-width="100" show-overflow-tooltip />
      <el-table-column label="源路径" prop="source" min-width="140" show-overflow-tooltip />
      <el-table-column label="目标路径" prop="target" min-width="140" show-overflow-tooltip />
      <el-table-column label="原因" prop="reason" min-width="160" show-overflow-tooltip />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAgentStore } from '@/stores/agent'
import type { PlanItem } from '@/api/agent'

const agentStore = useAgentStore()

const plan = computed<PlanItem[]>(() => agentStore.pendingPlan?.plan ?? [])
</script>

<style scoped>
.plan-display {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.plan-display-title {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--app-text);
}
</style>
