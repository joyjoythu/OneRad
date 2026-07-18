import { ref } from 'vue'
import { defineStore } from 'pinia'
import * as api from '@/api/projects'
import type { Project, AnalysisConfig } from '@/api/projects'

export const useProjectStore = defineStore('project', () => {
  const projects = ref<Project[]>([])
  const currentProject = ref<Project | null>(null)
  const currentConfig = ref<AnalysisConfig | null>(null)
  const loading = ref(false)

  async function loadProjects(): Promise<void> {
    loading.value = true
    try {
      projects.value = await api.listProjects()
    } finally {
      loading.value = false
    }
  }

  function selectProject(projectId: string): void {
    const project = projects.value.find((p) => p.id === projectId) || null
    currentProject.value = project
    currentConfig.value = project ? { ...project.analysis } : null
  }

  async function createProject(payload: api.CreateProjectRequest): Promise<Project> {
    loading.value = true
    try {
      const project = await api.createProject(payload)
      projects.value.unshift(project)
      selectProject(project.id)
      return project
    } finally {
      loading.value = false
    }
  }

  async function deleteProject(projectId: string): Promise<void> {
    loading.value = true
    try {
      await api.deleteProject(projectId)
      projects.value = projects.value.filter((p) => p.id !== projectId)
      if (currentProject.value?.id === projectId) {
        currentProject.value = null
        currentConfig.value = null
      }
    } finally {
      loading.value = false
    }
  }

  async function saveConfig(
    projectId: string,
    config: AnalysisConfig
  ): Promise<Project> {
    loading.value = true
    try {
      const updated = await api.updateConfig(projectId, config)
      const idx = projects.value.findIndex((p) => p.id === projectId)
      if (idx >= 0) {
        projects.value[idx] = updated
      }
      if (currentProject.value?.id === projectId) {
        currentProject.value = updated
        // api_key 已随 project.yaml 持久化，直接使用后端返回的配置。
        currentConfig.value = { ...updated.analysis }
      }
      return updated
    } finally {
      loading.value = false
    }
  }

  async function renameProject(projectId: string, name: string): Promise<Project> {
    const updated = await api.renameProject(projectId, name)
    const idx = projects.value.findIndex((p) => p.id === projectId)
    if (idx >= 0) {
      projects.value[idx] = updated
    }
    if (currentProject.value?.id === projectId) {
      currentProject.value = updated
      currentConfig.value = { ...updated.analysis }
    }
    return updated
  }

  return {
    projects,
    currentProject,
    currentConfig,
    loading,
    loadProjects,
    selectProject,
    createProject,
    deleteProject,
    saveConfig,
    renameProject,
  }
})
