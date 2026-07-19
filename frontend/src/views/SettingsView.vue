<template>
  <div class="settings-view">
    <header class="settings-header">
      <div>
        <p class="settings-eyebrow">OneRad workspace</p>
        <h2>{{ pageTitle }}</h2>
      </div>
      <div
        v-if="projectStore.currentProject"
        class="save-status"
        :class="`save-status--${saveStatus}`"
        role="status"
        data-testid="settings-save-status"
      >
        <span class="save-status__dot" />
        <template v-if="saveStatus === 'saving'">保存中</template>
        <template v-else-if="saveStatus === 'saved'">已保存 {{ savedTimeLabel }}</template>
        <button
          v-else-if="saveStatus === 'error'"
          type="button"
          class="save-status__retry"
          data-testid="settings-save-retry"
          @click="retrySave"
        >
          保存失败 · 重试
        </button>
        <template v-else>修改后自动保存</template>
      </div>
    </header>

    <section class="settings-card settings-card--appearance">
      <div class="settings-card__heading">
        <div>
          <h3>界面外观</h3>
          <p>主题偏好会保存在当前浏览器。</p>
        </div>
      </div>
      <el-radio-group
        :model-value="currentTheme"
        aria-label="主题外观"
        @change="handleThemeChange"
      >
        <el-radio-button value="light">浅色</el-radio-button>
        <el-radio-button value="dark">深色</el-radio-button>
      </el-radio-group>
    </section>

    <el-empty v-if="!projectStore.currentProject" description="请先选择一个项目" />

    <el-form
      v-else
      class="settings-card settings-form"
      label-position="top"
      @focusout="handleFieldBlur"
    >
      <div class="settings-card__heading">
        <div>
          <h3>分析配置</h3>
          <p>用于影像组学工作流的数据发现、特征分析与结果输出。</p>
        </div>
      </div>

      <div class="settings-grid">
        <el-form-item label="影像目录" class="settings-grid__wide">
          <div class="path-input-row">
            <el-input
              v-model="draft.image_dir"
              class="path-input-row__field"
              placeholder="包含影像与分割文件的目录"
              data-testid="settings-image-dir"
            />
            <el-button
              class="path-input-row__browse"
              data-testid="browse-image-dir"
              @click="openPicker('image_dir')"
            >
              浏览
            </el-button>
          </div>
        </el-form-item>

        <el-form-item label="临床数据文件" class="settings-grid__wide">
          <div class="path-input-row">
            <el-input
              v-model="draft.clinical_path"
              class="path-input-row__field"
              placeholder="CSV 或 Excel 临床数据文件"
              data-testid="settings-clinical-path"
            />
            <el-button
              class="path-input-row__browse"
              data-testid="browse-clinical-path"
              @click="openPicker('clinical_path')"
            >
              浏览
            </el-button>
          </div>
          <p class="field-hint">支持 .csv、.xlsx、.xls</p>
        </el-form-item>

        <el-form-item label="输出目录" class="settings-grid__wide">
          <div class="path-input-row">
            <el-input
              v-model="draft.output_dir"
              class="path-input-row__field"
              placeholder="可手动填写尚未创建的目录"
              data-testid="settings-output-dir"
            />
            <el-button
              class="path-input-row__browse"
              data-testid="browse-output-dir"
              @click="openPicker('output_dir')"
            >
              浏览
            </el-button>
          </div>
        </el-form-item>

        <el-form-item label="影像模态">
          <el-select v-model="draft.modality" data-testid="settings-modality">
            <el-option label="自动识别" value="auto" />
            <el-option label="CT" value="CT" />
            <el-option label="MRI" value="MRI" />
            <el-option label="PET" value="PET" />
          </el-select>
        </el-form-item>

        <el-form-item label="分析模型">
          <el-select v-model="draft.analysis_model" data-testid="settings-analysis-model">
            <el-option label="Logistic Regression" value="logistic" />
            <el-option label="Random Forest" value="random_forest" />
            <el-option label="XGBoost" value="xgboost" />
          </el-select>
        </el-form-item>

        <el-form-item label="协变量" class="settings-grid__wide">
          <el-input
            v-model="draft.covariates"
            placeholder="多个字段使用英文逗号分隔，例如 age, sex"
            data-testid="settings-covariates"
          />
        </el-form-item>

        <el-form-item
          label="DeepSeek API 密钥"
          class="settings-grid__wide api-key-field"
          :class="{ 'api-key-field--required': showMissingApiKey }"
        >
          <el-input
            ref="apiKeyInputRef"
            v-model="draft.api_key"
            show-password
            autocomplete="off"
            placeholder="请输入 DeepSeek API 密钥"
            data-testid="settings-api-key"
          />
          <p
            v-if="showMissingApiKey"
            class="field-hint field-hint--danger"
            data-testid="missing-api-key-hint"
          >
            尚未填写 DeepSeek API 密钥，填写并自动保存后即可新建对话。
          </p>
          <p class="field-hint field-hint--warning">
            密钥会以明文写入当前项目的 project.yaml，请勿将含密钥的配置提交或分享。
          </p>
        </el-form-item>
      </div>
    </el-form>

    <PathPickerDialog
      v-model:visible="pickerVisible"
      :model-value="pickerValue"
      :mode="pickerMode"
      :title="pickerTitle"
      :accepted-extensions="pickerExtensions"
      @select="handlePathSelected"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import type { InputInstance } from 'element-plus'
import { useProjectStore } from '@/stores/project'
import { getTheme, setTheme, type Theme } from '@/utils/theme'
import type { AnalysisConfig } from '@/api/projects'
import PathPickerDialog from '@/components/PathPickerDialog.vue'

type PathField = 'image_dir' | 'clinical_path' | 'output_dir'
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

interface SaveRequest {
  projectId: string
  config: AnalysisConfig
  serialized: string
}

const AUTOSAVE_DELAY = 600
const projectStore = useProjectStore()

const emptyConfig = (): AnalysisConfig => ({
  image_dir: '',
  clinical_path: '',
  output_dir: './outputs',
  modality: 'auto',
  covariates: '',
  model: 'logistic',
  analysis_model: 'logistic',
  api_key: '',
})

const draft = reactive<AnalysisConfig>(emptyConfig())
const currentTheme = ref<Theme>(getTheme())
const saveStatus = ref<SaveStatus>('idle')
const savedAt = ref<Date | null>(null)
const pickerVisible = ref(false)
const pickerField = ref<PathField>('image_dir')
const apiKeyInputRef = ref<InputInstance>()

let activeProjectId: string | null = null
let lastSavedSerialized = ''
let debounceTimer: ReturnType<typeof setTimeout> | null = null
let pendingSave: SaveRequest | null = null
let saveLoop: Promise<void> | null = null
let suppressDraftWatch = false

const pageTitle = computed(() =>
  projectStore.currentProject ? `设置 · ${projectStore.currentProject.name}` : '设置'
)
const showMissingApiKey = computed(
  () => {
    const projectId = projectStore.currentProject?.id
    return (
      !!projectId &&
      projectStore.apiKeyRequiredProjectId === projectId &&
      !draft.api_key.trim()
    )
  }
)
const savedTimeLabel = computed(() =>
  savedAt.value
    ? savedAt.value.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : ''
)
const pickerValue = computed(() => draft[pickerField.value])
const pickerMode = computed(() => pickerField.value === 'clinical_path' ? 'file' : 'directory')
const pickerExtensions = computed(() =>
  pickerField.value === 'clinical_path' ? ['.csv', '.xlsx', '.xls'] : []
)
const pickerTitle = computed(() => {
  const labels: Record<PathField, string> = {
    image_dir: '选择影像目录',
    clinical_path: '选择临床数据文件',
    output_dir: '选择输出目录',
  }
  return labels[pickerField.value]
})

function cloneConfig(config: AnalysisConfig): AnalysisConfig {
  const analysisModel = config.analysis_model || config.model || 'logistic'
  return {
    ...emptyConfig(),
    ...config,
    model: analysisModel,
    analysis_model: analysisModel,
  }
}

function serializeConfig(config: AnalysisConfig): string {
  return JSON.stringify(config)
}

function snapshotDraft(): AnalysisConfig {
  return cloneConfig({ ...draft })
}

function clearDebounce(): void {
  if (debounceTimer) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
}

function handleThemeChange(value: string | number | boolean): void {
  const theme: Theme = value === 'dark' ? 'dark' : 'light'
  currentTheme.value = theme
  setTheme(theme)
}

function applyProjectConfig(config: AnalysisConfig | undefined): void {
  suppressDraftWatch = true
  Object.assign(draft, cloneConfig(config ?? emptyConfig()))
  lastSavedSerialized = serializeConfig(snapshotDraft())
  saveStatus.value = 'idle'
  savedAt.value = null
  suppressDraftWatch = false
}

function makeCurrentRequest(): SaveRequest | null {
  if (!activeProjectId) return null
  const config = snapshotDraft()
  const serialized = serializeConfig(config)
  if (serialized === lastSavedSerialized) return null
  return { projectId: activeProjectId, config, serialized }
}

function enqueueSave(request: SaveRequest): Promise<void> {
  pendingSave = request
  if (!saveLoop) {
    saveLoop = drainSaveQueue().finally(() => {
      saveLoop = null
      if (pendingSave) void enqueueSave(pendingSave)
    })
  }
  return saveLoop
}

async function drainSaveQueue(): Promise<void> {
  while (pendingSave) {
    const request = pendingSave
    pendingSave = null
    if (request.projectId === activeProjectId) saveStatus.value = 'saving'
    try {
      await projectStore.saveConfig(request.projectId, request.config)
      if (request.config.api_key.trim()) {
        projectStore.clearApiKeyRequest(request.projectId)
      }
      if (request.projectId === activeProjectId) {
        lastSavedSerialized = request.serialized
        savedAt.value = new Date()
        const draftIsSaved = serializeConfig(snapshotDraft()) === request.serialized
        saveStatus.value = draftIsSaved && !pendingSave ? 'saved' : 'saving'
      }
    } catch {
      if (request.projectId === activeProjectId && !pendingSave) {
        saveStatus.value = 'error'
      }
    }
  }
}

function flushCurrent(): Promise<void> {
  clearDebounce()
  const request = makeCurrentRequest()
  return request ? enqueueSave(request) : (saveLoop ?? Promise.resolve())
}

function scheduleSave(): void {
  clearDebounce()
  if (!makeCurrentRequest()) {
    saveStatus.value = savedAt.value ? 'saved' : 'idle'
    return
  }
  saveStatus.value = 'saving'
  debounceTimer = setTimeout(() => {
    debounceTimer = null
    void flushCurrent()
  }, AUTOSAVE_DELAY)
}

function handleFieldBlur(): void {
  void flushCurrent()
}

function retrySave(): void {
  void flushCurrent()
}

function openPicker(field: PathField): void {
  pickerField.value = field
  pickerVisible.value = true
}

function handlePathSelected(path: string): void {
  draft[pickerField.value] = path
}

watch(
  () => projectStore.currentProject?.id ?? null,
  (projectId, previousProjectId) => {
    clearDebounce()
    if (previousProjectId && previousProjectId === activeProjectId) {
      const previousRequest = makeCurrentRequest()
      if (previousRequest) void enqueueSave(previousRequest)
    }
    activeProjectId = projectId
    applyProjectConfig(projectStore.currentProject?.analysis)
  },
  { immediate: true, flush: 'sync' }
)

watch(
  draft,
  () => {
    if (!suppressDraftWatch && activeProjectId) scheduleSave()
  },
  { deep: true }
)

watch(
  showMissingApiKey,
  async (required) => {
    if (!required) return
    await nextTick()
    apiKeyInputRef.value?.focus()
  },
  { immediate: true, flush: 'post' }
)

onBeforeUnmount(() => {
  void flushCurrent()
})
</script>

<style scoped>
.settings-view {
  display: flex;
  width: min(100%, 920px);
  margin: 0 auto;
  flex-direction: column;
  gap: 1rem;
}

.settings-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
  padding-bottom: 0.25rem;
}

.settings-eyebrow {
  margin: 0 0 0.25rem;
  color: var(--app-accent);
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.settings-header h2,
.settings-card h3 {
  margin: 0;
  color: var(--app-text);
}

.settings-header h2 {
  font-size: 1.375rem;
  font-weight: 650;
}

.settings-card {
  padding: 1.25rem;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-bg-panel);
  box-shadow: var(--app-shadow-sm);
}

.settings-card--appearance {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.settings-card__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.25rem;
}

.settings-card--appearance .settings-card__heading {
  margin-bottom: 0;
}

.settings-card h3 {
  font-size: 1rem;
  font-weight: 650;
}

.settings-card__heading p {
  margin: 0.25rem 0 0;
  color: var(--app-text-muted);
  font-size: 0.8125rem;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 1rem;
}

.settings-grid__wide {
  grid-column: 1 / -1;
}

.settings-grid :deep(.el-select) {
  width: 100%;
}

.path-input-row {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 0.625rem;
}

.path-input-row__field {
  min-width: 0;
  flex: 1;
}

.path-input-row__browse {
  min-width: 72px;
  flex: 0 0 auto;
}

.field-hint {
  width: 100%;
  margin: 0.375rem 0 0;
  color: var(--app-text-muted);
  font-size: 0.75rem;
  line-height: 1.5;
}

.field-hint--warning {
  color: var(--app-warning);
}

.field-hint--danger {
  color: var(--app-danger);
  font-weight: 600;
}

.api-key-field--required :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--app-danger) inset;
}

.save-status {
  display: inline-flex;
  min-height: 32px;
  align-items: center;
  gap: 0.5rem;
  color: var(--app-text-muted);
  font-size: 0.75rem;
  white-space: nowrap;
}

.save-status__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.save-status--saving {
  color: var(--app-accent);
}

.save-status--saved {
  color: var(--app-success);
}

.save-status--error {
  color: var(--app-danger);
}

.save-status__retry {
  min-height: 32px;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.save-status__retry:focus-visible {
  border-radius: var(--app-radius-sm);
  outline: 2px solid var(--app-accent);
  outline-offset: 3px;
}

@media (max-width: 680px) {
  .settings-header,
  .settings-card--appearance {
    align-items: stretch;
    flex-direction: column;
  }

  .settings-grid {
    grid-template-columns: 1fr;
  }

  .settings-grid__wide {
    grid-column: auto;
  }

  .path-input-row {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
