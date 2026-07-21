<template>
  <div class="choice-panel" data-testid="choice-panel">
    <div class="choice-question">{{ question }}</div>

    <!-- 可交互：等待用户选择 -->
    <template v-if="status === 'pending' && interactive">
      <div class="choice-options" role="radiogroup" :aria-label="question">
        <button
          v-for="(option, index) in options"
          :key="index"
          type="button"
          class="choice-option"
          :class="{ 'choice-option--selected': selected === option }"
          @click="select(option)"
        >
          {{ option }}
        </button>
        <button
          type="button"
          class="choice-option choice-option--other"
          :class="{ 'choice-option--selected': selected === OTHER }"
          @click="select(OTHER)"
        >
          其他（自己输入）
        </button>
      </div>
      <el-input
        v-if="selected === OTHER"
        v-model="otherText"
        class="choice-other-input"
        type="textarea"
        :rows="2"
        placeholder="请输入你的想法…"
      />
      <div class="choice-actions">
        <el-button
          type="primary"
          size="small"
          :disabled="!canSubmit"
          :loading="submitting"
          @click="handleSubmit"
        >
          提交
        </el-button>
      </div>
    </template>

    <!-- 只读定格：已回答 / 已取消 / 已提交待处理 -->
    <template v-else>
      <div class="choice-static-options">
        <div
          v-for="(option, index) in options"
          :key="index"
          class="choice-static-option"
          :class="{ 'choice-static-option--selected': status === 'answered' && option === answer }"
        >
          {{ option }}
        </div>
      </div>
      <div v-if="status === 'answered'" class="choice-result">已选择：{{ answer }}</div>
      <div v-else-if="status === 'cancelled'" class="choice-result choice-result--muted">
        已取消
      </div>
      <div v-else class="choice-result choice-result--muted">已提交，等待 agent 继续…</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

const OTHER = '__other__'

const props = defineProps<{
  question: string
  options: string[]
  /** pending 等待回答；answered 定格显示答案；cancelled 定格显示已取消 */
  status: 'pending' | 'answered' | 'cancelled'
  /** status=pending 时是否允许交互（仅 interrupt 中的当前提问可交互） */
  interactive?: boolean
  answer?: string
  submitting?: boolean
}>()

const emit = defineEmits<{
  submit: [text: string]
}>()

const selected = ref<string>('')
const otherText = ref('')

function select(value: string): void {
  selected.value = value
}

const canSubmit = computed(() => {
  if (props.submitting) return false
  if (!selected.value) return false
  if (selected.value === OTHER) return otherText.value.trim().length > 0
  return true
})

function handleSubmit(): void {
  if (!canSubmit.value) return
  const text = selected.value === OTHER ? otherText.value.trim() : selected.value
  emit('submit', text)
}
</script>

<style scoped>
.choice-panel {
  margin-top: 0.5rem;
  padding: 0.75rem 1rem;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-bg-panel);
}

.choice-question {
  font-weight: 600;
  font-size: 0.875rem;
  color: var(--app-text);
  margin-bottom: 0.625rem;
  white-space: pre-wrap;
  word-break: break-word;
}

.choice-options {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.choice-option {
  text-align: left;
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
  color: var(--app-text);
  background: var(--app-bg-hover);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.choice-option:hover {
  border-color: var(--el-color-primary);
}

.choice-option--selected {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.choice-option--other {
  color: var(--app-text-secondary);
  border-style: dashed;
}

.choice-other-input {
  margin-top: 0.5rem;
}

.choice-actions {
  margin-top: 0.625rem;
  display: flex;
  justify-content: flex-end;
}

.choice-static-options {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.choice-static-option {
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
  color: var(--app-text-muted);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.choice-static-option--selected {
  color: var(--app-text);
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.choice-result {
  margin-top: 0.5rem;
  font-size: 0.8125rem;
  color: var(--el-color-success);
}

.choice-result--muted {
  color: var(--app-text-muted);
}
</style>
