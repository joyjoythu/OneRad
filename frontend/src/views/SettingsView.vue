<template>
  <div class="settings-view">
    <header class="settings-header">
      <div>
        <p class="settings-eyebrow">OneRad workspace</p>
        <h2>设置</h2>
        <p class="settings-intro">管理应用级偏好。</p>
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
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { InputInstance } from 'element-plus'
import { useSettingsStore } from '@/stores/settings'
import { getTheme, setTheme, type Theme } from '@/utils/theme'

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

const AUTOSAVE_DELAY = 600
const settingsStore = useSettingsStore()

const currentTheme = ref<Theme>(getTheme())
const generalApiKey = ref('')
const apiKeyInputRef = ref<InputInstance>()
const generalSaveStatus = ref<SaveStatus>('idle')
const generalSavedAt = ref<Date | null>(null)

let lastGeneralSaved = ''
let generalDebounceTimer: ReturnType<typeof setTimeout> | null = null
let pendingGeneralSave: string | null = null
let generalSaveLoop: Promise<void> | null = null
let suppressGeneralWatch = true

const generalSavedTimeLabel = computed(() => formatSavedTime(generalSavedAt.value))
const showMissingApiKey = computed(
  () => settingsStore.apiKeyRequired && !settingsStore.apiKeyConfigured && !generalApiKey.value.trim()
)
const apiKeyFromEnvironment = computed(
  () => settingsStore.settings.api_key_source === 'environment'
)

function formatSavedTime(value: Date | null): string {
  return value
    ? value.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : ''
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
  .settings-section__header {
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
}
</style>
