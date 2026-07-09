import { ref } from 'vue'
import { defineStore } from 'pinia'
import * as api from '@/api/projects'
import type { Project, AnalysisConfig } from '@/api/projects'

export const useProjectStore = defineStore('project', () => {
  const projects = ref<Project[]>([])
  const currentProject = ref<Project | null>(null)
  const currentConfig = ref<AnalysisConfig | null>(null)

  async function loadProjects(): Promise<void> {
    projects.value = await api.listProjects()
  }

  function selectProject(projectId: string): void {
    const project = projects.value.find((p) => p.id === projectId) || null
    currentProject.value = project
    currentConfig.value = project ? { ...project.analysis } : null
  }

  async function createProject(payload: api.CreateProjectRequest): Promise<Project> {
    const project = await api.createProject(payload)
    projects.value.unshift(project)
    selectProject(project.id)
    return project
  }

  async function deleteProject(projectId: string): Promise<void> {
    await api.deleteProject(projectId)
    projects.value = projects.value.filter((p) => p.id !== projectId)
    if (currentProject.value?.id === projectId) {
      currentProject.value = null
      currentConfig.value = null
    }
  }

  async function saveConfig(
    projectId: string,
    config: AnalysisConfig
  ): Promise<Project> {
    const updated = await api.updateConfig(projectId, config)
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
    loadProjects,
    selectProject,
    createProject,
    deleteProject,
    saveConfig,
  }
})
