<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  activateProvider, createProvider, deleteProvider, getPrompt, listPromptGroups, listProviders,
  listRoutes, rollbackPrompt, savePrompt, saveRoute, testProvider, updateProvider, VENDOR_PRESETS,
  type PromptDetail, type PromptGroup, type Provider, type RouteItem,
} from '@/api/ai'

const tab = ref('provider')

// ---------------- 厂商 ----------------
const providers = ref<Provider[]>([])
const loading = ref(false)
const testing = ref<number | null>(null)
const dialogVisible = ref(false)
const saving = ref(false)
const editing = ref<Provider | null>(null)
const form = ref<Record<string, any>>({})

const chatProviders = computed(() =>
  providers.value.filter((p) => p.capability.includes('CHAT') && p.enabled === 1 && p.locked !== 1))

const VENDOR_LABEL: Record<string, string> = {
  deepseek: 'DeepSeek', qwen: '通义千问', zhipu: '智谱', moonshot: '月之暗面',
  openai: 'OpenAI', claude: 'Claude', ollama: 'Ollama', xfyun: '讯飞',
  xfyun_lfasr: '讯飞语音转写', aliyun: '阿里云', local: '本地', mock: 'Mock', custom: '自定义',
}

const CAP_LABEL: Record<string, string> = {
  CHAT: '对话', EMBED: '向量化', ASR: '语音识别', OCR: '图片识别',
}

function capLabel(cap: string) {
  return cap.split(',').map((c) => CAP_LABEL[c.trim()] || c.trim()).join(' / ')
}

function openCreate() {
  editing.value = null
  form.value = {
    name: '', vendor: 'deepseek', protocol: 'openai-compatible', baseUrl: '', model: '',
    apiKey: '', apiSecret: '', appId: '',
    capability: 'CHAT', enabled: 1, priority: 100, remark: '',
    temperature: 0.7, temperatureStr: '0.7', maxTokens: 8192,
    priceIn: 0, priceOut: 0,
  }
  dialogVisible.value = true
}

/**
 * 讯飞「语音听写（流式版）」只有这三个官方端点，没有自定义的可能。
 * 所以对讯飞用下拉而不是自由输入 —— 讯飞文档里把地址写成 `ws[s]://…`
 * （表示 ws 或 wss），很多人会连方括号一起复制进来，
 * 结果 URI 解析直接报 `Illegal character in scheme name at index 2`。
 */
const XFYUN_ENDPOINTS = [
  { value: 'wss://iat-api.xfyun.cn/v2/iat', label: '中英文（推荐）· iat-api.xfyun.cn' },
  { value: 'wss://ws-api.xfyun.cn/v2/iat', label: '中英文（备用）· ws-api.xfyun.cn' },
  { value: 'wss://iat-niche-api.xfyun.cn/v2/iat', label: '小语种 · iat-niche-api.xfyun.cn' },
]

/**
 * 讯飞这类厂商要「三元组」：APPID + APIKey + APISecret。
 * 只给一个 API Key 输入框会让人以为填一个就够了 —— 实际调不通。
 *
 * 语音转写（面经用的长音频接口）同样是三件套，所以一并算进 needsTriple。
 */
const needsTriple = computed(
  () => form.value.vendor === 'xfyun' || form.value.vendor === 'xfyun_lfasr',
)

/** 只有语音听写需要选端点；语音转写的地址是固定的，选了反而会被改坏 */
const isIat = computed(() => form.value.vendor === 'xfyun')

function applyPreset(vendor: string) {
  const preset = VENDOR_PRESETS.find((p) => p.vendor === vendor)
  if (preset) {
    form.value.protocol = preset.protocol
    form.value.baseUrl = preset.baseUrl
    form.value.model = preset.model
    form.value.capability = preset.capability
    if (!form.value.name) form.value.name = preset.name
  }
}

function openEdit(p: Provider) {
  editing.value = p
  form.value = {
    name: p.name, vendor: p.vendor, protocol: p.protocol, baseUrl: p.baseUrl, model: p.model,
    apiKey: '', apiSecret: '', appId: p.appId, capability: p.capability,
    enabled: p.enabled, priority: p.priority, remark: p.remark,
    temperatureStr: String(p.extraParams?.temperature ?? 0.7),
    maxTokens: Number(p.extraParams?.max_tokens ?? 8192),
    priceIn: Number(p.extraParams?.price_in ?? 0),
    priceOut: Number(p.extraParams?.price_out ?? 0),
  }
  dialogVisible.value = true
}

async function submit() {
  if (!form.value.name?.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.value.name,
      vendor: form.value.vendor,
      protocol: form.value.protocol,
      baseUrl: form.value.baseUrl,
      model: form.value.model,
      apiKey: form.value.apiKey || undefined,
      apiSecret: form.value.apiSecret || undefined,
      appId: form.value.appId,
      capability: form.value.capability,
      enabled: form.value.enabled,
      priority: form.value.priority,
      remark: form.value.remark,
      extraParams: {
        temperature: Number(form.value.temperatureStr) || 0.7,
        max_tokens: Number(form.value.maxTokens) || 8192,
        price_in: Number(form.value.priceIn) || 0,
        price_out: Number(form.value.priceOut) || 0,
      },
    }
    if (editing.value) {
      await updateProvider(editing.value.id, payload)
      ElMessage.success('已保存')
    } else {
      await createProvider(payload)
      ElMessage.success('已新增')
    }
    dialogVisible.value = false
    await loadProviders()
  } finally {
    saving.value = false
  }
}

async function doTest(p: Provider) {
  testing.value = p.id
  try {
    const res = await testProvider(p.id)
    if (res.ok) {
      ElMessage.success(`${p.name}：${res.message}`)
    } else {
      ElMessage.error(`${p.name}：${res.message}`)
    }
    await loadProviders()
  } finally {
    testing.value = null
  }
}

async function doActivate(p: Provider) {
  await activateProvider(p.id)
  ElMessage.success(`已切换到「${p.name}」`)
  await Promise.all([loadProviders(), loadRoutes()])
}

async function doDelete(p: Provider) {
  await ElMessageBox.confirm(`删除厂商「${p.name}」？`, '删除', { type: 'warning' })
  await deleteProvider(p.id)
  ElMessage.success('已删除')
  await loadProviders()
}

// ---------------- 任务路由 ----------------
const routes = ref<RouteItem[]>([])

async function changeRoute(item: RouteItem, providerId: number | null) {
  await saveRoute({
    taskType: item.taskType, providerId,
    fallbackProviderId: item.fallbackProviderId, remark: item.remark,
  })
  ElMessage.success(`${item.taskName} 已指向新模型`)
  await loadRoutes()
}

// ---------------- Prompt ----------------
const promptGroups = ref<PromptGroup[]>([])
const promptDialog = ref(false)
const promptDetail = ref<PromptDetail | null>(null)
const promptContent = ref('')
const promptRemark = ref('')
const promptSaving = ref(false)
const historyVisible = ref(false)
const historyGroup = ref<PromptGroup | null>(null)

async function openPrompt(group: PromptGroup) {
  const active = group.versions.find((v) => v.isActive === 1) || group.versions[0]
  promptDetail.value = await getPrompt(active.id)
  promptContent.value = promptDetail.value.content
  promptRemark.value = ''
  promptDialog.value = true
}

async function doSavePrompt() {
  if (!promptDetail.value) return
  promptSaving.value = true
  try {
    const saved = await savePrompt(promptDetail.value.id, promptContent.value, promptRemark.value)
    ElMessage.success(`已保存为 v${saved.version}（旧版本仍保留，可回滚）`)
    promptDialog.value = false
    await loadPrompts()
  } finally {
    promptSaving.value = false
  }
}

function openHistory(group: PromptGroup) {
  historyGroup.value = group
  historyVisible.value = true
}

async function doRollback(versionId: number, version: number) {
  await ElMessageBox.confirm(
    `回滚到 v${version}？会生成一个新版本（内容等于 v${version}），历史链条不会断。`,
    '回滚', { type: 'warning' },
  )
  const saved = await rollbackPrompt(versionId)
  ElMessage.success(`已回滚，新版本 v${saved.version}`)
  historyVisible.value = false
  await loadPrompts()
}

// ---------------- 加载 ----------------
async function loadProviders() {
  providers.value = await listProviders()
}

async function loadRoutes() {
  routes.value = await listRoutes()
}

async function loadPrompts() {
  promptGroups.value = await listPromptGroups()
}

onMounted(async () => {
  loading.value = true
  try {
    await Promise.all([loadProviders(), loadRoutes(), loadPrompts()])
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-head">
      <div>
        <h2>AI 配置</h2>
        <div class="sub">厂商、任务路由与 Prompt 模板 —— API Key 加密存储，界面上只显示掩码</div>
      </div>
      <el-button v-if="tab === 'provider'" type="primary" :icon="'Plus'" @click="openCreate">
        新增厂商
      </el-button>
    </div>

    <el-tabs v-model="tab">
      <!-- ============ 厂商 ============ -->
      <el-tab-pane label="厂商" name="provider">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 14px"
          title="锁定项不能删除或切换"
          description="本地向量模型与 OCR 是已入库数据的固定依赖，换了会导致向量不可比、需要整库重建。"
        />

        <el-card v-for="p in providers" :key="p.id" shadow="never" class="p-card">
          <div class="p-head">
            <span class="p-name">{{ p.name }}</span>
            <el-tag size="small" effect="plain">{{ VENDOR_LABEL[p.vendor] || p.vendor }}</el-tag>
            <el-tag size="small" type="info" effect="plain">{{ capLabel(p.capability) }}</el-tag>
            <el-tag v-if="p.locked === 1" size="small" type="warning">🔒 锁定</el-tag>
            <el-tag v-if="p.isActive === 1" size="small" type="success">当前使用</el-tag>
            <el-tag v-if="p.enabled === 0" size="small" type="danger">已禁用</el-tag>
            <div style="flex: 1"></div>

            <el-tooltip v-if="p.lastTestAt" :content="p.lastTestMsg" placement="top">
              <el-tag size="small" :type="p.lastTestOk === 1 ? 'success' : 'danger'" effect="plain">
                {{ p.lastTestOk === 1 ? '测试通过' : '测试失败' }}
              </el-tag>
            </el-tooltip>

            <el-button size="small" :loading="testing === p.id" @click="doTest(p)">测试连通</el-button>
            <el-button
              v-if="p.isActive !== 1 && p.locked !== 1"
              size="small"
              type="primary"
              :disabled="p.enabled === 0"
              @click="doActivate(p)"
            >
              设为当前
            </el-button>
            <el-button size="small" :icon="'Edit'" @click="openEdit(p)">编辑</el-button>
            <el-button
              v-if="p.locked !== 1"
              size="small"
              type="danger"
              :icon="'Delete'"
              @click="doDelete(p)"
            />
          </div>

          <div class="p-meta">
            <span>模型：<b>{{ p.model || '-' }}</b></span>
            <span>地址：<span class="mono">{{ p.baseUrl || '-' }}</span></span>
            <span>
              Key：
              <b v-if="p.hasApiKey" class="mono">{{ p.apiKeyMasked }}</b>
              <b v-else style="color:#ef4444">未配置</b>
            </span>
            <span v-if="p.hasApiSecret">Secret：<b class="mono">{{ p.apiSecretMasked }}</b></span>
            <span>优先级：{{ p.priority }}</span>
          </div>
          <div v-if="p.remark" class="p-remark">{{ p.remark }}</div>
        </el-card>
      </el-tab-pane>

      <!-- ============ 任务路由 ============ -->
      <el-tab-pane label="任务路由" name="route">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 14px"
          title="按任务分配模型 —— 出题用强模型，分类和打标用便宜模型"
          description="不配置时按「当前使用」的厂商走。配置了就以这里为准。"
        />

        <el-table :data="routes" size="default">
          <el-table-column prop="taskName" label="任务" width="140" />
          <el-table-column prop="description" label="说明" min-width="240" show-overflow-tooltip />
          <el-table-column label="使用模型" width="240">
            <template #default="{ row }">
              <el-select
                :model-value="row.providerId"
                placeholder="跟随「当前使用」"
                clearable
                size="small"
                style="width: 100%"
                @change="(v: number | null) => changeRoute(row, v)"
              >
                <el-option
                  v-for="p in providers.filter((x) => x.enabled === 1)"
                  :key="p.id"
                  :value="p.id"
                  :label="`${p.name}（${p.model}）`"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="当前指向" min-width="160">
            <template #default="{ row }">
              <span v-if="row.providerName">{{ row.providerName }}</span>
              <span v-else style="color:#94a3b8">跟随当前使用</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============ Prompt ============ -->
      <el-tab-pane label="Prompt 模板" name="prompt">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 14px"
          title="改这里的效果远大于改代码"
          description="保存会生成新版本，旧版本保留可随时回滚。{变量} 由系统注入，不要删掉。"
        />

        <el-card v-for="g in promptGroups" :key="g.code" shadow="never" class="g-card">
          <div class="g-head">
            <span class="g-name">{{ g.name }}</span>
            <el-tag size="small" effect="plain" class="mono">{{ g.code }}</el-tag>
            <el-tag size="small" type="success" effect="plain">当前 v{{ g.activeVersion }}</el-tag>
            <el-tag size="small" type="info" effect="plain">共 {{ g.versionCount }} 个版本</el-tag>
            <div style="flex: 1"></div>
            <el-button size="small" @click="openHistory(g)">历史版本</el-button>
            <el-button size="small" type="primary" :icon="'Edit'" @click="openPrompt(g)">编辑</el-button>
          </div>
          <div v-if="g.remark" class="g-remark">{{ g.remark }}</div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 厂商编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editing ? `编辑：${editing.name}` : '新增 AI 厂商'"
      width="640px"
      top="6vh"
    >
      <el-form label-width="96px">
        <el-form-item label="厂商类型">
          <el-select v-model="form.vendor" style="width: 100%" @change="applyPreset">
            <el-option v-for="p in VENDOR_PRESETS" :key="p.vendor" :value="p.vendor" :label="p.name" />
            <el-option value="custom" label="自定义" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="展示用，如「DeepSeek 官方」" />
        </el-form-item>
        <el-form-item label="协议">
          <el-radio-group v-model="form.protocol">
            <el-radio-button value="openai-compatible">OpenAI 兼容</el-radio-button>
            <el-radio-button value="ollama">Ollama</el-radio-button>
            <el-radio-button value="custom">自定义</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="isIat" label="服务端点">
          <el-select v-model="form.baseUrl" style="width: 100%">
            <el-option v-for="e in XFYUN_ENDPOINTS" :key="e.value" :value="e.value" :label="e.label" />
          </el-select>
        </el-form-item>
        <el-form-item v-else label="Base URL">
          <el-input v-model="form.baseUrl" placeholder="https://api.deepseek.com" />
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="form.model" placeholder="deepseek-chat" />
        </el-form-item>
        <el-form-item :label="needsTriple ? 'APIKey' : 'API Key'">
          <el-input
            v-model="form.apiKey"
            type="password"
            show-password
            :placeholder="editing?.hasApiKey ? `已配置（${editing.apiKeyMasked}），留空表示不改动` : (needsTriple ? '32 位字符串' : 'sk-...')"
          />
        </el-form-item>

        <!-- 讯飞是「三元组」，一个 API Key 不够，必须有地方填另两个值 -->
        <template v-if="needsTriple">
          <el-alert type="warning" :closable="false" show-icon class="triple-tip">
            <template #title>讯飞需要 <b>三个</b> 值，缺一不可</template>
            <div class="triple-tip-body">
              在讯飞控制台「应用详情页」拿 <b>APPID</b>、<b>APIKey</b>、<b>APISecret</b>：
              上面的 APIKey 填 APIKey，下面两栏填 APPID 与 APISecret。<br />
              还要确认已开通 <b>「语音听写（流式版）」</b> 并领取免费额度，
              否则会报 11200 / 10005。填完记得把「启用」打开。
            </div>
          </el-alert>
          <el-form-item label="APPID">
            <el-input v-model="form.appId" placeholder="8 位十六进制，如 5f3a1b2c" />
          </el-form-item>
          <el-form-item label="APISecret">
            <el-input
              v-model="form.apiSecret"
              type="password"
              show-password
              :placeholder="editing?.hasApiSecret ? `已配置（${editing.apiSecretMasked}），留空表示不改动` : '32 位字符串'"
            />
          </el-form-item>
        </template>
        <el-form-item label="能力">
          <el-checkbox-group v-model="(form.capabilityList as string[])" v-if="false" />
          <el-input
            v-model="form.capability"
            placeholder="CHAT / EMBED / ASR / OCR，多个用逗号分隔"
          />
        </el-form-item>
        <el-form-item label="优先级">
          <el-input-number v-model="form.priority" :min="1" :max="999" />
          <span class="hint-inline">数字越小越优先，用于同能力多厂商时的降级顺序</span>
        </el-form-item>

        <el-divider content-position="left">调用参数与计价</el-divider>

        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="temperature" label-width="100px">
              <el-input v-model="form.temperatureStr" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="max_tokens" label-width="100px">
              <el-input-number v-model="form.maxTokens" :min="256" :max="65536" :step="1024" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="启用" label-width="60px">
              <el-switch v-model="form.enabled" :active-value="1" :inactive-value="0" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="输入单价" label-width="100px">
              <el-input-number v-model="form.priceIn" :min="0" :precision="2" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="输出单价" label-width="100px">
              <el-input-number v-model="form.priceOut" :min="0" :precision="2" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <div class="hint-block">
          单价单位「元 / 百万 token」，用来在统计页算成本。不知道可以不填（成本显示 0）。
        </div>

        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- Prompt 编辑 -->
    <el-dialog
      v-model="promptDialog"
      :title="`编辑 Prompt：${promptDetail?.name || ''}（当前 v${promptDetail?.version}）`"
      width="900px"
      top="4vh"
    >
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
        title="保存会生成新版本"
        description="旧版本不会被覆盖，随时可以从「历史版本」回滚。"
      />
      <el-input v-model="promptContent" type="textarea" :rows="22" class="mono-input" />
      <el-input
        v-model="promptRemark"
        placeholder="这次改了什么？（可选，便于日后回滚时判断）"
        style="margin-top: 10px"
      />
      <template #footer>
        <el-button @click="promptDialog = false">取消</el-button>
        <el-button type="primary" :loading="promptSaving" @click="doSavePrompt">保存为新版本</el-button>
      </template>
    </el-dialog>

    <!-- Prompt 历史 -->
    <el-dialog v-model="historyVisible" :title="`${historyGroup?.name} 的历史版本`" width="560px">
      <el-table :data="historyGroup?.versions || []" size="small">
        <el-table-column label="版本" width="80">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.isActive === 1" size="small" type="success">当前</el-tag>
            <span v-else style="color:#cbd5e1">历史</span>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="说明" min-width="140" show-overflow-tooltip />
        <el-table-column prop="contentLength" label="字数" width="70" />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button
              v-if="row.isActive !== 1"
              link
              type="primary"
              size="small"
              @click="doRollback(row.id, row.version)"
            >
              回滚
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.p-card {
  margin-bottom: 12px;
}

.p-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.p-name {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}

.p-meta {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: #64748b;
  background: #f8fafc;
  border-radius: 6px;
  padding: 8px 12px;
}

.p-meta b {
  color: #334155;
}

.p-remark {
  font-size: 12.5px;
  color: #94a3b8;
  margin-top: 6px;
}

.g-card {
  margin-bottom: 10px;
}

.g-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.g-name {
  font-size: 14.5px;
  font-weight: 600;
  color: #1e293b;
}

.g-remark {
  font-size: 12.5px;
  color: #94a3b8;
  margin-top: 6px;
}

.hint-inline {
  font-size: 12px;
  color: #94a3b8;
  margin-left: 10px;
}

.hint-block {
  font-size: 12px;
  color: #94a3b8;
  margin: -6px 0 14px 96px;
}

/* 讯飞三元组提示：单独占一行，别挤在 label 右边 */
.triple-tip {
  margin: -4px 0 16px 96px;
  width: calc(100% - 96px);
}

.triple-tip-body {
  font-size: 12px;
  line-height: 1.7;
  color: #92400e;
}

.mono-input :deep(textarea) {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12.5px;
  line-height: 1.7;
}

.mono {
  font-family: Consolas, monospace;
}
</style>
