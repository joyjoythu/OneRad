import client from './client'

export interface FilesystemRoot {
  name: string
  path: string
}

export interface FilesystemEntry {
  name: string
  path: string
  is_dir: boolean
}

export interface FilesystemBreadcrumb {
  name: string
  path: string
}

export interface FilesystemEntries {
  path: string
  parent: string | null
  breadcrumbs: FilesystemBreadcrumb[]
  entries: FilesystemEntry[]
}

export async function listFilesystemRoots(): Promise<FilesystemRoot[]> {
  const response = await client.get<{ roots: FilesystemRoot[] }>('/filesystem/roots')
  return response.data.roots
}

export async function listFilesystemEntries(path: string): Promise<FilesystemEntries> {
  const response = await client.get<FilesystemEntries>('/filesystem/entries', {
    params: { path },
  })
  return response.data
}
