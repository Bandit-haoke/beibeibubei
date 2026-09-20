<script setup lang="ts">
/**
 * 面经详情：正文 + 逐句对话（按角色分色）+ 问题清单 + 原始转写。
 *
 * 三个 Tab 的取舍：
 *  - 「面经」是成品，给读者看的；
 *  - 「逐句对话」是过程，用来看 AI 分角色分得对不对；
 *  - 「原始转写」是底稿，怀疑 AI 漏掉/改错时可以逐句对照。
 * 三份都留着，是因为这类"AI 整理"最怕黑盒 —— 用户能核对，才会信任。
 *
 * Markdown 渲染没有引第三方库（项目里目前没有 markdown 依赖），
 * 就支持面经模板实际会产出的子集：标题、列表、加粗、行内代码。
 * 先转义再套标签，所以不会因为内容里带 < > 而注入 HTML。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  NOTE_STATUS,
  QUESTION_CATEGORY_COLOR,
  ROLE_LABEL,
  deleteNote,
  durationText,
  getNote,
  retryNote,
  stampText,
  updateNote,
  type NoteDetailVO,
  type TurnVO,
} from '@/api/interviewNote'
import { subscribeTask } from '@/api/task'

const route = useRoute()
const router = useRouter()

const noteId = Number(route.params.id)
const detail = ref<NoteDetailVO | null>(null)
const loading = ref(false)
const activeTab = ref('content')

/** 展示清洗前还是清洗后（逐句对话里可切换） */
const showRaw = ref(false)

const editing = ref(false)
const form = ref({ title: '', company: '', position: '' })

const activeTaskId = ref(0)
const activeProgress = ref(0)
const activeStage = ref('')
let unsubscribe: (() => void) | null = null
let pollTimer: number | null = null

const note = computed(() => detail.value?.note ?? null)
const running = computed(() => {
  const s = note.value?.status
  return s === 0 || s === 1 || s === 2 || s === 3
})

const interviewerTurns = computed(() =>
  (detail.value?.turns ?? []).filter((t) => t.role === 1),
)

// ---------------------------------------------------------------------------
//  数据
// ---------------------------------------------------------------------------

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    detail.value = await getNote(noteId)
    if (!editing.value) {
      form.value = {
        title: detail.value.note.title,
        company: detail.value.note.company,
        position: detail.value.note.position,
      }
    }
    if (running.value) startPolling()
    else stopPolling()
  } catch (e) {
    if (!silent) ElMessage.error((e as Error).message || '加载面经失败')
  } finally {
    if (!silent) loading.value = false
  }
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(() => {
    if (running.value) void load(true)
    else stopPolling()
  }, 5000)
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(() => void load())
onUnmounted(() => {
  unsubscribe?.()
  stopPolling()
})

// ---------------------------------------------------------------------------
//  操作
// ---------------------------------------------------------------------------

async function saveEdit() {
  try {
    await updateNote(noteId, {
      title: form.value.title,
      company: form.value.company,
      position: form.value.position,
    })
    ElMessage.success('已保存')
    editing.value = false
    await load(true)
  } catch (e) {
    ElMessage.error((e as Error).message || '保存失败')
  }
}

async function doRetry() {
  try {
    const taskId = await retryNote(noteId)
    ElMessage.success('已重新排队')
    activeTaskId.value = taskId
    activeProgress.value = 0
    activeStage.value = '排队中'
    await load(true)
    unsubscribe?.()
    unsubscribe = subscribeTask(taskId, {
      onProgress: (ev) => {
        activeProgress.value = ev.progress ?? 0
        activeStage.value = ev.stage || ''
      },
      onDone: () => {
        activeTaskId.value = 0
        ElMessage.success('面经已重新生成')
        void load(true)
      },
      onError: (ev) => {
        activeTaskId.value = 0
        ElMessage.error(ev.errorMsg || '重新整理失败')
        void load(true)
      },
    })
  } catch (e) {
    ElMessage.error((e as Error).message || '重试失败')
  }
}

async function doDelete() {
  try {
    await ElMessageBox.confirm('删除后音频文件与面经都会消失，不可恢复。', '删除面经', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await deleteNote(noteId)
    ElMessage.success('已删除')
    router.push('/interview')
  } catch (e) {
    ElMessage.error((e as Error).message || '删除失败')
  }
}

// ---------------------------------------------------------------------------
//  Markdown（极简子集）
// ---------------------------------------------------------------------------

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function inline(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+?)`/g, '<code>$1</code>')
}

function renderMarkdown(md: string): string {
  if (!md) return ''
  const lines = escapeHtml(md).split(/\r?\n/)
  const out: string[] = []
  let inList = false

  const closeList = () => {
    if (inList) {
      out.push('</ul>')
      inList = false
    }
  }

  for (const raw of lines) {
    const line = raw.trim()
    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    const bullet = line.match(/^[-*]\s+(.*)$/)
    const ordered = line.match(/^\d+[.)]\s+(.*)$/)

    if (heading) {
      closeList()
      const level = Math.min(heading[1].length + 1, 6)
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`)
    } else if (bullet || ordered) {
      if (!inList) {
        out.push('<ul>')
        inList = true
      }
      out.push(`<li>${inline((bullet ?? ordered)![1])}</li>`)
    } else if (!line) {
      closeList()
    } else {
      closeList()
      out.push(`<p>${inline(line)}</p>`)
    }
  }
  closeList()
  return out.join('\n')
}

const contentHtml = computed(() => renderMarkdown(detail.value?.content ?? ''))

// ---------------------------------------------------------------------------
//  展示辅助
// ---------------------------------------------------------------------------

function turnText(turn: TurnVO): string {
  return showRaw.value ? turn.rawText : turn.text
}

function roleClass(role: number): string {
  return role === 1 ? 'role-interviewer' : 'role-me'
}

function engineText(): string {
  const n = note.value
  if (!n?.engine) return '-'
  return n.engine === 'LFASR'
    ? '讯飞语音转写 · 原生角色分离'
    : '讯飞语音听写 · 大模型推断角色'
}
</script>

<template>
  <div class="note-detail" v-loading="loading">
    <div class="topbar">
      <el-button link :icon="'ArrowLeft'" @click="router.push('/interview')">返回模拟面试</el-button>
    </div>

    <el-card v-if="note" shadow="never" class="head">
      <template v-if="!editing">
        <div class="head-row">
          <h2 class="head-title">{{ note.title || note.fileName }}</h2>
          <div class="head-actions">
            <el-button size="small" @click="editing = true">编辑信息</el-button>
            <el-button size="small" :loading="running" @click="doRetry">重新整理</el-button>
            <el-button size="small" type="danger" plain @click="doDelete">删除</el-button>
          </div>
        </div>
        <div class="head-meta">
          <el-tag size="small" :type="NOTE_STATUS[note.status as 0 | 1 | 2 | 3 | 4 | 9]?.type">
            {{ NOTE_STATUS[note.status as 0 | 1 | 2 | 3 | 4 | 9]?.text }}
          </el-tag>
          <span v-if="note.company || note.position" class="meta-item">
            {{ note.company }} {{ note.position }}
          </span>
          <span class="meta-item">时长 {{ durationText(note.durationMs) }}</span>
          <span class="meta-item">{{ note.turnCount }} 句对话</span>
          <span class="meta-item">{{ note.questionCount }} 个提问</span>
          <span class="meta-item">{{ note.fileName }}</span>
        </div>
      </template>

      <template v-else>
        <el-form label-width="70px" class="edit-form">
          <el-form-item label="标题">
            <el-input v-model="form.title" placeholder="面经标题" />
          </el-form-item>
          <el-form-item label="公司">
            <el-input v-model="form.company" placeholder="公司（可选）" />
          </el-form-item>
          <el-form-item label="岗位">
            <el-input v-model="form.position" placeholder="岗位（可选）" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveEdit">保存</el-button>
            <el-button @click="editing = false">取消</el-button>
          </el-form-item>
        </el-form>
      </template>
    </el-card>

    <!-- 还在处理 -->
    <el-card v-if="running" shadow="never" class="progress-card">
      <div class="progress-head">
        <span class="stage">{{ activeStage || note?.stage || '处理中' }}</span>
        <span class="pct">{{ activeProgress || note?.progress || 0 }}%</span>
      </div>
      <el-progress
        :percentage="activeProgress || note?.progress || 0"
        :stroke-width="10"
        :show-text="false"
      />
      <div class="progress-tip">页面会自动刷新进度，可以先去做别的</div>
    </el-card>

    <el-alert v-if="note?.status === 9" type="error" :closable="false" show-icon class="fail">
      <template #title>整理失败</template>
      <div class="fail-msg">{{ note.errorMsg || '未知原因' }}</div>
      <div class="fail-hint">
        如果是「没有找到语音转写的凭据」或「服务时长不足」，说明当前走的是降级方案。
        降级方案本身可用，只是角色区分靠大模型推断而不是引擎原生分离。
      </div>
    </el-alert>

    <el-alert
      v-if="note?.status === 4"
      :type="note.roleSource === 'LFASR' ? 'success' : 'warning'"
      :closable="false"
      show-icon
      class="engine"
    >
      <template #title>角色来源：{{ engineText() }}</template>
      <div v-if="note.roleSource !== 'LFASR'" class="engine-hint">
        本次没有说话人分离，角色由大模型按内容推断，多人抢话时可能不准，可在「逐句对话」里核对。
        到「AI 配置」新增一条「讯飞语音转写」配置即可启用高精度分离。
      </div>
    </el-alert>

    <el-tabs v-if="note" v-model="activeTab" class="tabs">
      <!-- ---------- 面经正文 ---------- -->
      <el-tab-pane name="content">
        <template #label>面经</template>
        <el-card shadow="never" class="summary-card">
          <div class="summary">{{ note.summary || '（暂无总览）' }}</div>
          <div v-if="detail?.highlights?.length" class="highlights">
            <div class="section-title">经验点</div>
            <ul>
              <li v-for="(h, i) in detail.highlights" :key="i">{{ h }}</li>
            </ul>
          </div>
        </el-card>
        <div v-if="contentHtml" class="markdown" v-html="contentHtml"></div>
        <el-empty v-else description="还没有生成正文" />
      </el-tab-pane>

      <!-- ---------- 逐句对话 ---------- -->
      <el-tab-pane name="turns">
        <template #label>逐句对话（{{ detail?.turns?.length ?? 0 }}）</template>
        <div class="turn-toolbar">
          <el-switch v-model="showRaw" active-text="显示转写原文" inactive-text="显示清洗后" />
          <span class="hint">
            切成「原文」可以看出 AI 到底去掉了哪些语气词与重复
          </span>
        </div>
        <el-empty v-if="!detail?.turns?.length" description="还没有对话内容" />
        <div v-else class="turns">
          <div v-for="turn in detail.turns" :key="turn.seq" class="turn" :class="roleClass(turn.role)">
            <div class="turn-head">
              <span class="role">{{ ROLE_LABEL[turn.role] || '未知' }}</span>
              <span class="time">{{ stampText(turn.startMs) }}</span>
              <el-tag v-if="turn.removedWords" size="small" type="info" effect="plain">
                去掉：{{ turn.removedWords }}
              </el-tag>
            </div>
            <div class="turn-text">{{ turnText(turn) }}</div>
          </div>
        </div>
      </el-tab-pane>

      <!-- ---------- 问题清单 ---------- -->
      <el-tab-pane name="questions">
        <template #label>问题清单（{{ detail?.questions?.length ?? 0 }}）</template>
        <el-empty v-if="!detail?.questions?.length" description="还没有抽出问题" />
        <div v-else class="questions">
          <el-card v-for="(q, i) in detail.questions" :key="i" shadow="never" class="q-card">
            <div class="q-head">
              <span class="q-index">Q{{ i + 1 }}</span>
              <el-tag
                size="small"
                effect="plain"
                :style="{ color: QUESTION_CATEGORY_COLOR[q.category] || '#64748b',
                          borderColor: QUESTION_CATEGORY_COLOR[q.category] || '#64748b' }"
              >
                {{ q.category || '其他' }}
              </el-tag>
            </div>
            <div class="q-text">{{ q.question }}</div>
            <div class="q-answer">
              <span class="q-answer-label">回答要点</span>
              {{ q.answer || '（未记录）' }}
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- ---------- 原始转写 ---------- -->
      <el-tab-pane name="raw">
        <template #label>原始转写（{{ interviewerTurns.length }} 个提问）</template>
        <div class="hint" style="margin-bottom: 10px">
          这是未经清洗、未经角色归并的转写结果，用于和上面两栏对照核对。
        </div>
        <el-empty v-if="!detail?.turns?.length" description="没有原始转写" />
        <el-table v-else :data="detail.turns" stripe size="small">
          <el-table-column prop="seq" label="#" width="60" />
          <el-table-column label="时间" width="80">
            <template #default="{ row }">{{ stampText(row.startMs) }}</template>
          </el-table-column>
          <el-table-column label="角色" width="80">
            <template #default="{ row }">
              <span :class="roleClass(row.role)">{{ ROLE_LABEL[row.role] || '未知' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="rawText" label="转写原文" min-width="320" show-overflow-tooltip />
          <el-table-column prop="cleanText" label="清洗后" min-width="320" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.note-detail {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.topbar {
  margin-bottom: -6px;
}

.head-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.head-title {
  flex: 1;
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.head-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.edit-form {
  max-width: 520px;
}

.progress-card {
  border-left: 3px solid var(--el-color-primary);
}

.progress-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 13px;
}

.progress-head .pct {
  font-weight: 600;
  color: var(--el-color-primary);
}

.progress-tip {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.fail-msg {
  margin-top: 4px;
  font-size: 13px;
}

.fail-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.engine-hint {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
}

.summary-card {
  margin-bottom: 14px;
}

.summary {
  font-size: 14px;
  line-height: 1.8;
}

.highlights {
  margin-top: 12px;
}

.section-title {
  font-weight: 600;
  margin-bottom: 6px;
}

.highlights ul {
  margin: 0;
  padding-left: 20px;
  line-height: 1.9;
  font-size: 13px;
}

.markdown {
  line-height: 1.9;
  font-size: 14px;
}

.markdown :deep(h2) {
  margin: 20px 0 10px;
  font-size: 16px;
  font-weight: 600;
  padding-left: 9px;
  border-left: 3px solid var(--el-color-primary);
}

.markdown :deep(h3) {
  margin: 16px 0 8px;
  font-size: 14px;
  font-weight: 600;
}

.markdown :deep(p) {
  margin: 8px 0;
}

.markdown :deep(ul) {
  margin: 8px 0;
  padding-left: 22px;
}

.markdown :deep(li) {
  margin: 4px 0;
}

.markdown :deep(code) {
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--el-fill-color-light);
  font-size: 13px;
}

.turn-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.turns {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.turn {
  padding: 10px 14px;
  border-radius: 8px;
  border-left: 3px solid transparent;
}

.turn.role-interviewer {
  background: var(--el-fill-color-light);
  border-left-color: #4c7cf3;
}

.turn.role-me {
  background: var(--el-color-primary-light-9);
  border-left-color: #10b981;
}

.turn-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 5px;
}

.turn-head .role {
  font-size: 12px;
  font-weight: 600;
}

.role-interviewer .role {
  color: #4c7cf3;
}

.role-me .role {
  color: #10b981;
}

.turn-head .time {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.turn-text {
  font-size: 14px;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
}

.questions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.q-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.q-index {
  font-weight: 600;
  color: var(--el-color-primary);
}

.q-text {
  font-size: 14px;
  font-weight: 500;
  line-height: 1.7;
}

.q-answer {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--el-text-color-regular);
}

.q-answer-label {
  display: inline-block;
  margin-right: 6px;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--el-fill-color-light);
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
