<template>
  <div class="analysis-form">
    <el-empty v-if="!projectStore.currentProject" description="请选择一个项目" />

    <template v-else>
      <el-form
        :model="projectStore.currentConfig"
        label-position="top"
        class="analysis-form-body"
      >
        <el-form-item label="影像目录">
          <el-input
            v-model="projectStore.currentConfig!.image_dir"
            placeholder="请输入影像目录路径"
          />
        </el-form-item>

        <el-form-item label="临床数据文件">
          <el-input
            v-model="projectStore.currentConfig!.clinical_path"
            placeholder="请输入临床数据文件路径"
          />
        </el-form-item>

        <el-form-item label="输出目录">
          <el-input
            v-model="projectStore.currentConfig!.output_dir"
            placeholder="请输入输出目录路径"
          />
        </el-form-item>

        <el-form-item label="影像模态">
          <el-select v-model="projectStore.currentConfig!.modality" placeholder="请选择模态">
            <el-option label="CT" value="CT" />
            <el-option label="MRI" value="MRI" />
            <el-option label="PET" value="PET" />
          </el-select>
        </el-form-item>

        <el-form-item label="协变量">
          <el-input
            v-model="projectStore.currentConfig!.covariates"
            placeholder="请输入协变量，多个用逗号分隔"
          />
        </el-form-item>

        <el-form-item label="模型">
          <el-select v-model="projectStore.currentConfig!.model" placeholder="请选择模型">
            <el-option label="Logistic 回归" value="logistic" />
            <el-option label="随机森林" value="random_forest" />
            <el-option label="支持向量机" value="svm" />
            <el-option label="XGBoost" value="xgboost" />
          </el-select>
        </el-form-item>

        <el-form-item label="API 密钥">
          <el-input
            v-model="projectStore.currentConfig!.api_key"
            show-password
            placeholder="请输入 API 密钥"
          />
        </el-form-item>
      </el-form>

      <div class="analysis-form-actions">
        <el-button :icon="Document" @click="handleSave">保存配置</el-button>
        <el-button type="primary" :icon="VideoPlay" @click="handleRun">
          开始分析
        </el-button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { Document, VideoPlay } from '@element-plus/icons-vue'
import { useProjectStore } from '@/stores/project'

const emit = defineEmits<{
  save: []
  run: []
}>()

const projectStore = useProjectStore()

function handleSave(): void {
  emit('save')
}

function handleRun(): void {
  emit('run')
}
</script>

<style scoped>
.analysis-form {
  max-width: 720px;
}

.analysis-form-body :deep(.el-select) {
  width: 100%;
}

.analysis-form-actions {
  display: flex;
  gap: 0.75rem;
  margin-top: 1rem;
}
</style>
