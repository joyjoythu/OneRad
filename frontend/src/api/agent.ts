import client from './client'
import { API_BASE } from './client'

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
  const res = await client.get(`/agent/threads/${encodeURIComponent(threadId)}`)
  return res.data
}

export const sendMessage = async (
  threadId: string,
  role: string,
  content: string
): Promise<{ thread_id: string }> => {
  const payload: MessageRequest = { role, content }
  const res = await client.post(
    `/agent/threads/${encodeURIComponent(threadId)}/messages`,
    payload
  )
  return res.data
}

export const updatePlan = async (
  threadId: string,
  plan: Record<string, unknown>
): Promise<AgentState> => {
  const payload: UpdatePlanRequest = { plan }
  const res = await client.put(
    `/agent/threads/${encodeURIComponent(threadId)}/plan`,
    payload
  )
  return res.data
}

export const confirm = async (threadId: string): Promise<{ thread_id: string }> => {
  const res = await client.post(`/agent/threads/${encodeURIComponent(threadId)}/confirm`)
  return res.data
}

export const cancel = async (threadId: string): Promise<{ thread_id: string }> => {
  const res = await client.post(`/agent/threads/${encodeURIComponent(threadId)}/cancel`)
  return res.data
}

export const connectAgentEvents = (
  threadId: string,
  callbacks: AgentEventCallbacks = {}
): EventSource => {
  const es = new EventSource(
    `${API_BASE}/agent/threads/${encodeURIComponent(threadId)}/events`
  )

  es.addEventListener('agent', (event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data) as AgentState
      callbacks.onState?.(data)
    } catch (err) {
      console.error('Failed to parse agent SSE payload', err)
    }
  })

  es.addEventListener('agent_end', () => {
    callbacks.onEnd?.()
  })

  // Keep the connection open on transient errors; the browser will reconnect
  // automatically per the EventSource spec. close() is only called from the
  // consumer when the stream is truly finished.
  es.onerror = () => {
    callbacks.onError?.({ message: 'EventSource error' })
  }

  return es
}
