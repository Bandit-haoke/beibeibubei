<script setup lang="ts">
/**
 * 面经面板（嵌在「模拟面试」页的第三个 Tab 里）。
 *
 * 独立性说明：这个组件自带上传、列表、进度与轮询，父页面只需要
 * `<InterviewNotePanel />` 一行。这样新增功能不用把已经 600 行的
 * InterviewHomeView 再撑大一圈。
 *
 * 进度为什么既订阅 SSE 又轮询列表：
 *  - SSE 负责「实时」，体验到秒级刷新；
 *  - 后端把 progress/stage 也写进了数据库，所以页面刷新、SSE 断了之后，
 *    靠轮询依然能看到进度 —— 面经是全项目最慢的流水线，
 *    这一点比省几次请求重要得多。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type UploadFile } from 'element-plus'
import {
  NOTE_STATUS,
  deleteNote,
  durationText,
  listNotes,
  retryNote,
  uploadNote,
  type NoteVO,
} from '@/api/interviewNote'
import { subscribeTask } from '@/api/task'

const router = useRouter()

const notes = ref<NoteVO[]>([])
const loading = ref(false)
const uploading = ref(false)
const company = ref('')
const position = ref('')

/** 界面上正在跟踪的任务（只跟最近一次上传的） */
const activeTaskId = ref(0)
const activeNoteId = ref(0)
const activeProgress = ref(0)
const activeStage = ref('')

let unsubscribe: (() => void) | null = null
let pollTimer: number | null = null

const AUDIO_ACCEPT = '.mp3,.wav,.m4a,.flac,.opus,.aac,.ogg,.wma,.amr'

/** 有记录还在处理中 —— 决定要不要继续轮询 */
const hasRunning = computed(() =>
  notes.value.some((n) => n.status === 0 || n.status === 1 || n.status === 2 || n.status === 3),
)

const readyCount = computed(() => notes.value.filter((n) => n.status === 4).length)

// ---------------------------------------------------------------------------
//  数据
// ---------------------------------------------------------------------------

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    notes.value = await listNotes()
  } catch (e) {
    if (!silent) ElMessage.error((e as Error).message || '加载面经列表失败')
  } finally {
    if (!silent) loading.value = false
  }
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(() => {
    if (hasRunning.value) {
      void load(true)
    } else {
      stopPolling()
    }
  }, 5000)
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(async () => {
  await load()
  if (hasRunning.value) startPolling()
})

onUnmounted(() => {
  unsubscribe?.()
  stopPolling()
})

// ---------------------------------------------------------------------------
//  上传
// ---------------------------------------------------------------------------

async function handleUpload(uploadFile: UploadFile) {
  const file = uploadFile.raw
  if (!file) return
  if (file.size > 500 * 1024 * 1024) {
    ElMessage.error('单个录音不能超过 500MB')
    return
  }

  uploading.value = true
  try {
    const res = await uploadNote(file, company.value.trim(), position.value.trim())
    ElMessage.success(res.message || '已加入转写队列')
    activeTaskId.value = res.taskId
    activeNoteId.value = res.noteId
    activeProgress.value = 0
    activeStage.value = '排队中'
    await load(true)
    startPolling()
    watchTask(res.taskId, res.noteId)
  } catch (e) {
    ElMessage.error((e as Error).message || '上传失败')
  } finally {
    uploading.value = false
  }
}

function watchTask(taskId: number, noteId: number) {
  unsubscribe?.()
  unsubscribe = subscribeTask(taskId, {
    onProgress: (ev) => {
      activeProgress.value = ev.progress ?? 0
      activeStage.value = ev.stage || ''
      // 顺手把列表里这一条的进度也更新掉，不用等下一次轮询
      const row = notes.value.find((n) => n.id === noteId)
      if (row) {
        row.progress = ev.progress ?? row.progress
        row.stage = ev.stage || row.stage
        if (ev.status === 1) row.status = Math.max(row.status, 1)
      }
    },
    onDone: (ev) => {
      activeTaskId.value = 0
      const result = ev.result as { degraded?: boolean; degradeReason?: string } | null
      if (result?.degraded) {
        ElMessage.warning(
          '已完成，但角色分离走的是降级方案（语音听写 + 大模型推断）。' +
          (result.degradeReason || ''),
        )
      } else {
        ElMessage.success('面经已生成')
      }
      void load(true)
      router.push(`/interview/notes/${noteId}`)
    },
    onError: (ev) => {
      activeTaskId.value = 0
      ElMessage.error(ev.errorMsg || '整理失败')
      void load(true)
    },
  })
}

// ---------------------------------------------------------------------------
//  行操作
// ---------------------------------------------------------------------------

function openDetail(row: NoteVO) {
  router.push(`/interview/notes/${row.id}`)
}

async function doRetry(row: NoteVO) {
  try {
    const taskId = await retryNote(row.id)
    ElMessage.success('已重新排队')
    activeTaskId.value = taskId
    activeNoteId.value = row.id
    activeProgress.value = 0
    activeStage.value = '排队中'
    await load(true)
    startPolling()
    watchTask(taskId, row.id)
  } catch (e) {
    ElMessage.error((e as Error).message || '重试失败')
  }
}

async function doDelete(row: NoteVO) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.title || row.fileName}」吗？音频文件会一并删除，不可恢复。`,
      '删除面经',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await deleteNote(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message || '删除失败')
  }
}

function engineText(row: NoteVO) {
  if (!row.engine) return '-'
  return row.engine === 'LFASR' ? '语音转写·角色分离' : '语音听写·推断'
}

function engineTagType(row: NoteVO) {
  return row.engine === 'LFASR' ? ('success' as const) : ('warning' as const)
}
</script>

<template>
  <div class="note-panel">
    <el-alert type="info" :closable="false" show-icon class="intro">
      <template #title>
        上传一场<strong>真实面试</strong>的录音，AI 自动把它整理成面经
      </template>
      <div class="intro-sub">
        转写后自动区分「面试官 / 我」两个角色，去掉「啊、额、嗯」这类语气词与重复，再生成问题清单与复盘。
        录音越长处理越久，可以先去做别的。
      </div>
    </el-alert>

    <div class="toolbar">
      <el-upload
        :auto-upload="false"
        :show-file-list="false"
        :accept="AUDIO_ACCEPT"
        :on-change="handleUpload"
        :disabled="uploading"
      >
        <el-button type="primary" :loading="uploading">
          <el-icon style="margin-right: 4px"><Microphone /></el-icon>
          上传面试录音
        </el-button>
      </el-upload>
      <el-input v-model="company" placeholder="公司（可选）" clearable style="width: 160px" />
      <el-input v-model="position" placeholder="岗位（可选）" clearable style="width: 160px" />
      <span class="hint">
        支持 mp3 / wav / m4a / flac / opus · 已生成 {{ readyCount }} 篇
      </span>
    </div>

    <!-- 正在处理的那一条 -->
    <el-card v-if="activeTaskId" class="progress-card" shadow="never">
      <div class="progress-head">
        <el-icon class="spin"><Loading /></el-icon>
        <span class="stage">{{ activeStage || '处理中' }}</span>
        <span class="pct">{{ activeProgress }}%</span>
      </div>
      <el-progress :percentage="activeProgress" :stroke-width="10" :show-text="false" />
      <div class="progress-tip">这一步可能要几分钟到十几分钟，刷新页面也不会丢进度</div>
    </el-card>

    <el-empty
      v-if="!notes.length && !loading"
      description="还没有面经，上传一段面试录音试试"
    />

    <el-table v-else :data="notes" v-loading="loading" stripe class="table">
      <el-table-column label="标题 / 文件名" min-width="240" show-overflow-tooltip>
        <template #default="{ row }">
          <div class="title-cell">
            <span class="title">{{ row.title || row.fileName }}</span>
            <span class="file">{{ row.fileName }}</span>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="公司 / 岗位" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.company || row.position">{{ row.company }} {{ row.position }}</span>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>

      <el-table-column label="时长" width="100">
        <template #default="{ row }">{{ durationText(row.durationMs) }}</template>
      </el-table-column>

      <el-table-column label="处理情况" min-width="230">
        <template #default="{ row }">
          <div v-if="row.status === 0 || row.status === 1 || row.status === 2 || row.status === 3"
               class="running">
            <el-progress :percentage="row.progress || 0" :stroke-width="8" />
            <span class="stage-text">{{ row.stage || '处理中' }}</span>
          </div>
          <div v-else-if="row.status === 4" class="metric">
            <el-tag size="small" effect="plain">{{ row.turnCount }} 句</el-tag>
            <el-tag size="small" type="primary" effect="plain">
              {{ row.questionCount }} 个问题
            </el-tag>
            <el-tag size="small" :type="engineTagType(row)" effect="plain">
              {{ engineText(row) }}
            </el-tag>
          </div>
          <span v-else class="err">{{ row.errorMsg || '处理失败' }}</span>
        </template>
      </el-table-column>

      <el-table-column label="状态" width="96">
        <template #default="{ row }">
          <el-tag size="small" :type="NOTE_STATUS[row.status as 0 | 1 | 2 | 3 | 4 | 9]?.type">
            {{ NOTE_STATUS[row.status as 0 | 1 | 2 | 3 | 4 | 9]?.text || row.status }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" :disabled="row.status !== 4"
                     @click="openDetail(row)">查看面经</el-button>
          <el-button v-if="row.status === 9" link type="success" size="small"
                     @click="doRetry(row)">重试</el-button>
          <el-button link type="danger" size="small" @click="doDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.note-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.intro-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.progress-card {
  border-left: 3px solid var(--el-color-primary);
}

.progress-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.progress-head .stage {
  flex: 1;
  font-size: 13px;
}

.progress-head .pct {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-color-primary);
}

.spin {
  animation: spin 1.4s linear infinite;
  color: var(--el-color-primary);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.progress-tip {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.title-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.title-cell .title {
  font-weight: 500;
}

.title-cell .file {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.running {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.running .stage-text {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.metric {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.muted {
  color: var(--el-text-color-secondary);
}

.err {
  color: var(--el-color-danger);
  font-size: 12px;
}
</style>
