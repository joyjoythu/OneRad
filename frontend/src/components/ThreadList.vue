<template>
  <div
    class="thread-list"
    :class="{ 'thread-list--collapsed': collapsed }"
  >
    <div class="thread-list-header">
      <el-button
        link
        size="small"
        :icon="collapsed ? Expand : Fold"
        aria-label="折叠/展开历史会话面板"
        @click="emit('toggle-collapse')"
      />
      <span v-show="!collapsed" class="thread-list-title">历史会话</span>
      <el-button
        v-show="!collapsed"
        type="primary"
        size="small"
        :icon="Plus"
        @click="handleCreate"
      >
        新建对话
      </el-button>
    </div>

    <div v-show="!collapsed">
      <div v-if="threads.length === 0" class="thread-list-empty">
        <el-empty description="暂无历史会话" :image-size="60" />
      </div>

      <ul v-else class="thread-list-items">
        <li
          v-for="thread in threads"
          :key="thread.id"
          :class="['thread-item', { 'thread-item--active': currentThreadId === thread.id }]"
          @click="handleSelect(thread.id)"
        >
          <div class="thread-item-content">
            <el-icon class="thread-item-icon"><ChatDotRound /></el-icon>
            <span class="thread-item-title">{{ thread.title || '未命名会话' }}</span>
          </div>
          <div class="thread-item-actions">
            <el-button
              link
              size="small"
              :icon="Edit"
              @click.stop="handleRename(thread)"
            />
            <el-button
              link
              size="small"
              type="danger"
              :icon="Delete"
              @click.stop="handleDelete(thread)"
            />
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  Plus,
  Edit,
  Delete,
  ChatDotRound,
  Fold,
  Expand,
} from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import type { ThreadSummary } from '@/api/agent'

defineProps<{
  threads: ThreadSummary[]
  currentThreadId: string | null
  collapsed?: boolean
}>()

const emit = defineEmits<{
  select: [threadId: string]
  create: []
  rename: [threadId: string, title: string]
  delete: [threadId: string]
  'toggle-collapse': []
}>()

function handleSelect(threadId: string): void {
  emit('select', threadId)
}

function handleCreate(): void {
  emit('create')
}

async function handleRename(thread: ThreadSummary): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('请输入新标题', '重命名会话', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: thread.title || '未命名会话',
      inputValidator: (value) => {
        if (!value || value.trim() === '') {
          return '标题不能为空'
        }
        return true
      },
    })
    emit('rename', thread.id, value.trim())
  } catch {
    // user cancelled
  }
}

async function handleDelete(thread: ThreadSummary): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定要删除会话 "${thread.title || '未命名会话'}" 吗？删除后无法恢复。`,
      '删除会话',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    emit('delete', thread.id)
  } catch {
    // user cancelled
  }
}
</script>

<style scoped>
.thread-list {
  display: flex;
  flex-direction: column;
  width: 240px;
  height: 100%;
  border-right: 1px solid #e4e7ed;
  background-color: #f5f7fa;
  transition: width 0.2s ease;
}

.thread-list--collapsed {
  width: 40px;
  align-items: center;
}

.thread-list--collapsed .thread-list-header {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}

.thread-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e4e7ed;
}

.thread-list-title {
  font-weight: 600;
  color: #303133;
}

.thread-list-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.thread-list-items {
  flex: 1;
  overflow-y: auto;
  list-style: none;
  margin: 0;
  padding: 0.5rem 0;
}

.thread-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  margin: 0 0.5rem;
  border-radius: 4px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.thread-item:hover,
.thread-item--active {
  background-color: #e6f2ff;
}

.thread-item-content {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  overflow: hidden;
}

.thread-item-icon {
  flex-shrink: 0;
  color: #909399;
}

.thread-item-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #303133;
  font-size: 0.875rem;
}

.thread-item-actions {
  display: flex;
  gap: 0.25rem;
  opacity: 0;
  transition: opacity 0.2s;
}

.thread-item:hover .thread-item-actions {
  opacity: 1;
}
</style>
