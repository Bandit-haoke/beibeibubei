<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listKb, type KnowledgeBase } from '@/api/kb'
import {
  listMistakes,
  markMastered,
  removeMistake,
  STAGE_TYPE,
  type MistakeItem,
} from '@/api/review'

const router = useRouter()

const loading = ref(false)
const list = ref<MistakeItem[]>([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(15)

const kbs = ref<KnowledgeBase[]>([])
const filters = ref<{ kbId?: number; mastered?: number }>({ mastered: 0 })

async function load() {
  loading.value = true
  try {
    const res = await listMistakes({
      kbId: filters.value.kbId,
      mastered: filters.value.mastered,
      pageNum: pageNum.value,
      pageSize: pageSize.value,
    })
    list.value = res.list
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function toggleMastered(item: MistakeItem) {
  const to = item.mastered === 1 ? false : true
  await markMastered(item.id, to)
  ElMessage.success(to ? '已标记为掌握' : '已重新列入复习')
  await load()
}

async function remove(item: MistakeItem) {
  await ElMessageBox.confirm('从错题本移除这道题？不影响题库里的题目。', '移除', { type: 'warning' })
  await removeMistake(item.id)
  ElMessage.success('已移除')
  await load()
}

function fmtTime(t: string | null) {
  return t ? t.replace('T', ' ').slice(0, 16) : '-'
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
        <h2>错题本</h2>
        <div class="sub">
          判分没拿满分的题会自动进来，按艾宾浩斯曲线排复习时间
        </div>
      </div>
      <div style="display: flex; gap: 10px">
        <el-button :icon="'AlarmClock'" @click="router.push('/review')">今日待复习</el-button>
        <el-button :icon="'Refresh'" @click="load">刷新</el-button>
      </div>
    </div>

    <el-card shadow="never" style="margin-bottom: 14px">
      <div style="display: flex; gap: 14px; flex-wrap: wrap; align-items: center">
        <el-select v-model="filters.kbId" placeholder="全部知识库" clearable style="width: 200px" @change="load">
          <el-option v-for="k in kbs" :key="k.id" :value="k.id" :label="k.name" />
        </el-select>
        <el-radio-group v-model="filters.mastered" @change="load">
          <el-radio-button :value="0">未掌握</el-radio-button>
          <el-radio-button :value="1">已掌握</el-radio-button>
          <el-radio-button :value="undefined">全部</el-radio-button>
        </el-radio-group>
        <div style="flex: 1"></div>
        <span style="font-size: 13px; color: #94a3b8">共 {{ total }} 条</span>
      </div>
    </el-card>

    <el-empty v-if="!loading && !list.length" description="错题本是空的 —— 要么还没答过题，要么全答对了" />

    <el-card v-for="item in list" :key="item.id" shadow="never" class="m-card">
      <div class="m-head">
        <el-tag size="small" type="primary" effect="plain">{{ item.qTypeName }}</el-tag>
        <el-tag size="small" :type="STAGE_TYPE[item.stage] || 'info'">{{ item.stage }}</el-tag>
        <el-tag size="small" type="info" effect="plain">{{ item.kbName }}</el-tag>
        <el-tag
          v-for="t in item.tags.slice(0, 3)"
          :key="t.id"
          size="small"
          :type="t.level === 1 ? 'warning' : 'success'"
          effect="plain"
        >
          {{ t.name }}
        </el-tag>
        <div style="flex: 1"></div>
        <span class="m-wrong">错过 {{ item.wrongCount }} 次</span>
      </div>

      <div class="m-stem">{{ item.stem }}</div>

      <div class="m-meta">
        <span>下次复习：<b>{{ fmtTime(item.nextReviewAt) }}</b></span>
        <span>间隔：<b>{{ item.intervalDays }}</b> 天</span>
        <span>难度系数：<b>{{ item.easeFactor }}</b></span>
        <span>连续答对：<b>{{ item.rightStreak }}</b> 次</span>
        <span>最近答错：{{ fmtTime(item.lastWrongAt) }}</span>
      </div>

      <div class="m-actions">
        <el-button
          size="small"
          :type="item.mastered === 1 ? 'warning' : 'success'"
          :icon="item.mastered === 1 ? 'RefreshLeft' : 'Select'"
          @click="toggleMastered(item)"
        >
          {{ item.mastered === 1 ? '重新列入复习' : '标记已掌握' }}
        </el-button>
        <el-button size="small" type="danger" :icon="'Delete'" @click="remove(item)">
          移出错题本
        </el-button>
        <span class="m-src">题目 #{{ item.questionId }}</span>
      </div>
    </el-card>

    <el-pagination
      v-if="total > pageSize"
      style="margin-top: 14px; justify-content: flex-end"
      layout="total, prev, pager, next"
      :total="total"
      :current-page="pageNum"
      :page-size="pageSize"
      @current-change="(p: number) => { pageNum = p; load() }"
    />
  </div>
</template>

<style scoped>
.m-card {
  margin-bottom: 12px;
}

.m-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.m-wrong {
  font-size: 12.5px;
  color: #ef4444;
  font-weight: 600;
}

.m-stem {
  font-size: 14px;
  line-height: 1.7;
  color: #1e293b;
  margin-bottom: 10px;
}

.m-meta {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: #64748b;
  background: #f8fafc;
  border-radius: 6px;
  padding: 9px 12px;
}

.m-meta b {
  color: #4c7cf3;
}

.m-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}

.m-src {
  margin-left: auto;
  font-size: 12px;
  color: #cbd5e1;
}
</style>
