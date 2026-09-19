<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { appeal, getExamResult, type ExamResult, type ItemResult } from '@/api/exam'
import { subscribeTask, type TaskEvent } from '@/api/task'

const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)

const loading = ref(true)
const result = ref<ExamResult | null>(null)
const filter = ref<'all' | 'wrong'>('all')
const regrading = ref(0)
const regradeStage = ref('')

const items = computed<ItemResult[]>(() => {
  const all = result.value?.items || []
  return filter.value === 'wrong' ? all.filter((i) => i.score < i.fullScore) : all
})

function scoreColor(item: ItemResult) {
  const ratio = item.fullScore ? item.score / item.fullScore : 0
  return ratio >= 0.999 ? '#10b981' : ratio > 0 ? '#e6a23c' : '#ef4444'
}

function fmtDuration(sec: number) {
  const m = Math.floor((sec || 0) / 60)
  return `${m} 分 ${(sec || 0) % 60} 秒`
}

async function load() {
  loading.value = true
  try {
    result.value = await getExamResult(examId)
  } finally {
    loading.value = false
  }
}

async function doAppeal(item: ItemResult) {
  let reason = ''
  try {
    const res = await ElMessageBox.prompt(
      '说说你觉得哪里判得不对。AI 会带着你的理由重新批改一次，两次结果都会保留。',
      '申诉重判',
      {
        confirmButtonText: '提交申诉',
        cancelButtonText: '取消',
        inputType: 'textarea',
        inputPlaceholder: '例如：我答案里其实提到了这个要点，只是表述和参考答案不同',
        inputValidator: (v: string) => (v && v.trim().length >= 5) || '请至少写 5 个字',
      },
    )
    reason = res.value
  } catch {
    return
  }

  regrading.value = item.answerItemId
  regradeStage.value = '正在提交申诉 ...'
  try {
    const taskId = await appeal(item.answerItemId, reason)
    subscribeTask(taskId, {
      onProgress: (e: TaskEvent) => { regradeStage.value = e.stage || '' },
      onDone: async (e: TaskEvent) => {
        const r = (e.result || {}) as Record<string, number>
        regradeStage.value = ''
        regrading.value = 0
        ElMessage.success(`重判完成：${r.score ?? 0} / ${r.fullScore ?? 0} 分`)
        await load()
      },
      onError: (e: TaskEvent) => {
        regrading.value = 0
        regradeStage.value = ''
        ElMessage.error(e.errorMsg || '重判失败')
      },
    })
  } catch {
    regrading.value = 0
    regradeStage.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <div style="display: flex; align-items: center; gap: 8px">
          <el-button link :icon="'ArrowLeft'" @click="router.push(`/kb/${result?.kbId}/generate`)">
            出题页
          </el-button>
          <h2 style="margin: 0">{{ result?.title || '判分结果' }}</h2>
        </div>
        <div class="sub">
          用时 {{ fmtDuration(result?.durationSec || 0) }}
          <template v-if="result?.gradedAt"> · 判分于 {{ (result.gradedAt || '').replace('T', ' ').slice(0, 16) }}</template>
        </div>
      </div>
      <el-radio-group v-model="filter" size="small">
        <el-radio-button value="all">全部 {{ result?.items.length || 0 }}</el-radio-button>
        <el-radio-button value="wrong">只看错题 {{ result?.wrongCount || 0 }}</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 总分卡片 -->
    <el-card shadow="never" class="score-card">
      <div class="score-main">
        <div class="score-num">
          <span class="big" :style="{ color: (result?.scoreRate || 0) >= 60 ? '#10b981' : '#ef4444' }">
            {{ result?.gotScore }}
          </span>
          <span class="small">/ {{ result?.totalScore }}</span>
        </div>
        <div class="score-meta">
          <el-progress
            :percentage="result?.scoreRate || 0"
            :stroke-width="12"
            :color="(result?.scoreRate || 0) >= 60 ? '#10b981' : '#ef4444'"
            style="width: 260px"
          />
          <div class="score-stats">
            <span><b style="color:#10b981">{{ result?.correctCount }}</b> 全对</span>
            <span><b style="color:#ef4444">{{ result?.wrongCount }}</b> 有失分</span>
            <span><b>{{ result?.items.length }}</b> 总题数</span>
          </div>
        </div>
      </div>
    </el-card>

    <el-alert
      v-if="regrading"
      type="warning"
      :closable="false"
      show-icon
      :title="`正在重新批阅：${regradeStage}`"
      style="margin-bottom: 14px"
    />

    <el-empty v-if="!items.length" description="没有符合条件的题目" />

    <el-card v-for="(item, i) in items" :key="item.answerItemId" shadow="never" class="item-card">
      <div class="item-head">
        <span class="item-no">{{ i + 1 }}</span>
        <el-tag size="small" type="primary" effect="plain">{{ item.qTypeName }}</el-tag>
        <el-tag size="small" effect="plain">{{ item.gradeMethodName }}</el-tag>
        <el-tag
          v-if="item.inputMode === 2"
          size="small"
          type="success"
          effect="plain"
        >
          语音作答
        </el-tag>
        <el-tag
          v-for="t in item.tags.slice(0, 3)"
          :key="t.id"
          size="small"
          :type="t.level === 1 ? 'warning' : 'info'"
          effect="plain"
        >
          {{ t.name }}
        </el-tag>
        <div style="flex: 1"></div>
        <span class="item-score" :style="{ color: scoreColor(item) }">
          {{ item.score }} / {{ item.fullScore }}
        </span>
      </div>

      <div class="item-stem">{{ item.stem }}</div>
      <pre v-if="item.codeSnippet" class="item-code">{{ item.codeSnippet }}</pre>

      <div class="answer-block">
        <div class="answer-label">你的作答</div>
        <div class="answer-body" :class="{ empty: !item.userAnswer }">
          {{ item.userAnswer || '（未作答）' }}
        </div>
        <div v-if="item.inputMode === 2 && item.asrText" class="asr-note">
          语音原始转写：{{ item.asrText }}
        </div>
      </div>

      <div v-if="item.referenceAnswer" class="answer-block ref">
        <div class="answer-label">参考答案</div>
        <div class="answer-body">{{ item.referenceAnswer }}</div>
      </div>

      <!-- 命中 / 遗漏 / 答错 -->
      <div v-if="item.hitPoints.length" class="points hit">
        <div class="points-title">✓ 答对的要点（{{ item.hitPoints.length }}）</div>
        <div v-for="(p, pi) in item.hitPoints" :key="pi" class="point-row">
          <el-tag size="small" type="success" effect="plain">{{ p.score ?? '-' }} 分</el-tag>
          <span>{{ p.point }}</span>
        </div>
      </div>

      <div v-if="item.missPoints.length" class="points miss">
        <div class="points-title">✗ 漏掉的要点（{{ item.missPoints.length }}）</div>
        <div v-for="(p, pi) in item.missPoints" :key="pi" class="point-row">
          <span class="point-text">{{ p.point }}</span>
          <div v-if="p.hint" class="point-hint">{{ p.hint }}</div>
        </div>
      </div>

      <div v-if="item.wrongPoints.length" class="points wrong">
        <div class="points-title">! 说错的地方（{{ item.wrongPoints.length }}）</div>
        <div v-for="(p, pi) in item.wrongPoints" :key="pi" class="point-row">
          <span class="point-text">{{ p.point }}</span>
          <div v-if="p.correction" class="point-hint">{{ p.correction }}</div>
        </div>
      </div>

      <!-- 原文引用 -->
      <div v-if="item.citations.length" class="points cite">
        <div class="points-title">📖 原文依据</div>
        <el-collapse>
          <el-collapse-item
            v-for="(c, ci) in item.citations"
            :key="ci"
            :title="`第 ${c.pageNo || '-'} 页 · ${c.sectionPath || '原文'} · chunk #${c.chunkId}`"
          >
            <div v-if="c.quote" class="cite-quote">「{{ c.quote }}」</div>
            <div class="cite-snippet">{{ c.snippet }}</div>
          </el-collapse-item>
        </el-collapse>
      </div>

      <div v-if="item.aiFeedback" class="feedback">
        <b>AI 评语：</b>{{ item.aiFeedback }}
      </div>

      <div v-if="item.appealStatus === 2" class="feedback appeal-done">
        <b>已重判：</b>原得分 {{ item.score }} 分 →
        重判 {{ item.appealScore }} 分（申诉理由：{{ item.appealReason || '未填写' }}）
      </div>

      <div class="item-actions">
        <!-- 客观题由程序判定，答案对不对是确定的，申诉不会改变结果，所以不给按钮 -->
        <el-button
          v-if="item.qType > 3"
          size="small"
          :icon="'Refresh'"
          :loading="regrading === item.answerItemId"
          :disabled="!!regrading"
          @click="doAppeal(item)"
        >
          申诉重判
        </el-button>
        <span v-else class="source-note" style="margin-left: 0">
          客观题由程序比对判定，无需申诉
        </span>
        <span class="source-note">题目 #{{ item.questionId }}</span>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.score-card {
  margin-bottom: 16px;
}

.score-main {
  display: flex;
  align-items: center;
  gap: 32px;
  flex-wrap: wrap;
}

.score-num .big {
  font-size: 44px;
  font-weight: 700;
  line-height: 1;
}

.score-num .small {
  font-size: 16px;
  color: #94a3b8;
  margin-left: 6px;
}

.score-meta {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.score-stats {
  display: flex;
  gap: 22px;
  font-size: 13px;
  color: #64748b;
}

.score-stats b {
  font-size: 16px;
  margin-right: 2px;
}

.item-card {
  margin-bottom: 14px;
}

.item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.item-no {
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

.item-score {
  font-size: 16px;
  font-weight: 700;
  font-family: Consolas, monospace;
}

.item-stem {
  font-size: 14.5px;
  line-height: 1.75;
  color: #1e293b;
  margin-bottom: 12px;
  white-space: pre-wrap;
}

.item-code {
  background: #f8fafc;
  border-radius: 6px;
  padding: 10px 12px;
  font-family: Consolas, monospace;
  font-size: 12.5px;
  color: #334155;
  overflow-x: auto;
  margin-bottom: 12px;
}

.answer-block {
  margin-bottom: 10px;
}

.answer-label {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 4px;
}

.answer-body {
  font-size: 13.5px;
  line-height: 1.7;
  color: #334155;
  background: #f8fafc;
  border-radius: 6px;
  padding: 9px 12px;
  white-space: pre-wrap;
}

.answer-body.empty {
  color: #cbd5e1;
  font-style: italic;
}

.answer-block.ref .answer-body {
  background: #f0fdf4;
  color: #166534;
}

.asr-note {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
}

.points {
  margin-top: 10px;
  border-radius: 6px;
  padding: 10px 12px;
}

.points.hit {
  background: #f0fdf4;
}

.points.miss {
  background: #fffbeb;
}

.points.wrong {
  background: #fef2f2;
}

.points.cite {
  background: #f8fafc;
}

.points-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
  color: #475569;
}

.point-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: 13px;
  line-height: 1.65;
  color: #334155;
  margin-bottom: 4px;
}

.point-text {
  flex: 1;
}

.point-hint {
  font-size: 12.5px;
  color: #92400e;
  margin-top: 2px;
}

.cite-quote {
  font-size: 13px;
  color: #1e293b;
  margin-bottom: 6px;
}

.cite-snippet {
  font-size: 12.5px;
  color: #64748b;
  line-height: 1.7;
  white-space: pre-wrap;
}

.feedback {
  margin-top: 10px;
  font-size: 13.5px;
  line-height: 1.75;
  color: #334155;
  background: #eff6ff;
  border-radius: 6px;
  padding: 10px 12px;
}

.feedback.appeal-done {
  background: #f5f3ff;
  color: #5b21b6;
}

.item-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
}

.source-note {
  margin-left: auto;
  font-size: 12px;
  color: #cbd5e1;
}
</style>
