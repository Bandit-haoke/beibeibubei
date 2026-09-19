<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getKb, type KnowledgeBase } from '@/api/kb'
import { createTag, deleteTag, getTagTree, refreshTagCounts, updateTag, type TagNode } from '@/api/tag'

const route = useRoute()
const router = useRouter()
const kbId = Number(route.params.id)

const kb = ref<KnowledgeBase | null>(null)
const tree = ref<TagNode[]>([])
const loading = ref(false)

const dialogVisible = ref(false)
const editing = ref<TagNode | null>(null)
const form = ref({ name: '', description: '', parentId: 0 })

async function load() {
  loading.value = true
  try {
    const [kbData, treeData] = await Promise.all([getKb(kbId), getTagTree(kbId)])
    kb.value = kbData
    tree.value = treeData
  } finally {
    loading.value = false
  }
}

function openCreate(parent?: TagNode) {
  editing.value = null
  form.value = { name: '', description: '', parentId: parent?.id ?? 0 }
  dialogVisible.value = true
}

function openEdit(node: TagNode) {
  editing.value = node
  form.value = { name: node.name, description: node.description, parentId: node.parentId }
  dialogVisible.value = true
}

async function submit() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写知识点名称')
    return
  }
  if (editing.value) {
    await updateTag(editing.value.id, {
      kbId,
      name: form.value.name.trim(),
      description: form.value.description,
    })
    ElMessage.success('已修改')
  } else {
    await createTag({
      kbId,
      parentId: form.value.parentId || undefined,
      name: form.value.name.trim(),
      description: form.value.description,
    })
    ElMessage.success('已新增')
  }
  dialogVisible.value = false
  await load()
}

async function remove(node: TagNode) {
  const childCount = countDescendants(node)
  await ElMessageBox.confirm(
    childCount
      ? `「${node.name}」下面还有 ${childCount} 个子知识点，会一起删除。确认？`
      : `删除知识点「${node.name}」？`,
    '确认删除',
    { type: 'warning' },
  )
  await deleteTag(node.id)
  ElMessage.success('已删除')
  await load()
}

function countDescendants(node: TagNode): number {
  return (node.children || []).reduce((sum, c) => sum + 1 + countDescendants(c), 0)
}

async function doRefreshCounts() {
  await refreshTagCounts(kbId)
  ElMessage.success('已重算分块数')
  await load()
}

/** 用已入库的分块让 AI 重抽知识点树 */
async function aiExtract() {
  await ElMessageBox.confirm(
    'AI 会基于已入库的分块内容重新抽取知识点树。若该知识库已有知识点，会先全部清除（包括分块关联）。确认继续？',
    'AI 重新抽取知识点',
    { type: 'warning' },
  )

  ElMessage.info('正在调用大模型抽取，请稍候 ...')

  await new Promise<void>((resolve) => {
    const source = new EventSource(`/api/tag/ai-extract/stream?kbId=${kbId}&force=true`)
    source.addEventListener('progress', (ev) => {
      const data = JSON.parse((ev as MessageEvent).data)
      ElMessage.info({ message: data.stage || '处理中', duration: 1500 })
    })
    source.addEventListener('done', (ev) => {
      const data = JSON.parse((ev as MessageEvent).data)
      source.close()
      if (data.skipped) {
        ElMessage.warning(data.reason || '抽取被跳过')
      } else {
        ElMessage.success(`抽取完成，新增 ${data.created} 个知识点`)
      }
      load()
      resolve()
    })
    source.addEventListener('error', () => {
      source.close()
      ElMessage.error('抽取失败，请检查智能体与大模型配置')
      resolve()
    })
  })
}

function nodeType(level: number) {
  return level === 1 ? 'primary' : level === 2 ? 'success' : 'warning'
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <div style="display: flex; align-items: center; gap: 8px">
          <el-button link :icon="'ArrowLeft'" @click="router.push(`/kb/${kbId}/doc`)">
            {{ kb?.name || '知识库' }}
          </el-button>
          <h2 style="margin: 0">知识点</h2>
        </div>
        <div class="sub">
          AI 抽出的层级知识体系。题目会挂在知识点上，用来统计薄弱项
        </div>
      </div>
      <div style="display: flex; gap: 10px">
        <el-button :icon="'Refresh'" @click="doRefreshCounts">重算分块数</el-button>
        <el-button :icon="'MagicStick'" @click="aiExtract">AI 重新抽取</el-button>
        <el-button type="primary" :icon="'Plus'" @click="openCreate()">新增知识点</el-button>
      </div>
    </div>

    <el-alert
      v-if="!tree.length && !loading"
      type="info"
      :closable="false"
      show-icon
      title="还没有知识点"
      description="上传并解析文档时会自动抽取；也可以点「AI 重新抽取」基于已入库的分块生成，或手动新增。"
      style="margin-bottom: 16px"
    />

    <el-card v-else shadow="never">
      <el-tree
        :data="tree"
        node-key="id"
        default-expand-all
        :expand-on-click-node="false"
        :props="{ label: 'name', children: 'children' }"
      >
        <template #default="{ data }">
          <div class="tag-row">
            <el-tag :type="nodeType(data.level)" size="small" effect="plain">
              L{{ data.level }}
            </el-tag>
            <span class="tag-name">{{ data.name }}</span>
            <span v-if="data.origin === 1" class="tag-origin">AI</span>
            <span v-else class="tag-origin manual">手动</span>
            <span class="tag-desc">{{ data.description }}</span>
            <span class="tag-count">{{ data.chunkCount }} 分块</span>

            <span class="tag-actions">
              <el-button
                v-if="data.level < 3"
                link
                size="small"
                :icon="'Plus'"
                @click.stop="openCreate(data)"
              />
              <el-button link size="small" :icon="'Edit'" @click.stop="openEdit(data)" />
              <el-button link size="small" type="danger" :icon="'Delete'" @click.stop="remove(data)" />
            </span>
          </div>
        </template>
      </el-tree>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '修改知识点' : '新增知识点'"
      width="440px"
    >
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="form.name" maxlength="100" placeholder="如：Spring Cloud" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="2"
            maxlength="500"
            placeholder="这个知识点包含什么内容"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.tag-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding-right: 10px;
}

.tag-name {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
}

.tag-origin {
  font-size: 11px;
  color: #8b5cf6;
  background: #f5f3ff;
  padding: 1px 5px;
  border-radius: 3px;
}

.tag-origin.manual {
  color: #0891b2;
  background: #ecfeff;
}

.tag-desc {
  font-size: 12.5px;
  color: #94a3b8;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-count {
  font-size: 12px;
  color: #64748b;
}

.tag-actions {
  opacity: 0;
  transition: opacity 0.15s;
}

.tag-row:hover .tag-actions {
  opacity: 1;
}
</style>
