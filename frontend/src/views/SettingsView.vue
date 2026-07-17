<template>
  <div class="settings-view">
    <header class="settings-header">
      <h2>{{ pageTitle }}</h2>
    </header>

    <el-empty v-if="!projectStore.currentProject" description="请先选择一个项目" />

    <el-form v-else label-width="100px" class="settings-form">
      <el-form-item label="API 密钥">
        <el-input
          v-model="apiKeyDraft"
          show-password
          placeholder="请输入 API 密钥"
        />
        <p class="api-key-hint">API 密钥随项目配置保存，Agent 对话时使用</p>
      </el-form-item>
      <el-form-item>
        <el-button
          type="primary"
          :loading="projectStore.loading"
          data-testid="settings-save"
          @click="handleSave"
        >
          保存
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '@/stores/project'

const projectStore = useProjectStore()

const apiKeyDraft = ref(projectStore.currentConfig?.api_key ?? '')

// 切换项目/保存成功后，草稿跟随最新配置
watch(
  () => projectStore.currentConfig?.api_key,
  (value) => {
    apiKeyDraft.value = value ?? ''
  }
)

const pageTitle = computed(() => {
  return projectStore.currentProject
    ? `设置 - ${projectStore.currentProject.name}`
    : '设置'
})

async function handleSave(): Promise<void> {
  if (!projectStore.currentProject || !projectStore.currentConfig) {
    ElMessage.warning('请先选择一个项目')
    return
  }
  try {
    await projectStore.saveConfig(projectStore.currentProject.id, {
      ...projectStore.currentConfig,
      api_key: apiKeyDraft.value,
    })
    ElMessage.success('设置已保存')
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}
</script>

<style scoped>
.settings-view {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.settings-header h2 {
  margin: 0;
  font-size: 1.25rem;
}

.settings-form {
  max-width: 560px;
}

.api-key-hint {
  margin: 0.25rem 0 0;
  font-size: 0.8125rem;
  color: #909399;
}
</style>
