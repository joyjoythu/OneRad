import { ref } from 'vue'
import { defineStore } from 'pinia'
import * as api from '@/api/agent'
import type {
  AgentState,
  AgentMessage,
  PendingPlan,
  PendingCommand,
  PendingScript,
} from '@/api/agent'

export const useAgentStore = defineStore('agent', () => {
  const threadId = ref<string | null>(null)
  const messages = ref<AgentMessage[]>([])
  const interrupt = ref<string | null>(null)
  const operationLog = ref<string[]>([])
  const pendingPlan = ref<PendingPlan | null>(null)
  const pendingCommand = ref<PendingCommand | null>(null)
  const pendingScript = ref<PendingScript | null>(null)

  let es: EventSource | null = null

  function applyState(state: Partial<AgentState>): void {
    if (state.messages) {
      messages.value = state.messages
    }
    if (state.interrupt_type !== undefined) {
      interrupt.value = state.interrupt_type
    }
    if (state.operation_log) {
      operationLog.value = state.operation_log
    }
    if (state.pending_plan !== undefined) {
      pendingPlan.value = state.pending_plan
    }
    if (state.pending_command !== undefined) {
      pendingCommand.value = state.pending_command
    }
    if (state.pending_script !== undefined) {
      pendingScript.value = state.pending_script
    }
  }

  async function ensureThread(projectId: string): Promise<string> {
    if (threadId.value) {
      return threadId.value
    }
    const { thread_id } = await api.createThread(projectId)
    threadId.value = thread_id
    await syncThread()
    connect()
    return thread_id
  }

  async function syncThread(): Promise<void> {
    if (!threadId.value) return
    const state = await api.getThread(threadId.value)
    applyState(state)
  }

  function connect(): void {
    if (!threadId.value || es) return
    es = api.connectAgentEvents(threadId.value, {
      onState: (state) => applyState(state),
      onEnd: () => {
        // Stream ended naturally.
      },
      onError: () => {
        disconnect()
      },
    })
  }

  async function sendMessage(content: string, role = 'user'): Promise<void> {
    if (!threadId.value) {
      throw new Error('No active agent thread')
    }
    messages.value.push({ role, content })
    await api.sendMessage(threadId.value, role, content)
    connect()
  }

  async function updatePlan(plan: PendingPlan): Promise<void> {
    if (!threadId.value) {
      throw new Error('No active agent thread')
    }
    const state = await api.updatePlan(threadId.value, plan)
    applyState(state)
  }

  async function confirm(): Promise<void> {
    if (!threadId.value) {
      throw new Error('No active agent thread')
    }
    await api.confirm(threadId.value)
    connect()
  }

  async function cancel(): Promise<void> {
    if (!threadId.value) {
      throw new Error('No active agent thread')
    }
    await api.cancel(threadId.value)
    connect()
  }

  function disconnect(): void {
    if (es) {
      es.close()
      es = null
    }
  }

  async function reconnect(): Promise<void> {
    await syncThread()
    connect()
  }

  function resetThread(): void {
    disconnect()
    threadId.value = null
    messages.value = []
    interrupt.value = null
    operationLog.value = []
    pendingPlan.value = null
    pendingCommand.value = null
    pendingScript.value = null
  }

  return {
    threadId,
    messages,
    interrupt,
    operationLog,
    pendingPlan,
    pendingCommand,
    pendingScript,
    ensureThread,
    reconnect,
    sendMessage,
    updatePlan,
    confirm,
    cancel,
    disconnect,
    resetThread,
  }
})
