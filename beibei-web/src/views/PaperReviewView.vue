<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  approveAll,
  approveQuestions,
  deleteQuestion,
  getPaper,
  getPaperReview,
  PAPER_STATUS,
  Q_TYPE_OPTIONS,
  regeneratePaper,
  updateQuestion,
  type PaperVO,
  type QuestionVO,
} from '@/api/paper'
import { subscribeTask, type TaskEvent } from '@/api/task'

const route = useRoute()
const router = useRouter()
const paperId = Number(route.params.id)

const paper = ref<PaperVO | null>(null)
const allQuestions = ref<QuestionVO[]>([])
const drafts = ref<QuestionVO[]>([])
const loading = ref(false)
const scope = ref<'draft' | 'all'>('draft')
const regenerating = ref(false)
const regenStage = ref('')

const shown = computed(() => (scope.value === 'draft' ? drafts.value : allQuestions.value))

async function load() {
  loading.value = true
  try {
    const [full, review] = await Promise.all([getPaper(paperId), getPaperReview(paperId)])
    paper.value = full.paper
    allQuestions.value = full.questions
    drafts.value = review.questions
  } finally {
    loading.value = false
  }
}

async function doApprove(ids: number[]) {
  if (!ids.length) return
  const n = await approveQuestions(ids)
  ElMessage.success(`已通过 ${n} 道`)
  await load()
}

async function doApproveAll() {
  await ElMessageBox.confirm(
    `把本卷全部 ${drafts.value.length} 道草稿题一次性发布？发布后就可以用来组卷答题。`,
    '整卷通过',
    { type: 'warning' },
  )
  const n = await approveAll(paperId)
  ElMessage.success(`已通过 ${n} 道`)
  await load()
}

async function doDelete(q: QuestionVO) {
  await ElMessageBox.confirm('删除这道题？不可恢复。', '删除题目', { type: 'warning' })
  await deleteQuestion(q.id)
  ElMessage.success('已删除')
  const fresh = await getPaper(paperId)
  paper.value = fresh.paper
  await load()
}

async function doRegenerate() {
  await ElMessageBox.confirm(
    '重新出题会先清空本卷里所有「待审」的草稿题，然后按同样的配置再生成一次。已发布的题不受影响。',
    '重新出题',
    { type: 'warning' },
  )
  regenerating.value = true
  regenStage.value = '提交中'
  try {
    const res = await regeneratePaper(paperId, paper.value?.totalCount || undefined)
    ElMessage.info('已重新提交，正在生成 ...')
    subscribeTask(res.taskId, {
      onProgress: (e: TaskEvent) => { regenStage.value = e.stage || '' },
      onDone: async () => {
        regenerating.value = false
        regenStage.value = '完成'
        ElMessage.success('重新生成完成')
        await load()
      },
      onError: (e: TaskEvent) => {
        regenerating.value = false
        regenStage.value = ''
        ElMessage.error(e.errorMsg || '生成失败')
      },
    })
  } catch {
    regenerating.value = false
  }
}

// ---------------- 编辑 ----------------
const editVisible = ref(false)
const editForm = ref<QuestionVO | null>(null)
const saving = ref(false)

function openEdit(q: QuestionVO) {
  // 深拷贝，取消编辑不影响原数据
  editForm.value = JSON.parse(JSON.stringify(q))
  editVisible.value = true
}

async function saveEdit() {
  if (!editForm.value) return
  const q = editForm.value
  saving.value = true
  try {
    await updateQuestion(q.id, {
      stem: q.stem,
      answer: q.answer,
      analysis: q.analysis,
      difficulty: q.difficulty,
      codeSnippet: q.codeSnippet,
      options: q.options?.map((o) => ({ key: o.key, content: o.content, correct: o.correct })),
      tagIds: q.tags?.map((t) => t.id),
    })
    ElMessage.success('已保存')
    editVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

function qualityColor(score: number | null) {
  const v = score ?? 1
  return v >= 0.8 ? '#10b981' : v >= 0.6 ? '#e6a23c' : '#ef4444'
}

/**
 * 导出走浏览器直接下载（后端返回附件响应），
 * 不用 axios —— 否则要处理 Blob 与文件名解析，反而更绕。
 */
function doExport(format: string) {
  if (!paper.value?.kbId) return
  const url = `/api/question/export?kbId=${paper.value.kbId}&status=1&format=${format}`
  window.open(url, '_blank')
  ElMessage.success('已开始下载（只导出已发布的题目）')
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <div style="display: flex; align-items: center; gap: 8px">
          <el-button link :icon="'ArrowLeft'" @click="router.push(`/kb/${paper?.kbId}/generate`)">
            出题页
          </el-button>
          <h2 style="margin: 0">{{ paper?.title || '题卷审核' }}</h2>
        </div>
        <div class="sub">
          AI 生成的题都是草稿，通过之后才会进入可用的题库
        </div>
      </div>
      <div style="display: flex; gap: 10px; align-items: center">
        <el-radio-group v-model="scope" size="small">
          <el-radio-button value="draft">待审 {{ drafts.length }}</el-radio-button>
          <el-radio-button value="all">全部 {{ allQuestions.length }}</el-radio-button>
        </el-radio-group>
        <el-button :icon="'Refresh'" :disabled="regenerating" @click="doRegenerate">
          重新出题
        </el-button>
        <el-button
          type="primary"
          :icon="'Select'"
          :disabled="!drafts.length || regenerating"
          @click="doApproveAll"
        >
          整卷通过
        </el-button>
        <el-button
          type="success"
          :icon="'Tickets'"
          :disabled="!paper?.publishedCount || regenerating"
          @click="router.push(`/exam/start/${paperId}`)"
        >
          开始答题
        </el-button>
        <el-dropdown trigger="click" @command="doExport">
          <el-button :icon="'Download'">导出题库<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="anki">导出 Anki（.txt，手机背）</el-dropdown-item>
              <el-dropdown-item command="csv">导出 Excel（.csv）</el-dropdown-item>
              <el-dropdown-item command="json">导出 JSON（全量字段）</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <el-alert
      v-if="paper"
      :type="PAPER_STATUS[paper.status]?.type === 'danger' ? 'error' : 'info'"
      :closable="false"
      show-icon
      style="margin-bottom: 14px"
    >
      <template #title>
        状态：{{ PAPER_STATUS[paper.status]?.text }} ·
        共 {{ paper.totalCount }} 道 / {{ paper.totalScore }} 分 ·
        待审 {{ paper.draftCount }} · 已发布 {{ paper.publishedCount }}
      </template>
      <div v-if="paper.genSummary" class="mono" style="font-size: 12.5px">
        生成统计：请求 {{ paper.genSummary.requested }} ·
        生成 {{ paper.genSummary.generated }} ·
        结构校验丢弃 {{ paper.genSummary.droppedByValidate ?? 0 }} ·
        自检丢弃 {{ paper.genSummary.droppedBySelfCheck ?? 0 }} ·
        查重丢弃 {{ paper.genSummary.droppedByDedup ?? 0 }} ·
        入库 {{ paper.genSummary.saved }}
      </div>
    </el-alert>

    <el-alert
      v-if="regenerating"
      type="warning"
      :closable="false"
      show-icon
      :title="`正在重新生成：${regenStage}`"
      style="margin-bottom: 14px"
    />

    <el-empty v-if="!shown.length" description="没有待审的题目" />

    <el-card v-for="(q, i) in shown" :key="q.id" shadow="never" class="q-card">
      <div class="q-head">
        <span class="q-index">{{ i + 1 }}</span>
        <el-tag size="small" type="primary" effect="plain">{{ q.qTypeName }}</el-tag>
        <el-tag size="small" effect="plain">{{ q.difficultyName }}</el-tag>
        <el-tag size="small" :type="q.origin === 1 ? 'info' : 'success'" effect="plain">
          {{ q.origin === 1 ? 'AI 生成' : '手动录入' }}
        </el-tag>
        <el-tooltip :content="q.selfCheckMsg || '自检未执行'" placement="top">
          <span class="q-quality" :style="{ color: qualityColor(q.qualityScore) }">
            自检 {{ q.qualityScore != null ? Number(q.qualityScore).toFixed(2) : '-' }}
          </span>
        </el-tooltip>
        <el-tag
          v-for="t in q.tags"
          :key="t.id"
          size="small"
          :type="t.level === 1 ? 'warning' : 'success'"
          effect="plain"
        >
          {{ t.name }}
        </el-tag>
        <div style="flex: 1"></div>
        <el-tag v-if="q.status === 0" size="small" type="warning">待审</el-tag>
        <el-tag v-else-if="q.status === 1" size="small" type="success">已发布</el-tag>
        <el-tag v-else size="small" type="danger">已停用</el-tag>
      </div>

      <div class="q-stem">{{ q.stem }}</div>

      <div v-if="q.codeSnippet" class="q-code">
        <pre>{{ q.codeSnippet }}</pre>
      </div>

      <div v-if="q.options?.length" class="q-options">
        <div
          v-for="o in q.options"
          :key="o.key"
          class="q-option"
          :class="{ correct: o.correct }"
        >
          <b>{{ o.key }}.</b>
          <span>{{ o.content }}</span>
          <el-icon v-if="o.correct" color="#10b981"><CircleCheckFilled /></el-icon>
        </div>
      </div>

      <div class="q-block">
        <span class="q-label">答案</span>
        <span>{{ q.answer }}</span>
      </div>

      <div v-if="q.rubric?.length" class="q-block">
        <span class="q-label">评分要点</span>
        <div style="flex: 1">
          <div v-for="(p, pi) in q.rubric" :key="pi" class="rubric-row">
            <el-tag size="small" type="warning" effect="plain">{{ p.score }} 分</el-tag>
            <span>{{ p.point }}</span>
          </div>
        </div>
      </div>

      <div v-if="q.analysis" class="q-block analysis">
        <span class="q-label">解析</span>
        <span>{{ q.analysis }}</span>
      </div>

      <div class="q-actions">
        <el-button
          v-if="q.status === 0"
          type="success"
          size="small"
          :icon="'Select'"
          @click="doApprove([q.id])"
        >
          通过
        </el-button>
        <el-button size="small" :icon="'Edit'" @click="openEdit(q)">编辑</el-button>
        <el-button size="small" type="danger" :icon="'Delete'" @click="doDelete(q)">删除</el-button>
        <span class="q-source">依据分块：{{ q.sourceChunkIds?.join(', ') || '—' }}</span>
      </div>
    </el-card>

    <!-- 编辑弹窗 -->
    <el-dialog v-model="editVisible" title="编辑题目" width="760px" top="5vh">
      <el-form v-if="editForm" label-width="72px">
        <el-form-item label="题干">
          <el-input v-model="editForm.stem" type="textarea" :rows="3" />
        </el-form-item>

        <el-form-item v-if="editForm.options?.length" label="选项">
          <div style="width: 100%">
            <div v-for="o in editForm.options" :key="o.key" class="edit-option">
              <b style="width: 18px">{{ o.key }}</b>
              <el-input v-model="o.content" size="small" />
              <el-checkbox v-model="o.correct" label="正确" />
            </div>
          </div>
        </el-form-item>

        <el-form-item label="答案">
          <el-input v-model="editForm.answer" type="textarea" :rows="3" />
        </el-form-item>

        <el-form-item label="解析">
          <el-input v-model="editForm.analysis" type="textarea" :rows="3" />
        </el-form-item>

        <el-form-item label="难度">
          <el-radio-group v-model="editForm.difficulty">
            <el-radio-button :value="1">易</el-radio-button>
            <el-radio-button :value="2">中</el-radio-button>
            <el-radio-button :value="3">难</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.q-card {
  margin-bottom: 14px;
}

.q-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.q-index {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: #eef2ff;
  color: #4c7cf3;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.q-quality {
  font-size: 12px;
  font-weight: 600;
}

.q-stem {
  font-size: 14.5px;
  line-height: 1.75;
  color: #1e293b;
  margin-bottom: 10px;
  white-space: pre-wrap;
}

.q-code {
  background: #f8fafc;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
  overflow-x: auto;
}

.q-code pre {
  margin: 0;
  font-family: Consolas, monospace;
  font-size: 12.5px;
  color: #334155;
}

.q-options {
  margin-bottom: 10px;
}

.q-option {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 13.5px;
  color: #475569;
  line-height: 1.6;
}

.q-option.correct {
  background: #f0fdf4;
  color: #166534;
}

.q-block {
  display: flex;
  gap: 10px;
  font-size: 13.5px;
  color: #334155;
  line-height: 1.7;
  padding: 8px 10px;
  background: #f8fafc;
  border-radius: 6px;
  margin-bottom: 8px;
}

.q-block.analysis {
  background: #fffbeb;
  color: #78350f;
}

.q-label {
  flex-shrink: 0;
  font-weight: 600;
  color: #94a3b8;
  font-size: 12.5px;
  padding-top: 2px;
}

.rubric-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  margin-bottom: 4px;
}

.q-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
}

.q-source {
  margin-left: auto;
  font-size: 12px;
  color: #cbd5e1;
}

.edit-option {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
</style>
