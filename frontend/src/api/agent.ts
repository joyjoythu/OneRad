import client from './client'

export interface AgentMessage {
  role: string
  content: string
  tool_calls?: unknown[]
  tool_call_id?: string
}

export interface AgentState {
  thread_id?: string
  messages: AgentMessage[]
  interrupt_type: string | null
  operation_log: string[]
  pending_plan: Record<string, unknown> | null
  pending_command: Record<string, unknown> | null
  pending_script: Record<string, unknown> | null
}

export interface CreateThreadResponse {
  thread_id: string
}

export interface MessageRequest {
  role: string
  content: string
}

export interface UpdatePlanRequest {
  plan: Record<string, unknown>
}

export interface AgentEventCallbacks {
  onState?: (state: AgentState) => void
  onEnd?: () => void
  onError?: (error: Record<string, unknown>) => void
}

export const createThread = async (
  projectId: string
): Promise<CreateThreadResponse> => {
  const res = await client.post('/agent/threads', undefined, {
    params: { project_id: projectId },
  })
  return res.data
}

export const getThread = async (
  threadId: string
): Promise<AgentState & { thread_id: string }> => {
  const res = await client.get(`/agent/threads/${threadId}`)
  return res.data
}

export const sendMessage = async (
  threadId: string,
  role: string,
  content: string
): Promise<{ thread_id: string }> => {
  const payload: MessageRequest = { role, content }
  const res = await client.post(`/agent/threads/${threadId}/messages`, payload)
  return res.data
}

export const updatePlan = async (
  threadId: string,
  plan: Record<string, unknown>
): Promise<AgentState> => {
  const payload: UpdatePlanRequest = { plan }
  const res = await client.put(`/agent/threads/${threadId}/plan`, payload)
  return res.data
}

export const confirm = async (threadId: string): Promise<{ thread_id: string }> => {
  const res = await client.post(`/agent/threads/${threadId}/confirm`)
  return res.data
}

export const cancel = async (threadId: string): Promise<{ thread_id: string }> => {
  const res = await client.post(`/agent/threads/${threadId}/cancel`)
  return res.data
}

export const connectAgentEvents = (
  threadId: string,
  callbacks: AgentEventCallbacks = {}
): EventSource => {
  const es = new EventSource(`/api/agent/threads/${threadId}/events`)

  es.addEventListener('agent', (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data) as AgentState
      callbacks.onState?.(data)
    } catch {
      // Ignore malformed SSE payloads.
    }
  })

  es.addEventListener('agent_end', () => {
    callbacks.onEnd?.()
  })

  es.onerror = () => {
    callbacks.onError?.({ message: 'EventSource error' })
  }

  return es
}
