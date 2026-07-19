<template>
  <el-dialog
    v-model="dialogVisible"
    class="path-picker-dialog"
    :title="title"
    width="min(1280px, calc(100vw - 32px))"
    top="3dvh"
    destroy-on-close
    append-to-body
    @closed="resetTransientState"
  >
    <div class="path-picker" data-testid="path-picker">
      <aside class="path-picker__roots" aria-label="文件系统位置">
        <div class="path-picker__section-title">位置</div>
        <button
          v-for="root in roots"
          :key="root.path"
          type="button"
          class="path-picker__root"
          :class="{ 'path-picker__root--active': currentPath === root.path }"
          :title="root.path"
          @click="openDirectory(root.path)"
        >
          <el-icon><FolderOpened /></el-icon>
          <span>{{ root.name }}</span>
        </button>
      </aside>

      <section class="path-picker__browser">
        <div class="path-picker__toolbar">
          <el-button
            :icon="Back"
            :disabled="!parentPath || loading"
            title="返回上级目录"
            aria-label="返回上级目录"
            data-testid="path-picker-parent"
            @click="parentPath && openDirectory(parentPath)"
          />
          <el-button
            :icon="Refresh"
            :disabled="!currentPath || loading"
            title="刷新"
            aria-label="刷新"
            @click="currentPath && openDirectory(currentPath)"
          />
          <el-input
            v-model="pathInput"
            aria-label="目录路径"
            placeholder="输入本机目录路径"
            data-testid="path-picker-input"
            @keyup.enter="openTypedPath"
          >
            <template #append>
              <el-button data-testid="path-picker-go" @click="openTypedPath">前往</el-button>
            </template>
          </el-input>
        </div>

        <nav v-if="breadcrumbs.length" class="path-picker__breadcrumbs" aria-label="当前路径">
          <button
            v-for="crumb in breadcrumbs"
            :key="crumb.path"
            type="button"
            class="path-picker__crumb"
            @click="openDirectory(crumb.path)"
          >
            {{ crumb.name }}
          </button>
        </nav>

        <div v-loading="loading" class="path-picker__content">
          <el-alert
            v-if="errorMessage"
            :title="errorMessage"
            type="error"
            :closable="false"
            show-icon
          >
            <template #default>
              <el-button link type="primary" data-testid="path-picker-retry" @click="retry">
                重试
              </el-button>
            </template>
          </el-alert>

          <ul v-else class="path-picker__entries" aria-label="目录内容">
            <li v-if="!entries.length && !loading" class="path-picker__empty">此目录为空</li>
            <li v-for="entry in entries" :key="entry.path">
              <button
                type="button"
                class="path-picker__entry"
                :class="{
                  'path-picker__entry--selected': selectedPath === entry.path,
                  'path-picker__entry--disabled': !entry.is_dir && !isAllowedFile(entry),
                }"
                :disabled="!entry.is_dir && !isAllowedFile(entry)"
                :data-testid="entry.is_dir ? 'path-picker-directory' : 'path-picker-file'"
                @click="selectEntry(entry)"
                @dblclick="activateEntry(entry)"
              >
                <el-icon class="path-picker__entry-icon">
                  <Folder v-if="entry.is_dir" />
                  <Document v-else />
                </el-icon>
                <span>{{ entry.name }}</span>
              </button>
            </li>
          </ul>
        </div>

        <div v-if="mode === 'file'" class="path-picker__hint">
          允许的文件类型：{{ normalizedExtensions.join('、') || '所有文件' }}
        </div>
      </section>
    </div>

    <template #footer>
      <div class="path-picker__footer">
        <span class="path-picker__selection" :title="selectionForConfirm">
          {{ selectionForConfirm || '尚未选择' }}
        </span>
        <div class="path-picker__actions">
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button
            type="primary"
            :disabled="!canConfirm"
            data-testid="path-picker-confirm"
            @click="confirmSelection"
          >
            {{ mode === 'directory' ? '选择此目录' : '选择文件' }}
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Back, Document, Folder, FolderOpened, Refresh } from '@element-plus/icons-vue'
import {
  listFilesystemEntries,
  listFilesystemRoots,
  type FilesystemBreadcrumb,
  type FilesystemEntry,
  type FilesystemRoot,
} from '@/api/filesystem'

const props = withDefaults(
  defineProps<{
    visible: boolean
    modelValue?: string
    mode?: 'directory' | 'file'
    title?: string
    acceptedExtensions?: string[]
  }>(),
  {
    modelValue: '',
    mode: 'directory',
    title: '选择本机路径',
    acceptedExtensions: () => [],
  }
)

const emit = defineEmits<{
  'update:visible': [value: boolean]
  'update:modelValue': [value: string]
  select: [value: string]
}>()

const dialogVisible = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value),
})

const roots = ref<FilesystemRoot[]>([])
const currentPath = ref('')
const parentPath = ref<string | null>(null)
const pathInput = ref('')
const breadcrumbs = ref<FilesystemBreadcrumb[]>([])
const entries = ref<FilesystemEntry[]>([])
const selectedPath = ref('')
const loading = ref(false)
const errorMessage = ref('')

const normalizedExtensions = computed(() =>
  props.acceptedExtensions.map((extension) => {
    const normalized = extension.trim().toLowerCase()
    return normalized.startsWith('.') ? normalized : `.${normalized}`
  })
)

const selectionForConfirm = computed(() =>
  props.mode === 'directory' ? currentPath.value : selectedPath.value
)
const canConfirm = computed(() => Boolean(selectionForConfirm.value) && !loading.value)

watch(
  () => props.visible,
  (visible) => {
    if (visible) void initialize()
  },
  { immediate: true }
)

function errorDetail(error: unknown): string {
  const candidate = error as { response?: { data?: { detail?: string } }; message?: string }
  return candidate.response?.data?.detail || candidate.message || '无法读取该目录'
}

function isAllowedFile(entry: FilesystemEntry): boolean {
  if (entry.is_dir || normalizedExtensions.value.length === 0) return true
  const lowerName = entry.name.toLowerCase()
  return normalizedExtensions.value.some((extension) => lowerName.endsWith(extension))
}

function parentOf(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, '')
  const separatorIndex = Math.max(trimmed.lastIndexOf('\\'), trimmed.lastIndexOf('/'))
  if (separatorIndex < 0) return ''
  if (separatorIndex === 2 && /^[a-zA-Z]:/.test(trimmed)) return `${trimmed.slice(0, 2)}\\`
  return trimmed.slice(0, separatorIndex) || '/'
}

function looksLikeAcceptedFile(path: string): boolean {
  if (props.mode !== 'file' || !path) return false
  if (normalizedExtensions.value.length === 0) return true
  const lowerPath = path.toLowerCase()
  return normalizedExtensions.value.some((extension) => lowerPath.endsWith(extension))
}

async function initialize(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    roots.value = await listFilesystemRoots()
    const configuredPath = props.modelValue.trim()
    selectedPath.value = looksLikeAcceptedFile(configuredPath) ? configuredPath : ''
    const initialDirectory = selectedPath.value ? parentOf(selectedPath.value) : configuredPath
    const firstPath = initialDirectory || roots.value[0]?.path
    if (!firstPath) {
      errorMessage.value = '未找到可浏览的文件系统位置'
      return
    }
    await openDirectory(firstPath)
  } catch (error) {
    errorMessage.value = errorDetail(error)
  } finally {
    loading.value = false
  }
}

async function openDirectory(path: string): Promise<void> {
  if (!path.trim()) return
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await listFilesystemEntries(path.trim())
    currentPath.value = result.path
    parentPath.value = result.parent
    pathInput.value = result.path
    breadcrumbs.value = result.breadcrumbs
    entries.value = result.entries
    if (props.mode === 'directory') selectedPath.value = result.path
    else if (parentOf(selectedPath.value) !== result.path) selectedPath.value = ''
  } catch (error) {
    errorMessage.value = errorDetail(error)
  } finally {
    loading.value = false
  }
}

function openTypedPath(): void {
  void openDirectory(pathInput.value)
}

function selectEntry(entry: FilesystemEntry): void {
  if (entry.is_dir) {
    void openDirectory(entry.path)
  } else if (isAllowedFile(entry)) {
    selectedPath.value = entry.path
  }
}

function activateEntry(entry: FilesystemEntry): void {
  if (entry.is_dir) {
    void openDirectory(entry.path)
  } else if (isAllowedFile(entry)) {
    selectedPath.value = entry.path
    confirmSelection()
  }
}

function retry(): void {
  const path = pathInput.value || currentPath.value || roots.value[0]?.path
  if (path) void openDirectory(path)
  else void initialize()
}

function confirmSelection(): void {
  const value = selectionForConfirm.value
  if (!value) return
  emit('update:modelValue', value)
  emit('select', value)
  dialogVisible.value = false
}

function resetTransientState(): void {
  errorMessage.value = ''
  selectedPath.value = ''
}
</script>

<style scoped>
.path-picker {
  display: grid;
  grid-template-columns: minmax(170px, 220px) minmax(0, 1fr);
  height: clamp(420px, 68dvh, 720px);
  min-height: 420px;
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-bg-panel);
}

.path-picker__roots {
  padding: 1rem 0.75rem;
  overflow-y: auto;
  border-right: 1px solid var(--app-border);
  background: var(--app-sidebar-bg);
}

.path-picker__section-title {
  padding: 0 0.625rem 0.625rem;
  color: var(--app-text-muted);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.path-picker__root,
.path-picker__entry,
.path-picker__crumb {
  border: 0;
  font: inherit;
  cursor: pointer;
}

.path-picker__root {
  display: flex;
  align-items: center;
  width: 100%;
  min-height: 38px;
  gap: 0.5rem;
  padding: 0.5rem 0.625rem;
  overflow: hidden;
  border-radius: var(--app-radius-md);
  background: transparent;
  color: var(--app-text-secondary);
  text-align: left;
}

.path-picker__root span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.path-picker__root:hover,
.path-picker__root--active {
  background: var(--app-sidebar-hover);
  color: var(--app-text);
}

.path-picker__root:focus-visible,
.path-picker__entry:focus-visible,
.path-picker__crumb:focus-visible {
  outline: 2px solid var(--app-accent);
  outline-offset: -2px;
}

.path-picker__browser {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.path-picker__toolbar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  border-bottom: 1px solid var(--app-border);
}

.path-picker__toolbar .el-button + .el-button {
  margin-left: 0;
}

.path-picker__breadcrumbs {
  display: flex;
  min-height: 38px;
  align-items: center;
  gap: 0.25rem;
  padding: 0.375rem 0.75rem;
  overflow-x: auto;
  border-bottom: 1px solid var(--app-border);
}

.path-picker__crumb {
  flex: 0 0 auto;
  min-height: 30px;
  padding: 0.25rem 0.5rem;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-text-secondary);
}

.path-picker__crumb:hover {
  background: var(--app-sidebar-hover);
  color: var(--app-text);
}

.path-picker__crumb + .path-picker__crumb::before {
  margin-right: 0.5rem;
  color: var(--app-text-muted);
  content: '/';
}

.path-picker__content {
  min-height: 0;
  flex: 1;
  padding: 0.5rem;
  overflow-y: auto;
}

.path-picker__entries {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.25rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.path-picker__entry {
  display: flex;
  align-items: center;
  width: 100%;
  min-height: 42px;
  gap: 0.625rem;
  padding: 0.5rem 0.75rem;
  overflow: hidden;
  border: 1px solid transparent;
  border-radius: var(--app-radius-md);
  background: transparent;
  color: var(--app-text);
  text-align: left;
}

.path-picker__entry span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.path-picker__entry:hover {
  border-color: var(--app-border);
  background: var(--app-sidebar-hover);
}

.path-picker__entry--selected {
  border-color: var(--app-accent);
  background: var(--app-sidebar-active);
}

.path-picker__entry--disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.path-picker__entry-icon {
  flex: 0 0 auto;
  color: var(--app-accent);
  font-size: 1.125rem;
}

.path-picker__empty {
  padding: 2.5rem 1rem;
  color: var(--app-text-muted);
  text-align: center;
}

.path-picker__hint {
  padding: 0.625rem 0.75rem;
  border-top: 1px solid var(--app-border);
  color: var(--app-text-muted);
  font-size: 0.75rem;
}

.path-picker__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.path-picker__selection {
  min-width: 0;
  overflow: hidden;
  color: var(--app-text-secondary);
  font-size: 0.8125rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.path-picker__actions {
  display: flex;
  flex: 0 0 auto;
  gap: 0.5rem;
}

@media (max-width: 680px) {
  .path-picker {
    display: flex;
    grid-template-columns: 1fr;
    flex-direction: column;
    height: 64dvh;
    min-height: 320px;
  }

  .path-picker__roots {
    display: flex;
    flex: 0 0 auto;
    gap: 0.375rem;
    padding: 0.5rem;
    overflow-x: auto;
    border-right: 0;
    border-bottom: 1px solid var(--app-border);
  }

  .path-picker__section-title {
    display: none;
  }

  .path-picker__root {
    width: auto;
    min-width: max-content;
  }

  .path-picker__toolbar {
    flex-wrap: wrap;
  }

  .path-picker__browser {
    min-height: 0;
    flex: 1;
  }

  .path-picker__toolbar .el-input {
    flex-basis: 100%;
    order: 2;
  }

  .path-picker__entries {
    grid-template-columns: 1fr;
  }

  .path-picker__footer {
    align-items: stretch;
    flex-direction: column;
  }

  .path-picker__actions {
    justify-content: flex-end;
  }
}
</style>
