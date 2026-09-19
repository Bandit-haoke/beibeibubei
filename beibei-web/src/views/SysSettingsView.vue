<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  checkConsistency, deleteBackup, doBackup, doRestore, getSysHealth, getSysInfo, listBackups,
  repairConsistency, type BackupFile, type ConsistencyReport, type SysHealth,
} from '@/api/sys'

const loading = ref(false)
const backingUp = ref(false)
const restoring = ref<string | null>(null)
const backups = ref<BackupFile[]>([])
const consistency = ref<ConsistencyReport | null>(null)
const checking = ref(false)
const repairing = ref(false)
const sysInfo = ref<Record<string, any>>({})
const health = ref<SysHealth | null>(null)

async function load() {
  loading.value = true
  try {
    const [b, info, h] = await Promise.all([listBackups(), getSysInfo(), getSysHealth()])
    backups.value = b
    sysInfo.value = info as Record<string, any>
    health.value = h
  } finally {
    loading.value = false
  }
}

async function backup() {
  backingUp.value = true
  try {
    const res = await doBackup()
    ElMessage.success(
      `备份完成：${res.filename}（${res.tableCount} 张表 / ${res.rowCount} 行 / ` +
      `${res.fileCount} 个文件 / ${fmtSize(res.sizeBytes)}）`,
    )
    await load()
  } finally {
    backingUp.value = false
  }
}

async function restore(file: BackupFile) {
  await ElMessageBox.confirm(
    `从「${file.filename}」恢复会**覆盖当前全部业务数据**（知识库、题目、答卷、错题本都会被替换）。\n\n` +
    `向量库不在备份里，恢复后需要重新解析文档才能恢复检索。\n\n建议先做一次当前数据的备份。确认恢复？`,
    '确认恢复',
    { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' },
  )
  restoring.value = file.filename
  try {
    const res = await doRestore(file.filename)
    ElMessage.success(`恢复完成：${res.tableCount} 张表 / ${res.rowCount} 行 / ${res.fileCount} 个文件`)
    await load()
  } finally {
    restoring.value = null
  }
}

async function removeBackup(file: BackupFile) {
  await ElMessageBox.confirm(`删除备份文件「${file.filename}」？`, '删除', { type: 'warning' })
  await deleteBackup(file.filename)
  ElMessage.success('已删除')
  await load()
}

async function runCheck() {
  checking.value = true
  try {
    consistency.value = await checkConsistency()
    if (consistency.value.ok && consistency.value.healthy) {
      ElMessage.success('数据一致，没有问题')
    } else if (consistency.value.ok) {
      ElMessage.warning('发现不一致，详见下方')
    } else {
      ElMessage.error(consistency.value.error || '校验失败')
    }
  } finally {
    checking.value = false
  }
}

async function runRepair() {
  await ElMessageBox.confirm(
    '只清理「MySQL 里已经没有对应分块」的孤儿向量。\n\n' +
    '缺失的向量（有分块但没向量）不会被补 —— 那需要重新解析文档，请在文档管理页操作。',
    '清理孤儿向量',
    { type: 'warning' },
  )
  repairing.value = true
  try {
    const res = await repairConsistency()
    if (res.ok) {
      ElMessage.success(`已清理 ${res.deleted} 条孤儿向量`)
      consistency.value = res.after || null
    } else {
      ElMessage.error('清理失败')
    }
  } finally {
    repairing.value = false
  }
}

function fmtSize(bytes: number) {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function fmtTime(t: string) {
  return t ? t.replace('T', ' ').slice(0, 19) : '-'
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <h2>系统设置</h2>
        <div class="sub">数据备份、恢复与向量一致性校验</div>
      </div>
      <el-button :icon="'Refresh'" @click="load">刷新</el-button>
    </div>

    <!-- 系统信息 -->
    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header><b>运行环境</b></template>
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="JDK">{{ sysInfo.javaStatus?.version }}</el-descriptions-item>
        <el-descriptions-item label="进程 PID">{{ sysInfo.javaStatus?.pid }}</el-descriptions-item>
        <el-descriptions-item label="堆内存">
          {{ sysInfo.javaStatus?.heapUsedMb }} / {{ sysInfo.javaStatus?.heapMaxMb }} MB
        </el-descriptions-item>
        <el-descriptions-item label="智能体地址">
          <span class="mono">{{ sysInfo.agentBaseUrl }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="内部令牌">
          <el-tag size="small" :type="sysInfo.tokenConfigured ? 'success' : 'danger'">
            {{ sysInfo.tokenConfigured ? '已配置' : '未配置' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="备份目录">
          <span class="mono">{{ sysInfo.backupDir }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-row :gutter="16">
      <!-- 备份 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="never" style="margin-bottom: 16px">
          <template #header>
            <div style="display: flex; align-items: center; justify-content: space-between">
              <b>数据备份</b>
              <el-button type="primary" :icon="'Download'" :loading="backingUp" @click="backup">
                立即备份
              </el-button>
            </div>
          </template>

          <el-alert
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom: 12px"
            title="备份包含：全部业务数据 + 上传的原始资料"
            description="向量库不进备份 —— 它可以从分块重新算出来，备份它只会让文件膨胀好几倍。"
          />

          <el-table :data="backups" size="small" empty-text="还没有备份">
            <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip />
            <el-table-column label="大小" width="90">
              <template #default="{ row }">{{ fmtSize(row.sizeBytes) }}</template>
            </el-table-column>
            <el-table-column label="时间" width="150">
              <template #default="{ row }">{{ fmtTime(row.modifiedAt) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="130">
              <template #default="{ row }">
                <el-button
                  link
                  type="warning"
                  size="small"
                  :loading="restoring === row.filename"
                  @click="restore(row)"
                >
                  恢复
                </el-button>
                <el-button link type="danger" size="small" @click="removeBackup(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <!-- 一致性 -->
      <el-col :xs="24" :lg="12">
        <el-card shadow="never" style="margin-bottom: 16px">
          <template #header>
            <div style="display: flex; align-items: center; justify-content: space-between">
              <b>向量库一致性</b>
              <div style="display: flex; gap: 8px">
                <el-button :loading="checking" @click="runCheck">开始校验</el-button>
                <el-button
                  type="warning"
                  :disabled="!consistency?.orphanCount"
                  :loading="repairing"
                  @click="runRepair"
                >
                  清理孤儿向量
                </el-button>
              </div>
            </div>
          </template>

          <el-empty v-if="!consistency" :image-size="70"
                    description="点「开始校验」检查 MySQL 分块与 Milvus 向量是否对得上" />

          <template v-else-if="consistency.ok">
            <el-alert
              :type="consistency.healthy ? 'success' : 'warning'"
              :closable="false"
              show-icon
              style="margin-bottom: 12px"
              :title="consistency.healthy ? '数据一致' : '发现不一致'"
            />

            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="MySQL 分块">{{ consistency.mysqlChunks }}</el-descriptions-item>
              <el-descriptions-item label="Milvus 向量">{{ consistency.milvusVectors }}</el-descriptions-item>
              <el-descriptions-item label="孤儿向量">
                <span :style="{ color: consistency.orphanCount ? '#ef4444' : '#10b981' }">
                  {{ consistency.orphanCount }}
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="缺失向量">
                <span :style="{ color: consistency.missingCount ? '#ef4444' : '#10b981' }">
                  {{ consistency.missingCount }}
                </span>
              </el-descriptions-item>
              <el-descriptions-item label="分区错位">{{ consistency.misplacedCount || 0 }}</el-descriptions-item>
              <el-descriptions-item label="集合">
                <span class="mono">{{ consistency.collection }}</span>
              </el-descriptions-item>
            </el-descriptions>

            <el-alert
              v-if="consistency.orphanCount"
              type="warning"
              :closable="false"
              show-icon
              style="margin-top: 12px"
              title="孤儿向量"
              :description="`Milvus 里有 ${consistency.orphanCount} 条向量在 MySQL 里已经没有对应分块（删文档时没清干净）。它们会占空间并可能污染检索结果，建议清理。`"
            />

            <el-alert
              v-if="consistency.missingCount"
              type="error"
              :closable="false"
              show-icon
              style="margin-top: 12px"
              title="缺失向量"
              :description="`${consistency.missingCount} 个分块在 Milvus 里没有向量，这些内容检索不到。请到文档管理页对相关文档点「重新解析」。`"
            />

            <el-alert
              v-if="consistency.partitionErrors?.length"
              type="error"
              :closable="false"
              show-icon
              style="margin-top: 12px"
              title="分区读取异常"
              :description="consistency.partitionErrors.join('；')"
            />
          </template>

          <el-alert v-else type="error" :closable="false" show-icon
                    :title="consistency.error" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.mono {
  font-family: Consolas, monospace;
  font-size: 12.5px;
}
</style>
