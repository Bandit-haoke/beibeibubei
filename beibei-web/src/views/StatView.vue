<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { listKb, type KnowledgeBase } from '@/api/kb'
import { getCost, getKbMastery, getOverview, getRadar, getTrend,
  type CostSummary, type KbMastery, type Overview, type RadarItem, type TrendPoint } from '@/api/stat'

const router = useRouter()

const overview = ref<Overview | null>(null)
const kbs = ref<KnowledgeBase[]>([])
const selectedKb = ref<number | null>(null)
const radar = ref<RadarItem[]>([])
const trend = ref<TrendPoint[]>([])
const cost = ref<CostSummary | null>(null)
const mastery = ref<KbMastery[]>([])
const trendDays = ref(30)
const loading = ref(false)

const radarRef = ref<HTMLDivElement>()
const trendRef = ref<HTMLDivElement>()
let radarChart: echarts.ECharts | null = null
let trendChart: echarts.ECharts | null = null

async function load() {
  loading.value = true
  try {
    const [o, t, c, m] = await Promise.all([
      getOverview(), getTrend(trendDays.value), getCost(trendDays.value), getKbMastery(),
    ])
    overview.value = o
    trend.value = t
    cost.value = c
    mastery.value = m

    if (selectedKb.value == null && kbs.value.length) {
      selectedKb.value = kbs.value[0].id
    }
    if (selectedKb.value != null) {
      radar.value = await getRadar(selectedKb.value)
    }
    await nextTick()
    renderRadar()
    renderTrend()
  } finally {
    loading.value = false
  }
}

function renderRadar() {
  if (!radarRef.value) return
  radarChart ??= echarts.init(radarRef.value)

  // 只取掌握度最低的 8 个知识点 —— 雷达图的目的是暴露短板，不是炫耀
  const weakest = [...radar.value].sort((a, b) => a.scoreRate - b.scoreRate).slice(0, 8)
  if (!weakest.length) {
    radarChart.clear()
    radarChart.setOption({
      title: {
        text: '还没有答题数据',
        subtext: '答几道题就能看到各知识点的掌握情况',
        left: 'center',
        top: 'middle',
        textStyle: { color: '#cbd5e1', fontSize: 14, fontWeight: 'normal' },
        subtextStyle: { color: '#e2e8f0', fontSize: 12 },
      },
    })
    return
  }

  radarChart.setOption({
    tooltip: {},
    radar: {
      indicator: weakest.map((r) => ({ name: r.name.slice(0, 8), max: 100 })),
      radius: '62%',
      splitNumber: 4,
      axisName: { color: '#64748b', fontSize: 11 },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
      splitArea: { areaStyle: { color: ['#fff', '#f8fafc'] } },
    },
    series: [{
      type: 'radar',
      data: [{
        value: weakest.map((r) => r.scoreRate),
        name: '掌握度 %',
        areaStyle: { color: 'rgba(76,124,243,.25)' },
        lineStyle: { color: '#4c7cf3', width: 2 },
        itemStyle: { color: '#4c7cf3' },
      }],
    }],
  }, true)
}

function renderTrend() {
  if (!trendRef.value) return
  trendChart ??= echarts.init(trendRef.value)

  const withData = trend.value.filter((t) => t.answered > 0)
  trendChart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        const point = trend.value[p.dataIndex]
        return `${point.date}<br/>得分率 ${point.avgScoreRate}%<br/>答题 ${point.answered} 道 / 答卷 ${point.examCount} 份`
      },
    },
    grid: { left: 42, right: 20, top: 26, bottom: 30 },
    xAxis: {
      type: 'category',
      data: trend.value.map((t) => t.date.slice(5)),
      axisLabel: { fontSize: 11, color: '#94a3b8' },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
    },
    yAxis: {
      type: 'value',
      max: 100,
      axisLabel: { fontSize: 11, color: '#94a3b8', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
    },
    series: [{
      type: 'line',
      smooth: true,
      connectNulls: true,
      // 没答题的天补 null，折线才不会连到 0 造成"暴跌"的错觉
      data: trend.value.map((t) => (t.answered > 0 ? t.avgScoreRate : null)),
      lineStyle: { color: '#4c7cf3', width: 2 },
      itemStyle: { color: '#4c7cf3' },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(76,124,243,.28)' },
          { offset: 1, color: 'rgba(76,124,243,.02)' },
        ]),
      },
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { color: '#f59e0b', type: 'dashed' },
        data: [{ yAxis: 60, label: { formatter: '及格线', fontSize: 11, color: '#f59e0b' } }],
      },
      connectNulls_: withData.length,
    }],
  }, true)
}

function resize() {
  radarChart?.resize()
  trendChart?.resize()
}

watch(selectedKb, async (id) => {
  if (id == null) return
  radar.value = await getRadar(id)
  await nextTick()
  renderRadar()
})

watch(trendDays, async () => {
  trend.value = await getTrend(trendDays.value)
  cost.value = await getCost(trendDays.value)
  await nextTick()
  renderTrend()
})

onMounted(async () => {
  kbs.value = await listKb()
  await load()
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  radarChart?.dispose()
  trendChart?.dispose()
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <h2>学习统计</h2>
        <div class="sub">用数据告诉你哪里会、哪里不会</div>
      </div>
      <div style="display: flex; gap: 10px; align-items: center">
        <el-select v-model="trendDays" style="width: 120px">
          <el-option :value="7" label="近 7 天" />
          <el-option :value="30" label="近 30 天" />
          <el-option :value="90" label="近 90 天" />
        </el-select>
        <el-button :icon="'Refresh'" @click="load">刷新</el-button>
      </div>
    </div>

    <!-- 概览 -->
    <el-row :gutter="14" style="margin-bottom: 16px">
      <el-col v-for="card in [
        { label: '知识库', value: overview?.kbCount, color: '#4c7cf3', to: '/kb' },
        { label: '资料分块', value: overview?.chunkCount, color: '#06b6d4' },
        { label: '题库（已发布）', value: overview?.publishedCount, color: '#10b981',
          sub: `${overview?.draftCount || 0} 道待审` },
        { label: '未掌握错题', value: overview?.mistakeCount, color: '#ef4444', to: '/mistake' },
        { label: '今日待复习', value: overview?.todayDueCount, color: '#f59e0b', to: '/review' },
        { label: '连续打卡', value: overview?.streakDays, color: '#8b5cf6', sub: '天' },
        { label: '平均得分率', value: overview?.avgScoreRate, color: '#0ea5e9', sub: '%' },
        { label: '累计答题', value: overview?.totalAnswered, color: '#64748b', sub: '道' },
      ]" :key="card.label" :xs="12" :sm="6" :md="3">
        <el-card
          shadow="never"
          class="ov-card"
          :class="{ clickable: card.to }"
          @click="card.to && router.push(card.to)"
        >
          <div class="ov-num" :style="{ color: card.color }">
            {{ card.value ?? 0 }}<span v-if="card.sub" class="ov-sub">{{ card.sub }}</span>
          </div>
          <div class="ov-label">{{ card.label }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="12">
        <el-card shadow="never" style="margin-bottom: 16px">
          <template #header>
            <div style="display: flex; align-items: center; justify-content: space-between">
              <b>知识点掌握度（最薄弱的 8 个）</b>
              <el-select v-model="selectedKb" size="small" style="width: 170px" placeholder="选择知识库">
                <el-option v-for="k in kbs" :key="k.id" :value="k.id" :label="k.name" />
              </el-select>
            </div>
          </template>
          <div ref="radarRef" style="height: 320px"></div>
          <div v-if="radar.length" class="hint">
            数值 = 该知识点下题目的得分率。得分率越低越该优先复习。
          </div>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="12">
        <el-card shadow="never" style="margin-bottom: 16px">
          <template #header><b>正确率趋势（近 {{ trendDays }} 天）</b></template>
          <div ref="trendRef" style="height: 320px"></div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="12">
        <el-card shadow="never">
          <template #header><b>各知识库掌握情况</b></template>
          <el-table :data="mastery" size="small" empty-text="还没有数据">
            <el-table-column prop="name" label="知识库" min-width="140" show-overflow-tooltip />
            <el-table-column prop="questionCount" label="题量" width="70" />
            <el-table-column prop="answeredCount" label="已答" width="70" />
            <el-table-column label="得分率" width="150">
              <template #default="{ row }">
                <el-progress
                  :percentage="Math.round(row.scoreRate)"
                  :stroke-width="10"
                  :color="row.scoreRate >= 60 ? '#10b981' : '#ef4444'"
                />
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="12">
        <el-card shadow="never">
          <template #header>
            <div style="display: flex; align-items: center; gap: 16px">
              <b>AI 调用与成本</b>
              <span v-if="cost" class="cost-sum">
                共 {{ cost.totalCalls }} 次 ·
                {{ (cost.totalTokens / 1000).toFixed(1) }}K tokens ·
                约 {{ cost.totalCost.toFixed(4) }} 元 ·
                平均 {{ cost.avgLatencyMs }} ms
              </span>
            </div>
          </template>

          <el-table :data="cost?.items || []" size="small" max-height="300" empty-text="还没有调用记录">
            <el-table-column prop="date" label="日期" width="105" />
            <el-table-column prop="vendor" label="厂商" width="90" />
            <el-table-column prop="model" label="模型" min-width="120" show-overflow-tooltip />
            <el-table-column prop="calls" label="次数" width="70" />
            <el-table-column label="Tokens" width="90">
              <template #default="{ row }">
                {{ ((row.promptTokens + row.completionTokens) / 1000).toFixed(1) }}K
              </template>
            </el-table-column>
            <el-table-column prop="avgLatencyMs" label="延迟" width="80">
              <template #default="{ row }">{{ row.avgLatencyMs }}ms</template>
            </el-table-column>
            <el-table-column label="失败" width="70">
              <template #default="{ row }">
                <span :style="{ color: row.failedCalls ? '#ef4444' : '#cbd5e1' }">
                  {{ row.failedCalls }}
                </span>
              </template>
            </el-table-column>
          </el-table>

          <div class="hint">
            成本需要厂商单价才会计算。在「AI 配置」里给厂商填上 price_in / price_out（元/百万 token）即可。
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.ov-card {
  text-align: center;
  margin-bottom: 12px;
}

.ov-card.clickable {
  cursor: pointer;
  transition: transform 0.12s;
}

.ov-card.clickable:hover {
  transform: translateY(-2px);
}

.ov-num {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
}

.ov-sub {
  font-size: 12px;
  color: #94a3b8;
  margin-left: 3px;
  font-weight: 400;
}

.ov-label {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 4px;
  white-space: nowrap;
}

.hint {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.6;
  margin-top: 10px;
}

.cost-sum {
  font-size: 12.5px;
  color: #64748b;
}
</style>
