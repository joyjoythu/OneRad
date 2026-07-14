<template>
  <div class="analysis-form">
    <el-empty v-if="!projectStore.currentProject" description="请选择一个项目" />

    <template v-else>
      <el-form :model="draft" label-position="top" class="analysis-form-body">
        <el-form-item label="影像目录">
          <el-input
            v-model="draft.image_dir"
            placeholder="请输入影像目录路径"
            @change="onFieldChange"
          />
        </el-form-item>

        <el-form-item label="临床数据文件">
          <el-input
            v-model="draft.clinical_path"
            placeholder="请输入临床数据文件路径"
            @change="onFieldChange"
          />
        </el-form-item>

        <el-form-item label="输出目录">
          <el-input
            v-model="draft.output_dir"
            placeholder="请输入输出目录路径"
            @change="onFieldChange"
          />
        </el-form-item>

        <el-form-item label="影像模态">
          <el-select v-model="draft.modality" placeholder="请选择模态" @change="onFieldChange">
            <el-option label="CT" value="CT" />
            <el-option label="MRI" value="MRI" />
            <el-option label="PET" value="PET" />
          </el-select>
        </el-form-item>

        <el-form-item label="协变量">
          <el-input
            v-model="draft.covariates"
            placeholder="请输入协变量，多个用逗号分隔"
            @change="onFieldChange"
          />
        </el-form-item>

        <el-form-item label="分析模型">
          <el-select
            v-model="draft.analysis_model"
            placeholder="请选择分析模型"
            @change="onFieldChange"
          >
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
            @change="onFieldChange"
          />
          <p class="api-key-hint">API 密钥仅在当前会话中保留，不会写入项目文件</p>
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
          v-if="runStore.running"
          type="danger"
          :icon="VideoPause"
          :loading="runStore.cancelling"
          @click="handleStop"
        >
          停止分析
        </el-button>
        <el-button
          v-else
          type="primary"
          :icon="VideoPlay"
          :loading="runStore.running"
          @click="handleRun"
        >
          开始分析
        </el-button>
      </div>

      <p v-if="saveStatus === 'saved' && lastSavedAt" class="save-hint">
        配置已自动保存 · {{ lastSavedAt }}
      </p>
      <p v-else-if="saveStatus === 'error'" class="save-hint error">
        自动保存失败，请重试
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { reactive, watch, ref } from 'vue'
import { Document, VideoPlay, VideoPause } from '@element-plus/icons-vue'
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
  stop: []
}>()

const projectStore = useProjectStore()
const runStore = useRunStore()

const saveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const lastSavedAt = ref<string | null>(null)

function debounce(fn: () => void, wait: number): () => void {
  let timer: ReturnType<typeof setTimeout> | null = null
  return () => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(fn, wait)
  }
}

const debouncedSave = debounce(() => {
  saveStatus.value = 'saving'
  emit('save')
}, 500)

function onFieldChange(): void {
  debouncedSave()
}

watch(
  () => projectStore.loading,
  (loading) => {
    if (!loading && saveStatus.value === 'saving') {
      saveStatus.value = 'saved'
      lastSavedAt.value = new Date().toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      })
    }
  }
)

const defaultConfig = (): AnalysisConfig => ({
  image_dir: '',
  clinical_path: '',
  output_dir: './outputs',
  modality: 'CT',
  covariates: '',
  model: 'logistic',
  analysis_model: 'logistic',
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
    a.analysis_model === b.analysis_model &&
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

function handleStop(): void {
  emit('stop')
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

.save-hint {
  margin: 0.5rem 0 0;
  font-size: 0.875rem;
  color: #67c23a;
}

.save-hint.error {
  color: #f56c6c;
}

.api-key-hint {
  margin: 0.25rem 0 0;
  font-size: 0.75rem;
  color: #909399;
}
</style>
