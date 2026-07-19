import client from './client'

export interface AnalysisConfig {
  image_dir: string
  clinical_path: string
  output_dir: string
  modality: string
  covariates: string
  model: string
  analysis_model: string
  api_key: string
}

export interface Project {
  id: string
  name: string
  path: string
  description: string
  created_at: string
  updated_at: string
  analysis: AnalysisConfig
}

export interface CreateProjectRequest {
  name: string
  path: string
  description?: string
}

export type UpdateConfigRequest = AnalysisConfig

export const listProjects = async (): Promise<Project[]> => {
  const res = await client.get('/projects')
  return res.data
}

export const getProject = async (projectId: string): Promise<Project> => {
  const res = await client.get(`/projects/${encodeURIComponent(projectId)}`)
  return res.data
}

export const createProject = async (payload: CreateProjectRequest): Promise<Project> => {
  const res = await client.post('/projects', payload)
  return res.data
}

export const updateConfig = async (
  projectId: string,
  config: UpdateConfigRequest
): Promise<Project> => {
  const res = await client.put(`/projects/${encodeURIComponent(projectId)}/config`, config)
  return res.data
}

export const deleteProject = async (projectId: string): Promise<void> => {
  await client.delete(`/projects/${encodeURIComponent(projectId)}`)
}

export const renameProject = async (projectId: string, name: string): Promise<Project> => {
  const res = await client.patch(`/projects/${encodeURIComponent(projectId)}`, { name })
  return res.data
}

/** 项目内文件/目录索引（聊天输入框 @ 引用补全），返回 POSIX 分隔的相对路径，
 * 目录条目以 / 结尾。 */
export const listProjectEntries = async (
  projectId: string,
  q = '',
  limit = 200
): Promise<string[]> => {
  const res = await client.get(`/projects/${encodeURIComponent(projectId)}/files`, {
    params: { q, limit },
  })
  return res.data.entries
}
