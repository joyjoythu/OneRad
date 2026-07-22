import client from './client'

export type ApiKeySource = 'settings' | 'environment' | 'none'

export interface GeneralSettings {
  api_key: string
  api_key_configured: boolean
  api_key_source: ApiKeySource
  memory_enabled: boolean
}

export const getSettings = async (): Promise<GeneralSettings> => {
  const response = await client.get('/settings')
  return response.data
}

export const updateSettings = async (
  apiKey: string,
  memoryEnabled?: boolean,
): Promise<GeneralSettings> => {
  const body: Record<string, unknown> = { api_key: apiKey }
  if (memoryEnabled !== undefined) body.memory_enabled = memoryEnabled
  const response = await client.put('/settings', body)
  return response.data
}
