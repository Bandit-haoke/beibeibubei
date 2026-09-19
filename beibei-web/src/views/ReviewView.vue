<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getCalendar, getTodayDue, startReview, type CalendarDay, type DueItem } from '@/api/review'

const router = useRouter()

const loading = ref(false)
const starting = ref(false)
const due = ref<DueItem[]>([])
const calendar = ref<CalendarDay[]>([])
const batchSize = ref(20)

/** 按知识库分组，方便一眼看出该复习哪个科目 */
const grouped = computed(() => {
  const map = new Map<string, DueItem[]>()
  for (const item of due.value) {
    const key = item.kbName || '未命名知识库'
    if (!map.has(key)) {
      map.set(key, [])
    }
    map.get(key)!.push(item)
  }
  return Array.from(map.entries())
})

const overdueCount = computed(() => due.value.filter((d) => d.overdueDays > 0).length)

async function load() {
  loading.value = true
  try {
    const [d, c] = await Promise.all([getTodayDue(undefined, 200), getCalendar(60, 14)])
    due.value = d
    calendar.value = c
  } finally {
    loading.value = false
  }
}

async function begin() {
  starting.value = true
  try {
    const res = await startReview(undefined, batchSize.value)
    ElMessage.success(`已组卷 ${res.count} 道，开始复习`)
    router.push(`/exam/start/${res.paperId}`)
  } catch {
    // request.ts 已提示
  } finally {
    starting.value = false
  }
}

/**
 * 日历热力图配色：需要复习的越多颜色越深（偏橙），
 * 已经复习过的用绿色，两者都有就混合。
 */
function cellColor(day: CalendarDay) {
  if (day.reviewedCount > 0 && day.dueCount === 0) return '#10b981'
  if (day.dueCount === 0) return '#f1f5f9'
  const intensity = Math.min(1, day.dueCount / 10)
  if (day.reviewedCount > 0) return `rgba(16,185,129,${0.25 + intensity * 0.5})`
  return `rgba(245,158,11,${0.2 + intensity * 0.75})`
}

function isToday(date: string) {
  return date === new Date().toISOString().slice(0, 10)
}

function fmtTime(t: string) {
  return (t || '').replace('T', ' ').slice(0, 16)
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <h2>复习计划</h2>
        <div class="sub">
          按艾宾浩斯曲线排期：答对间隔翻倍，答错回到 1 天。复习只出旧题，不生成新题
        </div>
      </div>
      <div style="display: flex; gap: 10px; align-items: center">
        <el-select v-model="batchSize" style="width: 120px" size="default">
          <el-option :value="10" label="10 道" />
          <el-option :value="20" label="20 道" />
          <el-option :value="30" label="30 道" />
          <el-option :value="50" label="50 道" />
        </el-select>
        <el-button
          type="primary"
          size="large"
          :icon="'AlarmClock'"
          :loading="starting"
          :disabled="!due.length"
          @click="begin"
        >
          {{ due.length ? `开始复习（${Math.min(batchSize, due.length)} 道）` : '暂无待复习' }}
        </el-button>
      </div>
    </div>

    <!-- 概览 -->
    <el-row :gutter="14" style="margin-bottom: 16px">
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-num" style="color:#4c7cf3">{{ due.length }}</div>
          <div class="stat-label">今日待复习</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-num" style="color:#ef4444">{{ overdueCount }}</div>
          <div class="stat-label">其中已逾期</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-num" style="color:#10b981">{{ grouped.length }}</div>
          <div class="stat-label">涉及知识库</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-num" style="color:#8b5cf6">
            {{ calendar.filter((d) => d.dueCount > 0).length }}
          </div>
          <div class="stat-label">未来有排期的天数</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 复习日历 -->
    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header>
        <div style="display: flex; align-items: center; gap: 14px">
          <b>复习日历</b>
          <span class="legend"><i style="background:#f1f5f9"></i>无排期</span>
          <span class="legend"><i style="background:rgba(245,158,11,.7)"></i>待复习</span>
          <span class="legend"><i style="background:#10b981"></i>已复习</span>
          <span style="font-size: 12px; color: #94a3b8">左边是过去 60 天，右边是未来 14 天</span>
        </div>
      </template>

      <div class="heatmap">
        <el-tooltip
          v-for="d in calendar"
          :key="d.date"
          :content="`${d.date}：待复习 ${d.dueCount} 道，已复习 ${d.reviewedCount} 道`"
          placement="top"
        >
          <div
            class="heat-cell"
            :class="{ today: isToday(d.date) }"
            :style="{ background: cellColor(d) }"
          />
        </el-tooltip>
      </div>
    </el-card>

    <!-- 今日待复习列表 -->
    <el-card v-if="due.length" shadow="never">
      <template #header><b>今日待复习（{{ due.length }} 道）</b></template>

      <div v-for="[kbName, items] in grouped" :key="kbName" class="kb-group">
        <div class="kb-title">{{ kbName }}（{{ items.length }} 道）</div>
        <div v-for="item in items.slice(0, 8)" :key="item.mistakeId" class="due-row">
          <el-tag size="small" type="primary" effect="plain">{{ item.qTypeName }}</el-tag>
          <el-tag
            v-if="item.overdueDays > 0"
            size="small"
            type="danger"
            effect="plain"
          >
            逾期 {{ item.overdueDays }} 天
          </el-tag>
          <el-tag v-else size="small" type="success" effect="plain">今日到期</el-tag>
          <span class="due-stem">{{ item.stem }}</span>
          <span class="due-meta">错过 {{ item.wrongCount }} 次 · 间隔 {{ item.intervalDays }} 天</span>
        </div>
        <div v-if="items.length > 8" class="more">…还有 {{ items.length - 8 }} 道</div>
      </div>
    </el-card>

    <el-empty
      v-else-if="!loading"
      description="今天没有需要复习的题目"
    >
      <div style="font-size: 13px; color: #94a3b8; line-height: 1.8">
        答错的题会自动进错题本并按艾宾浩斯曲线排期。<br />
        先去出题 → 答题，答错的题明天就会出现在这里。
      </div>
    </el-empty>
  </div>
</template>

<style scoped>
.stat-card {
  text-align: center;
}

.stat-num {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
}

.stat-label {
  font-size: 12.5px;
  color: #94a3b8;
  margin-top: 4px;
}

.legend {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: #64748b;
}

.legend i {
  width: 12px;
  height: 12px;
  border-radius: 3px;
  display: inline-block;
}

.heatmap {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}

.heat-cell {
  width: 15px;
  height: 15px;
  border-radius: 3px;
  cursor: default;
}

.heat-cell.today {
  outline: 2px solid #4c7cf3;
  outline-offset: 1px;
}

.kb-group {
  margin-bottom: 18px;
}

.kb-title {
  font-size: 13.5px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 8px;
}

.due-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 0;
  border-bottom: 1px solid #f8fafc;
  font-size: 13px;
}

.due-stem {
  flex: 1;
  color: #475569;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.due-meta {
  font-size: 12px;
  color: #cbd5e1;
}

.more {
  font-size: 12px;
  color: #94a3b8;
  padding-top: 6px;
}
</style>
