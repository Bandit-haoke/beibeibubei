<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getKb, type KnowledgeBase } from '@/api/kb'
import { search, type SearchHit } from '@/api/search'
import { getTagTree, type TagNode } from '@/api/tag'

const route = useRoute()
const router = useRouter()
const kbId = Number(route.params.id)

const kb = ref<KnowledgeBase | null>(null)
const query = ref('')
const topK = ref(8)
const loading = ref(false)
const hits = ref<SearchHit[]>([])
const engine = ref('')
const errorMsg = ref('')
const hint = ref('')

const tagTree = ref<TagNode[]>([])
const selectedTags = ref<number[]>([])
const elapsedMs = ref(0)

async function load() {
  kb.value = await getKb(kbId)
  tagTree.value = await getTagTree(kbId)
}

async function doSearch() {
  if (!query.value.trim()) {
    ElMessage.warning('请输入查询内容')
    return
  }
  loading.value = true
  errorMsg.value = ''
  hint.value = ''
  const started = performance.now()
  try {
    const res = await search({
      kbId,
      query: query.value.trim(),
      topK: topK.value,
      tagIds: selectedTags.value.length ? selectedTags.value : undefined,
    })
    elapsedMs.value = Math.round(performance.now() - started)
    if (!res.ok) {
      errorMsg.value = res.error || '检索失败'
      hint.value = res.hint || ''
      hits.value = []
      return
    }
    engine.value = res.source
    hits.value = res.hits
  } catch (e) {
    errorMsg.value = String(e)
  } finally {
    loading.value = false
  }
}

/** 把命中的知识点 ID 映射成名字 */
function tagNames(ids: number[]): string[] {
  const map = new Map<number, string>()
  const walk = (nodes: TagNode[]) => {
    for (const n of nodes) {
      map.set(n.id, n.name)
      walk(n.children || [])
    }
  }
  walk(tagTree.value)
  return ids.map((id) => map.get(id) || `#${id}`)
}

function sourceLabel(s: string) {
  if (s === 'hybrid') return '混合检索'
  if (s === 'dense') return '纯向量'
  return s
}

function scoreColor(score: number) {
  if (score >= 0.6) return '#10b981'
  if (score >= 0.4) return '#f59e0b'
  return '#94a3b8'
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
          <h2 style="margin: 0">检索调试</h2>
        </div>
        <div class="sub">
          输入一个问题，看看能召回哪些原文分块 —— 这是验证 RAG 效果最直接的方式
        </div>
      </div>
    </div>

    <el-card shadow="never">
      <div style="display: flex; gap: 10px; align-items: flex-start; flex-wrap: wrap">
        <el-input
          v-model="query"
          placeholder="例如：Redis 缓存穿透和击穿有什么区别？"
          style="flex: 1; min-width: 300px"
          size="large"
          clearable
          @keyup.enter="doSearch"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="topK" style="width: 130px" size="large">
          <el-option :value="5" label="Top 5" />
          <el-option :value="8" label="Top 8" />
          <el-option :value="15" label="Top 15" />
          <el-option :value="30" label="Top 30" />
        </el-select>
        <el-button type="primary" size="large" :loading="loading" @click="doSearch">检索</el-button>
      </div>

      <div v-if="tagTree.length" style="margin-top: 12px">
        <span style="font-size: 12.5px; color: #94a3b8; margin-right: 8px">限定知识点：</span>
        <el-select
          v-model="selectedTags"
          multiple
          collapse-tags
          collapse-tags-tooltip
          clearable
          placeholder="不选则全库检索"
          style="min-width: 320px"
        >
          <el-option
            v-for="n in tagTree.flatMap((x) => [x, ...(x.children || [])])"
            :key="n.id"
            :value="n.id"
            :label="`${'　'.repeat(n.level - 1)}${n.name}`"
          />
        </el-select>
      </div>
    </el-card>

    <el-alert
      v-if="errorMsg"
      type="error"
      :closable="false"
      show-icon
      style="margin-top: 16px"
      :title="errorMsg"
      :description="hint"
    />

    <el-card v-if="hits.length || engine" shadow="never" style="margin-top: 16px">
      <template #header>
        <div style="display: flex; align-items: center; gap: 12px">
          <b>召回 {{ hits.length }} 个分块</b>
          <el-tag v-if="engine" size="small" effect="plain">{{ sourceLabel(engine) }}</el-tag>
          <span style="font-size: 12.5px; color: #94a3b8">耗时 {{ elapsedMs }} ms</span>
        </div>
      </template>

      <div v-for="(h, i) in hits" :key="h.pk" class="hit">
        <div class="hit-rank">{{ i + 1 }}</div>
        <div class="hit-body">
          <div class="hit-head">
            <span class="hit-score" :style="{ color: scoreColor(h.score) }">
              {{ h.score.toFixed(4) }}
            </span>
            <el-tag v-if="h.fileName" size="small" effect="plain">{{ h.fileName }}</el-tag>
            <el-tag v-if="h.pageNo" size="small" type="info" effect="plain">
              第 {{ h.pageNo }} 页
            </el-tag>
            <el-tag v-for="n in tagNames(h.tagIds)" :key="n" size="small" type="success">
              {{ n }}
            </el-tag>
          </div>
          <div v-if="h.sectionPath" class="hit-section">{{ h.sectionPath }}</div>
          <div class="hit-text">{{ h.text }}</div>
        </div>
      </div>

      <el-empty v-if="!hits.length && !loading" description="没有召回任何分块，检查资料是否已解析入库" />
    </el-card>
  </div>
</template>

<style scoped>
.hit {
  display: flex;
  gap: 12px;
  padding: 14px 0;
  border-bottom: 1px solid #f1f5f9;
}

.hit:last-child {
  border-bottom: none;
}

.hit-rank {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: #eef2ff;
  color: #4c7cf3;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.hit-body {
  flex: 1;
  min-width: 0;
}

.hit-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.hit-score {
  font-weight: 700;
  font-size: 13px;
  font-family: Consolas, monospace;
}

.hit-section {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 6px;
}

.hit-text {
  font-size: 13px;
  color: #334155;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  background: #f8fafc;
  border-radius: 6px;
  padding: 10px 12px;
}
</style>
