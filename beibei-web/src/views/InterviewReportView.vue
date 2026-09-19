<script setup lang="ts">
/**
 * 面试评估报告。
 *
 * 页面结构按「先结论、后证据、再行动」排：
 *   总分与总评 → 维度雷达 + 逐轮曲线 → 薄弱项（带证据与建议）→ 一键出题
 *
 * 最后一块是这个功能的闭环：报告不是终点，
 * 薄弱知识点要能直接变成一张专项题卷，回学习模块去刷。
 */
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import {
  DIFFICULTY,
  createLinkagePaper,
  getInterview,
  type InterviewDetailVO,
  type InterviewReport,
} from '@/api/interview'
import { listKb, type KnowledgeBase } from '@/api/kb'

const route = useRoute()
const router = useRouter()
const interviewId = Number(route.params.id)

const detail = ref<InterviewDetailVO | null>(null)
const loading = ref(false)
const kbs = ref<KnowledgeBase[]>([])

const radarRef = ref<HTMLDivElement>()
const trendRef = ref<HTMLDivElement>()
let radarChart: echarts.ECharts | null = null
let trendChart: echarts.ECharts | null = null

const report = () => (detail.value?.report ?? {}) as InterviewReport

const scoreColor = (score?: number | null) => {
  if (score == null) return '#94a3b8'
  if (score >= 85) return '#10b981'
  if (score >= 70) return '#f59e0b'
  return '#ef4444'
}

function renderRadar() {
  const dims = report().dimensions ?? []
  if (!radarRef.value) return
  radarChart ??= echarts.init(radarRef.value)
  if (!dims.length) {
    radarChart.clear()
    return
  }
  radarChart.setOption({
    tooltip: {},
    radar: {
      indicator: dims.map((d) => ({ name: d.name, max: 100 })),
      radius: '64%',
      splitNumber: 4,
      axisName: { color: '#64748b', fontSize: 11 },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
      splitArea: { areaStyle: { color: ['#fff', '#f8fafc'] } },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: dims.map((d) => d.score),
            name: '本场得分',
            areaStyle: { color: 'rgba(76,124,243,.25)' },
            lineStyle: { color: '#4c7cf3', width: 2 },
            itemStyle: { color: '#4c7cf3' },
          },
        ],
      },
    ],
  })
}

function renderTrend() {
  const scores = report().turnScores ?? []
  if (!trendRef.value) return
  trendChart ??= echarts.init(trendRef.value)
  if (!scores.length) {
    trendChart.clear()
    return
  }
  trendChart.setOption({
    grid: { left: 40, right: 20, top: 30, bottom: 30 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: scores.map((s) => `第${s.seq}轮`),
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#64748b', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      splitLine: { lineStyle: { color: '#f1f5f9' } },
      axisLabel: { color: '#94a3b8', fontSize: 11 },
    },
    series: [
      {
        type: 'line',
        smooth: true,
        data: scores.map((s) => s.score),
        symbolSize: 7,
        lineStyle: { color: '#4c7cf3', width: 2.5 },
        itemStyle: { color: '#4c7cf3' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(76,124,243,.28)' },
            { offset: 1, color: 'rgba(76,124,243,0)' },
          ]),
        },
      },
    ],
  })
}

function resize() {
  radarChart?.resize()
  trendChart?.resize()
}

async function load() {
  loading.value = true
  try {
    const [d, k] = await Promise.all([getInterview(interviewId), listKb()])
    detail.value = d
    kbs.value = k
    if (d.interview.status !== 2) {
      await router.replace(`/interview/${interviewId}/room`)
      return
    }
    await nextTick()
    renderRadar()
    renderTrend()
  } finally {
    loading.value = false
  }
}

// ---------------- 联动出题 ----------------

const linkageVisible = ref(false)
const linkageForm = ref<{ kbId: number | null; count: number; selfCheck: boolean }>({
  kbId: null,
  count: 10,
  selfCheck: true,
})
const linking = ref(false)

function openLinkage() {
  linkageForm.value.kbId = detail.value?.interview.kbId ?? kbs.value[0]?.id ?? null
  linkageForm.value.count = Math.max(5, Math.min(30, (report().knowledgePoints?.length ?? 3) * 3))
  linkageVisible.value = true
}

async function doLinkage() {
  if (!linkageForm.value.kbId) {
    ElMessage.warning('请选择要出题的知识库')
    return
  }
  linking.value = true
  try {
    const res = await createLinkagePaper(interviewId, { ...linkageForm.value })
    linkageVisible.value = false
    ElMessage.success(res.message)
    await router.push(`/paper/${res.paperId}/review`)
  } finally {
    linking.value = false
  }
}

onMounted(() => {
  void load()
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  radarChart?.dispose()
  trendChart?.dispose()
})
</script>

<template>
  <div v-loading="loading" class="report">
    <div class="topbar">
      <el-button link @click="router.push('/interview')">
        <el-icon><ArrowLeft /></el-icon>
        返回面试记录
      </el-button>
    </div>

    <template v-if="detail">
      <!-- 结论 -->
      <div class="hero">
        <div class="hero-score">
          <div class="big" :style="{ color: scoreColor(report().overallScore) }">
            {{ report().overallScore ?? '-' }}
          </div>
          <div class="muted">综合得分</div>
        </div>
        <div class="hero-body">
          <div class="hero-title">
            {{ detail.interview.jobTitle }}
            <el-tag size="small" effect="plain">
              {{ DIFFICULTY[detail.interview.difficulty as 1 | 2 | 3] }}
            </el-tag>
            <span class="muted">{{ detail.interview.turnCount }} 轮 · 简历「{{ detail.interview.resumeName }}」</span>
          </div>
          <div class="summary">{{ report().summary || '暂无总评' }}</div>
        </div>
        <el-button type="primary" size="large" @click="openLinkage">
          <el-icon style="margin-right: 4px"><MagicStick /></el-icon>
          针对薄弱点出题
        </el-button>
      </div>

      <!-- 图表 -->
      <div class="charts">
        <el-card shadow="never" class="chart-card">
          <template #header><b>能力维度</b></template>
          <div ref="radarRef" class="chart"></div>
        </el-card>
        <el-card shadow="never" class="chart-card">
          <template #header><b>逐轮得分走向</b></template>
          <div ref="trendRef" class="chart"></div>
        </el-card>
      </div>

      <!-- 维度点评 -->
      <el-card shadow="never" class="section">
        <template #header><b>维度点评</b></template>
        <div v-for="d in report().dimensions" :key="d.name" class="dim-row">
          <span class="dim-name">{{ d.name }}</span>
          <el-progress :percentage="d.score" :stroke-width="10"
                       :color="scoreColor(d.score)" style="flex: 1" />
          <span class="dim-comment">{{ d.comment }}</span>
        </div>
      </el-card>

      <!-- 优势 -->
      <el-card v-if="report().strengths?.length" shadow="never" class="section">
        <template #header><b>表现不错的地方</b></template>
        <div class="tags">
          <el-tag v-for="s in report().strengths" :key="s" type="success" effect="light" class="chip">
            {{ s }}
          </el-tag>
        </div>
      </el-card>

      <!-- 薄弱项 -->
      <el-card shadow="never" class="section">
        <template #header>
          <b>薄弱项（带证据）</b>
          <span class="muted header-hint">
            每一条都对应面试里的具体表现，不是泛泛而谈
          </span>
        </template>
        <el-empty v-if="!report().weakPoints?.length" description="没有识别出明显薄弱项" />
        <div v-for="(w, i) in report().weakPoints" :key="i" class="weak">
          <div class="weak-head">
            <el-tag type="danger" effect="light">{{ w.skill }}</el-tag>
            <el-tag v-if="w.level" size="small" effect="plain">{{ w.level }}</el-tag>
          </div>
          <div class="weak-line"><b>证据：</b>{{ w.evidence }}</div>
          <div class="weak-line"><b>怎么补：</b>{{ w.suggestion }}</div>
        </div>
      </el-card>

      <!-- 优先补的知识点 -->
      <el-card shadow="never" class="section highlight">
        <template #header>
          <b>优先补的知识点</b>
          <span class="muted header-hint">点「针对薄弱点出题」会按这些知识点生成专项题卷</span>
        </template>
        <div class="tags">
          <el-tag v-for="kp in report().knowledgePoints" :key="kp" type="warning" effect="dark" class="chip big-chip">
            {{ kp }}
          </el-tag>
          <span v-if="!report().knowledgePoints?.length" class="muted">暂无</span>
        </div>
        <ol v-if="report().nextSteps?.length" class="steps">
          <li v-for="(s, i) in report().nextSteps" :key="i">{{ s }}</li>
        </ol>
      </el-card>

      <!-- 完整对话回顾 -->
      <el-card shadow="never" class="section">
        <template #header><b>完整对话回顾</b></template>
        <el-collapse>
          <el-collapse-item v-for="t in detail.turns.filter((x) => x.role === 1)" :key="t.id"
                            :name="String(t.id)">
            <template #title>
              <span class="turn-title">
                <el-tag size="small" effect="plain">{{ t.questionType || '提问' }}</el-tag>
                <span class="turn-q">{{ t.content.slice(0, 60) }}{{ t.content.length > 60 ? '…' : '' }}</span>
              </span>
            </template>
            <div class="turn-q-full">{{ t.content }}</div>
            <div v-if="t.basedOn" class="muted">依据简历：{{ t.basedOn }}</div>
            <div v-if="t.expects?.length" class="muted">期望要点：{{ t.expects.join('、') }}</div>
            <div v-for="a in detail.turns.filter((x) => x.role === 2 && x.seq === t.seq + 1)" :key="a.id"
                 class="answer">
              <div class="answer-head">
                你的回答
                <span class="score" :style="{ color: scoreColor(a.score) }">{{ a.score }}</span>
              </div>
              <div class="answer-body">{{ a.content }}</div>
              <div v-if="a.feedback?.problems?.length" class="fb-line bad">
                ⚠ {{ a.feedback.problems.join('；') }}
              </div>
              <div v-if="a.feedback?.suggestion" class="fb-line tip">
                建议：{{ a.feedback.suggestion }}
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>
      </el-card>
    </template>

    <!-- 联动出题 -->
    <el-dialog v-model="linkageVisible" title="按薄弱知识点出题" width="560px">
      <el-alert type="info" :closable="false" class="dialog-alert">
        <template #title>会拿报告里的知识点去知识库匹配标签，匹配上的范围定向出题</template>
        <div class="kp-list">
          {{ (report().knowledgePoints ?? []).join('、') || '（报告里没有知识点）' }}
        </div>
      </el-alert>
      <el-form label-width="100px">
        <el-form-item label="知识库">
          <el-select v-model="linkageForm.kbId" placeholder="选择出题的知识库" style="width: 100%">
            <el-option v-for="kb in kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="题目数量">
          <el-slider v-model="linkageForm.count" :min="1" :max="30" show-input />
        </el-form-item>
        <el-form-item label="AI 自检">
          <el-switch v-model="linkageForm.selfCheck" />
          <span class="muted" style="margin-left: 10px">开启后会多一道校验，慢一些但质量更稳</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="linkageVisible = false">取消</el-button>
        <el-button type="primary" :loading="linking" @click="doLinkage">生成专项题卷</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.report {
  max-width: 1180px;
}

.topbar {
  margin-bottom: 10px;
}

.muted {
  color: #94a3b8;
  font-size: 12.5px;
}

.header-hint {
  margin-left: 10px;
}

.hero {
  display: flex;
  align-items: center;
  gap: 22px;
  background: #fff;
  border-radius: 10px;
  padding: 20px 24px;
  margin-bottom: 16px;
}

.hero-score {
  text-align: center;
  min-width: 96px;
}

.big {
  font-size: 46px;
  font-weight: 800;
  line-height: 1;
}

.hero-body {
  flex: 1;
}

.hero-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 8px;
}

.summary {
  color: #475569;
  font-size: 13.5px;
  line-height: 1.7;
}

.charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}

.chart-card :deep(.el-card__header),
.section :deep(.el-card__header) {
  padding: 12px 16px;
  font-size: 14px;
}

.chart {
  height: 260px;
}

.section {
  margin-bottom: 16px;
}

.highlight {
  border: 1px solid #fcd34d;
}

.dim-row {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 12px;
}

.dim-name {
  width: 110px;
  font-size: 13px;
  color: #334155;
  flex-shrink: 0;
}

.dim-comment {
  width: 260px;
  font-size: 12.5px;
  color: #64748b;
  text-align: right;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  margin: 0;
}

.big-chip {
  font-size: 13.5px;
  padding: 6px 12px;
}

.weak {
  border-left: 3px solid #fca5a5;
  padding: 8px 0 8px 12px;
  margin-bottom: 14px;
}

.weak-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.weak-line {
  font-size: 13px;
  color: #475569;
  line-height: 1.75;
}

.steps {
  margin: 14px 0 0;
  padding-left: 20px;
  font-size: 13px;
  color: #475569;
  line-height: 1.9;
}

.turn-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.turn-q {
  font-size: 13px;
  color: #334155;
}

.turn-q-full {
  font-size: 13.5px;
  color: #1e293b;
  line-height: 1.7;
  margin-bottom: 6px;
}

.answer {
  background: #f8fafc;
  border-radius: 8px;
  padding: 10px 12px;
  margin-top: 10px;
}

.answer-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: #64748b;
  margin-bottom: 6px;
}

.score {
  font-size: 17px;
  font-weight: 700;
}

.answer-body {
  font-size: 13px;
  color: #334155;
  line-height: 1.75;
  white-space: pre-wrap;
}

.fb-line {
  font-size: 12.5px;
  margin-top: 6px;
  line-height: 1.6;
}

.fb-line.bad {
  color: #dc2626;
}

.fb-line.tip {
  color: #475569;
}

.dialog-alert {
  margin-bottom: 14px;
}

.kp-list {
  font-size: 12.5px;
  color: #475569;
  margin-top: 4px;
}
</style>
