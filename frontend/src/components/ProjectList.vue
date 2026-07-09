<template>
  <div class="project-list">
    <div class="project-list-header">
      <h2>项目</h2>
      <el-button type="primary" :icon="Plus" @click="dialogVisible = true">
        新建项目
      </el-button>
    </div>

    <el-skeleton
      v-if="projectStore.loading && !projectStore.projects.length"
      :rows="4"
      animated
      class="project-skeleton"
    />

    <el-empty v-else-if="!projectStore.projects.length" description="暂无项目" />

    <ul v-else class="project-items">
      <li
        v-for="project in projectStore.projects"
        :key="project.id"
        :class="{ active: projectStore.currentProject?.id === project.id }"
        tabindex="0"
        role="button"
        @click="projectStore.selectProject(project.id)"
        @keydown.enter="projectStore.selectProject(project.id)"
        @keydown.space.prevent="projectStore.selectProject(project.id)"
      >
        <div class="project-info">
          <div class="project-name">{{ project.name }}</div>
          <div class="project-path">{{ project.path }}</div>
        </div>
        <el-button
          type="danger"
          link
          size="small"
          @click.stop="handleDelete(project.id)"
        >
          删除
        </el-button>
      </li>
    </ul>

    <el-dialog v-model="dialogVisible" title="新建项目" width="480px" @closed="resetForm">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入项目名称" />
        </el-form-item>
        <el-form-item label="路径" prop="path">
          <el-input v-model="form.path" placeholder="请输入项目路径" />
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
        <el-button
          type="primary"
          :loading="projectStore.loading"
          @click="handleCreate"
        >
          创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useProjectStore } from '@/stores/project'

const projectStore = useProjectStore()

const dialogVisible = ref(false)
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
}

async function handleDelete(projectId: string): Promise<void> {
  try {
    await ElMessageBox.confirm('确定要删除该项目吗？', '提示', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }

  try {
    await projectStore.deleteProject(projectId)
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || err.message || '删除项目失败')
  }
}
</script>

<style scoped>
.project-list {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.project-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem;
  border-bottom: 1px solid #e4e7ed;
}

.project-list-header h2 {
  margin: 0;
  font-size: 1.125rem;
}

.project-skeleton {
  padding: 1rem;
}

.project-items {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  flex: 1;
}

.project-items li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #ebeef5;
  cursor: pointer;
  transition: background-color 0.2s;
  outline: none;
}

.project-items li:hover {
  background-color: #f5f7fa;
}

.project-items li:focus-visible {
  outline: 2px solid #409eff;
  outline-offset: -2px;
  background-color: #f5f7fa;
}

.project-items li.active {
  background-color: #ecf5ff;
}

.project-info {
  min-width: 0;
}

.project-name {
  font-weight: 500;
  color: #303133;
}

.project-path {
  font-size: 0.75rem;
  color: #909399;
  margin-top: 0.25rem;
  word-break: break-all;
}
</style>
