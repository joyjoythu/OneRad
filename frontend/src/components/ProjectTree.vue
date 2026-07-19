<template>
  <div class="project-tree">
    <div class="project-tree-top">
      <button class="new-task-btn" data-testid="new-task" @click="handleNewTask">
        <el-icon><Plus /></el-icon>
        <span>新建任务</span>
      </button>
    </div>

    <div class="project-tree-group">
      <span>项目</span>
      <el-button
        link
        size="small"
        :icon="FolderAdd"
        data-testid="new-project"
        title="新建项目"
        @click="dialogVisible = true"
      />
    </div>

    <el-skeleton
      v-if="projectStore.loading && !projectStore.projects.length"
      :rows="4"
      animated
      class="tree-skeleton"
    />
    <el-empty v-else-if="!projectStore.projects.length" description="暂无项目" :image-size="60" />

    <ul v-else v-auto-hide-scrollbar class="project-tree-items auto-hide-scrollbar">
      <li v-for="project in projectStore.projects" :key="project.id">
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
          <el-input
            v-model="form.path"
            placeholder="相对路径（如 demo）或本机绝对路径（如 D:\project）"
          >
            <template #append>
              <el-button data-testid="browse-project-path" @click="pathPickerVisible = true">
                浏览
              </el-button>
            </template>
          </el-input>
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
      @select="form.path = $event"
    />
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Plus,
  Edit,
  Delete,
  Folder,
  FolderOpened,
  FolderAdd,
  ChatDotRound,
  Loading,
  More,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useProjectStore } from '@/stores/project'
import { useAgentStore } from '@/stores/agent'
import type { Project } from '@/api/projects'
import type { ThreadSummary } from '@/api/agent'
import { vAutoHideScrollbar } from '@/directives/autoHideScrollbar'
import PathPickerDialog from '@/components/PathPickerDialog.vue'

const projectStore = useProjectStore()
const agentStore = useAgentStore()
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

const rules = reactive<FormRules>({
  name: [{ required: true, message: '请输入项目名称', trigger: 'blur' }],
  path: [{ required: true, message: '请输入项目路径', trigger: 'blur' }],
})

// 展开状态：会话内存即可，刷新后默认只展开当前项目。
const expandedIds = ref<Set<string>>(new Set())

// 对话加载失败的项目集合：展示内联重试入口。
const failedIds = ref<Set<string>>(new Set())

function isExpanded(projectId: string): boolean {
  return expandedIds.value.has(projectId)
}

function threadsOf(projectId: string): ThreadSummary[] {
  return agentStore.threadsByProject[projectId] ?? []
}

onMounted(() => {
  loadProjects()
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
    await agentStore.loadThread(thread.id, project.analysis.api_key)
  }
  if (route.path !== '/') {
    void router.push('/')
  }
}

function handleNewTask(): void {
  const project = projectStore.currentProject
  if (!project) {
    ElMessage.warning('请先选择项目')
    return
  }
  void handleNewThread(project)
}

async function handleNewThread(project: Project): Promise<void> {
  const isCurrent = projectStore.currentProject?.id === project.id
  try {
    await agentStore.createThread(project.id, project.analysis.api_key)
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
  if (command === 'rename') {
    void handleRenameProject(project)
  } else if (command === 'delete') {
    void handleDeleteProject(project)
  }
}

function handleThreadCommand(command: string, project: Project, thread: ThreadSummary): void {
  if (command === 'rename') {
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
    await ElMessageBox.confirm('确定要删除该项目吗？其下的会话将一并删除。', '提示', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }

  const wasCurrent = projectStore.currentProject?.id === project.id
  try {
    await projectStore.deleteProject(project.id)
    agentStore.clearProjectThreads(project.id)
    expandedIds.value.delete(project.id)
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
      `确定要删除会话 "${thread.title || '未命名会话'}" 吗？删除后无法恢复。`,
      '删除会话',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    await agentStore.deleteThread(thread.id, project.id)
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

.new-task-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--app-border-strong);
  border-radius: var(--app-radius-lg);
  background: transparent;
  color: var(--app-text);
  font-size: 0.75rem;
  cursor: pointer;
  transition: background-color 0.2s;
}

.new-task-btn:hover {
  background-color: var(--app-sidebar-hover);
}

.project-tree-group {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem 0.375rem;
  font-size: 0.75rem;
  color: var(--app-text-muted);
}

.project-tree-group .el-button {
  color: var(--app-text-muted);
}

.project-tree-group .el-button:hover {
  color: var(--app-text);
}

.tree-skeleton {
  padding: 1rem;
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
  margin: 0;
  padding: 0 0 0.25rem 1.25rem;
}

.thread-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
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
}
</style>
