<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getSysHealth, type SysHealth } from '@/api/sys'
import { getOverview, type Overview } from '@/api/stat'

const router = useRouter()
const loading = ref(false)
const probeLlm = ref(false)
const health = ref<SysHealth | null>(null)
const overview = ref<Overview | null>(null)

async function load() {
  loading.value = true
  try {
    health.value = await getSysHealth(probeLlm.value)
    // 概览挂了不该影响环境自检的展示
    try {
      overview.value = await getOverview()
    } catch {
      overview.value = null
    }
    if (health.value?.agent?.coreOk) {
      ElMessage.success('核心链路正常')
    }
  } catch {
    // request.ts 已经弹过提示
  } finally {
    loading.value = false
  }
}

function levelTag(level: string) {
  return level === 'core' ? { type: 'warning' as const, text: '核心' } : { type: 'info' as const, text: '可降级' }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <h2>首页看板</h2>
        <div class="sub">
          <template v-if="overview">
            连续打卡 <b>{{ overview.streakDays }}</b> 天 ·
            今日已复习 <b>{{ overview.todayReviewedCount }}</b> 道 ·
            环境自检 {{ health?.agent?.coreOk ? '正常' : '异常' }}
          </template>
          <template v-else>正在加载 ...</template>
        </div>
      </div>
      <div style="display: flex; align-items: center; gap: 12px">
        <el-checkbox v-model="probeLlm">真实调用一次大模型</el-checkbox>
        <el-button type="primary" :icon="'Refresh'" @click="load">刷新</el-button>
      </div>
    </div>

    <!-- 学习概览：最该先看的东西放最上面 -->
    <el-row v-if="overview" :gutter="14" style="margin-bottom: 16px">
      <el-col v-for="card in [
        { label: '今日待复习', value: overview.todayDueCount, unit: '道', color: '#f59e0b', to: '/review' },
        { label: '未掌握错题', value: overview.mistakeCount, unit: '道', color: '#ef4444', to: '/mistake' },
        { label: '题库已发布', value: overview.publishedCount, unit: '道', color: '#10b981',
          sub: overview.draftCount ? `${overview.draftCount} 道待审` : '', to: '/kb' },
        { label: '平均得分率', value: overview.avgScoreRate, unit: '%', color: '#4c7cf3', to: '/stat' },
      ]" :key="card.label" :xs="12" :sm="6">
        <el-card shadow="never" class="ov-card" @click="router.push(card.to)">
          <div class="ov-num" :style="{ color: card.color }">
            {{ card.value }}<span class="ov-unit">{{ card.unit }}</span>
          </div>
          <div class="ov-label">{{ card.label }}</div>
          <div v-if="card.sub" class="ov-sub">{{ card.sub }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 总体状态 -->
    <el-alert
      v-if="health"
      :type="health.agent?.coreOk ? 'success' : 'error'"
      :closable="false"
      show-icon
      style="margin-bottom: 16px"
    >
      <template #title>
        <span v-if="health.agent?.coreOk">核心链路正常 —— 数据库与向量库均已就绪</span>
        <span v-else-if="health.agent?.unreachable">智能体未启动 —— 请在 PyCharm 中运行 beibei-agent</span>
        <span v-else>核心链路存在问题 —— 请查看下方红色项</span>
      </template>
      <div class="mono">检测时间：{{ health.checkedAt }}</div>
    </el-alert>

    <!-- Java 运行时 -->
    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header><b>Java 后端（beibei-server :8080）</b></template>
      <el-descriptions v-if="health?.java" :column="3" border size="small">
        <el-descriptions-item label="JDK">{{ health.java.version }}</el-descriptions-item>
        <el-descriptions-item label="PID">{{ health.java.pid }}</el-descriptions-item>
        <el-descriptions-item label="已运行">{{ health.java.uptimeSeconds }} 秒</el-descriptions-item>
        <el-descriptions-item label="堆内存">
          {{ health.java.heapUsedMb }} / {{ health.java.heapMaxMb }} MB
        </el-descriptions-item>
        <el-descriptions-item label="CPU 核心">{{ health.java.processors }}</el-descriptions-item>
        <el-descriptions-item label="操作系统">{{ health.java.os }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 智能体与中间件 -->
    <el-card shadow="never">
      <template #header>
        <b>智能体与中间件（beibei-agent :8000）</b>
      </template>

      <el-alert
        v-if="health?.agent?.unreachable"
        type="error"
        :closable="false"
        show-icon
        :title="health.agent.error"
        :description="health.agent.hint"
      />

      <template v-else-if="health?.agent?.checks?.length">
        <div v-for="c in health.agent.checks" :key="c.key" class="check-row">
          <el-icon :size="18" :color="c.ok ? '#10b981' : '#ef4444'" style="margin-top: 2px">
            <component :is="c.ok ? 'CircleCheckFilled' : 'CircleCloseFilled'" />
          </el-icon>

          <div class="check-body">
            <div class="check-title">
              {{ c.name }}
              <el-tag :type="levelTag(c.level).type" size="small" effect="plain" style="margin-left: 8px">
                {{ levelTag(c.level).text }}
              </el-tag>
            </div>
            <div class="check-detail" :class="{ 'is-error': !c.ok }">
              {{ c.ok ? c.detail : c.error }}
            </div>
            <div v-if="!c.ok && c.hint" class="check-hint">{{ c.hint }}</div>
          </div>
        </div>
      </template>

      <el-empty v-else description="暂无检测结果" />
    </el-card>
  </div>
</template>

<style scoped>
.ov-card {
  text-align: center;
  cursor: pointer;
  transition: transform 0.12s;
  margin-bottom: 12px;
}

.ov-card:hover {
  transform: translateY(-2px);
}

.ov-num {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
}

.ov-unit {
  font-size: 13px;
  color: #94a3b8;
  margin-left: 3px;
  font-weight: 400;
}

.ov-label {
  font-size: 12.5px;
  color: #94a3b8;
  margin-top: 4px;
}

.ov-sub {
  font-size: 12px;
  color: #f59e0b;
  margin-top: 2px;
}
</style>
