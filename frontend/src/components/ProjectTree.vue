<template>
  <div class="project-tree">
    <div class="project-tree-top">
      <button class="new-project-btn" data-testid="new-project" @click="dialogVisible = true">
        <el-icon><Plus /></el-icon>
        <span>新建项目</span>
      </button>
    </div>

    <div class="project-tree-group">
      <span>项目</span>
    </div>

    <el-skeleton
      v-if="projectStore.loading && !projectStore.projects.length"
      :rows="4"
      animated
      class="tree-skeleton"
    />
    <el-empty v-else-if="!projectStore.projects.length" description="暂无项目" :image-size="60" />

    <ul v-else v-auto-hide-scrollbar class="project-tree-items auto-hide-scrollbar">
      <li v-for="project in sortedProjects" :key="project.id">
        <div
          class="project-row"
          :class="{ 'project-row--active': projectStore.currentProject?.id === project.id }"
          data-testid="project-row"
          tabindex="0"
          role="button"
          @click="handleProjectClick(project)"
          @keydown.enter="handleProjectClick(project)"
        >
          <el-icon class="row-icon">
            <FolderOpened v-if="isExpanded(project.id)" />
            <Folder v-else />
          </el-icon>
          <span class="row-label">{{ project.name }}</span>
          <el-icon
            v-if="isProjectPinned(project.id)"
            class="pin-indicator"
            title="已置顶"
            data-testid="project-pinned"
          >
            <Top />
          </el-icon>
          <span class="row-actions" @click.stop>
            <el-button
              link
              size="small"
              :icon="Plus"
              title="新建对话"
              data-testid="project-new-thread"
              @click.stop="handleNewThread(project)"
            />
            <el-dropdown
              trigger="click"
              @command="(command: string) => handleProjectCommand(command, project)"
            >
              <el-button
                link
                size="small"
                :icon="More"
                title="更多操作"
                data-testid="project-more"
                @click.stop
              />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    :icon="Top"
                    command="pin"
                    data-testid="project-menu-pin"
                  >
                    {{ isProjectPinned(project.id) ? '取消置顶' : '置顶' }}
                  </el-dropdown-item>
                  <el-dropdown-item
                    :icon="Edit"
                    command="rename"
                    data-testid="project-menu-rename"
                  >
                    重命名
                  </el-dropdown-item>
                  <el-dropdown-item
                    :icon="Delete"
                    command="delete"
                    class="dropdown-item--danger"
                    data-testid="project-menu-delete"
                  >
                    删除
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </span>
        </div>

        <ul v-if="isExpanded(project.id)" class="thread-items">
          <li
            v-for="thread in threadsOf(project.id)"
            :key="thread.id"
            class="thread-row"
            :class="{ 'thread-row--active': agentStore.currentThread?.id === thread.id }"
            data-testid="thread-row"
            tabindex="0"
            role="button"
            @click="handleThreadClick(project, thread)"
            @keydown.enter="handleThreadClick(project, thread)"
          >
            <el-icon class="row-icon"><ChatDotRound /></el-icon>
            <span class="row-label">{{ thread.title || '未命名会话' }}</span>
            <el-icon
              v-if="isThreadPinned(thread.id)"
              class="pin-indicator"
              title="已置顶"
              data-testid="thread-pinned"
            >
              <Top />
            </el-icon>
            <span
              class="row-actions"
              :class="{
                'row-actions--indicator':
                  agentStore.runningThreadIds.has(thread.id) ||
                  agentStore.finishedThreadIds.has(thread.id),
              }"
              @click.stop
            >
              <span class="more-wrap">
                <el-icon
                  v-if="agentStore.runningThreadIds.has(thread.id)"
                  class="is-loading more-indicator more-indicator--spinner"
                  data-testid="thread-running"
                >
                  <Loading />
                </el-icon>
                <span
                  v-else-if="agentStore.finishedThreadIds.has(thread.id)"
                  class="more-indicator more-indicator--dot"
                  data-testid="thread-finished-dot"
                />
                <el-dropdown
                  trigger="click"
                  class="more-dropdown"
                  @command="(command: string) => handleThreadCommand(command, project, thread)"
                >
                  <el-button
                    link
                    size="small"
                    :icon="More"
                    title="更多操作"
                    data-testid="thread-more"
                    @click.stop
                  />
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item
                        :icon="Top"
                        command="pin"
                        data-testid="thread-menu-pin"
                      >
                        {{ isThreadPinned(thread.id) ? '取消置顶' : '置顶' }}
                      </el-dropdown-item>
                      <el-dropdown-item
                        :icon="Edit"
                        command="rename"
                        data-testid="thread-menu-rename"
                      >
                        重命名
                      </el-dropdown-item>
                      <el-dropdown-item
                        :icon="Delete"
                        command="delete"
                        class="dropdown-item--danger"
                        data-testid="thread-menu-delete"
                      >
                        删除
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </span>
            </span>
          </li>
          <li
            v-if="failedIds.has(project.id)"
            class="thread-retry"
            data-testid="thread-retry"
            @click="retryLoadThreads(project.id)"
          >
            加载失败，点击重试
          </li>
          <li v-else-if="threadsOf(project.id).length === 0" class="thread-empty">暂无会话</li>
        </ul>
      </li>
    </ul>

    <el-dialog
      v-model="dialogVisible"
      class="project-create-dialog"
      title="新建项目"
      width="min(640px, calc(100vw - 32px))"
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入项目名称" />
        </el-form-item>
        <el-form-item label="路径" prop="path">
          <div class="path-input-row">
            <el-input
              v-model="form.path"
              class="path-input-row__field"
              data-testid="project-path-input"
              placeholder="相对路径（如 demo）或本机绝对路径（如 D:\project）"
            />
            <el-button
              class="path-input-row__browse"
              data-testid="browse-project-path"
              @click="pathPickerVisible = true"
            >
              浏览
            </el-button>
          </div>
          <div
            class="path-hint"
            :class="{ 'path-hint--warning': pathHasNonAscii }"
            data-testid="project-path-hint"
          >
            请勿使用中文路径：pyradiomics 在中文路径下无法正常工作。
          </div>
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            placeholder="请输入项目描述"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="projectStore.loading" @click="handleCreate">
          创建
        </el-button>
      </template>
    </el-dialog>

    <PathPickerDialog
      v-model:visible="pathPickerVisible"
      :model-value="form.path"
      mode="directory"
      title="选择项目目录"
      @select="handleProjectPathSelected"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Plus,
  Edit,
  Delete,
  Folder,
  FolderOpened,
  ChatDotRound,
  Loading,
  More,
  Top,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useProjectStore } from '@/stores/project'
import { useAgentStore } from '@/stores/agent'
import { useSettingsStore } from '@/stores/settings'
import type { Project } from '@/api/projects'
import type { ThreadSummary } from '@/api/agent'
import { vAutoHideScrollbar } from '@/directives/autoHideScrollbar'
import PathPickerDialog from '@/components/PathPickerDialog.vue'

const projectStore = useProjectStore()
const agentStore = useAgentStore()
const settingsStore = useSettingsStore()
const route = useRoute()
const router = useRouter()

const dialogVisible = ref(false)
const pathPickerVisible = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({
  name: '',
  path: '',
  description: '',
})

/** 路径含中文等非 ASCII 字符时高亮提示（pyradiomics 不兼容中文路径）。 */
const pathHasNonAscii = computed(() => /[^\x00-\x7F]/.test(form.path))

const rules = reactive<FormRules>({
  name: [{ required: true, message: '请输入项目名称', trigger: 'blur' }],
  path: [
    { required: true, message: '请输入项目路径', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        if (value && /[^\x00-\x7F]/.test(value)) {
          callback(new Error('路径不能包含中文等非 ASCII 字符：pyradiomics 无法正常工作'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
})

const PINNED_PROJECTS_KEY = 'onerad:sidebar:pinnedProjects'
const PINNED_THREADS_KEY = 'onerad:sidebar:pinnedThreads'

function loadPinnedIds(key: string): Set<string> {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '[]')
    return new Set(Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : [])
  } catch {
    return new Set()
  }
}

function savePinnedIds(key: string, ids: Set<string>): void {
  try {
    localStorage.setItem(key, JSON.stringify([...ids]))
  } catch {
    // 浏览器禁用本地存储时，置顶仍在当前页面内生效。
  }
}

function sortPinned<T extends { id: string }>(items: T[], pinnedIds: Set<string>): T[] {
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const pinOrder = Number(pinnedIds.has(right.item.id)) - Number(pinnedIds.has(left.item.id))
      return pinOrder || left.index - right.index
    })
    .map(({ item }) => item)
}

const pinnedProjectIds = ref(loadPinnedIds(PINNED_PROJECTS_KEY))
const pinnedThreadIds = ref(loadPinnedIds(PINNED_THREADS_KEY))
const sortedProjects = computed(() => sortPinned(projectStore.projects, pinnedProjectIds.value))

// 展开状态：会话内存即可，刷新后默认只展开当前项目。
const expandedIds = ref<Set<string>>(new Set())

// 对话加载失败的项目集合：展示内联重试入口。
const failedIds = ref<Set<string>>(new Set())

function isExpanded(projectId: string): boolean {
  return expandedIds.value.has(projectId)
}

function threadsOf(projectId: string): ThreadSummary[] {
  return sortPinned(agentStore.threadsByProject[projectId] ?? [], pinnedThreadIds.value)
}

function isProjectPinned(projectId: string): boolean {
  return pinnedProjectIds.value.has(projectId)
}

function isThreadPinned(threadId: string): boolean {
  return pinnedThreadIds.value.has(threadId)
}

function togglePinnedId(ids: Set<string>, id: string): Set<string> {
  const next = new Set(ids)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  return next
}

function toggleProjectPin(projectId: string): void {
  pinnedProjectIds.value = togglePinnedId(pinnedProjectIds.value, projectId)
  savePinnedIds(PINNED_PROJECTS_KEY, pinnedProjectIds.value)
}

function toggleThreadPin(threadId: string): void {
  pinnedThreadIds.value = togglePinnedId(pinnedThreadIds.value, threadId)
  savePinnedIds(PINNED_THREADS_KEY, pinnedThreadIds.value)
}

onMounted(() => {
  void loadProjects()
  void settingsStore.ensureLoaded()
})

async function loadProjects(): Promise<void> {
  try {
    await projectStore.loadProjects()
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || err.message || '加载项目失败')
  }
}

// 当前项目始终保持展开（含刷新后的初始状态）。
watch(
  () => projectStore.currentProject?.id,
  (id) => {
    if (id && !expandedIds.value.has(id)) {
      expandedIds.value.add(id)
      void ensureThreadsLoaded(id)
    }
  },
  { immediate: true }
)

async function ensureThreadsLoaded(projectId: string): Promise<void> {
  if (agentStore.threadsByProject[projectId]) return
  try {
    await agentStore.loadProjectThreads(projectId)
    failedIds.value.delete(projectId)
  } catch {
    // axios 拦截器统一 toast；行内提供重试入口
    failedIds.value.add(projectId)
  }
}

async function retryLoadThreads(projectId: string): Promise<void> {
  failedIds.value.delete(projectId)
  try {
    await agentStore.loadProjectThreads(projectId)
  } catch {
    failedIds.value.add(projectId)
  }
}

async function handleProjectClick(project: Project): Promise<void> {
  const isCurrent = projectStore.currentProject?.id === project.id
  projectStore.selectProject(project.id)
  if (expandedIds.value.has(project.id)) {
    // 只有再次点击当前项目才折叠；切换到其他项目时保持展开
    if (isCurrent) {
      expandedIds.value.delete(project.id)
    }
    return
  }
  expandedIds.value.add(project.id)
  await ensureThreadsLoaded(project.id)
}

async function handleThreadClick(project: Project, thread: ThreadSummary): Promise<void> {
  if (projectStore.currentProject?.id !== project.id) {
    // 交由 AgentView 的项目切换 watcher 消费 preferredThreadId 完成加载
    agentStore.preferredThreadId = thread.id
    projectStore.selectProject(project.id)
  } else if (thread.id !== agentStore.currentThread?.id) {
    await agentStore.loadThread(thread.id)
  }
  if (route.path !== '/') {
    void router.push('/')
  }
}

async function handleNewThread(project: Project): Promise<void> {
  try {
    await settingsStore.ensureLoaded()
  } catch {
    return
  }
  if (!settingsStore.apiKeyConfigured) {
    projectStore.selectProject(project.id)
    settingsStore.requestApiKey()
    if (route.path !== '/settings') {
      await router.push('/settings')
    }
    return
  }

  const isCurrent = projectStore.currentProject?.id === project.id
  try {
    await agentStore.createThread(project.id)
  } catch {
    // axios 拦截器统一 toast；创建失败不切换项目
    return
  }
  if (!isCurrent) {
    projectStore.selectProject(project.id)
  }
  if (route.path !== '/') {
    void router.push('/')
  }
}

function handleProjectCommand(command: string, project: Project): void {
  if (command === 'pin') {
    toggleProjectPin(project.id)
  } else if (command === 'rename') {
    void handleRenameProject(project)
  } else if (command === 'delete') {
    void handleDeleteProject(project)
  }
}

function handleThreadCommand(command: string, project: Project, thread: ThreadSummary): void {
  if (command === 'pin') {
    toggleThreadPin(thread.id)
  } else if (command === 'rename') {
    void handleRenameThread(project, thread)
  } else if (command === 'delete') {
    void handleDeleteThread(project, thread)
  }
}

async function handleRenameProject(project: Project): Promise<void> {  try {
    const { value } = await ElMessageBox.prompt('请输入新名称', '重命名项目', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: project.name,
      inputValidator: (v) => (v && v.trim() ? true : '名称不能为空'),
    })
    await projectStore.renameProject(project.id, value.trim())
  } catch {
    // 用户取消；API 失败由 axios 拦截器统一 toast
  }
}

async function handleDeleteProject(project: Project): Promise<void> {
  try {
    await ElMessageBox.confirm('删除项目及其全部对话？此操作无法恢复。', '删除项目', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      customClass: 'compact-confirm-box',
    })
  } catch {
    return
  }

  const wasCurrent = projectStore.currentProject?.id === project.id
  try {
    await projectStore.deleteProject(project.id)
    agentStore.clearProjectThreads(project.id)
    expandedIds.value.delete(project.id)
    if (pinnedProjectIds.value.delete(project.id)) {
      pinnedProjectIds.value = new Set(pinnedProjectIds.value)
      savePinnedIds(PINNED_PROJECTS_KEY, pinnedProjectIds.value)
    }
    if (wasCurrent) {
      agentStore.resetThread()
    }
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || err.message || '删除项目失败')
  }
}

async function handleRenameThread(project: Project, thread: ThreadSummary): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('请输入新标题', '重命名会话', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: thread.title || '未命名会话',
      inputValidator: (v) => (v && v.trim() ? true : '标题不能为空'),
    })
    await agentStore.renameThread(thread.id, value.trim(), project.id)
  } catch {
    // 用户取消；API 失败由 axios 拦截器统一 toast
  }
}

async function handleDeleteThread(project: Project, thread: ThreadSummary): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `删除会话“${thread.title || '未命名会话'}”？此操作无法恢复。`,
      '删除会话',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        customClass: 'compact-confirm-box',
      }
    )
    await agentStore.deleteThread(thread.id, project.id)
    if (pinnedThreadIds.value.delete(thread.id)) {
      pinnedThreadIds.value = new Set(pinnedThreadIds.value)
      savePinnedIds(PINNED_THREADS_KEY, pinnedThreadIds.value)
    }
  } catch {
    // 用户取消；API 失败由 axios 拦截器统一 toast
  }
}

async function handleCreate(): Promise<void> {
  if (!formRef.value) return

  try {
    await formRef.value.validate()
  } catch {
    ElMessage.warning('请填写必填项')
    return
  }

  try {
    await projectStore.createProject({
      name: form.name.trim(),
      path: form.path.trim(),
      description: form.description.trim() || undefined,
    })

    dialogVisible.value = false
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || err.message || '创建项目失败')
  }
}

function resetForm(): void {
  form.name = ''
  form.path = ''
  form.description = ''
  formRef.value?.resetFields()
  pathPickerVisible.value = false
}

function handleProjectPathSelected(path: string): void {
  form.path = path
  // 保留原项目目录选择器的便利行为：名称为空时使用文件夹名。
  if (!form.name.trim()) {
    form.name =
      path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() ?? ''
  }
}
</script>

<style scoped>
.project-tree {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.project-tree-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.75rem 0.75rem 0.25rem;
}

.new-project-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
  min-height: 38px;
  padding: 0.375rem 0.75rem;
  border: 1px solid var(--app-border-strong);
  border-radius: var(--app-radius-lg);
  background: var(--app-bg-panel);
  color: var(--app-accent-active);
  font-size: 0.8125rem;
  font-weight: 600;
  cursor: pointer;
  box-shadow: var(--app-shadow-sm);
  transition: background-color 0.16s ease, border-color 0.16s ease,
    box-shadow 0.16s ease, transform 0.12s ease;
}

.new-project-btn:hover {
  border-color: var(--app-accent);
  background-color: var(--app-sidebar-hover);
}

.new-project-btn:active {
  transform: translateY(1px);
}

.new-project-btn:focus-visible {
  outline: 3px solid var(--app-focus-ring);
  outline-offset: 1px;
}

.project-tree-group {
  display: flex;
  align-items: center;
  padding: 0.75rem 1rem 0.375rem;
  font-size: 0.75rem;
  color: var(--app-text-muted);
}

.tree-skeleton {
  padding: 1rem;
}

/* 创建项目对话框：路径输入与「选择文件夹」按钮同行 */
.path-input-row {
  display: flex;
  gap: 0.5rem;
  width: 100%;
}

.path-input-row .el-input {
  flex: 1;
}

.path-hint {
  width: 100%;
  margin-top: 0.25rem;
  font-size: 0.75rem;
  line-height: 1.4;
  color: var(--app-text-muted);
}

.path-hint--warning {
  color: var(--el-color-warning);
  font-weight: 500;
}

.project-tree-items {
  list-style: none;
  margin: 0;
  padding: 0 0.5rem 0.5rem;
  overflow-y: auto;
  flex: 1;
}

.project-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 38px;
  padding: 0.4375rem 0.625rem;
  border-radius: var(--app-radius-md);
  cursor: pointer;
  transition: background-color 0.2s;
  outline: none;
}

.project-row:hover {
  background-color: var(--app-sidebar-hover);
}

.project-row:focus-visible {
  outline: 2px solid var(--app-accent);
  outline-offset: -2px;
}

.project-row--active {
  background-color: var(--app-sidebar-active);
}

.project-row--active .row-label {
  font-weight: 600;
}

.row-icon {
  flex-shrink: 0;
  color: var(--app-text-muted);
}

.pin-indicator {
  flex: 0 0 auto;
  color: var(--app-accent-active);
  font-size: 0.75rem;
}

.row-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-text);
  font-size: 0.875rem;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 0.125rem;
  opacity: 0;
  transition: opacity 0.2s;
}

.project-row:hover .row-actions,
.project-row:focus-within .row-actions,
.project-row--active .row-actions,
.thread-row:hover .row-actions,
.thread-row:focus-within .row-actions,
.thread-row--active .row-actions,
.thread-row .row-actions--indicator {
  opacity: 1;
}

.row-actions .el-button,
.row-actions .el-dropdown .el-button {
  margin-left: 0;
}

/* 运行中/完成未读：转圈或提示点占据「更多操作」按钮的位置
   （按钮保留占位但隐藏），光标移到指示符上时才换出按钮供操作 */
.more-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.more-indicator {
  position: absolute;
  inset: 0;
}

.more-indicator--spinner {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  /* el-icon 自带 height/width: 1em：绝对定位 + inset:0 时显式高度会
     让盒子贴顶（over-constrained 时 top 生效、bottom 被忽略），
     重置为 auto 才能随父盒拉伸、把图标真正居中到按钮位置 */
  width: auto;
  height: auto;
  color: var(--app-text-muted);
}

/* 8px 圆点：absolute + inset + margin auto 使固定尺寸在按钮盒内居中 */
.more-indicator--dot {
  width: 8px;
  height: 8px;
  margin: auto;
  border-radius: 50%;
  background-color: var(--app-accent);
}

.row-actions--indicator .more-dropdown {
  visibility: hidden;
}

.row-actions--indicator .more-wrap:hover .more-dropdown {
  visibility: visible;
}

.row-actions--indicator .more-wrap:hover .more-indicator {
  display: none;
}

.thread-items {
  list-style: none;
  margin: 0.25rem 0 0;
  padding: 0 0 0.25rem 1.25rem;
}

.thread-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 36px;
  padding: 0.375rem 0.625rem;
  border-radius: var(--app-radius-md);
  cursor: pointer;
  transition: background-color 0.2s;
}

.thread-row:hover {
  background-color: var(--app-sidebar-hover);
}

.thread-row:focus-visible {
  outline: 2px solid var(--app-accent);
  outline-offset: -2px;
}

.thread-row--active {
  background-color: var(--app-sidebar-active);
}

.thread-row--active .row-label {
  font-weight: 600;
}

.thread-empty {
  padding: 0.375rem 0.625rem;
  font-size: 0.75rem;
  color: var(--app-text-muted);
}

.thread-retry {
  padding: 0.375rem 0.625rem;
  font-size: 0.75rem;
  color: var(--app-text-secondary);
  border-radius: var(--app-radius-md);
  cursor: pointer;
}

.thread-retry:hover {
  background-color: var(--app-sidebar-hover);
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

:global(.project-create-dialog) {
  max-width: calc(100vw - 2rem);
  border-radius: 16px;
}

@media (max-width: 560px) {
  :global(.project-create-dialog .el-dialog__body) {
    padding-inline: 1rem;
  }

  :global(.project-create-dialog .el-form-item) {
    display: block;
  }

  :global(.project-create-dialog .el-form-item__label) {
    width: auto !important;
  }

  .path-input-row {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
