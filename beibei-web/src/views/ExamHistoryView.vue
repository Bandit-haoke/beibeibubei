<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { listExams, type ExamListItem } from '@/api/exam'
import { listKb, type KnowledgeBase } from '@/api/kb'

const router = useRouter()
const loading = ref(false)
const list = ref<ExamListItem[]>([])
const kbs = ref<KnowledgeBase[]>([])
const kbId = ref<number | undefined>()

const STATUS_TYPE: Record<number, 'info' | 'warning' | 'success' | 'danger'> = {
  0: 'warning', 1: 'info', 2: 'warning', 3: 'success', 4: 'danger',
}

async function load() {
  loading.value = true
  try {
    list.value = await listExams(kbId.value)
  } finally {
    loading.value = false
  }
}

function fmtTime(t: string | null) {
  return t ? t.replace('T', ' ').slice(0, 16) : '-'
}

function fmtDuration(sec: number) {
  const m = Math.floor((sec || 0) / 60)
  return m > 0 ? `${m} 分 ${(sec || 0) % 60} 秒` : `${sec || 0} 秒`
}

onMounted(async () => {
  kbs.value = await listKb()
  await load()
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h2>答题记录</h2>
        <div class="sub">每次作答的得分、用时与错题情况</div>
      </div>
      <div style="display: flex; gap: 10px">
        <el-select v-model="kbId" placeholder="全部知识库" clearable style="width: 200px" @change="load">
          <el-option v-for="k in kbs" :key="k.id" :value="k.id" :label="k.name" />
        </el-select>
        <el-button :icon="'Refresh'" @click="load">刷新</el-button>
      </div>
    </div>

    <el-card shadow="never">
      <el-table :data="list" v-loading="loading" stripe empty-text="还没有答题记录">
        <el-table-column prop="title" label="题卷" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="STATUS_TYPE[row.status] || 'info'">{{ row.statusName }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="模式" width="80">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">
              {{ row.examMode === 3 ? '复习' : row.examMode === 1 ? '练习' : '考试' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="得分" width="150">
          <template #default="{ row }">
            <template v-if="row.status === 3">
              <span :style="{ color: row.scoreRate >= 60 ? '#10b981' : '#ef4444', fontWeight: 600 }">
                {{ row.gotScore }}
              </span>
              <span style="color:#94a3b8"> / {{ row.totalScore }}（{{ row.scoreRate }}%）</span>
            </template>
            <span v-else style="color:#cbd5e1">—</span>
          </template>
        </el-table-column>
        <el-table-column label="对/错" width="90">
          <template #default="{ row }">
            <span v-if="row.status === 3">
              <span style="color:#10b981">{{ row.correctCount }}</span> /
              <span style="color:#ef4444">{{ row.wrongCount }}</span>
            </span>
            <span v-else style="color:#cbd5e1">—</span>
          </template>
        </el-table-column>
        <el-table-column label="用时" width="100">
          <template #default="{ row }">{{ fmtDuration(row.durationSec) }}</template>
        </el-table-column>
        <el-table-column label="开始时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.startedAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 3 || row.status === 4"
              link
              type="primary"
              size="small"
              @click="router.push(`/exam/${row.id}/result`)"
            >
              查看结果
            </el-button>
            <el-button
              v-else
              link
              type="warning"
              size="small"
              @click="router.push(`/exam/start/${row.paperId}`)"
            >
              继续作答
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
