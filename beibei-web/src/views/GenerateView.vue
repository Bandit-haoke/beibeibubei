<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getKb, refreshKbCounters, type KnowledgeBase } from '@/api/kb'
import { getTagTree, type TagNode } from '@/api/tag'
import { generatePaper, listPapers, PAPER_STATUS, type PaperVO } from '@/api/paper'
import { subscribeTask, type TaskEvent } from '@/api/task'

const route = useRoute()
const router = useRouter()
const kbId = Number(route.params.id)

const kb = ref<KnowledgeBase | null>(null)
const tagTree = ref<TagNode[]>([])
const papers = ref<PaperVO[]>([])

// ---- 出题表单 ----
const form = ref({
  title: '',
  count: 20,
  tagIds: [] as number[],
  includeChildTags: true,
  selfCheck: true,
  typeRatio: { SINGLE: 40, MULTI: 10, JUDGE: 15, BLANK: 15, SHORT: 20 } as Record<string, number>,
  diffRatio: { EASY: 30, MEDIUM: 50, HARD: 20 } as Record<string, number>,
})

const TYPE_LABELS: Record<string, string> = {
  SINGLE: '单选题', MULTI: '多选题', JUDGE: '判断题',
  BLANK: '填空题', SHORT: '简答题',
}
const DIFF_LABELS: Record<string, string> = { EASY: '简单', MEDIUM: '中等', HARD: '困难' }

const generating = ref(false)
const progress = ref(0)
const stage = ref('')
let closer: (() => void) | null = null

const typeSum = computed(() => Object.values(form.value.typeRatio).reduce((a, b) => a + b, 0))
const diffSum = computed(() => Object.values(form.value.diffRatio).reduce((a, b) => a + b, 0))

/** 扁平化知识点，用于多选 */
const tagOptions = computed(() => {
  const out: Array<{ id: number; label: string; level: number }> = []
  const walk = (nodes: TagNode[]) => {
    for (const n of nodes) {
      out.push({ id: n.id, label: n.name, level: n.level })
      walk(n.children || [])
    }
  }
  walk(tagTree.value)
  return out
})

async function load() {
  const [kbData, tree, paperList] = await Promise.all([
    getKb(kbId),
    getTagTree(kbId),
    listPapers(kbId),
  ])
  kb.value = kbData
  tagTree.value = tree
  papers.value = paperList

  // 知识库的 docCount / chunkCount 是**冗余计数**，入库完成后由后端重算。
  // 但历史数据可能因为「重算漏调」而停在 0（这个 bug 真实发生过：
  // 文档明明解析成功、分块也写进去了，这里却报「还没有解析好的资料」）。
  // 所以发现计数为 0 时主动让后端重算一次再重新读——自愈，不用人工干预。
  if (!kbData?.chunkCount) {
    try {
      await refreshKbCounters(kbId)
      kb.value = await getKb(kbId)
    } catch {
      // 重算失败就按原值走，submit() 里还会再拦一次并给出提示
    }
  }
}

async function submit() {
  if (typeSum.value !== 100) {
    ElMessage.warning(`题型配比合计应为 100%，当前 ${typeSum.value}%`)
    return
  }
  if (diffSum.value !== 100) {
    ElMessage.warning(`难度配比合计应为 100%，当前 ${diffSum.value}%`)
    return
  }
  if (!kb.value?.chunkCount) {
    ElMessage.warning('这个知识库还没有解析好的资料，先去上传文档')
    return
  }

  generating.value = true
  progress.value = 0
  stage.value = '提交中'

  // 把百分数转成 0~1 的小数
  const toRatio = (src: Record<string, number>) => {
    const out: Record<string, number> = {}
    for (const [k, v] of Object.entries(src)) {
      if (v > 0) out[k] = v / 100
    }
    return out
  }

  try {
    const res = await generatePaper({
      kbId,
      title: form.value.title || undefined,
      count: form.value.count,
      tagIds: form.value.tagIds.length ? form.value.tagIds : undefined,
      includeChildTags: form.value.includeChildTags,
      selfCheck: form.value.selfCheck,
      qTypeRatio: toRatio(form.value.typeRatio),
      difficultyRatio: toRatio(form.value.diffRatio),
    })
    ElMessage.success('已开始生成，可以看下面的进度')
    await load()

    closer = subscribeTask(res.taskId, {
      onProgress: (e: TaskEvent) => {
        progress.value = e.progress ?? 0
        stage.value = e.stage || ''
      },
      onDone: async (e: TaskEvent) => {
        progress.value = 100
        const r = (e.result || {}) as Record<string, number>
        stage.value = `完成：生成 ${r.generated ?? 0} 道，查重丢弃 ${r.droppedByDedup ?? 0} 道，入库 ${r.saved ?? 0} 道`
        ElMessage.success('生成完成，去审核')
        generating.value = false
        await load()
        router.push(`/paper/${res.paperId}/review`)
      },
      onError: (e: TaskEvent) => {
        stage.value = `失败：${e.errorMsg}`
        ElMessage.error(e.errorMsg || '生成失败')
        generating.value = false
        load()
      },
    })
  } catch {
    generating.value = false
  }
}

function fmtTime(t: string) {
  return (t || '').replace('T', ' ').slice(0, 16)
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <div style="display: flex; align-items: center; gap: 8px">
          <el-button link :icon="'ArrowLeft'" @click="router.push(`/kb/${kbId}/doc`)">
            {{ kb?.name || '知识库' }}
          </el-button>
          <h2 style="margin: 0">AI 出题</h2>
        </div>
        <div class="sub">从 {{ kb?.chunkCount || 0 }} 个分块里按知识点命题，生成后进入审核</div>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="14">
        <el-card shadow="never">
          <template #header><b>出题配置</b></template>

          <el-form label-width="96px" label-position="left">
            <el-form-item label="题卷标题">
              <el-input v-model="form.title" placeholder="留空自动生成" maxlength="200" />
            </el-form-item>

            <el-form-item label="题目数量">
              <el-radio-group v-model="form.count">
                <el-radio-button :value="10">10 道</el-radio-button>
                <el-radio-button :value="20">20 道</el-radio-button>
                <el-radio-button :value="30">30 道</el-radio-button>
              </el-radio-group>
              <el-input-number v-model="form.count" :min="1" :max="60" style="margin-left: 12px" />
            </el-form-item>

            <el-form-item label="知识点范围">
              <el-select
                v-model="form.tagIds"
                multiple
                clearable
                collapse-tags
                collapse-tags-tooltip
                placeholder="不选 = 全库范围"
                style="width: 100%"
              >
                <el-option
                  v-for="t in tagOptions"
                  :key="t.id"
                  :value="t.id"
                  :label="'　'.repeat(t.level - 1) + t.label"
                />
              </el-select>
              <el-checkbox v-model="form.includeChildTags" style="margin-top: 6px">
                包含子知识点
              </el-checkbox>
            </el-form-item>

            <el-form-item label="题型配比">
              <div class="ratio-grid">
                <div v-for="(label, key) in TYPE_LABELS" :key="key" class="ratio-item">
                  <span class="ratio-label">{{ label }}</span>
                  <el-input-number
                    v-model="form.typeRatio[key]"
                    :min="0"
                    :max="100"
                    :step="5"
                    size="small"
                    controls-position="right"
                    style="width: 100px"
                  />
                  <span class="ratio-unit">%</span>
                </div>
                <div class="ratio-sum" :class="{ bad: typeSum !== 100 }">合计 {{ typeSum }}%</div>
              </div>
            </el-form-item>

            <el-form-item label="难度配比">
              <div class="ratio-grid">
                <div v-for="(label, key) in DIFF_LABELS" :key="key" class="ratio-item">
                  <span class="ratio-label">{{ label }}</span>
                  <el-input-number
                    v-model="form.diffRatio[key]"
                    :min="0"
                    :max="100"
                    :step="5"
                    size="small"
                    controls-position="right"
                    style="width: 100px"
                  />
                  <span class="ratio-unit">%</span>
                </div>
                <div class="ratio-sum" :class="{ bad: diffSum !== 100 }">合计 {{ diffSum }}%</div>
              </div>
            </el-form-item>

            <el-form-item label="质量闸门">
              <el-checkbox v-model="form.selfCheck">
                启用自检（把题目和依据的原文一起交给模型复核，不通过就丢弃）
              </el-checkbox>
              <div class="hint-text">
                还会自动做查重：与题库已有题目向量相似度超过 0.92 的直接丢弃
              </div>
            </el-form-item>
          </el-form>

          <div style="text-align: right">
            <el-button type="primary" size="large" :loading="generating" @click="submit">
              {{ generating ? '正在生成 ...' : '开始出题' }}
            </el-button>
          </div>

          <div v-if="generating || stage" style="margin-top: 16px">
            <el-progress :percentage="progress" :stroke-width="12" />
            <div class="stage-text">{{ stage }}</div>
          </div>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="10">
        <el-card shadow="never">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <b>历史题卷</b>
              <el-button link size="small" :icon="'Refresh'" @click="load">刷新</el-button>
            </div>
          </template>

          <el-empty v-if="!papers.length" description="还没有题卷" :image-size="70" />

          <div v-for="p in papers" :key="p.id" class="paper-row">
            <div class="paper-main">
              <div class="paper-title">{{ p.title }}</div>
              <div class="paper-meta">
                {{ fmtTime(p.createdAt) }} ·
                {{ p.totalCount }} 道 / {{ p.totalScore }} 分
                <template v-if="p.draftCount">
                  · <span style="color:#e6a23c">待审 {{ p.draftCount }}</span>
                </template>
                <template v-if="p.publishedCount">
                  · <span style="color:#10b981">已发布 {{ p.publishedCount }}</span>
                </template>
              </div>
              <div v-if="p.genSummary?.error" class="paper-err">
                {{ p.genSummary.error }}
              </div>
            </div>
            <el-tag :type="PAPER_STATUS[p.status]?.type || 'info'" size="small">
              {{ PAPER_STATUS[p.status]?.text || p.status }}
            </el-tag>
            <el-button
              v-if="p.totalCount"
              link
              type="primary"
              size="small"
              @click="router.push(`/paper/${p.id}/review`)"
            >
              审核
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.ratio-grid {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 16px;
}

.ratio-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ratio-label {
  font-size: 13px;
  color: #475569;
  min-width: 52px;
}

.ratio-unit {
  font-size: 12px;
  color: #94a3b8;
}

.ratio-sum {
  font-size: 12.5px;
  color: #10b981;
  font-weight: 600;
}

.ratio-sum.bad {
  color: #ef4444;
}

.hint-text {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
}

.stage-text {
  font-size: 13px;
  color: #64748b;
  margin-top: 8px;
}

.paper-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid #f1f5f9;
}

.paper-row:last-child {
  border-bottom: none;
}

.paper-main {
  flex: 1;
  min-width: 0;
}

.paper-title {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.paper-meta {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 3px;
}

.paper-err {
  font-size: 12px;
  color: #ef4444;
  margin-top: 3px;
}
</style>
