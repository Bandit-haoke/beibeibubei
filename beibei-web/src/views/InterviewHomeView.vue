<script setup lang="ts">
/**
 * 模拟面试首页：简历库 + 面试记录。
 *
 * 为什么把两者放一个页面：简历是面试的**前置条件**，
 * 分两个菜单的结果一定是「用户先点面试记录，发现空的，再回来找简历库」。
 */
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type UploadFile } from 'element-plus'
import {
  DIFFICULTY,
  INTERVIEW_STATUS,
  RESUME_STATUS,
  deleteInterview,
  deleteResume,
  getResume,
  listInterviews,
  listResumes,
  pasteResume,
  reparseResume,
  startInterview,
  uploadResume,
  type InterviewVO,
  type ResumeDetailVO,
  type ResumeVO,
} from '@/api/interview'
import { listKb, type KnowledgeBase } from '@/api/kb'
import { subscribeTask } from '@/api/task'

const router = useRouter()
const activeTab = ref('resume')

const resumes = ref<ResumeVO[]>([])
const interviews = ref<InterviewVO[]>([])
const kbs = ref<KnowledgeBase[]>([])
const loading = ref(false)

/** 正在解析的简历 → 进度百分比（key 是 resumeId） */
const parsing = reactive<Record<number, number>>({})
let unsubscribe: (() => void) | null = null

// ---------------- 上传 / 粘贴 ----------------

const pasteVisible = ref(false)
const pasteForm = reactive({ fileName: '', content: '', targetPosition: '' })

async function handleUpload(file: UploadFile) {
  const raw = file.raw
  if (!raw) return
  loading.value = true
  try {
    const res = await uploadResume(raw)
    ElMessage.success(`${res.fileName}：${res.message}`)
    await loadResumes()
    watchParse(res.resumeId, res.taskId)
  } finally {
    loading.value = false
  }
  return false
}

function watchParse(resumeId: number, taskId: number) {
  parsing[resumeId] = 0
  unsubscribe?.()
  unsubscribe = subscribeTask(taskId, {
    onProgress: (e) => {
      parsing[resumeId] = e.progress ?? 0
    },
    onDone: (e) => {
      delete parsing[resumeId]
      if (e.status === 2) {
        ElMessage.success('简历已解析完成，可以开始面试了')
      } else {
        ElMessage.error(e.errorMsg || '简历解析失败')
      }
      void loadResumes()
    },
    onError: (e) => {
      delete parsing[resumeId]
      ElMessage.error(e.errorMsg || '简历解析失败')
      void loadResumes()
    },
  })
}

async function submitPaste() {
  if (!pasteForm.content.trim()) {
    ElMessage.warning('请先粘贴简历内容')
    return
  }
  loading.value = true
  try {
    const res = await pasteResume({ ...pasteForm })
    pasteVisible.value = false
    pasteForm.fileName = ''
    pasteForm.content = ''
    ElMessage.success(res.message)
    await loadResumes()
    watchParse(res.resumeId, res.taskId)
  } finally {
    loading.value = false
  }
}

// ---------------- 简历档案 ----------------

const profileVisible = ref(false)
const detail = ref<ResumeDetailVO | null>(null)

async function openProfile(row: ResumeVO) {
  detail.value = await getResume(row.id)
  profileVisible.value = true
}

async function doReparse(row: ResumeVO) {
  const taskId = await reparseResume(row.id)
  ElMessage.info('已重新加入解析队列')
  await loadResumes()
  watchParse(row.id, taskId)
}

async function doDeleteResume(row: ResumeVO) {
  await ElMessageBox.confirm(
    `删除简历「${row.fileName}」会连带删除它的所有面试记录，确定吗？`,
    '确认删除',
    { type: 'warning' },
  )
  await deleteResume(row.id)
  ElMessage.success('已删除')
  await Promise.all([loadResumes(), loadInterviews()])
}

// ---------------- 新建面试 ----------------

const startVisible = ref(false)
const startForm = reactive({
  resumeId: 0,
  resumeName: '',
  jobTitle: '',
  kbId: null as number | null,
  difficulty: 2,
  maxTurns: 10,
})
const starting = ref(false)

function openStart(row: ResumeVO) {
  if (row.status !== 2) {
    ElMessage.warning('这份简历还没解析成功，请先等解析完成')
    return
  }
  startForm.resumeId = row.id
  startForm.resumeName = row.fileName
  startForm.jobTitle = row.targetPosition || 'Java 后端开发工程师'
  startForm.kbId = kbs.value[0]?.id ?? null
  startForm.difficulty = 2
  startForm.maxTurns = 10
  startVisible.value = true
}

async function doStart() {
  starting.value = true
  try {
    const res = await startInterview({
      resumeId: startForm.resumeId,
      jobTitle: startForm.jobTitle,
      kbId: startForm.kbId,
      difficulty: startForm.difficulty,
      maxTurns: startForm.maxTurns,
    })
    startVisible.value = false
    ElMessage.success('面试开始')
    await router.push(`/interview/${res.interviewId}/room`)
  } finally {
    starting.value = false
  }
}

// ---------------- 面试记录 ----------------

function openInterview(row: InterviewVO) {
  if (row.status === 2) {
    void router.push(`/interview/${row.id}/report`)
  } else {
    void router.push(`/interview/${row.id}/room`)
  }
}

async function doDeleteInterview(row: InterviewVO) {
  await ElMessageBox.confirm(`删除这场「${row.jobTitle}」面试记录？`, '确认删除', { type: 'warning' })
  await deleteInterview(row.id)
  ElMessage.success('已删除')
  await loadInterviews()
}

// ---------------- 加载 ----------------

async function loadResumes() {
  resumes.value = await listResumes()
}

async function loadInterviews() {
  interviews.value = await listInterviews()
}

const readyCount = computed(() => resumes.value.filter((r) => r.status === 2).length)

function sizeText(bytes: number) {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const scoreColor = (score: number | null) => {
  if (score == null) return '#94a3b8'
  if (score >= 85) return '#10b981'
  if (score >= 70) return '#f59e0b'
  return '#ef4444'
}

onMounted(async () => {
  loading.value = true
  try {
    const [r, i, k] = await Promise.all([listResumes(), listInterviews(), listKb()])
    resumes.value = r
    interviews.value = i
    kbs.value = k
  } finally {
    loading.value = false
  }
})

onUnmounted(() => unsubscribe?.())
</script>

<template>
  <div class="interview-home">
    <el-alert type="info" :closable="false" show-icon class="intro">
      <template #title>
        AI 模拟面试：上传简历 → AI 抽取档案 → 面试官逐轮追问（8~12 轮）→ 评分报告 →
        薄弱知识点一键出题
      </template>
      <div class="intro-sub">
        简历库与学习知识库完全隔离；题目从简历出发做深度追问，并核对你的回答与简历是否一致。
      </div>
    </el-alert>

    <el-tabs v-model="activeTab" class="tabs">
      <!-- ============ 简历库 ============ -->
      <el-tab-pane name="resume">
        <template #label>
          <span>简历库<el-badge v-if="resumes.length" :value="resumes.length" class="tab-badge" /></span>
        </template>

        <div class="toolbar">
          <el-upload
            :auto-upload="false"
            :show-file-list="false"
            accept=".pdf,.doc,.docx,.txt,.md"
            :on-change="handleUpload"
          >
            <el-button type="primary" :loading="loading">
              <el-icon style="margin-right: 4px"><UploadFilled /></el-icon>
              上传简历（PDF / Word）
            </el-button>
          </el-upload>
          <el-button @click="pasteVisible = true">
            <el-icon style="margin-right: 4px"><EditPen /></el-icon>
            粘贴简历文字
          </el-button>
          <span class="hint">已就绪 {{ readyCount }} 份 · 上传后 AI 自动抽取技能与项目经历</span>
        </div>

        <el-empty v-if="!resumes.length && !loading" description="还没有简历，先上传一份吧" />

        <el-table v-else :data="resumes" v-loading="loading" stripe class="table">
          <el-table-column prop="fileName" label="文件名" min-width="220" show-overflow-tooltip />
          <el-table-column label="类型" width="80">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ row.fileType || '-' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="90">
            <template #default="{ row }">{{ sizeText(row.fileSize) }}</template>
          </el-table-column>
          <el-table-column label="解析情况" min-width="200">
            <template #default="{ row }">
              <div v-if="parsing[row.id] !== undefined" class="parsing">
                <el-progress :percentage="parsing[row.id]" :stroke-width="10" />
              </div>
              <div v-else-if="row.status === 2" class="metric">
                <span>{{ row.charCount }} 字</span>
                <el-tag size="small" type="primary" effect="plain">技能 {{ row.skillCount }}</el-tag>
                <el-tag size="small" effect="plain">项目 {{ row.projectCount }}</el-tag>
                <el-tag v-if="row.riskCount" size="small" type="warning" effect="plain">
                  待核实 {{ row.riskCount }}
                </el-tag>
              </div>
              <span v-else-if="row.status === 3" class="err">{{ row.errorMsg || '解析失败' }}</span>
              <span v-else class="muted">等待解析</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="RESUME_STATUS[row.status as 0 | 1 | 2 | 3]?.type">
                {{ RESUME_STATUS[row.status as 0 | 1 | 2 | 3]?.text || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="290" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openProfile(row)">查看档案</el-button>
              <el-button link type="success" size="small" :disabled="row.status !== 2"
                         @click="openStart(row)">开始面试</el-button>
              <el-button link size="small" @click="doReparse(row)">重新解析</el-button>
              <el-button link type="danger" size="small" @click="doDeleteResume(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============ 面试记录 ============ -->
      <el-tab-pane name="history">
        <template #label>
          <span>面试记录<el-badge v-if="interviews.length" :value="interviews.length" class="tab-badge" /></span>
        </template>

        <el-empty v-if="!interviews.length" description="还没有面试记录，去简历库点「开始面试」" />

        <el-table v-else :data="interviews" stripe class="table">
          <el-table-column prop="jobTitle" label="目标岗位" min-width="180" show-overflow-tooltip />
          <el-table-column prop="resumeName" label="简历" min-width="160" show-overflow-tooltip />
          <el-table-column label="难度" width="80">
            <template #default="{ row }">{{ DIFFICULTY[row.difficulty as 1 | 2 | 3] }}</template>
          </el-table-column>
          <el-table-column label="进度" width="100">
            <template #default="{ row }">{{ row.turnCount }} / {{ row.maxTurns }} 轮</template>
          </el-table-column>
          <el-table-column label="综合得分" width="110">
            <template #default="{ row }">
              <span class="score" :style="{ color: scoreColor(row.totalScore) }">
                {{ row.totalScore == null ? '-' : row.totalScore }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="INTERVIEW_STATUS[row.status as 0 | 1 | 2 | 3]?.type">
                {{ INTERVIEW_STATUS[row.status as 0 | 1 | 2 | 3]?.text || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="createdAt" label="创建时间" width="170" />
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openInterview(row)">
                {{ row.status === 2 ? '看报告' : '继续面试' }}
              </el-button>
              <el-button link type="danger" size="small" @click="doDeleteInterview(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 粘贴简历 -->
    <el-dialog v-model="pasteVisible" title="粘贴简历文字" width="680px">
      <el-form label-width="90px">
        <el-form-item label="名称">
          <el-input v-model="pasteForm.fileName" placeholder="不填则为「手动录入简历.txt」" />
        </el-form-item>
        <el-form-item label="意向岗位">
          <el-input v-model="pasteForm.targetPosition" placeholder="如 Java 后端开发工程师" />
        </el-form-item>
        <el-form-item label="简历内容">
          <el-input v-model="pasteForm.content" type="textarea" :rows="14"
                    placeholder="直接把简历文字粘进来，AI 会抽取技能、项目经历与待核实点" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pasteVisible = false">取消</el-button>
        <el-button type="primary" :loading="loading" @click="submitPaste">开始解析</el-button>
      </template>
    </el-dialog>

    <!-- 开始面试 -->
    <el-dialog v-model="startVisible" title="开始模拟面试" width="560px">
      <el-form label-width="110px">
        <el-form-item label="简历">
          <el-input :model-value="startForm.resumeName" disabled />
        </el-form-item>
        <el-form-item label="目标岗位">
          <el-input v-model="startForm.jobTitle" placeholder="如 Java 后端开发工程师" />
        </el-form-item>
        <el-form-item label="难度">
          <el-radio-group v-model="startForm.difficulty">
            <el-radio-button :value="1">初级</el-radio-button>
            <el-radio-button :value="2">中级</el-radio-button>
            <el-radio-button :value="3">高级</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="面试轮数">
          <el-slider v-model="startForm.maxTurns" :min="5" :max="20" :step="1" show-stops />
          <span class="hint">推荐 8~12 轮；轮数越多追问越深，也越花时间和 token</span>
        </el-form-item>
        <el-form-item label="关联知识库">
          <el-select v-model="startForm.kbId" clearable placeholder="可选：用于面试后按薄弱点出题"
                     style="width: 100%">
            <el-option v-for="kb in kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="startVisible = false">取消</el-button>
        <el-button type="primary" :loading="starting" @click="doStart">开始面试</el-button>
      </template>
    </el-dialog>

    <!-- 简历档案 -->
    <el-drawer v-model="profileVisible" title="简历结构化档案" size="620px">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small" class="desc">
          <el-descriptions-item label="姓名">{{ detail.profile.name || '未识别' }}</el-descriptions-item>
          <el-descriptions-item label="工作年限">
            {{ detail.profile.years ? `${detail.profile.years} 年` : '未识别' }}
          </el-descriptions-item>
          <el-descriptions-item label="学历">{{ detail.profile.education || '-' }}</el-descriptions-item>
          <el-descriptions-item label="院校">{{ detail.profile.school || '-' }}</el-descriptions-item>
          <el-descriptions-item label="专业">{{ detail.profile.major || '-' }}</el-descriptions-item>
          <el-descriptions-item label="意向岗位">
            {{ detail.profile.targetPosition || '-' }}
          </el-descriptions-item>
        </el-descriptions>

        <div class="block">
          <div class="block-title">技能</div>
          <el-tag v-for="s in detail.profile.skills" :key="s" class="chip" effect="plain">{{ s }}</el-tag>
          <span v-if="!detail.profile.skills?.length" class="muted">未识别</span>
        </div>

        <div v-if="detail.profile.projects?.length" class="block">
          <div class="block-title">项目经历</div>
          <div v-for="(p, i) in detail.profile.projects" :key="i" class="project">
            <div class="project-head">
              <b>{{ p.name || `项目 ${i + 1}` }}</b>
              <span class="muted">{{ p.role }} {{ p.period }}</span>
            </div>
            <div v-if="p.techStack?.length" class="muted">技术栈：{{ p.techStack.join('、') }}</div>
            <div v-for="(h, hi) in p.highlights" :key="hi" class="bullet">· {{ h }}</div>
            <div v-if="p.evidence" class="evidence">原文佐证：{{ p.evidence }}</div>
          </div>
        </div>

        <div v-if="detail.profile.risks?.length" class="block">
          <div class="block-title warn">面试官会重点核实的点</div>
          <el-tag v-for="r in detail.profile.risks" :key="r" type="warning" class="chip" effect="light">
            {{ r }}
          </el-tag>
        </div>

        <el-collapse class="block">
          <el-collapse-item title="查看解析原文" name="raw">
            <pre class="raw">{{ detail.rawText }}</pre>
          </el-collapse-item>
        </el-collapse>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.interview-home {
  max-width: 1280px;
}

.intro {
  margin-bottom: 16px;
}

.intro-sub {
  font-size: 12.5px;
  color: #64748b;
  margin-top: 4px;
}

.tabs :deep(.el-tabs__header) {
  margin-bottom: 14px;
}

.tab-badge {
  margin-left: 6px;
  transform: translateY(-2px);
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.hint {
  font-size: 12.5px;
  color: #94a3b8;
}

.table {
  background: #fff;
  border-radius: 8px;
}

.metric {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: #475569;
}

.err {
  color: #ef4444;
  font-size: 12.5px;
}

.muted {
  color: #94a3b8;
  font-size: 12.5px;
}

.score {
  font-size: 17px;
  font-weight: 700;
}

.desc {
  margin-bottom: 16px;
}

.block {
  margin-bottom: 18px;
}

.block-title {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 8px;
}

.block-title.warn {
  color: #d97706;
}

.chip {
  margin: 0 6px 6px 0;
}

.project {
  border-left: 3px solid #e2e8f0;
  padding: 6px 0 6px 10px;
  margin-bottom: 10px;
}

.project-head {
  display: flex;
  gap: 10px;
  align-items: baseline;
}

.bullet {
  font-size: 12.5px;
  color: #475569;
  margin-top: 3px;
}

.evidence {
  font-size: 12px;
  color: #64748b;
  background: #f8fafc;
  border-radius: 4px;
  padding: 5px 8px;
  margin-top: 5px;
}

.raw {
  white-space: pre-wrap;
  font-size: 12.5px;
  color: #475569;
  max-height: 340px;
  overflow: auto;
  margin: 0;
}
</style>
