import client from './client'

export type ApiKeySource = 'settings' | 'environment' | 'none'

export interface GeneralSettings {
  api_key: string
  api_key_configured: boolean
  api_key_source: ApiKeySource
}

export const getSettings = async (): Promise<GeneralSettings> => {
  const response = await client.get('/settings')
  return response.data
}

export const updateSettings = async (apiKey: string): Promise<GeneralSettings> => {
  const response = await client.put('/settings', { api_key: apiKey })
  return response.data
}
