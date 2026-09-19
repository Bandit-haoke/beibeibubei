<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  saveDraft,
  startExam,
  submitExam,
  type AnswerPayload,
  type ExamQuestion,
  type StartResult,
} from '@/api/exam'
import { subscribeTask, type TaskEvent } from '@/api/task'
import VoiceInput from '@/components/VoiceInput.vue'

const route = useRoute()
const router = useRouter()
const paperId = Number(route.params.paperId)

const loading = ref(true)
const exam = ref<StartResult | null>(null)
const answers = ref<Record<number, string>>({})
const asrTexts = ref<Record<number, string>>({})
const inputModes = ref<Record<number, number>>({})
const current = ref(0)

const elapsed = ref(0)
const submitting = ref(false)
const gradeProgress = ref(0)
const gradeStage = ref('')
let timer: number | null = null
let autoSave: number | null = null
let closer: (() => void) | null = null

const questions = computed<ExamQuestion[]>(() => exam.value?.questions || [])
const currentQ = computed<ExamQuestion | null>(() => questions.value[current.value] || null)

const answeredCount = computed(
  () => questions.value.filter((q) => (answers.value[q.questionId] || '').trim()).length,
)

function fmtDuration(sec: number) {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function isAnswered(q: ExamQuestion) {
  return !!(answers.value[q.questionId] || '').trim()
}

/** 多选题的答案在 UI 上是数组，存的时候要拼成 "AC" 这种形式 */
function multiValue(q: ExamQuestion): string[] {
  const raw = answers.value[q.questionId] || ''
  return raw ? raw.split('') : []
}

function setMulti(q: ExamQuestion, keys: string[]) {
  answers.value[q.questionId] = keys.slice().sort().join('')
  inputModes.value[q.questionId] = 1
}

function setSingle(q: ExamQuestion, key: string) {
  answers.value[q.questionId] = key
  inputModes.value[q.questionId] = 1
}

function onVoiceText(q: ExamQuestion, text: string) {
  const old = answers.value[q.questionId] || ''
  answers.value[q.questionId] = old ? `${old} ${text}` : text
  asrTexts.value[q.questionId] = text
  inputModes.value[q.questionId] = 2
}

function buildPayload(): AnswerPayload[] {
  return questions.value.map((q) => ({
    questionId: q.questionId,
    userAnswer: answers.value[q.questionId] || '',
    asrText: asrTexts.value[q.questionId] || undefined,
    inputMode: inputModes.value[q.questionId] || 1,
  }))
}

async function doAutoSave(silent = true) {
  if (!exam.value || submitting.value) return
  try {
    await saveDraft(exam.value.examId, buildPayload(), elapsed.value)
    if (!silent) ElMessage.success('已保存')
  } catch {
    // 自动保存失败不打扰用户
  }
}

async function submit() {
  if (!exam.value || submitting.value) return

  const unanswered = questions.value.length - answeredCount.value
  try {
    await ElMessageBox.confirm(
      unanswered > 0
        ? `还有 ${unanswered} 道题没答，交卷后未答题按 0 分计。确认交卷？`
        : '全部题目已作答，确认交卷并开始判分？',
      '交卷',
      { type: 'warning', confirmButtonText: '交卷', cancelButtonText: '再检查一下' },
    )
  } catch {
    return
  }

  submitting.value = true
  gradeProgress.value = 0
  gradeStage.value = '正在提交 ...'

  try {
    const taskId = await submitExam(exam.value.examId, buildPayload(), elapsed.value)
    ElMessage.info('已交卷，AI 正在判分 ...')

    closer = subscribeTask(taskId, {
      onProgress: (e: TaskEvent) => {
        gradeProgress.value = e.progress ?? 0
        gradeStage.value = e.stage || ''
      },
      onDone: (e: TaskEvent) => {
        gradeProgress.value = 100
        const r = (e.result || {}) as Record<string, number>
        gradeStage.value = `判分完成：${r.gotScore ?? 0} / ${r.totalScore ?? 0} 分（${r.scoreRate ?? 0}%）`
        stopTimers()
        setTimeout(() => router.replace(`/exam/${exam.value!.examId}/result`), 800)
      },
      onError: (e: TaskEvent) => {
        gradeStage.value = `判分失败：${e.errorMsg}`
        ElMessage.error(e.errorMsg || '判分失败')
        submitting.value = false
        // 判分失败也能进结果页（客观题的分已经出来了）
        setTimeout(() => router.replace(`/exam/${exam.value!.examId}/result`), 1500)
      },
    })
  } catch {
    submitting.value = false
  }
}

function stopTimers() {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
  if (autoSave !== null) {
    window.clearInterval(autoSave)
    autoSave = null
  }
}

onMounted(async () => {
  try {
    exam.value = await startExam(paperId, 2)
    // 回填已保存的作答（断点续答）
    for (const q of exam.value.questions) {
      if (q.savedAnswer) {
        answers.value[q.questionId] = q.savedAnswer
      }
      if (q.savedInputMode) {
        inputModes.value[q.questionId] = q.savedInputMode
      }
    }
    // 已经有作答的题说明是续答，起始位置跳到最后一道未答题
    const firstUnanswered = exam.value.questions.findIndex((q) => !q.savedAnswer)
    current.value = firstUnanswered >= 0 ? firstUnanswered : 0

    timer = window.setInterval(() => { elapsed.value += 1 }, 1000)
    autoSave = window.setInterval(() => doAutoSave(true), 30000)
  } catch {
    ElMessage.error('无法开始作答，请先在审核页把题目通过审核')
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  stopTimers()
  closer?.()
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <div style="display: flex; align-items: center; gap: 10px">
          <h2 style="margin: 0">{{ exam?.title || '答题' }}</h2>
          <el-tag type="warning" effect="dark" class="timer">{{ fmtDuration(elapsed) }}</el-tag>
        </div>
        <div class="sub">
          已答 {{ answeredCount }} / {{ questions.length }} 道 ·
          满分 {{ exam?.totalScore }} 分 ·
          <a style="color: #4c7cf3; cursor: pointer" @click="doAutoSave(false)">立即保存草稿</a>
        </div>
      </div>
      <el-button type="primary" size="large" :loading="submitting" @click="submit">交卷</el-button>
    </div>

    <el-alert
      v-if="submitting"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 14px"
    >
      <template #title>{{ gradeStage }}</template>
      <el-progress :percentage="gradeProgress" :stroke-width="10" style="margin-top: 8px" />
    </el-alert>

    <el-row :gutter="16">
      <!-- 题号导航 -->
      <el-col :xs="24" :md="5">
        <el-card shadow="never" class="nav-card">
          <template #header><b>题号</b></template>
          <div class="nav-grid">
            <div
              v-for="(q, i) in questions"
              :key="q.questionId"
              class="nav-cell"
              :class="{ active: i === current, done: isAnswered(q) }"
              @click="current = i"
            >
              {{ i + 1 }}
            </div>
          </div>
          <div class="nav-legend">
            <span><i class="dot done"></i>已答</span>
            <span><i class="dot"></i>未答</span>
          </div>
        </el-card>
      </el-col>

      <!-- 题目 -->
      <el-col :xs="24" :md="19">
        <el-card v-if="currentQ" shadow="never">
          <div class="q-head">
            <span class="q-no">第 {{ current + 1 }} 题</span>
            <el-tag size="small" type="primary" effect="plain">{{ currentQ.qTypeName }}</el-tag>
            <el-tag size="small" effect="plain">{{ currentQ.difficultyName }}</el-tag>
            <el-tag size="small" type="warning" effect="plain">{{ currentQ.fullScore }} 分</el-tag>
          </div>

          <div class="q-stem">{{ currentQ.stem }}</div>

          <pre v-if="currentQ.codeSnippet" class="q-code">{{ currentQ.codeSnippet }}</pre>

          <!-- 单选 -->
          <el-radio-group
            v-if="currentQ.qType === 1"
            :model-value="answers[currentQ.questionId] || ''"
            class="opt-group"
            @update:model-value="(v: any) => setSingle(currentQ!, String(v))"
          >
            <el-radio v-for="o in currentQ.options" :key="o.key" :value="o.key" class="opt">
              <b>{{ o.key }}.</b> {{ o.content }}
            </el-radio>
          </el-radio-group>

          <!-- 多选 -->
          <el-checkbox-group
            v-else-if="currentQ.qType === 2"
            :model-value="multiValue(currentQ)"
            class="opt-group"
            @update:model-value="(v: any) => setMulti(currentQ!, v as string[])"
          >
            <el-checkbox v-for="o in currentQ.options" :key="o.key" :value="o.key" class="opt">
              <b>{{ o.key }}.</b> {{ o.content }}
            </el-checkbox>
          </el-checkbox-group>

          <!-- 判断 -->
          <el-radio-group
            v-else-if="currentQ.qType === 3"
            :model-value="answers[currentQ.questionId] || ''"
            class="opt-group"
            @update:model-value="(v: any) => setSingle(currentQ!, String(v))"
          >
            <el-radio value="正确" class="opt">正确</el-radio>
            <el-radio value="错误" class="opt">错误</el-radio>
          </el-radio-group>

          <!-- 主观题 -->
          <div v-else>
            <el-input
              :model-value="answers[currentQ.questionId] || ''"
              type="textarea"
              :rows="currentQ.qType === 6 || currentQ.qType === 7 ? 8 : 4"
              placeholder="写出你的答案；也可以长按空格用语音输入（可切换为点按模式）"
              @update:model-value="(v: string) => { answers[currentQ!.questionId] = v; inputModes[currentQ!.questionId] = 1 }"
            />
            <div class="input-bar">
              <VoiceInput :kb-id="exam?.kbId || 0" @text="(t: string) => onVoiceText(currentQ!, t)" />
              <span class="tip">语音识别后会自动纠正专有名词，并填入上方输入框（可再编辑）。空格快捷键在光标离开输入框后生效</span>
            </div>
          </div>

          <div class="q-footer">
            <el-button :disabled="current === 0" @click="current -= 1">上一题</el-button>
            <el-button
              :disabled="current >= questions.length - 1"
              type="primary"
              @click="current += 1"
            >
              下一题
            </el-button>
            <div style="flex: 1"></div>
            <span class="pos">{{ current + 1 }} / {{ questions.length }}</span>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.timer {
  font-family: Consolas, monospace;
  font-size: 15px;
}

.nav-card {
  position: sticky;
  top: 16px;
}

.nav-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 6px;
}

.nav-cell {
  height: 32px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.12s;
}

.nav-cell:hover {
  border-color: #4c7cf3;
}

.nav-cell.done {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #047857;
}

.nav-cell.active {
  background: #4c7cf3;
  border-color: #4c7cf3;
  color: #fff;
  font-weight: 700;
}

.nav-legend {
  display: flex;
  gap: 14px;
  margin-top: 12px;
  font-size: 12px;
  color: #94a3b8;
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  border: 1px solid #e2e8f0;
  margin-right: 4px;
}

.dot.done {
  background: #ecfdf5;
  border-color: #a7f3d0;
}

.q-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.q-no {
  font-weight: 700;
  color: #4c7cf3;
  font-size: 14px;
}

.q-stem {
  font-size: 15px;
  line-height: 1.8;
  color: #1e293b;
  margin-bottom: 14px;
  white-space: pre-wrap;
}

.q-code {
  background: #f8fafc;
  border-radius: 6px;
  padding: 12px;
  font-family: Consolas, monospace;
  font-size: 12.5px;
  color: #334155;
  overflow-x: auto;
  margin-bottom: 14px;
}

.opt-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
}

.opt {
  display: flex;
  align-items: flex-start;
  white-space: normal;
  height: auto;
  padding: 8px 10px;
  border-radius: 6px;
  line-height: 1.65;
}

.opt:hover {
  background: #f8fafc;
}

.input-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}

.tip {
  font-size: 12px;
  color: #94a3b8;
}

.q-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px solid #f1f5f9;
}

.pos {
  font-size: 13px;
  color: #94a3b8;
}
</style>
