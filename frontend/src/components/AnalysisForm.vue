<template>
  <div class="analysis-form">
    <el-empty v-if="!projectStore.currentProject" description="请选择一个项目" />

    <template v-else>
      <el-form :model="draft" label-position="top" class="analysis-form-body">
        <el-form-item label="影像目录">
          <el-input v-model="draft.image_dir" placeholder="请输入影像目录路径" />
        </el-form-item>

        <el-form-item label="临床数据文件">
          <el-input v-model="draft.clinical_path" placeholder="请输入临床数据文件路径" />
        </el-form-item>

        <el-form-item label="输出目录">
          <el-input v-model="draft.output_dir" placeholder="请输入输出目录路径" />
        </el-form-item>

        <el-form-item label="影像模态">
          <el-select v-model="draft.modality" placeholder="请选择模态">
            <el-option label="CT" value="CT" />
            <el-option label="MRI" value="MRI" />
            <el-option label="PET" value="PET" />
          </el-select>
        </el-form-item>

        <el-form-item label="协变量">
          <el-input
            v-model="draft.covariates"
            placeholder="请输入协变量，多个用逗号分隔"
          />
        </el-form-item>

        <el-form-item label="模型">
          <el-select v-model="draft.model" placeholder="请选择模型">
            <el-option label="Logistic 回归" value="logistic" />
            <el-option label="随机森林" value="random_forest" />
            <el-option label="支持向量机" value="svm" />
            <el-option label="XGBoost" value="xgboost" />
          </el-select>
        </el-form-item>

        <el-form-item label="API 密钥">
          <el-input
            v-model="draft.api_key"
            show-password
            placeholder="请输入 API 密钥"
          />
        </el-form-item>
      </el-form>

      <div class="analysis-form-actions">
        <el-button
          :icon="Document"
          :loading="projectStore.loading"
          @click="handleSave"
        >
          保存配置
        </el-button>
        <el-button
          type="primary"
          :icon="VideoPlay"
          :loading="runStore.running"
          @click="handleRun"
        >
          开始分析
        </el-button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { reactive, watch } from 'vue'
import { Document, VideoPlay } from '@element-plus/icons-vue'
import { useProjectStore } from '@/stores/project'
import { useRunStore } from '@/stores/run'
import type { AnalysisConfig } from '@/api/projects'

const props = defineProps<{
  config: AnalysisConfig | null
}>()

const emit = defineEmits<{
  'update:config': [AnalysisConfig]
  save: []
  run: []
}>()

const projectStore = useProjectStore()
const runStore = useRunStore()

const defaultConfig = (): AnalysisConfig => ({
  image_dir: '',
  clinical_path: '',
  output_dir: './outputs',
  modality: 'CT',
  covariates: '',
  model: 'logistic',
  api_key: '',
})

const draft = reactive<AnalysisConfig>(defaultConfig())

function configsEqual(a: AnalysisConfig, b: AnalysisConfig): boolean {
  return (
    a.image_dir === b.image_dir &&
    a.clinical_path === b.clinical_path &&
    a.output_dir === b.output_dir &&
    a.modality === b.modality &&
    a.covariates === b.covariates &&
    a.model === b.model &&
    a.api_key === b.api_key
  )
}

watch(
  () => props.config,
  (cfg) => {
    if (cfg && !configsEqual(cfg, draft)) {
      Object.assign(draft, cfg)
    }
  },
  { immediate: true, deep: true }
)

watch(
  draft,
  () => {
    if (props.config) {
      emit('update:config', { ...draft })
    }
  },
  { deep: true }
)

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
