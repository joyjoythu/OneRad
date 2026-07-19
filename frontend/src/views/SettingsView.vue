<template>
  <div class="settings-view">
    <header class="settings-header">
      <div>
        <p class="settings-eyebrow">OneRad workspace</p>
        <h2>设置</h2>
        <p class="settings-intro">管理应用级偏好，以及当前研究项目的分析参数。</p>
      </div>
    </header>

    <section class="settings-section" aria-labelledby="general-settings-title">
      <div class="settings-section__header">
        <div>
          <p class="settings-section__index">01</p>
          <div>
            <h3 id="general-settings-title">通用设置</h3>
            <p>应用于所有项目和会话。</p>
          </div>
        </div>
        <div
          class="save-status"
          :class="`save-status--${generalSaveStatus}`"
          role="status"
          data-testid="general-save-status"
        >
          <span class="save-status__dot" />
          <template v-if="generalSaveStatus === 'saving'">保存中</template>
          <template v-else-if="generalSaveStatus === 'saved'">
            已保存 {{ generalSavedTimeLabel }}
          </template>
          <button
            v-else-if="generalSaveStatus === 'error'"
            type="button"
            class="save-status__retry"
            data-testid="general-save-retry"
            @click="retryGeneralSave"
          >
            保存失败 · 重试
          </button>
          <template v-else>自动保存</template>
        </div>
      </div>

      <div class="settings-card general-settings-card">
        <div class="general-setting-row">
          <div class="general-setting-row__copy">
            <h4>界面外观</h4>
            <p>主题偏好仅保存在当前浏览器。</p>
          </div>
          <el-radio-group
            :model-value="currentTheme"
            aria-label="主题外观"
            @change="handleThemeChange"
          >
            <el-radio-button value="light">浅色</el-radio-button>
            <el-radio-button value="dark">深色</el-radio-button>
          </el-radio-group>
        </div>

        <div class="general-setting-divider" />

        <div class="general-setting-row general-setting-row--api">
          <div class="general-setting-row__copy">
            <h4>DeepSeek API 密钥</h4>
            <p>统一用于所有项目的会话、标题生成与报告润色。</p>
          </div>
          <div
            class="api-key-control"
            :class="{ 'api-key-control--required': showMissingApiKey }"
          >
            <el-input
              ref="apiKeyInputRef"
              v-model="generalApiKey"
              show-password
              autocomplete="off"
              placeholder="请输入 DeepSeek API 密钥"
              data-testid="settings-api-key"
              :disabled="settingsStore.loading"
              @blur="flushGeneralSettings"
            />
            <p
              v-if="showMissingApiKey"
              class="field-hint field-hint--danger"
              data-testid="missing-api-key-hint"
            >
              尚未填写 DeepSeek API 密钥，填写并自动保存后即可新建对话。
            </p>
            <p v-else-if="apiKeyFromEnvironment" class="field-hint field-hint--success">
              已通过环境变量 DEEPSEEK_API_KEY 配置；这里填写的密钥将优先使用。
            </p>
            <p class="field-hint field-hint--warning">
              密钥会以明文写入 OneRad 通用配置 settings.yaml，请勿提交或分享该文件。
            </p>
          </div>
        </div>
      </div>
    </section>

    <section class="settings-section" aria-labelledby="project-settings-title">
      <div class="settings-section__header">
        <div>
          <p class="settings-section__index">02</p>
          <div>
            <h3 id="project-settings-title">项目设置</h3>
            <p>仅影响当前项目的影像组学分析流程。</p>
          </div>
        </div>
        <div class="project-settings-meta">
          <span v-if="projectStore.currentProject" class="project-chip">
            {{ projectStore.currentProject.name }}
          </span>
          <div
            v-if="projectStore.currentProject"
            class="save-status"
            :class="`save-status--${projectSaveStatus}`"
            role="status"
            data-testid="project-save-status"
          >
            <span class="save-status__dot" />
            <template v-if="projectSaveStatus === 'saving'">保存中</template>
            <template v-else-if="projectSaveStatus === 'saved'">
              已保存 {{ projectSavedTimeLabel }}
            </template>
            <button
              v-else-if="projectSaveStatus === 'error'"
              type="button"
              class="save-status__retry"
              data-testid="project-save-retry"
              @click="retryProjectSave"
            >
              保存失败 · 重试
            </button>
            <template v-else>自动保存</template>
          </div>
        </div>
      </div>

      <el-empty
        v-if="!projectStore.currentProject"
        class="settings-card project-empty"
        description="请先从左侧选择一个项目"
      />

      <el-form
        v-else
        class="settings-card settings-form"
        label-position="top"
        @focusout="handleProjectFieldBlur"
      >
        <div class="settings-grid">
          <el-form-item label="影像目录" class="settings-grid__wide">
            <div class="path-input-row">
              <el-input
                v-model="projectDraft.image_dir"
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
                v-model="projectDraft.clinical_path"
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
                v-model="projectDraft.output_dir"
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
            <el-select v-model="projectDraft.modality" data-testid="settings-modality">
              <el-option label="自动识别" value="auto" />
              <el-option label="CT" value="CT" />
              <el-option label="MRI" value="MRI" />
              <el-option label="PET" value="PET" />
            </el-select>
          </el-form-item>

          <el-form-item label="分析模型">
            <el-select
              v-model="projectDraft.analysis_model"
              data-testid="settings-analysis-model"
            >
              <el-option label="Logistic Regression" value="logistic" />
              <el-option label="Random Forest" value="random_forest" />
              <el-option label="XGBoost" value="xgboost" />
            </el-select>
          </el-form-item>

          <el-form-item label="协变量" class="settings-grid__wide">
            <el-input
              v-model="projectDraft.covariates"
              placeholder="多个字段使用英文逗号分隔，例如 age, sex"
              data-testid="settings-covariates"
            />
          </el-form-item>
        </div>
      </el-form>
    </section>

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
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { InputInstance } from 'element-plus'
import { useProjectStore } from '@/stores/project'
import { useSettingsStore } from '@/stores/settings'
import { getTheme, setTheme, type Theme } from '@/utils/theme'
import type { AnalysisConfig } from '@/api/projects'
import PathPickerDialog from '@/components/PathPickerDialog.vue'

type PathField = 'image_dir' | 'clinical_path' | 'output_dir'
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

interface ProjectSaveRequest {
  projectId: string
  config: AnalysisConfig
  serialized: string
}

const AUTOSAVE_DELAY = 600
const projectStore = useProjectStore()
const settingsStore = useSettingsStore()

const emptyProjectConfig = (): AnalysisConfig => ({
  image_dir: '',
  clinical_path: '',
  output_dir: './outputs',
  modality: 'auto',
  covariates: '',
  model: 'logistic',
  analysis_model: 'logistic',
})

const projectDraft = reactive<AnalysisConfig>(emptyProjectConfig())
const currentTheme = ref<Theme>(getTheme())
const generalApiKey = ref('')
const apiKeyInputRef = ref<InputInstance>()
const generalSaveStatus = ref<SaveStatus>('idle')
const projectSaveStatus = ref<SaveStatus>('idle')
const generalSavedAt = ref<Date | null>(null)
const projectSavedAt = ref<Date | null>(null)
const pickerVisible = ref(false)
const pickerField = ref<PathField>('image_dir')

let activeProjectId: string | null = null
let lastProjectSavedSerialized = ''
let projectDebounceTimer: ReturnType<typeof setTimeout> | null = null
let pendingProjectSave: ProjectSaveRequest | null = null
let projectSaveLoop: Promise<void> | null = null
let suppressProjectWatch = false

let lastGeneralSaved = ''
let generalDebounceTimer: ReturnType<typeof setTimeout> | null = null
let pendingGeneralSave: string | null = null
let generalSaveLoop: Promise<void> | null = null
let suppressGeneralWatch = true

const generalSavedTimeLabel = computed(() => formatSavedTime(generalSavedAt.value))
const projectSavedTimeLabel = computed(() => formatSavedTime(projectSavedAt.value))
const showMissingApiKey = computed(
  () => settingsStore.apiKeyRequired && !settingsStore.apiKeyConfigured && !generalApiKey.value.trim()
)
const apiKeyFromEnvironment = computed(
  () => settingsStore.settings.api_key_source === 'environment'
)
const pickerValue = computed(() => projectDraft[pickerField.value])
const pickerMode = computed(() => pickerField.value === 'clinical_path' ? 'file' : 'directory')
const pickerExtensions = computed(() =>
  pickerField.value === 'clinical_path' ? ['.csv', '.xlsx', '.xls'] : []
)
const pickerTitle = computed(() => ({
  image_dir: '选择影像目录',
  clinical_path: '选择临床数据文件',
  output_dir: '选择输出目录',
})[pickerField.value])

function formatSavedTime(value: Date | null): string {
  return value
    ? value.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : ''
}

function cloneProjectConfig(config: AnalysisConfig): AnalysisConfig {
  const analysisModel = config.analysis_model || config.model || 'logistic'
  return {
    ...emptyProjectConfig(),
    ...config,
    model: analysisModel,
    analysis_model: analysisModel,
  }
}

function snapshotProjectDraft(): AnalysisConfig {
  return cloneProjectConfig({ ...projectDraft })
}

function serializeProjectConfig(config: AnalysisConfig): string {
  return JSON.stringify(config)
}

function handleThemeChange(value: string | number | boolean): void {
  const theme: Theme = value === 'dark' ? 'dark' : 'light'
  currentTheme.value = theme
  setTheme(theme)
}

function clearGeneralDebounce(): void {
  if (generalDebounceTimer) {
    clearTimeout(generalDebounceTimer)
    generalDebounceTimer = null
  }
}

function scheduleGeneralSave(): void {
  clearGeneralDebounce()
  if (generalApiKey.value === lastGeneralSaved) {
    generalSaveStatus.value = generalSavedAt.value ? 'saved' : 'idle'
    return
  }
  generalSaveStatus.value = 'saving'
  generalDebounceTimer = setTimeout(() => {
    generalDebounceTimer = null
    void flushGeneralSettings()
  }, AUTOSAVE_DELAY)
}

function enqueueGeneralSave(apiKey: string): Promise<void> {
  pendingGeneralSave = apiKey
  if (!generalSaveLoop) {
    generalSaveLoop = drainGeneralSaveQueue().finally(() => {
      generalSaveLoop = null
      if (pendingGeneralSave !== null) void enqueueGeneralSave(pendingGeneralSave)
    })
  }
  return generalSaveLoop
}

async function drainGeneralSaveQueue(): Promise<void> {
  while (pendingGeneralSave !== null) {
    const apiKey = pendingGeneralSave
    pendingGeneralSave = null
    generalSaveStatus.value = 'saving'
    try {
      await settingsStore.saveApiKey(apiKey)
      lastGeneralSaved = apiKey
      generalSavedAt.value = new Date()
      generalSaveStatus.value = generalApiKey.value === apiKey && pendingGeneralSave === null
        ? 'saved'
        : 'saving'
    } catch {
      if (pendingGeneralSave === null) generalSaveStatus.value = 'error'
    }
  }
}

function flushGeneralSettings(): Promise<void> {
  clearGeneralDebounce()
  if (generalApiKey.value === lastGeneralSaved) return generalSaveLoop ?? Promise.resolve()
  return enqueueGeneralSave(generalApiKey.value)
}

function retryGeneralSave(): void {
  void flushGeneralSettings()
}

function clearProjectDebounce(): void {
  if (projectDebounceTimer) {
    clearTimeout(projectDebounceTimer)
    projectDebounceTimer = null
  }
}

function applyProjectConfig(config: AnalysisConfig | undefined): void {
  suppressProjectWatch = true
  Object.assign(projectDraft, cloneProjectConfig(config ?? emptyProjectConfig()))
  lastProjectSavedSerialized = serializeProjectConfig(snapshotProjectDraft())
  projectSaveStatus.value = 'idle'
  projectSavedAt.value = null
  suppressProjectWatch = false
}

function makeProjectSaveRequest(): ProjectSaveRequest | null {
  if (!activeProjectId) return null
  const config = snapshotProjectDraft()
  const serialized = serializeProjectConfig(config)
  if (serialized === lastProjectSavedSerialized) return null
  return { projectId: activeProjectId, config, serialized }
}

function enqueueProjectSave(request: ProjectSaveRequest): Promise<void> {
  pendingProjectSave = request
  if (!projectSaveLoop) {
    projectSaveLoop = drainProjectSaveQueue().finally(() => {
      projectSaveLoop = null
      if (pendingProjectSave) void enqueueProjectSave(pendingProjectSave)
    })
  }
  return projectSaveLoop
}

async function drainProjectSaveQueue(): Promise<void> {
  while (pendingProjectSave) {
    const request = pendingProjectSave
    pendingProjectSave = null
    if (request.projectId === activeProjectId) projectSaveStatus.value = 'saving'
    try {
      await projectStore.saveConfig(request.projectId, request.config)
      if (request.projectId === activeProjectId) {
        lastProjectSavedSerialized = request.serialized
        projectSavedAt.value = new Date()
        const draftIsSaved = serializeProjectConfig(snapshotProjectDraft()) === request.serialized
        projectSaveStatus.value = draftIsSaved && !pendingProjectSave ? 'saved' : 'saving'
      }
    } catch {
      if (request.projectId === activeProjectId && !pendingProjectSave) {
        projectSaveStatus.value = 'error'
      }
    }
  }
}

function flushProjectSettings(): Promise<void> {
  clearProjectDebounce()
  const request = makeProjectSaveRequest()
  return request ? enqueueProjectSave(request) : (projectSaveLoop ?? Promise.resolve())
}

function scheduleProjectSave(): void {
  clearProjectDebounce()
  if (!makeProjectSaveRequest()) {
    projectSaveStatus.value = projectSavedAt.value ? 'saved' : 'idle'
    return
  }
  projectSaveStatus.value = 'saving'
  projectDebounceTimer = setTimeout(() => {
    projectDebounceTimer = null
    void flushProjectSettings()
  }, AUTOSAVE_DELAY)
}

function handleProjectFieldBlur(): void {
  void flushProjectSettings()
}

function retryProjectSave(): void {
  void flushProjectSettings()
}

function openPicker(field: PathField): void {
  pickerField.value = field
  pickerVisible.value = true
}

function handlePathSelected(path: string): void {
  projectDraft[pickerField.value] = path
}

watch(
  () => projectStore.currentProject?.id ?? null,
  (projectId, previousProjectId) => {
    clearProjectDebounce()
    if (previousProjectId && previousProjectId === activeProjectId) {
      const previousRequest = makeProjectSaveRequest()
      if (previousRequest) void enqueueProjectSave(previousRequest)
    }
    activeProjectId = projectId
    applyProjectConfig(projectStore.currentProject?.analysis)
  },
  { immediate: true, flush: 'sync' }
)

watch(
  projectDraft,
  () => {
    if (!suppressProjectWatch && activeProjectId) scheduleProjectSave()
  },
  { deep: true }
)

watch(generalApiKey, () => {
  if (!suppressGeneralWatch) scheduleGeneralSave()
})

watch(
  showMissingApiKey,
  async (required) => {
    if (!required) return
    await nextTick()
    apiKeyInputRef.value?.focus()
  },
  { immediate: true, flush: 'post' }
)

onMounted(async () => {
  try {
    await settingsStore.ensureLoaded()
    generalApiKey.value = settingsStore.settings.api_key
    lastGeneralSaved = generalApiKey.value
    generalSaveStatus.value = 'idle'
  } finally {
    suppressGeneralWatch = false
  }
})

onBeforeUnmount(() => {
  void flushGeneralSettings()
  void flushProjectSettings()
})
</script>

<style scoped>
.settings-view {
  display: flex;
  width: min(100%, 960px);
  margin: 0 auto;
  flex-direction: column;
  gap: 1.5rem;
  padding-bottom: 1rem;
}

.settings-header {
  padding-bottom: 0.25rem;
}

.settings-eyebrow,
.settings-section__index {
  margin: 0 0 0.25rem;
  color: var(--app-accent);
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.settings-header h2,
.settings-section h3,
.general-setting-row h4 {
  margin: 0;
  color: var(--app-text);
}

.settings-header h2 {
  font-size: 1.5rem;
  font-weight: 680;
}

.settings-intro {
  margin: 0.375rem 0 0;
  color: var(--app-text-muted);
  font-size: 0.875rem;
}

.settings-section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.settings-section__header {
  display: flex;
  min-height: 44px;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
  padding: 0 0.25rem;
}

.settings-section__header > div:first-child {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.settings-section__index {
  min-width: 1.5rem;
  margin-top: 0.2rem;
}

.settings-section h3 {
  font-size: 1.0625rem;
  font-weight: 680;
}

.settings-section__header p:not(.settings-section__index) {
  margin: 0.25rem 0 0;
  color: var(--app-text-muted);
  font-size: 0.8125rem;
}

.settings-card {
  padding: 1.25rem;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-bg-panel);
  box-shadow: var(--app-shadow-sm);
}

.general-settings-card {
  display: flex;
  flex-direction: column;
}

.general-setting-row {
  display: grid;
  grid-template-columns: minmax(220px, 0.7fr) minmax(280px, 1.3fr);
  align-items: center;
  gap: 2rem;
}

.general-setting-row__copy h4 {
  font-size: 0.9375rem;
  font-weight: 650;
}

.general-setting-row__copy p {
  margin: 0.3rem 0 0;
  color: var(--app-text-muted);
  font-size: 0.8125rem;
  line-height: 1.5;
}

.general-setting-row > :last-child {
  justify-self: end;
}

.general-setting-row--api {
  align-items: start;
}

.general-setting-row--api > :last-child {
  width: 100%;
  justify-self: stretch;
}

.general-setting-divider {
  height: 1px;
  margin: 1.125rem 0;
  background: var(--app-border);
}

.api-key-control {
  width: 100%;
}

.api-key-control--required :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--app-danger) inset;
}

.project-settings-meta {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.project-chip {
  max-width: 220px;
  padding: 0.25rem 0.625rem;
  overflow: hidden;
  border: 1px solid var(--app-border-strong);
  border-radius: 999px;
  background: var(--app-bg-panel);
  color: var(--app-text-secondary);
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-empty {
  min-height: 180px;
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

.field-hint--success {
  color: var(--app-success);
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
  .settings-section__header,
  .project-settings-meta {
    align-items: stretch;
    flex-direction: column;
  }

  .general-setting-row {
    grid-template-columns: 1fr;
    gap: 0.875rem;
  }

  .general-setting-row > :last-child {
    justify-self: stretch;
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
