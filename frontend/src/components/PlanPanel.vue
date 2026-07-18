<template>
  <div class="plan-panel">
    <el-card shadow="never">
      <template #header>
        <div class="plan-panel-header">
          <span class="plan-title">待执行文件计划</span>
          <el-tag type="warning">需确认</el-tag>
        </div>
      </template>

      <el-alert
        v-if="dirty"
        type="info"
        :closable="false"
        show-icon
        class="plan-dirty-hint"
      >
        计划已被编辑，确认前请点击“更新计划”同步到后端。
      </el-alert>

      <el-table :data="localPlan" border stripe style="width: 100%">
        <el-table-column label="序号" type="index" width="60" align="center" />
        <el-table-column label="操作" prop="action" min-width="120">
          <template #default="{ row }">
            <el-input v-model="row.action" size="small" placeholder="操作" />
          </template>
        </el-table-column>
        
        <el-table-column label="源路径" prop="source" min-width="160">
          <template #default="{ row }">
            <el-input v-model="row.source" size="small" placeholder="源路径" />
          </template>
        </el-table-column>
        
        <el-table-column label="目标路径" prop="target" min-width="160">
          <template #default="{ row }">
            <el-input v-model="row.target" size="small" placeholder="目标路径" />
          </template>
        </el-table-column>
        
        <el-table-column label="原因" prop="reason" min-width="200">
          <template #default="{ row }">
            <el-input v-model="row.reason" size="small" placeholder="原因" />
          </template>
        </el-table-column>

        <el-table-column label="管理" width="120" align="center">
          <template #default="{ $index }">
            <el-button
              link
              type="danger"
              :icon="Delete"
              @click="removeItem($index)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="plan-actions">
        <el-button type="primary" plain :icon="Plus" @click="addItem">
          添加步骤
        </el-button>
        <el-button
          type="success"
          :icon="Check"
          :disabled="!dirty"
          @click="handleUpdate"
        >
          更新计划
        </el-button>
        <el-button type="primary" :icon="CircleCheck" @click="handleConfirm">
          确认执行
        </el-button>
        <el-button :icon="Close" @click="handleCancel">取消</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { Check, Plus, Delete, CircleCheck, Close } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'
import type { PlanItem, PendingPlan } from '@/api/agent'

const agentStore = useAgentStore()

const localPlan = ref<PlanItem[]>([])

const dirty = computed(() => {
  return JSON.stringify(localPlan.value) !== JSON.stringify(agentStore.pendingPlan?.plan ?? [])
})

watch(
  () => agentStore.pendingPlan,
  (pending) => {
    localPlan.value = (pending?.plan ?? []).map((item) => ({ ...item }))
  },
  { immediate: true, deep: true }
)

function addItem(): void {
  localPlan.value.push({
    action: '',
    source: '',
    target: '',
    reason: '',
  })
}

function removeItem(index: number): void {
  localPlan.value.splice(index, 1)
}

async function handleUpdate(): Promise<void> {
  const pending = agentStore.pendingPlan
  if (!pending) return

  const payload: PendingPlan = {
    tool_call_id: pending.tool_call_id,
    plan: localPlan.value,
  }

  try {
    await agentStore.updatePlan(payload)
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
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
</script>

<style scoped>
.plan-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.plan-title {
  font-weight: 500;
  color: var(--app-text);
}

.plan-dirty-hint {
  margin-bottom: 1rem;
}

.plan-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 1rem;
  align-items: center;
}
</style>
