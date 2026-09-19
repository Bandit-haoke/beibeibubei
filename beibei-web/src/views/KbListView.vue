<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createKb, deleteKb, listKb, type KnowledgeBase } from '@/api/kb'

const router = useRouter()
const loading = ref(false)
const list = ref<KnowledgeBase[]>([])
const keyword = ref('')

const dialogVisible = ref(false)
const submitting = ref(false)
const form = ref({ name: '', description: '', coverColor: '#4C7CF3' })

const COLORS = ['#4C7CF3', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#06B6D4', '#EC4899']

async function load() {
  loading.value = true
  try {
    list.value = await listKb(keyword.value || undefined)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = {
    name: '',
    description: '',
    coverColor: COLORS[Math.floor(Math.random() * COLORS.length)],
  }
  dialogVisible.value = true
}

async function submit() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写知识库名称')
    return
  }
  submitting.value = true
  try {
    const kb = await createKb({
      name: form.value.name.trim(),
      description: form.value.description,
      coverColor: form.value.coverColor,
    })
    ElMessage.success(`知识库「${kb.name}」创建成功`)
    dialogVisible.value = false
    await load()
    router.push(`/kb/${kb.id}/doc`)
  } finally {
    submitting.value = false
  }
}

async function remove(kb: KnowledgeBase) {
  try {
    await ElMessageBox.confirm(
      `删除「${kb.name}」会同时清空它的 ${kb.docCount} 个文档、${kb.chunkCount} 个分块和全部向量数据，且不可恢复。确认删除？`,
      '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await deleteKb(kb.id)
  ElMessage.success('已删除')
  await load()
}

function fmtSize(bytes: number) {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <h2>知识库</h2>
        <div class="sub">每个知识库是一套独立的资料、知识点和题库</div>
      </div>
      <div style="display: flex; gap: 10px">
        <el-input
          v-model="keyword"
          placeholder="搜索名称"
          clearable
          style="width: 180px"
          @keyup.enter="load"
          @clear="load"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button type="primary" :icon="'Plus'" @click="openCreate">新建知识库</el-button>
      </div>
    </div>

    <el-empty v-if="!loading && list.length === 0" description="还没有知识库">
      <el-button type="primary" @click="openCreate">创建第一个知识库</el-button>
    </el-empty>

    <el-row :gutter="16">
      <el-col v-for="kb in list" :key="kb.id" :xs="24" :sm="12" :md="8" :lg="6">
        <el-card class="kb-card" shadow="hover" @click="router.push(`/kb/${kb.id}/doc`)">
          <div class="kb-top">
            <div class="kb-dot" :style="{ background: kb.coverColor }"></div>
            <div class="kb-title">{{ kb.name }}</div>
            <el-button
              link
              type="danger"
              :icon="'Delete'"
              size="small"
              @click.stop="remove(kb)"
            />
          </div>

          <div class="kb-desc">{{ kb.description || '暂无描述' }}</div>

          <div class="kb-stats">
            <span><b>{{ kb.docCount }}</b> 文档</span>
            <span><b>{{ kb.chunkCount }}</b> 分块</span>
            <span><b>{{ kb.questionCount }}</b> 题目</span>
          </div>

          <div class="kb-meta">
            <el-tag size="small" effect="plain">{{ kb.embeddingModel }}</el-tag>
            <span class="kb-time">{{ (kb.createdAt || '').slice(0, 10) }}</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="dialogVisible" title="新建知识库" width="460px">
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如：JavaWeb 开发" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="2"
            placeholder="这份资料大概包含什么内容"
            maxlength="500"
          />
        </el-form-item>
        <el-form-item label="主题色">
          <div style="display: flex; gap: 8px">
            <div
              v-for="c in COLORS"
              :key="c"
              class="color-dot"
              :style="{ background: c, outline: form.coverColor === c ? `2px solid ${c}` : 'none' }"
              @click="form.coverColor = c"
            />
          </div>
        </el-form-item>
      </el-form>

      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="向量模型创建后不可修改"
        description="换向量模型会让已入库的向量失去可比性。如需更换，只能新建知识库重新入库。"
      />

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.kb-card {
  margin-bottom: 16px;
  cursor: pointer;
  transition: transform 0.15s;
}

.kb-card:hover {
  transform: translateY(-2px);
}

.kb-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.kb-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.kb-title {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-desc {
  font-size: 12.5px;
  color: #94a3b8;
  height: 34px;
  overflow: hidden;
  line-height: 1.35;
  margin-bottom: 10px;
}

.kb-stats {
  display: flex;
  gap: 14px;
  font-size: 12.5px;
  color: #64748b;
  padding: 8px 0;
  border-top: 1px solid #f1f5f9;
}

.kb-stats b {
  color: #4c7cf3;
  font-size: 14px;
}

.kb-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}

.kb-time {
  font-size: 12px;
  color: #cbd5e1;
}

.color-dot {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  cursor: pointer;
  outline-offset: 2px;
}
</style>
