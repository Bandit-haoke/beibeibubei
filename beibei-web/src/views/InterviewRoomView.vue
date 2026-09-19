<script setup lang="ts">
/**
 * 面试室：聊天式模拟面试。
 *
 * 交互取舍：
 *  1. 面试官问题在左、候选人回答在右，和真实聊天一致；
 *  2. 每个问题都显示「题型 + 依据」（依据来自简历哪一段）——
 *     这是这个功能区别于「和 AI 随便聊聊」的地方：你随时知道它为什么问这个；
 *  3. 每条回答旁边挂分数，点开是五维明细与点评，**评分是实时可见的**，
 *     不要攒到最后才给，那样中途就没有改进机会；
 *  4. 最后一步生成报告是单独一次请求，因为它要读整场记录。
 */
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  DIFFICULTY,
  QUESTION_TYPE,
  answerInterview,
  finishInterview,
  getInterview,
  type InterviewVO,
  type QuestionVO,
  type TurnVO,
} from '@/api/interview'
import VoiceInput from '@/components/VoiceInput.vue'

const route = useRoute()
const router = useRouter()
const interviewId = Number(route.params.id)

const interview = ref<InterviewVO | null>(null)
const turns = ref<TurnVO[]>([])
const draft = ref('')
const loading = ref(false)
const submitting = ref(false)
const finishing = ref(false)

const listRef = ref<HTMLDivElement>()

const kbIdForAsr = computed(() => interview.value?.kbId ?? 0)
const turnCount = computed(() => interview.value?.turnCount ?? 0)
const maxTurns = computed(() => interview.value?.maxTurns ?? 10)
const percent = computed(() => Math.round((turnCount.value / Math.max(1, maxTurns.value)) * 100))

/**
 * 轮数是否用完。
 *
 * 刻意用「派生」而不是用 answer 接口返回的 finished 存一份状态：
 * 中途刷新页面时后端只告诉我们 turnCount 和 maxTurns，
 * 存下来的 finished 会丢，用户就会看到一个本该结束的面试还在等他输入。
 */
const finished = computed(() => turnCount.value >= maxTurns.value)

/** 最后一条是面试官提问 → 轮到用户回答 */
const awaitingAnswer = computed(() => {
  const last = turns.value[turns.value.length - 1]
  return !!last && last.role === 1
})

/** 每题类型标签 */
const typeMeta = (type: string) =>
  QUESTION_TYPE[type as keyof typeof QUESTION_TYPE] ?? { text: type || '提问', color: '#64748b' }

const scoreColor = (score?: number | null) => {
  if (score == null) return '#94a3b8'
  if (score >= 85) return '#10b981'
  if (score >= 70) return '#f59e0b'
  return '#ef4444'
}

function appendQuestion(q: QuestionVO) {
  turns.value.push({
    id: -Date.now(),
    seq: turns.value.length + 1,
    role: 1,
    content: q.question,
    questionType: q.type,
    basedOn: q.basedOn,
    expects: q.expects ?? [],
    score: null,
    feedback: null,
    createdAt: '',
  })
}

async function scrollBottom() {
  await nextTick()
  const el = listRef.value
  if (el) el.scrollTop = el.scrollHeight
}

async function load() {
  loading.value = true
  try {
    const res = await getInterview(interviewId)
    interview.value = res.interview
    turns.value = res.turns
    if (res.interview.status === 2) {
      await router.replace(`/interview/${interviewId}/report`)
      return
    }
    await scrollBottom()
  } finally {
    loading.value = false
  }
}

async function submit() {
  const answer = draft.value.trim()
  if (!answer) {
    ElMessage.warning('请先说出或输入你的回答')
    return
  }
  submitting.value = true
  try {
    const res = await answerInterview(interviewId, answer)
    turns.value.push({
      id: -Date.now(),
      seq: turns.value.length + 1,
      role: 2,
      content: answer,
      questionType: '',
      basedOn: '',
      expects: [],
      score: res.evaluation?.score ?? null,
      feedback: res.evaluation ?? null,
      createdAt: '',
    })
    draft.value = ''
    if (interview.value) {
      interview.value.turnCount = res.turnCount
      interview.value.maxTurns = res.maxTurns
    }
    if (res.nextQuestion) {
      appendQuestion(res.nextQuestion)
    }
    await scrollBottom()
    if (res.finished) {
      ElMessage.success('轮数已用完，可以生成评估报告了')
    }
  } finally {
    submitting.value = false
  }
}

function onVoice(text: string) {
  draft.value = draft.value ? `${draft.value} ${text}` : text
}

async function doFinish() {
  if (!turns.value.some((t) => t.role === 2)) {
    ElMessage.warning('至少回答一轮才能生成报告')
    return
  }
  if (!finished.value) {
    await ElMessageBox.confirm(
      '提前结束会按目前的回答出报告，后面的轮次就没有了。确定结束吗？',
      '结束面试',
      { type: 'warning' },
    )
  }
  finishing.value = true
  try {
    await finishInterview(interviewId)
    ElMessage.success('报告已生成')
    await router.push(`/interview/${interviewId}/report`)
  } finally {
    finishing.value = false
  }
}

function onKeydown(e: KeyboardEvent) {
  // Ctrl/Cmd + Enter 提交：回车留给换行，长回答不会被误提交
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    void submit()
  }
}

onMounted(load)
onUnmounted(() => {
  /* 无需清理，SSE 只在首页用 */
})
</script>

<template>
  <div v-loading="loading" class="room">
    <!-- 顶栏 -->
    <div class="room-head">
      <div class="head-left">
        <el-button link @click="router.push('/interview')">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
        <div class="title">
          <b>{{ interview?.jobTitle || '模拟面试' }}</b>
          <span class="muted">
            {{ interview ? DIFFICULTY[interview.difficulty as 1 | 2 | 3] : '' }}
            · 简历「{{ interview?.resumeName }}」
          </span>
        </div>
      </div>
      <div class="head-right">
        <el-progress :percentage="percent" :stroke-width="8" :show-text="false" style="width: 160px" />
        <span class="muted">第 {{ turnCount }} / {{ maxTurns }} 轮</span>
        <el-button type="primary" :loading="finishing" @click="doFinish">
          {{ finished ? '生成评估报告' : '提前结束并出报告' }}
        </el-button>
      </div>
    </div>

    <!-- 对话区 -->
    <div ref="listRef" class="chat">
      <div v-for="t in turns" :key="t.id" class="row" :class="t.role === 1 ? 'left' : 'right'">
        <div class="avatar" :class="t.role === 1 ? 'bot' : 'me'">
          {{ t.role === 1 ? '面' : '我' }}
        </div>
        <div class="bubble-wrap">
          <div v-if="t.role === 1" class="meta">
            <el-tag size="small" effect="dark"
                    :style="{ background: typeMeta(t.questionType).color, borderColor: typeMeta(t.questionType).color }">
              {{ typeMeta(t.questionType).text }}
            </el-tag>
            <span v-if="t.basedOn" class="based-on" :title="t.basedOn">
              依据：{{ t.basedOn }}
            </span>
          </div>

          <div class="bubble" :class="t.role === 1 ? 'bubble-bot' : 'bubble-me'">
            {{ t.content }}
          </div>

          <!-- 期望要点：帮助自评「我答到点上了吗」 -->
          <div v-if="t.role === 1 && t.expects?.length" class="expects">
            期望覆盖：{{ t.expects.join('、') }}
          </div>

          <!-- 评分明细 -->
          <div v-if="t.role === 2 && t.feedback" class="feedback">
            <div class="fb-head">
              <span class="fb-score" :style="{ color: scoreColor(t.score) }">{{ t.score }}</span>
              <span class="muted">本轮得分</span>
            </div>
            <div class="dims">
              <div v-for="(val, key) in t.feedback.scores" :key="key" class="dim">
                <span class="dim-name">{{ t.feedback.dimensionLabels?.[key] || key }}</span>
                <el-progress :percentage="Number(val)" :stroke-width="6"
                             :color="scoreColor(Number(val))" :show-text="false" style="flex: 1" />
                <span class="dim-val">{{ val }}</span>
              </div>
            </div>
            <div v-if="t.feedback.goodPoints?.length" class="fb-line good">
              ✓ {{ t.feedback.goodPoints.join('；') }}
            </div>
            <div v-if="t.feedback.problems?.length" class="fb-line bad">
              ⚠ {{ t.feedback.problems.join('；') }}
            </div>
            <div v-if="t.feedback.contradiction" class="fb-line bad">
              ⚠ 与简历不一致：{{ t.feedback.contradiction }}
            </div>
            <div v-if="t.feedback.suggestion" class="fb-line tip">
              建议：{{ t.feedback.suggestion }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="composer">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="3"
        resize="none"
        :disabled="!awaitingAnswer || submitting"
        :placeholder="awaitingAnswer
          ? '用口语把思路讲出来，就像真的面试一样。长按空格说话（可切点按），Ctrl + Enter 提交'
          : '面试已结束，点右上角生成报告'"
        @keydown="onKeydown"
      />
      <div class="composer-bar">
        <VoiceInput :kb-id="kbIdForAsr" :disabled="!awaitingAnswer || submitting" @text="onVoice" />
        <span class="muted">
          {{ draft.length }} 字 · 回答越具体（做了什么、为什么、结果如何）得分越高
        </span>
        <el-button type="primary" :disabled="!awaitingAnswer" :loading="submitting" @click="submit">
          提交回答
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.room {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 136px);
  max-width: 1120px;
  background: #fff;
  border-radius: 10px;
  overflow: hidden;
}

.room-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
}

.head-left,
.head-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.title {
  display: flex;
  flex-direction: column;
  line-height: 1.35;
}

.muted {
  color: #94a3b8;
  font-size: 12.5px;
}

.chat {
  flex: 1;
  overflow-y: auto;
  padding: 18px 16px;
  background: #f8fafc;
}

.row {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

.row.right {
  flex-direction: row-reverse;
}

.avatar {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
}

.avatar.bot {
  background: #4c7cf3;
}

.avatar.me {
  background: #10b981;
}

.bubble-wrap {
  max-width: 76%;
}

.row.right .bubble-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.based-on {
  font-size: 12px;
  color: #64748b;
  background: #eef2f7;
  border-radius: 4px;
  padding: 2px 7px;
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bubble {
  padding: 11px 14px;
  border-radius: 10px;
  line-height: 1.65;
  font-size: 14px;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble-bot {
  background: #fff;
  border: 1px solid #e2e8f0;
  color: #1e293b;
}

.bubble-me {
  background: #4c7cf3;
  color: #fff;
}

.expects {
  margin-top: 6px;
  font-size: 12px;
  color: #94a3b8;
}

.feedback {
  margin-top: 8px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  width: 100%;
}

.fb-head {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 8px;
}

.fb-score {
  font-size: 22px;
  font-weight: 700;
}

.dims {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.dim {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dim-name {
  width: 88px;
  font-size: 12px;
  color: #64748b;
  flex-shrink: 0;
}

.dim-val {
  width: 30px;
  text-align: right;
  font-size: 12px;
  color: #475569;
}

.fb-line {
  font-size: 12.5px;
  margin-top: 6px;
  line-height: 1.6;
}

.fb-line.good {
  color: #059669;
}

.fb-line.bad {
  color: #dc2626;
}

.fb-line.tip {
  color: #475569;
}

.composer {
  border-top: 1px solid #e2e8f0;
  padding: 12px 16px 14px;
  background: #fff;
}

.composer-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}

.composer-bar .muted {
  flex: 1;
}
</style>
