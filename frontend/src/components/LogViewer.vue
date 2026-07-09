<template>
  <div class="log-viewer">
    <div class="log-viewer-header">
      <span class="log-viewer-title">运行日志</span>
      <el-button v-if="logs.length" link :icon="Delete" @click="handleClear">
        清空
      </el-button>
      <el-button link :icon="Close" @click="handleClose">关闭</el-button>
    </div>

    <div ref="logContainer" class="log-viewer-body">
      <div v-if="!logs.length" class="log-empty">暂无日志</div>
      <div v-else class="log-entries">
        <div v-for="(log, index) in logs" :key="index" class="log-entry">
          {{ log }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { Delete, Close } from '@element-plus/icons-vue'

const props = defineProps<{
  logs: string[]
}>()

const emit = defineEmits<{
  clear: []
  close: []
}>()

const logContainer = ref<HTMLDivElement | null>(null)

watch(
  () => props.logs.length,
  async () => {
    await nextTick()
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  }
)

function handleClear(): void {
  emit('clear')
}

function handleClose(): void {
  emit('close')
}
</script>

<style scoped>
.log-viewer {
  display: flex;
  flex-direction: column;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  background-color: #ffffff;
  overflow: hidden;
}

.log-viewer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e4e7ed;
  background-color: #f5f7fa;
}

.log-viewer-title {
  font-weight: 500;
  color: #303133;
}

.log-viewer-body {
  max-height: 320px;
  min-height: 120px;
  overflow-y: auto;
  padding: 0.75rem 1rem;
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.875rem;
  line-height: 1.5;
  background-color: #f5f7fa;
  color: #303133;
}

.log-empty {
  color: #909399;
  text-align: center;
  padding: 2rem 0;
}

.log-entry {
  white-space: pre-wrap;
  word-break: break-all;
}

.log-entry + .log-entry {
  margin-top: 0.25rem;
}
</style>
