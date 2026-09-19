<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getKb, type KnowledgeBase } from '@/api/kb'
import {
  DOC_STATUS,
  deleteDoc,
  getDocChunks,
  listDocs,
  pasteText,
  reindexDoc,
  uploadDocs,
  type ChunkItem,
  type DocumentItem,
} from '@/api/doc'
import { subscribeTask, type TaskEvent } from '@/api/task'

const route = useRoute()
const router = useRouter()
const kbId = Number(route.params.id)

const kb = ref<KnowledgeBase | null>(null)
const loading = ref(false)
const docs = ref<DocumentItem[]>([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(10)
const keyword = ref('')

/** 正在进行的上传/解析任务 */
interface ActiveTask {
  taskId: number
  fileName: string
  progress: number
  stage: string
  status: 'running' | 'done' | 'error'
  errorMsg?: string
}
const activeTasks = ref<ActiveTask[]>([])
const closers: Array<() => void> = []

/** 分块预览 */
const chunkDrawer = ref(false)
const chunkLoading = ref(false)
const chunkDoc = ref<DocumentItem | null>(null)
const chunks = ref<ChunkItem[]>([])

/** 粘贴文本 */
const pasteVisible = ref(false)
const pasteForm = ref({ title: '', content: '' })

const uploading = ref(false)
const dragOver = ref(false)

const maxSizeMb = 100
const acceptExt =
  '.pdf,.doc,.docx,.ppt,.pptx,.txt,.md,.xlsx,.jpg,.jpeg,.png,.bmp,.webp'

async function loadKb() {
  kb.value = await getKb(kbId)
}

async function loadDocs() {
  loading.value = true
  try {
    const res = await listDocs({
      kbId,
      keyword: keyword.value || undefined,
      pageNum: pageNum.value,
      pageSize: pageSize.value,
    })
    docs.value = res.list
    total.value = res.total
  } finally {
    loading.value = false
  }
}

// ---------------------------------------------------------------- 上传
async function doUpload(files: File[], imageMode = false) {
  if (!files.length) return

  const tooBig = files.filter((f) => f.size > maxSizeMb * 1024 * 1024)
  if (tooBig.length) {
    ElMessage.error(`${tooBig.map((f) => f.name).join('、')} 超过 ${maxSizeMb} MB 限制`)
    return
  }

  uploading.value = true
  try {
    const results = await uploadDocs(kbId, files, imageMode)
    for (const r of results) {
      if (r.duplicated) {
        ElMessage.info(r.message)
        continue
      }
      if (!r.docId || !r.taskId) {
        ElMessage.error(`${r.fileName}：${r.message}`)
        continue
      }

      const task: ActiveTask = {
        taskId: r.taskId,
        fileName: r.fileName,
        progress: 0,
        stage: '排队中',
        status: 'running',
      }
      activeTasks.value.push(task)

      const close = subscribeTask(r.taskId, {
        onProgress: (e: TaskEvent) => {
          task.progress = e.progress ?? 0
          task.stage = e.stage || ''
        },
        onDone: (e: TaskEvent) => {
          task.status = 'done'
          task.progress = 100
          const res = e.result as Record<string, number> | null
          task.stage = res
            ? `解析完成：${res.chunkCount ?? 0} 个分块` +
              (res.tagCount ? ` · ${res.tagCount} 个知识点` : '')
            : '解析完成'
          ElMessage.success(`${r.fileName} 解析完成`)
          loadDocs()
          loadKb()
        },
        onError: (e: TaskEvent) => {
          task.status = 'error'
          task.errorMsg = e.errorMsg || '解析失败'
          task.stage = '解析失败'
          ElMessage.error(`${r.fileName}：${task.errorMsg}`)
          loadDocs()
        },
      })
      closers.push(close)
    }
    await loadDocs()
  } finally {
    uploading.value = false
  }
}

function onFileInput(e: Event) {
  const input = e.target as HTMLInputElement
  doUpload(Array.from(input.files || []))
  input.value = ''
}

function onDrop(e: DragEvent) {
  dragOver.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  const images = files.filter((f) => f.type.startsWith('image/'))
  if (images.length === files.length && files.length > 0) {
    doUpload(files, true)
  } else {
    doUpload(files)
  }
}

function pickImages() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  input.multiple = true
  input.onchange = () => {
    doUpload(Array.from(input.files || []), true)
    input.value = ''
  }
  input.click()
}

function clearFinished() {
  activeTasks.value = activeTasks.value.filter((t) => t.status === 'running')
}

// ---------------------------------------------------------------- 行操作
async function openChunks(doc: DocumentItem) {
  chunkDoc.value = doc
  chunkDrawer.value = true
  chunkLoading.value = true
  try {
    const res = await getDocChunks(doc.id, 1, 100)
    chunks.value = res.list
  } finally {
    chunkLoading.value = false
  }
}

async function doReindex(doc: DocumentItem) {
  await ElMessageBox.confirm(
    `重新解析「${doc.fileName}」会先清空它的旧分块与向量，再跑一遍完整流程。确认？`,
    '重新解析',
    { type: 'warning' },
  )
  const taskId = await reindexDoc(doc.id)
  ElMessage.success('已加入解析队列')
  activeTasks.value.push({
    taskId,
    fileName: doc.fileName,
    progress: 0,
    stage: '排队中',
    status: 'running',
  })
  const close = subscribeTask(taskId, {
    onProgress: (e) => {
      const t = activeTasks.value.find((x) => x.taskId === taskId)
      if (t) {
        t.progress = e.progress ?? 0
        t.stage = e.stage || ''
      }
    },
    onDone: () => {
      const t = activeTasks.value.find((x) => x.taskId === taskId)
      if (t) {
        t.status = 'done'
        t.progress = 100
        t.stage = '重新解析完成'
      }
      loadDocs()
    },
    onError: (e) => {
      const t = activeTasks.value.find((x) => x.taskId === taskId)
      if (t) {
        t.status = 'error'
        t.errorMsg = e.errorMsg
      }
      loadDocs()
    },
  })
  closers.push(close)
  await loadDocs()
}

async function doDelete(doc: DocumentItem) {
  await ElMessageBox.confirm(
    `删除「${doc.fileName}」会同时清空它的 ${doc.chunkCount} 个分块和对应向量。确认？`,
    '删除文档',
    { type: 'warning' },
  )
  await deleteDoc(doc.id)
  ElMessage.success('已删除')
  await loadDocs()
  loadKb()
}

async function submitPaste() {
  if (!pasteForm.value.content.trim()) {
    ElMessage.warning('请粘贴内容')
    return
  }
  const r = await pasteText({
    kbId,
    title: pasteForm.value.title,
    content: pasteForm.value.content,
  })
  ElMessage.success('已加入解析队列')
  pasteVisible.value = false
  pasteForm.value = { title: '', content: '' }
  if (r.taskId) {
    activeTasks.value.push({
      taskId: r.taskId,
      fileName: r.fileName,
      progress: 0,
      stage: '排队中',
      status: 'running',
    })
  }
  await loadDocs()
}

function fmtSize(bytes: number) {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const hasRunning = computed(() => activeTasks.value.some((t) => t.status === 'running'))

onMounted(async () => {
  await Promise.all([loadKb(), loadDocs()])
})

onUnmounted(() => {
  closers.forEach((c) => c())
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <div style="display: flex; align-items: center; gap: 8px">
          <el-button link :icon="'ArrowLeft'" @click="router.push('/kb')">知识库</el-button>
          <h2 style="margin: 0">{{ kb?.name || '加载中' }}</h2>
        </div>
        <div class="sub">
          {{ kb?.milvusCollection }} ·
          {{ kb?.chunkSize }} token / 重叠 {{ kb?.chunkOverlap }}
        </div>
      </div>
      <div style="display: flex; gap: 10px">
        <el-button :icon="'MagicStick'" @click="router.push(`/kb/${kbId}/tag`)">知识点</el-button>
        <el-button :icon="'Search'" @click="router.push(`/kb/${kbId}/search`)">检索调试</el-button>
        <el-button type="success" :icon="'EditPen'" @click="router.push(`/kb/${kbId}/generate`)">
          AI 出题
        </el-button>
        <el-button :icon="'DocumentCopy'" @click="pasteVisible = true">粘贴文本</el-button>
        <el-button type="primary" :icon="'Camera'" @click="pickImages">拍照上传</el-button>
      </div>
    </div>

    <!-- 上传区 -->
    <div
      class="drop-zone"
      :class="{ over: dragOver }"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop.prevent="onDrop"
      @click="($refs.fileInput as HTMLInputElement).click()"
    >
      <input
        ref="fileInput"
        type="file"
        multiple
        :accept="acceptExt"
        style="display: none"
        @change="onFileInput"
      />
      <el-icon :size="34" color="#94a3b8"><UploadFilled /></el-icon>
      <div class="drop-title">
        {{ uploading ? '上传中 ...' : '把资料拖到这里，或点击选择文件' }}
      </div>
      <div class="drop-sub">
        支持 PDF / Word / PPT / Excel / TXT / Markdown / 图片 · 单文件最大 {{ maxSizeMb }} MB
      </div>
      <div class="drop-sub">图片会自动走 OCR 识别；扫描版 PDF 也会自动 OCR</div>
    </div>

    <!-- 任务进度 -->
    <el-card v-if="activeTasks.length" shadow="never" style="margin-top: 16px">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between">
          <b>解析进度</b>
          <el-button link size="small" @click="clearFinished">清除已完成</el-button>
        </div>
      </template>

      <div v-for="t in activeTasks" :key="t.taskId" class="task-row">
        <el-icon v-if="t.status === 'running'" class="is-loading" color="#4c7cf3"><Loading /></el-icon>
        <el-icon v-else-if="t.status === 'done'" color="#10b981"><CircleCheckFilled /></el-icon>
        <el-icon v-else color="#ef4444"><CircleCloseFilled /></el-icon>

        <div class="task-body">
          <div class="task-name">{{ t.fileName }}</div>
          <el-progress
            :percentage="t.progress"
            :status="t.status === 'error' ? 'exception' : t.status === 'done' ? 'success' : undefined"
            :stroke-width="10"
          />
          <div class="task-stage" :class="{ err: t.status === 'error' }">
            {{ t.status === 'error' ? t.errorMsg : t.stage }}
          </div>
        </div>
      </div>
    </el-card>

    <!-- 文档列表 -->
    <el-card shadow="never" style="margin-top: 16px">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between">
          <b>文档（{{ total }}）</b>
          <div style="display: flex; gap: 8px">
            <el-input
              v-model="keyword"
              placeholder="搜索文件名"
              size="small"
              clearable
              style="width: 180px"
              @keyup.enter="loadDocs"
              @clear="loadDocs"
            />
            <el-button size="small" :icon="'Refresh'" @click="loadDocs">刷新</el-button>
          </div>
        </div>
      </template>

      <el-table :data="docs" v-loading="loading" stripe>
        <el-table-column prop="fileName" label="文件名" min-width="220" show-overflow-tooltip />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.fileType || '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="90">
          <template #default="{ row }">{{ fmtSize(row.fileSize) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tooltip :content="row.errorMsg" :disabled="!row.errorMsg" placement="top">
              <el-tag size="small" :type="DOC_STATUS[row.status as 0].type">
                {{ DOC_STATUS[row.status as 0].text }}
              </el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="分块" width="80">
          <template #default="{ row }">
            <el-button v-if="row.chunkCount" link type="primary" @click="openChunks(row)">
              {{ row.chunkCount }}
            </el-button>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="字数" width="90">
          <template #default="{ row }">{{ row.charCount || '-' }}</template>
        </el-table-column>
        <el-table-column label="上传时间" width="160">
          <template #default="{ row }">{{ (row.createdAt || '').replace('T', ' ').slice(0, 16) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              size="small"
              :disabled="row.sourceType === 3"
              @click="doReindex(row)"
            >
              重新解析
            </el-button>
            <el-button link type="danger" size="small" @click="doDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="total > pageSize"
        style="margin-top: 14px; justify-content: flex-end"
        layout="total, prev, pager, next"
        :total="total"
        :current-page="pageNum"
        :page-size="pageSize"
        @current-change="(p: number) => { pageNum = p; loadDocs() }"
      />
    </el-card>

    <!-- 分块预览 -->
    <el-drawer v-model="chunkDrawer" size="62%" :title="`分块预览 · ${chunkDoc?.fileName || ''}`">
      <div v-loading="chunkLoading">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
          title="每个分块都会被向量化后写入 Milvus，并挂上 AI 抽出的知识点标签"
        />
        <el-card v-for="c in chunks" :key="c.id" shadow="never" class="chunk-card">
          <div class="chunk-head">
            <span class="chunk-idx">#{{ c.chunkIndex }}</span>
            <el-tag v-if="c.pageNo" size="small" effect="plain">第 {{ c.pageNo }} 页</el-tag>
            <el-tag size="small" type="info" effect="plain">{{ c.tokenCount }} token</el-tag>
            <el-tag
              v-for="t in c.tags"
              :key="t.id"
              size="small"
              :type="t.level === 1 ? 'primary' : t.level === 2 ? 'success' : 'warning'"
            >
              {{ t.name }}
            </el-tag>
          </div>
          <div v-if="c.sectionPath" class="chunk-section">{{ c.sectionPath }}</div>
          <div class="chunk-content">{{ c.content }}</div>
        </el-card>
        <el-empty v-if="!chunkLoading && !chunks.length" description="还没有分块" />
      </div>
    </el-drawer>

    <!-- 粘贴文本 -->
    <el-dialog v-model="pasteVisible" title="粘贴文本入库" width="640px">
      <el-form label-width="60px">
        <el-form-item label="标题">
          <el-input v-model="pasteForm.title" placeholder="留空则自动生成" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input
            v-model="pasteForm.content"
            type="textarea"
            :rows="14"
            placeholder="把要背的内容粘贴进来，支持 Markdown 标题（# ## ###）来划分章节"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pasteVisible = false">取消</el-button>
        <el-button type="primary" @click="submitPaste">入库</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.drop-zone {
  border: 2px dashed #cbd5e1;
  border-radius: 12px;
  background: #fff;
  padding: 30px 20px;
  text-align: center;
  cursor: pointer;
  transition: all 0.15s;
}

.drop-zone:hover,
.drop-zone.over {
  border-color: #4c7cf3;
  background: #f5f8ff;
}

.drop-title {
  font-size: 15px;
  font-weight: 600;
  color: #334155;
  margin-top: 10px;
}

.drop-sub {
  font-size: 12.5px;
  color: #94a3b8;
  margin-top: 4px;
}

.task-row {
  display: flex;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid #f1f5f9;
}

.task-row:last-child {
  border-bottom: none;
}

.task-body {
  flex: 1;
  min-width: 0;
}

.task-name {
  font-size: 13.5px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-stage {
  font-size: 12.5px;
  color: #64748b;
  margin-top: 3px;
}

.task-stage.err {
  color: #dc2626;
}

.chunk-card {
  margin-bottom: 10px;
}

.chunk-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.chunk-idx {
  font-weight: 700;
  color: #4c7cf3;
  font-size: 13px;
}

.chunk-section {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 6px;
}

.chunk-content {
  font-size: 13px;
  color: #334155;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
