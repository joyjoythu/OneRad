<template>
  <div class="project-list">
    <div class="project-list-header">
      <h2>项目</h2>
      <el-button type="primary" :icon="Plus" @click="dialogVisible = true">
        新建项目
      </el-button>
    </div>

    <el-empty v-if="!projectStore.projects.length" description="暂无项目" />

    <ul v-else class="project-items">
      <li
        v-for="project in projectStore.projects"
        :key="project.id"
        :class="{ active: projectStore.currentProject?.id === project.id }"
        @click="projectStore.selectProject(project.id)"
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

    <el-dialog v-model="dialogVisible" title="新建项目" width="480px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="请输入项目名称" />
        </el-form-item>
        <el-form-item label="路径">
          <el-input v-model="form.path" placeholder="请输入项目路径" />
        </el-form-item>
        <el-form-item label="描述">
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
import { useProjectStore } from '@/stores/project'

const projectStore = useProjectStore()

const dialogVisible = ref(false)
const form = reactive({
  name: '',
  path: '',
  description: '',
})

onMounted(() => {
  projectStore.loadProjects()
})

async function handleCreate(): Promise<void> {
  const name = form.name.trim()
  const path = form.path.trim()
  if (!name || !path) return

  await projectStore.createProject({
    name,
    path,
    description: form.description.trim() || undefined,
  })

  dialogVisible.value = false
  form.name = ''
  form.path = ''
  form.description = ''
}

function handleDelete(projectId: string): void {
  if (confirm('确定要删除该项目吗？')) {
    projectStore.deleteProject(projectId)
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
}

.project-items li:hover {
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
