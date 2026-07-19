import client from './client'

export interface DirEntry {
  name: string
  path: string
}

export interface DirListing {
  /** 当前目录的绝对路径 */
  path: string
  /** 父目录路径；到达根目录时为 null */
  parent: string | null
  /** 非隐藏子目录列表 */
  dirs: DirEntry[]
  /** Windows 下可用盘符；其它平台为空 */
  drives: string[]
}

export const listDirectory = async (path?: string): Promise<DirListing> => {
  const res = await client.get('/fs/list', {
    params: path ? { path } : {},
  })
  return res.data
}
